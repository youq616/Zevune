// Package gatetest supplies REAL local OS pipes for gateway tests. It contains
// no accepting backend, protocol replacement, or application entry point.
package gatetest

import "os"

func Pipe() (*os.File, *os.File, error) { return os.Pipe() }
