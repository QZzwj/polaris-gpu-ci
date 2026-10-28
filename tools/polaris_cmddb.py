#!/usr/bin/env python3
"""Packaging-time gate for the Polaris A630 command-DB dump.

The kernel only carries pinned facts (xnu/patches/0095). Content validation lives
here because it needs the dump text, which XNU would have to map at boot -- and
mapping command-DB memory is exactly what forced 0092's withdrawal.

Input: the text produced by `cat /sys/kernel/debug/cmd_db` on this handset's
recovery kernel. Output: exit 0 only if every pinned row matches.
"""
import re
import sys

from polaris_arc_db import decode_arc_levels

# Ordered AUX consumer levels. Position, including OFF, is the ARC selector.
ARC_LEVELS = {
    'cx.lvl': (0, 0x10, 0x30, 0x40, 0x80, 0xc0, 0x100, 0x180),
    'mx.lvl': (0, 0x10, 0x10, 0x100, 0x180),
    'gfx.lvl': (0, 0x10, 0x30, 0x40, 0x80, 0xc0, 0x100, 0x140, 0x180, 0x1a0),
    'ddr.lvl': (0, 0x20, 0x80, 0xa0),
    'xo.lvl': (0, 0x20, 0x50, 0x80),
}

# id -> (address, selector count including OFF, AUX prefix)
PINNED = {
    'cx.lvl': (0x30000, 8, '00 00 10 00 30 00 40 00'),
    'mx.lvl': (0x30010, 5, '00 00 10 00 10 00 00 01'),
    'gfx.lvl': (0x30050, 10, '00 00 10 00 30 00 40 00'),
    'ddr.lvl': (0x30070, 4, '00 00 20 00 80 00 a0 00'),
    'xo.lvl': (0x30080, 4, '00 00 20 00 50 00 80 00'),
    'vrm.cx': (0x40800, 0, ''),
    'vrm.mx': (0x40700, 0, ''),
    'vrm.gfx': (0x42700, 0, ''),
    'vrm.ebi': (0x40400, 0, ''),
    'MC0': (0x50000, 0, '80 84 1e 00 10 00 00 00'),
}

ROW = re.compile(r'Address:\s*0x([0-9a-fA-F]+),\s*id:\s*([^,\s]+)'
                 r'(?:,\s*aux data:\s*((?:[0-9a-fA-F]{2}\s*)+))?')


def parse(text):
    rows = {}
    for line in text.splitlines():
        m = ROW.search(line)
        if not m:
            continue
        addr = int(m.group(1), 16)
        rid = m.group(2)
        aux = ' '.join((m.group(3) or '').split())
        if rid in rows:
            raise ValueError(f'duplicate command-db id: {rid}')
        rows[rid] = (addr, aux)
    if not rows:
        raise ValueError('no command-db rows parsed')
    return rows


def count_levels(aux):
    """Count hardware selectors, including OFF; omit only trailing padding."""
    return len(decode_arc_levels(bytes.fromhex(aux))) if aux else 0


def validate(text):
    rows = parse(text)
    for rid, (addr, levels, aux) in PINNED.items():
        if rid not in rows:
            raise ValueError(f'pinned row missing: {rid}')
        got_addr, got_aux = rows[rid]
        if got_addr != addr:
            raise ValueError(f'{rid}: address 0x{got_addr:x} != 0x{addr:x}')
        if aux:
            if not got_aux.startswith(aux):
                raise ValueError(f'{rid}: aux prefix {got_aux[:len(aux)]!r} != {aux!r}')
            if levels:
                decoded = tuple(decode_arc_levels(bytes.fromhex(got_aux)))
                if len(decoded) != levels:
                    raise ValueError(f'{rid}: {len(decoded)} levels != {levels}')
                if decoded != ARC_LEVELS[rid]:
                    raise ValueError(f'{rid}: ARC consumer levels differ from pinned table')
    return rows


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    text = open(sys.argv[1], encoding='utf-8', errors='replace').read()
    try:
        rows = validate(text)
    except ValueError as exc:
        print(f'command-db gate FAILED: {exc}')
        return 1
    print(f'command-db gate OK: {len(rows)} rows parsed, {len(PINNED)} pinned rows matched')
    for rid, (addr, levels, _aux) in PINNED.items():
        extra = f' ({levels} selectors including OFF)' if levels else ''
        print(f'  {rid:<8} 0x{addr:05x}{extra}')
    print('IOMMU routing is resolved separately from provider phandles by polaris_iommu.py.')
    print('No MMIO, no vote, no firmware: this is a data check only.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
