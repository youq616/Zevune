package ledger

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/youq616/Zevune/internal/protocol"
)

// This bounded append-only journal is for local NO-FUNDS testing. Checksums are
// not authentication, encryption, consensus, or protection against local rollback.
const (
	journalMagic           = "ZEVUNE-LOCAL-JOURNAL\x00\x01"
	MaxJournalBytes  int64 = 64 * 1024 * 1024
	maxJournalBlocks       = 10000
	maxFrameBytes          = MaxBlockBytes + 4*MaxBlockTransactions + 12
)

var (
	ErrJournalCorrupt     = errors.New("invalid or incomplete journal; original file left unchanged")
	ErrJournalLocked      = errors.New("journal already in use, or OS lock unavailable")
	ErrStorageUnavailable = errors.New("storage unavailable; stop and inspect before reopening")
	ErrClosed             = errors.New("ledger is closed")
)

type journal struct {
	f         *os.File
	size      int64
	tail      [32]byte
	blocks    int
	recovered bool
	// Injectable I/O boundary ONLY for fault tests; normal open binds File methods.
	write func([]byte) (int, error)
	sync  func() error
}

type StorageStatus struct {
	Mode      string `json:"mode"`
	Recovered bool   `json:"recovered"`
	Available bool   `json:"available"`
}

func (e *Engine) usableLocked() error {
	if e.closed {
		return ErrClosed
	}
	if e.storageErr != nil {
		return ErrStorageUnavailable
	}
	return nil
}

func (e *Engine) StorageStatus() StorageStatus {
	e.mu.RLock()
	defer e.mu.RUnlock()
	mode := "memory"
	recovered := false
	if e.journal != nil {
		mode = "journal"
		recovered = e.journal.recovered
	}
	return StorageStatus{mode, recovered, e.usableLocked() == nil}
}

// Close is idempotent. The OS releases the exclusive journal lock on file close.
func (e *Engine) Close() error {
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.closed {
		return nil
	}
	e.closed = true
	if e.journal != nil {
		return e.journal.f.Close()
	}
	return nil
}

// OpenPersistent creates or replays ledger.journal in a trusted, local directory.
// Existing empty, corrupt, wrong-chain or incomplete journals are NOT reset.
// All recovered blocks are validated again using v; test proofs cannot be loaded
// by the executable's UnavailableVerifier. Genesis must exactly match the caller.
// No accepting verifier, recovery bypass, import endpoint or auto-miner is added.
func OpenPersistent(chain, dir string, genesis []protocol.Hash, v Verifier) (*Engine, error) {
	e, err := New(chain, genesis, v)
	if err != nil {
		return nil, err
	}
	if dir == "" {
		return nil, errors.New("empty data directory")
	}
	if err = os.MkdirAll(dir, 0700); err != nil {
		return nil, err
	}
	path := filepath.Join(dir, "ledger.journal")
	// Do not follow a final-component symlink. Parent directory must be trusted;
	// this check is NOT a defense against a hostile local user racing path changes.
	if info, er := os.Lstat(path); er == nil && !info.Mode().IsRegular() {
		return nil, errors.New("journal must be a regular file")
	} else if er != nil && !errors.Is(er, os.ErrNotExist) {
		return nil, er
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_RDWR, 0600)
	fresh := err == nil
	if errors.Is(err, os.ErrExist) {
		f, err = os.OpenFile(path, os.O_RDWR, 0600)
	}
	if err != nil {
		return nil, err
	}
	ok := false
	defer func() {
		if !ok {
			_ = f.Close()
		}
	}()
	if err = lockJournal(f); err != nil {
		return nil, fmt.Errorf("%w: %v", ErrJournalLocked, err)
	}
	info, err := f.Stat()
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() > MaxJournalBytes {
		return nil, ErrJournalCorrupt
	}
	j := &journal{f: f, size: info.Size(), recovered: !fresh, write: f.Write, sync: f.Sync}
	genesisData := encodeGenesis(chain, genesis)
	if fresh {
		if err = j.appendFrame(genesisData); err != nil {
			return nil, err
		}
		if err = syncJournalDirectory(dir); err != nil {
			return nil, err
		}
	} else {
		data, er := j.readFrame()
		if er != nil {
			return nil, fmt.Errorf("%w: missing genesis: %v", ErrJournalCorrupt, er)
		}
		if !bytes.Equal(data, genesisData) {
			return nil, fmt.Errorf("%w: genesis/chain/version mismatch", ErrJournalCorrupt)
		}
		for {
			data, er = j.readFrame()
			if er == io.EOF {
				break
			}
			if er != nil {
				return nil, er
			}
			j.blocks++
			if j.blocks > maxJournalBlocks {
				return nil, ErrJournalCorrupt
			}
			height, txs, er := decodeBlock(data)
			if er != nil {
				return nil, er
			}
			// e.journal stays nil until replay completes, avoiding duplicate disk writes.
			if _, er = e.ApplyBlock(height, txs); er != nil {
				return nil, fmt.Errorf("%w: block replay rejected: %v", ErrJournalCorrupt, er)
			}
		}
	}
	if _, err = f.Seek(0, io.SeekEnd); err != nil {
		return nil, err
	}
	e.journal = j
	ok = true
	return e, nil
}

func encodeGenesis(chain string, genesis []protocol.Hash) []byte {
	var b bytes.Buffer
	b.WriteString(journalMagic)
	_ = binary.Write(&b, binary.BigEndian, protocol.Version)
	b.WriteByte(byte(len(chain)))
	b.WriteString(chain)
	_ = binary.Write(&b, binary.BigEndian, uint32(len(genesis)))
	for _, c := range genesis {
		b.Write(c[:])
	}
	b.WriteString(protocol.CircuitID)
	return b.Bytes()
}

func (j *journal) appendBlock(height uint64, txs []protocol.Envelope) error {
	if j.blocks >= maxJournalBlocks {
		return errors.New("local journal block limit reached")
	}
	var b bytes.Buffer
	_ = binary.Write(&b, binary.BigEndian, height)
	_ = binary.Write(&b, binary.BigEndian, uint32(len(txs)))
	for _, tx := range txs {
		data, err := tx.MarshalBinary()
		if err != nil {
			return err
		}
		_ = binary.Write(&b, binary.BigEndian, uint32(len(data)))
		b.Write(data)
	}
	if err := j.appendFrame(b.Bytes()); err != nil {
		return err
	}
	j.blocks++
	return nil
}

func frameDigest(previous [32]byte, header, payload []byte) [32]byte {
	h := sha256.New()
	_, _ = h.Write([]byte(journalMagic))
	_, _ = h.Write(previous[:])
	_, _ = h.Write(header)
	_, _ = h.Write(payload)
	var out [32]byte
	copy(out[:], h.Sum(nil))
	return out
}

func (j *journal) appendFrame(payload []byte) error {
	if len(payload) == 0 || len(payload) > maxFrameBytes {
		return ErrJournalCorrupt
	}
	total := int64(4 + len(payload) + 32)
	if j.size > MaxJournalBytes-total {
		return errors.New("local journal size limit reached")
	}
	var header [4]byte
	binary.BigEndian.PutUint32(header[:], uint32(len(payload)))
	digest := frameDigest(j.tail, header[:], payload)
	frame := make([]byte, 0, int(total))
	frame = append(frame, header[:]...)
	frame = append(frame, payload...)
	frame = append(frame, digest[:]...)
	n, err := j.write(frame)
	if err != nil {
		return err
	}
	if n != len(frame) {
		return io.ErrShortWrite
	}
	if err = j.sync(); err != nil {
		return err
	}
	j.size += total
	j.tail = digest
	return nil
}

func (j *journal) readFrame() ([]byte, error) {
	var header [4]byte
	n, err := io.ReadFull(j.f, header[:])
	if err == io.EOF && n == 0 {
		return nil, io.EOF
	}
	if err != nil {
		return nil, fmt.Errorf("%w: short frame header", ErrJournalCorrupt)
	}
	length := binary.BigEndian.Uint32(header[:])
	if length == 0 || length > maxFrameBytes {
		return nil, ErrJournalCorrupt
	}
	payload := make([]byte, int(length))
	if _, err = io.ReadFull(j.f, payload); err != nil {
		return nil, ErrJournalCorrupt
	}
	var digest [32]byte
	if _, err = io.ReadFull(j.f, digest[:]); err != nil {
		return nil, ErrJournalCorrupt
	}
	if digest != frameDigest(j.tail, header[:], payload) {
		return nil, ErrJournalCorrupt
	}
	j.tail = digest
	return payload, nil
}

func decodeBlock(data []byte) (uint64, []protocol.Envelope, error) {
	r := bytes.NewReader(data)
	var height uint64
	var count uint32
	if binary.Read(r, binary.BigEndian, &height) != nil || binary.Read(r, binary.BigEndian, &count) != nil || count > MaxBlockTransactions {
		return 0, nil, ErrJournalCorrupt
	}
	txs := make([]protocol.Envelope, 0, int(count))
	total := 0
	for i := uint32(0); i < count; i++ {
		var n uint32
		if binary.Read(r, binary.BigEndian, &n) != nil || n == 0 || n > protocol.MaxTxBytes || uint64(n) > uint64(r.Len()) {
			return 0, nil, ErrJournalCorrupt
		}
		total += int(n)
		if total > MaxBlockBytes {
			return 0, nil, ErrJournalCorrupt
		}
		raw := make([]byte, int(n))
		_, _ = io.ReadFull(r, raw)
		tx, err := protocol.DecodeBinary(raw)
		if err != nil {
			return 0, nil, fmt.Errorf("%w: bad envelope", ErrJournalCorrupt)
		}
		txs = append(txs, tx)
	}
	if r.Len() != 0 {
		return 0, nil, ErrJournalCorrupt
	}
	return height, txs, nil
}
