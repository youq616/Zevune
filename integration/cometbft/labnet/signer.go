package labnet

import (
	"bytes"
	"crypto/ed25519"
	"crypto/subtle"
	"encoding/json"
	"io"

	cmted25519 "github.com/cometbft/cometbft/crypto/ed25519"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/privval"
)

// loadExistingFilePV must run only after this node's Rust journal lock has been
// acquired. Read both files afresh here: a lock-before-read ordering is required
// so a previous owner cannot sign after the successor's state snapshot.
// Unlike upstream LoadFilePV, malformed data returns without printing or exiting.
// Loading never creates, resets or saves signer state.
func loadExistingFilePV(keyPath, statePath string) (*privval.FilePV, error) {
	keyRaw, err := regularBytes(keyPath, 2, 32*1024)
	if err != nil {
		return nil, err
	}
	stateRaw, err := regularBytes(statePath, 2, 32*1024)
	if err != nil {
		return nil, err
	}
	keyFields, err := signerJSONObject(keyRaw, []string{"address", "pub_key", "priv_key"}, nil)
	if err != nil {
		return nil, err
	}
	for _, field := range []string{"pub_key", "priv_key"} {
		if _, err := signerJSONObject(keyFields[field], []string{"type", "value"}, nil); err != nil {
			return nil, err
		}
	}
	if _, err := signerJSONObject(stateRaw, []string{"height", "round", "step"}, []string{"signature", "signbytes"}); err != nil {
		return nil, err
	}
	var key privval.FilePVKey
	var state privval.FilePVLastSignState
	if cmtjson.Unmarshal(keyRaw, &key) != nil || cmtjson.Unmarshal(stateRaw, &state) != nil {
		return nil, ErrStorage
	}
	secret, privateOK := key.PrivKey.(cmted25519.PrivKey)
	public, publicOK := key.PubKey.(cmted25519.PubKey)
	if !privateOK || !publicOK || len(secret) != ed25519.PrivateKeySize || len(public) != ed25519.PublicKeySize {
		return nil, ErrConfiguration
	}
	// Comet's PrivKey.PubKey copies the cached public half of the private key.
	// Validate that half against the seed using the standard Ed25519 constructor
	// before allowing NewFilePV or any signing operation to consume the key.
	expanded := ed25519.NewKeyFromSeed(secret[:ed25519.SeedSize])
	if subtle.ConstantTimeCompare(secret, expanded) != 1 || !bytes.Equal(public, expanded[ed25519.SeedSize:]) || !bytes.Equal(key.Address, public.Address()) {
		return nil, ErrConfiguration
	}
	initial := state.Height == 0 && state.Round == 0 && state.Step == 0 && len(state.Signature) == 0 && len(state.SignBytes) == 0
	if !initial && (state.Height < 1 || state.Round < 0 || state.Step < 1 || state.Step > 3 || len(state.Signature) != ed25519.SignatureSize || len(state.SignBytes) == 0) {
		return nil, ErrStorage
	}
	if !initial && !public.VerifySignature(state.SignBytes, state.Signature) {
		return nil, ErrStorage
	}
	pv := privval.NewFilePV(secret, keyPath, statePath)
	// NewFilePV sets private filePath fields. A whole-struct assignment would
	// erase the state's persistence path and break the next saveSigned call.
	pv.LastSignState.Height = state.Height
	pv.LastSignState.Round = state.Round
	pv.LastSignState.Step = state.Step
	pv.LastSignState.Signature = bytes.Clone(state.Signature)
	pv.LastSignState.SignBytes = bytes.Clone(state.SignBytes)
	return pv, nil
}

// Require explicit, unambiguous fields while accepting upstream JSON whitespace
// and field ordering. In particular, {} and null H/R/S must not decode as a new
// unsigned state. Raw decoder errors can include contents, so return only the
// fixed local-storage error.
func signerJSONObject(raw []byte, required, optional []string) (map[string]json.RawMessage, error) {
	allowed := make(map[string]bool, len(required)+len(optional))
	for _, name := range required {
		allowed[name] = true
	}
	for _, name := range optional {
		allowed[name] = true
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	token, err := decoder.Token()
	if err != nil || token != json.Delim('{') {
		return nil, ErrStorage
	}
	fields := make(map[string]json.RawMessage, len(allowed))
	for decoder.More() {
		token, err := decoder.Token()
		name, ok := token.(string)
		if err != nil || !ok || !allowed[name] || fields[name] != nil {
			return nil, ErrStorage
		}
		var value json.RawMessage
		if decoder.Decode(&value) != nil || bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
			return nil, ErrStorage
		}
		fields[name] = value
	}
	if token, err = decoder.Token(); err != nil || token != json.Delim('}') {
		return nil, ErrStorage
	}
	if _, err = decoder.Token(); err != io.EOF {
		return nil, ErrStorage
	}
	for _, name := range required {
		if fields[name] == nil {
			return nil, ErrStorage
		}
	}
	return fields, nil
}
