#!/usr/bin/env python3
"""Host-side reference model for the Polaris A630 handoff gate (XNU 0094).

Pure functions only: no MMIO, no firmware execution, no clock or rail votes.
`xnu/patches/0094-polaris-gpu-handoff-validation.patch` implements the same
arithmetic in C; this model exists so the rules are testable on a host where no
Apple toolchain exists.

Two different things are modelled and must not be conflated:

* validation of what the boot loader handed over (ADT identity, DRAM window,
  firmware blob ranges, reserved-memory exclusions) -- read-only, and
* the ownership ledger, which records whether *we* acquired a resource or only
  observed somebody else's. Observing PWR_ON is never ownership.
"""
import struct
from dataclasses import dataclass, field

PAGE = 0x4000
ZAP_BASE, ZAP_SIZE = 0x8c415000, 0x2000
SPLASH_BASE, SPLASH_SIZE = 0x9d400000, 0x2400000
U64_MAX = (1 << 64) - 1

REQUIRED_IDENTITIES = ('xiaomi,polaris', 'qcom,sdm845')

# ADT memory-map names, in the order the diagnostic prints them.
BLOB_NAMES = ('GPU-SQE', 'GPU-GMU', 'GPU-ZAP-MDT', 'GPU-ZAP-B00', 'GPU-ZAP-B01',
              'GPU-ZAP-B02')

# Registered firmware sets: name -> ((size per BLOB_NAMES), note).
# Lengths only. Hash binding stays in tools/polaris_gpu_preflight.py because the
# kernel has no SHA-256 and must not grow one just to gate a bring-up.
FIRMWARE_SETS = {
    'device-2026-10-22': ((32136, 32768, 6684, 148, 6536, 1968),
                          'this handset /vendor readback'),
    'miui-v12.5.1.0-qdgcnxm-20210707': ((31980, 20480, 6684, 148, 6536, 1968),
                                        'official ROM vendor.img (older)'),
}


class HandoffError(ValueError):
    pass


@dataclass(frozen=True)
class Blob:
    name: str
    addr: int
    size: int

    @property
    def reserve(self):
        return round_up(self.size, PAGE)


@dataclass(frozen=True)
class Handoff:
    """Immutable result of a successful validation."""
    set_name: str
    set_note: str
    dram_base: int
    dram_size: int
    blobs: tuple
    reserved: tuple = ((ZAP_BASE, ZAP_SIZE), (SPLASH_BASE, SPLASH_SIZE))

    def blob(self, name):
        for b in self.blobs:
            if b.name == name:
                return b
        raise KeyError(name)


def round_up(value, align):
    if value > U64_MAX - (align - 1):
        raise HandoffError('size overflow')
    return (value + align - 1) & ~(align - 1)


def overlaps(a, n, b, m):
    return a < b + m and b < a + n


def match_set(sizes):
    """Return (name, note) for an exact registered length vector, else raise."""
    key = tuple(sizes)
    for name, (want, note) in FIRMWARE_SETS.items():
        if key == want:
            return name, note
    raise HandoffError(f'unregistered firmware length vector {key}')


def validate_handoff(identities, dram_base, dram_size, blobs,
                     reserved=((ZAP_BASE, ZAP_SIZE), (SPLASH_BASE, SPLASH_SIZE))):
    """Fail closed on anything unexpected. Read-only by construction."""
    have = set(identities)
    for want in REQUIRED_IDENTITIES:
        if want not in have:
            raise HandoffError(f'missing board identity {want}')
    if not dram_size:
        raise HandoffError('empty XNU managed RAM')
    if dram_base > U64_MAX - dram_size:
        raise HandoffError('DRAM range overflows 64 bits')
    for base, size in reserved:
        if overlaps(dram_base, dram_size, base, size):
            raise HandoffError(f'managed RAM overlaps reserved 0x{base:x}')
    ordered = [Blob(*entry) for entry in blobs]
    names = tuple(b.name for b in ordered)
    if names != BLOB_NAMES:
        raise HandoffError(f'unexpected firmware list {names}')
    set_name, note = match_set(b.size for b in ordered)
    seen = []
    for blob in ordered:
        if blob.addr & (PAGE - 1):
            raise HandoffError(f'{blob.name} is not {PAGE:#x}-aligned')
        if blob.addr < dram_base or blob.addr > dram_base + dram_size:
            raise HandoffError(f'{blob.name} lies outside managed RAM')
        reserve = blob.reserve
        if reserve > dram_base + dram_size - blob.addr:
            raise HandoffError(f'{blob.name} extends past managed RAM')
        for base, size in reserved:
            if overlaps(blob.addr, reserve, base, size):
                raise HandoffError(f'{blob.name} collides with reserved 0x{base:x}')
        for other, other_reserve in seen:
            if overlaps(blob.addr, reserve, other, other_reserve):
                raise HandoffError(f'{blob.name} overlaps {other:#x}')
        seen.append((blob.addr, reserve))
    return Handoff(set_name, note, dram_base, dram_size, tuple(ordered), tuple(reserved))


# --- ownership ledger -------------------------------------------------------

UNKNOWN, OBSERVED_FOREIGN, ACQUIRED_BY_US = 'unknown', 'observed-foreign', 'acquired-by-us'


@dataclass
class Entry:
    state: str = UNKNOWN
    readback: object = None
    released: bool = False


@dataclass
class Ledger:
    """Only an ACQUIRED_BY_US entry may be released, and only after quiesce."""
    entries: dict = field(default_factory=dict)
    quarantined: bool = False

    def record(self, name, state):
        if state not in (UNKNOWN, OBSERVED_FOREIGN, ACQUIRED_BY_US):
            raise HandoffError(f'bad ledger state {state}')
        self.entries[name] = Entry(state=state)

    def acquire(self, name, ack, readback, expected):
        """Acquire only with a completed transaction AND a matching readback."""
        if self.quarantined:
            raise HandoffError('ledger quarantined until reboot')
        if not ack or readback != expected:
            self.entries[name] = Entry(state=UNKNOWN, readback=readback)
            self.quarantined = True
            raise HandoffError(f'{name} not acquired; quarantined until reboot')
        self.entries[name] = Entry(state=ACQUIRED_BY_US, readback=readback)
        return True

    def release(self, name, quiesced):
        entry = self.entries.get(name)
        if entry is None or entry.state != ACQUIRED_BY_US:
            raise HandoffError(f'{name} is not owned; release refused')
        if not quiesced:
            self.quarantined = True
            raise HandoffError(f'{name} may still be busy; quarantined')
        if entry.released:
            raise HandoffError(f'{name} released twice')
        entry.released = True
        return True

    def owned(self):
        return tuple(n for n, e in self.entries.items()
                     if e.state == ACQUIRED_BY_US and not e.released)


def parse_memory_map(raw):
    """Parse ADT-style <2Q> memory-map entries into (name, addr, size) tuples."""
    out = []
    for name, value in raw.items():
        if len(value) != 16:
            raise HandoffError(f'{name}: memory-map entry is not two u64s')
        addr, size = struct.unpack('<2Q', value)
        out.append((name, addr, size))
    return out
