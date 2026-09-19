//go:build !linux && !windows

package labnet

import "os"

const diskSpaceScope = "unsupported_disk_space_platform"
const diskSpaceSupported = false
const diskSpaceUsesDirectory = false

func diskSpacePlatformInfo(_ os.FileInfo) bool { return false }

func openDiskSpaceHandle(_ string, _ bool) (*os.File, error) { return nil, errDiskSpace }

func diskSpaceAvailable(_ *diskSpaceTarget) (uint64, error) { return 0, errDiskSpace }
