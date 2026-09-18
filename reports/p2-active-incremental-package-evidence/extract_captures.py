"""Decode explicit tool text carriers without newline normalization.

This preserves the connector's decoded UTF-8 text, including BOM and CRLF. It
does not reconstruct GitHub's original compressed HTTP bytes or accept tests.
"""
import hashlib
import json
from pathlib import Path
import sys

root = Path(__file__).parent
rows = []
for argument in sys.argv[1:]:
    carrier = root / 'carriers' / argument
    value = json.loads(carrier.read_bytes())
    relative = Path(value['target_relative'])
    assert not relative.is_absolute() and '..' not in relative.parts
    target = root / relative
    raw = value['content'].encode('utf-8')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert target.read_bytes() == raw, 'Captured original may not be overwritten: ' + str(relative)
    else:
        with target.open('xb') as stream:
            stream.write(raw)
    rows.append({'path': str(relative), 'bytes': len(raw),
                 'sha256': hashlib.sha256(raw).hexdigest(),
                 'scope': value['scope']})
print(json.dumps(rows, ensure_ascii=False))
