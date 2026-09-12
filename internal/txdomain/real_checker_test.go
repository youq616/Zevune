//go:build domain_e2e

package txdomain

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

func TestRealRustDomainAuthorizationAndGoRoundtrip(t *testing.T) {
	executable, corpus := os.Getenv("ZEVUNE_DOMAIN_CHECKER"), os.Getenv("ZEVUNE_DOMAIN_FIXTURES")
	if !filepath.IsAbs(executable) || !filepath.IsAbs(corpus) {
		t.Fatal("real checker and public corpus are required; no skip or test verifier fallback")
	}
	load := func(name string) []byte {
		t.Helper()
		b, e := os.ReadFile(filepath.Join(corpus, name))
		if e != nil {
			t.Fatal(e)
		}
		return b
	}
	descriptor := load("domain.bin")
	domain, err := DecodeDomain(descriptor)
	if err != nil {
		t.Fatal(err)
	}
	foreign := load("foreign-domain.bin")
	other, err := DecodeDomain(foreign)
	if err != nil {
		t.Fatal(err)
	}
	raw := load("transaction.bin")
	body, err := Decode(raw, domain)
	if err != nil {
		t.Fatal(err)
	}
	encoded, err := Encode(body, domain)
	if err != nil || !bytes.Equal(encoded, raw) {
		t.Fatal("Go changed Rust transaction")
	}
	if _, err := Decode(raw, other); err == nil {
		t.Fatal("Go accepted wrong domain")
	}
	type receipt struct {
		Verified  *bool  `json:"authorization_verified"`
		Ledger    *bool  `json:"ledger_checked"`
		Confirmed *bool  `json:"confirmed"`
		RealFunds *bool  `json:"real_funds_allowed"`
		Domain    string `json:"domain_id"`
		Payload   string `json:"payload_digest"`
	}
	invoke := func(descriptor, raw []byte, success bool) {
		t.Helper()
		ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
		defer cancel()
		cmd := exec.CommandContext(ctx, executable, "--no-real-funds", "--domain-hex", hex.EncodeToString(descriptor))
		cmd.Stdin = bytes.NewReader(raw)
		var stderr bytes.Buffer
		cmd.Stderr = &stderr
		out, err := cmd.Output()
		if !success {
			if err == nil || len(out) != 0 {
				t.Fatal("invalid authorization reported as successful")
			}
			return
		}
		if err != nil || stderr.Len() != 0 {
			t.Fatal("real Rust authorization did not succeed", err)
		}
		var got receipt
		decoder := json.NewDecoder(bytes.NewReader(out))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&got); err != nil {
			t.Fatal(err)
		}
		id, _ := domain.ID()
		payload := PayloadDigest(raw)
		if got.Verified == nil || !*got.Verified || got.Ledger == nil || *got.Ledger || got.Confirmed == nil || *got.Confirmed || got.RealFunds == nil || *got.RealFunds || got.Domain != hex.EncodeToString(id[:]) || got.Payload != hex.EncodeToString(payload[:]) {
			t.Fatal("unexpected authorizer receipt")
		}
	}
	invoke(descriptor, encoded, true)
	invoke(foreign, raw, false)
	invoke(foreign, load("transplanted.bin"), false)
	invoke(descriptor, load("wrapped-legacy.bin"), false)
	invoke(descriptor, raw[PrefixSize:], false)
	changed := bytes.Clone(raw)
	changed[len(changed)-1] ^= 1
	invoke(descriptor, changed, false)
}
