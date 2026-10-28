#!/usr/bin/env python3
"""Parse Qualcomm command-db ARC entries from a supplied offline byte buffer.

No physical memory access, voltage votes, or device interaction. Format from
MiCode polaris-o-oss drivers/soc/qcom/cmd-db.c. AUX values are consumer levels;
their original array positions are hardware selectors. Neither is a voltage.
Caller must independently establish live source and ownership.
"""
import argparse
import struct
from pathlib import Path

MAGIC = 0x0c0330db
HEADER = 144
ENTRY = 24
SLAVE = 3
NAMES = ('gfx.lvl', 'cx.lvl', 'mx.lvl')
MAX_DB = 0x100000
MAX_ARC_BYTES = 32


class CommandDbError(ValueError):
    pass


def _u16(data, offset):
    return struct.unpack_from('<H', data, offset)[0]


def _u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def _bounded(start, count, limit):
    return 0 <= start <= limit and 0 <= count <= limit - start


def decode_arc_levels(aux):
    """Preserve OFF and duplicate selector positions; trim only tail padding."""
    if not 4 <= len(aux) <= MAX_ARC_BYTES or len(aux) % 2:
        raise CommandDbError('invalid ARC auxiliary length')
    values = struct.unpack('<' + 'H' * (len(aux) // 2), aux)
    levels = []
    terminated = False
    for index, value in enumerate(values):
        if index > 0 and value == 0:
            terminated = True
            continue
        if terminated or (levels and value < levels[-1]):
            raise CommandDbError('nonmonotonic ARC levels or nonzero padding')
        levels.append(value)
    if not levels or not any(levels):
        raise CommandDbError('empty ARC levels')
    return levels


def parse_arc(data):
    """Return {resource: {address, levels, priority, aux_version}} or fail."""
    if not HEADER <= len(data) <= MAX_DB or _u32(data, 4) != MAGIC:
        raise CommandDbError('invalid command-db length or magic')
    if _u32(data, 0) != 1 or _u32(data, 140) & 1:
        raise CommandDbError('unsupported command-db version or standalone mode')
    found = {}
    for slot in range(8):
        h = 8 + slot * 16
        slave, head_off, aux_off, count, version = struct.unpack_from('<5H', data, h)
        if slave == 0:
            break
        if count > MAX_DB // ENTRY:
            raise CommandDbError('excess command-db entries')
        entry_start = HEADER + head_off
        aux_start = HEADER + aux_off
        if entry_start % 4 or not _bounded(entry_start, count * ENTRY, len(data)) or \
                not _bounded(aux_start, 0, len(data)):
            raise CommandDbError('malformed command-db resource header')
        for j in range(count):
            p = entry_start + j * ENTRY
            raw = data[p:p + 8]
            if raw.split(b'\0')[0] not in (n.encode() for n in NAMES):
                continue
            name = raw.split(b'\0')[0].decode('ascii')
            if raw != name.encode().ljust(8, b'\0') or name in found:
                raise CommandDbError('noncanonical or duplicate ARC resource')
            address = _u32(data, p + 16)
            length, offset = struct.unpack_from('<2H', data, p + 20)
            start = aux_start + offset
            if slave != SLAVE or (address >> 16) & 7 != SLAVE or \
                    (address >> 16) != SLAVE or length < 4 or \
                    length > MAX_ARC_BYTES or length & 1 or not _bounded(start, length, len(data)):
                raise CommandDbError(f'invalid ARC entry for {name}')
            levels = decode_arc_levels(data[start:start + length])
            found[name] = dict(address=address, levels=levels,
                               priority=(_u32(data, p + 8), _u32(data, p + 12)),
                               aux_version=version)
    if set(found) != set(NAMES):
        raise CommandDbError('missing ARC resources: ' + ', '.join(sorted(set(NAMES) - set(found))))
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path, help='explicit offline command-db image')
    args = parser.parse_args()
    try:
        entries = parse_arc(args.database.read_bytes())
    except (OSError, CommandDbError) as exc:
        parser.error(str(exc))
    for name in NAMES:
        item = entries[name]
        print(name, f"address={item['address']:#x}",
              f"aux_version={item['aux_version']:#x}",
              f"levels={item['levels']}", f"priority={item['priority']}")
    print('AUX entries are consumer levels; positions are hardware selectors. No vote is sent.')


if __name__ == '__main__':
    main()
