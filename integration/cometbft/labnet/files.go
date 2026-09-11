// Package labnet is an explicitly local, fixed-validator, NO-FUNDS network
// operator. It does not provide network anonymity or a production trust model.
package labnet

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
)

type Hash = [32]byte

var (
	ErrBounds        = errors.New("local network input bounds")
	ErrConfiguration = errors.New("local network configuration not authenticated")
	ErrStorage       = errors.New("local network file operation failed; existing data was not reset")
	ErrCertificate   = errors.New("signed network state could not be authenticated")
	ErrEndpoint      = errors.New("only an explicit numeric loopback HTTP endpoint is supported")
	ErrResponse      = errors.New("local RPC response exceeded bounds or failed")
	ErrBehind        = errors.New("remote tip is stale or behind the saved reference state")
	ErrSyncRequired  = errors.New("reference journal must be fully synchronized before submission")
	ErrSubmission    = errors.New("submission outcome is uncertain; do not release wallet reservations")
)

const Version = "0.1.0-local-network-operator"
const configName = "network.json"
const genesisName = "consensus-genesis.json"
const assetName = "test-genesis.bin"

func ParseHash(text string) (Hash, error) {
	var out Hash
	if len(text) != 64 {
		return out, ErrBounds
	}
	b, err := hex.DecodeString(text)
	if err != nil || hex.EncodeToString(b) != text {
		return out, ErrBounds
	}
	copy(out[:], b)
	if out == (Hash{}) {
		return Hash{}, ErrBounds
	}
	return out, nil
}
func HashText(h Hash) string { return hex.EncodeToString(h[:]) }

func regularBytes(path string, minimum, maximum int64) ([]byte, error) {
	if !filepath.IsAbs(path) || maximum < minimum || minimum < 0 {
		return nil, ErrBounds
	}
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Size() < minimum || info.Size() > maximum {
		return nil, ErrStorage
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, ErrStorage
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !opened.Mode().IsRegular() || !os.SameFile(info, opened) {
		return nil, ErrStorage
	}
	raw, err := io.ReadAll(io.LimitReader(file, maximum+1))
	if err != nil || int64(len(raw)) != info.Size() || int64(len(raw)) > maximum {
		return nil, ErrStorage
	}
	return raw, nil
}
func pinnedBytes(path string, pin Hash, minimum, maximum int64) ([]byte, error) {
	if pin == (Hash{}) {
		return nil, ErrBounds
	}
	b, err := regularBytes(path, minimum, maximum)
	if err != nil {
		return nil, err
	}
	if sha256.Sum256(b) != pin {
		return nil, ErrConfiguration
	}
	return b, nil
}
func writeNew(path string, raw []byte) error {
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return ErrStorage
	}
	_, err = io.Copy(file, bytes.NewReader(raw))
	if err == nil {
		err = file.Sync()
	}
	if closeErr := file.Close(); err == nil {
		err = closeErr
	}
	if err != nil {
		return ErrStorage
	}
	return nil
}
func canonicalJSON(raw []byte, out any) error {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if decoder.Decode(out) != nil || decoder.Decode(new(any)) != io.EOF {
		return ErrConfiguration
	}
	var compact bytes.Buffer
	expected, err := json.Marshal(out)
	if err != nil || json.Compact(&compact, raw) != nil || !bytes.Equal(compact.Bytes(), expected) {
		return ErrConfiguration
	}
	return nil
}
