package consensus

import (
	"runtime"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/cometbft/cometbft/abci/example/kvstore"
	cfg "github.com/cometbft/cometbft/config"
	cstypes "github.com/cometbft/cometbft/consensus/types"
	"github.com/cometbft/cometbft/libs/bits"
	"github.com/cometbft/cometbft/libs/log"
	"github.com/cometbft/cometbft/p2p"
	p2pmock "github.com/cometbft/cometbft/p2p/mock"
	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
	sm "github.com/cometbft/cometbft/state"
	"github.com/cometbft/cometbft/types"
)

// This test-only barrier advertises fixture heights solely to select the real
// reactor consumer. It never accepts a block, signature or authorization.
type shutdownReadBarrier struct {
	sm.BlockStore
	kind           string
	entered        chan struct{}
	release        chan struct{}
	once           sync.Once
	released       sync.Once
	closed         atomic.Bool
	readAfterClose atomic.Bool
}

func (b *shutdownReadBarrier) Base() int64   { return 1 }
func (b *shutdownReadBarrier) Height() int64 { return 3 }
func (b *shutdownReadBarrier) gate(kind string) {
	if b.kind != kind {
		return
	}
	b.once.Do(func() { close(b.entered) })
	<-b.release
	if b.closed.Load() {
		b.readAfterClose.Store(true)
	}
}
func (b *shutdownReadBarrier) LoadBlockMeta(h int64) *types.BlockMeta {
	b.gate("data")
	return b.BlockStore.LoadBlockMeta(h)
}
func (b *shutdownReadBarrier) LoadBlockCommit(h int64) *types.Commit {
	b.gate("commit")
	return b.BlockStore.LoadBlockCommit(h)
}
func (b *shutdownReadBarrier) Close() error { b.closed.Store(true); return b.BlockStore.Close() }
func (b *shutdownReadBarrier) unblock()     { b.released.Do(func() { close(b.release) }) }

func shutdownTestReactor(t *testing.T, height int64, waitSync bool) (*Reactor, *State) {
	t.Helper()
	c := cfg.TestConfig().SetRoot(t.TempDir())
	cfg.EnsureRoot(c.RootDir)
	// Deliberately long existing intervals prove cancellation, not grace sleeps.
	c.Consensus.PeerGossipSleepDuration = time.Hour
	c.Consensus.PeerQueryMaj23SleepDuration = time.Hour
	state, pvs := randGenesisState(1, false, 10, types.DefaultConsensusParams())
	cs := newStateWithConfig(c, state, pvs[0], kvstore.NewInMemoryApplication())
	cs.Height = height
	cs.Votes = cstypes.NewHeightVoteSet(state.ChainID, height, state.Validators)
	r := NewReactor(cs, waitSync)
	r.SetLogger(log.NewNopLogger())
	r.SetEventBus(cs.eventBus)
	t.Cleanup(func() {
		if r.IsRunning() {
			_ = r.Stop()
		}
		_ = cs.eventBus.Stop()
	})
	return r, cs
}
func shutdownAwait(t *testing.T, ch <-chan struct{}, label string) {
	t.Helper()
	select {
	case <-ch:
	case <-time.After(5 * time.Second):
		t.Fatalf("timeout waiting for %s", label)
	}
}
func shutdownWaitStoppedFlag(t *testing.T, r *Reactor) {
	t.Helper()
	deadline := time.After(5 * time.Second)
	for r.IsRunning() {
		select {
		case <-deadline:
			t.Fatal("Stop did not begin")
		default:
			runtime.Gosched()
		}
	}
}

func TestReactorShutdownJoinsEveryStorageConsumer(t *testing.T) {
	for _, kind := range []string{"data", "votes", "query"} {
		t.Run(kind, func(t *testing.T) {
			height := int64(4)
			if kind == "query" {
				height = 1
			}
			r, cs := shutdownTestReactor(t, height, true)
			barrierKind := "commit"
			if kind == "data" {
				barrierKind = "data"
			}
			b := &shutdownReadBarrier{BlockStore: cs.blockStore, kind: barrierKind, entered: make(chan struct{}), release: make(chan struct{})}
			cs.blockStore = b
			t.Cleanup(b.unblock)
			if err := r.Start(); err != nil {
				t.Fatal(err)
			}
			peer := p2pmock.NewPeer(nil)
			t.Cleanup(func() { _ = peer.Stop() })
			r.InitPeer(peer)
			ps := peer.Get(types.PeerStateKey).(*PeerState)
			ps.PRS.Height = 1
			ps.PRS.Round = 0
			ps.PRS.Step = cstypes.RoundStepCommit
			ps.PRS.ProposalPOLRound = -1
			ps.PRS.CatchupCommitRound = -1
			if kind != "data" {
				ps.PRS.ProposalBlockParts = bits.NewBitArray(1)
				ps.PRS.ProposalBlockParts.SetIndex(0, true)
			}
			if kind == "query" {
				ps.PRS.CatchupCommitRound = 0
			}
			r.AddPeer(peer)
			shutdownAwait(t, b.entered, "real "+kind+" storage consumer")
			stopped := make(chan struct{})
			go func() { _ = r.Stop(); _ = b.Close(); close(stopped) }()
			shutdownWaitStoppedFlag(t, r)
			// The consumer is deterministically held, not sampled during a timing race.
			// A bounded noncompletion assertion also catches accidental deadlocks safely.
			select {
			case <-stopped:
				t.Error("Stop and store close overtook an admitted storage consumer")
			case <-time.After(100 * time.Millisecond):
			}
			b.unblock()
			shutdownAwait(t, stopped, "joined shutdown")
			if b.readAfterClose.Load() {
				t.Error("consumer accessed storage after close")
			}
		})
	}
}

type shutdownSendPeer struct {
	*p2pmock.Peer
	entered  chan struct{}
	release  chan struct{}
	once     sync.Once
	released sync.Once
	sends    atomic.Int64
}

func (p *shutdownSendPeer) Send(_ p2p.Envelope) bool {
	p.sends.Add(1)
	p.once.Do(func() { close(p.entered) })
	<-p.release
	return true
}
func (p *shutdownSendPeer) unblock() { p.released.Do(func() { close(p.release) }) }
func TestReactorShutdownJoinsInitialSend(t *testing.T) {
	r, _ := shutdownTestReactor(t, 1, false)
	if err := r.Start(); err != nil {
		t.Fatal(err)
	}
	p := &shutdownSendPeer{Peer: p2pmock.NewPeer(nil), entered: make(chan struct{}), release: make(chan struct{})}
	t.Cleanup(func() { p.unblock(); _ = p.Stop() })
	r.InitPeer(p)
	added := make(chan struct{})
	go func() { r.AddPeer(p); close(added) }()
	shutdownAwait(t, p.entered, "initial peer send")
	stopped := make(chan struct{})
	go func() { _ = r.Stop(); close(stopped) }()
	shutdownWaitStoppedFlag(t, r)
	select {
	case <-stopped:
		t.Error("Stop overtook initial AddPeer send")
	case <-time.After(100 * time.Millisecond):
	}
	p.unblock()
	shutdownAwait(t, added, "AddPeer return")
	shutdownAwait(t, stopped, "Stop return")
	if p.sends.Load() != 1 {
		t.Fatalf("shutdown chained additional sends: %d", p.sends.Load())
	}
	if err := r.Stop(); err == nil {
		t.Error("repeated Stop lost original service error")
	}
}

func TestReactorShutdownAdmissionAndPrivateCancellation(t *testing.T) {
	r, _ := shutdownTestReactor(t, 1, true)
	if err := r.Start(); err != nil {
		t.Fatal(err)
	}
	peers := make([]*p2pmock.Peer, 24)
	for i := range peers {
		peers[i] = p2pmock.NewPeer(nil)
		r.InitPeer(peers[i])
		p := peers[i]
		t.Cleanup(func() { _ = p.Stop() })
	}
	ready := make(chan struct{})
	var calls sync.WaitGroup
	for _, p := range peers {
		calls.Add(1)
		go func(p p2p.Peer) { defer calls.Done(); <-ready; r.AddPeer(p) }(p)
	}
	stopDone := make(chan struct{})
	go func() { <-ready; _ = r.Stop(); close(stopDone) }()
	close(ready)
	calls.Wait()
	shutdownAwait(t, stopDone, "concurrent admission shutdown")
	// Original public APIs only: the test also compiles against the pinned origin.
	for _, p := range peers {
		r.AddPeer(p)
	}
	if r.IsRunning() {
		t.Error("stopped reactor unexpectedly running")
	}
}

func TestReactorShutdownPreservesIndirectVoteSendUntilStopping(t *testing.T) {
	r, cs := shutdownTestReactor(t, 1, true)
	if err := r.Start(); err != nil {
		t.Fatal(err)
	}
	p := &shutdownSendPeer{Peer: p2pmock.NewPeer(nil), entered: make(chan struct{}), release: make(chan struct{})}
	p.unblock()
	t.Cleanup(func() { _ = p.Stop() })
	r.InitPeer(p)
	ps := p.Get(types.PeerStateKey).(*PeerState)
	ps.PRS.Height = 1
	ps.PRS.Round = 0
	vs := newValidatorStub(cs.privValidator, 0)
	vs.Height = 1
	vote, err := vs.signVote(cmtproto.PrevoteType, nil, types.PartSetHeader{}, nil, false)
	if err != nil {
		t.Fatal(err)
	}
	votes := types.NewVoteSet(cs.state.ChainID, 1, 0, cmtproto.PrevoteType, cs.state.Validators)
	added, err := votes.AddVote(vote)
	if err != nil || !added {
		t.Fatalf("genuine fixture vote: %v", err)
	}
	if !ps.PickSendVote(votes) || p.sends.Load() != 1 {
		t.Fatal("running indirect send was not preserved")
	}
	// Clear only test peer knowledge; the same real signed vote remains available.
	ps.mtx.Lock()
	ps.PRS.Prevotes = bits.NewBitArray(1)
	ps.mtx.Unlock()
	if err = r.Stop(); err != nil {
		t.Fatal(err)
	}
	if ps.PickSendVote(votes) || p.sends.Load() != 1 {
		t.Fatal("stopped reactor forwarded an indirect vote")
	}
}
