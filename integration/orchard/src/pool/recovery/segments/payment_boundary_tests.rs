//! Genuine ZERO-VALUE authorization across the production 1 MiB backup boundary.
use super::*;

#[cfg(feature = "local-funding-lab")]
#[test]
fn real_zero_value_authorization_crosses_segment_boundary_and_rehashed_corruption_cannot_restore() {
    use crate::wallet::Wallet;
    use crate::{signing_digest, Context, CIRCUIT, NETWORK, VERSION};
    use orchard::builder::{Builder, BundleType};
    use orchard::circuit::ProvingKey;
    use orchard::value::NoteValue;
    use orchard::Anchor;
    let d = Dir::new();
    let source = d.path("zero-value-cross-segment");
    let folder = d.path("segments");
    let domain = Some([9; 32]);
    let receiver = Wallet::create().unwrap();
    let mut pool = PoolStore::create_with_policy(&source, &[], domain).unwrap();
    let mut state = pool.state.clone();
    let mut original = Vec::new();
    pool.file.rewind().unwrap();
    pool.file.read_to_end(&mut original).unwrap();
    drop(pool);
    // Position a real signed transaction across the 1 MiB boundary. Empty
    // records supply deterministic padding, not fake proof-bearing payments.
    let padding = (SEGMENT_BYTES as usize - original.len() - 4096) / 150;
    let verifier = AuthorizationVerifier::new();
    for height in 1..=padding as u64 {
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
        original.extend_from_slice(&(body.len() as u32).to_be_bytes());
        original.extend_from_slice(&body);
        original.extend_from_slice(&Sha256::digest(&body));
        state = next;
    }
    fs::write(&source, &original).unwrap();
    let mut pool = PoolStore::open_with_policy(&source, &[], domain).unwrap();
    assert_eq!(pool.summary().unwrap().height, padding as u64);
    // A zero-value fixture keeps the thousands of padding blocks empty-tree
    // and makes the boundary test practical on native CI. This is a genuine
    // Orchard proof/binding signature, NOT a nonzero payment or mock verifier.
    // Existing funded archive tests separately verify real receiver spending.
    let mut builder = Builder::new(
        BundleType::DEFAULT,
        VERSION,
        VERSION.default_flags(),
        Anchor::empty_tree(),
    )
    .unwrap();
    builder
        .add_output(
            None,
            receiver.receive_address(0).unwrap(),
            NoteValue::from_raw(0),
            [0; 512],
        )
        .unwrap();
    let bundle = builder.build::<i64>(OsRng).unwrap().unwrap().0;
    let context = Context {
        network: NETWORK.into(),
        signing_domain: domain,
        expiry_height: padding as u64 + 20,
        fee: 0,
    };
    let digest = signing_digest(&bundle, &context).unwrap();
    let signed = bundle
        .create_proof(&ProvingKey::build(CIRCUIT), OsRng)
        .unwrap()
        .apply_signatures(OsRng, digest, &[])
        .unwrap();
    let tx = crate::wire::encode(&signed, &context).unwrap();
    assert_eq!(*signed.value_balance(), 0);
    verifier.verify(&tx).unwrap();
    let frame_start = original.len();
    let tx_start = frame_start + 4 + 114 + 4;
    assert!(tx_start < SEGMENT_BYTES as usize);
    assert!(tx_start + tx.len() > SEGMENT_BYTES as usize);
    let height = padding as u64 + 1;
    let prepared = pool
        .prepare(height, [91; 32], std::slice::from_ref(&tx))
        .unwrap();
    pool.commit(prepared).unwrap();
    let pin = pool.recovery_checkpoint().unwrap();
    assert_eq!(count(pin), 2);
    pool.file.rewind().unwrap();
    original.clear();
    pool.file.read_to_end(&mut original).unwrap();
    drop(pool);
    pack(&source, &folder, pin);
    let restored = d.path("restored");
    let mut archive = SegmentedArchive::open(&folder, pin).unwrap();
    archive.restore_new(&restored).unwrap();
    assert_eq!(fs::read(&restored).unwrap(), original);
    drop(archive);
    let mut recovered = PoolStore::open_with_policy(&restored, &[], domain).unwrap();
    assert!(matches!(
        recovered.prepare(height + 1, [92; 32], &[tx]),
        Err(PoolError::DoubleSpend)
    ));
    assert_eq!(recovered.summary().unwrap().fees, 0);
    let prepared = recovered.prepare(height + 1, [92; 32], &[]).unwrap();
    assert_eq!(recovered.commit(prepared).unwrap().height, height + 1);
    drop(recovered);
    // Swapping two real segments is not just renaming an unknown single file.
    let first = fs::read(folder.join(name(0))).unwrap();
    let second = fs::read(folder.join(name(1))).unwrap();
    fs::write(folder.join(name(0)), &second).unwrap();
    fs::write(folder.join(name(1)), &first).unwrap();
    assert!(SegmentedArchive::open(&folder, pin).is_err());
    fs::write(folder.join(name(0)), first).unwrap();
    fs::write(folder.join(name(1)), second).unwrap();
    // Change the binding signature in the second segment and recompute ALL
    // ordinary checksums, including the external pin. Genuine authorization,
    // not a stale checksum or a file lock failure, must reject this archive.
    let mut altered = original.clone();
    let body_len =
        u32::from_be_bytes(altered[frame_start..frame_start + 4].try_into().unwrap()) as usize;
    let end = frame_start + 4 + body_len;
    assert!(end - 1 > SEGMENT_BYTES as usize);
    altered[end - 1] ^= 1;
    let hash: Hash = Sha256::digest(&altered[frame_start + 4..end]).into();
    altered[end..end + 32].copy_from_slice(&hash);
    let mut forged = pin;
    forged.journal_hash = Sha256::digest(&altered).into();
    let mut entries = Vec::new();
    for (i, part) in altered.chunks(SEGMENT_BYTES as usize).enumerate() {
        fs::write(folder.join(name(i)), part).unwrap();
        entries.push(Entry {
            length: part.len() as u32,
            hash: Sha256::digest(part).into(),
        });
    }
    fs::write(folder.join(MANIFEST), encode(forged, &entries).unwrap()).unwrap();
    assert!(matches!(
        SegmentedArchive::open(&folder, forged),
        Err(PoolError::Authorization)
    ));
    assert_eq!(fs::read(&source).unwrap(), original);
}
