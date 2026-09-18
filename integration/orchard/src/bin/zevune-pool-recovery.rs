//! Local NO-FUNDS recovery utility. No networking, signer reset or file deletion.
use std::collections::BTreeMap;
use std::io::Write;
use std::path::Path;
use zevune_orchard_lab::pool::recovery::active::package::ActiveIncrementalPackage;
use zevune_orchard_lab::pool::recovery::active::{
    ActiveArchive, ActiveRecoveryCheckpoint, ACTIVE_CHECKPOINT_BYTES,
};
use zevune_orchard_lab::pool::recovery::segments::SegmentedArchive;
use zevune_orchard_lab::pool::recovery::{RecoveryArchive, RecoveryCheckpoint, CHECKPOINT_BYTES};
use zevune_orchard_lab::pool::testnet::TestGenesis;
use zevune_orchard_lab::pool::StorageProfile;

#[path = "../recovery_incremental_output.rs"]
mod incremental_output;
#[path = "../recovery_index_output.rs"]
mod index_output;
#[path = "../recovery_package_output.rs"]
mod package_output;

const HELP: &str = "Zevune PUBLIC journal recovery (NO FUNDS; NOT full validator recovery)\n\
checkpoint --no-real-funds --source <absolute journal> --genesis <absolute manifest> --genesis-sha256 <64 hex> --height <trusted height> --app-hash <trusted hash>\n\
verify --no-real-funds --source <absolute backup> --checkpoint <240 hex independently retained pin>\n\
backup|restore --no-real-funds --source <absolute journal/backup> --output <new absolute path> --checkpoint <240 hex pin>\n\
pack --no-real-funds --source <absolute journal> --output <NEW absolute directory> --checkpoint <240 hex pin>\n\
verify-segments --no-real-funds --source <absolute archive directory> --checkpoint <240 hex pin>\n\
restore-segments --no-real-funds --source <absolute archive directory> --output <NEW absolute journal> --checkpoint <240 hex pin>\n\
index --no-real-funds --source <absolute archive directory> --checkpoint <240 hex pin> (JSON to stdout)\n\
locate-height --no-real-funds --source <absolute archive directory> --checkpoint <240 hex pin> --height <1..tip>\n\
checkpoint-active --no-real-funds --source <absolute active directory> --genesis <absolute ZVTGEN03 manifest> --genesis-sha256 <64 hex> --height <trusted height> --app-hash <trusted hash>\n\
backup-active|restore-active --no-real-funds --source <absolute active/archive directory> --output <NEW absolute directory> --checkpoint <256 hex independently retained ZVARCP01 pin>\n\
verify-active --no-real-funds --source <absolute active/archive directory> --checkpoint <256 hex independently retained ZVARCP01 pin>\n\
plan-active-incremental --no-real-funds --base <absolute earlier archive> --base-checkpoint <256 hex pin> --source <absolute later archive> --checkpoint <256 hex pin> (read-only JSON; no incremental backup is written)\n\
pack-active-incremental --no-real-funds --base <absolute earlier archive> --base-checkpoint <256 hex pin> --source <absolute later archive> --checkpoint <256 hex pin> --output <NEW absolute package file>\n\
verify-active-incremental --no-real-funds --base <absolute earlier archive> --base-checkpoint <256 hex pin> --source <absolute package file> --checkpoint <256 hex independently retained later pin>\n\
restore-active-incremental --no-real-funds --base <absolute earlier archive> --base-checkpoint <256 hex pin> --source <absolute package file> --checkpoint <256 hex independently retained later pin> --output <NEW absolute directory>\n\
Stop the owning writer before use. No consensus database or signer state is copied.\n\
A failed copy may leave a partial or complete target. No automatic retry or repair.\n";

fn unhex<const N: usize>(text: &str) -> Result<[u8; N], ()> {
    if text.len() != 2 * N {
        return Err(());
    }
    let mut out = [0; N];
    fn digit(b: u8) -> Result<u8, ()> {
        match b {
            b'0'..=b'9' => Ok(b - b'0'),
            b'a'..=b'f' => Ok(b - b'a' + 10),
            _ => Err(()),
        }
    }
    for (i, pair) in text.as_bytes().as_chunks::<2>().0.iter().enumerate() {
        out[i] = digit(pair[0])? * 16 + digit(pair[1])?;
    }
    Ok(out)
}
fn hex(raw: &[u8]) -> String {
    raw.iter().map(|b| format!("{b:02x}")).collect()
}

#[cfg(any(unix, windows))]
fn write_active_receipt(report: &[u8]) -> Result<(), ()> {
    // Stdout's buffered adapter intentionally turns EBADF into success. Keep
    // its lock, but write this ASCII receipt through an owned duplicate so OS
    // errors propagate and dropping the File never closes the original stdout.
    let output_guard = std::io::stdout().lock();
    #[cfg(unix)]
    let handle = {
        use std::os::fd::AsFd;
        output_guard.as_fd().try_clone_to_owned().map_err(|_| ())?
    };
    #[cfg(windows)]
    let handle = {
        use std::os::windows::io::{AsHandle, AsRawHandle};
        let borrowed = output_guard.as_handle();
        // Windows permits a null borrowed stdout and even duplicates it as a
        // null OwnedHandle. An absent receipt destination cannot mean success.
        if borrowed.as_raw_handle().is_null() {
            return Err(());
        }
        borrowed.try_clone_to_owned().map_err(|_| ())?
    };
    let mut output = std::fs::File::from(handle);
    output.write_all(report).map_err(|_| ())?;
    output.flush().map_err(|_| ())
}

#[cfg(not(any(unix, windows)))]
fn write_active_receipt(_report: &[u8]) -> Result<(), ()> {
    Err(())
}

fn run_active(mode: &str, source: &Path, options: &BTreeMap<&str, &str>) -> Result<(), ()> {
    let pin = if mode == "checkpoint-active" {
        let height: u64 = options["--height"].parse().map_err(|_| ())?;
        if height.to_string() != options["--height"] {
            return Err(());
        }
        let app_hash = unhex::<32>(options["--app-hash"])?;
        let genesis = TestGenesis::read_pinned(
            Path::new(options["--genesis"]),
            unhex::<32>(options["--genesis-sha256"])?,
        )
        .map_err(|_| ())?;
        // Only an independently pinned 03 manifest selects this profile. The
        // candidate directory and new pin cannot upgrade a legacy deployment.
        if genesis.storage_profile() != StorageProfile::ActiveSegmentsV1 {
            return Err(());
        }
        let mut pool = genesis.open_pool(source).map_err(|_| ())?;
        pool.check_checkpoint(height, app_hash).map_err(|_| ())?;
        pool.active_recovery_checkpoint().map_err(|_| ())?
    } else {
        let pin = ActiveRecoveryCheckpoint::from_bytes(&unhex::<ACTIVE_CHECKPOINT_BYTES>(
            options["--checkpoint"],
        )?)
        .map_err(|_| ())?;
        let mut archive = ActiveArchive::open(source, pin).map_err(|_| ())?;
        match mode {
            // open already performs a new complete replay and final byte/name
            // checks. Do not replay the entire history twice for one CLI call.
            "verify-active" => archive.checkpoint(),
            "backup-active" | "restore-active" => archive
                .copy_new(Path::new(options["--output"]))
                .map_err(|_| ())?,
            _ => return Err(()),
        }
    };
    let report = format!("{{\"operation\":\"{mode}\",\"checkpoint\":\"{}\",\"height\":{},\"bytes\":{},\"checkpoint_format\":\"ZVARCP01\",\"storage_profile\":\"ActiveSegmentsV1\",\"app_hash\":\"{}\",\"segment_count\":{},\"replay_verified\":true,\"finality_verified\":false,\"validator_ready\":false,\"real_funds_allowed\":false}}\n", hex(&pin.to_bytes()), pin.height(), pin.length(), hex(&pin.app_hash()), pin.segment_count());
    // A complete copy can already exist when writing its receipt fails. Keep
    // that failure nonzero; never delete the new target or retry the operation.
    write_active_receipt(report.as_bytes())
}

fn run_incremental(source: &Path, options: &BTreeMap<&str, &str>) -> Result<(), ()> {
    // Parse both independently retained pins before opening either directory.
    let base_pin = ActiveRecoveryCheckpoint::from_bytes(&unhex::<ACTIVE_CHECKPOINT_BYTES>(
        options["--base-checkpoint"],
    )?)
    .map_err(|_| ())?;
    let later_pin = ActiveRecoveryCheckpoint::from_bytes(&unhex::<ACTIVE_CHECKPOINT_BYTES>(
        options["--checkpoint"],
    )?)
    .map_err(|_| ())?;
    let mut base = ActiveArchive::open(Path::new(options["--base"]), base_pin).map_err(|_| ())?;
    let mut later = ActiveArchive::open(source, later_pin).map_err(|_| ())?;
    // Each open replays once; the method independently replays both again.
    // Its result is historical metadata, never authority to apply an update.
    let plan = base.incremental_plan(&mut later).map_err(|_| ())?;
    incremental_output::emit(&plan)
}

fn run_package(mode: &str, source: &Path, options: &BTreeMap<&str, &str>) -> Result<(), ()> {
    // Both trust anchors must decode before any candidate input is opened.
    // The package's embedded pins are compared with them, never trusted alone.
    let base_pin = ActiveRecoveryCheckpoint::from_bytes(&unhex::<ACTIVE_CHECKPOINT_BYTES>(
        options["--base-checkpoint"],
    )?)
    .map_err(|_| ())?;
    let later_pin = ActiveRecoveryCheckpoint::from_bytes(&unhex::<ACTIVE_CHECKPOINT_BYTES>(
        options["--checkpoint"],
    )?)
    .map_err(|_| ())?;
    let mut base = ActiveArchive::open(Path::new(options["--base"]), base_pin).map_err(|_| ())?;
    let package = match mode {
        "pack-active-incremental" => {
            let mut later = ActiveArchive::open(source, later_pin).map_err(|_| ())?;
            // Two input opens plus four method replays: six in total.
            base.pack_incremental_new(&mut later, Path::new(options["--output"]))
                .map_err(|_| ())?
        }
        "verify-active-incremental" | "restore-active-incremental" => {
            // Open fully verifies base and the reconstructed history. Together
            // with base.open, a successful verify CLI performs three replays.
            let mut package =
                ActiveIncrementalPackage::open(source, &mut base, later_pin).map_err(|_| ())?;
            if mode == "restore-active-incremental" {
                // Restore adds five complete replays, for eight in this CLI.
                package
                    .restore_new(&mut base, Path::new(options["--output"]))
                    .map_err(|_| ())?;
            }
            package
        }
        _ => return Err(()),
    };
    // A complete new output may already exist if receipt writing fails.
    package_output::emit(&package, mode)
}

fn run(args: &[String]) -> Result<(), ()> {
    if args == ["--help"] || args == ["help"] {
        print!("{HELP}");
        return Ok(());
    }
    let (mode, rest) = args.split_first().ok_or(())?;
    if ![
        "checkpoint",
        "backup",
        "verify",
        "restore",
        "pack",
        "verify-segments",
        "restore-segments",
        "index",
        "locate-height",
        "checkpoint-active",
        "backup-active",
        "verify-active",
        "restore-active",
        "plan-active-incremental",
        "pack-active-incremental",
        "verify-active-incremental",
        "restore-active-incremental",
    ]
    .contains(&mode.as_str())
        || rest.len() > 13
        || rest.iter().any(|s| s.len() > 4096)
    {
        return Err(());
    }
    let mut options = BTreeMap::new();
    let mut iter = rest.iter();
    let mut acknowledged = false;
    while let Some(key) = iter.next() {
        if key == "--no-real-funds" {
            if acknowledged {
                return Err(());
            }
            acknowledged = true;
        } else {
            let val = iter.next().ok_or(())?;
            if !key.starts_with("--") || options.insert(key.as_str(), val.as_str()).is_some() {
                return Err(());
            }
        }
    }
    if !acknowledged {
        return Err(());
    }
    let expected: &[&str] = match mode.as_str() {
        "checkpoint" | "checkpoint-active" => &[
            "--source",
            "--genesis",
            "--genesis-sha256",
            "--height",
            "--app-hash",
        ],
        "locate-height" => &["--source", "--checkpoint", "--height"],
        "plan-active-incremental" | "verify-active-incremental" => {
            &["--base", "--base-checkpoint", "--source", "--checkpoint"]
        }
        "pack-active-incremental" | "restore-active-incremental" => &[
            "--base",
            "--base-checkpoint",
            "--source",
            "--checkpoint",
            "--output",
        ],
        "verify" | "verify-segments" | "index" | "verify-active" => &["--source", "--checkpoint"],
        _ => &["--source", "--output", "--checkpoint"],
    };
    if options.len() != expected.len() || expected.iter().any(|k| !options.contains_key(k)) {
        return Err(());
    }
    for key in ["--source", "--output", "--genesis", "--base"] {
        if let Some(path) = options.get(key) {
            if !Path::new(path).is_absolute() {
                return Err(());
            }
        }
    }
    let source = Path::new(options["--source"]);
    if mode == "plan-active-incremental" {
        return run_incremental(source, &options);
    }
    if matches!(
        mode.as_str(),
        "pack-active-incremental" | "verify-active-incremental" | "restore-active-incremental"
    ) {
        return run_package(mode, source, &options);
    }
    if matches!(
        mode.as_str(),
        "checkpoint-active" | "backup-active" | "verify-active" | "restore-active"
    ) {
        return run_active(mode, source, &options);
    }
    let pin = if mode == "checkpoint" {
        let height: u64 = options["--height"].parse().map_err(|_| ())?;
        if height.to_string() != options["--height"] {
            return Err(());
        }
        let app_hash = unhex::<32>(options["--app-hash"])?;
        let genesis = TestGenesis::read_pinned(
            Path::new(options["--genesis"]),
            unhex::<32>(options["--genesis-sha256"])?,
        )
        .map_err(|_| ())?;
        let mut pool = genesis.open_pool(source).map_err(|_| ())?;
        pool.check_checkpoint(height, app_hash).map_err(|_| ())?;
        pool.recovery_checkpoint().map_err(|_| ())?
    } else {
        let pin =
            RecoveryCheckpoint::from_bytes(&unhex::<CHECKPOINT_BYTES>(options["--checkpoint"])?)
                .map_err(|_| ())?;
        match mode.as_str() {
            "index" | "locate-height" => {
                let height = if mode == "locate-height" {
                    let value: u64 = options["--height"].parse().map_err(|_| ())?;
                    if value == 0
                        || value > pin.height()
                        || value.to_string() != options["--height"]
                    {
                        return Err(());
                    }
                    Some(value)
                } else {
                    None
                };
                let (_archive, index) =
                    SegmentedArchive::open_indexed(source, pin).map_err(|_| ())?;
                return index_output::emit(&index, height);
            }
            "verify-segments" | "restore-segments" => {
                let mut archive = SegmentedArchive::open(source, pin).map_err(|_| ())?;
                if mode == "restore-segments" {
                    archive
                        .restore_new(Path::new(options["--output"]))
                        .map_err(|_| ())?;
                }
            }
            _ => {
                let mut archive = RecoveryArchive::open(source, pin).map_err(|_| ())?;
                if mode == "pack" {
                    archive
                        .pack_new(Path::new(options["--output"]))
                        .map_err(|_| ())?;
                } else if mode != "verify" {
                    archive
                        .copy_new(Path::new(options["--output"]))
                        .map_err(|_| ())?;
                }
            }
        }
        pin
    };
    println!("{{\"operation\":\"{mode}\",\"checkpoint\":\"{}\",\"height\":{},\"bytes\":{},\"replay_verified\":true,\"finality_verified\":false,\"validator_ready\":false,\"real_funds_allowed\":false}}", hex(&pin.to_bytes()), pin.height(), pin.length());
    Ok(())
}
fn main() {
    let args: Result<Vec<_>, _> = std::env::args_os()
        .skip(1)
        .take(25)
        .map(|s| s.into_string())
        .collect();
    if args.as_ref().map_err(|_| ()).and_then(|a| run(a)).is_err() {
        eprintln!("Recovery not completed. No existing file was replaced. A partial or complete NEW target may remain; do not reset signer state or retry automatically.");
        std::process::exit(1);
    }
}
