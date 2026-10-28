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

# id -> (address, level count, aux prefix as the vendor kernel prints it)
PINNED = {
    'cx.lvl': (0x30000, 7, '00 00 10 00 30 00 40 00'),
    'mx.lvl': (0x30010, 4, '00 00 10 00 10 00 00 01'),
    'gfx.lvl': (0x30050, 9, '00 00 10 00 30 00 40 00'),
    'ddr.lvl': (0x30070, 3, '00 00 20 00 80 00 a0 00'),
    'xo.lvl': (0x30080, 3, '00 00 20 00 50 00 80 00'),
    'vrm.cx': (0x40800, 0, ''),
    'vrm.mx': (0x40700, 0, ''),
    'vrm.gfx': (0x42700, 0, ''),
    'vrm.ebi': (0x40400, 0, ''),
    'MC0': (0x50000, 0, '80 84 1e 00 10 00 00 00'),
}

# SID -> context bank, from the vendor DT (documentation, not used for routing yet)
SID_MAP = ((0x208, 0x0, 'gfx3d_user'), (0x208, 0x1, 'gfx3d_secure'),
           (0x208, 0x2, 'gfx3d_secure'), (0x208, 0x4, 'gmu_user'),
           (0x208, 0x5, 'gmu_kernel'))

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
    values = [int(b, 16) for b in aux.split()]
    pairs = [(values[i] | (values[i + 1] << 8)) for i in range(0, len(values) - 1, 2)]
    return sum(1 for v in pairs if v)


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
            if levels and count_levels(got_aux) != levels:
                raise ValueError(f'{rid}: {count_levels(got_aux)} levels != {levels}')
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
        extra = f' ({levels} levels)' if levels else ''
        print(f'  {rid:<8} 0x{addr:05x}{extra}')
    print('SID -> context bank (vendor DT, informational):')
    for sid, mask, role in SID_MAP:
        print(f'  0x{sid:x} & {mask:#x} -> {role}')
    print('No MMIO, no vote, no firmware: this is a data check only.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
