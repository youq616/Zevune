package paymentnet
import(
 "bytes"
 "context"
 "crypto/sha256"
 "encoding/binary"
 "encoding/hex"
 "encoding/json"
 "errors"
 "io"
 "math"
 "net/http"
 "path/filepath"
 "time"
 cfg "github.com/cometbft/cometbft/config"
 rpc "github.com/cometbft/cometbft/rpc/client/http"
 "github.com/cometbft/cometbft/types"
 "github.com/youq616/Zevune/integration/cometbft/paymentapp"
)
type limitedBody struct{io.Reader;io.Closer}
type transport struct{}
func(transport)RoundTrip(r *http.Request)(*http.Response,error){res,err:=http.DefaultTransport.RoundTrip(r);if err==nil{res.Body=limitedBody{io.LimitReader(res.Body,48*1024*1024),res.Body}};return res,err}
func Client(m Manifest,index int)(*rpc.HTTP,error){
 if index<0||index>=NodeCount{return nil,errors.New("invalid node index")}
 return rpc.NewWithClient(RPCAddress(m,index),"/websocket",&http.Client{Timeout:10*time.Second,Transport:transport{},CheckRedirect:func(*http.Request,[]*http.Request)error{return errors.New("RPC redirects disabled")}})
}
func Summary(ctx context.Context,home string,index int)(paymentapp.Summary,error){
 var out paymentapp.Summary;m,err:=Load(home);if err!=nil{return out,err};c,err:=Client(m,index);if err!=nil{return out,err}
 res,err:=c.ABCIQuery(ctx,"/payment/status",nil);if err!=nil{return out,err};if res.Response.Code!=0{return out,errors.New("status rejected")};err=json.Unmarshal(res.Response.Value,&out);return out,err
}
func hashBytes(text string)([]byte,error){if len(text)!=64{return nil,errors.New("invalid hash")};b,err:=hex.DecodeString(text);if err!=nil||hex.EncodeToString(b)!=text{return nil,errors.New("noncanonical hash")};return b,nil}
// VerifyHistory binds the exact ordered public transaction bytes to a signed
// application hash. Rust separately re-executes effects before wallet spending.
func VerifyHistory(e paymentapp.Export,expectedGenesis []byte)error{
 if e.Format!=1||len(e.Blocks)>4096||e.Summary.Height!=uint64(len(e.Blocks))||e.Summary.ChainID!=ChainID||e.Summary.RealFundsAllowed{return errors.New("invalid export context")}
 g,err:=hex.DecodeString(e.Genesis);if err!=nil||!bytes.Equal(g,expectedGenesis){return errors.New("export genesis mismatch")};id:=sha256.Sum256(g);if e.Summary.GenesisID!=hex.EncodeToString(id[:]){return errors.New("wrong genesis ID")}
 prior:=make([]byte,32);var total int
 for i,b:=range e.Blocks{
  if b.Height!=uint64(i+1)||len(b.Txs)>paymentapp.MaxBlockTxs{return errors.New("export height or transaction limit")};blockHash,err:=hashBytes(b.Hash);if err!=nil{return err}
  h:=sha256.New();_,_=h.Write([]byte("ZEVUNE-PAYMENT-LAB-HISTORY\x00\x01"));_,_=h.Write(prior)
  var height [8]byte;binary.BigEndian.PutUint64(height[:],b.Height);_,_=h.Write(height[:]);_,_=h.Write(blockHash)
  var count [4]byte;binary.BigEndian.PutUint32(count[:],uint32(len(b.Txs)));_,_=h.Write(count[:])
  for _,tx:=range b.Txs{
   if len(tx)>paymentapp.MaxTxBytes*2{return errors.New("transaction limit")};raw,err:=hex.DecodeString(tx);if err!=nil||hex.EncodeToString(raw)!=tx{return errors.New("invalid transaction bytes")};total+=len(raw);if total>8*1024*1024{return errors.New("history limit")}
   binary.BigEndian.PutUint32(count[:],uint32(len(raw)));_,_=h.Write(count[:]);_,_=h.Write(raw)
  };prior=h.Sum(nil)
 }
 if hex.EncodeToString(prior)!=e.Summary.HistoryHash{return errors.New("export history digest mismatch")}
 stateHash,err:=hashBytes(e.Summary.StateHash);if err!=nil{return err};h:=sha256.New();_,_=h.Write([]byte("ZEVUNE-PAYMENT-LAB-APP\x00\x01"));_,_=h.Write(stateHash);_,_=h.Write(prior)
 if hex.EncodeToString(h.Sum(nil))!=e.Summary.AppHash{return errors.New("export application digest mismatch")};return nil
}
// ExportVerified authenticates the checkpoint against the ORIGINAL local
// genesis validator set. It does not implement dynamic-validator light sync.
func ExportVerified(ctx context.Context,home string,index int)(paymentapp.Export,error){
 var out paymentapp.Export;m,err:=Load(home);if err!=nil{return out,err};c,err:=Client(m,index);if err!=nil{return out,err}
 res,err:=c.ABCIQuery(ctx,"/payment/export",nil);if err!=nil{return out,err};if res.Response.Code!=0||len(res.Response.Value)>paymentapp.MaxResponse{return out,errors.New("export unavailable")}
 decoder:=json.NewDecoder(bytes.NewReader(res.Response.Value));decoder.DisallowUnknownFields();if err=decoder.Decode(&out);err!=nil{return out,err};var trailing any;if decoder.Decode(&trailing)!=io.EOF{return out,errors.New("trailing export")}
 genesisBytes,err:=ReadBounded(GenesisPath(home),paymentapp.MaxTxBytes);if err!=nil{return out,err};if err=VerifyHistory(out,genesisBytes);err!=nil{return out,err}
 if out.Summary.Height>=math.MaxInt64{return out,errors.New("export height overflow")};next:=int64(out.Summary.Height)+1
 genesis,err:=types.GenesisDocFromFile(cfg.DefaultConfig().SetRoot(filepath.Join(home,"node0")).GenesisFile());if err!=nil{return out,err};validators:=make([]*types.Validator,len(genesis.Validators));for i,v:=range genesis.Validators{validators[i]=types.NewValidator(v.PubKey,v.Power)};set:=types.NewValidatorSet(validators)
 ticker:=time.NewTicker(100*time.Millisecond);defer ticker.Stop()
 for{
  signed,err:=c.Commit(ctx,&next)
  if err==nil{
   header:=signed.SignedHeader
   if header.ValidateBasic(ChainID)!=nil||!bytes.Equal(header.Header.Hash(),header.Commit.BlockID.Hash)||!bytes.Equal(header.Header.ValidatorsHash,set.Hash())||!bytes.Equal(header.Header.NextValidatorsHash,set.Hash()){return out,errors.New("unbound checkpoint")}
   if err=set.VerifyCommit(ChainID,header.Commit.BlockID,next,header.Commit);err!=nil{return out,err}
   appHash,err:=hashBytes(out.Summary.AppHash);if err!=nil||!bytes.Equal(header.Header.AppHash,appHash){return out,errors.New("checkpoint does not authenticate exported application state")};return out,nil
  }
  select{case<-ctx.Done():return out,ctx.Err();case<-ticker.C:}
 }
}
type Receipt struct { Status string `json:"status"`; Height uint64 `json:"height"`; CheckpointHeight uint64 `json:"checkpoint_height"`; TxHash string `json:"tx_hash"`; AppHash string `json:"app_hash"` }
func Submit(ctx context.Context,home string,tx []byte)(Receipt,error){
 var receipt Receipt;if len(tx)==0||len(tx)>paymentapp.MaxTxBytes{return receipt,errors.New("invalid transaction size")};m,err:=Load(home);if err!=nil{return receipt,err};c,err:=Client(m,0);if err!=nil{return receipt,err}
 admitted,err:=c.BroadcastTxSync(ctx,types.Tx(tx));if err!=nil{return receipt,err};if admitted.Code!=0{return receipt,paymentapp.ErrRejected}
 want:=hex.EncodeToString(tx);ticker:=time.NewTicker(150*time.Millisecond);defer ticker.Stop()
 for{
  e,err:=ExportVerified(ctx,home,0)
  if err==nil{for _,b:=range e.Blocks{for _,raw:=range b.Txs{if raw==want{return Receipt{Status:"local_test_asset_committed",Height:b.Height,CheckpointHeight:e.Summary.Height+1,TxHash:hex.EncodeToString(types.Tx(tx).Hash()),AppHash:e.Summary.AppHash},nil}}}}
  select{case<-ctx.Done():return receipt,errors.New("submission outcome not confirmed; preserve transaction and check history before retrying");case<-ticker.C:}
 }
}
