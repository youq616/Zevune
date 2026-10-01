package node

import (
	dbm "github.com/cometbft/cometbft-db"
	cfg "github.com/cometbft/cometbft/config"
	"github.com/cometbft/cometbft/internal/test"
	"github.com/cometbft/cometbft/libs/log"
	"github.com/cometbft/cometbft/p2p"
	p2pmock "github.com/cometbft/cometbft/p2p/mock"
	"github.com/cometbft/cometbft/privval"
	"github.com/cometbft/cometbft/proxy"
	"os"
	"sync"
	"testing"
	"time"
)

type lifetimeCloseDB struct {
	dbm.DB
	closed chan struct{}
	once   sync.Once
}

func (d *lifetimeCloseDB) Close() error { d.once.Do(func() { close(d.closed) }); return d.DB.Close() }

type lifetimeSendPeer struct {
	*p2pmock.Peer
	entered, release chan struct{}
	once, released   sync.Once
}

func (p *lifetimeSendPeer) Send(p2p.Envelope) bool {
	p.once.Do(func() { close(p.entered) })
	<-p.release
	return true
}
func (p *lifetimeSendPeer) unblock() { p.released.Do(func() { close(p.release) }) }

// This exercises real Node.OnStop ordering, not a surrogate call sequence. The
// controlled in-flight send belongs to the real consensus Reactor.AddPeer.
func TestNodeShutdownStoresAfterReactorConsumers(t *testing.T) {
	c := test.ResetTestRoot("node_shutdown_store_order")
	t.Cleanup(func() { _ = os.RemoveAll(c.RootDir) })
	c.P2P.ListenAddress = "tcp://127.0.0.1:0"
	c.RPC.ListenAddress = "tcp://127.0.0.1:0"
	c.RPC.GRPCListenAddress = ""
	closed := make(chan struct{})
	provider := func(ctx *cfg.DBContext) (dbm.DB, error) {
		d, e := cfg.DefaultDBProvider(ctx)
		if e != nil {
			return nil, e
		}
		if ctx.ID == "blockstore" {
			return &lifetimeCloseDB{DB: d, closed: closed}, nil
		}
		return d, nil
	}
	key, e := p2p.LoadOrGenNodeKey(c.NodeKeyFile())
	if e != nil {
		t.Fatal(e)
	}
	n, e := NewNode(c, privval.LoadOrGenFilePV(c.PrivValidatorKeyFile(), c.PrivValidatorStateFile()), key,
		proxy.DefaultClientCreator(c.ProxyApp, c.ABCI, c.DBDir()), DefaultGenesisDocProviderFunc(c), provider, DefaultMetricsProvider(c.Instrumentation), log.NewNopLogger())
	if e != nil {
		t.Fatal(e)
	}
	if e = n.Start(); e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() {
		if n.IsRunning() {
			_ = n.Stop()
		}
	})
	if n.consensusReactor.WaitSync() {
		t.Fatal("single-validator test node unexpectedly waiting for block sync")
	}
	p := &lifetimeSendPeer{Peer: p2pmock.NewPeer(nil), entered: make(chan struct{}), release: make(chan struct{})}
	t.Cleanup(func() { p.unblock(); _ = p.Stop() })
	n.consensusReactor.InitPeer(p)
	added := make(chan struct{})
	go func() { n.consensusReactor.AddPeer(p); close(added) }()
	select {
	case <-p.entered:
	case <-time.After(5 * time.Second):
		t.Fatal("initial real-reactor send did not start")
	}
	stopped := make(chan error, 1)
	go func() { stopped <- n.Stop() }()
	select {
	case <-closed:
		t.Error("Node closed blockstore before admitted reactor callback completed")
	case <-time.After(100 * time.Millisecond):
	}
	p.unblock()
	select {
	case <-added:
	case <-time.After(5 * time.Second):
		t.Fatal("AddPeer did not finish after release")
	}
	select {
	case e = <-stopped:
		if e != nil {
			t.Fatal(e)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Node did not finish shutdown")
	}
	select {
	case <-closed:
	default:
		t.Error("Node failed to close real blockstore after joining consumers")
	}
}
