// Package paymentapp adapts the NO-FUNDS Rust payment state through private pipes.
package paymentapp
import("bytes";"context";"encoding/binary";"encoding/json";"errors";"io";"os";"os/exec";"path/filepath";"sync";"time")
var ErrRejected=errors.New("test transaction or state request rejected")
const MaxRequest=600000
const MaxResponse=32*1024*1024
type Summary struct{
 ChainID string `json:"chain_id"`;GenesisID string `json:"genesis_id"`;Height uint64 `json:"height"`
 AppHash string `json:"app_hash"`;StateHash string `json:"state_hash"`;HistoryHash string `json:"history_hash"`
 NoteRoot string `json:"note_root"`;NoteCount uint64 `json:"note_count"`;SpentCount uint64 `json:"spent_count"`
 BurnedFees uint64 `json:"burned_fees"`;TestAssetPayments bool `json:"test_asset_payments"`;RealFundsAllowed bool `json:"real_funds_allowed"`
}
type Block struct{Height uint64 `json:"height"`;Hash string `json:"hash"`;Txs []string `json:"txs"`}
type Export struct{Format int `json:"format"`;Genesis string `json:"genesis"`;Blocks []Block `json:"blocks"`;Summary Summary `json:"summary"`}
type response struct{ID uint64 `json:"id"`;OK bool `json:"ok"`;Error *string `json:"error"`;Data json.RawMessage `json:"data"`}
type Bridge struct{mu sync.Mutex;cmd *exec.Cmd;input io.WriteCloser;output io.ReadCloser;done chan error;sequence uint64;closed bool}
func OpenBridge(executable,genesis,home string)(*Bridge,error){
 absolute,err:=filepath.Abs(executable);if err!=nil{return nil,err};fi,err:=os.Lstat(absolute);if err!=nil{return nil,err};if !fi.Mode().IsRegular(){return nil,errors.New("crypto executable must be a regular file")}
 cmd:=exec.Command(absolute,"serve",genesis,home);cmd.Env=append(os.Environ(),"RAYON_NUM_THREADS=2");cmd.Stderr=io.Discard
 input,err:=cmd.StdinPipe();if err!=nil{return nil,err};output,err:=cmd.StdoutPipe();if err!=nil{_ = input.Close();return nil,err};if err=cmd.Start();err!=nil{_ = input.Close();_ = output.Close();return nil,err}
 b:=&Bridge{cmd:cmd,input:input,output:output,done:make(chan error,1)};go func(){b.done<-cmd.Wait();close(b.done)}()
 var summary Summary;if err=b.Call(context.Background(),map[string]any{"op":"info"},&summary);err!=nil{_ = b.Close();return nil,err};return b,nil
}
func(b *Bridge)Call(ctx context.Context,request map[string]any,destination any)error{
 b.mu.Lock();defer b.mu.Unlock();if b.closed{return errors.New("crypto worker unavailable")};if err:=ctx.Err();err!=nil{return err};b.sequence++;request["id"]=b.sequence
 payload,err:=json.Marshal(request);if err!=nil{return err};if len(payload)>MaxRequest{return errors.New("worker request limit")};result:=make(chan error,1);var reply response
 go func(){
  header:=make([]byte,4);binary.BigEndian.PutUint32(header,uint32(len(payload)));if _,e:=io.Copy(b.input,bytes.NewReader(append(header,payload...)));e!=nil{result<-e;return}
  if _,e:=io.ReadFull(b.output,header);e!=nil{result<-e;return};n:=binary.BigEndian.Uint32(header);if n==0||n>MaxResponse{result<-errors.New("worker response limit");return}
  data:=make([]byte,int(n));if _,e:=io.ReadFull(b.output,data);e!=nil{result<-e;return};decoder:=json.NewDecoder(bytes.NewReader(data));decoder.DisallowUnknownFields();if e:=decoder.Decode(&reply);e!=nil{result<-e;return};var extra any;if decoder.Decode(&extra)!=io.EOF{result<-errors.New("trailing worker data");return};result<-nil
 }()
 timer:=time.NewTimer(30*time.Second);defer timer.Stop();select{case err=<-result:case<-ctx.Done():err=ctx.Err();case<-timer.C:err=errors.New("crypto worker request timeout")}
 if err!=nil{b.closed=true;_ = b.cmd.Process.Kill();_ = b.input.Close();_ = b.output.Close();return err};if reply.ID!=b.sequence{b.closed=true;_ = b.cmd.Process.Kill();return errors.New("worker sequence mismatch")}
 if !reply.OK{if reply.Error!=nil&&*reply.Error=="rejected"{return ErrRejected};b.closed=true;_ = b.cmd.Process.Kill();return errors.New("crypto worker storage unavailable")};if reply.Error!=nil{return errors.New("inconsistent worker response")};return json.Unmarshal(reply.Data,destination)
}
func(b *Bridge)Close()error{b.mu.Lock();defer b.mu.Unlock();b.closed=true;_ = b.input.Close();select{case<-b.done:_ = b.output.Close();return nil;case<-time.After(3*time.Second):_ = b.cmd.Process.Kill();_ = b.output.Close();return errors.New("worker shutdown required termination")}}
