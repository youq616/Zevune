//go:build !linux && !windows

package rpcgate

import "os"

// Other hosts have not established an inherited-stream cancellation contract.
func streamPipe(*os.File, bool) (*os.File, error) { return nil, ErrConfiguration }
