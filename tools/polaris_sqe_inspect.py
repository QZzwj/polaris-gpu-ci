#!/usr/bin/env python3
"""Offline inspection of an Adreno SQE firmware image (read-only, no hardware).

Layout rule taken from worthdoingbadly/patch-a630: `a630_sqe.fw` is a 4-byte header
followed by flat 32-bit instruction words, so instruction index `n` lives at file
offset `n * 4 + 4`. That project patches index 0x092c of the Pixel 3 XL image to
turn a `brne` guarding `CP_SMMU_TABLE_UPDATE` into a `nop`.

This tool does not patch anything. It reports what our own image contains so the
CP stage starts from measured bytes:
  * size, header word, instruction count;
  * the first words and the word at 0x092c (the patch site in the referenced image);
  * whether the observed word matches the documented pre/post-patch encodings.

Encodings we compare against are cited, not invented:
  * pre-patch `brne` shown in patch-a630's comment: 0xc240fa26
  * the nop it writes: 0x01000000 (file bytes 00 00 00 01), i.e. LE word 0x01000000
"""
import struct
import sys

PATCH_SITE = 0x092c
PATCH_SITE_REFERENCE_WORD = 0xC240FA26
PATCH_SITE_NOP_WORD = 0x01000000


def load(path):
    data = open(path, 'rb').read()
    if len(data) < 8:
        raise ValueError('file too small to be SQE firmware')
    header = struct.unpack_from('<I', data, 0)[0]
    words = struct.unpack_from('<%dI' % ((len(data) - 4) // 4), data, 4)
    return header, words


def report(path):
    header, words = load(path)
    print(f'{path}: {len(words)} instructions, header word 0x{header:08x}')
    print('  first words:', ' '.join(f'{w:08x}' for w in words[:8]))
    if len(words) > PATCH_SITE:
        site = words[PATCH_SITE]
        print(f'  word @0x{PATCH_SITE:04x}: 0x{site:08x}')
        if site == PATCH_SITE_REFERENCE_WORD:
            print('    == the reference image\'s pre-patch brne (same firmware generation)')
        elif site == PATCH_SITE_NOP_WORD:
            print('    == the reference project\'s post-patch nop')
        else:
            print('    differs from both reference encodings; do not assume the same gate')
    else:
        print(f'  image shorter than the 0x{PATCH_SITE:04x} patch site')
    return header, words


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for path in sys.argv[1:]:
        report(path)
    print('read-only inspection; nothing patched, no hardware touched')
    return 0


if __name__ == '__main__':
    sys.exit(main())
