// Package paymentnet runs an isolated four-process, no-value payment network.
package paymentnet
import(
 "context"
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "errors"
 "fmt"
 "io"
 "os"
 "os/exec"
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
 "github.com/youq616/Zevune/integration/cometbft/paymentapp"
)
const NodeCount=4
const ChainID=paymentapp.ChainID
type Manifest struct{
 Format int `json:"format"`
 ChainID string `json:"chain_id"`
 BasePort int `json:"base_port"`
 NodeIDs []string `json:"node_ids"`
 ConsensusGenesisSHA256 string `json:"consensus_genesis_sha256"`
 PaymentGenesisSHA256 string `json:"payment_genesis_sha256"`
}
func NodeHome(home string,index int)string{return filepath.Join(home,fmt.Sprintf("node%d",index))}
func GenesisPath(home string)string{return filepath.Join(home,"payment-genesis.bin")}
func RPCAddress(m Manifest,index int)string{return fmt.Sprintf("http://127.0.0.1:%d",m.BasePort+2*index)}
func ReadBounded(path string,max int64)([]byte,error){
 fi,err:=os.Lstat(path);if err!=nil{return nil,err};if !fi.Mode().IsRegular()||fi.Size()>max{return nil,errors.New("unsupported file or size")}
 f,err:=os.Open(path);if err!=nil{return nil,err};defer f.Close();b,err:=io.ReadAll(io.LimitReader(f,max+1));if err!=nil{return nil,err};if int64(len(b))>max{return nil,errors.New("file size limit")};return b,nil
}
func WriteNew(path string,data []byte)error{f,err:=os.OpenFile(path,os.O_WRONLY|os.O_CREATE|os.O_EXCL,0600);if err!=nil{return err};_,err=f.Write(data);if err==nil{err=f.Sync()};return errors.Join(err,f.Close())}
func Init(home string,basePort int,cryptoExecutable,genesisPath string)(Manifest,error){
 var m Manifest
 if home==""||basePort<1024||basePort>65528{return m,errors.New("home and valid port range required")}
 genesisBytes,err:=ReadBounded(genesisPath,paymentapp.MaxTxBytes);if err!=nil{return m,err}
 absolute,err:=filepath.Abs(cryptoExecutable);if err!=nil{return m,err};genesisPath,err=filepath.Abs(genesisPath);if err!=nil{return m,err}
 ctx,cancel:=context.WithTimeout(context.Background(),time.Minute);defer cancel()
 data,err:=exec.CommandContext(ctx,absolute,"verify-genesis",genesisPath).Output();if err!=nil{return m,errors.New("real genesis proof verification failed")}
 var initial paymentapp.Summary;if json.Unmarshal(data,&initial)!=nil||initial.ChainID!=ChainID||initial.Height!=0||initial.RealFundsAllowed{return m,errors.New("invalid genesis summary")}
 digest:=sha256.Sum256(genesisBytes);if hex.EncodeToString(digest[:])!=initial.GenesisID{return m,errors.New("genesis identifier mismatch")}
 initialHash,err:=hex.DecodeString(initial.AppHash);if err!=nil||len(initialHash)!=32{return m,errors.New("genesis app hash")}
 home,err=filepath.Abs(home);if err!=nil{return m,err};if err=os.MkdirAll(filepath.Dir(home),0700);err!=nil{return m,err};if err=os.Mkdir(home,0700);err!=nil{return m,errors.New("refusing existing or unavailable network directory")}
 if err=WriteNew(GenesisPath(home),genesisBytes);err!=nil{return m,err}
 m=Manifest{Format:1,ChainID:ChainID,BasePort:basePort,PaymentGenesisSHA256:initial.GenesisID}
 appState,_:=json.Marshal(map[string]string{"shielded_genesis_id":initial.GenesisID})
 genesis:=&types.GenesisDoc{GenesisTime:time.Now().UTC(),ChainID:ChainID,InitialHeight:1,ConsensusParams:types.DefaultConsensusParams(),AppHash:initialHash,AppState:appState}
 genesis.ConsensusParams.Version.App=paymentapp.AppVersion;genesis.ConsensusParams.Validator.PubKeyTypes=[]string{"ed25519"};genesis.ConsensusParams.Block.MaxBytes=1024*1024
 for i:=0;i<NodeCount;i++{
  c:=cfg.DefaultConfig().SetRoot(NodeHome(home,i));for _,dir:=range []string{"config","data"}{if err=os.MkdirAll(filepath.Join(c.RootDir,dir),0700);err!=nil{return m,err}}
  pv:=privval.GenFilePV(c.PrivValidatorKeyFile(),c.PrivValidatorStateFile());pv.Save();pub,e:=pv.GetPubKey();if e!=nil{return m,e}
  genesis.Validators=append(genesis.Validators,types.GenesisValidator{Address:pub.Address(),PubKey:pub,Power:10,Name:fmt.Sprintf("payment-local-%d",i)})
  nk,e:=p2p.LoadOrGenNodeKey(c.NodeKeyFile());if e!=nil{return m,e};m.NodeIDs=append(m.NodeIDs,string(nk.ID()))
 }
 if err=genesis.ValidateAndComplete();err!=nil{return m,err}
 for i:=0;i<NodeCount;i++{if err=genesis.SaveAs(cfg.DefaultConfig().SetRoot(NodeHome(home,i)).GenesisFile());err!=nil{return m,err}}
 data,err=ReadBounded(cfg.DefaultConfig().SetRoot(NodeHome(home,0)).GenesisFile(),1<<20);if err!=nil{return m,err};digest=sha256.Sum256(data);m.ConsensusGenesisSHA256=hex.EncodeToString(digest[:])
 data,err=json.MarshalIndent(m,"","  ");if err!=nil{return m,err};return m,WriteNew(filepath.Join(home,"payment-manifest.json"),data)
}
func Load(home string)(Manifest,error){
 var m Manifest;b,err:=ReadBounded(filepath.Join(home,"payment-manifest.json"),1<<20);if err!=nil{return m,err};if err=json.Unmarshal(b,&m);err!=nil{return m,err}
 if m.Format!=1||m.ChainID!=ChainID||m.BasePort<1024||m.BasePort>65528||len(m.NodeIDs)!=NodeCount||len(m.PaymentGenesisSHA256)!=64||len(m.ConsensusGenesisSHA256)!=64{return m,errors.New("invalid payment manifest")}
 seen:=map[string]bool{};for _,id:=range m.NodeIDs{b,err=hex.DecodeString(id);if err!=nil||len(b)!=20||seen[id]{return m,errors.New("invalid node identifiers")};seen[id]=true}
 b,err=ReadBounded(GenesisPath(home),paymentapp.MaxTxBytes);if err!=nil{return m,err};sum:=sha256.Sum256(b);if hex.EncodeToString(sum[:])!=m.PaymentGenesisSHA256{return m,errors.New("payment genesis mismatch")}
 for i:=0;i<NodeCount;i++{b,err=ReadBounded(cfg.DefaultConfig().SetRoot(NodeHome(home,i)).GenesisFile(),1<<20);if err!=nil{return m,err};sum=sha256.Sum256(b);if hex.EncodeToString(sum[:])!=m.ConsensusGenesisSHA256{return m,errors.New("consensus genesis mismatch")}}
 return m,nil
}
type Running struct{Node *node.Node;App *paymentapp.Application}
func Start(home string,index int,executable string,logger log.Logger)(*Running,error){
 if index<0||index>=NodeCount{return nil,errors.New("invalid node index")};m,err:=Load(home);if err!=nil{return nil,err}
 c:=cfg.DefaultConfig().SetRoot(NodeHome(home,index));c.Moniker=fmt.Sprintf("zevune-payment-local-%d",index)
 c.RPC.ListenAddress=fmt.Sprintf("tcp://127.0.0.1:%d",m.BasePort+2*index);c.RPC.GRPCListenAddress="";c.RPC.Unsafe=false;c.RPC.CORSAllowedOrigins=nil;c.RPC.MaxBodyBytes=128*1024;c.RPC.MaxOpenConnections=32;c.RPC.PprofListenAddress=""
 c.P2P.ListenAddress=fmt.Sprintf("tcp://127.0.0.1:%d",m.BasePort+2*index+1);c.P2P.ExternalAddress="";c.P2P.AddrBookStrict=false;c.P2P.AllowDuplicateIP=true;c.P2P.PexReactor=false;c.P2P.Seeds="";c.P2P.PersistentPeersMaxDialPeriod=time.Second
 peers:=[]string{};for i,id:=range m.NodeIDs{if i!=index{peers=append(peers,fmt.Sprintf("%s@127.0.0.1:%d",id,m.BasePort+2*i+1))}};c.P2P.PersistentPeers=strings.Join(peers,",")
 c.Consensus.CreateEmptyBlocks=true;c.Consensus.TimeoutCommit=400*time.Millisecond;c.Consensus.TimeoutPropose=time.Second;c.Consensus.TimeoutProposeDelta=500*time.Millisecond
 c.Mempool.Size=64;c.Mempool.MaxTxBytes=paymentapp.MaxTxBytes;c.Mempool.MaxTxsBytes=2*1024*1024;c.StateSync.Enable=false;c.TxIndex.Indexer="null";c.Instrumentation.Prometheus=false
 if err=c.ValidateBasic();err!=nil{return nil,err}
 for _,p:=range []string{c.PrivValidatorKeyFile(),c.PrivValidatorStateFile(),c.NodeKeyFile()}{fi,e:=os.Lstat(p);if e!=nil{return nil,e};if !fi.Mode().IsRegular(){return nil,errors.New("validator files must be regular")}}
 genesis,err:=types.GenesisDocFromFile(c.GenesisFile());if err!=nil{return nil,err};if genesis.ChainID!=ChainID||genesis.InitialHeight!=1||len(genesis.Validators)!=NodeCount{return nil,errors.New("unsupported genesis")}
 appHome:=filepath.Join(c.RootDir,"payment-application")
 if _,e:=os.Stat(filepath.Join(appHome,"payment.journal"));os.IsNotExist(e){for _,db:=range []string{"blockstore.db","state.db"}{if _,e=os.Stat(filepath.Join(c.DBDir(),db));e==nil{return nil,errors.New("missing payment state alongside existing consensus database")}}}
 a,err:=paymentapp.Open(executable,GenesisPath(home),appHome,m.PaymentGenesisSHA256);if err!=nil{return nil,err}
 pv:=privval.LoadFilePV(c.PrivValidatorKeyFile(),c.PrivValidatorStateFile());nk,err:=p2p.LoadNodeKey(c.NodeKeyFile());if err!=nil{_ = a.Close();return nil,err};pub,err:=pv.GetPubKey()
 if err!=nil||string(nk.ID())!=m.NodeIDs[index]||!pub.Equals(genesis.Validators[index].PubKey){_ = a.Close();return nil,errors.New("validator identity mismatch")}
 n,err:=node.NewNode(c,pv,nk,proxy.NewLocalClientCreator(a),node.DefaultGenesisDocProviderFunc(c),cfg.DefaultDBProvider,node.DefaultMetricsProvider(c.Instrumentation),logger);if err!=nil{_ = a.Close();return nil,err}
 if err=n.Start();err!=nil{_ = n.Stop();_ = a.Close();return nil,err};return &Running{n,a},nil
}
func(n *Running)Stop()error{var err error;if n.Node.IsRunning(){err=n.Node.Stop();n.Node.Wait()};return errors.Join(err,n.App.Close())}
