// zevune-rpc-gateway serves four bounded RPC methods on numeric loopback only.
// It does not publish an onion service, load wallet keys or start any node.
package main

import (
	"context"
	"errors"
	"flag"
	"io"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/youq616/Zevune/integration/cometbft/labnet"
	"github.com/youq616/Zevune/internal/rpcgate"
)

type options struct {
	config, pin string
	gateway     labnet.GatewayOptions
	stopOnEOF   bool
}

func parse(args []string) (options, error) {
	var o options
	f := flag.NewFlagSet("zevune-rpc-gateway", flag.ContinueOnError)
	f.SetOutput(io.Discard)
	f.BoolVar(&o.gateway.NoRealFunds, "no-real-funds", false, "required no-funds acknowledgement")
	f.StringVar(&o.config, "config", "", "independently pinned public network config")
	f.StringVar(&o.pin, "config-sha256", "", "independent public config digest")
	f.StringVar(&o.gateway.Listen, "listen", "", "canonical numeric loopback host:port")
	f.StringVar(&o.gateway.Upstream, "upstream", "", "fixed numeric loopback RPC URL")
	f.StringVar(&o.gateway.OnionEndpoint, "onion-endpoint", "", "expected canonical onion-v3 RPC URL")
	f.BoolVar(&o.stopOnEOF, "stop-on-stdin-eof", false, "stop on stdin EOF")
	seen := make(map[string]bool)
	for i := 0; i < len(args); i++ {
		if !strings.HasPrefix(args[i], "--") || args[i] == "--" {
			return o, rpcgate.ErrConfiguration
		}
		name, value, inline := strings.Cut(args[i][2:], "=")
		entry := f.Lookup(name)
		if entry == nil || seen[name] || inline && value == "" {
			return o, rpcgate.ErrConfiguration
		}
		seen[name] = true
		boolean := name == "no-real-funds" || name == "stop-on-stdin-eof"
		if !inline && !boolean {
			i++
			if i >= len(args) || strings.HasPrefix(args[i], "--") {
				return o, rpcgate.ErrConfiguration
			}
		}
	}
	if f.Parse(args) != nil || f.NArg() != 0 || !o.gateway.NoRealFunds || o.config == "" || o.pin == "" || o.gateway.Listen == "" || o.gateway.Upstream == "" || o.gateway.OnionEndpoint == "" {
		return o, rpcgate.ErrConfiguration
	}
	return o, nil
}

func execute(parent context.Context, args []string, input, output *os.File) (result error) {
	o, err := parse(args)
	if err != nil || parent == nil || parent.Err() != nil || output == nil || o.stopOnEOF && input == nil {
		return rpcgate.ErrConfiguration
	}
	pin, err := labnet.ParseHash(o.pin)
	if err != nil {
		return rpcgate.ErrConfiguration
	}
	n, err := labnet.Load(o.config, pin)
	if err != nil {
		return rpcgate.ErrConfiguration
	}
	// Validate every endpoint before starting the input reader or service. The
	// network method repeats the complete fixed-profile checks before listening.
	if rpcgate.ValidateListen(o.gateway.Listen) != nil || labnet.ValidateEndpoint(o.gateway.Upstream) != nil || labnet.ValidatePrivateRPC(o.gateway.OnionEndpoint, o.gateway.Listen) != nil || o.gateway.Upstream == "http://"+o.gateway.Listen {
		return rpcgate.ErrConfiguration
	}
	out, err := rpcgate.OpenOutput(output)
	if err != nil {
		return err
	}
	defer out.Close()
	var in *rpcgate.Input
	if o.stopOnEOF {
		in, err = rpcgate.OpenInput(input)
		if err != nil {
			return err
		}
		defer in.Close()
	}
	// Both capabilities are established before ANY watcher or listener starts.
	ctx, cancel := context.WithCancel(parent)
	defer cancel()
	if in != nil {
		stopped := make(chan error, 1)
		go func() { inputErr := in.UntilEOF(ctx); cancel(); stopped <- inputErr }()
		// Every read has a short real deadline. Join first, then close ownership;
		// neither an inherited blocking Read nor a detached task survives return.
		defer func() { cancel(); result = inputCompletion(result, <-stopped) }()
	}
	return n.RunGateway(ctx, o.gateway, out)
}

// EOF and an already-requested cancellation are normal. A real input failure
// must not become exit 0 merely because the watcher also stopped the service.
func inputCompletion(serviceErr, inputErr error) error {
	if serviceErr != nil {
		return serviceErr
	}
	if inputErr == nil || errors.Is(inputErr, context.Canceled) || errors.Is(inputErr, context.DeadlineExceeded) {
		return nil
	}
	return rpcgate.ErrService
}

func run() int {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	failure, err := rpcgate.OpenOutput(os.Stderr)
	if err != nil {
		// Unsupported diagnostics must not turn a startup rejection into a hang.
		// There is deliberately no fmt.Fprintln/os.Stderr fallback here.
		return 1
	}
	defer failure.Close()
	if err := execute(ctx, os.Args[1:], os.Stdin, os.Stdout); err != nil {
		_ = rpcgate.WriteFailure(context.Background(), failure)
		return 1
	}
	return 0
}

func main() { os.Exit(run()) }
