"""Real refusing child processes, not a wallet/proof authentication substitute."""
import hashlib
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wallet_backup_backend as transport
from test_wallet_backup import frames


class ReconcileTransportTests(unittest.TestCase):
    def setUp(self):
        self.executable = Path(sys.executable).resolve(strict=True)
        self.backend = transport.Backend(self.executable, hashlib.sha256(self.executable.read_bytes()).hexdigest())
        self.children, self.threads = [], []
        self.popen, self.thread = subprocess.Popen, threading.Thread
        self.addCleanup(self.cleanup)

    def child(self, *args, **kwargs):
        # Redirect only the process launch to a bounded, non-accepting Python
        # child. No success reply is constructed or passed to wallet callers.
        process = self.popen([str(self.executable), "-c", "import time; time.sleep(30)"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.children.append(process)
        return process

    def call(self):
        return self.backend.call(9, b"unused-test-password", ["unused.wallet"], frames()[1])

    def assert_reaped_and_closed(self):
        self.assertEqual(len(self.children), 1)
        process = self.children[0]
        self.assertIsNotNone(process.poll(), "owned child still alive after refusal")
        self.assertTrue(all(stream.closed for stream in (process.stdin, process.stdout, process.stderr)))
        self.assertFalse(any(worker.is_alive() for worker in self.threads))

    def cleanup(self):
        # The OLD-code red test leaves a real child; clean up that specific
        # child only, so the regression itself never leaves a waiting process.
        for process in self.children:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
        for worker in self.threads:
            if worker.ident is not None:
                worker.join(timeout=3)
        for process in self.children:
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
        self.children.clear()
        self.threads.clear()

    def test_each_thread_constructor_failure_reaps_child_and_closes_pipes(self):
        for index in range(3):
            def construct(*args, **kwargs):
                if len(self.threads) == index:
                    raise MemoryError("test_only_constructor_failure")
                worker = self.thread(*args, **kwargs)
                self.threads.append(worker)
                return worker
            try:
                with self.subTest(index=index), patch.object(transport.subprocess, "Popen", side_effect=self.child), \
                        patch.object(transport.threading, "Thread", side_effect=construct):
                    with self.assertRaises(MemoryError):
                        self.call()
                    self.assert_reaped_and_closed()
            finally:
                self.cleanup()

    def test_each_thread_start_failure_reaps_child_and_closes_pipes(self):
        for index in range(3):
            def construct(*args, **kwargs):
                worker = self.thread(*args, **kwargs)
                if len(self.threads) == index:
                    def fail():
                        raise RuntimeError("test_only_start_failure")
                    worker.start = fail
                self.threads.append(worker)
                return worker
            try:
                with self.subTest(index=index), patch.object(transport.subprocess, "Popen", side_effect=self.child), \
                        patch.object(transport.threading, "Thread", side_effect=construct):
                    with self.assertRaises(RuntimeError):
                        self.call()
                    self.assert_reaped_and_closed()
            finally:
                self.cleanup()

    def test_timeout_reaps_and_closes_all_three_pipes(self):
        with patch.object(transport.subprocess, "Popen", side_effect=self.child), \
                patch.object(transport, "TIMEOUT", 0.05):
            with self.assertRaisesRegex(transport.BackendError, "backend_timeout"):
                self.call()
        self.assert_reaped_and_closed()


if __name__ == "__main__":
    unittest.main()
