package devnet

import (
 "bytes"
 "context"
 "fmt"
 "io"
 "math/rand/v2"
 "net"
 "os"
 "os/exec"
 "path/filepath"
 "strconv"
 "testing"
 "time"

 "github.com/cometbft/cometbft/libs/log"
 rpc "github.com/cometbft/cometbft/rpc/client/http"
 "github.com/cometbft/cometbft/types"
 "github.com/youq616/Zevune/internal/ledger"
)

func TestNodeProcessHelper(t *testing.T) {
 home:=os.Getenv("ZEVUNE_M3_NODE_HOME");if home==""{return}
 i,_:=strconv.Atoi(os.Getenv("ZEVUNE_M3_NODE_INDEX"))
 n,err:=Start(home,i,log.NewNopLogger());if err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(21)}
 _,_=io.Copy(io.Discard,os.Stdin)
 if err=n.Stop();err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(22)}
 os.Exit(0)
}
type child struct {cmd *exec.Cmd;in io.WriteCloser;done chan error;output bytes.Buffer;stopped bool}
func spawn(t *testing.T,home string,index int)*child {
 t.Helper();c:=&child{done:make(chan error,1)}
 c.cmd=exec.Command(os.Args[0],"-test.run=^TestNodeProcessHelper$")
 c.cmd.Env=append(os.Environ(),"ZEVUNE_M3_NODE_HOME="+home,"ZEVUNE_M3_NODE_INDEX="+strconv.Itoa(index))
 c.cmd.Stdout=&c.output;c.cmd.Stderr=&c.output
 var err error;c.in,err=c.cmd.StdinPipe();if err!=nil{t.Fatal(err)}
 if err=c.cmd.Start();err!=nil{t.Fatal(err)}
 go func(){c.done<-c.cmd.Wait()}()
 t.Cleanup(func(){stop(t,c,false)});return c
}
func stop(t *testing.T,c *child,kill bool){
 t.Helper();if c==nil||c.stopped{return};c.stopped=true
 if kill{_=c.cmd.Process.Kill()};_=c.in.Close()
 select{
 case err:=<-c.done:if err!=nil&&!kill{t.Errorf("node exit: %v %s",err,c.output.String())}
 case <-time.After(20*time.Second):_=c.cmd.Process.Kill();<-c.done;t.Error("node failed to stop gracefully")
 }
}
func freeBase(t *testing.T)int{
 t.Helper()
 for tries:=0;tries<80;tries++{
 base:=30000+rand.IntN(3000)*8;var listeners []net.Listener
 for i:=0;i<8;i++{l,err:=net.Listen("tcp",fmt.Sprintf("127.0.0.1:%d",base+i));if err!=nil{break};listeners=append(listeners,l)}
 for _,l:=range listeners{_=l.Close()};if len(listeners)==8{return base}
 }
 t.Fatal("no available local eight-port range");return 0
}
func client(t *testing.T,m Manifest,index int)*rpc.HTTP{
 t.Helper();c,err:=rpc.New(RPCAddress(m,index),"/websocket");if err!=nil{t.Fatal(err)};return c
}
func height(c *rpc.HTTP)int64{
 ctx,cancel:=context.WithTimeout(context.Background(),time.Second);defer cancel()
 s,err:=c.Status(ctx);if err!=nil{return -1};return s.SyncInfo.LatestBlockHeight
}
func waitHeight(t *testing.T,c *rpc.HTTP,target int64){
 t.Helper();deadline:=time.Now().Add(90*time.Second)
 for time.Now().Before(deadline){if height(c)>=target{return};time.Sleep(150*time.Millisecond)}
 t.Fatalf("node did not reach height %d; observed %d",target,height(c))
}
// Uses four independent OS processes communicating through real CometBFT TCP
// peers. No mock consensus, accepting verifier, simulated vote or wallet is used.
func TestFourProcessConsensusAndRecovery(t *testing.T){
 if testing.Short(){t.Skip("four-process integration test")}
 home:=filepath.Join(t.TempDir(),"cluster");m,err:=Init(home,freeBase(t));if err!=nil{t.Fatal(err)}
 nodes:=make([]*child,4);clients:=make([]*rpc.HTTP,4)
 for i:=range nodes{nodes[i]=spawn(t,home,i);clients[i]=client(t,m,i)}
 for _,c:=range clients{waitHeight(t,c,4)}
 common:=height(clients[0]);for _,c:=range clients{if h:=height(c);h<common{common=h}}
 gen,err:=types.GenesisDocFromFile(filepath.Join(home,"node0","config","genesis.json"));if err!=nil{t.Fatal(err)}
 vals:=make([]*types.Validator,4);for i,v:=range gen.Validators{vals[i]=types.NewValidator(v.PubKey,v.Power)}
 set:=types.NewValidatorSet(vals)
 expected,err:=ledger.New(ChainID,nil,ledger.UnavailableVerifier{});if err!=nil{t.Fatal(err)};defer expected.Close()
 for h:=uint64(1);h<uint64(common);h++{if _,err=expected.ApplyBlock(h,nil);err!=nil{t.Fatal(err)}}
 expectedHash:=expected.Summary().AppHash;var blockHash []byte
 for i,c:=range clients{
 ctx,cancel:=context.WithTimeout(context.Background(),5*time.Second);r,er:=c.Commit(ctx,&common);cancel();if er!=nil{t.Fatal(er)}
 signed:=r.SignedHeader
 if er=signed.ValidateBasic(ChainID);er!=nil{t.Fatal(er)}
 if er=set.VerifyCommit(ChainID,signed.Commit.BlockID,common,signed.Commit);er!=nil{t.Fatal(er)}
 if !bytes.Equal(signed.Header.Hash(),signed.Commit.BlockID.Hash)||!bytes.Equal(signed.Header.ValidatorsHash,set.Hash()){t.Fatal("unbound header")}
 if !bytes.Equal(signed.Header.AppHash,expectedHash[:]){t.Fatal("wrong application state at common height")}
 if i==0{blockHash=append([]byte(nil),signed.Header.Hash()...)}else if !bytes.Equal(blockHash,signed.Header.Hash()){t.Fatal("divergent committed blocks")}
 }
 t.Logf("four processes verified common height=%d; equal block/app hashes; >2/3 signatures verified",common)
 ctx,cancel:=context.WithTimeout(context.Background(),5*time.Second);tx,err:=clients[0].BroadcastTxSync(ctx,types.Tx("not a valid private payment"));cancel()
 if err!=nil||tx.Code==0{t.Fatalf("transaction was not rejected: %v %v",tx,err)}
 t.Log("payment admission rejected by real CometBFT RPC/mempool path")
 stop(t,nodes[3],false);base:=height(clients[0]);waitHeight(t,clients[0],base+3)
 t.Log("one validator offline: remaining 3/4 continued committing")
 stop(t,nodes[2],false);time.Sleep(3*time.Second)
 stalled:=height(clients[0]);time.Sleep(3*time.Second)
 if stalled<0||height(clients[0])!=stalled{t.Fatal("half voting power unexpectedly kept committing")}
 t.Logf("two validators offline: height remained %d over observation window",stalled)
 nodes[2]=spawn(t,home,2);waitHeight(t,clients[0],stalled+3)
 nodes[3]=spawn(t,home,3);target:=height(clients[0]);waitHeight(t,clients[3],target)
 t.Log("restored quorum and lagging validator catch-up succeeded")
 stop(t,nodes[3],true);target=height(clients[0])+2;waitHeight(t,clients[0],target)
 nodes[3]=spawn(t,home,3);waitHeight(t,clients[3],target)
 t.Log("abrupt process termination recovered without resetting validator state")
 for _,n:=range nodes{stop(t,n,false)};before:=target
 for i:=range nodes{nodes[i]=spawn(t,home,i)}
 for _,c:=range clients{waitHeight(t,c,before+3)}
 t.Log("full four-process restart resumed from durable application/consensus state")
}
func TestInitAndManifestFailClosed(t *testing.T){
 home:=filepath.Join(t.TempDir(),"cluster");_,err:=Init(home,freeBase(t));if err!=nil{t.Fatal(err)}
 if _,err=Init(home,31000);err==nil{t.Fatal("existing home overwritten")}
 p:=filepath.Join(home,"node1","config","genesis.json")
 if err=os.WriteFile(p,[]byte("{}"),0600);err!=nil{t.Fatal(err)}
 if _,err=Load(home);err==nil{t.Fatal("altered genesis accepted")}
 if _,err=Start(home,-1,log.NewNopLogger());err==nil{t.Fatal("invalid index")}
}
