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
        # 0092 adds one line to the diagnostic; 0103 is generated against that
        # exact text, so the fixture must include it before applying 0103.
        subprocess.run(['git', 'apply', '--include=bsd/dev/polaris_gpu_diag.c',
                        str(next(PATCHES.glob('0092-*.patch')))],
                       cwd=root, check=True, capture_output=True)
        for number in range(94, 107):
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
        (root / 'include/kern').mkdir()
        (root / 'include/kern/clock.h').write_text(
            '#include <stdint.h>\n'
            'uint64_t mach_absolute_time(void);\n'
            'void absolutetime_to_nanoseconds(uint64_t, uint64_t *);\n')
        (root / 'include/machine').mkdir()
        (root / 'include/machine/machine_routines.h').write_text(
            'void DELAY(unsigned);\n')
        wrapper = root / 'wrapper.c'
        wrapper.write_text('''
#include <dev/polaris_gpu_arc_vote.h>
#include <dev/polaris_gpu_arc.h>
#include <dev/polaris_gpu_pwr.h>
#include <dev/polaris_rpmh.h>
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
static int rh_diag_arg = 1, rh_vote_arg, rh_level_arg;
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
    if (size != sizeof(power_enabled)) return 0;
    if (!strcmp(name, "polarisrpmhdiag")) {
        memcpy(out, &rh_diag_arg, sizeof(rh_diag_arg));
        return rh_diag_arg != 0;
    }
    if (!strcmp(name, "polarisrpmhvote")) {
        memcpy(out, &rh_vote_arg, sizeof(rh_vote_arg));
        return rh_vote_arg != 0;
    }
    if (!strcmp(name, "polarisrpmhlevel")) {
        memcpy(out, &rh_level_arg, sizeof(rh_level_arg));
        return rh_level_arg != 0;
    }
    memcpy(out, &power_enabled, sizeof(power_enabled));
    return 1;
}
vm_offset_t ml_io_map(vm_offset_t phys, vm_size_t size) {
    extern uint32_t rh_regs[];
    if (phys == 0x179e0000 && size == 0x4000u) return (vm_offset_t)rh_regs;
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
/* ---- Simulated RPMh DRV2, not a hardware emulator. ---- */
uint32_t rh_regs[0x4000 / 4];
static uint32_t rh_other[0x4000 / 4];
static uint64_t rh_now;
static unsigned rh_writes, rh_pauses, rh_complete_after, rh_bad_write;
static unsigned rh_seen_addr, rh_seen_data;
static unsigned rh_sent_selector, rh_sent_level;
static int rh_freeze_time, rh_fail_verify;
static struct pg_rh_transport rh_ctx;
uint64_t mach_absolute_time(void) { return rh_now * 1000ull; }
void absolutetime_to_nanoseconds(uint64_t value, uint64_t *ns) { *ns = value; }
void DELAY(unsigned us) {
    rh_pauses++;
    if (!rh_freeze_time) rh_now += us;
}
#define RHOFF(tcs, reg) ((0xd00u + (tcs) * 0x2a0u + (reg)) / 4)
static uint32_t rh_read(void *cookie, uint32_t off) {
    (void)cookie;
    if ((off & 3) || off > 0x3ffc) { rh_bad_write = 1; return UINT32_MAX; }
    return rh_regs[off / 4];
}
static void rh_write(void *cookie, uint32_t off, uint32_t value) {
    (void)cookie;
    if ((off & 3) || off > 0x3ffc) { rh_bad_write = 1; return; }
    rh_writes++;
    if (rh_fail_verify && off == 0xd00 + 0x1c) return;
    rh_regs[off / 4] = value;
    if (off == 0xd00 + 8) rh_regs[0xd00 / 4 + 1] &= ~value;
    if (off == 0xd00 + 0x34) rh_seen_addr = value;
    if (off == 0xd00 + 0x38) rh_seen_data = value;
    if (off >= 0xd00 && (off - 0xd00) % 0x2a0 == 0x14 && (value & 0x1000000u)) {
        unsigned tcs = (off - 0xd00) / 0x2a0;
        if (tcs >= 2 || rh_complete_after == 0) return;
        rh_regs[0xd00 / 4 + 1] |= 1u << tcs;
        rh_regs[RHOFF(tcs, 0x18)] = 1u;
        for (unsigned i = 0; i < rh_complete_after; i++)
            rh_regs[RHOFF(tcs, 0x3c + i * 0x14)] = 0x10100u;
    }
}
static uint64_t rh_time(void *cookie) { (void)cookie; return rh_now; }
static void rh_pause(void *cookie, unsigned us) {
    (void)cookie; rh_pauses++; if (!rh_freeze_time) rh_now += us;
}
EXPORT void rh_reset(unsigned banks, unsigned ncpt, unsigned complete_after) {
    memset(rh_regs, 0, sizeof(rh_regs));
    rh_regs[3] = (banks << 12) | (ncpt << 27) | 0x104u;
    rh_regs[0xd00 / 4] = 1;
    for (unsigned i = 0; i < 8; i++) rh_regs[RHOFF(i, 0x18)] = 1;
    memcpy(rh_other, rh_regs, sizeof(rh_regs));
    memset(&rh_ctx, 0, sizeof(rh_ctx));
    rh_now = 100; rh_writes = rh_pauses = 0; rh_bad_write = 0;
    rh_complete_after = complete_after; rh_freeze_time = rh_fail_verify = 0;
}
EXPORT void rh_freeze(int freeze) { rh_freeze_time = freeze; }
EXPORT void rh_fail_irq_verify(int fail) { rh_fail_verify = fail; }
EXPORT int rh_claim_mock(int drv, int idle, int votes) {
    struct pg_rh_io io = {0, rh_read, rh_write, rh_time, rh_pause};
    struct pg_rh_authority a = {(bool)drv, (bool)idle, (bool)votes};
    return pg_rh_claim(&rh_ctx, &io, &a);
}
EXPORT int rh_snapshot_mock(void) {
    struct pg_rh_io io = {0, rh_read, NULL, NULL, NULL};
    struct pg_rh_snapshot s;
    int r = pg_rh_snapshot(&io, &s);
    return r ? -r : (int)s.commands;
}
EXPORT void rh_set_config(unsigned config) { rh_regs[3] = config; }
EXPORT void rh_occupy(unsigned tcs, unsigned cmd, unsigned addr) {
    rh_regs[RHOFF(tcs, 0x1c)] |= 1u << cmd;
    rh_regs[RHOFF(tcs, 0x34 + cmd * 0x14)] = addr;
}
EXPORT void rh_set_irq(unsigned status) { rh_regs[0xd00 / 4 + 1] = status; }
EXPORT void rh_set_irq_en(unsigned value) { rh_regs[0xd00 / 4] = value; }
EXPORT int rh_send_mock(const char *row, unsigned selector, unsigned timeout) {
    struct pg_vote v;
    if (!pg_arc_compose_selector(row, selector, &v)) return -100;
    rh_sent_selector = v.selector; rh_sent_level = v.consumer_level;
    return pg_rh_send(&rh_ctx, &v, 1, timeout);
}
EXPORT void rh_adapter_reset(void) { polaris_rpmh_test_reset(); }
EXPORT void rh_adapter_set_io(void) { polaris_rpmh_test_set_io(rh_read, rh_write); }
EXPORT void rh_boot_args(int diag, int vote, int level) {
    rh_diag_arg = diag; rh_vote_arg = vote; rh_level_arg = level; power_board = 1;
}
EXPORT int rh_adapter_vote(unsigned level) {
    return polaris_rpmh_vote_gfx(level);
}
EXPORT void rh_adapter_probe(void) { polaris_rpmh_probe(); }
EXPORT int rh_adapter_quarantined(void) { return polaris_rpmh_test_quarantined(); }
EXPORT void rh_log_reset(void) { power_text_len = 0; power_text[0] = 0; }
EXPORT const char *rh_log(void) { return power_text; }
EXPORT unsigned rh_write_count(void) { return rh_writes; }
EXPORT unsigned rh_pause_count(void) { return rh_pauses; }
EXPORT int rh_bad(void) { return rh_bad_write; }
EXPORT int rh_quarantined(void) { return (int)rh_ctx.quarantined; }
EXPORT void rh_lock(void) { rh_ctx.locked = 1; }
EXPORT unsigned rh_read_off(unsigned off) { return rh_regs[off / 4]; }
EXPORT unsigned rh_sent_composed(unsigned which) {
    return which ? rh_sent_level : rh_sent_selector;
}
EXPORT int rh_sleep_wake_unchanged(void) {
    return !memcmp(&rh_regs[RHOFF(2, 0)], &rh_other[RHOFF(2, 0)], 6 * 0x2a0);
}
''')
        library = root / ('gpu.dll' if os.name == 'nt' else 'gpu.so')
        shared_flag = '-dynamiclib' if sys.platform == 'darwin' else '-shared'
        argv = compiler + ['-std=c11', '-Wall', '-Wextra', '-Werror', shared_flag,
                           '-DARM64_BOARD_CONFIG_SWEET=1', '-DPG_RH_TEST',
                           '-I' + str(root / 'include'),
                           '-I' + str(root / 'bsd'), str(wrapper),
                           str(dev / 'polaris_gpu_arc_vote.c'),
                           str(dev / 'polaris_gpu_arc.c'),
                           str(dev / 'polaris_gpu_pwr_diag.c'),
                           str(dev / 'polaris_gpu_pwron.c'),
                           str(dev / 'polaris_gpu_diag.c'),
                           str(dev / 'polaris_gpu_validate.c'),
                           str(dev / 'polaris_gpu.c'),
                           str(dev / 'polaris_rpmh_core.c'),
                           str(dev / 'polaris_rpmh.c'), '-o', str(library)]
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
        for name in ('rh_reset', 'rh_claim_mock', 'rh_snapshot_mock', 'rh_send_mock',
                     'rh_write_count', 'rh_pause_count', 'rh_bad', 'rh_quarantined',
                     'rh_read_off', 'rh_sleep_wake_unchanged'):
            fn = getattr(cls.lib, name)
            fn.restype = ctypes.c_int if name not in ('rh_reset',) else None
        cls.lib.rh_claim_mock.argtypes = [ctypes.c_int] * 3
        cls.lib.rh_send_mock.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint]
        cls.lib.rh_boot_args.argtypes = [ctypes.c_int] * 3
        cls.lib.rh_adapter_vote.argtypes = [ctypes.c_uint]
        cls.lib.rh_adapter_vote.restype = ctypes.c_int
        cls.lib.rh_adapter_quarantined.restype = ctypes.c_int
        cls.lib.rh_log.restype = ctypes.c_char_p
        cls.lib.rh_occupy.argtypes = [ctypes.c_uint] * 3
        cls.lib.rh_set_irq.argtypes = [ctypes.c_uint]
        cls.lib.rh_set_irq_en.argtypes = [ctypes.c_uint]
        cls.lib.rh_set_config.argtypes = [ctypes.c_uint]
        cls.lib.rh_reset.argtypes = [ctypes.c_uint] * 3
        cls.lib.rh_bad.restype = ctypes.c_int
        cls.lib.rh_write_count.restype = ctypes.c_uint
        cls.lib.rh_read_off.restype = ctypes.c_uint
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


class RpmhTests(GpuCTests):
    """Fault-inject the actual compiled TCS engine; no board or hardware."""
    def test_snapshot_is_readonly_and_rejects_unknown_geometry(self):
        self.lib.rh_reset(8, 16, 1)
        self.assertEqual(self.lib.rh_snapshot_mock(), 16)
        self.assertEqual(self.lib.rh_write_count(), 0)
        for config in (0, (7 << 12) | (16 << 27), (8 << 12) | (15 << 27),
                       (8 << 12) | (17 << 27), 0xffffffff):
            self.lib.rh_set_config(config)
            self.assertLess(self.lib.rh_snapshot_mock(), 0)
            self.assertEqual(self.lib.rh_write_count(), 0)

    def test_claim_requires_every_authority_fact_and_never_writes(self):
        for facts in ((0, 1, 1), (1, 0, 1), (1, 1, 0)):
            self.lib.rh_reset(8, 16, 1)
            self.assertEqual(self.lib.rh_claim_mock(*facts), 6)
            self.assertEqual(self.lib.rh_write_count(), 0)
        self.lib.rh_reset(8, 16, 1)
        self.assertEqual(self.lib.rh_claim_mock(1, 1, 1), 0)
        self.assertEqual(self.lib.rh_write_count(), 0)

    def test_completed_active_write_restores_payload_and_leaves_sleep_wake(self):
        self.lib.rh_reset(8, 16, 1)
        self.assertEqual(self.lib.rh_claim_mock(1, 1, 1), 0)
        self.assertEqual(self.lib.rh_send_mock(b'gfx.lvl', 9, 1000), 0)
        self.assertEqual(self.lib.rh_bad(), 0)
        self.assertEqual(self.lib.rh_sent_composed(0), 9)
        self.assertEqual(self.lib.rh_sent_composed(1), 0x1a0)
        self.assertEqual(self.lib.rh_read_off(0xd00 + 0x34), 0)
        self.assertEqual(self.lib.rh_read_off(0xd00 + 0x1c), 0)
        self.assertEqual(self.lib.rh_read_off(0xd00 + 0x14), 0)
        self.assertEqual(self.lib.rh_sleep_wake_unchanged(), 1)
        self.assertEqual(self.lib.rh_quarantined(), 0)

    def test_inflight_conflict_refuses_without_writes(self):
        self.lib.rh_reset(8, 16, 1)
        self.assertEqual(self.lib.rh_claim_mock(1, 1, 1), 0)
        self.lib.rh_occupy(1, 3, 0x30050)
        self.assertEqual(self.lib.rh_send_mock(b'gfx.lvl', 9, 1000), 3)
        self.assertEqual(self.lib.rh_write_count(), 0)
        self.assertEqual(self.lib.rh_quarantined(), 0)

    def test_busy_and_stale_irq_are_rejected_before_any_mutation(self):
        self.lib.rh_reset(8, 16, 1)
        self.assertEqual(self.lib.rh_claim_mock(1, 1, 1), 0)
        self.lib.rh_lock()
        self.assertEqual(self.lib.rh_send_mock(b'gfx.lvl', 9, 1000), 3)
        self.assertEqual(self.lib.rh_write_count(), 0)
        self.lib.rh_reset(8, 16, 1)
        self.assertEqual(self.lib.rh_claim_mock(1, 1, 1), 0)
        self.lib.rh_set_irq(3)
        self.assertEqual(self.lib.rh_send_mock(b'gfx.lvl', 9, 1000), 3)
        self.assertEqual(self.lib.rh_write_count(), 0)
        # A stale IRQ on ACTIVE0 alone must not poison the clean ACTIVE1 slot.
        self.lib.rh_set_irq(1)
        self.lib.rh_set_irq_en(3)
        self.assertEqual(self.lib.rh_send_mock(b'gfx.lvl', 9, 1000), 0)
        self.assertEqual(self.lib.rh_read_off(0xd00 + 0x2a0 + 0x34), 0)
        self.assertEqual(self.lib.rh_sleep_wake_unchanged(), 1)

    def test_timeout_and_missing_completion_quarantine_and_never_retry(self):
        for complete in (0, 0):
            self.lib.rh_reset(8, 16, complete)
            self.assertEqual(self.lib.rh_claim_mock(1, 1, 1), 0)
            self.assertEqual(self.lib.rh_send_mock(b'gfx.lvl', 9, 100), 4)
            self.assertEqual(self.lib.rh_quarantined(), 1)
            writes = self.lib.rh_write_count()
            self.assertEqual(self.lib.rh_send_mock(b'gfx.lvl', 9, 100), 7)
            self.assertEqual(self.lib.rh_write_count(), writes)
            break

    def test_active_irq_must_already_be_enabled(self):
        self.lib.rh_reset(8, 16, 1)
        self.assertEqual(self.lib.rh_claim_mock(1, 1, 1), 0)
        self.lib.rh_set_irq_en(0)
        self.assertEqual(self.lib.rh_send_mock(b'gfx.lvl', 9, 100), 5)
        self.assertEqual(self.lib.rh_write_count(), 0)
        self.assertEqual(self.lib.rh_quarantined(), 1)

    def test_frozen_clock_still_bounded_and_only_active_slot_changes(self):
        self.lib.rh_reset(8, 16, 0)
        self.assertEqual(self.lib.rh_claim_mock(1, 1, 1), 0)
        self.lib.rh_freeze(1)
        self.assertEqual(self.lib.rh_send_mock(b'gfx.lvl', 9, 100), 4)
        self.assertLess(self.lib.rh_pause_count(), 200001)
        self.assertEqual(self.lib.rh_sleep_wake_unchanged(), 1)

    def test_failed_readback_quarantines(self):
        self.lib.rh_reset(8, 16, 1)
        self.assertEqual(self.lib.rh_claim_mock(1, 1, 1), 0)
        self.lib.rh_fail_irq_verify(1)
        self.assertEqual(self.lib.rh_send_mock(b'gfx.lvl', 9, 100), 4)
        self.assertEqual(self.lib.rh_quarantined(), 1)

    def test_invalid_selector_and_unsupported_layout_do_not_write(self):
        self.lib.rh_reset(8, 16, 1)
        self.assertEqual(self.lib.rh_claim_mock(1, 1, 1), 0)
        self.assertEqual(self.lib.rh_send_mock(b'vrm.cx', 0, 100), -100)
        self.assertEqual(self.lib.rh_write_count(), 0)
        self.lib.rh_reset(8, 15, 1)
        self.assertEqual(self.lib.rh_claim_mock(1, 1, 1), 2)
        self.assertEqual(self.lib.rh_send_mock(b'gfx.lvl', 9, 100), 6)
        self.assertEqual(self.lib.rh_write_count(), 0)

    def _adapter_probe(self, banks=8, ncpt=16, complete=1):
        self.lib.rh_reset(banks, ncpt, complete)
        self.lib.rh_adapter_reset()
        self.lib.rh_adapter_set_io()
        self.lib.rh_log_reset()
        self.lib.rh_boot_args(1, 0, 0)
        self.lib.rh_adapter_probe()

    def test_adapter_observation_path_never_writes(self):
        self._adapter_probe()
        self.assertEqual(self.lib.rh_write_count(), 0)
        self.assertIn(b'observation only', self.lib.rh_log())
        self.assertIn(b'config=0x80008104', self.lib.rh_log())

    def test_adapter_vote_refuses_before_geometry_and_level_checks(self):
        self._adapter_probe(8, 15)
        self.assertEqual(self.lib.rh_adapter_vote(0), 6)
        self.assertEqual(self.lib.rh_write_count(), 0)
        self._adapter_probe()
        self.assertEqual(self.lib.rh_adapter_vote(10), 1)
        self.assertEqual(self.lib.rh_write_count(), 0)

    def test_adapter_vote_refuses_dirty_or_stale_active_state(self):
        self._adapter_probe()
        self.lib.rh_occupy(0, 3, 0x30050)
        self.assertEqual(self.lib.rh_adapter_vote(0), 3)
        self.assertEqual(self.lib.rh_write_count(), 0)
        self._adapter_probe()
        self.lib.rh_set_irq(1)
        self.assertEqual(self.lib.rh_adapter_vote(0), 3)
        self.assertEqual(self.lib.rh_write_count(), 0)

    def test_adapter_single_shot_vote_acks_and_restores_tcs(self):
        self._adapter_probe()
        self.assertEqual(self.lib.rh_adapter_vote(0), 0)
        self.assertGreater(self.lib.rh_write_count(), 0)
        self.assertEqual(self.lib.rh_read_off(0xd00 + 0x14), 0)
        self.assertEqual(self.lib.rh_read_off(0xd00 + 0x1c), 0)
        self.assertEqual(self.lib.rh_read_off(0xd00 + 0x10), 0)
        self.assertEqual(self.lib.rh_adapter_quarantined(), 0)
        self.assertIn(b'post-vote IRQ status=0x0', self.lib.rh_log())
        writes = self.lib.rh_write_count()
        self.assertEqual(self.lib.rh_adapter_vote(0), 6)
        self.assertEqual(self.lib.rh_write_count(), writes)

    def test_adapter_timeout_quarantines_and_never_retries(self):
        self._adapter_probe(complete=0)
        self.assertEqual(self.lib.rh_adapter_vote(0), 4)
        self.assertEqual(self.lib.rh_adapter_quarantined(), 1)
        self.assertIn(b'failure snapshot', self.lib.rh_log())
        self.assertIn(b'TCS0 status=0x', self.lib.rh_log())
        writes = self.lib.rh_write_count()
        self.assertEqual(self.lib.rh_adapter_vote(0), 6)
        self.assertEqual(self.lib.rh_write_count(), writes)


if __name__ == '__main__':
    unittest.main()
