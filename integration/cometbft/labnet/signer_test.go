package labnet

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	cmted25519 "github.com/cometbft/cometbft/crypto/ed25519"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/privval"
	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
)

func signerFixture(t *testing.T) (string, string, *privval.FilePV) {
	t.Helper()
	dir := t.TempDir()
	keyPath, statePath := filepath.Join(dir, "key.json"), filepath.Join(dir, "state.json")
	pv := privval.GenFilePV(keyPath, statePath)
	pv.Save() // Create a fresh test fixture, never a production recovery action.
	return keyPath, statePath, pv
}

func signerFileBytes(t *testing.T, paths ...string) map[string][]byte {
	t.Helper()
	files := make(map[string][]byte, len(paths))
	for _, path := range paths {
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal("cannot read signer fixture")
		}
		files[path] = raw
	}
	return files
}

func requireSignerFilesUnchanged(t *testing.T, before map[string][]byte) {
	t.Helper()
	for path, expected := range before {
		raw, err := os.ReadFile(path)
		if err != nil || !bytes.Equal(raw, expected) {
			t.Fatal("signer load or rejected signing attempt changed a file")
		}
	}
}

func signerVote(height int64, round int32, kind cmtproto.SignedMsgType) *cmtproto.Vote {
	return &cmtproto.Vote{
		Type:      kind,
		Height:    height,
		Round:     round,
		BlockID:   cmtproto.BlockID{Hash: bytes.Repeat([]byte{1}, 32), PartSetHeader: cmtproto.PartSetHeader{Total: 1, Hash: bytes.Repeat([]byte{2}, 32)}},
		Timestamp: time.Unix(1_700_000_000, 0).UTC(),
	}
}

func TestSafeSignerLoadPreservesHistoryAndPersistencePaths(t *testing.T) {
	for _, kind := range []cmtproto.SignedMsgType{cmtproto.PrevoteType, cmtproto.PrecommitType} {
		t.Run(kind.String(), func(t *testing.T) {
			keyPath, statePath, original := signerFixture(t)
			first := signerVote(5, 2, kind)
			if err := original.SignVote("signer-history-test", first); err != nil {
				t.Fatal("cannot sign fixture vote")
			}
			before := signerFileBytes(t, keyPath, statePath)
			loaded, err := loadExistingFilePV(keyPath, statePath)
			if err != nil {
				t.Fatal("valid signed state was rejected", err)
			}
			requireSignerFilesUnchanged(t, before)
			if loaded.LastSignState.Height != original.LastSignState.Height || loaded.LastSignState.Round != original.LastSignState.Round || loaded.LastSignState.Step != original.LastSignState.Step ||
				!bytes.Equal(loaded.LastSignState.Signature, original.LastSignState.Signature) || !bytes.Equal(loaded.LastSignState.SignBytes, original.LastSignState.SignBytes) {
				t.Fatal("load did not preserve all five signed-state fields")
			}
			for _, timestamp := range []time.Time{first.Timestamp, first.Timestamp.Add(time.Second)} {
				again := signerVote(5, 2, kind)
				again.Timestamp = timestamp
				if loaded.SignVote("signer-history-test", again) != nil || !bytes.Equal(again.Signature, first.Signature) || !again.Timestamp.Equal(first.Timestamp) {
					t.Fatal("same HRS did not reuse the saved timestamp and signature")
				}
				requireSignerFilesUnchanged(t, before)
			}
			conflict := signerVote(5, 2, kind)
			conflict.BlockID.Hash[0] ^= 1
			for _, vote := range []*cmtproto.Vote{conflict, signerVote(4, 2, kind), signerVote(5, 1, kind)} {
				if loaded.SignVote("signer-history-test", vote) == nil {
					t.Fatal("restored history accepted a conflict or H/R regression")
				}
				requireSignerFilesUnchanged(t, before)
			}
			if kind == cmtproto.PrecommitType {
				if loaded.SignVote("signer-history-test", signerVote(5, 2, cmtproto.PrevoteType)) == nil {
					t.Fatal("restored history accepted a step regression")
				}
				requireSignerFilesUnchanged(t, before)
			}
			next := signerVote(6, 0, kind)
			if loaded.SignVote("signer-history-test", next) != nil {
				t.Fatal("restored signer cannot advance using its original persistence path")
			}
			reopened, err := loadExistingFilePV(keyPath, statePath)
			if err != nil || reopened.LastSignState.Height != 6 || !bytes.Equal(reopened.LastSignState.Signature, next.Signature) {
				t.Fatal("advanced signer state was not persisted to its original path")
			}
			if reopened.SignVote("signer-history-test", first) == nil {
				t.Fatal("second load lost the advanced anti-double-sign state")
			}
			requireSignerFilesUnchanged(t, map[string][]byte{keyPath: before[keyPath]})
		})
	}
}

func TestSafeSignerLoadAcceptsInitialAndProposalState(t *testing.T) {
	keyPath, statePath, pv := signerFixture(t)
	before := signerFileBytes(t, keyPath, statePath)
	initial, err := loadExistingFilePV(keyPath, statePath)
	if err != nil || initial.LastSignState.Height != 0 || initial.LastSignState.Step != 0 {
		t.Fatal("fresh upstream signer fixture was rejected")
	}
	requireSignerFilesUnchanged(t, before)
	proposal := &cmtproto.Proposal{Type: cmtproto.ProposalType, Height: 2, Round: 0, PolRound: -1,
		BlockID: signerVote(2, 0, cmtproto.PrevoteType).BlockID, Timestamp: time.Unix(1_700_000_000, 0).UTC()}
	if pv.SignProposal("signer-history-test", proposal) != nil {
		t.Fatal("cannot sign fixture proposal")
	}
	before = signerFileBytes(t, keyPath, statePath)
	loaded, err := loadExistingFilePV(keyPath, statePath)
	if err != nil || loaded.LastSignState.Step != 1 || !bytes.Equal(loaded.LastSignState.Signature, proposal.Signature) {
		t.Fatal("valid proposal state was rejected or changed")
	}
	requireSignerFilesUnchanged(t, before)
}

func TestSafeSignerLoadRejectsDamagedStateWithoutRewriting(t *testing.T) {
	for _, mutate := range []func(*privval.FilePVLastSignState){
		func(s *privval.FilePVLastSignState) { s.Height = -1 },
		func(s *privval.FilePVLastSignState) { s.Round = -1 },
		func(s *privval.FilePVLastSignState) { s.Step = 0 },
		func(s *privval.FilePVLastSignState) { s.Step = 4 },
		func(s *privval.FilePVLastSignState) { s.Signature = nil },
		func(s *privval.FilePVLastSignState) { s.SignBytes = nil },
		func(s *privval.FilePVLastSignState) { s.Signature[0] ^= 1 },
		func(s *privval.FilePVLastSignState) { s.SignBytes[0] ^= 1 },
	} {
		keyPath, statePath, pv := signerFixture(t)
		if pv.SignVote("signer-history-test", signerVote(5, 2, cmtproto.PrevoteType)) != nil {
			t.Fatal("cannot sign fixture")
		}
		mutate(&pv.LastSignState)
		raw, err := cmtjson.Marshal(pv.LastSignState)
		if err != nil || os.WriteFile(statePath, raw, 0600) != nil {
			t.Fatal("cannot write damaged state fixture")
		}
		before := signerFileBytes(t, keyPath, statePath)
		if _, err := loadExistingFilePV(keyPath, statePath); !errors.Is(err, ErrStorage) {
			t.Fatal("damaged signed state was not rejected with a fixed error")
		}
		requireSignerFilesUnchanged(t, before)
	}
}

func TestSafeSignerLoadRejectsInconsistentKeyWithoutRepairing(t *testing.T) {
	for _, mutate := range []func(*privval.FilePVKey){
		func(k *privval.FilePVKey) { k.Address[0] ^= 1 },
		func(k *privval.FilePVKey) { k.PubKey = cmted25519.GenPrivKey().PubKey() },
		func(k *privval.FilePVKey) { k.PrivKey.(cmted25519.PrivKey)[0] ^= 1 },
		func(k *privval.FilePVKey) { k.PrivKey = cmted25519.PrivKey{1} },
	} {
		keyPath, statePath, pv := signerFixture(t)
		mutate(&pv.Key)
		raw, err := cmtjson.Marshal(pv.Key)
		if err != nil || os.WriteFile(keyPath, raw, 0600) != nil {
			t.Fatal("cannot write inconsistent key fixture")
		}
		before := signerFileBytes(t, keyPath, statePath)
		if _, err := loadExistingFilePV(keyPath, statePath); !errors.Is(err, ErrConfiguration) {
			t.Fatal("inconsistent private/public/address key fields were not rejected")
		}
		requireSignerFilesUnchanged(t, before)
	}
}

func TestSafeSignerJSONRejectsMissingNullDuplicateAndUnknownStateFields(t *testing.T) {
	for _, raw := range []string{
		"{{", `{}`, `{"height":"0","round":0}`, `{"height":null,"round":0,"step":0}`,
		`{"height":"0","round":0,"step":0,"height":"1"}`,
		`{"height":"0","round":0,"step":0,"reset":true}`,
		`{"height":"0","round":0,"step":0} {}`,
	} {
		keyPath, statePath, _ := signerFixture(t)
		if os.WriteFile(statePath, []byte(raw), 0600) != nil {
			t.Fatal("cannot write invalid state fixture")
		}
		before := signerFileBytes(t, keyPath, statePath)
		if _, err := loadExistingFilePV(keyPath, statePath); !errors.Is(err, ErrStorage) {
			t.Fatal("ambiguous or missing signer state was accepted")
		}
		requireSignerFilesUnchanged(t, before)
	}
	keyPath, statePath, _ := signerFixture(t)
	if os.WriteFile(statePath, []byte("{\n \"step\":0, \"round\":0, \"height\":\"0\"\n}"), 0600) != nil {
		t.Fatal("cannot write reordered state fixture")
	}
	before := signerFileBytes(t, keyPath, statePath)
	if _, err := loadExistingFilePV(keyPath, statePath); err != nil {
		t.Fatal("valid field ordering/whitespace was not preserved")
	}
	requireSignerFilesUnchanged(t, before)
}
