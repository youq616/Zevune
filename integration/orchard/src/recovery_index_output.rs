//! CLI-only rendering of already verified public historical index metadata.
use std::fmt::Write as _;
use std::io::Write as _;
use zevune_orchard_lab::pool::recovery::segments::index::VerifiedIndex;
use zevune_orchard_lab::pool::recovery::segments::SEGMENT_BYTES;

pub(super) fn emit(index: &VerifiedIndex, height: Option<u64>) -> Result<(), ()> {
    let records = match height {
        Some(height) => std::slice::from_ref(index.locate_height(height).map_err(|_| ())?),
        None => index.records(),
    };
    // Counts already bound by replay; still cap report size BEFORE allocation.
    let capacity = records
        .len()
        .checked_mul(500)
        .and_then(|n| n.checked_add(1024))
        .ok_or(())?;
    if capacity > 5 * 1024 * 1024 {
        return Err(());
    }
    let mut text = String::new();
    text.try_reserve_exact(capacity).map_err(|_| ())?;
    let pin = index.checkpoint();
    let mode = if height.is_some() {
        "locate-height"
    } else {
        "index"
    };
    write!(text, "{{\"format\":\"zevune-backup-index-1\",\"operation\":\"{mode}\",\"checkpoint\":\"{}\",\"height\":{},\"bytes\":{},\"header_bytes\":{},\"segment_bytes\":{},\"total_records\":{},\"replay_verified\":true,\"finality_verified\":false,\"validator_ready\":false,\"real_funds_allowed\":false,\"scope\":\"historical_navigation_not_current_path_authorization\",\"records\":[", super::hex(&pin.to_bytes()), pin.height(), pin.length(), index.header_bytes(), SEGMENT_BYTES, index.records().len()).map_err(|_| ())?;
    for (position, record) in records.iter().enumerate() {
        if position != 0 {
            text.push(',');
        }
        write!(text, "{{\"height\":{},\"offset\":{},\"length\":{},\"first_segment\":{},\"last_segment\":{},\"first_segment_offset\":{},\"last_segment_end\":{},\"before_app_hash\":\"{}\",\"after_app_hash\":\"{}\"}}", record.height(),record.offset(),record.length(),record.first_segment(),record.last_segment(),record.first_segment_offset(),record.last_segment_end(),super::hex(&record.before_app_hash()),super::hex(&record.after_app_hash())).map_err(|_| ())?;
    }
    text.push_str("]}\n");
    if text.len() > capacity {
        return Err(());
    }
    // Nothing is emitted before full archive verification and complete rendering.
    std::io::stdout()
        .lock()
        .write_all(text.as_bytes())
        .map_err(|_| ())
}
