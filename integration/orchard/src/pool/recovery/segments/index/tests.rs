use super::*;
use crate::pool::{genesis_bytes_policy, Record};
use rand::{rngs::OsRng, RngCore};

struct Dir(std::path::PathBuf);
impl Dir {
    fn new() -> Self {
        let mut random = [0; 16];
        OsRng.fill_bytes(&mut random);
        let name: String = random.iter().map(|b| format!("{b:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-index-{name}"));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn path(&self, name: &str) -> std::path::PathBuf {
        self.0.join(name)
    }
}
impl Drop for Dir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn fixture(path: &Path, heights: u64, domain: Option<Hash>) -> (RecoveryCheckpoint, Vec<u8>) {
    let mut state = State::from_policy(&[], domain).unwrap();
    let verifier = AuthorizationVerifier::new();
    let mut raw = genesis_bytes_policy(&[], domain).unwrap();
    for height in 1..=heights {
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
    let mut pool = PoolStore::open_with_policy(path, &[], domain).unwrap();
    (pool.recovery_checkpoint().unwrap(), raw)
}
fn packed(d: &Dir, heights: u64, domain: Option<Hash>) -> (SegmentedArchive, Vec<u8>) {
    let source = d.path("source");
    let target = d.path("archive");
    let (pin, bytes) = fixture(&source, heights, domain);
    let mut original = RecoveryArchive::open(&source, pin).unwrap();
    (original.pack_new(&target).unwrap(), bytes)
}

#[test]
fn both_profiles_have_exact_height_locations_and_unchanged_source() {
    for domain in [None, Some([9; 32])] {
        let d = Dir::new();
        let (mut archive, raw) = packed(&d, 3, domain);
        let pin = archive.pin;
        let index = archive.build_index().unwrap();
        let header = if domain.is_some() { 76 } else { 44 };
        assert_eq!(index.header_bytes(), header);
        assert_eq!(index.records().len(), 3);
        assert_eq!(index.checkpoint(), pin);
        for height in 1..=3 {
            let record = index.locate_height(height).unwrap();
            assert_eq!(record.offset(), header + (height - 1) * 150);
            assert_eq!(record.length(), 150);
            assert_eq!(record.first_segment(), 0);
            assert_eq!(record.last_segment(), 0);
            let start = record.offset() as usize + 4;
            assert_eq!(record.before_app_hash(), raw[start + 48..start + 80]);
            assert_eq!(record.after_app_hash(), raw[start + 80..start + 112]);
        }
        for height in [0, 4, u64::MAX] {
            assert_eq!(index.locate_height(height), Err(PoolError::Height));
        }
        assert_eq!(
            index.records().last().unwrap().after_app_hash(),
            pin.app_hash
        );
        archive.verify().unwrap(); // Index construction must leave reader cursors reusable.
        drop(archive);
        assert_eq!(fs::read(d.path("source")).unwrap(), raw);
        assert_eq!(fs::read(d.path("archive/segment-000000.bin")).unwrap(), raw);
        let (mut reopened, new_index) =
            SegmentedArchive::open_indexed(&d.path("archive"), pin).unwrap();
        assert_eq!(new_index.records(), index.records());
        reopened.verify().unwrap();
    }
}

#[test]
fn genesis_only_has_no_phantom_record() {
    let d = Dir::new();
    let (mut archive, raw) = packed(&d, 0, Some([9; 32]));
    let index = archive.build_index().unwrap();
    assert!(index.records().is_empty());
    assert_eq!(index.header_bytes(), raw.len() as u64);
    assert_eq!(index.locate_height(0), Err(PoolError::Height));
    assert_eq!(index.locate_height(1), Err(PoolError::Height));
}

#[test]
fn all_records_locate_correctly_across_real_production_segment_boundaries() {
    let d = Dir::new();
    let (mut archive, raw) = packed(&d, 7_200, None);
    let index = archive.build_index().unwrap();
    assert_eq!(index.records().len(), 7_200);
    let crossing = (SEGMENT_BYTES - 44) / 150 + 1;
    let record = index.locate_height(crossing).unwrap();
    assert_eq!(record.first_segment(), 0);
    assert_eq!(record.last_segment(), 1);
    assert!(record.first_segment_offset() > 0);
    assert!(record.last_segment_end() > 0);
    for record in index.records() {
        let offset = 44 + (record.height() - 1) * 150;
        assert_eq!(record.offset(), offset);
        assert_eq!(
            u64::from(record.first_segment()) * SEGMENT_BYTES
                + u64::from(record.first_segment_offset()),
            offset
        );
        assert_eq!(
            u64::from(record.last_segment()) * SEGMENT_BYTES + u64::from(record.last_segment_end()),
            offset + 150
        );
        assert_eq!(&raw[offset as usize + 4..offset as usize + 12], b"ZVOBLK01");
    }
    assert_eq!(
        index.records().last().unwrap().offset() + 150,
        raw.len() as u64
    );
}

#[test]
fn exact_segment_end_is_not_attributed_to_a_nonexistent_next_segment() {
    // Mapping arithmetic only, not a forged archive/state accepted by the API.
    for end in [SEGMENT_BYTES, 2 * SEGMENT_BYTES, MAX_JOURNAL_BYTES] {
        let record = RecordLocation {
            height: 1,
            offset: end - 150,
            length: 150,
            before_app_hash: [1; 32],
            after_app_hash: [2; 32],
        };
        assert_eq!(record.first_segment(), record.last_segment());
        assert_eq!(record.last_segment_end(), SEGMENT_BYTES as u32);
    }
}

#[test]
fn index_builder_rejects_gaps_overlaps_wrong_heights_hashes_and_bombs() {
    let d = Dir::new();
    let (pin, _) = fixture(&d.path("source"), 2, None);
    let initial = State::from_policy(&[], None).unwrap().summary();
    let mut one = initial.clone();
    one.height = 1;
    one.app_hash = [1; 32];
    let mut two = one.clone();
    two.height = 2;
    two.app_hash = pin.app_hash;
    for (start, end) in [(0, 150), (44, 44), (194, 44), (44, u64::MAX), (44, 193)] {
        let mut b = Builder::new(pin).unwrap();
        assert!(b.push(start, end, &initial, &one).is_err());
        assert!(b.records.is_empty());
    }
    for start in [193, 195] {
        let mut b = Builder::new(pin).unwrap();
        b.push(44, 194, &initial, &one).unwrap();
        assert!(b.push(start, start + 150, &one, &two).is_err());
        assert_eq!(b.records.len(), 1);
    }
    let mut b = Builder::new(pin).unwrap();
    assert!(b.push(44, 194, &initial, &two).is_err());
    b.push(44, 194, &initial, &one).unwrap();
    let mut wrong = one.clone();
    wrong.app_hash[0] ^= 1;
    assert!(b.push(194, 344, &wrong, &two).is_err());
    b.push(194, 344, &one, &two).unwrap();
    assert!(b.finish(45).is_err());
    let mut bad = pin;
    bad.height = u64::MAX;
    assert!(matches!(Builder::new(bad), Err(PoolError::Bounds)));
    let mut bad = pin;
    bad.length = u64::MAX;
    assert!(matches!(Builder::new(bad), Err(PoolError::Bounds)));
    assert!(Builder::new(pin).unwrap().finish(44).is_err());
}

#[test]
fn metadata_or_late_replay_failure_never_yields_a_prefix_index() {
    let d = Dir::new();
    let (mut archive, raw) = packed(&d, 3, None);
    let old_index = archive.build_index().unwrap();
    // Mutate through the original owning write handle, including on Windows.
    let start = 44 + 2 * 150 + 4;
    let mut changed = raw.clone();
    changed[start + 80] ^= 1;
    let sum: Hash = Sha256::digest(&changed[start..start + 114]).into();
    changed[start + 114..start + 146].copy_from_slice(&sum);
    archive.files[0].rewind().unwrap();
    archive.files[0].write_all(&changed).unwrap();
    // Recompute every ordinary checksum, including the supplied checkpoint.
    archive.pin.journal_hash = Sha256::digest(&changed).into();
    archive.entries[0].hash = archive.pin.journal_hash;
    archive.raw_manifest = encode(archive.pin, &archive.entries).unwrap();
    archive.manifest.rewind().unwrap();
    archive.manifest.write_all(&archive.raw_manifest).unwrap();
    assert!(matches!(archive.build_index(), Err(PoolError::Corrupt)));
    assert!(matches!(archive.verify(), Err(PoolError::Corrupt)));
    // A previously returned index is historical metadata only, never reused by
    // the archive verification or restore entry point to authorize changed bytes.
    assert_eq!(
        old_index.locate_height(3).unwrap().after_app_hash(),
        old_index.checkpoint().app_hash()
    );
    let target = d.path("must-not-exist");
    assert!(archive.restore_new(&target).is_err());
    assert!(!target.exists());
}

#[test]
fn changed_captured_length_and_wrong_pinned_tip_are_rejected() {
    let d = Dir::new();
    let (mut archive, _) = packed(&d, 2, None);
    archive.files[0].write_all(&[0]).unwrap();
    assert!(archive.build_index().is_err());
    drop(archive);
    let d = Dir::new();
    let (archive, _) = packed(&d, 2, None);
    let mut wrong = archive.pin;
    wrong.height = 1;
    drop(archive);
    assert!(SegmentedArchive::open_indexed(&d.path("archive"), wrong).is_err());
}

#[cfg(unix)]
#[test]
fn moved_named_archive_cannot_reuse_its_old_index_verdict() {
    let d = Dir::new();
    let (mut archive, _) = packed(&d, 2, None);
    archive.build_index().unwrap();
    fs::rename(d.path("archive"), d.path("moved")).unwrap();
    assert!(archive.build_index().is_err());
    let target = d.path("no-output");
    assert!(archive.restore_new(&target).is_err());
    assert!(!target.exists());
}

#[cfg(feature = "local-funding-lab")]
#[test]
fn genuine_nonzero_payment_index_cannot_bypass_authorization_or_double_spend() {
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
    let tx = alice
        .build_payment(
            bob.receive_address(0).unwrap(),
            10_000,
            100,
            20,
            &WalletProver::new(),
        )
        .unwrap()
        .bytes()
        .to_vec();
    let prepared = pool.prepare(1, [1; 32], std::slice::from_ref(&tx)).unwrap();
    let expected = pool.commit(prepared).unwrap();
    let pin = pool.recovery_checkpoint().unwrap();
    drop(pool);
    let original = fs::read(&source).unwrap();
    let mut input = RecoveryArchive::open(&source, pin).unwrap();
    let mut archive = input.pack_new(&folder).unwrap();
    let index = archive.build_index().unwrap();
    let record = index.locate_height(1).unwrap();
    assert_eq!(record.length(), 154 + tx.len() as u64);
    assert_eq!(record.after_app_hash(), expected.app_hash);
    assert_eq!(record.offset(), 108);
    let restore = d.path("restored");
    archive.restore_new(&restore).unwrap();
    let mut restored = genesis.open_pool(&restore).unwrap();
    assert!(matches!(
        restored.prepare(2, [2; 32], std::slice::from_ref(&tx)),
        Err(PoolError::DoubleSpend)
    ));
    bob.sync(&genesis.wallet_history(&mut restored).unwrap())
        .unwrap();
    assert_eq!(bob.balance().unwrap(), 10_000);
    let mut corrupt = original.clone();
    let end = (record.offset() + record.length() - 32) as usize;
    corrupt[end - 1] ^= 1;
    let sum: Hash = Sha256::digest(&corrupt[112..end]).into();
    corrupt[end..end + 32].copy_from_slice(&sum);
    archive.files[0].rewind().unwrap();
    archive.files[0].write_all(&corrupt).unwrap();
    archive.pin.journal_hash = Sha256::digest(&corrupt).into();
    archive.entries[0].hash = archive.pin.journal_hash;
    archive.raw_manifest = encode(archive.pin, &archive.entries).unwrap();
    archive.manifest.rewind().unwrap();
    archive.manifest.write_all(&archive.raw_manifest).unwrap();
    assert!(matches!(
        archive.build_index(),
        Err(PoolError::Authorization)
    ));
    assert_eq!(fs::read(&source).unwrap(), original);
}
