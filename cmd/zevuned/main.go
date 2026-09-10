package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"github.com/youq616/Zevune/internal/api"
	"net"
	"net/http"
	"os"
	"os/signal"
	"time"
)

func run() error {
	listen := flag.String("listen", "127.0.0.1:8080", "numeric loopback address only")
	chain := flag.String("chain-id", "veil-local-devnet-1", "local prototype chain id")
	flag.Parse()
	host, _, err := net.SplitHostPort(*listen)
	if err != nil {
		return err
	}
	ip := net.ParseIP(host)
	if ip == nil || !ip.IsLoopback() {
		return errors.New("this prototype refuses non-loopback listeners")
	}
	handler, err := api.New(*chain)
	if err != nil {
		return err
	}
	srv := &http.Server{Addr: *listen, Handler: handler, ReadHeaderTimeout: 3 * time.Second, ReadTimeout: 5 * time.Second, WriteTimeout: 5 * time.Second, IdleTimeout: 15 * time.Second, MaxHeaderBytes: 8 * 1024}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	done := make(chan error, 1)
	go func() { done <- srv.ListenAndServe() }()
	fmt.Fprintf(os.Stderr, "ZEVUNE LOCAL DIAGNOSTIC SCAFFOLD on %s; no ZK verifier, no consensus, NO PAYMENTS.\n", *listen)
	select {
	case err := <-done:
		if !errors.Is(err, http.ErrServerClosed) {
			return err
		}
	case <-ctx.Done():
		shutdown, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		return srv.Shutdown(shutdown)
	}
	return nil
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
