// zevune-paynet is a local-only test-asset network, never a mainnet launcher.
package main
import("context";"encoding/json";"errors";"flag";"fmt";"io";"os";"os/exec";"os/signal";"path/filepath";"strconv";"time";"github.com/cometbft/cometbft/libs/log";"github.com/youq616/Zevune/integration/cometbft/paymentnet")
func main(){if err:=run();err!=nil{fmt.Fprintln(os.Stderr,"Zevune payment laboratory:",err);os.Exit(1)}}
func run()error{
 action:=flag.String("action","status","init|start|node|status|export|submit|version")
 home:=flag.String("home","","new separate local payment-network directory")
 crypto:=flag.String("crypto","","absolute path to zevune-crypto executable")
 genesis:=flag.String("genesis","","public proven genesis file for initialization")
 port:=flag.Int("port",29650,"base of eight numeric loopback ports")
 index:=flag.Int("index",0,"node index")
 out:=flag.String("out","","new output file; never overwritten")
 tx:=flag.String("tx","","canonical public transaction file")
 flag.Parse();if flag.NArg()!=0{return errors.New("unexpected arguments")};if *action=="version"{fmt.Println("Zevune 0.3.0-dev LOCAL TEST ASSETS ONLY");return nil};if *home==""{return errors.New("home required")}
 absolute,err:=filepath.Abs(*home);if err!=nil{return err};*home=absolute
 ctx,cancel:=context.WithTimeout(context.Background(),2*time.Minute);defer cancel()
 switch *action{
 case "init":if *crypto==""||*genesis==""{return errors.New("crypto and genesis required")};m,e:=paymentnet.Init(*home,*port,*crypto,*genesis);if e!=nil{return e};return json.NewEncoder(os.Stdout).Encode(m)
 case "status":s,e:=paymentnet.Summary(ctx,*home,*index);if e!=nil{return e};return json.NewEncoder(os.Stdout).Encode(s)
 case "export":if *out==""{return errors.New("new output path required")};e,err:=paymentnet.ExportVerified(ctx,*home,*index);if err!=nil{return err};data,err:=json.Marshal(e);if err!=nil{return err};if err=paymentnet.WriteNew(*out,data);err!=nil{return err};fmt.Println("public history checkpoint signatures verified; no wallet keys exported");return nil
 case "submit":if *tx==""{return errors.New("transaction file required")};bytes,e:=paymentnet.ReadBounded(*tx,32768);if e!=nil{return e};r,e:=paymentnet.Submit(ctx,*home,bytes);if e!=nil{return e};return json.NewEncoder(os.Stdout).Encode(r)
 case "node":
  if *crypto==""{return errors.New("crypto executable required")};n,e:=paymentnet.Start(*home,*index,*crypto,log.NewNopLogger());if e!=nil{return e}
  stop,finish:=signal.NotifyContext(context.Background(),os.Interrupt);defer finish();closed:=make(chan struct{});go func(){_,_=io.Copy(io.Discard,os.Stdin);close(closed)}();select{case<-stop.Done():case<-closed:};return n.Stop()
 case "start":return cluster(*home,*crypto)
 default:return errors.New("unknown action")
 }
}
func cluster(home,crypto string)error{
 if crypto==""{return errors.New("crypto executable required")};if _,err:=paymentnet.Load(home);err!=nil{return err}
 executable,err:=os.Executable();if err!=nil{return err};crypto,err=filepath.Abs(crypto);if err!=nil{return err}
 ctx,cancel:=signal.NotifyContext(context.Background(),os.Interrupt);defer cancel()
 type child struct{cmd *exec.Cmd;stdin io.WriteCloser;done chan struct{};err error}
 children:=make([]*child,0,4);exited:=make(chan int,4)
 defer func(){for _,c:=range children{_ = c.stdin.Close()};for _,c:=range children{select{case<-c.done:case<-time.After(10*time.Second):_ = c.cmd.Process.Kill();<-c.done}}}()
 for i:=0;i<4;i++{
  c:=&child{cmd:exec.Command(executable,"-action","node","-home",home,"-crypto",crypto,"-index",strconv.Itoa(i)),done:make(chan struct{})};c.cmd.Stdout=os.Stdout;c.cmd.Stderr=os.Stderr;c.stdin,err=c.cmd.StdinPipe();if err!=nil{return err}
  if err=c.cmd.Start();err!=nil{_ = c.stdin.Close();return err};children=append(children,c)
  go func(i int,c *child){c.err=c.cmd.Wait();close(c.done);exited<-i}(i,c)
 }
 fmt.Println("Zevune local test-asset network started: four consensus processes and four private crypto workers. No real funds. Ctrl+C stops all children.")
 select{case<-ctx.Done():return nil;case i:=<-exited:return fmt.Errorf("node %d exited; cluster stopping: %v",i,children[i].err)}
}
