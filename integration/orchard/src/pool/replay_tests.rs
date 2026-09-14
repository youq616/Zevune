use super::*;
use crate::pool::{genesis_bytes_policy, PoolStore};
use std::io::{Cursor, Read, Seek, Write};

fn frame(record: &Record) -> Vec<u8> {
    let body = record.encode().unwrap();
    let mut raw = (body.len() as u32).to_be_bytes().to_vec();
    raw.extend_from_slice(&body);
    raw.extend_from_slice(&Sha256::digest(&body));
    raw
}

fn empty_chain(count: u64) -> (Vec<u8>, Summary) {
    let verifier = AuthorizationVerifier::new();
    let mut state = State::from_policy(&[], None).unwrap();
    let mut bytes = Vec::new();
    for height in 1..=count {
        let mut block_id = [0; 32];
        block_id[..8].copy_from_slice(&height.to_be_bytes());
        let next = state.execute(height, block_id, &[], &verifier).unwrap();
        bytes.extend_from_slice(&frame(&Record {
            height,
            block_id,
            base_hash: state.summary().app_hash,
            result_hash: next.summary().app_hash,
            transactions: Vec::new(),
        }));
        state = next;
    }
    (bytes, state.summary())
}

std::thread_local! {
    // Test-only reuse of the real public verifying parameters, never a fake
    // verifier. Empty-record mutation loops do not need hundreds of rebuilds.
    static TEST_VERIFIER: AuthorizationVerifier = AuthorizationVerifier::new();
}

fn finish_bytes(bytes: &[u8], captured_length: u64) -> Result<Summary, PoolError> {
    let state = State::from_policy(&[], None)?;
    let mut replay = Replay::new(Cursor::new(bytes), captured_length, 0, state)?;
    TEST_VERIFIER.with(|verifier| {
        while replay.next_block(verifier)?.is_some() {}
        Ok(replay.finish()?.1)
    })
}

struct Fragmented<R> {
    inner: R,
    calls: usize,
}
impl<R: Read> Read for Fragmented<R> {
    fn read(&mut self, buffer: &mut [u8]) -> std::io::Result<usize> {
        self.calls += 1;
        if self.calls % 2 == 1 {
            return Err(std::io::Error::from(ErrorKind::Interrupted));
        }
        let limit = buffer.len().min(1);
        self.inner.read(&mut buffer[..limit])
    }
}

#[test]
fn fragmented_reads_and_interrupted_eof_are_retried_without_skipping() {
    let (bytes, expected) = empty_chain(3);
    let state = State::from_policy(&[], None).unwrap();
    let reader = Fragmented {
        inner: Cursor::new(&bytes),
        calls: 0,
    };
    let mut replay = Replay::new(reader, bytes.len() as u64, 0, state).unwrap();
    let verifier = AuthorizationVerifier::new();
    for height in 1..=3 {
        let block = replay.next_block(&verifier).unwrap().unwrap();
        assert_eq!(block.result.height, height);
        assert!(block.transactions.is_empty());
    }
    assert!(replay.next_block(&verifier).unwrap().is_none());
    assert!(replay.next_block(&verifier).unwrap().is_none());
    assert_eq!(replay.finish().unwrap().1, expected);
}

#[test]
fn declared_size_and_record_count_are_bounded_before_body_allocation() {
    for n in [0, 113, MAX_RECORD_BYTES as u32 + 1, u32::MAX] {
        let prefix = n.to_be_bytes();
        let mut records = Records::new(Cursor::new(prefix), MAX_JOURNAL_BYTES, 0).unwrap();
        assert!(matches!(records.next(), Err(PoolError::Bounds)));
        assert_eq!(records.body.capacity(), 0);
        assert_eq!(records.reader.position(), 4);
    }
    let mut records = Records::new(Cursor::new(114u32.to_be_bytes()), 4, 0).unwrap();
    assert!(matches!(records.next(), Err(PoolError::Corrupt)));
    assert_eq!(records.body.capacity(), 0);
    let mut records = Records::new(Cursor::new([0; 4]), 4, 0).unwrap();
    records.count = MAX_RECORDS;
    assert!(matches!(records.next(), Err(PoolError::Bounds)));
    assert_eq!(records.reader.position(), 0);
    assert_eq!(records.body.capacity(), 0);
    assert!(matches!(
        Records::new(Cursor::new([]), 0, 1),
        Err(PoolError::Bounds)
    ));
    assert!(matches!(
        Records::new(Cursor::new([]), u64::MAX, 0),
        Err(PoolError::Bounds)
    ));
}

#[test]
fn every_truncated_frame_and_appended_byte_is_rejected() {
    let (bytes, expected) = empty_chain(2);
    assert_eq!(finish_bytes(&bytes, bytes.len() as u64).unwrap(), expected);
    for cut in 0..bytes.len() {
        assert!(
            finish_bytes(&bytes[..cut], bytes.len() as u64).is_err(),
            "captured cut {cut}"
        );
        // A complete prefix is a legitimate shorter chain in the absence of an
        // independent checkpoint. Only partial records are inherently corrupt.
        if cut != 0 && cut != 150 {
            assert!(
                finish_bytes(&bytes[..cut], cut as u64).is_err(),
                "partial cut {cut}"
            );
        }
    }
    let mut longer = bytes.clone();
    longer.push(0);
    assert!(finish_bytes(&longer, bytes.len() as u64).is_err());
    assert!(finish_bytes(&longer, longer.len() as u64).is_err());
}

#[test]
fn a_complete_shorter_prefix_still_requires_an_independent_checkpoint() {
    let (bytes, expected) = empty_chain(2);
    let shorter = finish_bytes(&bytes[..150], 150).unwrap();
    assert_eq!(shorter.height, 1);
    assert_ne!(shorter.app_hash, expected.app_hash);
}

#[test]
fn checksum_mutations_and_structural_corruption_do_not_replay() {
    let (bytes, _) = empty_chain(1);
    for i in 4..bytes.len() {
        let mut changed = bytes.clone();
        changed[i] ^= 1;
        assert!(
            finish_bytes(&changed, changed.len() as u64).is_err(),
            "offset {i}"
        );
    }
    for offset in [0, 8, 16, 48, 80, 112] {
        let mut body = bytes[4..118].to_vec();
        body[offset] ^= 1;
        let mut altered = 114u32.to_be_bytes().to_vec();
        altered.extend_from_slice(&body);
        altered.extend_from_slice(&Sha256::digest(&body));
        assert!(
            finish_bytes(&altered, altered.len() as u64).is_err(),
            "rehashed body offset {offset}"
        );
    }
}

#[test]
fn finish_requires_verified_eof_and_errors_permanently_poison_replay() {
    let (bytes, _) = empty_chain(2);
    let verifier = AuthorizationVerifier::new();
    let state = State::from_policy(&[], None).unwrap();
    let mut replay = Replay::new(Cursor::new(&bytes), bytes.len() as u64, 0, state).unwrap();
    replay.next_block(&verifier).unwrap();
    assert!(matches!(replay.finish(), Err(PoolError::Unavailable)));
    // Even after both bodies have been consumed, the extra EOF read remains
    // mandatory. A same-length snapshot is not evidence that no suffix exists.
    let state = State::from_policy(&[], None).unwrap();
    let mut replay = Replay::new(Cursor::new(&bytes), bytes.len() as u64, 0, state).unwrap();
    replay.next_block(&verifier).unwrap();
    replay.next_block(&verifier).unwrap();
    assert!(matches!(replay.finish(), Err(PoolError::Unavailable)));
    let mut bad = bytes;
    let last = bad.len() - 1;
    bad[last] ^= 1;
    let state = State::from_policy(&[], None).unwrap();
    let mut replay = Replay::new(Cursor::new(&bad), bad.len() as u64, 0, state).unwrap();
    assert_eq!(
        replay.next_block(&verifier).unwrap().unwrap().result.height,
        1
    );
    assert!(matches!(
        replay.next_block(&verifier),
        Err(PoolError::Corrupt)
    ));
    assert!(replay.state.is_none());
    assert!(matches!(
        replay.next_block(&verifier),
        Err(PoolError::Unavailable)
    ));
    assert!(matches!(replay.finish(), Err(PoolError::Unavailable)));
}

struct FailedReader;
impl Read for FailedReader {
    fn read(&mut self, _: &mut [u8]) -> std::io::Result<usize> {
        Err(std::io::Error::from(ErrorKind::Other))
    }
}

#[test]
fn input_failure_is_never_converted_to_a_successful_empty_history() {
    for length in [0, 150] {
        let state = State::from_policy(&[], None).unwrap();
        let mut replay = Replay::new(FailedReader, length, 0, state).unwrap();
        let verifier = AuthorizationVerifier::new();
        assert!(replay.next_block(&verifier).is_err());
        assert!(replay.state.is_none());
        assert!(matches!(replay.finish(), Err(PoolError::Unavailable)));
    }
}

#[test]
fn maximum_record_window_is_replayed_without_copying_the_full_state_per_block() {
    let (bytes, expected) = empty_chain(MAX_RECORDS);
    COPYING_EXECUTIONS.with(|c| assert!(c.get() >= MAX_RECORDS as usize));
    COPYING_EXECUTIONS.with(|c| c.set(0));
    assert_eq!(finish_bytes(&bytes, bytes.len() as u64).unwrap(), expected);
    COPYING_EXECUTIONS.with(|c| assert_eq!(c.get(), 0));
    // Extra records cannot be silently skipped after the allowed height window.
    let mut excessive = bytes;
    excessive.extend_from_within(..150);
    assert!(matches!(
        finish_bytes(&excessive, excessive.len() as u64),
        Err(PoolError::Bounds)
    ));
}

struct TestDir(std::path::PathBuf);
impl TestDir {
    fn new() -> Self {
        use rand::{rngs::OsRng, RngCore};
        let mut id = [0; 16];
        OsRng.fill_bytes(&mut id);
        let name: String = id.iter().map(|b| format!("{b:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-replay-{name}"));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn path(&self, name: &str) -> std::path::PathBuf {
        self.0.join(name)
    }
}
impl Drop for TestDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[test]
fn startup_and_wallet_history_share_replay_and_preserve_journal_bytes() {
    let dir = TestDir::new();
    let path = dir.path("legacy.journal");
    let (bytes, expected) = empty_chain(32);
    let mut file = genesis_bytes_policy(&[], None).unwrap();
    file.extend_from_slice(&bytes);
    std::fs::write(&path, &file).unwrap();
    COPYING_EXECUTIONS.with(|c| c.set(0));
    let mut pool = PoolStore::open(&path).unwrap();
    assert_eq!(pool.summary().unwrap(), expected);
    let history = pool.wallet_history().unwrap();
    assert_eq!(history.tip(), &expected);
    assert_eq!(history.blocks.len(), 32);
    COPYING_EXECUTIONS.with(|c| assert_eq!(c.get(), 0));
    pool.file.rewind().unwrap();
    let mut after = Vec::new();
    pool.file.read_to_end(&mut after).unwrap();
    assert_eq!(after, file);
    // Use the owning handle: a second file handle is not allowed to read/write
    // a locked file on every platform, notably the Windows test runner.
    pool.file.write_all(&[0]).unwrap();
    let damaged_size = pool.file.metadata().unwrap().len();
    assert!(pool.wallet_history().is_err());
    assert!(matches!(pool.summary(), Err(PoolError::Unavailable)));
    assert_eq!(pool.file.metadata().unwrap().len(), damaged_size);
}

#[cfg(feature = "local-funding-lab")]
#[test]
fn real_bound_payments_replay_and_partly_valid_blocks_are_discarded() {
    use crate::pool::testnet::TestGenesis;
    use crate::wallet::{Wallet, WalletProver};
    let dir = TestDir::new();
    let path = dir.path("bound.journal");
    let mut alice = Wallet::create().unwrap();
    let mut bob = Wallet::create().unwrap();
    let genesis = TestGenesis::generate(&[(alice.receive_address(0).unwrap(), 100_000)]).unwrap();
    let mut pool = genesis.create_pool(&path).unwrap();
    let initial = pool.state.clone();
    let initial_summary = pool.summary().unwrap();
    alice
        .sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    let prover = WalletProver::new();
    let payment = alice
        .build_payment(bob.receive_address(0).unwrap(), 30_000, 100, 100, &prover)
        .unwrap();
    let raw = payment.bytes().to_vec();
    let valid = pool
        .prepare(1, [1; 32], std::slice::from_ref(&raw))
        .unwrap();
    let expected = pool.commit(valid).unwrap();
    let valid_result = expected.app_hash;
    // A genuine first transaction followed by a duplicate fails late, after
    // the isolated reconstruction has applied the first. No state can escape.
    let bytes = frame(&Record {
        height: 1,
        block_id: [1; 32],
        base_hash: initial_summary.app_hash,
        result_hash: valid_result,
        transactions: vec![raw.clone(), raw.clone()],
    });
    let verifier = AuthorizationVerifier::new();
    let mut replay =
        Replay::new(Cursor::new(&bytes), bytes.len() as u64, 0, initial.clone()).unwrap();
    assert!(matches!(
        replay.next_block(&verifier),
        Err(PoolError::DoubleSpend)
    ));
    assert!(replay.state.is_none());
    assert!(matches!(
        replay.next_block(&verifier),
        Err(PoolError::Unavailable)
    ));
    assert!(matches!(replay.finish(), Err(PoolError::Unavailable)));
    // A valid authorized payment with a dishonest POST-state hash must also
    // discard the already-mutated isolated state, not return the valid prefix.
    let mut dishonest_result = valid_result;
    dishonest_result[0] ^= 1;
    let bytes = frame(&Record {
        height: 1,
        block_id: [1; 32],
        base_hash: initial_summary.app_hash,
        result_hash: dishonest_result,
        transactions: vec![raw.clone()],
    });
    let mut replay =
        Replay::new(Cursor::new(&bytes), bytes.len() as u64, 0, initial.clone()).unwrap();
    assert!(matches!(
        replay.next_block(&verifier),
        Err(PoolError::Corrupt)
    ));
    assert!(replay.state.is_none());
    assert!(matches!(replay.finish(), Err(PoolError::Unavailable)));
    // Cryptography still matters even if the public checksum and state hash
    // have both been replaced to make the outer record look self-consistent.
    let mut bad_signature = raw.clone();
    *bad_signature.last_mut().unwrap() ^= 1;
    let bytes = frame(&Record {
        height: 1,
        block_id: [1; 32],
        base_hash: initial_summary.app_hash,
        result_hash: valid_result,
        transactions: vec![bad_signature],
    });
    let mut replay = Replay::new(Cursor::new(&bytes), bytes.len() as u64, 0, initial).unwrap();
    assert!(matches!(
        replay.next_block(&verifier),
        Err(PoolError::Authorization)
    ));
    assert!(replay.state.is_none());
    let live_before = pool.summary().unwrap();
    assert!(pool
        .prepare(2, [2; 32], std::slice::from_ref(&raw))
        .is_err());
    assert_eq!(pool.summary().unwrap(), live_before);
    drop(pool);
    COPYING_EXECUTIONS.with(|c| c.set(0));
    let mut pool = genesis.open_pool(&path).unwrap();
    let history = genesis.wallet_history(&mut pool).unwrap();
    assert_eq!(history.tip(), &expected);
    assert_eq!(history.blocks[0].transactions, vec![raw]);
    bob.sync(&history).unwrap();
    assert_eq!(bob.balance().unwrap(), 30_000);
    COPYING_EXECUTIONS.with(|c| assert_eq!(c.get(), 0));
    // The restored receiver can really spend, not just display a test balance.
    let second = bob
        .build_payment(alice.receive_address(1).unwrap(), 10_000, 100, 100, &prover)
        .unwrap();
    let candidate = pool
        .prepare(2, [2; 32], &[second.bytes().to_vec()])
        .unwrap();
    let tip = pool.commit(candidate).unwrap();
    drop(pool);
    let mut pool = genesis.open_pool(&path).unwrap();
    assert_eq!(pool.summary().unwrap(), tip);
    bob.sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    assert_eq!(bob.balance().unwrap(), 19_900);
}

struct FailsAt<'a> {
    input: Cursor<&'a [u8]>,
    cut: usize,
}
impl Read for FailsAt<'_> {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        let position = self.input.position() as usize;
        if position >= self.cut {
            return Err(std::io::Error::from(ErrorKind::Other));
        }
        let amount = buf.len().min(self.cut - position);
        self.input.read(&mut buf[..amount])
    }
}

#[test]
fn io_fault_at_every_record_byte_including_final_eof_drops_the_reconstruction() {
    let (bytes, _) = empty_chain(2);
    let verifier = AuthorizationVerifier::new();
    for cut in 0..=bytes.len() {
        let state = State::from_policy(&[], None).unwrap();
        let input = FailsAt {
            input: Cursor::new(bytes.as_slice()),
            cut,
        };
        let mut replay = Replay::new(input, bytes.len() as u64, 0, state).unwrap();
        loop {
            match replay.next_block(&verifier) {
                Ok(Some(_)) => (),
                Ok(None) => panic!("I/O failure became success at {cut}"),
                Err(_) => break,
            }
        }
        assert!(replay.state.is_none(), "cut {cut}");
        assert!(matches!(
            replay.next_block(&verifier),
            Err(PoolError::Unavailable)
        ));
        assert!(matches!(replay.finish(), Err(PoolError::Unavailable)));
    }
}

#[test]
fn reusable_buffer_does_not_decode_stale_tail_bytes_after_a_shorter_record() {
    // Structurally framed bytes only, NOT valid payment proofs. No fake
    // authorization component is used, and Replay would reject this payload.
    let long = Record {
        height: 1,
        block_id: [1; 32],
        base_hash: [2; 32],
        result_hash: [3; 32],
        transactions: vec![vec![7; crate::wire::MAX_ENVELOPE_SIZE]; 16],
    };
    let short = Record {
        height: 2,
        block_id: [4; 32],
        base_hash: [3; 32],
        result_hash: [5; 32],
        transactions: Vec::new(),
    };
    let mut bytes = frame(&long);
    bytes.extend_from_slice(&frame(&short));
    let mut records = Records::new(Cursor::new(&bytes), bytes.len() as u64, 0).unwrap();
    assert_eq!(
        records.next().unwrap().unwrap().encode().unwrap(),
        long.encode().unwrap()
    );
    assert_eq!(records.body.len(), MAX_RECORD_BYTES);
    let capacity = records.body.capacity();
    assert_eq!(
        records.next().unwrap().unwrap().encode().unwrap(),
        short.encode().unwrap()
    );
    assert_eq!(records.body.len(), 114);
    assert_eq!(records.body.capacity(), capacity);
    assert!(records.next().unwrap().is_none());
}
