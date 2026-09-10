// Package devnet creates a four-validator, loopback-only, NO-FUNDS laboratory.
// Validator keys are created locally at runtime, never embedded or exported.
package devnet

import (
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "errors"
 "fmt"
 "os"
 "path/filepath"
 "strings"
 "time"

 cfg "github.com/cometbft/cometbft/config"
 "github.com/cometbft/cometbft/libs/log"
 "github.com/cometbft/cometbft/node"
 "github.com/cometbft/cometbft/p2p"
 "github.com/cometbft/cometbft/privval"
 "github.com/cometbft/cometbft/proxy"
 "github.com/cometbft/cometbft/types"
 "github.com/youq616/Zevune/integration/cometbft/app"
)

const ChainID = "zevune-consensus-lab-1"
const NodeCount = 4

type Manifest struct {
 Format int `json:"format"`
 ChainID string `json:"chain_id"`
 BasePort int `json:"base_port"`
 NodeIDs []string `json:"node_ids"`
 GenesisSHA256 string `json:"genesis_sha256"`
}
func nodeHome(home string, index int) string { return filepath.Join(home, fmt.Sprintf("node%d", index)) }
func RPCAddress(m Manifest, index int) string { return fmt.Sprintf("http://127.0.0.1:%d", m.BasePort+2*index) }
// Init refuses every existing home, including an empty directory. It never
// resets a validator's signing state or overwrites a partial initialization.
func Init(home string, basePort int) (Manifest, error) {
 var m Manifest
 if home == "" || basePort < 1024 || basePort > 65528 { return m, errors.New("home and valid eight-port range required") }
 abs, err := filepath.Abs(home)
 if err != nil { return m, err }
 if err = os.MkdirAll(filepath.Dir(abs), 0700); err != nil { return m, err }
 if err = os.Mkdir(abs, 0700); err != nil { return m, fmt.Errorf("refusing existing or unavailable home: %w", err) }
 m = Manifest{Format: 1, ChainID: ChainID, BasePort: basePort}
 genesis := &types.GenesisDoc{GenesisTime: time.Now().UTC(), ChainID: ChainID, InitialHeight: 1, ConsensusParams: types.DefaultConsensusParams()}
 genesis.ConsensusParams.Version.App = app.AppVersion
 genesis.ConsensusParams.Validator.PubKeyTypes = []string{"ed25519"}
 genesis.ConsensusParams.Block.MaxBytes = 2 * 1024 * 1024
 for i := 0; i < NodeCount; i++ {
 c := cfg.DefaultConfig().SetRoot(nodeHome(abs, i))
 for _, dir := range []string{"config", "data"} {
 if err = os.MkdirAll(filepath.Join(c.RootDir, dir), 0700); err != nil { return m, err }
 }
 pv := privval.GenFilePV(c.PrivValidatorKeyFile(), c.PrivValidatorStateFile())
 pv.Save()
 pub, er := pv.GetPubKey()
 if er != nil { return m, er }
 genesis.Validators = append(genesis.Validators, types.GenesisValidator{Address: pub.Address(), PubKey: pub, Power: 10, Name: fmt.Sprintf("local-%d", i)})
 nk, er := p2p.LoadOrGenNodeKey(c.NodeKeyFile())
 if er != nil { return m, er }
 m.NodeIDs = append(m.NodeIDs, string(nk.ID()))
 }
 if err = genesis.ValidateAndComplete(); err != nil { return m, err }
 for i := 0; i < NodeCount; i++ {
 c := cfg.DefaultConfig().SetRoot(nodeHome(abs, i))
 if err = genesis.SaveAs(c.GenesisFile()); err != nil { return m, err }
 }
 data, err := os.ReadFile(cfg.DefaultConfig().SetRoot(nodeHome(abs, 0)).GenesisFile())
 if err != nil { return m, err }
 sum := sha256.Sum256(data)
 m.GenesisSHA256 = hex.EncodeToString(sum[:])
 data, err = json.MarshalIndent(m, "", "  ")
 if err != nil { return m, err }
 f, err := os.OpenFile(filepath.Join(abs, "manifest.json"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
 if err != nil { return m, err }
 _, err = f.Write(data)
 if err == nil { err = f.Sync() }
 return m, errors.Join(err, f.Close())
}
func Load(home string) (Manifest, error) {
 var m Manifest
 b, err := os.ReadFile(filepath.Join(home, "manifest.json"))
 if err != nil { return m, err }
 if err = json.Unmarshal(b, &m); err != nil { return m, err }
 if m.Format != 1 || m.ChainID != ChainID || m.BasePort < 1024 || m.BasePort > 65528 || len(m.NodeIDs) != NodeCount || len(m.GenesisSHA256) != 64 {
 return m, errors.New("invalid laboratory manifest")
 }
 seen := map[string]bool{}
 for _, id := range m.NodeIDs {
 raw, er := hex.DecodeString(id)
 if er != nil || len(raw) != 20 || seen[id] { return m, errors.New("invalid/duplicate node ID") }
 seen[id] = true
 }
 for i := 0; i < NodeCount; i++ {
 b, er := os.ReadFile(cfg.DefaultConfig().SetRoot(nodeHome(home, i)).GenesisFile())
 if er != nil { return m, er }
 sum := sha256.Sum256(b)
 if hex.EncodeToString(sum[:]) != m.GenesisSHA256 { return m, errors.New("genesis mismatch; original files left unchanged") }
 }
 return m, nil
}
type RunningNode struct { Node *node.Node; App *app.Application }
// Start uses internal ABCI calls, not a publicly callable ABCI server. RPC and
// P2P addresses are derived here and cannot be replaced by wildcard interfaces.
func Start(home string, index int, logger log.Logger) (*RunningNode, error) {
 if index < 0 || index >= NodeCount { return nil, errors.New("node index out of range") }
 m, err := Load(home)
 if err != nil { return nil, err }
 c := cfg.DefaultConfig().SetRoot(nodeHome(home, index))
 c.Moniker = fmt.Sprintf("zevune-lab-%d", index)
 c.RPC.ListenAddress = fmt.Sprintf("tcp://127.0.0.1:%d", m.BasePort+2*index)
 c.RPC.GRPCListenAddress = ""
 c.RPC.Unsafe = false
 c.RPC.CORSAllowedOrigins = nil
 c.RPC.MaxBodyBytes = 64 * 1024
 c.RPC.MaxOpenConnections = 32
 c.P2P.ListenAddress = fmt.Sprintf("tcp://127.0.0.1:%d", m.BasePort+2*index+1)
 c.P2P.ExternalAddress = ""
 c.P2P.AddrBookStrict = false // Local loopback addresses only.
 c.P2P.AllowDuplicateIP = true
 c.P2P.PexReactor = false
 c.P2P.Seeds = ""
 c.P2P.PersistentPeersMaxDialPeriod = time.Second
 peers := make([]string, 0, NodeCount-1)
 for i, id := range m.NodeIDs {
 if i != index { peers = append(peers, fmt.Sprintf("%s@127.0.0.1:%d", id, m.BasePort+2*i+1)) }
 }
 c.P2P.PersistentPeers = strings.Join(peers, ",")
 c.Consensus.CreateEmptyBlocks = true
 c.Consensus.TimeoutCommit = 400*time.Millisecond
 c.Consensus.TimeoutPropose = time.Second
 c.Consensus.TimeoutProposeDelta = 500*time.Millisecond
 c.StateSync.Enable = false
 c.TxIndex.Indexer = "null"
 c.Instrumentation.Prometheus = false
 c.ProfListenAddress = ""
 if err = c.ValidateBasic(); err != nil { return nil, err }
 // Never regenerate a missing signing key or anti-double-sign state on restart.
 for _, p := range []string{c.PrivValidatorKeyFile(), c.PrivValidatorStateFile(), c.NodeKeyFile()} {
 fi, er := os.Lstat(p)
 if er != nil { return nil, er }
 if !fi.Mode().IsRegular() { return nil, errors.New("validator files must be regular files") }
 }
 genesis, err := types.GenesisDocFromFile(c.GenesisFile())
 if err != nil { return nil, err }
 if genesis.ChainID != ChainID || genesis.InitialHeight != 1 || len(genesis.Validators) != NodeCount || len(genesis.AppState) != 0 {
 return nil, errors.New("unsupported laboratory genesis")
 }
 // Acquire the exclusive ledger lock before reading validator signing state.
 a, err := app.Open(ChainID, filepath.Join(c.RootDir, "application"))
 if err != nil { return nil, err }
 pv := privval.LoadFilePV(c.PrivValidatorKeyFile(), c.PrivValidatorStateFile())
 nk, err := p2p.LoadNodeKey(c.NodeKeyFile())
 if err != nil { _ = a.Close(); return nil, err }
 if string(nk.ID()) != m.NodeIDs[index] { _ = a.Close(); return nil, errors.New("node key does not match manifest") }
 pub, err := pv.GetPubKey()
 if err != nil { _ = a.Close(); return nil, err }
 if !pub.Equals(genesis.Validators[index].PubKey) { _ = a.Close(); return nil, errors.New("validator key does not match genesis") }
 n, err := node.NewNode(c, pv, nk, proxy.NewLocalClientCreator(a), node.DefaultGenesisDocProviderFunc(c), cfg.DefaultDBProvider, node.DefaultMetricsProvider(c.Instrumentation), logger)
 if err != nil { _ = a.Close(); return nil, err }
 if err = n.Start(); err != nil { _ = n.Stop(); _ = a.Close(); return nil, err }
 return &RunningNode{n, a}, nil
}
// Stop stops networking before releasing the application journal lock.
func (n *RunningNode) Stop() error {
 var err error
 if n.Node.IsRunning() { err = n.Node.Stop(); n.Node.Wait() }
 return errors.Join(err, n.App.Close())
}
