#!/usr/bin/env python3
"""Host tests for the Polaris GPU handoff gate and ownership ledger.

Nothing here touches hardware, firmware or a phone.
"""
import unittest

import polaris_gpu_handoff as h

DRAM_BASE, DRAM_SIZE = 0x100000000, 0x7CC00000
GOOD_SIZES = h.FIRMWARE_SETS['device-2026-10-22'][0]


def blobs(sizes=GOOD_SIZES, starts=None):
    starts = starts or [0x110000000 + i * 0x10000 for i in range(len(sizes))]
    return [(name, addr, size) for name, addr, size
            in zip(h.BLOB_NAMES, starts, sizes)]


class ValidateHandoffTests(unittest.TestCase):
    def test_accepts_device_and_miui_sets(self):
        for set_name in h.FIRMWARE_SETS:
            sizes = h.FIRMWARE_SETS[set_name][0]
            result = h.validate_handoff(h.REQUIRED_IDENTITIES, DRAM_BASE, DRAM_SIZE,
                                        blobs(sizes))
            self.assertEqual(result.set_name, set_name)
            self.assertEqual(tuple(b.name for b in result.blobs), h.BLOB_NAMES)

    def test_requires_both_board_identities(self):
        for identities in (('xiaomi,polaris',), ('qcom,sdm845',),
                           ('qcom,sm7150', 'qcom,sdm845')):
            with self.assertRaises(h.HandoffError):
                h.validate_handoff(identities, DRAM_BASE, DRAM_SIZE, blobs())

    def test_refuses_unregistered_length_vector(self):
        sizes = list(GOOD_SIZES)
        sizes[1] = 4096
        with self.assertRaises(h.HandoffError):
            h.validate_handoff(h.REQUIRED_IDENTITIES, DRAM_BASE, DRAM_SIZE,
                               blobs(sizes))

    def test_refuses_misaligned_or_outside_blob(self):
        bad = blobs()
        bad[0] = (bad[0][0], bad[0][1] + 8, bad[0][2])
        with self.assertRaises(h.HandoffError):
            h.validate_handoff(h.REQUIRED_IDENTITIES, DRAM_BASE, DRAM_SIZE, bad)
        outside = blobs()
        outside[3] = (outside[3][0], DRAM_BASE + DRAM_SIZE - 0x1000, outside[3][2])
        with self.assertRaises(h.HandoffError):
            h.validate_handoff(h.REQUIRED_IDENTITIES, DRAM_BASE, DRAM_SIZE, outside)

    def test_refuses_overlap_with_platform_carveouts(self):
        for base, size in ((h.CAMERA_BASE, h.CAMERA_SIZE),
                           (h.ZAP_BASE, h.ZAP_SIZE),
                           (h.SPLASH_BASE, h.SPLASH_SIZE)):
            collision = dict(
                dram_base=base - 0x100000, dram_size=size + 0x800000,
                blobs=blobs(starts=[base - 0x100000 + 0x1000 * (i + 1)
                                    for i in range(len(GOOD_SIZES))]))
            with self.assertRaises(h.HandoffError):
                h.validate_handoff(h.REQUIRED_IDENTITIES, collision['dram_base'],
                                   collision['dram_size'], collision['blobs'])

    def test_refuses_blob_on_blob_overlap(self):
        starts = [0x110000000] * len(GOOD_SIZES)
        with self.assertRaises(h.HandoffError):
            h.validate_handoff(h.REQUIRED_IDENTITIES, DRAM_BASE, DRAM_SIZE,
                               blobs(starts=starts))

    def test_refuses_dram_overflow(self):
        with self.assertRaises(h.HandoffError):
            h.validate_handoff(h.REQUIRED_IDENTITIES, h.U64_MAX - 0x1000, 0x2000,
                               blobs())

    def test_result_is_immutable_and_reserve_is_page_rounded(self):
        result = h.validate_handoff(h.REQUIRED_IDENTITIES, DRAM_BASE, DRAM_SIZE, blobs())
        with self.assertRaises(Exception):
            result.set_name = 'other'
        sqe = result.blob('GPU-SQE')
        self.assertEqual(sqe.reserve % h.PAGE, 0)
        self.assertGreaterEqual(sqe.reserve, sqe.size)

    def test_accepts_low_dram_hfi_reservation(self):
        result = h.validate_handoff(h.REQUIRED_IDENTITIES, DRAM_BASE, DRAM_SIZE,
                                    blobs(), hfi=(0x8c420000, 0x8000))
        self.assertEqual(result.hfi_addr, 0x8c420000)
        self.assertEqual(result.hfi_size, 0x8000)

    def test_refuses_bad_hfi_reservations(self):
        for hfi in ((0x8c420000, 0x4000),        # too small
                    (0x8c420008, 0x8000),        # misaligned
                    (0x100000000, 0x8000),       # not low DRAM
                    (0x8c415000, 0x8000),        # collides with zap
                    (0x8bf80000, 0x8000),        # collides with camera
                    (0x9d400000, 0x8000),        # collides with splash
                    (DRAM_BASE, 0x8000),         # inside XNU-managed RAM
                    (0xfffffffffffff000, 0x2000)):  # overflow
            with self.assertRaises(h.HandoffError):
                h.validate_handoff(h.REQUIRED_IDENTITIES, DRAM_BASE, DRAM_SIZE,
                                   blobs(), hfi=hfi)


class LedgerTests(unittest.TestCase):
    def test_acquire_requires_ack_and_matching_readback(self):
        ledger = h.Ledger()
        with self.assertRaises(h.HandoffError):
            ledger.acquire('cx-gdsc', ack=True, readback=0, expected=1)
        self.assertEqual(ledger.entries['cx-gdsc'].state, h.UNKNOWN)
        self.assertTrue(ledger.quarantined)

    def test_clean_acquire_then_release(self):
        ledger = h.Ledger()
        ledger.acquire('gpucc-s6', ack=True, readback=0x1, expected=0x1)
        self.assertEqual(ledger.owned(), ('gpucc-s6',))
        ledger.release('gpucc-s6', quiesced=True)
        self.assertEqual(ledger.owned(), ())

    def test_foreign_owner_is_never_released(self):
        ledger = h.Ledger()
        ledger.record('cx-gdsc', h.OBSERVED_FOREIGN)
        with self.assertRaises(h.HandoffError):
            ledger.release('cx-gdsc', quiesced=True)

    def test_failed_quiesce_quarantines_and_blocks_release(self):
        ledger = h.Ledger()
        ledger.acquire('gmu', ack=True, readback=1, expected=1)
        with self.assertRaises(h.HandoffError):
            ledger.release('gmu', quiesced=False)
        self.assertTrue(ledger.quarantined)
        self.assertEqual(ledger.owned(), ('gmu',))

    def test_no_acquire_after_quarantine(self):
        ledger = h.Ledger()
        ledger.record('x', h.OBSERVED_FOREIGN)
        ledger.quarantined = True
        with self.assertRaises(h.HandoffError):
            ledger.acquire('y', ack=True, readback=1, expected=1)

    def test_double_release_refused(self):
        ledger = h.Ledger()
        ledger.acquire('a', ack=True, readback=1, expected=1)
        ledger.release('a', quiesced=True)
        with self.assertRaises(h.HandoffError):
            ledger.release('a', quiesced=True)


if __name__ == '__main__':
    unittest.main()
