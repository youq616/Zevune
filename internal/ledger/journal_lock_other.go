//go:build !linux && !darwin && !windows

package ledger

import (
	"errors"
	"os"
)

func lockJournal(*os.File) error        { return errors.New("persistent mode unsupported on this OS") }
func syncJournalDirectory(string) error { return errors.New("persistent mode unsupported on this OS") }
