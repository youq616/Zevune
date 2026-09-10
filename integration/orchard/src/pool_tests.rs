use super::*;
use orchard::circuit::ProvingKey;
use orchard::keys::{FullViewingKey, Scope};
use rand::{rngs::OsRng, RngCore};
use std::path::PathBuf;

#[path = "../tests/support/fixtures.rs"]
mod fixtures;
use fixtures::{context, genesis_note, key, prove, witness};

struct TestDir(PathBuf);
impl TestDir {
    fn new() -> Self {
        let mut bytes = [0; 16]; OsRng.fill_bytes(&mut bytes);
        let name: String = bytes.iter().map(|v| format!("{v:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-pool-test-{name}"));
        fs::create_dir(&path).unwrap(); Self(path)
    }
    fn file(&self, name: &str) -> PathBuf { self.0.join(name) }
}
impl Drop for TestDir {
    fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); }
}

#[test]
fn actual_two_hop_pool_commit_replay_and_corruption() {
    let dir = TestDir::new(); let path = dir.file("pool.journal");
    let alice = key(); let bob = key(); let carol = key();
    let afvk = FullViewingKey::from(&alice); let bfvk = FullViewingKey::from(&bob);
    let cfvk = FullViewingKey::from(&carol);
    let initial = genesis_note(afvk.address_at(0u32, Scope::External));
    let seed = [<[u8;32]>::from(&ExtractedNoteCommitment::from(initial.commitment()))];
    let mut leaves = vec![MerkleHashOrchard::from_cmx(&initial.commitment().into())];
    let (w, root) = witness(&leaves, 0);
    let pk = ProvingKey::build(crate::CIRCUIT); let ctx = context();
    let first = prove(&pk, &alice, initial, w, &[(bfvk.address_at(0u32, Scope::External),60_000), (afvk.address_at(0u32, Scope::External),39_000)], &ctx);
    let raw = crate::wire::encode(&first, &ctx).unwrap();
    let mut pool = PoolStore::create_with_genesis(&path, &seed).unwrap();
    let initial_summary = pool.summary().unwrap();
    assert_eq!(initial_summary.root, root.to_bytes());
    let len = fs::metadata(&path).unwrap().len();
    // A valid first entry followed by a duplicate must not partially apply.
    assert!(matches!(pool.prepare(1,[1;32],&[raw.clone(),raw.clone()]),Err(PoolError::DoubleSpend)));
    assert_eq!(pool.summary().unwrap(),initial_summary); assert_eq!(fs::metadata(&path).unwrap().len(),len);
    let mut broken = raw.clone(); broken[crate::wire::HEADER_SIZE + 2*crate::wire::ACTION_SIZE + 4] ^= 1;
    assert!(matches!(pool.prepare(1,[1;32],&[broken]),Err(PoolError::Authorization)));
    assert_eq!(pool.summary().unwrap(),initial_summary);
    let first_prepared = pool.prepare(1,[1;32],std::slice::from_ref(&raw)).unwrap();
    let competing = pool.prepare(1,[2;32],&[]).unwrap();
    assert_eq!(pool.summary().unwrap(),initial_summary); assert_eq!(fs::metadata(&path).unwrap().len(),len);
    let first_summary = pool.commit(first_prepared).unwrap();
    assert_eq!((first_summary.height,first_summary.commitments,first_summary.nullifiers,first_summary.fees),(1,3,2,1_000));
    assert!(matches!(pool.commit(competing),Err(PoolError::Stale)));
    assert!(matches!(pool.prepare(2,[2;32],std::slice::from_ref(&raw)),Err(PoolError::DoubleSpend)));
    drop(pool);
    // The only saved data is public genesis commitments and signed envelopes.
    let mut pool = PoolStore::open_with_genesis(&path,&seed).unwrap();
    assert_eq!(pool.summary().unwrap(), first_summary);
    pool.check_checkpoint(first_summary.height,first_summary.app_hash).unwrap();
    assert!(pool.check_checkpoint(0,initial_summary.app_hash).is_err());
    assert!(matches!(pool.prepare(2,[2;32],std::slice::from_ref(&raw)),Err(PoolError::DoubleSpend)));
    let received = first.decrypt_outputs_with_keys(&[bfvk.to_ivk(Scope::External)]);
    assert_eq!(received.len(),1);
    let bob_note = received[0].2; let bob_position = leaves.len() + received[0].0;
    leaves.extend(first.actions().iter().map(|a|MerkleHashOrchard::from_cmx(a.cmx())));
    let (bob_path,bob_root)=witness(&leaves,bob_position);
    assert_eq!(pool.summary().unwrap().root,bob_root.to_bytes());
    let second = prove(&pk,&bob,bob_note,bob_path,&[(cfvk.address_at(0u32,Scope::External),59_000)],&ctx);
    let raw2 = crate::wire::encode(&second,&ctx).unwrap();
    let fresh = State::from_genesis(&seed).unwrap();
    assert!(matches!(fresh.execute(1,[1;32],&[raw.clone(),raw2.clone()],&pool.verifier),Err(PoolError::Anchor)));
    let second_prepared=pool.prepare(2,[2;32],std::slice::from_ref(&raw2)).unwrap();
    let final_summary=pool.commit(second_prepared).unwrap();
    assert_eq!((final_summary.height,final_summary.commitments,final_summary.nullifiers,final_summary.fees),(2,5,4,2_000));
    let c=second.decrypt_outputs_with_keys(&[cfvk.to_ivk(Scope::External)]);
    assert_eq!(c.len(),1); assert_eq!(c[0].2.value().inner(),59_000);
    drop(pool);
    let recovered=PoolStore::open_with_genesis(&path,&seed).unwrap();
    assert_eq!(recovered.summary().unwrap(),final_summary); drop(recovered);
    // Public entry points cannot reinterpret a nonempty test genesis as issuance.
    assert!(matches!(PoolStore::open(&path),Err(PoolError::Genesis)));
    let original=fs::read(&path).unwrap();
    let mut changed=original.clone(); *changed.last_mut().unwrap()^=1;
    fs::write(dir.file("checksum"),changed).unwrap();
    assert!(PoolStore::open_with_genesis(&dir.file("checksum"),&seed).is_err());
    let header=genesis_bytes(&seed).unwrap().len();
    let n=u32::from_be_bytes(original[header..header+4].try_into().unwrap()) as usize;
    let mut forged=original.clone();
    let proof_offset=header+4+114+4+crate::wire::HEADER_SIZE+2*crate::wire::ACTION_SIZE+4;
    forged[proof_offset]^=1;
    let digest=Sha256::digest(&forged[header+4..header+4+n]);
    forged[header+4+n..header+4+n+32].copy_from_slice(&digest);
    fs::write(dir.file("forged"),forged).unwrap();
    assert!(matches!(PoolStore::open_with_genesis(&dir.file("forged"),&seed),Err(PoolError::Authorization)));
    for length in [0,1,header-1,header+1,original.len()-1] {
        let damaged=dir.file(&format!("truncated-{length}")); fs::write(&damaged,&original[..length]).unwrap();
        assert!(PoolStore::open_with_genesis(&damaged,&seed).is_err());
    }
    // Full-record rollback is only detectable with an external trusted checkpoint.
    let prefix=dir.file("valid-prefix"); fs::write(&prefix,&original[..header+4+n+32]).unwrap();
    let rolled=PoolStore::open_with_genesis(&prefix,&seed).unwrap();
    assert!(rolled.check_checkpoint(final_summary.height,final_summary.app_hash).is_err());
    assert_eq!(fs::read(&path).unwrap(),original);
}

#[test]
fn empty_pool_lock_restart_and_no_overwrite() {
    let d=TestDir::new();let p=d.file("empty");let mut s=PoolStore::create(&p).unwrap();
    // Windows file locks may deny reads through another handle. Check metadata
    // while the owner holds the lock, and read bytes only after dropping it.
    let initial_len=fs::metadata(&p).unwrap().len();
    assert!(PoolStore::create(&p).is_err());assert_eq!(fs::metadata(&p).unwrap().len(),initial_len);
    assert!(matches!(PoolStore::open(&p),Err(PoolError::Locked)));
    let plan=s.prepare(1,[1;32],&[]).unwrap();let after=s.commit(plan).unwrap();drop(s);
    assert_eq!(PoolStore::open(&p).unwrap().summary().unwrap(),after);
}
#[test]
fn partial_write_poison_does_not_advance_memory_or_repair_disk() {
    let d=TestDir::new();let p=d.file("partial");let mut s=PoolStore::create(&p).unwrap();
    let before=s.state.summary();let plan=s.prepare(1,[1;32],&[]).unwrap();s.fault=1;
    assert_eq!(s.commit(plan),Err(PoolError::Storage));
    assert_eq!(s.state.summary(),before);assert_eq!(s.summary(),Err(PoolError::Unavailable));
    assert!(matches!(s.prepare(1,[1;32],&[]),Err(PoolError::Unavailable)));drop(s);
    let damaged=fs::read(&p).unwrap();assert!(PoolStore::open(&p).is_err());assert_eq!(fs::read(&p).unwrap(),damaged);
}
#[test]
fn lost_sync_acknowledgement_remains_uncertain_until_replay() {
    let d=TestDir::new();let p=d.file("uncertain");let mut s=PoolStore::create(&p).unwrap();
    let before=s.state.summary();let plan=s.prepare(1,[1;32],&[]).unwrap();let next=plan.result().clone();s.fault=2;
    assert_eq!(s.commit(plan),Err(PoolError::Storage));assert_eq!(s.state.summary(),before);
    assert_eq!(s.summary(),Err(PoolError::Unavailable));drop(s);
    assert_eq!(PoolStore::open(&p).unwrap().summary().unwrap(),next);
}
#[test]
fn tampered_prepared_result_and_resource_limits() {
    let d=TestDir::new();let p=d.file("limits");let mut s=PoolStore::create(&p).unwrap();
    let before=s.summary().unwrap();let length=fs::metadata(&p).unwrap().len();
    let mut plan=s.prepare(1,[1;32],&[]).unwrap();plan.result.fees+=1;
    assert_eq!(s.commit(plan),Err(PoolError::Stale));
    assert_eq!(s.summary().unwrap(),before);assert_eq!(fs::metadata(&p).unwrap().len(),length);
    assert!(matches!(s.prepare(0,[1;32],&[]),Err(PoolError::Height)));
    assert!(matches!(s.prepare(1,[0;32],&[]),Err(PoolError::Height)));
    assert!(matches!(s.prepare(1,[1;32],&vec![vec![];MAX_BLOCK_TRANSACTIONS+1]),Err(PoolError::Bounds)));
    assert!(matches!(s.prepare(1,[1;32],&[vec![0;MAX_ENVELOPE_SIZE+1]]),Err(PoolError::Bounds)));
    assert!(State::from_genesis(&[[255;32]]).is_err());
    assert!(State::from_genesis(&[[0;32],[0;32]]).is_err());
    assert!(State::from_genesis(&vec![[0;32];MAX_COMMITMENTS+1]).is_err());
    s.state.height=u64::MAX;assert!(matches!(s.prepare(0,[1;32],&[]),Err(PoolError::Height)));
    drop(s);OpenOptions::new().write(true).open(&p).unwrap().set_len(MAX_JOURNAL_BYTES+1).unwrap();
    assert!(matches!(PoolStore::open(&p),Err(PoolError::Bounds)));
}
#[test]
fn record_decoder_rejects_truncation_trailing_and_length_bombs() {
    let r=Record{height:1,block_id:[1;32],base_hash:[2;32],result_hash:[3;32],transactions:vec![vec![1,2,3]]};
    let bytes=r.encode().unwrap();let parsed=Record::decode(&bytes).unwrap();assert_eq!(parsed.encode().unwrap(),bytes);
    for n in 0..bytes.len(){assert!(Record::decode(&bytes[..n]).is_err());}
    let mut trailing=bytes.clone();trailing.push(0);assert!(Record::decode(&trailing).is_err());
    let mut bomb=bytes.clone();bomb[114..118].fill(255);assert!(Record::decode(&bomb).is_err());
    assert!(Record::decode(&vec![0;MAX_RECORD_BYTES+1]).is_err());
    let mut rng=OsRng;
    for n in 0..2048 {let mut raw=vec![0;n];rng.fill_bytes(&mut raw);let _=Record::decode(&raw);}
}
