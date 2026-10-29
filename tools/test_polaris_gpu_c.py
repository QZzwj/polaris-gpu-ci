"""Execute the C code reconstructed from the GPU patch series on the host.

Set POLARIS_CC_JSON to a JSON compiler argv (e.g. ["zig", "cc"]). CI on
macOS/Linux uses cc by default. This compiles the shipped patch, not a C copy.
"""
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import polaris_rpmh_vote as model

PATCHES = Path(__file__).resolve().parents[1] / 'xnu/patches'


class Vote(ctypes.Structure):
    _fields_ = [('addr', ctypes.c_uint32), ('data', ctypes.c_uint32),
                ('resource', ctypes.c_char_p), ('selector', ctypes.c_uint),
                ('consumer_level', ctypes.c_uint16)]


class GpuCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = json.loads(os.environ.get('POLARIS_CC_JSON', 'null'))
        if compiler is None:
            compiler = [shutil.which('cc')] if shutil.which('cc') else None
        if not compiler:
            raise unittest.SkipTest('native C compiler unavailable; set POLARIS_CC_JSON')
        cls.temp = tempfile.TemporaryDirectory(prefix='polaris-c-',
                                               dir=os.environ.get('POLARIS_TEST_TMP'))
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        dev = root / 'bsd/dev'
        dev.mkdir(parents=True)
        lines = next(PATCHES.glob('0091-*.patch')).read_text().splitlines(keepends=True)
        start = lines.index('+++ b/bsd/dev/polaris_gpu_diag.c\n')
        (dev / 'polaris_gpu_diag.c').write_text(''.join(l[1:] for l in lines[start + 1:]
                                                     if l.startswith('+')), newline='\n')
        lines = next(PATCHES.glob('0093-*.patch')).read_text().splitlines(keepends=True)
        start = next(i for i, l in enumerate(lines) if l.startswith('+++ b/bsd/dev/polaris_gpu.c'))
        (dev / 'polaris_gpu.c').write_text(''.join(l[1:] for l in lines[start + 1:]
                                                if l.startswith('+')), newline='\n')
        for number in range(94, 104):
            candidates = list(PATCHES.glob(f'{number:04}-*.patch'))
            if len(candidates) != 1:
                raise RuntimeError(f'expected one patch for {number:04}, got {candidates}')
            subprocess.run(['git', 'apply', '--include=bsd/dev/*',
                            str(candidates[0])],
                           cwd=root, check=True, capture_output=True)
        inc = root / 'include/sys'
        inc.mkdir(parents=True)
        (inc / 'types.h').write_text('#include <stdint.h>\n')
        (inc / 'param.h').write_text('#include <stddef.h>\n#include <stdint.h>\n#include <stdbool.h>\n')
        (inc / 'systm.h').write_text('#include <stdio.h>\n#include <string.h>\n'
                                    'int pg_test_printf(const char *, ...);\n'
                                    '#define printf pg_test_printf\n')
        (root / 'include/pexpert').mkdir()
        (root / 'include/pexpert/pexpert.h').write_text(
            'int PE_parse_boot_argn(const char *, void *, int);\n')
        (root / 'include/pexpert/device_tree.h').write_text(
            'typedef void *DTEntry;\n#define kSuccess 0\n'
            'int SecureDTLookupEntry(DTEntry, const char *, DTEntry *);\n'
            'int SecureDTGetProperty(DTEntry, const char *, const void **, unsigned *);\n')
        (root / 'include/vm').mkdir()
        (root / 'include/vm/pmap.h').write_text(
            '#include <stdint.h>\n#include <stddef.h>\n'
            'typedef uintptr_t vm_offset_t;\ntypedef size_t vm_size_t;\n')
        wrapper = root / 'wrapper.c'
        wrapper.write_text('''
#include <dev/polaris_gpu_arc_vote.h>
#include <dev/polaris_gpu_arc.h>
#include <dev/polaris_gpu_pwr.h>
#include <pexpert/device_tree.h>
#include <vm/pmap.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif
EXPORT int probe(const char *row, unsigned value, int by_level, struct pg_vote *out) {
    return by_level ? pg_arc_compose_level(row, value, out)
        : pg_arc_compose_selector(row, value, out);
}
EXPORT unsigned selector_count(const char *row) { return pg_arc_selector_count(row); }
EXPORT unsigned ref_phandle(unsigned i) {
    unsigned n; const struct pg_iommu_ref *r = pg_arc_iommu_refs(&n);
    return i < n ? r[i].provider_phandle : 0;
}
EXPORT unsigned ref_arg(unsigned i) {
    unsigned n; const struct pg_iommu_ref *r = pg_arc_iommu_refs(&n);
    return i < n ? r[i].arg0 : 0xffffffff;
}
/* A local RAM window, never a real MMIO mapping. Poison unused offsets so a
 * second +0x1000 bias cannot masquerade as a plausible register value. */
static uint32_t power_regs[0x2000 / 4], power_snapshot[0x2000 / 4];
static int power_enabled, power_board, power_bad_map;
static unsigned power_maps;
static char power_text[8192];
static size_t power_text_len;
int pg_test_printf(const char *fmt, ...) {
    va_list ap;
    size_t remaining = sizeof(power_text) - power_text_len;
    va_start(ap, fmt);
    int n = vsnprintf(power_text + power_text_len, remaining, fmt, ap);
    va_end(ap);
    if (n > 0) power_text_len += (size_t)n < remaining ? (size_t)n : remaining - 1;
    return n;
}
bool polaris_touch_i2c_board(void) { return power_board != 0; }
int PE_parse_boot_argn(const char *name, void *out, int size) {
    (void)name;
    if (size != sizeof(power_enabled)) return 0;
    memcpy(out, &power_enabled, sizeof(power_enabled));
    return 1;
}
vm_offset_t ml_io_map(vm_offset_t phys, vm_size_t size) {
    power_maps++;
    if (phys != 0x05091000 || size != sizeof(power_regs)) {
        power_bad_map = 1;
        return 0;
    }
    return (vm_offset_t)power_regs;
}
EXPORT const char *power_probe(unsigned write_probe, int enabled, int board) {
    for (unsigned i = 0; i < sizeof(power_regs) / sizeof(power_regs[0]); i++)
        power_regs[i] = 0x5a5a5a5a;
    power_regs[0x6c / 4] = 0x80000001;
    power_regs[0x540 / 4] = 0x11223344;
    power_regs[0x0c / 4] = 0xaabbccdd;
    memcpy(power_snapshot, power_regs, sizeof(power_regs));
    power_enabled = enabled; power_board = board;
    power_maps = 0; power_bad_map = 0; power_text_len = 0; power_text[0] = 0;
    if (write_probe) polaris_gpu_cx_on(); else polaris_gpu_pwr_probe();
    return power_text;
}
EXPORT unsigned power_map_count(void) { return power_maps; }
EXPORT int power_memory_unchanged(void) {
    return !power_bad_map && memcmp(power_snapshot, power_regs, sizeof(power_regs)) == 0;
}
/* Fake ADT properties deliberately start at unaligned addresses, as real ADT
 * properties may. No firmware bytes, MMIO or device are needed by this test. */
static const char *const blob_names[6] = {
    "GPU-SQE", "GPU-GMU", "GPU-ZAP-MDT", "GPU-ZAP-B00", "GPU-ZAP-B01", "GPU-ZAP-B02"
};
static uint64_t dt_dram[2];
static unsigned char dt_blob[6][17];
static unsigned dt_blob_len[6], dt_reads;
void polaris_gpu_diag(void);
void polaris_gpu_init(void);
int SecureDTLookupEntry(DTEntry parent, const char *path, DTEntry *out) {
    (void)parent;
    dt_reads++;
    if (!strcmp(path, "/chosen")) *out = (DTEntry)(uintptr_t)1;
    else if (!strcmp(path, "/chosen/memory-map")) *out = (DTEntry)(uintptr_t)2;
    else return -1;
    return kSuccess;
}
int SecureDTGetProperty(DTEntry node, const char *name, const void **out, unsigned *len) {
    dt_reads++;
    if (node == (DTEntry)(uintptr_t)1) {
        if (!strcmp(name, "dram-base")) *out = &dt_dram[0];
        else if (!strcmp(name, "dram-size")) *out = &dt_dram[1];
        else return -1;
        *len = 8;
        return kSuccess;
    }
    for (unsigned i = 0; i < 6; i++) {
        if (!strcmp(name, blob_names[i]) && dt_blob_len[i]) {
            *out = &dt_blob[i][1];
            *len = dt_blob_len[i];
            return kSuccess;
        }
    }
    return -1;
}
EXPORT void diag_set_blob(unsigned i, uint64_t addr, uint64_t size, unsigned len) {
    if (i >= 6) return;
    memcpy(&dt_blob[i][1], &addr, 8);
    memcpy(&dt_blob[i][9], &size, 8);
    dt_blob_len[i] = len;
}
EXPORT void diag_set_dram(uint64_t base, uint64_t size) {
    dt_dram[0] = base; dt_dram[1] = size;
}
EXPORT void diag_reset(int historical, int enabled, int board) {
    const unsigned sizes[6] = {31980, 32768, 6684, 148, 6536, 1968};
    power_enabled = enabled; power_board = board;
    diag_set_dram(0x100000000ull, 0x7cc00000ull);
    for (unsigned i = 0; i < 6; i++)
        diag_set_blob(i, 0x110000000ull + i * 0x10000ull,
                      i == 0 && historical ? 32136 : sizes[i], 16);
}
EXPORT const char *diag_run(unsigned bringup) {
    power_text_len = 0; power_text[0] = 0; power_maps = 0; dt_reads = 0;
    if (bringup) polaris_gpu_init(); else polaris_gpu_diag();
    return power_text;
}
EXPORT unsigned diag_dt_reads(void) { return dt_reads; }
''')
        library = root / ('gpu.dll' if os.name == 'nt' else 'gpu.so')
        shared_flag = '-dynamiclib' if sys.platform == 'darwin' else '-shared'
        argv = compiler + ['-std=c11', '-Wall', '-Wextra', '-Werror', shared_flag,
                           '-DARM64_BOARD_CONFIG_SWEET=1', '-I' + str(root / 'include'),
                           '-I' + str(root / 'bsd'), str(wrapper),
                           str(dev / 'polaris_gpu_arc_vote.c'),
                           str(dev / 'polaris_gpu_arc.c'),
                           str(dev / 'polaris_gpu_pwr_diag.c'),
                           str(dev / 'polaris_gpu_pwron.c'),
                           str(dev / 'polaris_gpu_diag.c'),
                           str(dev / 'polaris_gpu_validate.c'),
                           str(dev / 'polaris_gpu.c'), '-o', str(library)]
        if os.name != 'nt':
            argv.append('-fPIC')
        result = subprocess.run(argv, capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise RuntimeError('C compilation failed:\n' + result.stdout + result.stderr)
        cls.lib = ctypes.CDLL(str(library))
        # Windows holds the DLL open; release before deleting the temporary tree.
        if os.name == 'nt':
            cls.addClassCleanup(lambda: ctypes.windll.kernel32.FreeLibrary(
                ctypes.c_void_p(cls.lib._handle)))
        cls.lib.probe.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.c_int,
                                  ctypes.POINTER(Vote)]
        cls.lib.probe.restype = ctypes.c_int
        for name in ('selector_count',):
            getattr(cls.lib, name).argtypes = [ctypes.c_char_p]
            getattr(cls.lib, name).restype = ctypes.c_uint
        for name in ('ref_phandle', 'ref_arg'):
            getattr(cls.lib, name).argtypes = [ctypes.c_uint]
            getattr(cls.lib, name).restype = ctypes.c_uint
        cls.lib.power_probe.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_int]
        cls.lib.power_probe.restype = ctypes.c_char_p
        cls.lib.power_map_count.restype = ctypes.c_uint
        cls.lib.power_memory_unchanged.restype = ctypes.c_int
        cls.lib.diag_reset.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        cls.lib.diag_set_blob.argtypes = [ctypes.c_uint, ctypes.c_uint64,
                                         ctypes.c_uint64, ctypes.c_uint]
        cls.lib.diag_set_dram.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
        cls.lib.diag_run.argtypes = [ctypes.c_uint]
        cls.lib.diag_run.restype = ctypes.c_char_p
        cls.lib.diag_dt_reads.restype = ctypes.c_uint

    def test_c_matches_protocol_for_every_selector(self):
        for row in model.GPU_ROWS:
            values = model.levels(row)
            self.assertEqual(self.lib.selector_count(row.encode()), len(values))
            for selector, level in enumerate(values):
                out = Vote()
                self.assertEqual(self.lib.probe(row.encode(), selector, 0,
                                                ctypes.byref(out)), 1)
                self.assertEqual((out.addr, out.data), model.compose(row, selector))
                self.assertEqual((out.selector, out.consumer_level), (selector, level))
                self.assertEqual(out.resource, row.encode())

    def test_c_ceiling_mapping_and_duplicate_levels(self):
        for row in model.GPU_ROWS:
            for level in range(model.levels(row)[-1] + 1):
                out = Vote()
                self.assertEqual(self.lib.probe(row.encode(), level, 1,
                                                ctypes.byref(out)), 1)
                self.assertEqual((out.addr, out.data), model.compose_level(row, level))

    def test_c_rejects_vrm_bad_indices_nulls_without_changing_output(self):
        for row, value, by_level in ((b'vrm.gfx', 1, 0), (b'gfx.lvl', 10, 0),
                                    (b'mx.lvl', 5, 0), (b'cx.lvl', 8, 0),
                                    (b'gfx.lvl', 0x1a1, 1), (None, 0, 0)):
            out = Vote(addr=0x12345678, data=0x87654321)
            self.assertEqual(self.lib.probe(row, value, by_level, ctypes.byref(out)), 0)
            self.assertEqual((out.addr, out.data), (0x12345678, 0x87654321))
        self.assertEqual(self.lib.probe(b'gfx.lvl', 1, 0, None), 0)

    def test_c_raw_references_do_not_claim_bank_assignment(self):
        self.assertEqual([self.lib.ref_phandle(i) for i in range(5)], [0x208] * 5)
        self.assertEqual([self.lib.ref_arg(i) for i in range(5)], [0, 2, 1, 4, 5])

    def test_power_readonly_uses_physical_registers_without_double_offset(self):
        log = self.lib.power_probe(0, 1, 1).decode()
        self.assertIn('cx_gdscr=0x80000001', log)
        self.assertIn('cx_hw_ctrl=0x11223344', log)
        self.assertIn('gx_gdscr=0xaabbccdd', log)
        self.assertEqual(self.lib.power_map_count(), 1)
        self.assertEqual(self.lib.power_memory_unchanged(), 1)

    def test_power_foreign_on_domain_is_observed_without_writes(self):
        log = self.lib.power_probe(1, 1, 1).decode()
        self.assertIn('CX GDSCR before=0x80000001', log)
        self.assertIn('CX already on and not ours; no write, no ownership', log)
        self.assertEqual(self.lib.power_map_count(), 1)
        self.assertEqual(self.lib.power_memory_unchanged(), 1)

    def test_power_requires_separate_optin_and_matching_board(self):
        for write in (0, 1):
            for enabled, board in ((0, 1), (1, 0)):
                self.assertEqual(self.lib.power_probe(write, enabled, board), b'')
                self.assertEqual(self.lib.power_map_count(), 0)
                self.assertEqual(self.lib.power_memory_unchanged(), 1)

    def test_diagnostic_accepts_both_registered_sets_without_gpu_access(self):
        for historical, name, size in ((0, 'miui-v12.5.1.0-qdgcnxm-20210707', 31980),
                                        (1, 'device-2026-10-22', 32136)):
            self.lib.diag_reset(historical, 1, 1)
            log = self.lib.diag_run(0).decode()
            self.assertIn('diagnostic metadata validated set=' + name, log)
            self.assertIn(f'GPU-SQE present size={size} (not executed)', log)
            self.assertIn('6/6 blobs validated; firmware metadata only', log)
            self.assertNotIn('invalid', log)
            self.assertEqual(self.lib.power_map_count(), 0)

    def test_diagnostic_checks_optin_and_board_before_reading_adt(self):
        for enabled, board in ((0, 1), (1, 0), (2, 1), (-1, 1)):
            self.lib.diag_reset(0, enabled, board)
            self.assertEqual(self.lib.diag_run(0), b'')
            self.assertEqual(self.lib.diag_dt_reads(), 0)
            self.assertEqual(self.lib.power_map_count(), 0)

    def test_diagnostic_refuses_incomplete_or_unknown_firmware_before_printing_present(self):
        for size, length, reason in ((1, 16, 'lengths match no registered set'),
                                     (1968, 0, 'blob missing'),
                                     (1968, 12, 'blob missing'),
                                     (1 << 32, 16, 'impossible length')):
            self.lib.diag_reset(0, 1, 1)
            self.lib.diag_set_blob(5, 0x110050000, size, length)
            log = self.lib.diag_run(0).decode()
            self.assertIn('diagnostic handoff refused', log)
            self.assertIn(reason, log)
            self.assertNotIn('present size=', log)
            self.assertEqual(self.lib.power_map_count(), 0)

    def test_diagnostic_refuses_misalignment_overlap_and_outside_ram(self):
        for address, reason in ((0x110000008, 'not page aligned'),
                                 (0x110010000, 'overlap each other'),
                                 (0x17cc00000, 'outside managed RAM')):
            self.lib.diag_reset(0, 1, 1)
            self.lib.diag_set_blob(0, address, 31980, 16)
            self.assertIn(reason, self.lib.diag_run(0).decode())
            self.assertEqual(self.lib.power_map_count(), 0)

    def test_diagnostic_refuses_overflow_and_reserved_dram(self):
        for base, size, reason in (((1 << 64) - 0x1000, 0x2000, 'overflows 64 bits'),
                                    (0x8c400000, 0x100000, 'zap or splash'),
                                    (0x9d400000, 0x100000, 'zap or splash')):
            self.lib.diag_reset(0, 1, 1)
            self.lib.diag_set_dram(base, size)
            self.assertIn(reason, self.lib.diag_run(0).decode())
            self.assertEqual(self.lib.power_map_count(), 0)

    def test_bringup_stops_at_rails_without_calling_standalone_cx_write(self):
        # Both power flags are 1 in this mock. Only the read-only probe may map;
        # the old unconditional CX experiment must not bypass the rails backend.
        self.lib.power_probe(0, 1, 1)
        self.lib.diag_reset(0, 1, 1)
        log = self.lib.diag_run(1).decode()
        self.assertIn('rails backend not implemented', log)
        self.assertIn('acceleration unavailable; CPU display unchanged', log)
        self.assertNotIn('CX GDSCR before=', log)
        self.assertEqual(self.lib.power_map_count(), 1)
        self.assertEqual(self.lib.power_memory_unchanged(), 1)


if __name__ == '__main__':
    unittest.main()
