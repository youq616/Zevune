"""Apply the existing real-Git source-binding tests to the request workflow."""
from pathlib import Path
from unittest.mock import patch
import unittest
import test_wallet_backup_source as established

WORKFLOW = Path(__file__).resolve().parents[2] / '.github/workflows/payment-requests.yml'

class RequestSourceTests(established.CatalogSourceTests):
    def setUp(self):
        guard = patch.object(established, 'WORKFLOW', WORKFLOW)
        guard.start()
        self.addCleanup(guard.stop)

    def test_workflow_pins_checkout_and_runs_source_regressions(self):
        super().test_workflow_pins_checkout_and_runs_source_regressions()
        source = WORKFLOW.read_text()
        self.assertEqual(source.count("'scripts/tests/test_payment_request_source.py'"), 2)
        self.assertIn('python -m unittest discover -s scripts/tests -p test_payment_request_source.py -v', source)
        self.assertIn("'scripts/check_payment_request_backend.py', str(backend)", source)
        self.assertNotIn('continue-on-error', source)

if __name__ == '__main__':
    unittest.main()
