"""Host tests for the ARC vote composer: pure data, no hardware."""
import unittest

import polaris_rpmh_vote as v


class VoteTests(unittest.TestCase):
    def test_levels_match_the_handset_dump(self):
        self.assertEqual(v.levels('cx.lvl'), [0x10, 0x30, 0x40, 0x80, 0xc0, 0x100, 0x180])
        self.assertEqual(v.levels('mx.lvl'), [0x10, 0x10, 0x100, 0x180])
        self.assertEqual(v.levels('gfx.lvl'),
                         [0x10, 0x30, 0x40, 0x80, 0xc0, 0x100, 0x140, 0x180, 0x1a0])

    def test_gfx_has_nine_levels_not_seven_frequencies(self):
        # 7 KGSL frequencies, 9 ARC levels: the composer must not conflate them.
        self.assertEqual(len(v.levels('gfx.lvl')), 9)

    def test_compose_returns_pinned_address_and_value(self):
        addr, data = v.compose('gfx.lvl', 0)
        self.assertEqual(addr, 0x30050)
        self.assertEqual(data, 0x10)
        addr, data = v.compose('gfx.lvl', 8)
        self.assertEqual(data, 0x1a0)

    def test_corner_out_of_range_refused(self):
        with self.assertRaisesRegex(v.VoteError, 'outside'):
            v.compose('cx.lvl', 7)
        with self.assertRaisesRegex(v.VoteError, 'outside'):
            v.compose('mx.lvl', 4)

    def test_bcm_rows_refused_until_layout_is_pinned(self):
        for row in ('MC0', 'SH0', 'CN0'):
            with self.assertRaisesRegex(v.VoteError, 'BCM row'):
                v.compose(row, 0)

    def test_unknown_row_and_rail_refused(self):
        with self.assertRaisesRegex(v.VoteError, 'unknown ARC level row'):
            v.compose('lcx.lvl', 0)
        with self.assertRaisesRegex(v.VoteError, 'unknown rail'):
            v.rail_vote('vrm.ebi', 0)

    def test_rail_vote_uses_pinned_rail_address(self):
        self.assertEqual(v.rail_vote('vrm.cx', 0), (0x40800, 0x10))
        self.assertEqual(v.rail_vote('vrm.gfx', 8), (0x42700, 0x1a0))

    def test_no_write_api_exists(self):
        # Guard against a future "convenience" that actually sends the vote.
        for name in dir(v):
            self.assertNotIn(name.lower(), ('write', 'send', 'submit', 'vote_now'))


if __name__ == '__main__':
    unittest.main()
