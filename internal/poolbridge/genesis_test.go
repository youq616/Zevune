package poolbridge

import (
    "crypto/sha256"
    "os"
    "path/filepath"
    "testing"
)

func TestTestGenesisArgumentsAreExplicitAndPinned(t *testing.T) {
    o := Options{Journal: filepath.Join(t.TempDir(), "state.journal")}
    args, err := o.workerArgs("open")
    if err != nil || len(args) != 2 { t.Fatal("legacy arguments changed", err) }
    p := filepath.Join(t.TempDir(), "genesis.bin")
    b := make([]byte, 165) // Structural dummy only; no Rust verifier accepts this.
    if err := os.WriteFile(p, b, 0600); err != nil { t.Fatal(err) }
    o.TestGenesis = p
    if _, err := o.workerArgs("open"); err == nil { t.Fatal("missing pin accepted") }
    o.TestGenesisSHA256 = sha256.Sum256(b)
    args, err = o.workerArgs("open")
    if err != nil || len(args) != 4 || args[2] != p { t.Fatal(err) }
    b[0] = 1
    if err := os.WriteFile(p, b, 0600); err != nil { t.Fatal(err) }
    if _, err := o.workerArgs("open"); err == nil { t.Fatal("modified manifest accepted") }
    o.TestGenesis = "relative.bin"
    if _, err := o.workerArgs("open"); err == nil { t.Fatal("relative path accepted") }
    o.TestGenesis = ""
    if _, err := o.workerArgs("open"); err == nil { t.Fatal("orphan pin accepted") }
}
