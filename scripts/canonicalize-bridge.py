"""One-time development normalization, never used by release verification.

Adds only an already-locked direct dependency to our own lockfile entry and
runs rustfmt. Third-party packages, versions, dependency lists and checksums must
remain identical. The final CI uses --locked and does not run this script.
"""
from pathlib import Path
import hashlib
import os
import subprocess
import tomllib

root = Path(__file__).resolve().parents[1]
crate = root / "integration/orchard"
lock = crate / "Cargo.lock"
before = tomllib.loads(lock.read_text())
marker = '[[package]]\nname = "zevune-orchard-lab"\n'
text = lock.read_text()
assert text.count(marker) == 1, "unexpected package lock layout"
start = text.index(marker)
end = text.find('\n[[package]]', start + len(marker))
if end == -1:
    end = len(text)
section = text[start:end]
if ' "nonempty",\n' not in section:
    assert section.count(' "orchard",\n') == 1
    section = section.replace(' "orchard",\n', ' "nonempty",\n "orchard",\n')
    lock.write_text(text[:start] + section + text[end:], newline="\n")
after = tomllib.loads(lock.read_text())
external = lambda x: [p for p in x['package'] if p['name'] != 'zevune-orchard-lab']
assert external(before) == external(after), "third-party dependency drift"
subprocess.run(['cargo', 'metadata', '--locked', '--format-version=1'], cwd=crate, stdout=subprocess.DEVNULL, check=True)
assert external(tomllib.loads(lock.read_text())) == external(before)
subprocess.run(['cargo', 'fmt', '--all'], cwd=crate, check=True)
paths = sorted([*crate.rglob('*.rs'), crate/'Cargo.toml', lock, crate/'rust-toolchain.toml'])
paths = [p for p in paths if 'target' not in p.relative_to(crate).parts]
h = hashlib.sha256()
for p in paths:
    b = p.read_bytes()
    name = p.relative_to(root).as_posix().encode()
    h.update(len(name).to_bytes(4,'big')); h.update(name)
    h.update(len(b).to_bytes(8,'big')); h.update(b)
fingerprint = h.hexdigest()
print('CANONICAL_SOURCE_SHA256=' + fingerprint)
out = os.getenv('GITHUB_OUTPUT')
if out:
    key = 'windows' if os.getenv('RUNNER_OS') == 'Windows' else 'linux'
    with open(out, 'a', encoding='utf-8') as f:
        f.write(key + '=' + fingerprint + '\n')
