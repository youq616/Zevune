//go:build !linux && !windows

package gatetest

import (
	"errors"
	"os"
)

func Pipe() (*os.File, *os.File, error) { return nil, nil, errors.New("unsupported gateway test host") }
