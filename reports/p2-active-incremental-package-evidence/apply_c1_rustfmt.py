"""Apply only exact, unique rustfmt replacements from the preserved C1 job."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path('/workspace/scratch/1753b04c9dbb/Zevune')
HERE = Path(__file__).parent
C1 = '61c691270b91aece076177cb757e51e0e63fe310'
raw = (HERE / 'c1-native/job-105656510131.log').read_bytes()
assert hashlib.sha256(raw).hexdigest() == '247217a4771742d0e14f66222cc6e9657d1969e290c3052272a44c9e5a927080'
text = re.sub(r'^\d{4}-\d\d-\d\dT\S+ ', '', raw.decode('utf-8-sig'), flags=re.M)
start = text.index('Diff in ')
end = text.index('##[error]', start)
parts = re.split(r'^Diff in /home/runner/work/Zevune/Zevune/([^\n]+):(\d+):\n', text[start:end], flags=re.M)
assert parts[0] == '' and (len(parts) - 1) // 3 == 30
before, after, counts = {}, {}, {}
def tokens(value):
    # rustfmt also wraps multiline closure bodies and adds trailing commas.
    # This is an extra guard, not a claim of semantic equivalence by parsing.
    return re.sub(r'[\s{},]+', '', value)

for offset in range(1, len(parts), 3):
    name, line, body = parts[offset:offset + 3]
    assert name.startswith('integration/orchard/') and name.endswith('.rs')
    if name not in before:
        original = subprocess.check_output(['git', 'show', C1 + ':' + name], cwd=ROOT)
        assert (ROOT / name).read_bytes() == original
        before[name] = original.decode()
        after[name] = before[name]
    lines = body.splitlines()
    while lines and lines[-1] == '':
        lines.pop()
    assert lines and all(line and line[0] in ' +-' for line in lines)
    old = ''.join(line[1:] + '\n' for line in lines if line[0] in ' -')
    new = ''.join(line[1:] + '\n' for line in lines if line[0] in ' +')
    assert after[name].count(old) == 1, (name, line, old)
    assert tokens(old) == tokens(new), (name, line)
    after[name] = after[name].replace(old, new, 1)
    counts[name] = counts.get(name, 0) + 1
assert len(after) == 7 and sum(counts.values()) == 30
rows = []
for name, value in after.items():
    assert tokens(value) == tokens(before[name])
    rows.append({'path': name, 'hunks': counts[name],
                 'before_sha256': hashlib.sha256(before[name].encode()).hexdigest(),
                 'after_sha256': hashlib.sha256(value.encode()).hexdigest()})
for name, value in after.items():
    (ROOT / name).write_bytes(value.encode())
result = {'candidate': C1, 'source_log': 'c1-native/job-105656510131.log',
          'files': rows, 'total_hunks': 30,
          'scope': 'Derived exact rustfmt replacements; no local Rust execution or acceptance.'}
target = HERE / 'c1-rustfmt-repairs.json'
assert not target.exists()
target.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
