//! Isolated, NO-FUNDS integration of upstream Orchard proofs and signatures.
//!
//! Candidate laboratory protocols, NOT an independently audited mainnet format.
//! Only a fixed, patched Orchard V2 circuit is accepted. Public authorization,
//! trusted genesis policy, and mutable ledger checks remain distinct.
#![forbid(unsafe_code)]

#[cfg(test)]
extern crate self as zevune_orchard_lab;

pub mod pool;
pub mod wire;
pub mod worker;

use std::collections::BTreeSet;
use std::fmt;

use orchard::bundle::{Authorization, Authorized, BatchValidator, BundleVersion, TxVersion};
use orchard::circuit::{OrchardCircuitVersion, VerifyingKey};
use orchard::{Bundle, Proof};
use rand::rngs::OsRng;
use sha2::{Digest, Sha256};

pub const NETWORK: &str = "zevune-orchard-lab-1";
pub const MAX_ACTIONS: usize = 8;
pub const MAX_ANCHORS: usize = 64;
pub const CIRCUIT: OrchardCircuitVersion = OrchardCircuitVersion::FixedPostNu6_2;
pub const VERSION: BundleVersion = BundleVersion::orchard_v2();

/// Public lab metadata. Fee and expiry are signed, not taken from wallet secrets.
#[derive(Clone, Debug)]
pub struct Context {
    pub network: String,
    /// None is legacy LAB1. Some binds LAB2 signatures to a pinned genesis.
    pub signing_domain: Option<[u8; 32]>,
    pub expiry_height: u64,
    pub fee: u64,
}

/// The caller must obtain these from a trusted committed state, NOT a transaction.
/// This borrowed view is deliberately read-only. M3 does not yet construct it.
pub struct StateView<'a> {
    /// Selected by committed chain configuration, never by a transaction.
    pub signing_domain: Option<[u8; 32]>,
    pub height: u64,
    pub anchors: &'a [[u8; 32]],
    pub spent: &'a BTreeSet<[u8; 32]>,
    pub outputs: &'a BTreeSet<[u8; 32]>,
}

/// Public effects only. This value is not an authority token or finality receipt.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Effects {
    pub nullifiers: Vec<[u8; 32]>,
    pub commitments: Vec<[u8; 32]>,
    pub fee: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Network,
    Version,
    Flags,
    ActionLimit,
    ProofLength,
    Fee,
    Expired,
    Anchor,
    DoubleSpend,
    DuplicateOutput,
    Commitment,
    Authorization,
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Fixed codes: never format a note, private key or decrypted memo.
        write!(f, "Orchard laboratory check failed: {self:?}")
    }
}
impl std::error::Error for Error {}

fn check_context(context: &Context) -> Result<(), Error> {
    if context.network != NETWORK || context.signing_domain == Some([0; 32]) {
        return Err(Error::Network);
    }
    if context.fee > i64::MAX as u64 {
        return Err(Error::Fee);
    }
    Ok(())
}

/// Experimental LAB1/LAB2 signing transcripts, not ZIP-244 or mainnet approval.
/// LAB1 bytes are preserved. LAB2 additionally commits to the pinned genesis
/// manifest digest with a different transcript version. The upstream V5 bundle
/// commitment binds Orchard effects; no circuit or signature primitive changes.
/// See docs/protocol/GENESIS_DOMAIN_V2.md for scope and deployment identity rules.
pub fn signing_digest<A: Authorization>(
    bundle: &Bundle<A, i64>,
    context: &Context,
) -> Result<[u8; 32], Error> {
    check_context(context)?;
    if bundle.bundle_version() != VERSION {
        return Err(Error::Version);
    }
    let commitment: [u8; 32] = bundle
        .commitment(TxVersion::V5)
        .map_err(|_| Error::Commitment)?
        .into();
    signing_digest_parts(context, commitment)
}

// Fixed public-field transcript. Kept separate for independent golden vectors;
// it is not exposed as an authorization or proof bypass.
fn signing_digest_parts(context: &Context, commitment: [u8; 32]) -> Result<[u8; 32], Error> {
    check_context(context)?;
    let mut h = Sha256::new();
    match context.signing_domain {
        None => h.update(b"ZEVUNE-ORCHARD-LAB-SIGHASH\x00\x01"),
        Some(domain) => {
            h.update(b"ZEVUNE-ORCHARD-LAB-SIGHASH\x00\x02");
            h.update(domain);
        }
    }
    h.update((context.network.len() as u16).to_be_bytes());
    h.update(context.network.as_bytes());
    h.update(context.expiry_height.to_be_bytes());
    h.update(context.fee.to_be_bytes());
    h.update(commitment);
    Ok(h.finalize().into())
}

/// Builds its own fixed upstream verifying key: there is no caller-supplied key,
/// circuit selector, mock mode or fallback to transparent transactions.
pub struct Verifier {
    key: VerifyingKey,
}

impl Default for Verifier {
    fn default() -> Self {
        Self::new()
    }
}
impl Verifier {
    pub fn new() -> Self {
        Self {
            key: VerifyingKey::build(CIRCUIT),
        }
    }

    /// Combines public state checks with actual upstream proof AND signature
    /// verification. Never mutates the state view, even on success. The upstream
    /// batch verifier uses secure randomness; its integration as a consensus
    /// decision remains a separate review, not claimed by this laboratory.
    pub fn verify(
        &self,
        bundle: &Bundle<Authorized, i64>,
        context: &Context,
        state: &StateView<'_>,
    ) -> Result<Effects, Error> {
        check_context(context)?;
        if context.signing_domain != state.signing_domain {
            return Err(Error::Network);
        }
        if bundle.bundle_version() != VERSION {
            return Err(Error::Version);
        }
        if bundle.flags() != &VERSION.default_flags() {
            return Err(Error::Flags);
        }
        let n = bundle.actions().len();
        if !(2..=MAX_ACTIONS).contains(&n) {
            return Err(Error::ActionLimit);
        }
        if bundle.authorization().proof().as_ref().len() != Proof::expected_proof_size(n) {
            return Err(Error::ProofLength);
        }
        if *bundle.value_balance() != context.fee as i64 {
            return Err(Error::Fee);
        }
        if context.expiry_height < state.height.saturating_add(1) || state.height == u64::MAX {
            return Err(Error::Expired);
        }
        if state.anchors.len() > MAX_ANCHORS || !state.anchors.contains(&bundle.anchor().to_bytes())
        {
            return Err(Error::Anchor);
        }
        let mut nullifiers = BTreeSet::new();
        let mut commitments = BTreeSet::new();
        for action in bundle.actions().iter() {
            let nf = action.nullifier().to_bytes();
            if state.spent.contains(&nf) || !nullifiers.insert(nf) {
                return Err(Error::DoubleSpend);
            }
            let cm = action.cmx().to_bytes();
            if state.outputs.contains(&cm) || !commitments.insert(cm) {
                return Err(Error::DuplicateOutput);
            }
        }
        let digest = signing_digest(bundle, context)?;
        let mut batch = BatchValidator::new(&self.key);
        batch
            .add_bundle(bundle, digest)
            .map_err(|_| Error::Authorization)?;
        if !batch.validate(OsRng) {
            return Err(Error::Authorization);
        }
        // Preserve consensus-relevant action order; BTreeSets above only detect
        // duplicates. Never append notes in set/sorted order instead of wire order.
        Ok(Effects {
            nullifiers: bundle
                .actions()
                .iter()
                .map(|a| a.nullifier().to_bytes())
                .collect(),
            commitments: bundle
                .actions()
                .iter()
                .map(|a| a.cmx().to_bytes())
                .collect(),
            fee: context.fee,
        })
    }
}

pub mod wallet;

#[cfg(test)]
mod signing_domain_vectors {
    use super::*;
    #[test]
    fn legacy_and_bound_transcripts_match_independent_sha256_vectors() {
        let mut context = Context {
            network: NETWORK.into(),
            signing_domain: None,
            expiry_height: 100,
            fee: 1000,
        };
        assert_eq!(
            signing_digest_parts(&context, [0x42; 32]).unwrap(),
            [
                0x26, 0xe1, 0x29, 0xe2, 0xc7, 0x72, 0x7a, 0x5f, 0xf6, 0x76, 0xcf, 0xe5, 0xbb, 0x31,
                0x6f, 0xb8, 0x20, 0xb9, 0xf7, 0xd7, 0xe9, 0xe7, 0x4a, 0x53, 0xb0, 0xd1, 0xb0, 0x63,
                0xb4, 0xc5, 0x8b, 0x3b
            ]
        );
        context.signing_domain = Some(std::array::from_fn(|i| i as u8));
        assert_eq!(
            signing_digest_parts(&context, [0x42; 32]).unwrap(),
            [
                0x7d, 0xd1, 0x59, 0x0f, 0x47, 0xdb, 0x25, 0x8d, 0x0b, 0x73, 0xe8, 0x95, 0x51, 0x4c,
                0x7c, 0x5f, 0x2b, 0x3a, 0x0b, 0x6c, 0x4e, 0x5b, 0x3c, 0x4f, 0x4a, 0xe2, 0x90, 0x3a,
                0xdc, 0xb4, 0x19, 0xce
            ]
        );
    }
    #[test]
    fn every_context_component_changes_the_bound_signature_message() {
        let original = Context {
            network: NETWORK.into(),
            signing_domain: Some([7; 32]),
            expiry_height: 100,
            fee: 1000,
        };
        let expected = signing_digest_parts(&original, [0x42; 32]).unwrap();
        let mut changed = original.clone();
        changed.expiry_height += 1;
        assert_ne!(
            signing_digest_parts(&changed, [0x42; 32]).unwrap(),
            expected
        );
        changed = original.clone();
        changed.fee += 1;
        assert_ne!(
            signing_digest_parts(&changed, [0x42; 32]).unwrap(),
            expected
        );
        changed = original.clone();
        changed.signing_domain = Some([8; 32]);
        assert_ne!(
            signing_digest_parts(&changed, [0x42; 32]).unwrap(),
            expected
        );
        changed.signing_domain = None;
        assert_ne!(
            signing_digest_parts(&changed, [0x42; 32]).unwrap(),
            expected
        );
        assert_ne!(
            signing_digest_parts(&original, [0x43; 32]).unwrap(),
            expected
        );
        changed = original.clone();
        changed.network = "foreign-network".into();
        assert_eq!(
            signing_digest_parts(&changed, [0x42; 32]),
            Err(Error::Network)
        );
        changed = original;
        changed.signing_domain = Some([0; 32]);
        assert_eq!(
            signing_digest_parts(&changed, [0x42; 32]),
            Err(Error::Network)
        );
    }
}
