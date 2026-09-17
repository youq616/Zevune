"""Windows shared-file regression and bounded public I/O diagnostics.

The native tests retain real DELETE access to fix the sharing state that can
exist after a new rename name becomes visible, before the rename handle closes.
The successful-read case does not execute a rename and does not prove that a
historical CI failure had this cause. All files contain synthetic public JSON.

Win32 sharing contract:
https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew
https://devblogs.microsoft.com/oldnewthing/20211022-00/?p=105822
"""
from contextlib import contextmanager
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_payment_resources as resource


class MutatingReader:
    """Inject one deterministic metadata change after an actual binary read."""
    def __init__(self, stream, mutate):
        self.stream = stream
        self.mutate = mutate

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *arguments):
        return self.stream.__exit__(*arguments)

    def fileno(self):
        return self.stream.fileno()

    def close(self):
        return self.stream.close()

    def read(self, maximum):
        raw = self.stream.read(maximum)
        self.mutate()
        return raw


@unittest.skipUnless(sys.platform == "win32", "requires native Windows file-sharing semantics")
class WindowsSharedProtocolTests(unittest.TestCase):
    def setUp(self):
        from ctypes import wintypes

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateFileW": ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                             wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                             wintypes.HANDLE], wintypes.HANDLE),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "SetFilePointerEx": ([wintypes.HANDLE, ctypes.c_longlong,
                                  ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD], wintypes.BOOL),
            "WriteFile": ([wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
                           ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID], wintypes.BOOL),
            "FlushFileBuffers": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = arguments, result
        self.wintypes = wintypes

    @contextmanager
    def held_delete_access(self, path, writable=False):
        access = 0x80000000 | 0x10000  # GENERIC_READ | DELETE
        if writable:
            access |= 0x40000000
        handle = self.api.CreateFileW(str(path), access, 7, None, 3, 0x80, None)
        self.assertNotIn(handle, (None, ctypes.c_void_p(-1).value), "native DELETE holder must open")
        try:
            yield handle
        finally:
            self.assertTrue(self.api.CloseHandle(handle), "native DELETE holder must close")

    def assert_legacy_share_conflict(self, path):
        # Win32 preserves error 32; the CRT used by Path.open may expose only
        # errno EACCES. Verify both layers without inventing a CRT winerror.
        handle = self.api.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x80, None)
        code = ctypes.get_last_error()
        if handle not in (None, ctypes.c_void_p(-1).value):
            self.api.CloseHandle(handle)
            self.fail("legacy reader unexpectedly shared an outstanding DELETE request")
        self.assertEqual(code, 32)
        with self.assertRaises(OSError) as caught:
            with path.open("rb") as stream:
                stream.read()
        self.assertTrue(caught.exception.errno == errno.EACCES
                        or getattr(caught.exception, "winerror", None) == 32)

    def test_delete_holder_blocks_legacy_open_but_shared_reader_preserves_exact_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "progress-0001.json"
            raw = b'{"schema_version":1,"seq":1,"synthetic_public_value":7}\n'
            path.write_bytes(raw)
            with self.held_delete_access(path):
                self.assert_legacy_share_conflict(path)
                value, digest = resource.read_public_json(path, resource.MAX_PROGRESS_BYTES)
                self.assertEqual(value, json.loads(raw))
                self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
            self.assertEqual(path.read_bytes(), raw)

    def test_delete_sharing_does_not_disable_replacement_identity_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, replacement, retired = root / "event-01.json", root / "replacement.json", root / "retired.json"
            raw = b'{"synthetic_public_value":7}'
            path.write_bytes(raw)
            replacement.write_bytes(raw)  # Equal bytes/size, distinct file identity.
            original = resource.open_public_binary

            def replace_before_open(target):
                self.assertEqual(target, path)
                path.rename(retired)
                replacement.rename(path)
                return original(target)

            with self.held_delete_access(path), mock.patch.object(
                    resource, "open_public_binary", side_effect=replace_before_open):
                with self.assertRaisesRegex(resource.MeasurementError, "protocol_file_changed"):
                    resource.read_public_json(path, resource.MAX_EVENT_BYTES)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(retired.read_bytes(), raw)

    def test_delete_sharing_does_not_disable_post_read_size_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "event-01.json"
            raw = b'{"synthetic_public_value":7}'
            path.write_bytes(raw)
            original = resource.open_public_binary
            with self.held_delete_access(path, writable=True) as holder:
                def append_one_byte():
                    self.assertTrue(self.api.SetFilePointerEx(holder, 0, None, 2))
                    written = self.wintypes.DWORD()
                    buffer = ctypes.create_string_buffer(b" ")
                    self.assertTrue(self.api.WriteFile(holder, buffer, 1, ctypes.byref(written), None))
                    self.assertEqual(written.value, 1)
                    self.assertTrue(self.api.FlushFileBuffers(holder))

                with mock.patch.object(resource, "open_public_binary", side_effect=lambda target:
                                       MutatingReader(original(target), append_one_byte)):
                    with self.assertRaisesRegex(resource.MeasurementError, "protocol_file_changed"):
                        resource.read_public_json(path, resource.MAX_EVENT_BYTES)
            self.assertEqual(path.read_bytes(), raw + b" ")


class WindowsHandleOwnershipTests(unittest.TestCase):
    def test_failed_crt_handle_transfer_closes_only_the_owned_windows_handle(self):
        api = mock.Mock()
        api.CreateFileW.return_value = 7654321
        api.CloseHandle.return_value = 1
        crt = mock.Mock()
        crt.open_osfhandle.side_effect = OSError(errno.EINVAL, "private exception must not be copied")
        with mock.patch.object(resource.os, "O_BINARY", 0x8000, create=True):
            with self.assertRaises(OSError):
                resource.windows_public_binary(Path("synthetic-protocol.json"), api=api, crt=crt)
        crt.open_osfhandle.assert_called_once()
        self.assertEqual(crt.open_osfhandle.call_args.args[0], 7654321)
        api.CloseHandle.assert_called_once_with(7654321)

    def test_failed_stream_creation_closes_crt_descriptor_not_raw_handle_twice(self):
        api, crt = mock.Mock(), mock.Mock()
        api.CreateFileW.return_value = 7654321
        crt.open_osfhandle.return_value = 333
        with mock.patch.object(resource.os, "O_BINARY", 0x8000, create=True), \
                mock.patch.object(resource.os, "set_inheritable") as inheritance, \
                mock.patch.object(resource.os, "fdopen", side_effect=OSError(errno.EINVAL, "private")), \
                mock.patch.object(resource.os, "close") as close_descriptor:
            with self.assertRaises(OSError):
                resource.windows_public_binary(Path("synthetic-protocol.json"), api=api, crt=crt)
        inheritance.assert_called_once_with(333, False)
        close_descriptor.assert_called_once_with(333)
        api.CloseHandle.assert_not_called()
        self.assertEqual(api.CreateFileW.call_args.args,
                         ("synthetic-protocol.json", 0x80000000, 7, None, 3, 0x80, None))


class PublicReadDiagnosticTests(unittest.TestCase):
    def test_known_protocol_positions_and_os_codes_survive_without_private_context(self):
        for name, kind, seq in (("event-01.json", "event", 1), ("event-09.json", "event", 9),
                                ("progress-0284.json", "progress", 284),
                                ("progress-2048.json", "progress", 2048),
                                ("result.json", "result", None)):
            path = Path("PRIVATE_DIRECTORY") / name
            error = OSError(errno.EACCES, "PRIVATE_EXCEPTION", str(path))
            error.winerror = 32
            failure = resource.ProtocolReadError(path, "open", error)
            with self.subTest(name=name):
                self.assertEqual(str(failure), "protocol_file_read_failed")
                self.assertEqual(failure.public(), {
                    "error_code": "protocol_file_read_failed",
                    "io_diagnostic": {"stage": "open", "errno": errno.EACCES,
                                      "winerror": 32, "protocol_kind": kind, "seq": seq},
                })
                self.assertNotIn("PRIVATE", json.dumps(failure.public()))
                self.assertNotIn(name, json.dumps(failure.public()))

    def test_unknown_names_and_invalid_diagnostic_scalars_are_not_serialized(self):
        names = ("event-00.json", "event-10.json", "event-001.json", "event-01.json.PRIVATE",
                 "progress-0000.json", "progress-2049.json", "progress-1.json", "Result.json",
                 "PRIVATE_WALLET.zwallet")
        for name in names:
            failure = resource.ProtocolReadError(Path(name), "open", OSError(errno.EACCES, "PRIVATE"))
            with self.subTest(name=name):
                self.assertEqual(failure.public()["io_diagnostic"]["protocol_kind"], "unknown")
                self.assertIsNone(failure.public()["io_diagnostic"]["seq"])
                self.assertNotIn(name, json.dumps(failure.public()))
        for invalid in (True, False, -1, 1 << 32, 32.0, "PRIVATE", [], {}):
            error = OSError()
            error.errno = invalid
            error.winerror = invalid
            failure = resource.ProtocolReadError(Path("result.json"), invalid, error)
            with self.subTest(invalid=repr(invalid)):
                self.assertEqual(failure.public()["io_diagnostic"], {
                    "stage": "unknown", "errno": None, "winerror": None,
                    "protocol_kind": "result", "seq": None,
                })

    def test_all_io_stages_produce_only_bounded_public_diagnostics(self):
        for stage in ("lstat_before", "open", "fstat", "read", "close", "lstat_after"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "progress-0284.json"
                path.write_bytes(b'{"synthetic_public_value":7}')
                before = path.lstat()
                error = OSError(errno.EIO, "PRIVATE_EXCEPTION", str(path))
                error.winerror = 32
                with path.open("rb") as stream:
                    wrapper = mock.Mock(wraps=stream)
                    if stage == "read":
                        wrapper.read.side_effect = error
                    if stage == "close":
                        def failed_close():
                            stream.close()
                            raise error
                        wrapper.close.side_effect = failed_close
                    real_fstat = os.fstat
                    stat_answers = [error] if stage == "lstat_before" else [before, error if stage == "lstat_after" else before]
                    with mock.patch.object(Path, "lstat", side_effect=stat_answers), \
                            mock.patch.object(resource, "open_public_binary", return_value=wrapper,
                                              side_effect=error if stage == "open" else None), \
                            mock.patch.object(resource.os, "fstat", side_effect=error if stage == "fstat" else real_fstat):
                        with self.assertRaises(resource.ProtocolReadError) as caught:
                            resource.read_public_json(path, resource.MAX_PROGRESS_BYTES)
                self.assertEqual(caught.exception.public(), {
                    "error_code": "protocol_file_read_failed",
                    "io_diagnostic": {"stage": stage, "errno": errno.EIO, "winerror": 32,
                                      "protocol_kind": "progress", "seq": 284},
                })
                self.assertNotIn("PRIVATE", json.dumps(caught.exception.public()))
                self.assertNotIn(str(path), json.dumps(caught.exception.public()))

    def test_read_error_is_preserved_when_closing_the_same_stream_also_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "event-02.json"
            path.write_bytes(b'{"synthetic_public_value":7}')
            with path.open("rb") as stream:
                wrapper = mock.Mock(wraps=stream)
                wrapper.read.side_effect = OSError(errno.EIO, "PRIVATE_READ")
                def failed_close():
                    stream.close()
                    raise OSError(errno.EBUSY, "PRIVATE_CLOSE")
                wrapper.close.side_effect = failed_close
                with mock.patch.object(resource, "open_public_binary", return_value=wrapper):
                    with self.assertRaises(resource.ProtocolReadError) as caught:
                        resource.read_public_json(path, resource.MAX_EVENT_BYTES)
            diagnostic = caught.exception.public()["io_diagnostic"]
            self.assertEqual((diagnostic["stage"], diagnostic["errno"]), ("read", errno.EIO))
            wrapper.close.assert_called_once_with()
            self.assertNotIn("PRIVATE", json.dumps(caught.exception.public()))


if __name__ == "__main__":
    unittest.main()
