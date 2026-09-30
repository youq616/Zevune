package labnet

import (
	"context"
	"encoding/json"
	"strconv"

	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/types"
	"github.com/youq616/Zevune/internal/rpcgate"
)

// GatewayOptions starts no node, Tor daemon, wallet or private worker. Both
// sockets are local; the expected onion identity is only an HTTP route guard.
type GatewayOptions struct {
	NoRealFunds   bool
	Listen        string
	Upstream      string
	OnionEndpoint string
}

func (n *Network) gatewayConfig(o GatewayOptions) (rpcgate.Config, error) {
	if n == nil || n.configPin == (Hash{}) || n.assetPin == (Hash{}) || !o.NoRealFunds ||
		rpcgate.ValidateListen(o.Listen) != nil || ValidateEndpoint(o.Upstream) != nil || o.Upstream == "http://"+o.Listen {
		return rpcgate.Config{}, rpcgate.ErrConfiguration
	}
	host, port, err := parseOnionEndpoint(o.OnionEndpoint)
	if err != nil {
		return rpcgate.Config{}, rpcgate.ErrConfiguration
	}
	height := n.profile.MaxHeight()
	if height == 0 || height > uint64(1<<63-1) {
		return rpcgate.Config{}, rpcgate.ErrConfiguration
	}
	return rpcgate.Config{Listen: o.Listen, Host: host + ":" + strconv.Itoa(int(port)), MaxHeight: int64(height)}, nil
}

// RunGateway requires a Network produced by the independently pinned Load and
// a concrete, deadline-capable output owner established before listening.
// Root cancellation owns service shutdown; single HTTP requests do not.
func (n *Network) RunGateway(ctx context.Context, o GatewayOptions, output *rpcgate.Output) error {
	c, err := n.gatewayConfig(o)
	if err != nil || ctx == nil || ctx.Err() != nil || !output.Valid() {
		return rpcgate.ErrConfiguration
	}
	upstream, err := newPeer(o.Upstream)
	if err != nil {
		return rpcgate.ErrConfiguration
	}
	defer upstream.close() // only after the service and all in-flight calls exit
	s, err := rpcgate.Start(ctx, c, &gatewayBackend{source: upstream, chain: n.config.ChainID})
	if err != nil {
		return err
	}
	if err = rpcgate.WriteReady(ctx, output); err != nil {
		s.Stop()
		_ = s.Wait()
		return rpcgate.ErrReady
	}
	return s.Wait()
}

// This is the sole production Backend: it reconstructs typed requests using
// one independently fixed numeric peer. No original JSON, HTTP header or
// caller-selected upstream is forwarded. It never retries an unknown result.
type gatewayBackend struct {
	source rpcSource
	chain  string
}

func (b *gatewayBackend) Status(ctx context.Context) (string, int64, error) {
	r, err := b.source.Status(ctx)
	if err != nil || r == nil || r.NodeInfo.Network != b.chain {
		return "", 0, rpcgate.ErrUpstream
	}
	return r.NodeInfo.Network, r.SyncInfo.LatestBlockHeight, nil
}
func (b *gatewayBackend) Block(ctx context.Context, h int64) (json.RawMessage, error) {
	r, err := b.source.Block(ctx, &h)
	if err != nil || r == nil || r.Block == nil {
		return nil, rpcgate.ErrUpstream
	}
	return cmtjson.Marshal(r)
}
func (b *gatewayBackend) Commit(ctx context.Context, h int64) (json.RawMessage, error) {
	r, err := b.source.Commit(ctx, &h)
	if err != nil || r == nil || r.Header == nil || r.Commit == nil {
		return nil, rpcgate.ErrUpstream
	}
	return cmtjson.Marshal(r)
}
func (b *gatewayBackend) Broadcast(ctx context.Context, tx []byte) (uint32, []byte, error) {
	r, err := b.source.BroadcastTxSync(ctx, types.Tx(tx))
	if err != nil || r == nil {
		return 0, nil, rpcgate.ErrUpstream
	}
	return r.Code, r.Hash, nil
}
