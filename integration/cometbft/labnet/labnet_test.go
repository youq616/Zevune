package labnet

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/cometbft/cometbft/crypto/ed25519"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	proto "github.com/cometbft/cometbft/proto/tendermint/types"
	cmtversion "github.com/cometbft/cometbft/proto/tendermint/version"
	"github.com/cometbft/cometbft/types"
	"github.com/cometbft/cometbft/version"
	"github.com/youq616/Zevune/integration/cometbft/poolapp"
)

// In-memory signing keys are random test-only material; they are never printed.
func signingNetwork(t *testing.T) (*Network, map[string]ed25519.PrivKey) {
	t.Helper()
	keys := map[string]ed25519.PrivKey{}
	vals := []*types.Validator{}
	g := &types.GenesisDoc{GenesisTime: time.Now().UTC().Add(-time.Minute), ChainID: poolapp.ChainID, InitialHeight: 1, ConsensusParams: types.DefaultConsensusParams(), AppHash: bytes.Repeat([]byte{7}, 32)}
	g.ConsensusParams.Version.App = poolapp.AppVersion
	g.ConsensusParams.Block.MaxBytes = 512 * 1024
	g.ConsensusParams.Evidence.MaxBytes = 64 * 1024
	for i := 0; i < 4; i++ {
		key := ed25519.GenPrivKey()
		pub := key.PubKey()
		keys[string(pub.Address())] = key
		vals = append(vals, types.NewValidator(pub, 10))
		g.Validators = append(g.Validators, types.GenesisValidator{Address: pub.Address(), PubKey: pub, Power: 10})
	}
	return &Network{genesis: g, validators: types.NewValidatorSet(vals)}, keys
}
func headerTemplate(n *Network, h int64) *types.Header {
	return &types.Header{Version: cmtversion.Consensus{Block: version.BlockProtocol, App: poolapp.AppVersion}, ChainID: poolapp.ChainID, Height: h, Time: time.Now().UTC().Add(-time.Second), ValidatorsHash: n.validators.Hash(), NextValidatorsHash: n.validators.Hash(), ConsensusHash: n.genesis.ConsensusParams.Hash(), AppHash: bytes.Clone(n.genesis.AppHash), ProposerAddress: n.validators.Validators[0].Address}
}
func signHeader(t *testing.T, n *Network, keys map[string]ed25519.PrivKey, h *types.Header, parts types.PartSetHeader, count int) *types.SignedHeader {
	t.Helper()
	id := types.BlockID{Hash: h.Hash(), PartSetHeader: parts}
	c := &types.Commit{Height: h.Height, Round: 0, BlockID: id, Signatures: make([]types.CommitSig, 4)}
	for i, v := range n.validators.Validators {
		if i >= count {
			c.Signatures[i] = types.NewCommitSigAbsent()
			continue
		}
		vote := &types.Vote{Type: proto.PrecommitType, Height: h.Height, Round: 0, BlockID: id, Timestamp: h.Time, ValidatorAddress: v.Address, ValidatorIndex: int32(i)}
		sig, err := keys[string(v.Address)].Sign(types.VoteSignBytes(h.ChainID, vote.ToProto()))
		if err != nil {
			t.Fatal(err)
		}
		vote.Signature = sig
		c.Signatures[i] = vote.CommitSig()
	}
	return &types.SignedHeader{Header: h, Commit: c}
}
func TestQuorumAndAllHeaderBindings(t *testing.T) {
	n, keys := signingNetwork(t)
	part := types.PartSetHeader{Total: 1, Hash: bytes.Repeat([]byte{3}, 32)}
	for count := 0; count <= 4; count++ {
		s := signHeader(t, n, keys, headerTemplate(n, 1), part, count)
		err := n.validateHeader(s, 1, time.Now())
		if (err == nil) != (count >= 3) {
			t.Fatalf("quorum %d accepted=%v", count, err == nil)
		}
	}
	changes := map[string]func(*types.Header){"chain": func(h *types.Header) { h.ChainID = "foreign-lab" }, "version": func(h *types.Header) { h.Version.App++ }, "validators": func(h *types.Header) { h.ValidatorsHash = bytes.Repeat([]byte{8}, 32) }, "next-validators": func(h *types.Header) { h.NextValidatorsHash = bytes.Repeat([]byte{8}, 32) }, "parameters": func(h *types.Header) { h.ConsensusHash = bytes.Repeat([]byte{8}, 32) }, "state-length": func(h *types.Header) { h.AppHash = []byte{1} }, "future": func(h *types.Header) { h.Time = time.Now().Add(time.Hour) }, "pre-genesis": func(h *types.Header) { h.Time = n.genesis.GenesisTime.Add(-time.Second) }, "height": func(h *types.Header) { h.Height = 2 }}
	for name, change := range changes {
		t.Run(name, func(t *testing.T) {
			h := headerTemplate(n, 1)
			change(h)
			if n.validateHeader(signHeader(t, n, keys, h, part, 4), 1, time.Now()) == nil {
				t.Fatal("accepted changed binding")
			}
		})
	}
	signed := signHeader(t, n, keys, headerTemplate(n, 1), part, 4)
	signed.Commit.Signatures[0].Signature[0] ^= 1
	if n.validateHeader(signed, 1, time.Now()) == nil {
		t.Fatal("invalid signature accepted")
	}
}
func TestPinnedPublicConfigurationAndCompanionFiles(t *testing.T) {
	n, _ := signingNetwork(t)
	home := t.TempDir()
	asset := bytes.Repeat([]byte{1}, 165) // structure-only fixture, never a spendable genesis
	assetPin := sha256.Sum256(asset)
	n.genesis.AppState, _ = json.Marshal(struct {
		Digest string `json:"test_genesis_sha256"`
	}{HashText(assetPin)})
	gen, err := cmtjson.MarshalIndent(n.genesis, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	for p, b := range map[string][]byte{assetName: asset, genesisName: gen} {
		if err = writeNew(filepath.Join(home, p), b); err != nil {
			t.Fatal(err)
		}
	}
	config := publicConfig{Version: 1, ChainID: poolapp.ChainID, AssetDigest: HashText(assetPin), ConsensusDigest: HashText(sha256.Sum256(gen)), NodeIDs: []string{strings.Repeat("0", 40), strings.Repeat("1", 40), strings.Repeat("2", 40), strings.Repeat("3", 40)}}
	raw, _ := json.Marshal(config)
	path := filepath.Join(home, configName)
	if err = writeNew(path, raw); err != nil {
		t.Fatal(err)
	}
	pin := sha256.Sum256(raw)
	if _, err = Load(path, pin); err != nil {
		t.Fatal(err)
	}
	if _, err = Load(path, Hash{1}); err == nil {
		t.Fatal("wrong pin accepted")
	}
	if writeNew(path, []byte("overwrite")) == nil {
		t.Fatal("overwritten")
	}
	altered := bytes.Clone(asset)
	altered[0] ^= 1
	os.WriteFile(filepath.Join(home, assetName), altered, 0600)
	if _, err = Load(path, pin); err == nil {
		t.Fatal("changed asset accepted")
	}
	os.WriteFile(filepath.Join(home, assetName), asset, 0600)
	config.NodeIDs[3] = config.NodeIDs[2]
	raw, _ = json.Marshal(config)
	os.WriteFile(path, raw, 0600)
	if _, err = Load(path, sha256.Sum256(raw)); err == nil {
		t.Fatal("duplicate node identity accepted")
	}
}
func TestCanonicalDecodingAndFileBounds(t *testing.T) {
	var out struct {
		Version int `json:"version"`
	}
	for _, raw := range []string{`{"version":1,"version":2}`, `{"version":1,"unknown":2}`, `{"version":1} {"version":2}`, `{"Version":1}`, `{"version":1e0}`, `null`} {
		if canonicalJSON([]byte(raw), &out) == nil {
			t.Fatalf("ambiguous config accepted: %s", raw)
		}
	}
	if canonicalJSON([]byte("{\n\"version\":1\n}\n"), &out) != nil {
		t.Fatal("canonical whitespace")
	}
	p := filepath.Join(t.TempDir(), "bounded")
	writeNew(p, []byte("abc"))
	if _, e := regularBytes(p, 1, 2); e == nil {
		t.Fatal("oversize")
	}
	if _, e := regularBytes(p, 4, 8); e == nil {
		t.Fatal("short")
	}
	if _, e := regularBytes(filepath.Dir(p), 0, 100); e == nil {
		t.Fatal("directory")
	}
	if _, e := ParseHash(strings.Repeat("A", 64)); e == nil {
		t.Fatal("uppercase hash")
	}
	if _, e := ParseHash(strings.Repeat("0", 64)); e == nil {
		t.Fatal("zero pin")
	}
}
func TestLoopbackEndpointAndStreamingLimits(t *testing.T) {
	for _, endpoint := range []string{"http://localhost:1234", "https://127.0.0.1:1234", "http://127.0.0.2:1234", "http://127.0.0.1:01234", "http://127.0.0.1:1234/", "http://127.0.0.1:1234#", "http://127.0.0.1:1234?", "http://x@127.0.0.1:1234", "http://127.0.0.1:80", "http://[::1]:1234"} {
		if ValidateEndpoint(endpoint) == nil {
			t.Fatalf("accepted %s", endpoint)
		}
	}
	if ValidateEndpoint("http://127.0.0.1:1234") != nil {
		t.Fatal("rejected canonical loopback")
	}
	for _, extra := range []int{0, 1} {
		r := &boundedBody{ReadCloser: io.NopCloser(bytes.NewReader(make([]byte, 32+extra))), remaining: 32}
		b, e := io.ReadAll(r)
		if len(b) != 32 || (e == nil) != (extra == 0) {
			t.Fatal("stream bound", len(b), e)
		}
	}
}
func TestRPCRejectsRedirectCompressionAndOversize(t *testing.T) {
	for _, mode := range []string{"redirect", "encoding", "length", "stream"} {
		t.Run(mode, func(t *testing.T) {
			s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				switch mode {
				case "redirect":
					w.Header().Set("Location", "http://127.0.0.1:1/")
					w.WriteHeader(302)
				case "encoding":
					w.Header().Set("Content-Encoding", "gzip")
					w.WriteHeader(200)
				case "length":
					w.Header().Set("Content-Length", fmt.Sprint(maxResponseBytes+1))
					w.WriteHeader(200)
				case "stream":
					w.WriteHeader(200)
					w.(http.Flusher).Flush()
					chunk := make([]byte, 8192)
					for i := int64(0); i <= maxResponseBytes; i += int64(len(chunk)) {
						if _, e := w.Write(chunk); e != nil {
							return
						}
					}
				}
			}))
			defer s.Close()
			p, e := newPeer(s.URL)
			if e != nil {
				t.Fatal(e)
			}
			defer p.close()
			ctx, cancel := context.WithTimeout(context.Background(), time.Second*5)
			defer cancel()
			if _, e = p.Status(ctx); e == nil {
				t.Fatal("malformed response accepted")
			}
		})
	}
}
func FuzzCanonicalPublicConfiguration(f *testing.F) {
	f.Add([]byte(`{"version":1}`))
	f.Add([]byte("{}"))
	f.Fuzz(func(t *testing.T, b []byte) {
		if len(b) > 16384 {
			return
		}
		var c publicConfig
		if canonicalJSON(b, &c) == nil {
			want, _ := json.Marshal(c)
			var compact bytes.Buffer
			json.Compact(&compact, b)
			if !bytes.Equal(want, compact.Bytes()) {
				t.Fatal("noncanonical success")
			}
		}
	})
}
func FuzzNumericLoopbackEndpoint(f *testing.F) {
	f.Add("http://127.0.0.1:1234")
	f.Add("http://127.0.0.1:1234#")
	f.Fuzz(func(t *testing.T, s string) {
		if len(s) > 4096 {
			return
		}
		if ValidateEndpoint(s) == nil && !strings.HasPrefix(s, "http://127.0.0.1:") {
			t.Fatal("escaped local policy")
		}
	})
}
