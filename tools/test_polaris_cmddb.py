"""Host tests for the command-DB gate (no hardware, no firmware)."""
import unittest

import polaris_cmddb as db

GOOD = """Address: 0x30000, id: cx.lvl, aux data: 00 00 10 00 30 00 40 00 80 00 c0 00 00 01 80 01
Address: 0x30004, id: cx.tmr
Address: 0x30010, id: mx.lvl, aux data: 00 00 10 00 10 00 00 01 80 01
Address: 0x30050, id: gfx.lvl, aux data: 00 00 10 00 30 00 40 00 80 00 c0 00 00 01 40 01 80 01 a0 01
Address: 0x30070, id: ddr.lvl, aux data: 00 00 20 00 80 00 a0 00
Address: 0x30080, id: xo.lvl, aux data: 00 00 20 00 50 00 80 00
Address: 0x40800, id: vrm.cx
Address: 0x40700, id: vrm.mx
Address: 0x42700, id: vrm.gfx
Address: 0x40400, id: vrm.ebi
Address: 0x50000, id: MC0, aux data: 80 84 1e 00 10 00 00 00
"""


class CmdDbTests(unittest.TestCase):
    def test_good_dump_passes(self):
        rows = db.validate(GOOD)
        self.assertEqual(rows['gfx.lvl'][0], 0x30050)

    def test_level_counts(self):
        self.assertEqual(db.count_levels('00 00 10 00 30 00 40 00 80 00 c0 00 00 01 80 01'), 7)
        self.assertEqual(db.count_levels('00 00 10 00 30 00 40 00 80 00 c0 00 00 01 40 01 80 01 a0 01'), 9)
        self.assertEqual(db.count_levels(''), 0)

    def test_wrong_address_rejected(self):
        bad = GOOD.replace('0x30050, id: gfx.lvl', '0x30060, id: gfx.lvl')
        with self.assertRaisesRegex(ValueError, 'address'):
            db.validate(bad)

    def test_wrong_level_count_rejected(self):
        bad = GOOD.replace(
            'aux data: 00 00 10 00 30 00 40 00 80 00 c0 00 00 01 40 01 80 01 a0 01',
            'aux data: 00 00 10 00 30 00 40 00')
        with self.assertRaisesRegex(ValueError, 'levels'):
            db.validate(bad)

    def test_missing_row_rejected(self):
        bad = '\n'.join(line for line in GOOD.splitlines() if 'vrm.gfx' not in line)
        with self.assertRaisesRegex(ValueError, 'missing'):
            db.validate(bad)

    def test_duplicate_id_rejected(self):
        bad = GOOD + 'Address: 0x30050, id: gfx.lvl\n'
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            db.validate(bad)

    def test_empty_input_rejected(self):
        with self.assertRaisesRegex(ValueError, 'no command-db rows'):
            db.validate('nothing here\n')


if __name__ == '__main__':
    unittest.main()
