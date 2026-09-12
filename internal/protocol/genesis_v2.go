package protocol

import (
	"crypto/sha256"
	"encoding/json"
	"errors"
)

var ErrInvalidGenesisV2 = errors.New("invalid genesis v2")

type GenesisV2 struct {
	ChainID string `json:"chain_id"`
	ProtocolVersion uint32 `json:"protocol_version"`
	StateRoot [32]byte `json:"state_root"`
	ValidatorRoot [32]byte `json:"validator_root"`
	ActivationHeight uint64 `json:"activation_height"`
}

func (g GenesisV2) Valid() error {
	if g.ChainID == "" || g.ProtocolVersion == 0 {
		return ErrInvalidGenesisV2
	}
	return nil
}

func (g GenesisV2) Digest() ([32]byte,error) {
	if err:=g.Valid(); err!=nil { return [32]byte{},err }
	b,err:=json.Marshal(g)
	if err!=nil{return [32]byte{},err}
	return sha256.Sum256(b),nil
}
