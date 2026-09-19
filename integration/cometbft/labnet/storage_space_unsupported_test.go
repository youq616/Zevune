//go:build !linux && !windows

package labnet

import (
	"errors"
	"testing"

	"github.com/youq616/Zevune/internal/poolbridge"
)

func TestDiskSpaceUnsupportedPlatformReturnsExplicitError(t *testing.T) {
	if target, err := openDiskSpaceTarget(poolbridge.ActiveSegmentsV1, t.TempDir()); target != nil || !errors.Is(err, errDiskSpaceUnsupported) {
		t.Fatal("unsupported platform silently used a substitute disk query")
	}
}
