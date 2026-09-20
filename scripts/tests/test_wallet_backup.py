"""Catalog structure/refusal tests. Synthetic journal frames are NOT encrypted
wallets, proofs or successful authentication. Real happy paths run separately
against the unchanged Rust backend in check_wallet_backup_backend.py.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wallet_backup as b
import wallet_backup_backend as transport


def frames(count=1, marker=b"t"):
    header = b"ZVWJNL01" + marker * 64
    previous = hashlib.sha256(header).digest()
    wallet_id = previous
    data = bytearray(header)
    for number in range(1, count + 1):
        record = number.to_bytes(8, "big") + previous + marker * (b.RECORD - 72)
        previous = hashlib.sha256(record).digest()
        data.extend(record + previous)
    return bytes(data), (wallet_id + count.to_bytes(8, "big") + previous).hex()


def manifest(pin, raw):
    return {"format": "zevune-wallet-backup-1", "receipt": pin, "wallet_sha256": hashlib.sha256(raw).hexdigest(),
            "wallet_bytes": len(raw), "requires_rescan": True, "real_funds_allowed": False}


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="catalog-structure-")
        self.root = Path(self.temp.name).resolve()
        self.catalog = self.root / "catalog"
        b.init(self.catalog)
        self.raw, self.pin = frames(2)
        self.source = self.root / "source.wallet"
        self.source.write_bytes(self.raw)

    def tearDown(self):
        self.temp.cleanup()

    def entry(self, pin=None, raw=None):
        pin, raw = pin or self.pin, raw or self.raw
        path = self.catalog / b.version_id(pin)
        path.mkdir(mode=0o700)
        (path / "wallet.journal").write_bytes(raw)
        (path / "MANIFEST.json").write_bytes(b.canonical(manifest(pin, raw)))
        return path

    def test_init_is_create_only_and_private(self):
        self.assertEqual(b.list_versions(self.catalog)["versions"], [])
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.catalog.stat().st_mode), 0o700)
        old = (self.catalog / "CATALOG.json").read_bytes()
        with self.assertRaises(b.CatalogError):
            b.init(self.catalog)
        self.assertEqual((self.catalog / "CATALOG.json").read_bytes(), old)

    def test_missing_parent_is_not_automatically_created(self):
        with self.assertRaises(OSError):
            b.init(self.root / "missing" / "catalog")
        self.assertFalse((self.root / "missing").exists())

    def test_receipt_is_exact_canonical_and_version_specific(self):
        self.assertEqual(b.receipt(self.pin), self.pin)
        invalid = [None, True, "", self.pin.upper(), self.pin + "\n", "x" * 144,
                   self.pin[:64] + "0" * 16 + self.pin[80:],
                   self.pin[:64] + f"{257:016x}" + self.pin[80:]]
        for value in invalid:
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                b.receipt(value)
        self.assertEqual(len(b.version_id(self.pin)), 64)
        self.assertNotEqual(b.version_id(self.pin), b.version_id(frames(3)[1]))

    def test_public_framing_is_not_authentication(self):
        info = b.wallet_snapshot(self.source, self.pin)
        self.assertEqual(info["bytes"], len(self.raw))
        self.assertEqual(info["sha256"], hashlib.sha256(self.raw).hexdigest())
        with patch.object(b, "authenticate", side_effect=RuntimeError("native authentication required")):
            with self.assertRaises(RuntimeError):
                b.create(self.catalog, self.source, self.pin, b"unused-synthetic-input", None)
        self.assertEqual(b.list_versions(self.catalog)["versions"], [])

    def test_exact_tip_not_only_ancestor(self):
        for raw, pin in [(frames(3)[0], self.pin), (self.raw, frames(1)[1]),
                         (self.raw, frames(2, b"q")[1])]:
            self.source.write_bytes(raw)
            with self.assertRaises(ValueError):
                b.wallet_snapshot(self.source, pin)

    def test_all_public_wallet_segments_are_bound(self):
        for index in (0, 20, 72, 83, 105, 500, len(self.raw)-1):
            raw = bytearray(self.raw); raw[index] ^= 1
            self.source.write_bytes(raw)
            with self.subTest(index=index), self.assertRaises(ValueError):
                b.wallet_snapshot(self.source, self.pin)
        for raw in (b"", self.raw[:-1], self.raw+b"x"):
            self.source.write_bytes(raw)
            with self.assertRaises(ValueError):
                b.wallet_snapshot(self.source, self.pin)

    def test_listing_is_metadata_only_even_for_complete_entry(self):
        self.entry()
        data = b.list_versions(self.catalog)
        self.assertEqual(data["result"], "metadata_only")
        self.assertTrue(data["latest_not_inferred"])
        self.assertFalse(data["versions"][0]["authenticated"])
        self.assertTrue(data["versions"][0]["metadata_complete"])
        self.assertNotIn("balance", json.dumps(data))

    def test_partial_entry_retained_and_identified(self):
        folder = self.catalog / b.version_id(self.pin)
        folder.mkdir(mode=0o700)
        path = folder / "wallet.journal"; path.write_bytes(b"partial")
        data = b.list_versions(self.catalog)
        self.assertFalse(data["versions"][0]["metadata_complete"])
        self.assertEqual(path.read_bytes(), b"partial")
        with self.assertRaises(ValueError), b.Catalog(self.catalog) as catalog:
            catalog.load(self.pin)
        self.assertEqual(path.read_bytes(), b"partial")

    def test_manifest_requires_every_field_and_refuses_extras(self):
        folder = self.entry(); target = folder / "MANIFEST.json"
        good = manifest(self.pin, self.raw)
        for field in good:
            value = dict(good); del value[field]
            target.write_bytes(b.canonical(value))
            with self.subTest(field=field), self.assertRaises(ValueError), b.Catalog(self.catalog) as catalog:
                catalog.load(self.pin)
        target.write_bytes(b.canonical({**good, "secret": "SENTINEL"}))
        with self.assertRaises(ValueError), b.Catalog(self.catalog) as catalog:
            catalog.load(self.pin)

    def test_manifest_types_and_identity_are_not_advisory(self):
        folder = self.entry(); target = folder / "MANIFEST.json"
        good = manifest(self.pin, self.raw)
        for key, value in [("format", "future"), ("wallet_bytes", True), ("wallet_bytes", len(self.raw)+1),
                           ("wallet_sha256", "A"*64), ("wallet_sha256", "0"*64),
                           ("receipt", frames(3)[1]), ("requires_rescan", 1), ("real_funds_allowed", 0)]:
            target.write_bytes(b.canonical({**good, key: value}))
            with self.subTest(key=key), self.assertRaises(ValueError), b.Catalog(self.catalog) as catalog:
                catalog.load(self.pin)

    def test_json_duplicate_unknown_noncanonical_and_bounds(self):
        path = self.root / "json"
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'[]', b'{}', b'"x"', b' '*(b.MAX_MANIFEST+1), b'\xff', b'['*1500):
            path.write_bytes(raw)
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                b.json_file(path)
        path.write_bytes(b.canonical({"x": 1}))
        self.assertEqual(b.json_file(path)[0], {"x": 1})

    def test_unknown_catalog_format_and_lock_refused(self):
        path = self.catalog / "CATALOG.json"
        for data in ({"format": "future", "real_funds_allowed": False}, {**b.CATALOG, "x": 1}):
            path.write_bytes(b.canonical(data))
            with self.assertRaises(ValueError), b.Catalog(self.catalog):
                pass
        path.write_bytes(b.canonical(b.CATALOG))
        (self.catalog / ".lock").write_bytes(b"damaged!!")
        with self.assertRaises(ValueError), b.Catalog(self.catalog):
            pass

    def test_inventory_is_bounded_and_rejects_unknown_names(self):
        (self.catalog / "unknown").mkdir()
        with self.assertRaises(ValueError):
            b.list_versions(self.catalog)
        (self.catalog / "unknown").rmdir()
        for number in range(3):
            (self.catalog / f"{number:064x}").mkdir(mode=0o700)
        with patch.object(b, "MAX_ENTRIES", 2), self.assertRaises(ValueError):
            b.list_versions(self.catalog)

    def test_authentication_rejects_unknown_catalog_members_before_backend(self):
        self.entry()
        (self.catalog / "unlisted.data").write_bytes(b"retained foreign file")
        with patch.object(b, "authenticate", side_effect=AssertionError("must reject inventory first")):
            with self.assertRaises(ValueError):
                b.verify(self.catalog, self.pin, b"unused-synthetic-input", None)
            with self.assertRaises(ValueError):
                b.restore(self.catalog, self.root / "out", self.pin, b"unused-synthetic-input", None)
        self.assertFalse((self.root / "out").exists())
        self.assertEqual((self.catalog / "unlisted.data").read_bytes(), b"retained foreign file")

    def test_foreign_payload_is_not_silently_ignored(self):
        path = self.entry(); (path / "other").write_bytes(b"x")
        self.assertFalse(b.list_versions(self.catalog)["versions"][0]["metadata_complete"])
        with self.assertRaises(ValueError), b.Catalog(self.catalog) as catalog:
            catalog.load(self.pin)

    def test_bad_receipt_and_existing_target_rejected_without_backend(self):
        self.entry()
        with patch.object(b, "authenticate", side_effect=AssertionError("must not unlock")):
            for target in (self.source, self.catalog / "new"):
                with self.assertRaises(ValueError):
                    b.restore(self.catalog, target, self.pin, b"unused-test-input", None)
            with self.assertRaises(ValueError):
                b.create(self.catalog, self.source, frames(1)[1], b"unused-test-input", None)

    def test_wrong_password_failure_creates_no_target(self):
        self.entry(); target = self.root / "out"
        with patch.object(b, "authenticate", side_effect=RuntimeError("native failure")):
            with self.assertRaises(RuntimeError):
                b.restore(self.catalog, target, self.pin, b"unused-test-input", None)
        self.assertFalse(target.exists())

    def test_native_response_contract_is_strict(self):
        good = {"ok": True, "scope": "local_journal_only_no_funds", "result": "encrypted_copy_created", "receipt": self.pin}
        b.copied(good, self.pin)
        for key, value in [("ok", 1), ("scope", "remote"), ("result", "complete"), ("receipt", frames(3)[1]), ("balance", 1)]:
            with self.assertRaises(ValueError):
                b.copied({**good, key: value}, self.pin)
        with self.assertRaises(transport.BackendError):
            transport.unique([("ok", True), ("ok", True)])

    def test_lost_copy_response_retains_partial_entry(self):
        class Interrupt:
            def call(self, op, password, paths, pin):
                self.assert_op = op
                Path(paths[1]).write_bytes(b"partial")
                raise RuntimeError("reply lost, fixture is not a wallet")
        with patch.object(b, "authenticate", return_value=None):
            with self.assertRaises(RuntimeError):
                b.create(self.catalog, self.source, self.pin, b"unused-test-input", Interrupt())
        folder = self.catalog / b.version_id(self.pin)
        self.assertEqual((folder / "wallet.journal").read_bytes(), b"partial")
        self.assertFalse((folder / "MANIFEST.json").exists())
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertFalse(b.list_versions(self.catalog)["versions"][0]["metadata_complete"])

    def test_modified_source_after_authentication_refused_before_entry_creation(self):
        def changed(*args):
            self.source.write_bytes(self.raw[:-1])
        with patch.object(b, "authenticate", side_effect=changed):
            with self.assertRaises(ValueError):
                b.create(self.catalog, self.source, self.pin, b"unused-test-input", None)
        self.assertEqual(b.list_versions(self.catalog)["versions"], [])

    def test_real_process_catalog_lock_and_release(self):
        code = "import sys;sys.path.insert(0,sys.argv[1]);from pathlib import Path;from wallet_backup import Catalog\ntry:\n with Catalog(Path(sys.argv[2])): pass\nexcept (OSError,ValueError): sys.exit(7)\n"
        args = [sys.executable, "-c", code, str(Path(b.__file__).parent), str(self.catalog)]
        with b.Catalog(self.catalog):
            result = subprocess.run(args, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 7)
            self.assertFalse(result.stderr)
        result = subprocess.run(args, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.catalog / ".lock").read_bytes(), b.LOCK_BYTES)

    def test_exception_releases_os_lock_without_deleting_lockfile(self):
        with self.assertRaises(RuntimeError):
            with b.Catalog(self.catalog):
                raise RuntimeError("test-only exception")
        with b.Catalog(self.catalog):
            pass
        self.assertTrue((self.catalog / ".lock").exists())

    @unittest.skipUnless(os.name == "posix", "Unix symlink and permission case")
    def test_symlink_hardlink_and_public_catalog_refused(self):
        alias = self.root / "alias"; alias.symlink_to(self.catalog, target_is_directory=True)
        with self.assertRaises(ValueError):
            b.list_versions(alias)
        link = self.root / "hardlink"; os.link(self.source, link)
        with self.assertRaises(ValueError):
            b.wallet_snapshot(self.source, self.pin)
        link.unlink()
        self.catalog.chmod(0o755)
        with self.assertRaises(ValueError):
            b.list_versions(self.catalog)
        self.catalog.chmod(0o700)

    def test_cli_requires_pin_and_pinned_backend(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit:
            b.main(["--no-real-funds", "verify", str(self.catalog)])
        self.assertEqual(exit.exception.code, 2)

    def test_cli_metadata_never_asks_for_password(self):
        output = io.StringIO()
        with patch.object(b, "hidden_password", side_effect=AssertionError("no password")), contextlib.redirect_stdout(output):
            self.assertEqual(b.main(["--no-real-funds", "list", str(self.catalog)]), 0)
        self.assertEqual(json.loads(output.getvalue())["result"], "metadata_only")

    def test_cli_failure_is_fixed_and_does_not_echo_private_values(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(b, "list_versions", side_effect=ValueError("SECRET-PATH-SENTINEL")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(b.main(["--no-real-funds", "list", str(self.catalog)]), 1)
        self.assertNotIn("SENTINEL", err.getvalue())
        self.assertEqual(out.getvalue(), "")


class BackendBoundaryTests(unittest.TestCase):
    def test_digest_required_and_operation_allowlist(self):
        for digest in (None, "", "x" * 64, "A" * 64):
            with self.assertRaises(transport.BackendError):
                transport.Backend(Path("unused"), digest)
        backend = transport.Backend(Path("unused"), "a" * 64)
        with self.assertRaises(transport.BackendError):
            backend.call(4, b"unused-test-password", ["x"], frames()[1])

    def test_backend_wrong_digest_and_symlink_refused(self):
        with tempfile.TemporaryDirectory() as home:
            path = Path(home).resolve() / "binary"
            path.write_bytes(b"not an executable")
            backend = transport.Backend(path, "0" * 64)
            with self.assertRaises(transport.BackendError):
                backend._check()
            if os.name == "posix":
                alias = path.parent / "alias"
                alias.symlink_to(path)
                backend = transport.Backend(alias, hashlib.sha256(path.read_bytes()).hexdigest())
                with self.assertRaises(transport.BackendError):
                    backend._check()

    @unittest.skipUnless(os.name == "posix", "non-wallet POSIX process refusal fixture")
    def test_stream_limits_invalid_json_and_timeout_reject(self):
        # Deliberately non-wallet processes exercise refusal/transport only.
        # None can produce an authenticated catalog entry or spendable output.
        cases = [
            ("import sys;sys.stdin.buffer.read();sys.stdout.write('x'*16384)", 3),
            ("import sys;sys.stdin.buffer.read();sys.stderr.write('x'*4096)", 3),
            ("import sys;sys.stdin.buffer.read();print('{}')", 3),
            ("import sys;sys.stdin.buffer.read();print('{\"ok\":true,\"ok\":true}')", 3),
            ("import sys,time;sys.stdin.buffer.read();time.sleep(10)", 0.05),
        ]
        for body, timeout in cases:
            with self.subTest(timeout=timeout), tempfile.TemporaryDirectory() as home:
                path = Path(home).resolve() / "rejecting-process"
                path.write_text("#!" + sys.executable + "\n" + body + "\n")
                path.chmod(0o700)
                backend = transport.Backend(path, hashlib.sha256(path.read_bytes()).hexdigest())
                with patch.object(transport, "TIMEOUT", timeout), self.assertRaises((ValueError, RuntimeError)):
                    backend.call(9, b"unused-synthetic-password", ["unused.wallet"], frames()[1])



class StatView:
    """A metadata-query fixture, not a wallet or an authentication substitute."""
    def __init__(self, original, **changes):
        self.original = original
        self.changes = changes

    def __getattr__(self, name):
        return self.changes[name] if name in self.changes else getattr(self.original, name)


class MetadataRouteTests(unittest.TestCase):
    def test_stable_path_and_handle_timestamps_need_not_be_identical(self):
        # Cross-query timestamps are not file IDs. Each route must remain
        # unchanged relative to its OWN baseline; identity/size must still agree.
        with tempfile.TemporaryDirectory() as home:
            root = Path(home).resolve()
            path = root / "input"
            path.write_bytes(b"public metadata fixture")
            b.init(root / "catalog")
            real_fstat = os.fstat
            def handle_view(fd):
                info = real_fstat(fd)
                return StatView(info, st_mtime_ns=info.st_mtime_ns + 100,
                                st_ctime_ns=info.st_ctime_ns + 200)
            with patch.object(os, "fstat", side_effect=handle_view):
                with self.subTest(operation="read"):
                    self.assertEqual(b.read_file(path, 100)[0], b"public metadata fixture")
                with self.subTest(operation="lock"):
                    with b.Catalog(root / "catalog") as catalog:
                        catalog.check()
                with self.subTest(operation="backend"):
                    transport.Backend(path, hashlib.sha256(path.read_bytes()).hexdigest())._check()

    def test_handle_changes_still_fail_on_each_read_route(self):
        # Stable cross-route differences must not hide a change WITHIN a route.
        with tempfile.TemporaryDirectory() as home:
            path = Path(home).resolve() / "input"
            path.write_bytes(b"public metadata fixture")
            real_fstat = os.fstat
            for action in (lambda: b.read_file(path, 100),
                           lambda: transport.Backend(path, hashlib.sha256(path.read_bytes()).hexdigest())._check()):
                for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink"):
                    calls = 0
                    def changing(fd):
                        nonlocal calls
                        calls += 1
                        info = real_fstat(fd)
                        return StatView(info, **{field: getattr(info, field) + int(calls > 1)})
                    with self.subTest(field=field), patch.object(os, "fstat", side_effect=changing):
                        with self.assertRaises((ValueError, RuntimeError)):
                            action()

    def test_path_metadata_changes_are_not_ignored(self):
        with tempfile.TemporaryDirectory() as home:
            path = Path(home).resolve() / "input"
            path.write_bytes(b"public metadata fixture")
            original_lstat = Path.lstat
            for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink"):
                for backend in (False, True):
                    calls = 0
                    def changing(target, *args, **kwargs):
                        nonlocal calls
                        info = original_lstat(target, *args, **kwargs)
                        if target == path:
                            calls += 1
                            if calls > 1:
                                return StatView(info, **{field: getattr(info, field) + 1})
                        return info
                    with self.subTest(field=field, backend=backend), patch.object(Path, "lstat", new=changing):
                        with self.assertRaises((ValueError, RuntimeError)):
                            if backend:
                                transport.Backend(path, hashlib.sha256(path.read_bytes()).hexdigest())._check()
                            else:
                                b.read_file(path, 100)

    def test_lock_handle_changes_are_not_ignored(self):
        with tempfile.TemporaryDirectory() as home:
            path = Path(home).resolve() / "catalog"
            b.init(path)
            real_fstat = os.fstat
            for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink"):
                with b.Catalog(path) as catalog:
                    descriptor = catalog.lock.fileno()
                    def changing(fd):
                        info = real_fstat(fd)
                        return StatView(info, **{field: getattr(info, field) + 1}) if fd == descriptor else info
                    with self.subTest(field=field), patch.object(os, "fstat", side_effect=changing):
                        with self.assertRaises(ValueError):
                            catalog.check()

    def test_repeated_native_snapshots_and_catalog_locks(self):
        # Actual OS calls (including Windows), no patched metadata. Public field
        # names only: never log file paths, IDs, timestamps or wallet contents.
        differing = set()
        with tempfile.TemporaryDirectory() as home:
            root = Path(home).resolve()
            for number in range(64):
                path = root / str(number)
                b.write_new(path, b"public fixture")
                before = path.lstat()
                with path.open("rb") as stream:
                    opened = os.fstat(stream.fileno())
                    self.assertTrue(os.path.samestat(before, opened))
                    for field in ("st_mtime_ns", "st_ctime_ns"):
                        if getattr(before, field) != getattr(opened, field):
                            differing.add(field)
                self.assertEqual(b.read_file(path, 100)[0], b"public fixture")
                catalog_path = root / ("catalog-" + str(number))
                b.init(catalog_path)
                with b.Catalog(catalog_path) as catalog:
                    catalog.check()
        print("Native metadata route differences (field names only): " + (",".join(sorted(differing)) or "none observed"))


if __name__ == "__main__":
    unittest.main()
