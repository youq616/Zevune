package rpcgate

import (
	"net"
	"sync"
)

// Accepted TCP sockets, including incomplete HTTP headers, consume capacity.
// Excess sockets are closed immediately, never queued in user space.
type limitedListener struct {
	net.Listener
	mu     sync.Mutex
	closed bool
	conns  map[*trackedConn]struct{}
}

type trackedConn struct {
	net.Conn
	owner *limitedListener
	once  sync.Once
}

func (l *limitedListener) Accept() (net.Conn, error) {
	for {
		c, err := l.Listener.Accept()
		if err != nil {
			return nil, err
		}
		l.mu.Lock()
		if l.closed || len(l.conns) >= maxConnections {
			closed := l.closed
			l.mu.Unlock()
			_ = c.Close()
			if closed {
				return nil, net.ErrClosed
			}
			continue
		}
		tracked := &trackedConn{Conn: c, owner: l}
		l.conns[tracked] = struct{}{}
		l.mu.Unlock()
		return tracked, nil
	}
}

func (l *limitedListener) Close() error {
	l.mu.Lock()
	l.closed = true
	l.mu.Unlock()
	return l.Listener.Close()
}

func (l *limitedListener) closeConnections() {
	l.mu.Lock()
	list := make([]*trackedConn, 0, len(l.conns))
	for c := range l.conns {
		list = append(list, c)
	}
	l.mu.Unlock()
	for _, c := range list {
		_ = c.Close()
	}
}

func (c *trackedConn) Close() error {
	var err error
	c.once.Do(func() {
		err = c.Conn.Close()
		c.owner.mu.Lock()
		delete(c.owner.conns, c)
		c.owner.mu.Unlock()
	})
	return err
}
