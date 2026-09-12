//! Explicit replay domains for the opt-in V2 laboratory protocol.
//! Public identifiers, NOT authentication keys or reviewed mainnet parameters.
//! Callers must pin the descriptor independently; a transaction cannot select it.
use orchard::bundle::Authorization;
use orchard::Bundle;
use sha2::{Digest, Sha256};

use crate::{signing_digest, Context, Error};

pub const DESCRIPTOR_MAGIC: &[u8; 8] = b"ZVDOMN02";
pub const DESCRIPTOR_SIZE: usize = 104;
/// Exact ASCII bytes, with no trailing newline, identify this rule set. Changing
/// ANY acceptance rule requires a new descriptor/version, not editing this one.
pub const RULES: &[u8] = b"ZEVUNE-BOUND-LAB-RULES\0\x02;orchard=0.15.5;bundle=orchard_v2;circuit=FixedPostNu6_2;commitment=v5;actions=2..8;flags=3;fee=value_balance>=0;expiry=inclusive;anchors=preblock;block_txs<=16;commitments<=65536;height<=10000;anchors<=64;test_supply=100000";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DomainId([u8; 32]);
impl DomainId {
    /// Parsing an ID does not establish trust in a network or a genesis.
    pub fn from_bytes(bytes: [u8; 32]) -> Result<Self, DomainError> {
        if bytes == [0; 32] {
            return Err(DomainError::Identity);
        }
        Ok(Self(bytes))
    }
    pub fn to_bytes(self) -> [u8; 32] {
        self.0
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DomainError {
    Encoding,
    Identity,
    Rules,
}
impl std::fmt::Display for DomainError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "network domain failed: {self:?}")
    }
}
impl std::error::Error for DomainError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NetworkDescriptor {
    network: [u8; 32],
    asset_genesis: [u8; 32],
}
impl NetworkDescriptor {
    /// `network` is a public network identity, not a secret. Distinct networks
    /// MUST use distinct identities even when their initial assets are identical.
    pub fn new(network: [u8; 32], asset_genesis: [u8; 32]) -> Result<Self, DomainError> {
        if network == [0; 32] || asset_genesis == [0; 32] {
            return Err(DomainError::Identity);
        }
        Ok(Self {
            network,
            asset_genesis,
        })
    }
    pub fn asset_genesis(&self) -> [u8; 32] {
        self.asset_genesis
    }
    pub fn network(&self) -> [u8; 32] {
        self.network
    }
    pub fn encode(&self) -> [u8; DESCRIPTOR_SIZE] {
        let mut raw = [0; DESCRIPTOR_SIZE];
        raw[..8].copy_from_slice(DESCRIPTOR_MAGIC);
        raw[8..40].copy_from_slice(&self.network);
        raw[40..72].copy_from_slice(&self.asset_genesis);
        raw[72..].copy_from_slice(&Sha256::digest(RULES));
        raw
    }
    pub fn decode(raw: &[u8]) -> Result<Self, DomainError> {
        if raw.len() != DESCRIPTOR_SIZE || &raw[..8] != DESCRIPTOR_MAGIC {
            return Err(DomainError::Encoding);
        }
        if raw[72..] != Sha256::digest(RULES)[..] {
            return Err(DomainError::Rules);
        }
        Self::new(
            raw[8..40].try_into().map_err(|_| DomainError::Encoding)?,
            raw[40..72].try_into().map_err(|_| DomainError::Encoding)?,
        )
    }
    pub fn id(&self) -> DomainId {
        // This cannot be a caller-provided tag or a field read from a payment.
        let mut h = Sha256::new();
        h.update(b"ZEVUNE-NETWORK-DOMAIN\0\x02");
        h.update(self.encode());
        DomainId(h.finalize().into())
    }
}

/// Domain-separated transcript using the SAME upstream Orchard commitment and
/// signature primitives as V1. A V1 signature cannot be upgraded by wrapping it.
/// This protocol extension still requires independent cryptographic review.
pub fn bound_signing_digest<A: Authorization>(
    bundle: &Bundle<A, i64>,
    context: &Context,
    domain: DomainId,
) -> Result<[u8; 32], Error> {
    let inner = signing_digest(bundle, context)?;
    let mut h = Sha256::new();
    h.update(b"ZEVUNE-ORCHARD-BOUND-SIGHASH\0\x02");
    h.update(domain.to_bytes());
    h.update(inner);
    Ok(h.finalize().into())
}
