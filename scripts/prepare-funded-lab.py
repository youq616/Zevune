"""One-use, development-branch-only source assembly. No dependency upgrades."""
from pathlib import Path
import hashlib
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def change(path, digest, replacements):
    p = ROOT / path
    raw = p.read_bytes().replace(b'\r\n', b'\n')
    actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if actual != digest:
        raise SystemExit(f'Baseline changed, refusing to patch {path}')
    text = raw.decode('utf-8')
    for before, after in replacements:
        if text.count(before) != 1:
            raise SystemExit(f'Expected one exact context in {path}: {before[:60]}')
        text = text.replace(before, after, 1)
    p.write_text(text, encoding='utf-8', newline='\n')

change('integration/orchard/Cargo.toml', '1fa46f9da5d112a16ff3cc58c6b95aea314de60e', [
    ('[workspace]', '[features]\nlocal-funding-lab = []\n\n[[bin]]\nname = "zevune-funded-scenario"\npath = "src/bin/zevune-funded-scenario.rs"\nrequired-features = ["local-funding-lab"]\n\n[workspace]')])
change('integration/orchard/src/pool.rs', '8a604d31721cbd0ce63af53b06a373d6b8d020a6', [
    ('mod wallet_flow_tests;', 'mod wallet_flow_tests;\n\n#[cfg(feature = "local-funding-lab")]\npub mod testnet;')])
change('integration/orchard/src/wallet_history.rs', '8ae82714cbfbc84f75f1c7adedf915d188998e2a', [
    ('    origin: Summary,', '    #[cfg(feature = "local-funding-lab")]\n    pub(crate) genesis_notes: Vec<orchard::Note>,\n    origin: Summary,'),
    ('            genesis: state.genesis,', '            #[cfg(feature = "local-funding-lab")]\n            genesis_notes: Vec::new(),\n            genesis: state.genesis,')])
change('integration/orchard/src/wallet.rs', '30308ac3f1eab84bf5b469ecf22044cab0271885', [
    ('        let mut notes = BTreeMap::new();', '''        let mut notes = BTreeMap::new();
        #[cfg(feature = "local-funding-lab")]
        for (position, note) in history.genesis_notes.iter().enumerate() {
            let cm = orchard::note::ExtractedNoteCommitment::from(note.commitment()).to_bytes();
            if history.initial.get(position) != Some(&cm) {
                return Err(WalletError::History);
            }
            if fvk.scope_for_address(&note.recipient()).is_some() {
                let nf = note.nullifier(&fvk).to_bytes();
                if notes.insert(nf, OwnedNote { note: *note, position }).is_some() {
                    return Err(WalletError::History);
                }
            }
        }''')])
change('integration/orchard/src/bin/zevune-pool-worker.rs', 'e5d116e5e7c1710b25b1e8b4b89e3c830d68b7a2', [
    ('fn run() -> io::Result<()> {', '''fn requested_store(args: &[std::ffi::OsString]) -> Result<PoolStore, PoolError> {
    if ![3, 5].contains(&args.len()) || !Path::new(&args[2]).is_absolute() {
        return Err(PoolError::Bounds);
    }
    let create = if args[1] == "create" { true } else if args[1] == "open" { false } else { return Err(PoolError::Bounds); };
    let path = Path::new(&args[2]);
    if args.len() == 3 {
        return if create { PoolStore::create(path) } else { PoolStore::open(path) };
    }
    #[cfg(feature = "local-funding-lab")]
    {
        use zevune_orchard_lab::pool::testnet::TestGenesis;
        let manifest = Path::new(&args[3]);
        if !manifest.is_absolute() { return Err(PoolError::Genesis); }
        let text = args[4].to_str().ok_or(PoolError::Genesis)?;
        if text.len() != 64 || !text.bytes().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)) { return Err(PoolError::Genesis); }
        let mut digest = [0; 32];
        for (i, item) in digest.iter_mut().enumerate() {
            *item = u8::from_str_radix(&text[i*2..i*2+2], 16).map_err(|_| PoolError::Genesis)?;
        }
        let genesis = TestGenesis::read_pinned(manifest, digest)?;
        if create { genesis.create_pool(path) } else { genesis.open_pool(path) }
    }
    #[cfg(not(feature = "local-funding-lab"))]
    Err(PoolError::Genesis)
}
fn run() -> io::Result<()> {'''),
    ('''    if args.len() != 3 || !Path::new(&args[2]).is_absolute() {
        return Err(bad());
    }
    let path = Path::new(&args[2]);
    let store = if args[1] == "create" {
        PoolStore::create(path)
    } else if args[1] == "open" {
        PoolStore::open(path)
    } else {
        return Err(bad());
    }
    .map_err(|_| io::Error::other("pool could not be opened"))?;''', '''    let store = requested_store(&args).map_err(|_| io::Error::other("pool could not be opened"))?;''')])
change('internal/poolbridge/client.go', 'be5ef0f08aed80c7314a5b47a78ba980ddc7a793', [
    ('\tJournal        string', '\tTestGenesis string\n\tTestGenesisSHA256 Hash\n\tJournal        string'),
    ('\tcmd := exec.Command(o.Executable, mode, o.Journal)', '\targs, err := o.workerArgs(mode)\n\tif err != nil { return nil, err }\n\tcmd := exec.Command(o.Executable, args...)')])
change('integration/cometbft/poolapp/app.go', '5986aaa9fc686f968aae270d69de4479889c13a1', [
    ('const Version = "0.3.0-orchard-consensus-lab"', 'const Version = "0.3.1-funded-consensus-lab"'),
    ('\tclient  *poolbridge.Client', '\tclient  *poolbridge.Client\n\tgenesis poolbridge.Hash'),
    ('return &Application{client: c}, nil', 'return &Application{client: c, genesis: o.TestGenesisSHA256}, nil'),
    ('len(r.AppStateBytes) != 0', '!validGenesisState(r.AppStateBytes, a.genesis)'),
    ('\tb, e := json.Marshal(struct {', '\tmode := "local_zero_value_orchard_consensus"\n\tif a.genesis != (poolbridge.Hash{}) { mode = "local_fixed_supply_funded_orchard_lab" }\n\tb, e := json.Marshal(struct {'),
    ('}{Version, "local_zero_value_orchard_consensus", false, false, s})', '}{Version, mode, false, false, s})')])
change('integration/cometbft/poolapp/e2e_test.go', '2b8620163a085ab48c00803e1e854935eb9126ac', [
    ('\t"encoding/json"', '\t"encoding/json"\n\t"encoding/hex"'),
    ('\treturn poolbridge.Options{Executable: worker, ExpectedSHA256: sha256.Sum256(b), Journal: path, Create: create, StartupTimeout: 90 * time.Second}, nil', '''\to := poolbridge.Options{Executable: worker, ExpectedSHA256: sha256.Sum256(b), Journal: path, Create: create, StartupTimeout: 90 * time.Second}
    if manifest := os.Getenv("ZEVUNE_TEST_GENESIS"); manifest != "" {
        digest, err := hex.DecodeString(os.Getenv("ZEVUNE_TEST_GENESIS_SHA256"))
        if err != nil || len(digest) != 32 { return poolbridge.Options{}, poolbridge.ErrBounds }
        o.TestGenesis = manifest
        copy(o.TestGenesisSHA256[:], digest)
    }
    return o, nil'''),
    ('\t\ta := open(t, filepath.Join(c.RootDir, "pool.journal"), true)\n\t\tif e = a.Close();', '''\t\ta := open(t, filepath.Join(c.RootDir, "pool.journal"), true)
        if a.genesis != (poolbridge.Hash{}) {
            state := info(t, a)
            if i == 0 {
                g.AppState = testGenesisState(a.genesis)
                g.AppHash = bytes.Clone(state.LastBlockAppHash)
            } else if !bytes.Equal(g.AppHash, state.LastBlockAppHash) || !validGenesisState(g.AppState, a.genesis) {
                t.Fatal("genesis states differ")
            }
        }
\t\tif e = a.Close();''')])
change('integration/orchard/src/bin/zevune-funded-scenario.rs', 'd1c147bd0da81780e2bd648568e0847139707824', [('Some(receipt))?;', 'Some(receipt))?);')])
subprocess.run(['cargo', 'fmt', '--manifest-path', str(ROOT/'integration/orchard/Cargo.toml'), '--all'], check=True, cwd=ROOT)
subprocess.run(['gofmt', '-w', 'internal/poolbridge', 'integration/cometbft/poolapp'], check=True, cwd=ROOT)
print('Prepared explicit fixed-supply NO-FUNDS genesis and funded integration sources; dependency versions unchanged.')
