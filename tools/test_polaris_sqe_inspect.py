"""Host tests for the SQE inspector (synthetic images only)."""
import struct
import tempfile
import unittest
from pathlib import Path

import polaris_sqe_inspect as sqe


def make_image(words, header=0, at_site=None):
    count = max(len(words), sqe.PATCH_SITE + 1 if at_site is not None else 0)
    buf = [0] * count
    for i, w in enumerate(words):
        buf[i] = w
    if at_site is not None:
        buf[sqe.PATCH_SITE] = at_site
    data = struct.pack('<I', header) + struct.pack('<%dI' % count, *buf)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.fw')
    tmp.write(data)
    tmp.close()
    return Path(tmp.name)


class SqeTests(unittest.TestCase):
    def test_instruction_count_and_header(self):
        p = make_image([0x11223344, 0x55667788], header=0xdeadbeef)
        header, words = sqe.load(p)
        self.assertEqual(header, 0xdeadbeef)
        self.assertEqual(len(words), 2)
        self.assertEqual(words[0], 0x11223344)

    def test_reference_prepatch_word_is_recognised(self):
        p = make_image([], at_site=sqe.PATCH_SITE_REFERENCE_WORD)
        _h, _w = sqe.report(str(p))
        _h, words = sqe.load(p)
        self.assertEqual(words[sqe.PATCH_SITE], 0xC240FA26)

    def test_unknown_site_word_is_not_assumed(self):
        p = make_image([], at_site=0x0A2921FC)
        _h, words = sqe.load(p)
        self.assertNotIn(words[sqe.PATCH_SITE],
                         (sqe.PATCH_SITE_REFERENCE_WORD, sqe.PATCH_SITE_NOP_WORD))

    def test_short_image_handled(self):
        p = make_image([0x1, 0x2])
        header, words = sqe.load(p)
        self.assertEqual(header, 0)
        self.assertLess(len(words), sqe.PATCH_SITE)

    def test_offsets_follow_the_reference_rule(self):
        # instruction index n -> file offset n*4+4
        self.assertEqual(sqe.PATCH_SITE * 4 + 4, 0x24B4)


if __name__ == '__main__':
    unittest.main()
