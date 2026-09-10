//! Local public-authorization worker. No wallet secrets or network listeners.
#![forbid(unsafe_code)]
fn main() {
    // Error output is deliberately fixed and never includes request contents.
    let result = zevune_orchard_lab::worker::serve(
        &mut std::io::stdin().lock(),
        &mut std::io::stdout().lock(),
    );
    if result.is_err() {
        eprintln!("Zevune local verification session failed");
        std::process::exit(1);
    }
}
