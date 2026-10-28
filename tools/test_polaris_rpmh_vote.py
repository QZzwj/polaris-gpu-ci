"""ARC protocol regression tests, grounded in the Polaris vendor consumer."""
import unittest

import polaris_rpmh_vote as v


class VoteTests(unittest.TestCase):
    def test_off_keeps_hardware_selector_zero(self):
        self.assertEqual(v.levels('gfx.lvl')[0], 0)
        self.assertEqual(v.compose('gfx.lvl', 0), (0x30050, 0))
        self.assertEqual(v.compose_level('gfx.lvl', 0), (0x30050, 0))

    def test_request_uses_selector_not_aux_level(self):
        self.assertEqual(v.compose('gfx.lvl', 1), (0x30050, 1))
        self.assertEqual(v.compose_level('gfx.lvl', 0x10), (0x30050, 1))
        self.assertEqual(v.compose_level('gfx.lvl', 0x1a0), (0x30050, 9))
        self.assertEqual(v.compose('cx.lvl', 7), (0x30000, 7))

    def test_duplicate_mx_entries_keep_both_indices(self):
        self.assertEqual(v.levels('mx.lvl'), [0, 0x10, 0x10, 0x100, 0x180])
        self.assertEqual(v.compose('mx.lvl', 2), (0x30010, 2))
        self.assertEqual(v.compose_level('mx.lvl', 0x10), (0x30010, 1))
        self.assertEqual(v.compose_level('mx.lvl', 0x11), (0x30010, 3))

    def test_in_between_level_rounds_up(self):
        self.assertEqual(v.compose_level('gfx.lvl', 0x31), (0x30050, 3))

    def test_all_gpu_selector_boundaries(self):
        for row, address, count in (('cx.lvl', 0x30000, 8),
                                    ('mx.lvl', 0x30010, 5),
                                    ('gfx.lvl', 0x30050, 10)):
            self.assertEqual(len(v.levels(row)), count)
            for selector in range(count):
                self.assertEqual(v.compose(row, selector), (address, selector))
            for selector in (-1, count, 1.0, True, '1'):
                with self.assertRaises(v.VoteError):
                    v.compose(row, selector)

    def test_unsupported_consumer_level_refused(self):
        for level in (-1, 0x1a1, True, 1.5):
            with self.assertRaises(v.VoteError):
                v.compose_level('gfx.lvl', level)

    def test_vrm_and_old_rail_api_refused(self):
        for rail in ('vrm.cx', 'vrm.mx', 'vrm.gfx'):
            with self.assertRaisesRegex(v.VoteError, 'VRM'):
                v.compose(rail, 1)
            with self.assertRaisesRegex(v.VoteError, 'VRM'):
                v.rail_vote(rail, 1)

    def test_bcm_and_unknown_rows_refused(self):
        for row in ('MC0', 'SH0', 'CN0', 'unknown'):
            with self.assertRaises(v.VoteError):
                v.compose(row, 1)


if __name__ == '__main__':
    unittest.main()
