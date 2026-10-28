"""Host-only fail-closed tests for Polaris A630 firmware layout checks."""
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import polaris_gpu_preflight as gpu
import adt

# Structural tests fabricate bytes, so they run with hash verification off; the
# hash gate has its own test below.
DEVICE_SIZES = {key: gpu.FIRMWARE_SETS['device-2026-10-22']['files'][filename][0]
                for key, filename in gpu.BLOBS}


class PolarisGpuPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        header = bytearray(52 + 32)
        header[:6] = b'\x7fELF\x01\x01'
        struct.pack_into('<I', header, 28, 52)
        struct.pack_into('<HH', header, 42, 32, 1)
        struct.pack_into('<8I', header, 52, 1, 0x3000, 0x5000,
                         0x5000, DEVICE_SIZES['GPU-ZAP-B02'],
                         DEVICE_SIZES['GPU-ZAP-B02'], 0x8000007, 0x100000)
        for key, name in gpu.BLOBS:
            length = DEVICE_SIZES[key]
            content = bytes(header) + bytes(length - len(header)) if name.endswith('.mdt') else bytes(length)
            if key == 'GPU-GMU':
                content = struct.pack('<II', 0x43f80, 9) + content[8:]
            (self.root / name).write_bytes(content)

    def test_valid_and_rejects_corrupt_segment(self):
        gpu.check_firmware(self.root, verify_hashes=False)
        (self.root / 'a630_zap.b02').write_bytes(b'BAD')
        with self.assertRaisesRegex(ValueError, 'not registered'):
            gpu.check_firmware(self.root, verify_hashes=False)

    def test_rejects_wrong_gmu_length(self):
        (self.root / 'a630_gmu.bin').write_bytes(b'wrong')
        with self.assertRaisesRegex(ValueError, 'not registered'):
            gpu.check_firmware(self.root, verify_hashes=False)

    def test_rejects_unregistered_length_vector(self):
        # 20 KiB GMU belongs to the registered MIUI set, 16 KiB belongs nowhere.
        (self.root / 'a630_gmu.bin').write_bytes(bytes(16384))
        with self.assertRaisesRegex(ValueError, 'not registered'):
            gpu.check_firmware(self.root, verify_hashes=False)

    def test_hash_gate_rejects_fabricated_content(self):
        # Same lengths as the handset set, wrong bytes: must refuse.
        with self.assertRaisesRegex(ValueError, 'does not match the recorded hash'):
            gpu.check_firmware(self.root)

    def test_rejects_bad_header_and_missing_segment(self):
        meta = self.root / 'a630_zap.mdt'
        data = bytearray(meta.read_bytes())
        struct.pack_into('<I', data, 28, len(data) - 4)
        meta.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'out of bounds'):
            gpu.check_firmware(self.root, verify_hashes=False)
        meta.unlink()
        with self.assertRaisesRegex(ValueError, 'missing or nonregular'):
            gpu.check_firmware(self.root, verify_hashes=False)

    def test_rejects_overlap_and_oversize_without_writing(self):
        files = gpu.check_firmware(self.root, verify_hashes=False)
        root = adt.Node()
        root.props.append(('name', 0, b'/\0'))
        chosen = adt.Node()
        chosen.props.extend([('name', 0, b'chosen\0'),
                             ('dram-base', 0, struct.pack('<Q', gpu.ZAP_BASE)),
                             ('dram-size', 0, struct.pack('<Q', gpu.ZAP_SIZE))])
        root.children.append(chosen)
        tree = self.root / 'overlap.adt'
        tree.write_bytes(adt.serialize(root))
        with patch.object(gpu.mkpayload, 'build', side_effect=AssertionError('must not pack')):
            with self.assertRaisesRegex(ValueError, 'overlaps zap'):
                gpu.check_layout('unused-kernel', tree, 'debug=0', files)
        chosen.props = [(name, flags,
                         struct.pack('<Q', 0x100000000) if name == 'dram-base' else val)
                        for name, flags, val in chosen.props]
        tree.write_bytes(adt.serialize(root))
        with patch.object(gpu.mkpayload, 'build', return_value=(b'x' * (gpu.MAX_PAYLOAD_SIZE + 1), {})):
            with self.assertRaisesRegex(ValueError, 'exceeds ABL gap'):
                gpu.check_layout('unused-kernel', tree, 'debug=0', files)


if __name__ == '__main__':
    unittest.main()
