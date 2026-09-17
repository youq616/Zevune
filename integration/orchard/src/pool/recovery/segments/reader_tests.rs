//! Reader-only fault fixtures. No replacement verifier or accepted fake payment.
use super::*;
use std::io::Cursor;

struct Input {
    bytes: Cursor<Vec<u8>>,
    calls: usize,
    short_reads: bool,
    fail_at: Option<(u64, io::ErrorKind)>,
}
impl Input {
    fn new(bytes: &[u8]) -> Self {
        Self {
            bytes: Cursor::new(bytes.to_vec()),
            calls: 0,
            short_reads: false,
            fail_at: None,
        }
    }
}
impl Read for Input {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        self.calls += 1;
        if let Some((at, kind)) = self.fail_at {
            if self.bytes.position() >= at {
                self.fail_at = None; // The source would recover; the reader must not.
                return Err(kind.into());
            }
        }
        let mut n = out.len();
        if self.short_reads {
            n = n.min(1);
        }
        if let Some((at, _)) = self.fail_at {
            n = n.min((at - self.bytes.position()) as usize);
        }
        self.bytes.read(&mut out[..n])
    }
}
fn entry(length: u32) -> Entry {
    Entry {
        length,
        hash: [0; 32],
    }
}
fn reader<'a, R: Read>(files: &'a mut [R], entries: &'a [Entry]) -> SegmentReader<'a, R> {
    SegmentReader {
        files,
        entries,
        index: 0,
        position: 0,
        failed: false,
    }
}

#[test]
fn hard_io_failure_at_each_boundary_permanently_invalidates_reader() {
    for segment in 0..2 {
        for offset in 0..=3 {
            let mut inputs = [Input::new(b"abc"), Input::new(b"def")];
            inputs[segment].fail_at = Some((offset, io::ErrorKind::PermissionDenied));
            let entries = [entry(3), entry(3)];
            let mut r = reader(&mut inputs, &entries);
            let mut out = Vec::new();
            assert!(
                r.read_to_end(&mut out).is_err(),
                "segment {segment}, offset {offset}"
            );
            assert!(r.failed);
            let calls: Vec<_> = r.files.iter().map(|f| f.calls).collect();
            for _ in 0..3 {
                assert!(r.read(&mut [0; 8]).is_err());
                assert_eq!(r.read(&mut []).unwrap(), 0);
            }
            assert_eq!(r.files.iter().map(|f| f.calls).collect::<Vec<_>>(), calls);
        }
    }
}

#[test]
fn interrupted_short_reads_and_segment_end_checks_do_not_poison_reader() {
    for segment in 0..2 {
        for offset in 0..=3 {
            let mut inputs = [Input::new(b"abc"), Input::new(b"def")];
            for input in &mut inputs {
                input.short_reads = true;
            }
            inputs[segment].fail_at = Some((offset, io::ErrorKind::Interrupted));
            let entries = [entry(3), entry(3)];
            let mut r = reader(&mut inputs, &entries);
            let mut bytes = [0; 6];
            r.read_exact(&mut bytes).unwrap();
            assert_eq!(&bytes, b"abcdef");
            require_eof(&mut r).unwrap();
            assert!(!r.failed);
            assert_eq!(r.read(&mut [0; 1]).unwrap(), 0);
        }
    }
}

#[test]
fn truncated_or_extended_segment_cannot_be_skipped_by_retry() {
    for bad in [b"ab".as_slice(), b"abcd".as_slice()] {
        let mut inputs = [Input::new(bad), Input::new(b"def")];
        let entries = [entry(3), entry(3)];
        let mut r = reader(&mut inputs, &entries);
        assert!(r.read_to_end(&mut Vec::new()).is_err());
        assert_eq!(r.index, 0);
        assert_eq!(r.files[1].calls, 0); // Never consumes the next segment.
        assert!(r.failed);
        assert!(r.read(&mut [0; 8]).is_err());
        assert_eq!(r.files[1].calls, 0);
    }
}

#[test]
fn exact_payload_requires_last_segment_eof_check_before_success() {
    let mut inputs = [Input::new(b"abc"), Input::new(b"def!")];
    let entries = [entry(3), entry(3)];
    let mut r = reader(&mut inputs, &entries);
    let mut bytes = [0; 6];
    r.read_exact(&mut bytes).unwrap();
    assert_eq!(&bytes, b"abcdef");
    assert!(require_eof(&mut r).is_err());
    assert!(r.failed);
    // The extra byte was consumed by the probe, but cannot become EOF on retry.
    assert!(require_eof(&mut r).is_err());
}

#[test]
fn inconsistent_private_reader_metadata_returns_error_instead_of_panicking() {
    let mut inputs = [Input::new(b"abc")];
    let mut r = reader(&mut inputs, &[]);
    assert_eq!(
        r.read(&mut [0; 8]).unwrap_err().kind(),
        io::ErrorKind::InvalidData
    );
    for n in [0, SEGMENT_BYTES as u32 + 1] {
        let entries = [entry(n)];
        let mut r = reader(&mut inputs, &entries);
        assert_eq!(
            r.read(&mut [0; 8]).unwrap_err().kind(),
            io::ErrorKind::InvalidData
        );
    }
    let entries = [entry(3)];
    let mut r = reader(&mut inputs, &entries);
    r.position = 4;
    assert_eq!(
        r.read(&mut [0; 8]).unwrap_err().kind(),
        io::ErrorKind::InvalidData
    );
}
