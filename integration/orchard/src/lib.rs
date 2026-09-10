//! Isolated, NO-FUNDS integration of upstream Orchard proofs and signatures.
//!
//! This is NOT the Zevune network transaction format or a consensus verifier.
//! Only a fixed, patched Orchard V2 circuit is accepted. The local worker only
//! verifies public authorization data. No wallet or payment listener is enabled.
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
    pub expiry_height: u64,
    pub fee: u64,
}

/// The caller must obtain these from a trusted committed state, NOT a transaction.
/// This borrowed view is deliberately read-only. M3 does not yet construct it.
pub struct StateView<'a> {
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
    if context.network != NETWORK {
        return Err(Error::Network);
    }
    if context.fee > i64::MAX as u64 {
        return Err(Error::Fee);
    }
    Ok(())
}

/// An EXPERIMENTAL lab signing transcript, not ZIP-244 or a final network spec.
/// V5's upstream bundle commitment includes anchor, flags, balance and outputs.
/// Prefix and fixed-width metadata prevent accidental cross-context reuse here.
/// Do not connect this format to the network without an independently reviewed
/// transaction specification, canonical wire decoder and consensus adapter.
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
    let mut h = Sha256::new();
    h.update(b"ZEVUNE-ORCHARD-LAB-SIGHASH\x00\x01");
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
