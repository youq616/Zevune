//! Canonical, resource-bounded experimental public transaction envelope.
//! This is not a Zcash transaction or the old Go v0 envelope.
use crate::{Error, Result};
use nonempty::NonEmpty;
use orchard::bundle::{Authorization, Authorized, Flags, TxVersion};
use orchard::note::{ExtractedNoteCommitment, Nullifier, TransmittedNoteCiphertext};
use orchard::primitives::redpallas::{Signature, SpendAuth, VerificationKey};
use orchard::value::ValueCommitment;
use orchard::{Action, Anchor, Bundle, Proof};
use sha2::{Digest, Sha256};
use zevune_orchard_lab::VERSION;
pub const MAX_TX: usize = 32_768;
pub const MAX_ACTIONS: usize = 8;
const MAGIC: &[u8; 4] = b"ZVP1";
#[derive(Clone)]
pub struct Transaction { pub kind: u8, pub genesis: [u8; 32], pub expiry: u64, pub fee: u64, pub bundle: Bundle<Authorized, i64> }
pub fn signing_digest<A: Authorization>(bundle: &Bundle<A, i64>, kind: u8, genesis: [u8; 32], expiry: u64, fee: u64) -> Result<[u8; 32]> {
    if kind > 1 || bundle.bundle_version() != VERSION { return Err(Error::Context); }
    let commitment: [u8; 32] = bundle.commitment(TxVersion::V5).map_err(|_| Error::Encoding)?.into();
    let mut h = Sha256::new(); h.update(b"ZEVUNE-PAYMENT-LAB-SIGNATURE\0\x01"); h.update([kind]); h.update(genesis); h.update(expiry.to_be_bytes()); h.update(fee.to_be_bytes()); h.update(commitment); Ok(h.finalize().into())
}
impl Transaction {
    pub fn encode(&self) -> Result<Vec<u8>> {
        let b = &self.bundle; let n = b.actions().len();
        if self.kind > 1 || !(1..=MAX_ACTIONS).contains(&n) || b.bundle_version() != VERSION || b.authorization().proof().as_ref().len() != Proof::expected_proof_size(n) { return Err(Error::Encoding); }
        let mut out = Vec::with_capacity(MAX_TX); out.extend_from_slice(MAGIC); out.push(self.kind); out.extend_from_slice(&self.genesis); out.extend_from_slice(&self.expiry.to_be_bytes()); out.extend_from_slice(&self.fee.to_be_bytes()); out.push(n as u8); out.push(b.flag_byte()); out.extend_from_slice(&b.value_balance().to_be_bytes()); out.extend_from_slice(&b.anchor().to_bytes());
        for a in b.actions().iter() {
            out.extend_from_slice(&a.cv_net().to_bytes()); out.extend_from_slice(&a.nullifier().to_bytes()); out.extend_from_slice(&<[u8; 32]>::from(a.rk())); out.extend_from_slice(&a.cmx().to_bytes()); out.extend_from_slice(&a.encrypted_note().epk_bytes); out.extend_from_slice(&a.encrypted_note().enc_ciphertext); out.extend_from_slice(&a.encrypted_note().out_ciphertext); out.extend_from_slice(&<[u8; 64]>::from(a.authorization()));
        }
        let proof = b.authorization().proof().as_ref(); out.extend_from_slice(&(proof.len() as u32).to_be_bytes()); out.extend_from_slice(proof); out.extend_from_slice(&<[u8; 64]>::from(b.authorization().binding_signature()));
        if out.len() > MAX_TX { return Err(Error::Limit); } Ok(out)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self> {
        if bytes.len() > MAX_TX { return Err(Error::Limit); } let mut r = Reader::new(bytes);
        if &r.array::<4>()? != MAGIC { return Err(Error::Encoding); } let kind = r.byte()?; if kind > 1 { return Err(Error::Encoding); }
        let genesis = r.array()?; let expiry = r.u64()?; let fee = r.u64()?; let n = r.byte()? as usize; if !(1..=MAX_ACTIONS).contains(&n) { return Err(Error::Limit); }
        let flags = match r.byte()? { 2 => Flags::SPENDS_DISABLED, 3 => VERSION.default_flags(), _ => return Err(Error::Encoding) };
        let balance = i64::from_be_bytes(r.array()?); let anchor = Option::<Anchor>::from(Anchor::from_bytes(r.array()?)).ok_or(Error::Encoding)?; let mut actions = Vec::with_capacity(n);
        for _ in 0..n {
            let cv = Option::<ValueCommitment>::from(ValueCommitment::from_bytes(&r.array()?)).ok_or(Error::Encoding)?;
            let nf = Option::<Nullifier>::from(Nullifier::from_bytes(&r.array()?)).ok_or(Error::Encoding)?;
            let rk = VerificationKey::<SpendAuth>::try_from(r.array::<32>()?).map_err(|_| Error::Encoding)?;
            let cm = Option::<ExtractedNoteCommitment>::from(ExtractedNoteCommitment::from_bytes(&r.array()?)).ok_or(Error::Encoding)?;
            let encrypted = TransmittedNoteCiphertext { epk_bytes: r.array()?, enc_ciphertext: r.array()?, out_ciphertext: r.array()? };
            let signature = Signature::<SpendAuth>::from(r.array::<64>()?);
            actions.push(Action::from_parts(nf, rk, cm, encrypted, cv, signature).map_err(|_| Error::Encoding)?);
        }
        let size = r.u32()? as usize; if size != Proof::expected_proof_size(n) { return Err(Error::Encoding); }
        let proof = Proof::new(r.take(size)?.to_vec()); let binding = r.array::<64>()?.into(); r.finish()?;
        let bundle = Bundle::try_from_parts(NonEmpty::from_vec(actions).ok_or(Error::Encoding)?, flags, balance, anchor, Authorized::from_parts(proof, binding), VERSION).map_err(|_| Error::Encoding)?;
        let tx = Self { kind, genesis, expiry, fee, bundle }; if tx.encode()?.as_slice() != bytes { return Err(Error::Encoding); } Ok(tx)
    }
    pub fn digest(&self) -> Result<[u8; 32]> { signing_digest(&self.bundle, self.kind, self.genesis, self.expiry, self.fee) }
}
pub struct Reader<'a> { bytes: &'a [u8], pos: usize }
impl<'a> Reader<'a> {
    pub fn new(bytes: &'a [u8]) -> Self { Self { bytes, pos: 0 } }
    pub fn take(&mut self, n: usize) -> Result<&'a [u8]> { let end = self.pos.checked_add(n).ok_or(Error::Limit)?; let slice = self.bytes.get(self.pos..end).ok_or(Error::Encoding)?; self.pos = end; Ok(slice) }
    pub fn array<const N: usize>(&mut self) -> Result<[u8; N]> { self.take(N)?.try_into().map_err(|_| Error::Encoding) }
    pub fn byte(&mut self) -> Result<u8> { Ok(self.array::<1>()?[0]) }
    pub fn u32(&mut self) -> Result<u32> { Ok(u32::from_be_bytes(self.array()?)) }
    pub fn u64(&mut self) -> Result<u64> { Ok(u64::from_be_bytes(self.array()?)) }
    pub fn finish(&self) -> Result<()> { if self.pos == self.bytes.len() { Ok(()) } else { Err(Error::Encoding) } }
}
