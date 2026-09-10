//! Helpers for NO-FUNDS tests only. Never export keys or private witnesses.
use incrementalmerkletree::{Hashable, Level};
use orchard::builder::{Builder, BundleType};
use orchard::circuit::ProvingKey;
use orchard::keys::{FullViewingKey, SpendAuthorizingKey, SpendingKey};
use orchard::note::{RandomSeed, Rho};
use orchard::tree::{MerkleHashOrchard, MerklePath};
use orchard::value::NoteValue;
use orchard::{Address, Anchor, Note, NoteVersion};
use rand::{rngs::OsRng, RngCore};
use zevune_orchard_lab::{signing_digest, Context, NETWORK, VERSION};
use zevune_orchard_lab::wire::SignedBundle;

pub fn key() -> SpendingKey {
    loop {
        let mut bytes = [0;32]; OsRng.fill_bytes(&mut bytes);
        if let Some(k) = Option::<SpendingKey>::from(SpendingKey::from_bytes(bytes)) { return k; }
    }
}
pub fn genesis_note(address: Address) -> Note {
    let rho = Rho::from_bytes(&[0;32]).unwrap();
    loop {
        let mut raw=[0;32]; OsRng.fill_bytes(&mut raw);
        if let Some(seed)=Option::<RandomSeed>::from(RandomSeed::from_bytes(raw,&rho)) {
            if let Some(note)=Option::<Note>::from(Note::from_parts(address,NoteValue::from_raw(100_000),rho,seed,NoteVersion::V2)) { return note; }
        }
    }
}
pub fn witness(leaves: &[MerkleHashOrchard],position: usize)->(MerklePath,Anchor) {
    assert!(position<leaves.len()); let mut nodes=leaves.to_vec(); let mut index=position;
    let mut path=[MerkleHashOrchard::empty_leaf();32];
    for (level,sibling) in path.iter_mut().enumerate() {
        let l=Level::from(level as u8);
        *sibling=nodes.get(index^1).copied().unwrap_or_else(||MerkleHashOrchard::empty_root(l));
        nodes=nodes.chunks(2).map(|p|MerkleHashOrchard::combine(l,&p[0],&p.get(1).copied().unwrap_or_else(||MerkleHashOrchard::empty_root(l)))).collect();
        index>>=1;
    }
    (MerklePath::from_parts(position as u32,path),nodes[0].into())
}
pub fn context()->Context { Context{network:NETWORK.into(),expiry_height:100,fee:1_000} }
pub fn prove(pk:&ProvingKey,sk:&SpendingKey,note:Note,path:MerklePath,outputs:&[(Address,u64)],ctx:&Context)->SignedBundle {
    let mut b=Builder::new(BundleType::DEFAULT,VERSION,VERSION.default_flags(),path.root(note.commitment().into())).unwrap();
    b.add_spend(FullViewingKey::from(sk),note,path).unwrap();
    for &(address,value) in outputs { b.add_output(None,address,NoteValue::from_raw(value),[0;512]).unwrap(); }
    let unauthorized=b.build::<i64>(OsRng).unwrap().unwrap().0;
    let digest=signing_digest(&unauthorized,ctx).unwrap();
    unauthorized.create_proof(pk,OsRng).unwrap().apply_signatures(OsRng,digest,&[SpendAuthorizingKey::from(sk)]).unwrap()
}
