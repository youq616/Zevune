"""Independent public-field hash vectors; not proof verification or wallet data."""
import hashlib
import json
from pathlib import Path
import unittest


class ProtocolTranscriptVectors(unittest.TestCase):
    def test_legacy_and_genesis_bound_reference_vectors(self):
        path = Path(__file__).resolve().parents[2] / 'docs/protocol/signing-domain-vectors.json'
        vectors = json.loads(path.read_text(encoding='utf-8'))['vectors']
        self.assertEqual([v['name'] for v in vectors], ['legacy', 'bound'])
        digests = []
        for vector in vectors:
            domain = None if vector['domain'] is None else bytes.fromhex(vector['domain'])
            message = b'ZEVUNE-ORCHARD-LAB-SIGHASH\0'
            message += b'\x01' if domain is None else b'\x02' + domain
            network = b'zevune-orchard-lab-1'
            message += len(network).to_bytes(2, 'big') + network
            message += vector['expiry'].to_bytes(8, 'big') + vector['fee'].to_bytes(8, 'big')
            message += bytes.fromhex(vector['bundle_commitment'])
            self.assertEqual(message.hex(), vector['preimage'])
            self.assertEqual(hashlib.sha256(message).hexdigest(), vector['sha256'])
            digests.append(vector['sha256'])
        self.assertNotEqual(*digests)

    def test_declared_wire_and_manifest_resource_bounds(self):
        self.assertEqual(66 + 2 * 884 + (2720 + 2272 * 2) + 68, 9166)
        self.assertEqual(98 + 8 * 884 + (2720 + 2272 * 8) + 68, 28134)
        self.assertEqual(82 + 16 * 115, 1922)
        self.assertLess(114 + 16 * (4 + 28134) + 36, 512 * 1024)


if __name__ == '__main__':
    unittest.main()
