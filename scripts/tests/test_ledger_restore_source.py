"""Execute the established real-Git source rejection tests on ledger recovery CI."""
from pathlib import Path
import unittest
from unittest.mock import patch

import test_wallet_backup_source as established

WORKFLOW = Path(__file__).resolve().parents[2] / '.github/workflows/ledger-restore.yml'


class LedgerSourceTests(established.CatalogSourceTests):
    def setUp(self):
        guard = patch.object(established, 'WORKFLOW', WORKFLOW)
        guard.start()
        self.addCleanup(guard.stop)

    def test_workflow_pins_checkout_and_runs_source_regressions(self):
        super().test_workflow_pins_checkout_and_runs_source_regressions()
        source = WORKFLOW.read_text()
        for name in ('test_ledger_restore.py', 'test_ledger_restore_source.py'):
            self.assertEqual(source.count("'scripts/tests/" + name + "'"), 2)
            self.assertIn('python -m unittest discover -s scripts/tests -p ' + name + ' -v', source)
        self.assertIn("run: python scripts/check_ledger_restore.py", source)
        self.assertNotIn('continue-on-error', source)


if __name__ == '__main__':
    unittest.main()
