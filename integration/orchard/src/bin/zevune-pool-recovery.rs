//! Local NO-FUNDS recovery utility. No networking, signer reset or file deletion.
use std::collections::BTreeMap;
use std::path::Path;
use zevune_orchard_lab::pool::recovery::{RecoveryArchive, RecoveryCheckpoint, CHECKPOINT_BYTES};
use zevune_orchard_lab::pool::testnet::TestGenesis;

const HELP: &str = "Zevune PUBLIC journal recovery (NO FUNDS; NOT full validator recovery)\n\
checkpoint --no-real-funds --source <absolute journal> --genesis <absolute manifest> --genesis-sha256 <64 hex> --height <trusted height> --app-hash <trusted hash>\n\
verify --no-real-funds --source <absolute backup> --checkpoint <240 hex independently retained pin>\n\
backup|restore --no-real-funds --source <absolute journal/backup> --output <new absolute path> --checkpoint <240 hex pin>\n\
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
fn run(args: &[String]) -> Result<(), ()> {
    if args == ["--help"] || args == ["help"] {
        print!("{HELP}");
        return Ok(());
    }
    let (mode, rest) = args.split_first().ok_or(())?;
    if !["checkpoint", "backup", "verify", "restore"].contains(&mode.as_str())
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
        "checkpoint" => &[
            "--source",
            "--genesis",
            "--genesis-sha256",
            "--height",
            "--app-hash",
        ],
        "verify" => &["--source", "--checkpoint"],
        _ => &["--source", "--output", "--checkpoint"],
    };
    if options.len() != expected.len() || expected.iter().any(|k| !options.contains_key(k)) {
        return Err(());
    }
    for key in ["--source", "--output", "--genesis"] {
        if let Some(path) = options.get(key) {
            if !Path::new(path).is_absolute() {
                return Err(());
            }
        }
    }
    let source = Path::new(options["--source"]);
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
        let mut archive = RecoveryArchive::open(source, pin).map_err(|_| ())?;
        if mode != "verify" {
            archive
                .copy_new(Path::new(options["--output"]))
                .map_err(|_| ())?;
        }
        archive.checkpoint()
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
