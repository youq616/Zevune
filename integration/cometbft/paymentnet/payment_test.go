package paymentnet

import (
 "bytes"
 "context"
 "encoding/hex"
 "encoding/json"
 "errors"
 "fmt"
 "io"
 "math/rand/v2"
 "net"
 "os"
 "os/exec"
 "path/filepath"
 "strconv"
 "strings"
 "testing"
 "time"
 "github.com/cometbft/cometbft/libs/log"
 "github.com/youq616/Zevune/integration/cometbft/paymentapp"
)

const testPassword = "generated-test-only-password-not-a-real-secret"
func TestPaymentProcessHelper(t *testing.T) {
 home := os.Getenv("ZEVUNE_PAY_HELPER"); if home == "" { return }
 i,err := strconv.Atoi(os.Getenv("ZEVUNE_PAY_INDEX")); if err != nil { os.Exit(11) }
 n,err := Start(home,i,os.Getenv("ZEVUNE_CRYPTO_BIN"),log.NewNopLogger())
 if err != nil { fmt.Fprintln(os.Stderr,err); os.Exit(12) }
 _,_ = io.Copy(io.Discard,os.Stdin)
 if err = n.Stop(); err != nil { fmt.Fprintln(os.Stderr,err); os.Exit(13) }; os.Exit(0)
}
type process struct { cmd *exec.Cmd; input io.WriteCloser; done chan error; output bytes.Buffer; stopped bool }
func spawn(t *testing.T,home string,i int) *process {
 t.Helper(); p := &process{done:make(chan error,1)}
 p.cmd=exec.Command(os.Args[0],"-test.run=^TestPaymentProcessHelper$")
 p.cmd.Env=append(os.Environ(),"ZEVUNE_PAY_HELPER="+home,"ZEVUNE_PAY_INDEX="+strconv.Itoa(i))
 p.cmd.Stdout=&p.output; p.cmd.Stderr=&p.output; var err error
 p.input,err=p.cmd.StdinPipe(); if err!=nil { t.Fatal(err) }; if err=p.cmd.Start();err!=nil{t.Fatal(err)}
 go func(){p.done<-p.cmd.Wait()}(); t.Cleanup(func(){stop(t,p,false)}); return p
}
func stop(t *testing.T,p *process,kill bool) {
 t.Helper(); if p==nil||p.stopped{return}; p.stopped=true
 if kill {_ = p.cmd.Process.Kill()}; _ = p.input.Close()
 select { case err:=<-p.done: if err!=nil&&!kill {t.Errorf("node exit %v: %s",err,p.output.String())}
 case <-time.After(20*time.Second): _ = p.cmd.Process.Kill(); <-p.done; t.Error("node did not shut down") }
}
func availablePort(t *testing.T) int {
 t.Helper(); for n:=0;n<80;n++ {base:=30000+rand.IntN(3000)*8; var listeners []net.Listener
  for i:=0;i<8;i++ { l,err:=net.Listen("tcp",fmt.Sprintf("127.0.0.1:%d",base+i)); if err!=nil{break}; listeners=append(listeners,l) }
  for _,l:=range listeners{_ = l.Close()}; if len(listeners)==8{return base}
 }; t.Fatal("no local ports"); return 0
}
func crypto(t *testing.T,pw bool,args ...string) string {
 t.Helper(); ctx,cancel:=context.WithTimeout(context.Background(),2*time.Minute); defer cancel()
 if pw{args=append(args,"--password-stdin")}; cmd:=exec.CommandContext(ctx,os.Getenv("ZEVUNE_CRYPTO_BIN"),args...)
 if pw{cmd.Stdin=strings.NewReader(testPassword+"\n")}; var stderr bytes.Buffer; cmd.Stderr=&stderr; out,err:=cmd.Output()
 if err!=nil{t.Fatalf("crypto command %s failed: %v %s",args[0],err,stderr.String())}; return strings.TrimSpace(string(out))
}
func waitState(t *testing.T,home string,index int,at uint64) paymentapp.Summary {
 t.Helper(); deadline:=time.Now().Add(90*time.Second)
 for time.Now().Before(deadline) {ctx,cancel:=context.WithTimeout(context.Background(),3*time.Second); s,err:=Summary(ctx,home,index); cancel(); if err==nil&&s.Height>=at{return s}; time.Sleep(150*time.Millisecond)}
 t.Fatalf("payment node %d did not reach %d",index,at); return paymentapp.Summary{}
}
func export(t *testing.T,home,path string) paymentapp.Export {
 t.Helper(); ctx,cancel:=context.WithTimeout(context.Background(),30*time.Second); defer cancel()
 e,err:=ExportVerified(ctx,home,0); if err!=nil{t.Fatal(err)}; data,err:=json.Marshal(e); if err!=nil{t.Fatal(err)}; if err=WriteNew(path,data);err!=nil{t.Fatal(err)}; return e
}
func submit(t *testing.T,home,path string) Receipt {
 t.Helper(); tx,err:=ReadBounded(path,32768); if err!=nil{t.Fatal(err)}; ctx,cancel:=context.WithTimeout(context.Background(),30*time.Second);defer cancel()
 r,err:=Submit(ctx,home,tx);if err!=nil{t.Fatal(err)};return r
}
func rejected(t *testing.T,home string,tx []byte) {
 t.Helper();ctx,cancel:=context.WithTimeout(context.Background(),10*time.Second);defer cancel()
 if _,err:=Submit(ctx,home,tx);!errors.Is(err,paymentapp.ErrRejected){t.Fatalf("expected explicit transaction rejection, got %v",err)}
}
func TestFourNodePrivatePaymentsAndRecovery(t *testing.T) {
 if os.Getenv("ZEVUNE_CRYPTO_BIN")==""{if os.Getenv("ZEVUNE_M5_REQUIRE")=="1"{t.Fatal("missing genuine crypto executable")};t.Skip("run dedicated payment integration job with Rust executable")}
 dir:=t.TempDir();home:=filepath.Join(dir,"network");a:=filepath.Join(dir,"a.wallet");b:=filepath.Join(dir,"b.wallet");c:=filepath.Join(dir,"c.wallet")
 addrA:=crypto(t,true,"wallet-new",a);addrB:=crypto(t,true,"wallet-new",b);addrC:=crypto(t,true,"wallet-new",c)
 backup:=filepath.Join(dir,"b.backup");crypto(t,true,"backup",b,backup);restored:=filepath.Join(dir,"b-restored.wallet");crypto(t,true,"restore",backup,restored)
 if crypto(t,true,"address",restored)!=addrB{t.Fatal("backup changed receiver")}
 genesis:=filepath.Join(dir,"genesis.bin");crypto(t,false,"genesis",addrA,genesis)
 _,err:=Init(home,availablePort(t),os.Getenv("ZEVUNE_CRYPTO_BIN"),genesis);if err!=nil{t.Fatal(err)}
 nodes:=make([]*process,4);for i:=range nodes{nodes[i]=spawn(t,home,i)};for i:=range nodes{waitState(t,home,i,3)}
 initial:=filepath.Join(dir,"initial.json");export(t,home,initial)
 first:=filepath.Join(dir,"first.tx");start:=time.Now();crypto(t,true,"prepare",a,initial,genesis,addrB,"600000",first);prepared:=time.Now()
 raw,err:=ReadBounded(first,32768);if err!=nil{t.Fatal(err)}
 corrupt:=append([]byte{},raw...);corrupt[len(corrupt)-1]^=1
 // Check the bad authorization BEFORE consuming its nullifier. A double-spend
 // rejection must not mask missing signature verification.
 rejected(t,home,corrupt)
 genesisBytes,err:=ReadBounded(genesis,32768);if err!=nil{t.Fatal(err)};rejected(t,home,genesisBytes)
 admittedAt:=time.Now();r1:=submit(t,home,first);confirmed:=time.Now()
 after:=filepath.Join(dir,"after-first.json");e:=export(t,home,after)
 if crypto(t,true,"balance",restored,after,genesis)!="600000"{t.Fatal("recipient did not recover actual first receipt")}
 scanned:=time.Now()
 if crypto(t,true,"balance",a,after,genesis)!="399000"{t.Fatal("wrong change")}
 t.Logf("M5_TIMING cold_prepare_ms=%.3f submit_checkpoint_ms=%.3f subsequent_export_and_recipient_cold_scan_ms=%.3f height=%d; single sample, no p95; rejection probes excluded",float64(prepared.Sub(start).Microseconds())/1000,float64(confirmed.Sub(admittedAt).Microseconds())/1000,float64(scanned.Sub(confirmed).Microseconds())/1000,r1.Height)
 rejected(t,home,raw)
 tampered:=e;tampered.Blocks=append([]paymentapp.Block{},e.Blocks...)
 for i:=range tampered.Blocks{if len(tampered.Blocks[i].Txs)>0{tampered.Blocks[i].Txs=[]string{hex.EncodeToString(corrupt)};break}}
 if VerifyHistory(tampered,genesisBytes)==nil{t.Fatal("modified public history authenticated")}
 second:=filepath.Join(dir,"second.tx");crypto(t,true,"prepare",restored,after,genesis,addrC,"250000",second);r2:=submit(t,home,second)
 final:=filepath.Join(dir,"final.json");finalExport:=export(t,home,final)
 if crypto(t,true,"balance",restored,final,genesis)!="349000"||crypto(t,true,"balance",c,final,genesis)!="250000"{t.Fatal("onward payment or change mismatch")}
 if finalExport.Summary.BurnedFees!=2000{t.Fatal("fee accounting")}
 for i:=range nodes{s:=waitState(t,home,i,r2.Height+2);if s.BurnedFees!=2000||s.NoteRoot!=finalExport.Summary.NoteRoot{t.Fatal("divergent payment effects")}}
 stop(t,nodes[3],true);nodes[3]=spawn(t,home,3);waitState(t,home,3,r2.Height+4)
 var highest uint64
 for i:=range nodes{s:=waitState(t,home,i,r2.Height+4);if s.Height>highest{highest=s.Height};stop(t,nodes[i],false)}
 for i:=range nodes{
  bridge,err:=paymentapp.OpenBridge(os.Getenv("ZEVUNE_CRYPTO_BIN"),GenesisPath(home),filepath.Join(NodeHome(home,i),"payment-application"));if err!=nil{t.Fatal(err)}
  var s paymentapp.Summary;err=bridge.Call(context.Background(),map[string]any{"op":"info"},&s);_ = bridge.Close();if err!=nil{t.Fatal(err)};if s.Height>highest{highest=s.Height}
 }
 for i:=range nodes{nodes[i]=spawn(t,home,i)}
 for i:=range nodes{s:=waitState(t,home,i,highest+3);if s.BurnedFees!=2000||s.NoteRoot!=finalExport.Summary.NoteRoot{t.Fatal("restart changed assets")}}
 recovered:=filepath.Join(dir,"recovered.json");export(t,home,recovered)
 if crypto(t,true,"balance",restored,recovered,genesis)!="349000"{t.Fatal("wallet restore rescan after node restart")}
 t.Log("M5 four consensus processes plus private crypto workers: genuine two-hop transfers, signed checkpoints, explicit replay/tamper/mint rejection, encrypted-wallet rescan, crash and full-cluster restart passed")
}
