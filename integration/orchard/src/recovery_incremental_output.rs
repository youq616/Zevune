//! Bounded rendering of a verified read-only plan, never an importable update.
use std::fmt::Write as _;
use zevune_orchard_lab::pool::recovery::active::incremental::ActiveIncrementalPlan;

pub(super) fn emit(plan: &ActiveIncrementalPlan) -> Result<(), ()> {
    let ranges = plan.ranges();
    if ranges.len() > 2048 {
        return Err(());
    }
    // Two fixed 256-character pins and bounded numbers/flags fit in the base
    // allowance; each range has at most three u32 values and fixed ASCII keys.
    let capacity = ranges
        .len()
        .checked_mul(96)
        .and_then(|value| value.checked_add(2048))
        .ok_or(())?;
    let mut text = String::new();
    text.try_reserve_exact(capacity).map_err(|_| ())?;
    let base = plan.base_checkpoint();
    let later = plan.checkpoint();
    write!(
        text,
        concat!(
            "{{\"format\":\"zevune-active-incremental-plan-1\",",
            "\"operation\":\"plan-active-incremental\",",
            "\"base_checkpoint\":\"{}\",\"checkpoint\":\"{}\",",
            "\"base_height\":{},\"height\":{},\"base_bytes\":{},\"bytes\":{},",
            "\"reused_bytes\":{},\"appended_bytes\":{},",
            "\"unchanged_segment_count\":{},\"new_segment_count\":{},\"ranges\":["
        ),
        super::hex(&base.to_bytes()),
        super::hex(&later.to_bytes()),
        base.height(),
        later.height(),
        base.length(),
        later.length(),
        plan.reused_bytes(),
        plan.appended_bytes(),
        plan.unchanged_segment_count(),
        plan.new_segment_count(),
    )
    .map_err(|_| ())?;
    for (index, range) in ranges.iter().enumerate() {
        if index != 0 {
            text.push(',');
        }
        write!(
            text,
            "{{\"segment_index\":{},\"offset\":{},\"length\":{}}}",
            range.segment_index(),
            range.offset(),
            range.length(),
        )
        .map_err(|_| ())?;
    }
    text.push_str(concat!(
        "],\"replay_verified\":true,\"byte_prefix_verified\":true,",
        "\"incremental_backup_written\":false,\"snapshot_imported\":false,",
        "\"finality_verified\":false,\"validator_ready\":false,",
        "\"real_funds_allowed\":false}\n"
    ));
    if text.len() > capacity || !text.is_ascii() {
        return Err(());
    }
    // No output before complete verification and rendering. The existing safe
    // File-backed stdout path propagates errors, including a read-only handle.
    super::write_active_receipt(text.as_bytes())
}
