#!/usr/bin/env python3
"""Offline, fail-closed Polaris A630 firmware and payload preflight.

The reserved-memory addresses and ABL limit are from this handset's recovery
DT/0090 boot layout, not generic SDM845 constants. No firmware is executed.
"""
import argparse
import hashlib
import struct
from pathlib import Path

import adt
import mkpayload
from polaris_gmu_firmware import check_flat_a630_gmu

PAGE = 0x4000
ZAP_BASE, ZAP_SIZE = 0x8c415000, 0x2000
SPLASH_BASE, SPLASH_SIZE = 0x9d400000, 0x2400000
MAX_PAYLOAD_SIZE = 0x1dea000 - 0x1000000
BLOBS = (
    ('GPU-SQE', 'a630_sqe.fw'), ('GPU-GMU', 'a630_gmu.bin'),
    ('GPU-ZAP-MDT', 'a630_zap.mdt'), ('GPU-ZAP-B00', 'a630_zap.b00'),
    ('GPU-ZAP-B01', 'a630_zap.b01'), ('GPU-ZAP-B02', 'a630_zap.b02'),
)
# Every accepted firmware set is listed explicitly: unknown combinations are
# refused, never inferred from sizes alone when a hash is known.
#   device-2026-10-22 : read-only copy taken from this handset's /vendor in
#     recovery. Hash recorded for SQE/GMU/MDT only; the three ZAP segments were
#     logged by size, so they stay size-only here and must not be treated as
#     identity.
#   miui-v12.5.1.0-qdgcnxm-20210707 : extracted from the official fastboot ROM
#     images/vendor.img (a630_* in /firmware). All six files bound by hash.
#     This set is OLDER than this handset's vendor partition, so it is a second
#     variable in any bring-up result and cannot be described as "the phone's
#     firmware".
FIRMWARE_SETS = {
    'device-2026-10-22': {
        'provenance': 'recovery read-only copy from this handset /vendor/firmware',
        'files': {
            'a630_sqe.fw': (32136, '36298bd53ea3666413d288a3a3f5266f67fcb6db038a0a481af5869d1c17859c'),
            'a630_gmu.bin': (32768, 'b07f90299ff2ae33948fcfd6ed67f53fbd287b5bf85ff2d43db11d4d32c1621f'),
            'a630_zap.mdt': (6684, 'e1e11d7f124b53efe73c2b03fab613fc1075d4caa5f41f6a19dc2ac56ea736dd'),
            'a630_zap.b00': (148, None),
            'a630_zap.b01': (6536, None),
            'a630_zap.b02': (1968, None),
        },
    },
    'miui-v12.5.1.0-qdgcnxm-20210707': {
        'provenance': 'official fastboot ROM images/vendor.img /firmware (older than device vendor)',
        'files': {
            'a630_sqe.fw': (31980, '34edacb6fdedfbfc07ed5cd1d29b0b57a3543ef5be6ab34a43bd64686826fa1e'),
            'a630_gmu.bin': (20480, '894ae5550352d2d12596dc6d4b65af628307cf2c6adc5d112e6f5c9ffcd4ec11'),
            'a630_zap.mdt': (6684, '1882b214d24c13eae4ffc39ba5456d5e61c80b089fb77e8b15f7bdd04bc9c831'),
            'a630_zap.b00': (148, 'b2975f6a4c28a98197c1d694f6e275e71b23ec7e31e32ff5d1f83fdb80a94282'),
            'a630_zap.b01': (6536, 'c94da0d6edf4820885b814ecda2f91c89b9d766126c3574c05d580c418815b5f'),
            'a630_zap.b02': (1968, '519b5538809f54ee566246b0520746a8ea82ca9384ea6bddb0b0e0d3c2de520c'),
        },
    },
}


def _match_sizes(sizes):
    """Return the registered set whose length vector equals `sizes`, else None."""
    key = tuple(sizes)
    for set_name, entry in FIRMWARE_SETS.items():
        if tuple(entry['files'][filename][0] for _, filename in BLOBS) == key:
            return set_name
    return None


def check_firmware(folder, verify_hashes=True):
    """Stage 1: registered length vector, structure, then recorded hashes."""
    files = {}
    digests = {}
    for name, filename in BLOBS:
        path = folder / filename
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'missing or nonregular firmware: {filename}')
        data = path.read_bytes()
        files[name] = (path, data)
        digests[filename] = (len(data), hashlib.sha256(data).hexdigest())
    set_name = _match_sizes([digests[filename][0] for _, filename in BLOBS])
    if set_name is None:
        detail = ', '.join(f'{fn}={size}B/{digest[:12]}'
                           for fn, (size, digest) in digests.items())
        raise ValueError(f'firmware length vector is not registered; refusing ({detail})')
    provenance = FIRMWARE_SETS[set_name]['provenance']
    print(f'firmware set: {set_name} ({provenance})')
    gmu_size = FIRMWARE_SETS[set_name]['files']['a630_gmu.bin'][0]
    if gmu_size != 32768:
        print(f'  WARNING: GMU image is {gmu_size} bytes, not the 32 KiB image '
              f'this handset ships; the undefined ITCM tail is unproven')
    check_flat_a630_gmu(files['GPU-GMU'][1], expected_size=gmu_size)
    meta = files['GPU-ZAP-MDT'][1]
    if len(meta) < 52 or meta[:6] != b'\x7fELF\x01\x01':
        raise ValueError('zap metadata is not little-endian ELF32')
    phoff, = struct.unpack_from('<I', meta, 28)
    entsz, n = struct.unpack_from('<HH', meta, 42)
    if entsz != 32 or not 0 < n <= 32 or phoff + n * entsz > len(meta):
        raise ValueError('zap program headers out of bounds')
    loads = []
    for i in range(n):
        kind, _, _, addr, file_size, mem_size, flags, _ = struct.unpack_from(
            '<8I', meta, phoff + i * entsz)
        if kind == 1 and ((flags >> 24) & 7) != 2 and mem_size:
            loads.append((addr, file_size, mem_size))
    if len(loads) != 1:
        raise ValueError('expected one non-hash zap load segment')
    addr, file_size, mem_size = loads[0]
    if addr != 0x5000 or file_size != len(files['GPU-ZAP-B02'][1]) or \
            mem_size < file_size or mem_size > ZAP_SIZE:
        raise ValueError('zap load segment does not match this Polaris reservation')
    # Stage 3: content identity. Structure alone never pins a firmware version.
    if verify_hashes:
        for name, filename in BLOBS:
            want = FIRMWARE_SETS[set_name]['files'][filename][1]
            if want is None:
                print(f'  WARNING: {filename} has no recorded hash for this set; '
                      f'the match is size-only')
            elif digests[filename][1] != want:
                raise ValueError(f'{filename} content does not match the recorded '
                                 f'hash for {set_name}')
    return files


def overlap(base, size, other, other_size):
    return base < other + other_size and other < base + size


def check_layout(kernel, tree, cmdline, files):
    raw = tree.read_bytes()
    root, end = adt.parse(raw)
    if end != len(raw):
        raise ValueError('ADT has trailing bytes')
    chosen = next(c for c in root.children if c.name == 'chosen')
    base, size = (struct.unpack('<Q', chosen.prop(n))[0]
                  for n in ('dram-base', 'dram-size'))
    if not size or base + size > 1 << 64:
        raise ValueError('invalid XNU managed RAM range')
    for label, addr, length in (('zap', ZAP_BASE, ZAP_SIZE),
                                ('splash', SPLASH_BASE, SPLASH_SIZE)):
        if overlap(base, size, addr, length):
            raise ValueError(f'XNU managed RAM overlaps {label} reserved memory')
    image, _ = mkpayload.build(kernel, tree, cmdline,
                                blobs=[(name, str(files[name][0])) for name, _ in BLOBS])
    if len(image) > MAX_PAYLOAD_SIZE:
        raise ValueError(f'payload {len(image)} exceeds ABL gap {MAX_PAYLOAD_SIZE}')
    adt_off, adt_size = struct.unpack_from('<2Q', image, 0x20)
    packed, _ = adt.parse(image[adt_off:adt_off + adt_size])
    packed_chosen = next(c for c in packed.children if c.name == 'chosen')
    memory_map = next(c for c in packed_chosen.children if c.name == 'memory-map')
    intervals = []
    for name, _ in BLOBS:
        value = memory_map.prop(name)
        if value is None or len(value) != 16:
            raise ValueError(f'missing ADT entry: {name}')
        addr, length = struct.unpack('<2Q', value)
        reserved = (length + PAGE - 1) & ~(PAGE - 1)
        if length != len(files[name][1]) or addr & (PAGE - 1) or \
                addr < base or addr + reserved > base + size:
            raise ValueError(f'invalid ADT firmware allocation: {name}')
        if any(overlap(addr, reserved, a, s) for a, s in intervals):
            raise ValueError(f'overlapping firmware allocations: {name}')
        intervals.append((addr, reserved))
    return len(image), MAX_PAYLOAD_SIZE - len(image)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('firmware_dir', type=Path)
    parser.add_argument('kernel', type=Path)
    parser.add_argument('adt', type=Path)
    parser.add_argument('--cmdline', required=True)
    args = parser.parse_args()
    try:
        files = check_firmware(args.firmware_dir)
        used, remaining = check_layout(args.kernel, args.adt, args.cmdline, files)
    except (ValueError, OSError, AssertionError, StopIteration, struct.error) as exc:
        parser.error(str(exc))
    for name, _ in BLOBS:
        print(f'{name}: {len(files[name][1])} bytes '
              f'sha256={hashlib.sha256(files[name][1]).hexdigest()}')
    print(f'layout verified: payload={used} bytes, ABL gap remaining={remaining} bytes')
    print('No GPU power, secure PAS, HFI, SMMU, rendering, or boot was tested.')


if __name__ == '__main__':
    main()
