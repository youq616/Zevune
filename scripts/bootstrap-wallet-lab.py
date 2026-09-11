"""Temporary development bootstrap; removed before final read-only CI.

Applies additive modules, a reviewed source patch and pinned dependencies.
Pre-existing third-party versions/checksums may not change.
"""
import hashlib
import pathlib
import subprocess
import tomllib

root = pathlib.Path(__file__).resolve().parents[1]
module = root / "integration/orchard"

def append_exact(path, expected, suffix):
    data = path.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if blob != expected:
        raise SystemExit("bootstrap baseline changed: " + str(path.relative_to(root)))
    path.write_bytes(data.rstrip(b"\n") + b"\n" + suffix.encode())

append_exact(module / "src/lib.rs", "77500071118939b7182705fb85222a224ea6632f", "\npub mod wallet;\n")
append_exact(module / "src/pool.rs", "1cbb6bfc51f6144710bbd530965bc03ae6c3d490", '\n#[path = "wallet_history.rs"]\npub mod history;\n\n#[cfg(test)]\n#[path = "wallet_flow_tests.rs"]\nmod wallet_flow_tests;\n')
# Git checkout can give *.patch CRLF while *.rs is pinned to LF. Decode text
# once and pass canonical LF bytes; no whitespace-ignore or partial application.
patch = (root / "scripts/m8-source.patch").read_text(encoding="utf-8").encode("utf-8")
subprocess.run(["git", "apply", "--check", "-"], cwd=root, input=patch, check=True)
subprocess.run(["git", "apply", "-"], cwd=root, input=patch, check=True)
manifest = module / "Cargo.toml"
old = manifest.read_text(encoding="utf-8")
needle = 'incrementalmerkletree = "=0.8.1"\n'
if old.count(needle) != 1:
    raise SystemExit("unexpected manifest")
manifest.write_text(old.replace(needle, needle + 'argon2 = { version = "=0.5.3", default-features = false, features = ["alloc", "zeroize"] }\nchacha20poly1305 = "=0.10.1"\nzeroize = "=1.9.0"\nzip32 = "=0.2.1"\n'), encoding="utf-8", newline="\n")
lock = module / "Cargo.lock"
before = tomllib.loads(lock.read_text(encoding="utf-8"))
subprocess.run(["cargo", "metadata", "--format-version=1"], cwd=module, stdout=subprocess.DEVNULL, check=True)
after = tomllib.loads(lock.read_text(encoding="utf-8"))
keys = lambda p: (p["name"], p["version"], p.get("source", ""))
new = {keys(p): p for p in after["package"]}
for p in before["package"]:
    if not p.get("source"):
        continue
    q = new.get(keys(p))
    if q is None or any(q.get(k) != p.get(k) for k in ["name", "version", "source", "checksum"]):
        raise SystemExit("existing third-party version/checksum changed: " + p["name"])
    if not set(p.get("dependencies", [])).issubset(q.get("dependencies", [])):
        raise SystemExit("existing dependency edge removed: " + p["name"])
subprocess.run(["cargo", "fmt", "--all"], cwd=module, check=True)
print("Wallet source prepared; pre-existing third-party versions/checksums unchanged.")
