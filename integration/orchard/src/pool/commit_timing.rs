//! Test-build-only timing of the real store. No runtime feature, environment
//! switch, IPC extension, verifier replacement or timing-dependent state rule.
//! A session belongs to one test thread; nothing is recorded until it opts in.
use std::cell::{Cell, RefCell};
use std::fmt::Write;
use std::marker::PhantomData;
use std::rc::Rc;
use std::time::{Duration, Instant};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(usize)]
pub(super) enum Phase {
    Preflight,
    Reexecute,
    EncodeFrame,
    AppendBounds,
    TailIdentity,
    RotationPrepare,
    Seek,
    WriteFrame,
    FileSync,
    DirectorySync,
    PostIdentity,
    JournalPublish,
    StatePublish,
}
pub(super) const N: usize = 13;
pub(super) const NAMES: [&str; N] = [
    "preflight", "reexecute", "encode_frame", "append_bounds",
    "tail_identity_and_rotation_decision", "rotation_prepare", "seek",
    "write_frame", "file_sync", "directory_sync", "postwrite_identity",
    "journal_metadata_publish", "state_publish",
];
const MAX_ATTEMPTS: u64 = 1_000_001;
const MAX_NS: u64 = 3_600_000_000_000;

#[derive(Clone, Copy, Debug, Default)]
pub(super) struct Metric {
    pub count: u64,
    pub total_ns: u64,
    pub max_ns: u64,
}
impl Metric {
    fn add(&mut self, ns: u64) {
        // At most MAX_ATTEMPTS samples, each <= one hour. No u64 overflow.
        self.count += 1;
        self.total_ns += ns;
        self.max_ns = self.max_ns.max(ns);
    }
}

#[derive(Clone, Debug)]
pub(super) struct Failure {
    pub height: u64,
    pub pending: Option<Phase>,
    pub completed_mask: u16,
    pub elapsed_ns: Option<u64>,
}

#[derive(Clone, Debug)]
pub(super) struct Snapshot {
    pub valid: bool,
    pub attempts: u64,
    pub accepted: u64,
    pub failed: u64,
    pub last_accepted: u64,
    pub paid: u64,
    pub rotated: u64,
    pub total: Metric,
    pub ordinary: [Metric; N],
    pub rotating: [Metric; N],
    pub failure: Option<Failure>,
}
impl Snapshot {
    fn new(height: u64) -> Self {
        Self {
            valid: true, attempts: 0, accepted: 0, failed: 0,
            last_accepted: height, paid: 0, rotated: 0,
            total: Metric::default(), ordinary: [Metric::default(); N],
            rotating: [Metric::default(); N], failure: None,
        }
    }

    /// Fixed public schema; no input bytes, addresses, file paths or errors.
    /// This is not a completion certificate: the native test must also pass.
    pub fn json(&self) -> String {
        let mut out = format!(
            "{{\"schema_version\":1,\"scope\":\"test_store_internal_not_worker_ipc\",\"valid\":{},\"attempts\":{},\"accepted\":{},\"failed\":{},\"last_accepted_height\":{},\"paid\":{},\"rotated\":{},\"accepted_commit_total_ns\":{},\"accepted_commit_max_ns\":{},\"phases\":[",
            self.valid, self.attempts, self.accepted, self.failed,
            self.last_accepted, self.paid, self.rotated,
            self.total.total_ns, self.total.max_ns,
        );
        for (i, name) in NAMES.iter().enumerate() {
            if i != 0 { out.push(','); }
            let a = self.ordinary[i];
            let b = self.rotating[i];
            write!(out,
                "{{\"name\":\"{name}\",\"ordinary_count\":{},\"ordinary_total_ns\":{},\"ordinary_max_ns\":{},\"rotating_count\":{},\"rotating_total_ns\":{},\"rotating_max_ns\":{}}}",
                a.count, a.total_ns, a.max_ns, b.count, b.total_ns, b.max_ns,
            ).unwrap();
        }
        out.push_str("],\"last_failed_attempt\":");
        if let Some(f) = &self.failure {
            let pending = f.pending.map_or("null".to_owned(), |p| format!("\"{}\"", NAMES[p as usize]));
            let elapsed = f.elapsed_ns.map_or("null".to_owned(), |n| n.to_string());
            write!(out, "{{\"height\":{},\"pending\":{},\"completed_phase_mask\":{},\"elapsed_ns\":{},\"disk_outcome_not_inferred\":true}}", f.height, pending, f.completed_mask, elapsed).unwrap();
        } else {
            out.push_str("null");
        }
        out.push('}');
        assert!(out.len() <= 16 * 1024, "timing report exceeded fixed bound");
        out
    }
}

struct Current {
    height: u64,
    paid: bool,
    rotate: bool,
    started: Instant,
    last: Instant,
    pending: Option<(Phase, Instant)>,
    durations: [Option<u64>; N],
}
struct Recording {
    id: u64,
    snapshot: Snapshot,
    current: Option<Current>,
}
thread_local! {
    static RECORDING: RefCell<Option<Recording>> = const { RefCell::new(None) };
    static NEXT_ID: Cell<u64> = const { Cell::new(0) };
}

// Neither owner can move to another thread. IDs prevent a stale attempt or
// session destructor from changing a later recording; nested starts are refused.
pub(super) struct Session(u64, PhantomData<Rc<()>>);
impl Session {
    pub fn start(height: u64) -> Self {
        assert!(height <= 1_000_000, "invalid timing start height");
        let id = NEXT_ID.with(|n| { let next = n.get().checked_add(1).unwrap(); n.set(next); next });
        RECORDING.with(|slot| {
            let mut slot = slot.borrow_mut();
            assert!(slot.is_none(), "nested timing session");
            *slot = Some(Recording { id, snapshot: Snapshot::new(height), current: None });
        });
        Self(id, PhantomData)
    }
    pub fn finish(self) -> Snapshot {
        RECORDING.with(|slot| {
            let mut slot = slot.borrow_mut();
            assert_eq!(slot.as_ref().unwrap().id, self.0);
            assert!(slot.as_ref().unwrap().current.is_none(), "live timing attempt");
            slot.take().unwrap().snapshot
        })
    }
}
impl Drop for Session {
    fn drop(&mut self) {
        RECORDING.with(|slot| {
            let mut slot = slot.borrow_mut();
            if slot.as_ref().is_some_and(|r| r.id == self.0) { slot.take(); }
        });
    }
}

fn elapsed(now: Instant, earlier: Instant) -> Option<u64> {
    let value = now.checked_duration_since(earlier)?;
    if value > Duration::from_secs(3_600) { return None; }
    u64::try_from(value.as_nanos()).ok()
}

pub(super) struct Attempt {
    recording: Option<u64>,
    finished: bool,
    _thread: PhantomData<Rc<()>>,
}
impl Attempt {
    pub fn start(active: bool, height: u64, paid: bool) -> Self {
        let recording = if active { RECORDING.with(|slot| {
            let mut slot = slot.borrow_mut();
            let Some(r) = slot.as_mut() else { return None; };
            if r.current.is_some() || r.snapshot.attempts >= MAX_ATTEMPTS {
                r.snapshot.valid = false;
                return None;
            }
            r.snapshot.attempts += 1;
            let now = Instant::now();
            r.current = Some(Current {
                height, paid, rotate: false, started: now, last: now,
                pending: None, durations: [None; N],
            });
            Some(r.id)
        }) } else { None };
        Self { recording, finished: false, _thread: PhantomData }
    }

    // ONLY called after actual store state and length publication, just before
    // the existing Ok(result). Prior sync or append completion is insufficient.
    pub fn accept(mut self) {
        if let Some(id) = self.recording {
            RECORDING.with(|slot| {
                let mut slot = slot.borrow_mut();
                let Some(r) = slot.as_mut() else { return; };
                if r.id != id { return; }
                let Some(c) = r.current.take() else { r.snapshot.valid = false; return; };
                let s = &mut r.snapshot;
                let total = elapsed(Instant::now(), c.started);
                let mut sum = 0u64;
                for (i, ns) in c.durations.iter().enumerate() {
                    let required = c.rotate || (i != Phase::RotationPrepare as usize && i != Phase::DirectorySync as usize);
                    if ns.is_some() != required { s.valid = false; }
                    if let Some(ns) = ns { sum += ns; }
                }
                if c.pending.is_some() || total.is_none_or(|n| sum > n) || c.height != s.last_accepted + 1 {
                    s.valid = false;
                }
                // These are real API outcomes even if the timing inventory is
                // invalid; invalid timing is never presented as a valid sample.
                s.accepted += 1;
                s.last_accepted = c.height;
                s.paid += u64::from(c.paid);
                s.rotated += u64::from(c.rotate);
                if let Some(total) = total { s.total.add(total); }
                let group = if c.rotate { &mut s.rotating } else { &mut s.ordinary };
                for (metric, ns) in group.iter_mut().zip(c.durations) {
                    if let Some(ns) = ns { metric.add(ns); }
                }
            });
        }
        self.finished = true;
    }
}
impl Drop for Attempt {
    fn drop(&mut self) {
        let Some(id) = self.recording else { return; };
        if self.finished { return; }
        RECORDING.with(|slot| {
            let mut slot = slot.borrow_mut();
            let Some(r) = slot.as_mut() else { return; };
            if r.id != id { return; }
            let Some(c) = r.current.take() else { r.snapshot.valid = false; return; };
            r.snapshot.failed += 1;
            let duration = if r.snapshot.valid { elapsed(Instant::now(), c.started) } else { None };
            if duration.is_none() { r.snapshot.valid = false; }
            r.snapshot.failure = Some(Failure {
                height: c.height, pending: c.pending.map(|p| p.0),
                completed_mask: c.durations.iter().enumerate().fold(0, |mask, (i, n)| mask | (u16::from(n.is_some()) << i)),
                elapsed_ns: duration,
            });
            // In particular, phase durations of failed attempts are NOT mixed
            // into the successful-commit aggregate. Disk outcome stays unknown.
        });
    }
}

pub(super) fn begin(phase: Phase) {
    RECORDING.with(|slot| {
        let mut slot = slot.borrow_mut();
        let Some(r) = slot.as_mut() else { return; };
        let Some(c) = r.current.as_mut() else { return; };
        let now = Instant::now();
        let mut expected = c.durations.iter().rposition(Option::is_some).map_or(0, |p| p + 1);
        if !c.rotate && (expected == Phase::RotationPrepare as usize || expected == Phase::DirectorySync as usize) { expected += 1; }
        if phase as usize != expected || c.pending.is_some() || c.durations[phase as usize].is_some() || elapsed(now, c.last).is_none() {
            r.snapshot.valid = false;
            return;
        }
        c.last = now;
        c.pending = Some((phase, now));
    });
}
pub(super) fn end() {
    RECORDING.with(|slot| {
        let mut slot = slot.borrow_mut();
        let Some(r) = slot.as_mut() else { return; };
        let Some(c) = r.current.as_mut() else { return; };
        let Some((phase, start)) = c.pending.take() else { r.snapshot.valid = false; return; };
        let now = Instant::now();
        let ns = elapsed(now, start);
        if ns.is_none() || elapsed(now, c.last).is_none() { r.snapshot.valid = false; }
        c.durations[phase as usize] = ns;
        c.last = now;
    });
}
pub(super) fn rotation(value: bool) {
    RECORDING.with(|slot| {
        if let Some(c) = slot.borrow_mut().as_mut().and_then(|r| r.current.as_mut()) { c.rotate = value; }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn incomplete_attempt_never_increments_accepted_or_phase_totals() {
        let s = Session::start(0);
        {
            let _a = Attempt::start(true, 1, false);
            for phase in [Phase::Preflight, Phase::Reexecute, Phase::EncodeFrame, Phase::AppendBounds, Phase::TailIdentity, Phase::Seek, Phase::WriteFrame] { begin(phase); end(); }
            begin(Phase::FileSync);
        }
        let r = s.finish();
        assert!(r.valid);
        assert_eq!((r.attempts, r.accepted, r.failed, r.last_accepted), (1, 0, 1, 0));
        assert_eq!(r.failure.as_ref().unwrap().pending, Some(Phase::FileSync));
        assert!(r.ordinary.iter().all(|m| m.count == 0));
        assert_eq!(r.total.count, 0);
        assert!(r.json().contains("\"disk_outcome_not_inferred\":true"));
    }

    #[test]
    fn missing_and_duplicate_phase_samples_are_invalid() {
        for omitted in 0..N {
            let s = Session::start(0);
            let a = Attempt::start(true, 1, false);
            rotation(true);
            for phase in [Phase::Preflight, Phase::Reexecute, Phase::EncodeFrame, Phase::AppendBounds, Phase::TailIdentity, Phase::RotationPrepare, Phase::Seek, Phase::WriteFrame, Phase::FileSync, Phase::DirectorySync, Phase::PostIdentity, Phase::JournalPublish, Phase::StatePublish] {
                if phase as usize != omitted { begin(phase); end(); }
            }
            a.accept();
            assert!(!s.finish().valid);
        }
        let s = Session::start(0);
        let a = Attempt::start(true, 1, false);
        begin(Phase::Preflight); end(); begin(Phase::Preflight); end();
        a.accept();
        assert!(!s.finish().valid);
    }

    #[test]
    fn invalid_duration_is_unknown_and_sessions_are_thread_local() {
        let now = Instant::now();
        assert_eq!(elapsed(now, now + Duration::from_secs(1)), None);
        assert_eq!(elapsed(now + Duration::from_secs(3601), now), None);
        assert!(MAX_ATTEMPTS.checked_mul(MAX_NS).is_some());
        let s = Session::start(10);
        std::thread::spawn(|| {
            let _a = Attempt::start(true, 99, true);
            begin(Phase::Preflight); end();
        }).join().unwrap();
        assert_eq!(s.finish().attempts, 0);
        // A panic unwinds the session rather than leaking into the next test.
        assert!(std::panic::catch_unwind(|| { let _s = Session::start(0); panic!("test-only session unwind"); }).is_err());
        assert!(Session::start(0).finish().valid);
    }
    #[test]
    fn old_attempt_cannot_change_a_new_session() {
        let old_session = Session::start(0);
        let old_attempt = Attempt::start(true, 1, false);
        drop(old_session);
        let new_session = Session::start(0);
        old_attempt.accept();
        assert_eq!(new_session.finish().attempts, 0);
        let s = Session::start(0);
        let a = Attempt::start(true, 1, false);
        drop(s);
        let next = Session::start(0);
        drop(a);
        assert_eq!(next.finish().failed, 0);
    }

}
