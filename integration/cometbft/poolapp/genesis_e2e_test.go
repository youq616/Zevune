//go:build pool_e2e

package poolapp

import (
	"bytes"
	"context"
	"path/filepath"
	"testing"

	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/cometbft/cometbft/types"
)

func TestRealLegacyInitChainRejectsActiveApplicationVersion(t *testing.T) {
	ctx := context.Background()
	a := open(t, filepath.Join(t.TempDir(), "pool.journal"), true)
	before := info(t, a)
	if before.AppVersion != AppVersion {
		t.Fatal("legacy application version changed")
	}
	params := types.DefaultConsensusParams().ToProto()
	request := &abci.RequestInitChain{
		ChainId: ChainID, InitialHeight: 1, ConsensusParams: &params,
		AppStateBytes: testGenesisState(a.genesis),
	}
	for i := 0; i < 4; i++ {
		request.Validators = append(request.Validators, abci.Ed25519ValidatorUpdate(bytes.Repeat([]byte{byte(i + 1)}, 32), 10))
	}
	for _, version := range []uint64{0, ActiveAppVersion} {
		request.ConsensusParams.Version.App = version
		if _, err := a.InitChain(ctx, request); err == nil {
			t.Fatal("legacy InitChain accepted absent or active application version")
		}
	}
	saved := request.ConsensusParams.Version
	request.ConsensusParams.Version = nil
	if _, err := a.InitChain(ctx, request); err == nil {
		t.Fatal("legacy InitChain accepted no version parameters")
	}
	request.ConsensusParams.Version = saved
	request.ConsensusParams.Version.App = AppVersion
	result, err := a.InitChain(ctx, request)
	if err != nil || !bytes.Equal(result.AppHash, before.LastBlockAppHash) {
		t.Fatal("version rejection changed state or rejected the valid legacy genesis", err)
	}
}
