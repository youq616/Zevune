package protocol

import "testing"

func TestTransactionV1RejectsWrongDomain(t *testing.T) {
	ctx := Context{ChainID: "zevune-test", ProtocolVersion: Version, ActivationHeight: 1}
	tx := TransactionV1{Context: ctx, Payload: []byte("payload"), ExpiryHeight: 10}
	if err := tx.Valid(2); err != nil {
		t.Fatal(err)
	}
	other := tx
	other.Context.ChainID = "other-chain"
	if tx.SigningDigest() == other.SigningDigest() {
		t.Fatal("different domains produced same signing digest")
	}
}

func TestTransactionV1Expiry(t *testing.T) {
	tx := TransactionV1{Context: Context{ChainID: "test", ProtocolVersion: Version}, Payload: []byte("x"), ExpiryHeight: 3}
	if err := tx.Valid(4); err == nil {
		t.Fatal("expired transaction accepted")
	}
}
