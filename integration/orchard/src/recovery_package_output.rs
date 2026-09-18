//! Bounded receipts after full incremental package verification or recovery.
use std::fmt::Write as _;
use zevune_orchard_lab::pool::recovery::active::package::ActiveIncrementalPackage;

pub(super) fn emit(package: &ActiveIncrementalPackage, operation: &str) -> Result<(), ()> {
    let (written, restored) = match operation {
        "pack-active-incremental" => (true, false),
        "verify-active-incremental" => (false, false),
        "restore-active-incremental" => (false, true),
        _ => return Err(()),
    };
    let plan = package.plan();
    let ranges = plan.ranges();
    if ranges.len() > 2048 {
        return Err(());
    }
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
            "{{\"format\":\"zevune-active-incremental-package-1\",",
            "\"operation\":\"{}\",\"package_format\":\"ZVAIPK01\",",
            "\"package_bytes\":{},\"base_checkpoint\":\"{}\",\"checkpoint\":\"{}\",",
            "\"base_height\":{},\"height\":{},\"base_bytes\":{},\"bytes\":{},",
            "\"reused_bytes\":{},\"appended_bytes\":{},",
            "\"unchanged_segment_count\":{},\"new_segment_count\":{},\"ranges\":["
        ),
        operation,
        package.package_bytes(),
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
    write!(
        text,
        concat!(
            "],\"replay_verified\":true,\"byte_prefix_verified\":true,",
            "\"incremental_backup_written\":{},\"archive_restored\":{},",
            "\"snapshot_imported\":false,\"finality_verified\":false,",
            "\"validator_ready\":false,\"real_funds_allowed\":false}}\n"
        ),
        written, restored,
    )
    .map_err(|_| ())?;
    if text.len() > capacity || !text.is_ascii() {
        return Err(());
    }
    super::write_active_receipt(text.as_bytes())
}
