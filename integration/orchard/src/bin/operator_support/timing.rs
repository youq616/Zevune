//! Local diagnostic timing only: never part of a signature, journal or consensus.
//! A broken clock invalidates the measurement, not an already saved payment.
use std::time::Instant;

const LABELS: [&str; 5] = [
    "setup_and_sync",
    "intent_preflight",
    "prover_parameters",
    "prove_sign_verify_persist",
    "export",
];

pub(super) struct PrepareTiming {
    start: Instant,
    last: Instant,
    values: [Option<u64>; 5],
    count: usize,
    valid: bool,
}

impl PrepareTiming {
    pub(super) fn start() -> Self {
        let now = Instant::now();
        Self {
            start: now,
            last: now,
            values: [None; 5],
            count: 0,
            valid: true,
        }
    }
    pub(super) fn mark(&mut self) {
        self.record(Instant::now());
    }
    fn record(&mut self, now: Instant) {
        if self.count >= self.values.len() {
            self.valid = false;
            return;
        }
        self.values[self.count] = now
            .checked_duration_since(self.last)
            .and_then(|v| u64::try_from(v.as_micros()).ok());
        self.valid &= self.values[self.count].is_some();
        self.last = now;
        self.count += 1;
    }
    pub(super) fn json(&self) -> String {
        let total = self
            .last
            .checked_duration_since(self.start)
            .and_then(|v| u64::try_from(v.as_micros()).ok());
        let valid = self.valid && self.count == self.values.len() && total.is_some();
        let number = |value: Option<u64>| {
            if valid {
                value
                    .map(|v| v.to_string())
                    .unwrap_or_else(|| "null".into())
            } else {
                "null".into()
            }
        };
        let stages: Vec<String> = LABELS
            .iter()
            .zip(self.values)
            .map(|(label, value)| format!("\"{label}\":{}", number(value)))
            .collect();
        format!(
            "\"local_timing\":{{\"format\":\"zevune-prepare-timing-1\",\"scope\":\"local_prepare_not_finality\",\"unit\":\"microseconds\",\"valid\":{valid},\"stages\":{{{}}},\"total\":{}}}",
            stages.join(","),
            number(total)
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn stages_are_disjoint_and_total_includes_rounding_remainder() {
        let mut timing = PrepareTiming::start();
        for i in 1..=5 {
            timing.record(timing.start + Duration::from_nanos(i * 1_500));
        }
        assert_eq!(timing.values, [Some(1); 5]);
        let json = timing.json();
        assert!(json.contains("\"valid\":true"));
        assert!(json.ends_with("\"total\":7}"));
        for label in LABELS {
            assert!(json.contains(&format!("\"{label}\":1")));
        }
    }

    #[test]
    fn reversed_clock_invalidates_all_durations_not_payment_state() {
        let mut timing = PrepareTiming::start();
        timing.record(timing.start + Duration::from_secs(1));
        timing.record(timing.start);
        for _ in 0..3 {
            timing.record(timing.start + Duration::from_secs(2));
        }
        let json = timing.json();
        assert!(json.contains("\"valid\":false"));
        assert_eq!(json.matches(":null").count(), 6);
    }

    #[test]
    fn incomplete_or_extra_stages_do_not_make_a_success_measurement() {
        let mut timing = PrepareTiming::start();
        for _ in 0..5 {
            assert!(timing.json().contains("\"valid\":false"));
            timing.record(timing.start);
        }
        assert!(timing.json().contains("\"valid\":true"));
        timing.record(timing.start);
        assert!(timing.json().contains("\"valid\":false"));
    }
}
