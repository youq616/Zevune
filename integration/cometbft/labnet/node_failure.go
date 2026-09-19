package labnet

import (
	"context"
	"errors"

	"github.com/youq616/Zevune/internal/poolbridge"
)

// NodeFailure contains only fixed diagnostic labels. It never includes the
// underlying error text, peer response, local path or signer/worker contents.
type NodeFailure struct {
	Stage string `json:"stage"`
	Code  string `json:"code"`
}

type nodeRunError struct {
	stage string
	err   error
}

func (e *nodeRunError) Error() string { return "local node failed during " + e.stage }
func (e *nodeRunError) Unwrap() error { return e.err }

func DescribeNodeFailure(err error) NodeFailure {
	stage := "validation"
	var run *nodeRunError
	if errors.As(err, &run) {
		stage = run.stage
	}
	return NodeFailure{Stage: stage, Code: nodeFailureCode(err)}
}

func nodeFailureCode(err error) string {
	switch {
	case errors.Is(err, context.DeadlineExceeded):
		return "deadline"
	case errors.Is(err, context.Canceled):
		return "canceled"
	case isAddressInUse(err):
		return "address_in_use"
	case isConnectionRefused(err):
		return "connection_refused"
	case errors.Is(err, ErrNodeStopped):
		return "consensus_stopped"
	case errors.Is(err, poolbridge.ErrUnavailable):
		return "worker_unavailable"
	case errors.Is(err, poolbridge.ErrProtocol):
		return "worker_protocol"
	case errors.Is(err, poolbridge.ErrRejected):
		return "worker_rejected"
	case errors.Is(err, ErrConfiguration):
		return "configuration"
	case errors.Is(err, ErrStorage):
		return "storage"
	case errors.Is(err, ErrBounds), errors.Is(err, poolbridge.ErrBounds):
		return "bounds"
	default:
		return "other"
	}
}
