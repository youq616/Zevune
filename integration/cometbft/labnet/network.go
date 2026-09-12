package labnet

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	cfg "github.com/cometbft/cometbft/config"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/libs/log"
	"github.com/cometbft/cometbft/node"
	"github.com/cometbft/cometbft/p2p"
	"github.com/cometbft/cometbft/privval"
	"github.com/cometbft/cometbft/proxy"
	"github.com/cometbft/cometbft/types"
	"github.com/youq616/Zevune/integration/cometbft/poolapp"
	"github.com/youq616/Zevune/internal/poolbridge"
)

type publicConfig struct {
	Version         uint32   `json:"version"`
	ChainID         string   `json:"chain_id"`
	AssetDigest     string   `json:"asset_genesis_sha256"`
	ConsensusDigest string   `json:"consensus_genesis_sha256"`
	NodeIDs         []string `json:"node_ids"`
}

// Network can only be obtained by checking an independently supplied digest.
// All consensus and wallet material held here is public. Fields are private so
// callers cannot accidentally substitute validators after authentication.
type Network struct {
	home       string
	config     publicConfig
	genesis    *types.GenesisDoc
	validators *types.ValidatorSet
	assetPin   Hash
	configPin  Hash
}

func (n *Network) ConfigDigest() Hash { return n.configPin }
func (n *Network) AssetDigest() Hash  { return n.assetPin }
func (n *Network) AssetPath() string  { return filepath.Join(n.home, assetName) }

func Load(configPath string, expected Hash) (*Network, error) {
	raw, err := pinnedBytes(configPath, expected, 100, 16*1024)
	if err != nil {
		return nil, err
	}
	var c publicConfig
	if canonicalJSON(raw, &c) != nil || c.Version != 1 || c.ChainID != poolapp.ChainID || len(c.NodeIDs) != 4 {
		return nil, ErrConfiguration
	}
	seen := make(map[string]bool)
	for _, id := range c.NodeIDs {
		decoded, err := hex.DecodeString(id)
		if err != nil || len(decoded) != 20 || hex.EncodeToString(decoded) != id || seen[id] {
			return nil, ErrConfiguration
		}
		seen[id] = true
	}
	asset, err := ParseHash(c.AssetDigest)
	if err != nil {
		return nil, ErrConfiguration
	}
	consensus, err := ParseHash(c.ConsensusDigest)
	if err != nil {
		return nil, ErrConfiguration
	}
	home := filepath.Dir(configPath)
	if _, err = pinnedBytes(filepath.Join(home, assetName), asset, 165, 1922); err != nil {
		return nil, err
	}
	raw, err = pinnedBytes(filepath.Join(home, genesisName), consensus, 100, 64*1024)
	if err != nil {
		return nil, err
	}
	g, err := types.GenesisDocFromJSON(raw)
	if err != nil || g.ChainID != poolapp.ChainID || g.InitialHeight != 1 || len(g.Validators) != 4 || len(g.AppHash) != 32 || g.ConsensusParams == nil || g.ConsensusParams.Version.App != poolapp.AppVersion {
		return nil, ErrConfiguration
	}
	if g.ConsensusParams.Block.MaxBytes != 512*1024 || g.ConsensusParams.Evidence.MaxBytes > 64*1024 || g.ConsensusParams.ABCI.VoteExtensionsEnableHeight != 0 {
		return nil, ErrConfiguration
	}
	binding, _ := json.Marshal(struct {
		Digest string `json:"test_genesis_sha256"`
	}{c.AssetDigest})
	var compact bytes.Buffer
	if json.Compact(&compact, g.AppState) != nil || !bytes.Equal(compact.Bytes(), binding) {
		return nil, ErrConfiguration
	}
	vals := make([]*types.Validator, 0, 4)
	seen = make(map[string]bool)
	for _, val := range g.Validators {
		if val.PubKey == nil || val.PubKey.Type() != "ed25519" || val.Power != 10 || len(val.PubKey.Bytes()) != 32 || seen[string(val.PubKey.Bytes())] || !bytes.Equal(val.Address, val.PubKey.Address()) {
			return nil, ErrConfiguration
		}
		seen[string(val.PubKey.Bytes())] = true
		vals = append(vals, types.NewValidator(val.PubKey, val.Power))
	}
	return &Network{home: home, config: c, genesis: g, validators: types.NewValidatorSet(vals), assetPin: asset, configPin: expected}, nil
}

func (n *Network) workerOptions(worker string, workerPin Hash, journal string, create bool) poolbridge.Options {
	return poolbridge.Options{
		Executable: worker, ExpectedSHA256: workerPin, Journal: journal, Create: create,
		TestGenesis: n.AssetPath(), TestGenesisSHA256: n.assetPin,
		StartupTimeout: 90 * time.Second, RequestTimeout: 30 * time.Second,
	}
}

type InitOptions struct {
	Home          string
	Worker        string
	WorkerSHA256  Hash
	AssetManifest string
	AssetSHA256   Hash
}

// Initialize creates a NEW four-node local network, never an existing one.
// A failed multi-file initialization is retained for inspection, not silently
// erased or retried. No current chain, signer or wallet is reset.
func Initialize(ctx context.Context, o InitOptions) (pin Hash, err error) {
	if ctx == nil || ctx.Err() != nil || !filepath.IsAbs(o.Home) || !filepath.IsAbs(o.Worker) || o.WorkerSHA256 == (Hash{}) {
		return pin, ErrBounds
	}
	asset, err := pinnedBytes(o.AssetManifest, o.AssetSHA256, 165, 1922)
	if err != nil {
		return pin, err
	}
	if err = os.Mkdir(o.Home, 0700); err != nil {
		return pin, ErrStorage
	}
	// Upstream key constructors panic on local I/O failure. Preserve the new
	// files and translate that failure; never proceed with substitute keys.
	defer func() {
		if recover() != nil {
			pin = Hash{}
			err = ErrStorage
		}
	}()
	if err = writeNew(filepath.Join(o.Home, assetName), asset); err != nil {
		return pin, err
	}
	n := &Network{home: o.Home, assetPin: o.AssetSHA256}
	c := publicConfig{Version: 1, ChainID: poolapp.ChainID, AssetDigest: HashText(o.AssetSHA256), NodeIDs: make([]string, 0, 4)}
	g := &types.GenesisDoc{GenesisTime: time.Now().UTC(), ChainID: poolapp.ChainID, InitialHeight: 1, ConsensusParams: types.DefaultConsensusParams()}
	g.ConsensusParams.Version.App = poolapp.AppVersion
	g.ConsensusParams.Block.MaxBytes = 512 * 1024
	g.ConsensusParams.Evidence.MaxBytes = 64 * 1024
	g.ConsensusParams.Validator.PubKeyTypes = []string{"ed25519"}
	g.AppState, _ = json.Marshal(struct {
		Digest string `json:"test_genesis_sha256"`
	}{c.AssetDigest})
	for index := 0; index < 4; index++ {
		if ctx.Err() != nil {
			return Hash{}, ctx.Err()
		}
		conf := cfg.DefaultConfig().SetRoot(filepath.Join(o.Home, fmt.Sprintf("node%d", index)))
		for _, sub := range []string{"config", "data"} {
			if err = os.MkdirAll(filepath.Join(conf.RootDir, sub), 0700); err != nil {
				return pin, ErrStorage
			}
		}
		state, err := poolbridge.Start(ctx, n.workerOptions(o.Worker, o.WorkerSHA256, filepath.Join(conf.RootDir, "pool.journal"), true))
		if err != nil {
			return pin, err
		}
		summary, statusErr := state.Status(ctx)
		closeErr := state.Close()
		if statusErr != nil || closeErr != nil || summary.Height != 0 || summary.Fees != 0 || summary.Nullifiers != 0 {
			return pin, ErrConfiguration
		}
		if index == 0 {
			g.AppHash = append([]byte(nil), summary.AppHash[:]...)
		} else if !bytes.Equal(g.AppHash, summary.AppHash[:]) {
			return pin, ErrConfiguration
		}
		pv := privval.GenFilePV(conf.PrivValidatorKeyFile(), conf.PrivValidatorStateFile())
		pv.Save()
		pub, err := pv.GetPubKey()
		if err != nil {
			return pin, ErrStorage
		}
		g.Validators = append(g.Validators, types.GenesisValidator{Address: pub.Address(), PubKey: pub, Power: 10, Name: fmt.Sprintf("local-%d", index)})
		nk, err := p2p.LoadOrGenNodeKey(conf.NodeKeyFile())
		if err != nil {
			return pin, ErrStorage
		}
		c.NodeIDs = append(c.NodeIDs, string(nk.ID()))
	}
	if g.ValidateAndComplete() != nil {
		return pin, ErrConfiguration
	}
	genesis, err := cmtjson.MarshalIndent(g, "", "  ")
	if err != nil {
		return pin, ErrConfiguration
	}
	if err = writeNew(filepath.Join(o.Home, genesisName), genesis); err != nil {
		return pin, err
	}
	for index := 0; index < 4; index++ {
		if err = writeNew(filepath.Join(o.Home, fmt.Sprintf("node%d/config/genesis.json", index)), genesis); err != nil {
			return pin, err
		}
	}
	c.ConsensusDigest = HashText(sha256.Sum256(genesis))
	raw, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return pin, err
	}
	raw = append(raw, '\n')
	// Publish the public configuration LAST, so a partially initialized home is
	// not reported as ready. Directory fsync/Windows ACL guarantees are separate.
	if err = writeNew(filepath.Join(o.Home, configName), raw); err != nil {
		return pin, err
	}
	pin = sha256.Sum256(raw)
	if _, err = Load(filepath.Join(o.Home, configName), pin); err != nil {
		return Hash{}, err
	}
	return pin, nil
}

func ValidPorts(base int) bool        { return base >= 10240 && base <= 65528 }
func Endpoint(base, index int) string { return fmt.Sprintf("http://127.0.0.1:%d", base+2*index) }

// Run preserves signer state and existing journals. Each node reads only its
// OWN private files; peer IDs come from the pinned PUBLIC network configuration.
func (n *Network) Run(ctx context.Context, worker string, workerPin Hash, index, base int, ready func()) (err error) {
	if ctx == nil || ctx.Err() != nil || index < 0 || index >= 4 || !ValidPorts(base) || n == nil {
		return ErrBounds
	}
	conf := cfg.DefaultConfig().SetRoot(filepath.Join(n.home, fmt.Sprintf("node%d", index)))
	for _, p := range []string{conf.PrivValidatorKeyFile(), conf.PrivValidatorStateFile(), conf.NodeKeyFile()} {
		if _, err = regularBytes(p, 2, 32*1024); err != nil {
			return err
		}
	}
	consensusPin, err := ParseHash(n.config.ConsensusDigest)
	if err != nil {
		return err
	}
	if _, err = pinnedBytes(conf.GenesisFile(), consensusPin, 100, 64*1024); err != nil {
		return err
	}
	a, err := poolapp.Open(ctx, n.workerOptions(worker, workerPin, filepath.Join(conf.RootDir, "pool.journal"), false))
	if err != nil {
		return err
	}
	// The real Rust journal lock is acquired BEFORE loading any signer. A second
	// process using the same node home cannot get a competing application owner.
	defer a.Close()
	defer func() {
		if recover() != nil {
			err = ErrStorage
		}
	}()
	pv := privval.LoadFilePV(conf.PrivValidatorKeyFile(), conf.PrivValidatorStateFile())
	pub, err := pv.GetPubKey()
	if err != nil || !bytes.Equal(pub.Bytes(), n.genesis.Validators[index].PubKey.Bytes()) {
		return ErrConfiguration
	}
	nk, err := p2p.LoadNodeKey(conf.NodeKeyFile())
	if err != nil || string(nk.ID()) != n.config.NodeIDs[index] {
		return ErrConfiguration
	}
	conf.Moniker = fmt.Sprintf("zevune-local-%d", index)
	conf.RPC.ListenAddress = fmt.Sprintf("tcp://127.0.0.1:%d", base+index*2)
	conf.RPC.GRPCListenAddress = ""
	conf.RPC.PprofListenAddress = ""
	conf.RPC.Unsafe = false
	conf.RPC.CORSAllowedOrigins = nil
	conf.RPC.MaxBodyBytes = 512 * 1024
	conf.RPC.MaxOpenConnections = 32
	conf.P2P.ListenAddress = fmt.Sprintf("tcp://127.0.0.1:%d", base+index*2+1)
	conf.P2P.ExternalAddress = ""
	conf.P2P.AddrBookStrict = false
	conf.P2P.AllowDuplicateIP = true
	conf.P2P.PexReactor = false
	conf.P2P.Seeds = ""
	conf.P2P.PersistentPeersMaxDialPeriod = time.Second
	peers := make([]string, 0, 3)
	for i, id := range n.config.NodeIDs {
		if i != index {
			peers = append(peers, fmt.Sprintf("%s@127.0.0.1:%d", id, base+2*i+1))
		}
	}
	conf.P2P.PersistentPeers = strings.Join(peers, ",")
	conf.Consensus.TimeoutCommit = 400 * time.Millisecond
	conf.Consensus.TimeoutPropose = 2 * time.Second
	conf.Consensus.CreateEmptyBlocks = true
	conf.Consensus.CreateEmptyBlocksInterval = time.Second
	conf.TxIndex.Indexer = "null"
	conf.StateSync.Enable = false
	conf.Instrumentation.Prometheus = false
	conf.Mempool.Size = 256
	conf.Mempool.MaxTxsBytes = 8 * 1024 * 1024
	conf.Mempool.MaxTxBytes = poolbridge.MaxTransactionBytes
	conf.Mempool.CacheSize = 1024
	if conf.ValidateBasic() != nil {
		return ErrConfiguration
	}
	engine, err := node.NewNode(conf, pv, nk, proxy.NewLocalClientCreator(a), node.DefaultGenesisDocProviderFunc(conf), cfg.DefaultDBProvider, node.DefaultMetricsProvider(conf.Instrumentation), log.NewNopLogger())
	if err != nil {
		return ErrConfiguration
	}
	if err = engine.Start(); err != nil {
		return err
	}
	defer func() {
		if engine.IsRunning() {
			_ = engine.Stop()
			engine.Wait()
		}
	}()
	if ready != nil {
		ready()
	}
	return awaitNodeStop(ctx, engine.Quit())
}
