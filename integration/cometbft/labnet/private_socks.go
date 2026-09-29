package labnet

import (
	"context"
	"encoding/binary"
	"errors"
	"io"
	"net"
	"strconv"
	"time"
)

// This is a transport error, not an authenticated rejection of a transaction.
// Never include peer bytes, local addresses or isolation values in it.
var errPrivateSOCKS = errors.New("private RPC SOCKS transport failed")

const socksIsolationUsername = "<torS0X>0"
const socksHandshakeTimeout = 5 * time.Second

// net/http detaches dial cancellation but preserves context values. Retain the
// original request lifecycle explicitly, without changing legacy TCP dialing.
type privateRPCRequestContextKey struct{}

// Constructed only after canonical endpoint/proxy validation by newPrivatePeer.
// Immutable per peer: reconnections share this operation's isolation value,
// but separate top-level operations do not share values or connection pools.
type onionDialer struct {
	proxy     string
	host      string
	port      uint16
	isolation string
}

func (d *onionDialer) dialContext(ctx context.Context, network, address string) (net.Conn, error) {
	if d == nil || ctx == nil || ctx.Err() != nil || network != "tcp" ||
		len(d.host) != 62 || d.port == 0 || len(d.isolation) != 64 ||
		address != net.JoinHostPort(d.host, strconv.Itoa(int(d.port))) {
		return nil, errPrivateSOCKS
	}
	// This shorter context covers the ENTIRE dial and SOCKS exchange. The HTTP
	// caller retains its original timeout; SOCKS adds no extra time allowance.
	deadline := time.Now().Add(socksHandshakeTimeout)
	original, _ := ctx.Value(privateRPCRequestContextKey{}).(context.Context)
	if original != nil {
		if original.Err() != nil {
			return nil, errPrivateSOCKS
		}
		if earlier, ok := original.Deadline(); ok && earlier.Before(deadline) {
			deadline = earlier
		}
	}
	handshake, cancel := context.WithDeadline(ctx, deadline)
	defer cancel()
	if original != nil {
		// This callback only cancels the private handshake context; it never
		// owns the returned connection. The socket watcher below is joined.
		stopOriginal := context.AfterFunc(original, cancel)
		defer stopOriginal()
	}
	conn, err := (&net.Dialer{Timeout: 2 * time.Second}).DialContext(handshake, "tcp4", d.proxy)
	if err != nil {
		return nil, errPrivateSOCKS
	}
	keep := false
	defer func() {
		if !keep {
			_ = conn.Close()
		}
	}()
	deadline, _ = handshake.Deadline()
	if err = conn.SetDeadline(deadline); err != nil {
		return nil, errPrivateSOCKS
	}
	// A context can be cancelled before its deadline. Close the real socket to
	// interrupt reads AND writes, then join the watcher before handing off the
	// connection. A completed handshake must not leave a stale closer behind.
	stop, stopped := make(chan struct{}), make(chan struct{})
	go func() {
		defer close(stopped)
		select {
		case <-handshake.Done():
			_ = conn.Close()
		case <-stop:
		}
	}()
	err = d.handshake(conn)
	close(stop)
	<-stopped
	if err != nil || handshake.Err() != nil || conn.SetDeadline(time.Time{}) != nil {
		return nil, errPrivateSOCKS
	}
	keep = true
	return conn, nil
}

func writeSOCKS(w io.Writer, data []byte) error {
	for len(data) != 0 {
		n, err := w.Write(data)
		if err != nil {
			return errPrivateSOCKS
		}
		if n <= 0 || n > len(data) {
			return errPrivateSOCKS
		}
		data = data[n:]
	}
	return nil
}

func (d *onionDialer) handshake(conn net.Conn) error {
	// Offer USERNAME/PASSWORD only. Even a cooperative no-auth reply is an
	// error: it cannot establish the required Tor stream-isolation parameter.
	if writeSOCKS(conn, []byte{5, 1, 2}) != nil {
		return errPrivateSOCKS
	}
	var pair [2]byte
	if _, err := io.ReadFull(conn, pair[:]); err != nil || pair != [2]byte{5, 2} {
		return errPrivateSOCKS
	}
	auth := make([]byte, 0, 3+len(socksIsolationUsername)+len(d.isolation))
	auth = append(auth, 1, byte(len(socksIsolationUsername)))
	auth = append(auth, socksIsolationUsername...)
	auth = append(auth, byte(len(d.isolation)))
	auth = append(auth, d.isolation...)
	if writeSOCKS(conn, auth) != nil {
		return errPrivateSOCKS
	}
	if _, err := io.ReadFull(conn, pair[:]); err != nil || pair != [2]byte{1, 0} {
		return errPrivateSOCKS
	}
	// Send the frozen onion name AS A DOMAIN, never as a locally resolved IP.
	request := make([]byte, 0, 7+len(d.host))
	request = append(request, 5, 1, 0, 3, byte(len(d.host)))
	request = append(request, d.host...)
	request = binary.BigEndian.AppendUint16(request, d.port)
	if writeSOCKS(conn, request) != nil {
		return errPrivateSOCKS
	}
	var header [4]byte
	if _, err := io.ReadFull(conn, header[:]); err != nil || header[0] != 5 || header[1] != 0 || header[2] != 0 {
		return errPrivateSOCKS
	}
	size := 0
	switch header[3] {
	case 1:
		size = 4
	case 4:
		size = 16
	case 3:
		var length [1]byte
		if _, err := io.ReadFull(conn, length[:]); err != nil || length[0] == 0 {
			return errPrivateSOCKS
		}
		size = int(length[0])
	default:
		return errPrivateSOCKS
	}
	// Consume the complete bounded reply, including BND.PORT, without reading
	// any application data. Never follow or resolve the proxy's BND address.
	var bound [257]byte
	if _, err := io.ReadFull(conn, bound[:size+2]); err != nil {
		return errPrivateSOCKS
	}
	return nil
}
