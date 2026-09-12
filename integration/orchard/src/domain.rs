//! Candidate domain-bound authorization, NOT an activated network upgrade.
//! All expected context comes from the caller's independently trusted descriptor.
//! Legacy codecs and stored ledgers are unchanged; no implicit fallback exists.
use orchard::bundle::{Authorization, TxVersion};
use orchard::circuit::VerifyingKey;
use orchard::Bundle;
use sha2::{Digest, Sha256};

use crate::wire::{self, Decoded, SignedBundle};
use crate::{Context, CIRCUIT, NETWORK, VERSION};

pub const DOMAIN_SIZE: usize = 79;
pub const PREFIX_SIZE: usize = 40;
pub const MAX_TRANSACTION_SIZE: usize = PREFIX_SIZE + wire::MAX_ENVELOPE_SIZE;
const DOMAIN_MAGIC: &[u8; 8] = b"ZVDOM001";
const TX_MAGIC: &[u8; 8] = b"ZVTXB001";
const SUITE: u16 = 1; // FixedPostNu6_2, Orchard V2, V5 bundle commitment

type Hash = [u8; 32];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Error {
    Encoding,
    Domain,
    Metadata,
    Authorization,
}
impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "domain authorization rejected: {self:?}")
    }
}
impl std::error::Error for Error {}

/// Only local/dev and test descriptors are recognized. There is no mainnet mode.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum NetworkKind {
    Development = 1,
    Test = 2,
}

/// Immutable public identity. Genesis and rules commitments are independent of
/// signatures and of this descriptor's ID: their definitions MUST avoid cycles.
/// An epoch distinguishes rule sets; it does not authorize automatic activation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Domain {
    encoded: [u8; DOMAIN_SIZE],
}
impl Domain {
    pub fn new(kind: NetworkKind, genesis: Hash, rules: Hash, epoch: u32) -> Result<Self, Error> {
        if genesis == [0; 32] || rules == [0; 32] || epoch == 0 {
            return Err(Error::Domain);
        }
        let mut encoded = [0; DOMAIN_SIZE];
        encoded[..8].copy_from_slice(DOMAIN_MAGIC);
        encoded[8] = kind as u8;
        encoded[9..41].copy_from_slice(&genesis);
        encoded[41..73].copy_from_slice(&rules);
        encoded[73..77].copy_from_slice(&epoch.to_be_bytes());
        encoded[77..].copy_from_slice(&SUITE.to_be_bytes());
        Ok(Self { encoded })
    }

    pub fn decode(raw: &[u8]) -> Result<Self, Error> {
        if raw.len() != DOMAIN_SIZE || &raw[..8] != DOMAIN_MAGIC || raw[77..] != SUITE.to_be_bytes()
        {
            return Err(Error::Encoding);
        }
        let kind = match raw[8] {
            1 => NetworkKind::Development,
            2 => NetworkKind::Test,
            _ => return Err(Error::Domain),
        };
        let genesis = raw[9..41].try_into().map_err(|_| Error::Encoding)?;
        let rules = raw[41..73].try_into().map_err(|_| Error::Encoding)?;
        let epoch = u32::from_be_bytes(raw[73..77].try_into().map_err(|_| Error::Encoding)?);
        Self::new(kind, genesis, rules, epoch)
    }

    pub fn as_bytes(&self) -> &[u8; DOMAIN_SIZE] {
        &self.encoded
    }

    pub fn id(&self) -> Hash {
        let mut h = Sha256::new();
        h.update(b"ZEVUNE-DOMAIN\0\x01");
        h.update(self.encoded);
        h.finalize().into()
    }

    /// Primitive transcript helper. The commitment must be computed by Orchard
    /// from the actual bundle; an arbitrary 32-byte value is NOT proof of that.
    pub fn digest_for_commitment(
        &self,
        expiry: u64,
        fee: u64,
        commitment: Hash,
    ) -> Result<Hash, Error> {
        if expiry == 0 || fee > i64::MAX as u64 {
            return Err(Error::Metadata);
        }
        let mut h = Sha256::new();
        h.update(b"ZEVUNE-TX-SIGHASH\0\x01");
        h.update(self.id());
        h.update(expiry.to_be_bytes());
        h.update(fee.to_be_bytes());
        h.update(commitment);
        Ok(h.finalize().into())
    }

    /// Call before apply_signatures. Wrapping an old signature does not convert it.
    pub fn signing_digest<A: Authorization>(
        &self,
        bundle: &Bundle<A, i64>,
        context: &Context,
    ) -> Result<Hash, Error> {
        if context.network != NETWORK
            || bundle.bundle_version() != VERSION
            || bundle.flags() != &VERSION.default_flags()
            || context.fee > i64::MAX as u64
            || *bundle.value_balance() != context.fee as i64
        {
            return Err(Error::Metadata);
        }
        let commitment = bundle
            .commitment(TxVersion::V5)
            .map_err(|_| Error::Metadata)?
            .into();
        self.digest_for_commitment(context.expiry_height, context.fee, commitment)
    }
}

/// Reuse only the bounded legacy BODY SERIALIZATION, never its signing rules.
/// Encoding/decoding is not proof or signature verification.
pub fn encode(bundle: &SignedBundle, context: &Context, domain: &Domain) -> Result<Vec<u8>, Error> {
    let body = wire::encode(bundle, context).map_err(|_| Error::Encoding)?;
    let mut raw = Vec::with_capacity(PREFIX_SIZE + body.len());
    raw.extend_from_slice(TX_MAGIC);
    raw.extend_from_slice(&domain.id());
    raw.extend_from_slice(&body);
    Ok(raw)
}

pub fn decode(raw: &[u8], expected: &Domain) -> Result<Decoded, Error> {
    if raw.len() < PREFIX_SIZE + wire::HEADER_SIZE
        || raw.len() > MAX_TRANSACTION_SIZE
        || &raw[..8] != TX_MAGIC
    {
        return Err(Error::Encoding);
    }
    if raw[8..PREFIX_SIZE] != expected.id() {
        return Err(Error::Domain);
    }
    wire::decode(&raw[PREFIX_SIZE..]).map_err(|_| Error::Encoding)
}

/// Proof and signatures ONLY. No ledger, finality, freshness or issuance approval.
/// No cache is shared with legacy signatures or other network domains.
pub struct Verifier {
    expected: Domain,
    key: VerifyingKey,
}
impl Verifier {
    pub fn new(expected: Domain) -> Self {
        Self {
            expected,
            key: VerifyingKey::build(CIRCUIT),
        }
    }

    pub fn verify(&self, raw: &[u8]) -> Result<Hash, Error> {
        let decoded = decode(raw, &self.expected)?;
        let digest = self
            .expected
            .signing_digest(&decoded.bundle, &decoded.context)?;
        for action in decoded.bundle.actions().iter() {
            action
                .rk()
                .verify(&digest, action.authorization())
                .map_err(|_| Error::Authorization)?;
        }
        decoded
            .bundle
            .binding_validating_key()
            .verify(&digest, decoded.bundle.authorization().binding_signature())
            .map_err(|_| Error::Authorization)?;
        decoded
            .bundle
            .verify_proof(&self.key)
            .map_err(|_| Error::Authorization)?;
        Ok(Sha256::digest(raw).into())
    }
}
