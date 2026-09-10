package orchardbridge

import (
	"encoding/binary"
	"errors"
	"io"
)

const (
	helloMagic    = "ZVOH0001"
	requestMagic  = "ZVOQ0001"
	responseMagic = "ZVOS0001"
	maxFrame      = MaxEnvelopeSize + 20
	responseSize  = 49
)

var ErrWorkerProtocol = errors.New("Orchard worker protocol mismatch")

func readFrame(r io.Reader, limit int) ([]byte, error) {
	if limit < 1 || limit > maxFrame {
		return nil, ErrBounds
	}
	var head [4]byte
	if _, err := io.ReadFull(r, head[:]); err != nil {
		return nil, err
	}
	n := binary.BigEndian.Uint32(head[:])
	if n == 0 || uint64(n) > uint64(limit) {
		return nil, ErrBounds
	}
	out := make([]byte, int(n))
	_, err := io.ReadFull(r, out)
	return out, err
}

func writeAll(w io.Writer, p []byte) error {
	for len(p) > 0 {
		n, err := w.Write(p)
		if n < 0 || n > len(p) {
			return io.ErrShortWrite
		}
		if err != nil {
			return err
		}
		if n == 0 {
			return io.ErrShortWrite
		}
		p = p[n:]
	}
	return nil
}

func writeFrame(w io.Writer, data []byte) error {
	if len(data) == 0 || len(data) > maxFrame {
		return ErrBounds
	}
	var head [4]byte
	binary.BigEndian.PutUint32(head[:], uint32(len(data)))
	if err := writeAll(w, head[:]); err != nil {
		return err
	}
	return writeAll(w, data)
}
