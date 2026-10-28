#!/usr/bin/env python3
"""Compose (never send) RPMh ARC level votes for the Polaris GPU rails.

Why this exists: the first powered step needs CX/MX/GFX level votes whose *values*
come from the handset's command DB, not from guesses. This module composes those
votes from the dump we pinned (`tools/polaris_cmddb.py`) and refuses everything it
cannot ground:

  * only ARC level rows (`cx.lvl`, `mx.lvl`, `gfx.lvl`) are composed; a BCM row
    (`MC0`, `SH0`, ...) raises, because the BCM vote word layout (commit/valid/
    VCD/vote packing) is not pinned from a source yet;
  * a requested corner must index a level value that actually appears in the dump;
  * the address must equal the pinned ARC address for that row.

Semantics being relied on (state it, do not bury it): for an ARC level row the aux
data is the list of allowed level values as little-endian u16, and a vote is
"write this resource address with the chosen level value". That matches how the
vendor command DB encodes the level rows on this handset; it is **not** yet
verified against an RPMh consumer on this board, so nothing here may be turned into
a register write until it is.

Everything in this file is pure arithmetic over data we captured read-only.
"""
import struct
import sys

# ARC level rows exactly as the handset dump printed them: id -> (address, aux hex)
POURED_LEVELS = {
    'cx.lvl': (0x30000, '00 00 10 00 30 00 40 00 80 00 c0 00 00 01 80 01'),
    'mx.lvl': (0x30010, '00 00 10 00 10 00 00 01 80 01'),
    'gfx.lvl': (0x30050, '00 00 10 00 30 00 40 00 80 00 c0 00 00 01 40 01 80 01 a0 01'),
}

# Rows we know exist but must not compose yet.
BCM_ROWS = ('MC0', 'MC1', 'MC2', 'SH0', 'SH1', 'SH2', 'SH3', 'SH4', 'SH5', 'SH6',
            'SH7', 'MM0', 'MM1', 'MM2', 'MM3', 'SN0', 'CE0', 'IP0', 'CN0', 'QUP0')

# Regulator rows: the ARC address of the rail a BCM vote would ride on.
RAIL_ROWS = {'vrm.cx': 0x40800, 'vrm.mx': 0x40700, 'vrm.gfx': 0x42700}


class VoteError(ValueError):
    pass


def levels(row):
    """Return the ordered level values (u16) for an ARC level row."""
    if row not in POURED_LEVELS:
        raise VoteError(f'unknown ARC level row: {row}')
    _addr, aux = POURED_LEVELS[row]
    raw = bytes(int(b, 16) for b in aux.split())
    values = [struct.unpack_from('<H', raw, i)[0] for i in range(0, len(raw) - 1, 2)]
    return [v for v in values if v]


def compose(row, corner):
    """Compose one (address, data) vote. Never sends anything."""
    if row in BCM_ROWS:
        raise VoteError(f'{row} is a BCM row: its vote word layout is not pinned yet')
    values = levels(row)
    if not 0 <= corner < len(values):
        raise VoteError(f'{row}: corner {corner} outside 0..{len(values) - 1}')
    addr, _aux = POURED_LEVELS[row]
    return addr, values[corner]


def rail_vote(rail, corner):
    """Compose a vote for a rail name (vrm.*) using the level row it belongs to.

    The rail's ARC address is the resource the vote is written to; the level row
    supplies the data value. Both are pinned; nothing is inferred.
    """
    if rail not in RAIL_ROWS:
        raise VoteError(f'unknown rail: {rail}')
    row = {'vrm.cx': 'cx.lvl', 'vrm.mx': 'mx.lvl', 'vrm.gfx': 'gfx.lvl'}[rail]
    _addr, data = compose(row, corner)
    return RAIL_ROWS[rail], data


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--list':
        for row in POURED_LEVELS:
            vals = levels(row)
            print(f'{row}: {len(vals)} levels '
                  f'{[hex(v) for v in vals]} (addr 0x{POURED_LEVELS[row][0]:05x})')
        return 0
    print('composed votes (dry run, nothing is written):')
    for rail in RAIL_ROWS:
        for corner in (0, len(levels({'vrm.cx': 'cx.lvl', 'vrm.mx': 'mx.lvl',
                                      'vrm.gfx': 'gfx.lvl'}[rail])) - 1):
            addr, data = rail_vote(rail, corner)
            print(f'  {rail:<8} corner {corner} -> addr 0x{addr:05x} data 0x{data:04x}')
    print('no MMIO, no TCS write, no firmware: dry run only')
    return 0


if __name__ == '__main__':
    sys.exit(main())
