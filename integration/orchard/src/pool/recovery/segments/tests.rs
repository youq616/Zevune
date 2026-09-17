use super::*;
use crate::pool::{genesis_bytes_policy, Record};
use rand::{rngs::OsRng, RngCore};
use std::path::PathBuf;

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut random = [0; 16];
        OsRng.fill_bytes(&mut random);
        let suffix: String = random.iter().map(|b| format!("{b:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-segments-{suffix}"));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn path(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }
}
impl Drop for Dir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn fixture(path: &Path, blocks: u64) -> (RecoveryCheckpoint, Vec<u8>) {
    // Genuine empty blocks: no fake proofs or bypass verifier. Build a valid
    // old-format journal efficiently without thousands of separate fsync calls.
    let mut state = State::from_policy(&[], None).unwrap();
    let verifier = AuthorizationVerifier::new();
    let mut raw = genesis_bytes_policy(&[], None).unwrap();
    for height in 1..=blocks {
        let mut id = [0; 32];
        id[..8].copy_from_slice(&height.to_be_bytes());
        let next = state.execute(height, id, &[], &verifier).unwrap();
        let body = Record {
            height,
            block_id: id,
            base_hash: state.summary().app_hash,
            result_hash: next.summary().app_hash,
            transactions: vec![],
        }
        .encode()
        .unwrap();
        raw.extend_from_slice(&(body.len() as u32).to_be_bytes());
        raw.extend_from_slice(&body);
        raw.extend_from_slice(&Sha256::digest(&body));
        state = next;
    }
    fs::write(path, &raw).unwrap();
    let mut pool = PoolStore::open(path).unwrap();
    (pool.recovery_checkpoint().unwrap(), raw)
}
fn pack(source: &Path, target: &Path, pin: RecoveryCheckpoint) {
    let mut archive = RecoveryArchive::open(source, pin).unwrap();
    let packed = archive.pack_new(target).unwrap();
    assert_eq!(packed.checkpoint(), pin);
}

#[test]
fn manifest_is_exact_bounded_and_contains_no_supplied_paths() {
    // Codec-only metadata; it cannot be accepted as a journal without replay.
    for length in [44, SEGMENT_BYTES, SEGMENT_BYTES + 1, MAX_JOURNAL_BYTES] {
        let pin = RecoveryCheckpoint {
            genesis: [1; 32],
            height: 0,
            app_hash: [2; 32],
            length,
            journal_hash: [3; 32],
        };
        let entries: Vec<_> = (0..count(pin))
            .map(|i| Entry {
                length: segment_length(pin, i),
                hash: [4; 32],
            })
            .collect();
        let raw = encode(pin, &entries).unwrap();
        assert_eq!(raw.len(), FIXED_BYTES + 36 * count(pin));
        assert!(raw.len() <= MAX_MANIFEST);
        assert_eq!(decode(&raw, pin).unwrap().len(), count(pin));
        for cut in 0..raw.len() {
            assert!(decode(&raw[..cut], pin).is_err());
        }
        let mut trailing = raw.clone();
        trailing.push(0);
        assert!(decode(&trailing, pin).is_err());
        for index in [0, 8, 127, 128, 131, 132, 135, 136, 139] {
            let mut altered = raw.clone();
            altered[index] ^= 1;
            assert!(decode(&altered, pin).is_err(), "{index}");
        }
        let mut bomb = raw.clone();
        bomb[132..136].copy_from_slice(&u32::MAX.to_be_bytes());
        assert!(decode(&bomb, pin).is_err());
        assert!(encode(pin, &entries[..entries.len() - 1]).is_err());
    }
}

#[test]
fn actual_multisegment_replay_crosses_record_boundary_and_restores_exact_bytes() {
    let d = Dir::new();
    let source = d.path("source");
    let folder = d.path("segments");
    let (pin, raw) = fixture(&source, 7_200); // >1MiB and splits inside an original frame.
    assert_eq!(count(pin), 2);
    assert_ne!((SEGMENT_BYTES - 44) % 150, 0);
    pack(&source, &folder, pin);
    assert_eq!(
        fs::metadata(folder.join(name(0))).unwrap().len(),
        SEGMENT_BYTES
    );
    let mut archive = SegmentedArchive::open(&folder, pin).unwrap();
    let restored = d.path("restored");
    assert_eq!(archive.restore_new(&restored).unwrap(), pin);
    assert_eq!(fs::read(&restored).unwrap(), raw);
    assert_eq!(fs::read(&source).unwrap(), raw);
    let mut pool = PoolStore::open(&restored).unwrap();
    pool.check_checkpoint(pin.height(), pin.app_hash()).unwrap();
    let prepared = pool.prepare(7201, [9; 32], &[]).unwrap();
    assert_eq!(pool.commit(prepared).unwrap().height, 7201);
}

#[test]
fn pack_and_restore_are_create_only_and_archive_readers_keep_real_locks() {
    let d = Dir::new();
    let source = d.path("source");
    let folder = d.path("archive");
    let (pin, raw) = fixture(&source, 2);
    let mut input = RecoveryArchive::open(&source, pin).unwrap();
    assert!(input.pack_new(&source).is_err());
    assert!(input.pack_new(Path::new("relative")).is_err());
    assert!(input.pack_new(&d.path("absent/child")).is_err());
    drop(input.pack_new(&folder).unwrap());
    assert!(input.pack_new(&folder).is_err());
    let mut first = SegmentedArchive::open(&folder, pin).unwrap();
    let second = SegmentedArchive::open(&folder, pin).unwrap();
    for name in [MANIFEST.to_string(), name(0)] {
        let writer = OpenOptions::new()
            .read(true)
            .write(true)
            .open(folder.join(name))
            .unwrap();
        assert!(writer.try_lock().is_err());
    }
    let target = d.path("existing");
    fs::write(&target, b"preserve").unwrap();
    assert!(first.restore_new(&target).is_err());
    assert_eq!(fs::read(&target).unwrap(), b"preserve");
    assert!(first.restore_new(Path::new("relative")).is_err());
    assert!(first.restore_new(&source).is_err());
    let nested = folder.join("must-not-create.journal");
    assert!(matches!(first.restore_new(&nested), Err(PoolError::Bounds)));
    assert!(!nested.exists());
    first.verify().unwrap();
    assert_eq!(fs::read(&source).unwrap(), raw);
    drop(second);
    drop(first);
    assert!(SegmentedArchive::open(Path::new("relative"), pin).is_err());
    assert!(SegmentedArchive::open(&source, pin).is_err());
}

#[test]
fn missing_extra_swapped_truncated_or_changed_segments_are_rejected() {
    let d = Dir::new();
    let source = d.path("source");
    let folder = d.path("archive");
    let (pin, _) = fixture(&source, 2);
    pack(&source, &folder, pin);
    let part = folder.join(name(0));
    let good = fs::read(&part).unwrap();
    for changed in [
        good[..good.len() - 1].to_vec(),
        [good.as_slice(), &[0]].concat(),
        vec![0; good.len()],
    ] {
        fs::write(&part, &changed).unwrap();
        assert!(SegmentedArchive::open(&folder, pin).is_err());
    }
    fs::write(&part, &good).unwrap();
    for extra in ["extra", "segment-000001.bin", "../not-inside"] {
        let p = folder.join(extra);
        fs::write(&p, b"extra").unwrap();
        if extra.starts_with("../") {
            // Parser never accepts a path from the manifest; outside siblings
            // are irrelevant and must NOT become archive inputs.
            assert!(SegmentedArchive::open(&folder, pin).is_ok());
        } else {
            assert!(SegmentedArchive::open(&folder, pin).is_err());
        }
        fs::remove_file(p).unwrap();
    }
    fs::rename(&part, folder.join("segment-000001.bin")).unwrap();
    assert!(SegmentedArchive::open(&folder, pin).is_err());
    fs::rename(folder.join("segment-000001.bin"), &part).unwrap();
    let m = folder.join(MANIFEST);
    let saved = fs::read(&m).unwrap();
    for changed in [
        saved[..saved.len() - 1].to_vec(),
        vec![0; MAX_MANIFEST + 1],
        vec![0; saved.len()],
    ] {
        fs::write(&m, changed).unwrap();
        assert!(SegmentedArchive::open(&folder, pin).is_err());
    }
    fs::write(&m, saved).unwrap();
    assert!(SegmentedArchive::open(&folder, pin).is_ok());
}

#[test]
fn every_publication_failure_preserves_source_and_cannot_be_retried_in_place() {
    let d = Dir::new();
    let source = d.path("source");
    let (pin, raw) = fixture(&source, 1);
    let mut input = RecoveryArchive::open(&source, pin).unwrap();
    for fault in [3, 4, 5] {
        let folder = d.path(&format!("failure{fault}"));
        input.fault = fault;
        assert!(matches!(input.pack_new(&folder), Err(PoolError::Storage)));
        assert!(folder.is_dir());
        assert_eq!(folder.join(MANIFEST).exists(), fault == 5);
        assert_eq!(SegmentedArchive::open(&folder, pin).is_ok(), fault == 5);
        assert_eq!(fs::read(&source).unwrap(), raw);
        input.fault = 0;
        assert!(input.pack_new(&folder).is_err());
    }
}

#[test]
fn partial_restore_and_lost_ack_leave_explicitly_verifiable_targets() {
    let d = Dir::new();
    let source = d.path("source");
    let folder = d.path("archive");
    let (pin, raw) = fixture(&source, 1);
    pack(&source, &folder, pin);
    let mut archive = SegmentedArchive::open(&folder, pin).unwrap();
    for fault in [1, 2] {
        archive.fault = fault;
        let target = d.path(&format!("failure{fault}"));
        assert!(matches!(
            archive.restore_new(&target),
            Err(PoolError::Storage)
        ));
        assert!(target.exists());
        assert_eq!(RecoveryArchive::open(&target, pin).is_ok(), fault == 2);
        let before = fs::read(&target).unwrap();
        archive.fault = 0;
        assert!(archive.restore_new(&target).is_err());
        assert_eq!(fs::read(&target).unwrap(), before);
        assert_eq!(fs::read(&source).unwrap(), raw);
        archive.verify().unwrap();
    }
}

#[test]
fn empty_read_does_not_advance_and_segment_eof_is_not_journal_eof() {
    let d = Dir::new();
    let p = d.path("a");
    let q = d.path("b");
    fs::write(&p, [1, 2]).unwrap();
    fs::write(&q, [3, 4]).unwrap();
    let mut files = vec![File::open(&p).unwrap(), File::open(&q).unwrap()];
    let entries = vec![
        Entry {
            length: 2,
            hash: [0; 32]
        };
        2
    ];
    let mut reader = SegmentReader {
        files: &mut files,
        entries: &entries,
        index: 0,
        position: 0,
        failed: false,
    };
    assert_eq!(reader.read(&mut []).unwrap(), 0);
    assert_eq!(reader.index, 0);
    let mut out = [0; 4];
    reader.read_exact(&mut out).unwrap();
    assert_eq!(out, [1, 2, 3, 4]);
    require_eof(&mut reader).unwrap();
    drop(files);
    for bad in [vec![3], vec![3, 4, 5]] {
        fs::write(&q, bad).unwrap();
        let mut files = vec![File::open(&p).unwrap(), File::open(&q).unwrap()];
        let mut reader = SegmentReader {
            files: &mut files,
            entries: &entries,
            index: 0,
            position: 0,
            failed: false,
        };
        let result = reader.read_exact(&mut out);
        assert!(result.is_err() || require_eof(&mut reader).is_err());
    }
}

#[cfg(unix)]
#[test]
fn links_and_nonregular_inputs_are_refused_and_late_corruption_precedes_output_creation() {
    let d = Dir::new();
    let source = d.path("source");
    let folder = d.path("archive");
    let (pin, _) = fixture(&source, 1);
    pack(&source, &folder, pin);
    let link = d.path("link");
    std::os::unix::fs::symlink(&folder, &link).unwrap();
    assert!(SegmentedArchive::open(&link, pin).is_err());
    let mut opened = SegmentedArchive::open(&folder, pin).unwrap();
    assert!(matches!(
        opened.restore_new(&link.join("new.journal")),
        Err(PoolError::Bounds)
    ));
    assert!(!folder.join("new.journal").exists());
    drop(opened);
    let part = folder.join(name(0));
    let saved = d.path("part");
    fs::rename(&part, &saved).unwrap();
    std::os::unix::fs::symlink(&saved, &part).unwrap();
    assert!(SegmentedArchive::open(&folder, pin).is_err());
    fs::remove_file(&part).unwrap();
    fs::rename(&saved, &part).unwrap();
    let mut archive = SegmentedArchive::open(&folder, pin).unwrap();
    // Explicit Unix-only uncooperative writer; no claim that advisory locks
    // stop a malicious host, or that Windows permits this mutation.
    let mut raw = fs::read(&part).unwrap();
    raw[0] ^= 1;
    fs::write(&part, raw).unwrap();
    let target = d.path("never-created");
    assert!(archive.restore_new(&target).is_err());
    assert!(!target.exists());
}

#[cfg(feature = "local-funding-lab")]
#[test]
fn real_payment_restore_continues_but_rehashed_bad_signature_is_still_rejected() {
    use crate::pool::testnet::TestGenesis;
    use crate::wallet::{Wallet, WalletProver};
    let d = Dir::new();
    let source = d.path("source");
    let folder = d.path("archive");
    let mut alice = Wallet::create().unwrap();
    let mut bob = Wallet::create().unwrap();
    let genesis = TestGenesis::generate(&[(alice.receive_address(0).unwrap(), 100_000)]).unwrap();
    let mut pool = genesis.create_pool(&source).unwrap();
    alice
        .sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    let prover = WalletProver::new();
    let tx = alice
        .build_payment(bob.receive_address(0).unwrap(), 10_000, 100, 30, &prover)
        .unwrap()
        .bytes()
        .to_vec();
    let b = pool.prepare(1, [1; 32], std::slice::from_ref(&tx)).unwrap();
    pool.commit(b).unwrap();
    let pin = pool.recovery_checkpoint().unwrap();
    drop(pool);
    pack(&source, &folder, pin);
    let mut archive = SegmentedArchive::open(&folder, pin).unwrap();
    let restored = d.path("restored");
    archive.restore_new(&restored).unwrap();
    drop(archive);
    let mut pool = genesis.open_pool(&restored).unwrap();
    assert!(matches!(
        pool.prepare(2, [2; 32], std::slice::from_ref(&tx)),
        Err(PoolError::DoubleSpend)
    ));
    bob.sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    assert_eq!(bob.balance().unwrap(), 10_000);
    let tx2 = bob
        .build_payment(alice.receive_address(1).unwrap(), 1_000, 100, 30, &prover)
        .unwrap()
        .bytes()
        .to_vec();
    let b = pool.prepare(2, [2; 32], &[tx2]).unwrap();
    assert_eq!(pool.commit(b).unwrap().fees, 200);
    drop(pool);
    // Forge every ordinary hash including the supplied pin. Only genuine
    // authorization should reject, not a stale manifest/segment checksum.
    let mut raw = fs::read(folder.join(name(0))).unwrap();
    let mut reader = io::Cursor::new(&raw);
    let header = read_header(&mut reader, raw.len() as u64).unwrap();
    let begin = header.length as usize;
    let size = u32::from_be_bytes(raw[begin..begin + 4].try_into().unwrap()) as usize;
    let end = begin + 4 + size;
    raw[end - 1] ^= 1;
    let hash: Hash = Sha256::digest(&raw[begin + 4..end]).into();
    raw[end..end + 32].copy_from_slice(&hash);
    let mut forged = pin;
    forged.journal_hash = Sha256::digest(&raw).into();
    fs::write(folder.join(name(0)), &raw).unwrap();
    fs::write(
        folder.join(MANIFEST),
        encode(
            forged,
            &[Entry {
                length: raw.len() as u32,
                hash: forged.journal_hash,
            }],
        )
        .unwrap(),
    )
    .unwrap();
    assert!(matches!(
        SegmentedArchive::open(&folder, forged),
        Err(PoolError::Authorization)
    ));
    assert!(SegmentedArchive::open(&folder, pin).is_err());
}

#[cfg(feature = "local-funding-lab")]
#[path = "payment_boundary_tests.rs"]
mod payment_boundary_tests;

#[cfg(unix)]
#[test]
fn persistent_segment_path_replacement_is_rejected_before_restore() {
    let d = Dir::new();
    let source = d.path("source");
    let folder = d.path("archive");
    let (pin, _) = fixture(&source, 1);
    pack(&source, &folder, pin);
    let mut archive = SegmentedArchive::open(&folder, pin).unwrap();
    let part = folder.join(name(0));
    let old = d.path("old-segment");
    let mut replacement = fs::read(&part).unwrap();
    replacement[0] ^= 1;
    fs::rename(&part, &old).unwrap();
    fs::write(&part, &replacement).unwrap();
    // Rechecking the directory must not validate an unlinked old descriptor
    // while reporting that the newly replaced archive path was verified.
    assert!(matches!(archive.verify(), Err(PoolError::Corrupt)));
    let output = d.path("must-not-create");
    assert!(archive.restore_new(&output).is_err());
    assert!(!output.exists());
    assert_eq!(fs::read(part).unwrap(), replacement);
}

#[path = "namespace_tests.rs"]
mod namespace_tests;
