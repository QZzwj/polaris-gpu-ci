#!/usr/bin/env python3
"""Offline Polaris A630 GMU firmware format gate; does not authenticate firmware.

The SDM845 MiCode TCM_BOOT path copies a flat image into GMU ITCM. HackiOS
redwood_adreno.c instead parses a660_gmu.bin as 16-byte typed blocks. Never
feed an A630 flat image to that block loader or turn these checks into writes.
"""
import struct

A630_GMU_SIZE = 32768
# The MIUI V12.5.1.0 (QDGCNXM) vendor image ships a 20 KiB flat image; the
# handset's own /vendor file is 32 KiB. Both parse as the same flat ITCM dump
# (stack vector in range, Thumb reset vector, zero tail), so the length is a
# per-firmware-set property, not a hardware constant. Anything else is refused.
A630_GMU_ACCEPTED_SIZES = (32768, 20480)
ITCM_WORDS = 0x2000
ITCM_IMAGE_BYTES = ITCM_WORDS * 4
STACK_MIN = 0x40000
STACK_MAX = 0x50000


class FirmwareFormatError(ValueError):
    pass


def check_flat_a630_gmu(data, expected_size=A630_GMU_SIZE):
    """Return ITCM byte count after bounded, device-specific vector checks."""
    if expected_size not in A630_GMU_ACCEPTED_SIZES:
        raise FirmwareFormatError('unregistered A630 GMU image length')
    if len(data) != expected_size:
        raise FirmwareFormatError('unexpected Polaris A630 GMU image size')
    stack, entry = struct.unpack_from('<II', data)
    if not STACK_MIN <= stack < STACK_MAX or stack & 3:
        raise FirmwareFormatError('invalid GMU initial stack vector')
    if not entry & 1 or (entry & ~1) >= ITCM_IMAGE_BYTES:
        raise FirmwareFormatError('GMU reset vector is not Thumb ITCM code')
    if expected_size != A630_GMU_SIZE:
        # A short image leaves part of the 0x2000-word ITCM window undefined;
        # nothing here proves the vendor loader zero-fills it.
        last = max(i for i, byte in enumerate(data) if byte) + 1
        if last > expected_size:
            raise FirmwareFormatError('GMU image data past its own length')
    # In redwood a660 each record begins address,size,type,value; at offset 0
    # that would read address=stack, size=entry. Do not reinterpret it as such.
    return expected_size
