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
        lines = next(PATCHES.glob('0093-*.patch')).read_text().splitlines(keepends=True)
        start = next(i for i, l in enumerate(lines) if l.startswith('+++ b/bsd/dev/polaris_gpu.c'))
        (dev / 'polaris_gpu.c').write_text(''.join(l[1:] for l in lines[start + 1:]
                                                if l.startswith('+')), newline='\n')
        for number in range(94, 103):
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
        (root / 'include/vm').mkdir()
        (root / 'include/vm/pmap.h').write_text(
            '#include <stdint.h>\n#include <stddef.h>\n'
            'typedef uintptr_t vm_offset_t;\ntypedef size_t vm_size_t;\n')
        wrapper = root / 'wrapper.c'
        wrapper.write_text('''
#include <dev/polaris_gpu_arc_vote.h>
#include <dev/polaris_gpu_arc.h>
#include <dev/polaris_gpu_pwr.h>
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
static char power_text[1024];
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
''')
        library = root / ('gpu.dll' if os.name == 'nt' else 'gpu.so')
        shared_flag = '-dynamiclib' if sys.platform == 'darwin' else '-shared'
        argv = compiler + ['-std=c11', '-Wall', '-Wextra', '-Werror', shared_flag,
                           '-DARM64_BOARD_CONFIG_SWEET=1', '-I' + str(root / 'include'),
                           '-I' + str(root / 'bsd'), str(wrapper),
                           str(dev / 'polaris_gpu_arc_vote.c'),
                           str(dev / 'polaris_gpu_arc.c'),
                           str(dev / 'polaris_gpu_pwr_diag.c'),
                           str(dev / 'polaris_gpu_pwron.c'), '-o', str(library)]
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


if __name__ == '__main__':
    unittest.main()
