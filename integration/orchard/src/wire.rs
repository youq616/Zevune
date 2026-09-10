//! Bounded EXPERIMENTAL local wire format. Not a mainnet transaction protocol.
//! Structural decoding never establishes a proof or committed ledger membership.
use std::collections::BTreeSet;
use std::fmt;

use nonempty::NonEmpty;
use orchard::bundle::Authorized;
use orchard::circuit::VerifyingKey;
use orchard::note::{ExtractedNoteCommitment, Nullifier, TransmittedNoteCiphertext};
use orchard::primitives::redpallas::{Binding, Signature, SpendAuth, VerificationKey};
use orchard::value::ValueCommitment;
use orchard::{Action, Anchor, Bundle, Proof};
use sha2::{Digest, Sha256};

use crate::{signing_digest, Context, CIRCUIT, MAX_ACTIONS, NETWORK, VERSION};

pub const MAGIC: &[u8; 8] = b"ZVORLAB1";
pub const HEADER_SIZE: usize = 66;
pub const ACTION_SIZE: usize = 884;
pub const TAIL_SIZE: usize = 68;
pub const MAX_ENVELOPE_SIZE: usize =
    HEADER_SIZE + MAX_ACTIONS * ACTION_SIZE + Proof::expected_proof_size(MAX_ACTIONS) + TAIL_SIZE;

pub type SignedBundle = Bundle<Authorized, i64>;

// Do not derive Debug: careless logging must not dump arbitrary wire material.
pub struct Decoded {
    pub bundle: SignedBundle,
    pub context: Context,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WireError {
    Bounds,
    Encoding,
    Policy,
    Element,
    Authorization,
}
impl fmt::Display for WireError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Orchard local wire check failed: {self:?}")
    }
}
impl std::error::Error for WireError {}

fn size(n: usize) -> usize {
    HEADER_SIZE + n * ACTION_SIZE + Proof::expected_proof_size(n) + TAIL_SIZE
}

fn policy(bundle: &SignedBundle, context: &Context) -> Result<(), WireError> {
    if context.network != NETWORK
        || context.expiry_height == 0
        || context.fee > i64::MAX as u64
        || *bundle.value_balance() != context.fee as i64
        || bundle.bundle_version() != VERSION
        || bundle.flags() != &VERSION.default_flags()
    {
        return Err(WireError::Policy);
    }
    let n = bundle.actions().len();
    if !(2..=MAX_ACTIONS).contains(&n) {
        return Err(WireError::Bounds);
    }
    if bundle.authorization().proof().as_ref().len() != Proof::expected_proof_size(n) {
        return Err(WireError::Encoding);
    }
    let mut nfs = BTreeSet::new();
    let mut cms = BTreeSet::new();
    for action in bundle.actions().iter() {
        if !nfs.insert(action.nullifier().to_bytes()) || !cms.insert(action.cmx().to_bytes()) {
            return Err(WireError::Policy);
        }
    }
    Ok(())
}

/// Encode all authorizing bytes without changing the M4 signing transcript.
/// Only one implicit network, circuit version and flags combination is supported.
/// A future network format MUST have a separately reviewed activation/version rule.
pub fn encode(bundle: &SignedBundle, context: &Context) -> Result<Vec<u8>, WireError> {
    policy(bundle, context)?;
    let mut out = Vec::with_capacity(size(bundle.actions().len()));
    out.extend_from_slice(MAGIC);
    out.extend_from_slice(&context.expiry_height.to_be_bytes());
    out.extend_from_slice(&context.fee.to_be_bytes());
    out.extend_from_slice(&bundle.value_balance().to_be_bytes());
    out.extend_from_slice(&bundle.anchor().to_bytes());
    out.push(bundle.actions().len() as u8);
    out.push(bundle.flag_byte());
    for a in bundle.actions().iter() {
        out.extend_from_slice(&a.cv_net().to_bytes());
        out.extend_from_slice(&a.nullifier().to_bytes());
        out.extend_from_slice(&<[u8; 32]>::from(a.rk()));
        out.extend_from_slice(&a.cmx().to_bytes());
        out.extend_from_slice(&a.encrypted_note().epk_bytes);
        out.extend_from_slice(&a.encrypted_note().enc_ciphertext);
        out.extend_from_slice(&a.encrypted_note().out_ciphertext);
        out.extend_from_slice(&<[u8; 64]>::from(a.authorization()));
    }
    let proof = bundle.authorization().proof().as_ref();
    out.extend_from_slice(&(proof.len() as u32).to_be_bytes());
    out.extend_from_slice(proof);
    out.extend_from_slice(&<[u8; 64]>::from(
        bundle.authorization().binding_signature(),
    ));
    Ok(out)
}

struct Reader<'a> {
    raw: &'a [u8],
    pos: usize,
}
impl<'a> Reader<'a> {
    fn slice(&mut self, n: usize) -> Result<&'a [u8], WireError> {
        let end = self.pos.checked_add(n).ok_or(WireError::Bounds)?;
        let result = self.raw.get(self.pos..end).ok_or(WireError::Encoding)?;
        self.pos = end;
        Ok(result)
    }
    fn array<const N: usize>(&mut self) -> Result<[u8; N], WireError> {
        self.slice(N)?.try_into().map_err(|_| WireError::Encoding)
    }
}

/// Validate length before allocating and delegate canonical field/point checks to
/// the upstream library. No proof, key or ciphertext length comes from an
/// unchecked peer-controlled allocation size.
pub fn decode(raw: &[u8]) -> Result<Decoded, WireError> {
    if raw.len() > MAX_ENVELOPE_SIZE {
        return Err(WireError::Bounds);
    }
    if raw.len() < HEADER_SIZE || raw.get(..8) != Some(MAGIC.as_slice()) {
        return Err(WireError::Encoding);
    }
    let n = raw[64] as usize;
    if !(2..=MAX_ACTIONS).contains(&n) {
        return Err(WireError::Bounds);
    }
    if raw[65]
        != VERSION
            .default_flags()
            .to_byte(VERSION)
            .ok_or(WireError::Policy)?
    {
        return Err(WireError::Policy);
    }
    if raw.len() != size(n) {
        return Err(WireError::Encoding);
    }
    let mut r = Reader { raw, pos: 8 };
    let expiry = u64::from_be_bytes(r.array()?);
    let fee = u64::from_be_bytes(r.array()?);
    let balance = i64::from_be_bytes(r.array()?);
    if expiry == 0 || fee > i64::MAX as u64 || balance < 0 || balance as u64 != fee {
        return Err(WireError::Policy);
    }
    let anchor =
        Option::<Anchor>::from(Anchor::from_bytes(r.array()?)).ok_or(WireError::Element)?;
    r.slice(2)?;
    let mut actions = Vec::with_capacity(n);
    for _ in 0..n {
        let cv = Option::<ValueCommitment>::from(ValueCommitment::from_bytes(&r.array()?))
            .ok_or(WireError::Element)?;
        let nf = Option::<Nullifier>::from(Nullifier::from_bytes(&r.array()?))
            .ok_or(WireError::Element)?;
        let rk = VerificationKey::<SpendAuth>::try_from(r.array::<32>()?)
            .map_err(|_| WireError::Element)?;
        let cm = Option::<ExtractedNoteCommitment>::from(ExtractedNoteCommitment::from_bytes(
            &r.array()?,
        ))
        .ok_or(WireError::Element)?;
        let ciphertext = TransmittedNoteCiphertext {
            epk_bytes: r.array()?,
            enc_ciphertext: r.array()?,
            out_ciphertext: r.array()?,
        };
        let signature = Signature::<SpendAuth>::from(r.array::<64>()?);
        actions.push(
            Action::from_parts(nf, rk, cm, ciphertext, cv, signature)
                .map_err(|_| WireError::Element)?,
        );
    }
    let proof_len = u32::from_be_bytes(r.array()?) as usize;
    if proof_len != Proof::expected_proof_size(n) {
        return Err(WireError::Encoding);
    }
    let proof = Proof::new(r.slice(proof_len)?.to_vec());
    let binding = Signature::<Binding>::from(r.array::<64>()?);
    if r.pos != raw.len() {
        return Err(WireError::Encoding);
    }
    let bundle = Bundle::try_from_parts(
        NonEmpty::from_vec(actions).ok_or(WireError::Bounds)?,
        VERSION.default_flags(),
        balance,
        anchor,
        Authorized::from_parts(proof, binding),
        VERSION,
    )
    .map_err(|_| WireError::Encoding)?;
    let context = Context {
        network: NETWORK.into(),
        expiry_height: expiry,
        fee,
    };
    policy(&bundle, &context)?;
    if encode(&bundle, &context)? != raw {
        return Err(WireError::Encoding);
    }
    Ok(Decoded { bundle, context })
}

pub fn payload_digest(raw: &[u8]) -> [u8; 32] {
    Sha256::digest(raw).into()
}

/// Reuses a fixed public verifying key. This is STATELESS authorization only.
/// The caller must separately validate expiry, trusted roots, prior spends,
/// issuance, fees and atomic state updates against a committed ledger snapshot.
/// Individual upstream signature verification and SingleVerifier avoid a new
/// randomized signature-batch acceptance decision at this process boundary.
pub struct AuthorizationVerifier {
    key: VerifyingKey,
}
impl Default for AuthorizationVerifier {
    fn default() -> Self {
        Self::new()
    }
}
impl AuthorizationVerifier {
    pub fn new() -> Self {
        Self {
            key: VerifyingKey::build(CIRCUIT),
        }
    }
    pub fn verify(&self, raw: &[u8]) -> Result<[u8; 32], WireError> {
        let decoded = decode(raw)?;
        let digest = signing_digest(&decoded.bundle, &decoded.context)
            .map_err(|_| WireError::Authorization)?;
        for action in decoded.bundle.actions().iter() {
            action
                .rk()
                .verify(&digest, action.authorization())
                .map_err(|_| WireError::Authorization)?;
        }
        decoded
            .bundle
            .binding_validating_key()
            .verify(&digest, decoded.bundle.authorization().binding_signature())
            .map_err(|_| WireError::Authorization)?;
        decoded
            .bundle
            .verify_proof(&self.key)
            .map_err(|_| WireError::Authorization)?;
        Ok(payload_digest(raw))
    }
}
