package poolbridge

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"os"
	"path/filepath"
)

// These flags only work with the separately built local-funding-lab Rust
// feature. A normal worker rejects them; no implicit fallback or new issuance.
func (o Options) workerArgs(mode string) ([]string, error) {
	args := []string{mode, o.Journal}
	if o.TestGenesis == "" && o.TestGenesisSHA256 == (Hash{}) {
		return args, nil
	}
	if !filepath.IsAbs(o.TestGenesis) || o.TestGenesisSHA256 == (Hash{}) {
		return nil, ErrBounds
	}
	info, err := os.Lstat(o.TestGenesis)
	if err != nil || !info.Mode().IsRegular() || info.Size() < 165 || info.Size() > 1890 {
		return nil, ErrBounds
	}
	f, err := os.Open(o.TestGenesis)
	if err != nil {
		return nil, ErrBounds
	}
	b, err := io.ReadAll(io.LimitReader(f, 1891))
	closeErr := f.Close()
	digest := sha256.Sum256(b)
	if err != nil || closeErr != nil || int64(len(b)) != info.Size() || !bytes.Equal(digest[:], o.TestGenesisSHA256[:]) {
		return nil, ErrBounds
	}
	return append(args, o.TestGenesis, hex.EncodeToString(o.TestGenesisSHA256[:])), nil
}
