"""Real-Git source rejection tests plus mandatory native display gates."""
from pathlib import Path
import unittest
from unittest.mock import patch
import test_wallet_backup_source as established

WORKFLOW = Path(__file__).resolve().parents[2] / '.github/workflows/request-desktop.yml'


class DesktopSourceTests(established.CatalogSourceTests):
    def setUp(self):
        guard = patch.object(established, 'WORKFLOW', WORKFLOW)
        guard.start()
        self.addCleanup(guard.stop)

    def test_workflow_pins_checkout_and_runs_source_regressions(self):
        super().test_workflow_pins_checkout_and_runs_source_regressions()
        source = WORKFLOW.read_text()
        for name in ('test_request_desktop.py', 'test_request_desktop_source.py'):
            self.assertEqual(source.count("'scripts/tests/" + name + "'"), 2)
            self.assertIn('python -m unittest discover -s scripts/tests -p ' + name + ' -v', source)
        self.assertIn('xvfb-run -a python scripts/check_request_desktop_gui.py -v', source)
        self.assertIn('python scripts/check_request_desktop_gui.py -v', source)
        self.assertIn("'scripts/check_request_desktop_backend.py', str(backend)", source)
        self.assertNotIn('continue-on-error', source)


if __name__ == '__main__':
    unittest.main()
