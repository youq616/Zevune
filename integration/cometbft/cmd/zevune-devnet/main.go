// zevune-devnet runs a loopback-only laboratory, never a production validator.
package main

import (
 "errors"
 "flag"
 "fmt"
 "io"
 "os"
 "os/exec"
 "os/signal"
 "path/filepath"
 "time"

 "github.com/cometbft/cometbft/libs/log"
 "github.com/youq616/Zevune/integration/cometbft/app"
 "github.com/youq616/Zevune/integration/cometbft/devnet"
)

func run() error {
 fs:=flag.NewFlagSet("zevune-devnet",flag.ContinueOnError)
 home:=fs.String("home","","required new laboratory directory, separate from old ledger data")
 base:=fs.Int("base-port",28650,"init: first of eight loopback ports")
 index:=fs.Int("index",0,"node: index 0..3")
 action:=fs.String("action","start","init, start, node, version")
 managed:=fs.Bool("managed",false,"internal: stop node when parent closes stdin")
 if err:=fs.Parse(os.Args[1:]);err!=nil{return err}
 if fs.NArg()!=0{return errors.New("unexpected positional arguments")}
 if *action=="version"{fmt.Println("Zevune",app.Version,"CometBFT v0.38.26 NO-FUNDS");return nil}
 if *home==""{return errors.New("-home is required; do not use an existing wallet or M1/M2 data directory")}
 absolute,err:=filepath.Abs(*home);if err!=nil{return err}
 switch *action{
 case "init":
 _,err=devnet.Init(absolute,*base)
 if err==nil{fmt.Println("Initialized four local validators. NO PAYMENTS. Preserve all signing-state files.")}
 return err
 case "node":
 n,err:=devnet.Start(absolute,*index,log.NewTMLogger(log.NewSyncWriter(os.Stderr)));if err!=nil{return err}
 signals:=make(chan os.Signal,1);signal.Notify(signals,os.Interrupt);defer signal.Stop(signals)
 parentClosed:=make(chan struct{})
 if *managed{go func(){_,_=io.Copy(io.Discard,os.Stdin);close(parentClosed)}()}
 select{case <-signals:case <-parentClosed:}
 return n.Stop()
 case "start":
 m,err:=devnet.Load(absolute);if err!=nil{return err}
 binary,err:=os.Executable();if err!=nil{return err}
 var commands []*exec.Cmd;var inputs []io.WriteCloser
 exits:=make(chan error,devnet.NodeCount);stopped:=false
 stop:=func(){
 if stopped{return};stopped=true
 for _,in:=range inputs{_=in.Close()}
 deadline:=time.NewTimer(15*time.Second);defer deadline.Stop()
 for range commands{select{case <-exits:case <-deadline.C:for _,cmd:=range commands{_=cmd.Process.Kill()};return}}
 }
 defer stop()
 for i:=0;i<devnet.NodeCount;i++{
 cmd:=exec.Command(binary,"-action","node","-home",absolute,"-index",fmt.Sprint(i),"-managed")
 in,er:=cmd.StdinPipe();if er!=nil{return er}
 cmd.Stdout,cmd.Stderr=os.Stdout,os.Stderr
 if er=cmd.Start();er!=nil{_=in.Close();return er}
 commands,inputs=append(commands,cmd),append(inputs,in)
 go func(){exits<-cmd.Wait()}()
 fmt.Printf("node%d RPC %s; local empty blocks only\n",i,devnet.RPCAddress(m,i))
 }
 signals:=make(chan os.Signal,1);signal.Notify(signals,os.Interrupt);defer signal.Stop(signals)
 select{
 case <-signals:return nil
 case err=<-exits:
 exits<-err
 return fmt.Errorf("a validator process exited; laboratory stopped: %v",err)
 }
 default:return errors.New("unsupported action")
 }
}
func main(){if err:=run();err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(1)}}
