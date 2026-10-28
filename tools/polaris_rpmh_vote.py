#!/usr/bin/env python3
"""Compose ARC selector requests offline. This module has no transport.

MiCode polaris-o-oss rpmh-regulator.c sends a hardware selector to the *.lvl
ARC resource. AUX data maps that selector to a consumer level. OFF and duplicate
levels retain their array indices. VRM resources use a different protocol,
including millivolt voltage requests, and are deliberately rejected here.
Resource ownership is not established by composing a request.
"""
import sys

from polaris_cmddb import ARC_LEVELS, PINNED

BCM_ROWS = ('MC0', 'MC1', 'MC2', 'SH0', 'SH1', 'SH2', 'SH3', 'SH4', 'SH5', 'SH6',
            'SH7', 'MM0', 'MM1', 'MM2', 'MM3', 'SN0', 'CE0', 'IP0', 'CN0', 'QUP0')
GPU_ROWS = ('cx.lvl', 'mx.lvl', 'gfx.lvl')


class VoteError(ValueError):
    pass


def levels(row):
    """Consumer levels in hardware-selector order, including OFF."""
    if row not in GPU_ROWS:
        if isinstance(row, str) and row.startswith('vrm.'):
            raise VoteError('VRM voltage resources cannot use ARC selectors')
        if row in BCM_ROWS:
            raise VoteError(f'{row} is a BCM row: its vote word layout is not pinned yet')
        raise VoteError(f'unknown ARC level row: {row}')
    return list(ARC_LEVELS[row])


def compose(row, selector):
    """Return (ARC resource address, hardware selector); never send it."""
    values = levels(row)
    if type(selector) is not int or not 0 <= selector < len(values):
        raise VoteError(f'{row}: selector {selector!r} outside 0..{len(values) - 1}')
    return PINNED[row][0], selector


def compose_level(row, consumer_level):
    """Choose the first supported level >= request, preserving original indices.

    Refuse unsupported requests rather than silently clamp their level. This
    offline composer is not a power policy or a regulator enable callback.
    """
    values = levels(row)
    if type(consumer_level) is not int or consumer_level < 0:
        raise VoteError('consumer level must be a nonnegative integer')
    for selector, value in enumerate(values):
        if value >= consumer_level:
            return compose(row, selector)
    raise VoteError(f'{row}: consumer level {consumer_level:#x} exceeds supported maximum')


def rail_vote(rail, selector):
    """Reject the old API which mixed VRM addresses with ARC level data."""
    raise VoteError('VRM/rail votes are unsupported; use compose() with a *.lvl ARC row')


def main():
    list_only = sys.argv[1:] == ['--list']
    print('ARC requests (offline; no hardware access):')
    for row in GPU_ROWS:
        values = levels(row)
        print(f'  {row}: {len(values)} selectors (including OFF), '
              f'consumer levels={[hex(v) for v in values]}')
        if not list_only:
            for selector in (0, len(values) - 1):
                address, data = compose(row, selector)
                print(f'    selector={selector} level={values[selector]:#x} '
                      f'-> address={address:#x} data={data:#x}')
    print('No RPMh/TCS write backend; GPU remains disabled.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
