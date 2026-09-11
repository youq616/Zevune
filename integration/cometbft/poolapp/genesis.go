package poolapp

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"github.com/youq616/Zevune/internal/poolbridge"
	"io"
)

type genesisBinding struct {
	Digest string `json:"test_genesis_sha256"`
}

func testGenesisState(digest poolbridge.Hash) []byte {
	if digest == (poolbridge.Hash{}) {
		return nil
	}
	raw, _ := json.Marshal(genesisBinding{Digest: hex.EncodeToString(digest[:])})
	return raw
}
func validGenesisState(raw []byte, digest poolbridge.Hash) bool {
	if digest == (poolbridge.Hash{}) {
		return len(raw) == 0
	}
	if len(raw) == 0 || len(raw) > 256 {
		return false
	}
	var binding genesisBinding
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(&binding) != nil || d.Decode(new(any)) != io.EOF {
		return false
	}
	expected := hex.EncodeToString(digest[:])
	// Duplicate fields are not needed by this small protocol. Validate an exact
	// whitespace-normalized object, not merely the last JSON value of a field.
	var compact bytes.Buffer
	if json.Compact(&compact, raw) != nil {
		return false
	}
	return binding.Digest == expected && bytes.Equal(compact.Bytes(), testGenesisState(digest))
}
