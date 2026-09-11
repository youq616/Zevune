package poolapp

import (
    "bytes"
    "encoding/hex"
    "testing"
    "github.com/youq616/Zevune/internal/poolbridge"
)
func TestGenesisBindingRejectsAmbiguityAndMismatch(t *testing.T) {
    digest := poolbridge.Hash{1}
    good := testGenesisState(digest)
    if !validGenesisState(good, digest) || !validGenesisState(append([]byte(" \n"), good...), digest) { t.Fatal("valid pin rejected") }
    other := poolbridge.Hash{2}
    for _, b := range [][]byte{nil, []byte("null"), []byte("{}"), append(bytes.Clone(good), good...), []byte(`{"test_genesis_sha256":"`+hex.EncodeToString(digest[:])+`","extra":1}`), []byte(`{"test_genesis_sha256":"`+hex.EncodeToString(digest[:])+`","test_genesis_sha256":"`+hex.EncodeToString(digest[:])+`"}`), testGenesisState(other)} {
        if validGenesisState(b, digest) { t.Fatal("ambiguous or wrong pin accepted") }
    }
    if !validGenesisState(nil, poolbridge.Hash{}) || validGenesisState(good, poolbridge.Hash{}) { t.Fatal("empty mode changed") }
}
