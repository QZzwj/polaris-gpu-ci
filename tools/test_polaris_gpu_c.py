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
        for number in range(94, 117):
            candidates = list(PATCHES.glob(f'{number:04}-*.patch'))
            if len(candidates) != 1:
                raise RuntimeError(f'expected one patch for {number:04}, got {candidates}')
            subprocess.run(['git', 'apply', '--include=bsd/dev/*',
                            str(candidates[0])],
                           cwd=root, check=True, capture_output=True)
            if number == 107:
                subprocess.run(['git', 'apply', '--include=bsd/dev/*',
                                str(next(PATCHES.glob('0107b-*.patch')))],
                               cwd=root, check=True, capture_output=True)
        subprocess.run(['git', 'apply', '--include=bsd/dev/*',
                        str(next(PATCHES.glob('0116b-*.patch')))],
                       cwd=root, check=True, capture_output=True)
        subprocess.run(['git', 'apply', '--include=bsd/dev/*',
                        str(next(PATCHES.glob('0117-*.patch')))],
                       cwd=root, check=True, capture_output=True)
        subprocess.run(['git', 'apply', '--include=bsd/dev/*',
                        str(next(PATCHES.glob('0118-*.patch')))],
                       cwd=root, check=True, capture_output=True)
        subprocess.run(['git', 'apply', '--include=bsd/dev/*',
                        str(next(PATCHES.glob('0119-*.patch')))],
                       cwd=root, check=True, capture_output=True)
        subprocess.run(['git', 'apply', '--include=bsd/dev/*',
                        str(next(PATCHES.glob('0120-*.patch')))],
                       cwd=root, check=True, capture_output=True)
        subprocess.run(['git', 'apply', '--include=bsd/dev/*',
                        str(next(PATCHES.glob('0121-*.patch')))],
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
            'typedef uintptr_t vm_offset_t;\ntypedef size_t vm_size_t;\n'
            'typedef uint64_t addr64_t;\ntypedef uint32_t ppnum_t;\n'
            'typedef struct pmap *pmap_t;\n'
            'struct pmap { int unused; };\n'
            'extern pmap_t kernel_pmap;\n'
            '#define PAGE_SHIFT 14\n'
            '#define PAGE_SIZE (1u << PAGE_SHIFT)\n'
            '#define PAGE_MASK (PAGE_SIZE - 1u)\n'
            '#define ptoa_64(pn) ((uint64_t)(pn) << PAGE_SHIFT)\n'
            'ppnum_t pmap_find_phys(pmap_t, addr64_t);\n')
        (root / 'include/vm/vm_kern.h').write_text(
            '#include <stdint.h>\n#include <stddef.h>\n'
            'typedef uintptr_t vm_offset_t;\ntypedef size_t vm_size_t;\n'
            'typedef int kern_return_t;\ntypedef void *vm_map_t;\n'
            'extern vm_map_t kernel_map;\n'
            '#define KERN_SUCCESS 0\n'
            '#define KMA_DATA 0x1\n#define KMA_ZERO 0x2\n#define KMA_PERMANENT 0x4\n'
            '#define VM_KERN_MEMORY_IOKIT 0\n'
            'kern_return_t kmem_alloc_contig(vm_map_t, vm_offset_t *, vm_size_t,\n'
            '    vm_offset_t, uint32_t, uint32_t, int, int);\n')
        (root / 'include/arm').mkdir()
        (root / 'include/arm/caches_internal.h').write_text(
            '#include <stdint.h>\n'
            'typedef uint64_t addr64_t;\n'
            'void flush_dcache64(addr64_t, unsigned, int);\n')
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
#include <vm/vm_kern.h>
#include <arm/caches_internal.h>
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
static uint32_t pll_regs[0x1000 / 4], pll_snapshot[0x1000 / 4];
static uint32_t gcc_axi_regs[0x1000 / 4], gcc_axi_snapshot[0x1000 / 4];
static uint32_t gcc_gfx_regs[0x1000 / 4], gcc_gfx_snapshot[0x1000 / 4];
/* The GMU window is 0x30000 bytes in the vendor DTS; keep it unaligned like
 * the real mapping so a stray +0x1000 bias is visible as a poisoned read. */
static uint32_t gmu_regs[0x30000 / 4], gmu_snapshot[0x30000 / 4];
/* GPU-GMU firmware page handed over by the fake ADT (blob 1). Only the
 * legacy 32 KiB image is used; entry word carries the Thumb bit. */
static uint32_t gmu_fw_regs[0x8000 / 4] = { 0x00043F80u, 0x00000009u };
#define SMMU_WINDOW 0x10000u
static uint32_t smmu_regs[SMMU_WINDOW / 4], smmu_snapshot[SMMU_WINDOW / 4];
#define PLL1_PAGE_OFFSET 0x100u
static int power_enabled, power_on_arg, power_smmu_arg, power_board, power_bad_map;
static int power_pll_bad_map;
static int power_bus_bad_map;
static int power_gmu_bad_map;
static int gmu_boot_arg, gmu_boot_fault;
static unsigned gmu_itcm_writes, gmu_itcm_first, gmu_itcm_last;
static unsigned gmu_bad_write;
static int hfi_arg, hfi_alloc_fault_mode, hfi_pa_high_mode;
static int hfi_ctrl_fault_mode, hfi_ack_fault_mode, hfi_ack_timeout_mode;
static unsigned hfi_alloc_count, hfi_flush_count;
static uint64_t hfi_pa = 0x80000000ull;
static uint32_t hfi_mem[0x8000 / 4];
static uint32_t hfi_reserved_mem[0x8000 / 4];
static uint32_t hfi_reserve_pa, hfi_reserve_size;
static int hfi_map_fault_mode;
static unsigned gmu_log_count, gmu_log_off[128], gmu_log_val[128];
static int power_smmu_bad_map;
static int power_model, power_clk_model, power_bus_model;
static unsigned power_maps, power_writes, power_cfg_ahb_write_count;
static unsigned smmu_syncs;
static int rh_diag_arg = 1, rh_vote_arg, rh_level_arg;
static char power_text[65536];
static size_t power_text_len;
int pg_test_printf(const char *fmt, ...) {
    va_list ap;
    if (power_text_len >= sizeof(power_text) - 1) return 0;
    size_t remaining = sizeof(power_text) - power_text_len;
    va_start(ap, fmt);
    int n = vsnprintf(power_text + power_text_len, remaining, fmt, ap);
    va_end(ap);
    if (n > 0) power_text_len += (size_t)n < remaining ? (size_t)n : remaining - 1;
    return n;
}
EXPORT void sweet_log_sync(void) {
    smmu_syncs++;
    pg_test_printf("<smmu-sync>");
}
EXPORT unsigned smmu_sync_count(void) { return smmu_syncs; }
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
    if (!strcmp(name, "polarisgpuon")) {
        memcpy(out, &power_on_arg, sizeof(power_on_arg));
        return power_on_arg != 0;
    }
    if (!strcmp(name, "polarisgmuboot")) {
        memcpy(out, &gmu_boot_arg, sizeof(gmu_boot_arg));
        return gmu_boot_arg != 0;
    }
    if (!strcmp(name, "polarishfi")) {
        memcpy(out, &hfi_arg, sizeof(hfi_arg));
        return hfi_arg != 0;
    }
    if (!strcmp(name, "polarissmmu")) {
        memcpy(out, &power_smmu_arg, sizeof(power_smmu_arg));
        return power_smmu_arg != 0;
    }
    if (!strcmp(name, "polarisgpupwr")) {
        memcpy(out, &power_enabled, sizeof(power_enabled));
        return power_enabled != 0;
    }
    memcpy(out, &power_enabled, sizeof(power_enabled));
    return 1;
}
vm_offset_t ml_io_map(vm_offset_t phys, vm_size_t size) {
    extern uint32_t rh_regs[];
    if (phys == 0x179e0000 && size == 0x4000u) return (vm_offset_t)rh_regs;
    power_maps++;
    if (phys == 0x8c420000ull && size == sizeof(hfi_reserved_mem)) {
        if (hfi_map_fault_mode) return 0;
        return (vm_offset_t)hfi_reserved_mem;
    }
    if (phys == 0x05090000 && size == sizeof(pll_regs)) {
        if (power_pll_bad_map) return 0;
        return (vm_offset_t)pll_regs;
    }
    if (phys == 0x00144000 && size == sizeof(gcc_axi_regs)) {
        if (power_bus_bad_map) return 0;
        return (vm_offset_t)gcc_axi_regs;
    }
    if (phys == 0x00171000 && size == sizeof(gcc_gfx_regs)) {
        if (power_bus_bad_map) return 0;
        return (vm_offset_t)gcc_gfx_regs;
    }
    if (phys == 0x0506a000 && size == sizeof(gmu_regs)) {
        if (power_gmu_bad_map) return 0;
        return (vm_offset_t)gmu_regs;
    }
    if (phys == 0x110010000ull && size == sizeof(gmu_fw_regs)) {
        return (vm_offset_t)gmu_fw_regs;
    }
    if (phys == 0x05040000 && size == sizeof(smmu_regs)) {
        if (power_smmu_bad_map) return 0;
        return (vm_offset_t)smmu_regs;
    }
    if (phys != 0x05091000 || size != sizeof(power_regs)) {
        power_bad_map = 1;
        return 0;
    }
    return (vm_offset_t)power_regs;
}
pmap_t kernel_pmap;
vm_map_t kernel_map = (vm_map_t)(uintptr_t)1;
ppnum_t pmap_find_phys(pmap_t pmap, addr64_t va) {
    (void)pmap; (void)va;
    if (hfi_pa_high_mode)
        return (ppnum_t)(0x40000u);   /* 0x40000 << 14 == 4 GiB */
    return (ppnum_t)(hfi_pa >> PAGE_SHIFT);
}
kern_return_t kmem_alloc_contig(vm_map_t map, vm_offset_t *addrp,
    vm_size_t size, vm_offset_t mask, uint32_t max_pnum, uint32_t pnum_mask,
    int flags, int tag) {
    (void)map; (void)mask; (void)max_pnum; (void)pnum_mask;
    (void)flags; (void)tag;
    hfi_alloc_count++;
    if (hfi_alloc_fault_mode == 1)
        return 1;
    if (size != sizeof(hfi_mem))
        return 2;
    memset(hfi_mem, 0, sizeof(hfi_mem));
    *addrp = (vm_offset_t)hfi_mem;
    return 0;
}
void flush_dcache64(addr64_t addr, unsigned count, int phys) {
    (void)addr; (void)count; (void)phys;
    hfi_flush_count++;
}
static void power_pll_init(void) {
    memset(pll_regs, 0, sizeof(pll_regs));
    memcpy(pll_snapshot, pll_regs, sizeof(pll_regs));
    power_pll_bad_map = 0;
}
static void power_bus_init(void) {
    for (unsigned i = 0; i < sizeof(gcc_axi_regs) / sizeof(gcc_axi_regs[0]); i++)
        gcc_axi_regs[i] = 0x5a5a5a5a;
    for (unsigned i = 0; i < sizeof(gcc_gfx_regs) / sizeof(gcc_gfx_regs[0]); i++)
        gcc_gfx_regs[i] = 0x5a5a5a5a;
    gcc_axi_regs[0x38 / 4] = 0x80000000;
    gcc_gfx_regs[0x0c / 4] = 0x80000000;
    gcc_gfx_regs[0x04 / 4] = 0x00000001;
    memcpy(gcc_axi_snapshot, gcc_axi_regs, sizeof(gcc_axi_regs));
    memcpy(gcc_gfx_snapshot, gcc_gfx_regs, sizeof(gcc_gfx_regs));
    power_bus_bad_map = 0;
    power_bus_model = 0;
    power_cfg_ahb_write_count = 0;
}
static void power_gmu_init(void) {
    for (unsigned i = 0; i < sizeof(gmu_regs) / sizeof(gmu_regs[0]); i++)
        gmu_regs[i] = 0x5a5a5a5a;
    gmu_regs[0x14000 / 4] = 0;          /* CM3_SYSRESET */
    gmu_regs[0x14004 / 4] = 0;          /* CM3_BOOT_CONFIG */
    gmu_regs[0x14068 / 4] = 0;          /* CM3_FW_BUSY */
    gmu_regs[0x14070 / 4] = 0;          /* CM3_FW_INIT_RESULT */
    gmu_regs[0x140b4 / 4] = 0;          /* CM3_CFG */
    gmu_regs[0x14600 / 4] = 0;          /* HFI_CTRL_STATUS */
    gmu_regs[0x14604 / 4] = 0x00010000; /* HFI_VERSION_INFO */
    gmu_regs[0x14610 / 4] = 0;          /* HFI_QTBL_INFO */
    gmu_regs[0x14648 / 4] = 0;          /* GMU2HOST_INTR_INFO */
    gmu_regs[0x1464c / 4] = 1;          /* GMU2HOST_INTR_MASK */
    gmu_regs[0x14730 / 4] = 0;          /* GENERAL_7 */
    gmu_regs[0x24c14 / 4] = 0;          /* AO_HOST_INTR_STATUS */
    gmu_regs[0x24c18 / 4] = 0;          /* AO_HOST_INTR_MASK */
    gmu_regs[0x24c30 / 4] = 0;          /* GPU_CX_BUSY_STATUS */
    gmu_regs[0x24c20 / 4] = 0;          /* RSCC_CONTROL_ACK */
    gmu_regs[0x24c4c / 4] = 0;          /* AHB_FENCE_STATUS */
    gmu_regs[0x14220 / 4] = 0x00000010; /* CX_ALWAYS_ON_CNT_L */
    gmu_regs[0x14224 / 4] = 0x00000002; /* CX_ALWAYS_ON_CNT_H */
    memcpy(gmu_snapshot, gmu_regs, sizeof(gmu_regs));
    gmu_boot_arg = 0;
    gmu_boot_fault = 0;
    gmu_itcm_writes = 0;
    gmu_itcm_first = 0;
    gmu_itcm_last = 0;
    gmu_bad_write = 0;
    hfi_arg = 0;
    hfi_alloc_fault_mode = 0;
    hfi_pa_high_mode = 0;
    hfi_ctrl_fault_mode = 0;
    hfi_ack_fault_mode = 0;
    hfi_ack_timeout_mode = 0;
    hfi_alloc_count = 0;
    hfi_flush_count = 0;
    hfi_pa = 0x80000000ull;
    memset(hfi_mem, 0, sizeof(hfi_mem));
    memset(hfi_reserved_mem, 0, sizeof(hfi_reserved_mem));
    hfi_reserve_pa = hfi_reserve_size = 0;
    hfi_map_fault_mode = 0;
    gmu_log_count = 0;
    memset(gmu_log_off, 0, sizeof(gmu_log_off));
    memset(gmu_log_val, 0, sizeof(gmu_log_val));
    power_gmu_bad_map = 0;
}
static void power_smmu_init(void) {
    for (unsigned i = 0; i < sizeof(smmu_regs) / sizeof(smmu_regs[0]); i++)
        smmu_regs[i] = 0x5a5a5a5a;
    /* Device IDR values: 5 SMR groups, SID bits 3, 1 context IRQ, 5
     * context banks, 4 KiB granule (IDR1.PAGESIZE clear). */
    smmu_regs[0x020 / 4] = 0x48016605; /* device IDR0 */
    smmu_regs[0x024 / 4] = 0x20008005; /* device IDR1: 4K, NUMCB=5 */
    smmu_regs[0x028 / 4] = 0x00007511; /* device IDR2 */
    /* The remaining IDR and global fault values are synthetic parser
     * coverage; they are not device observations. */
    smmu_regs[0x034 / 4] = 0x00000002;
    smmu_regs[0x038 / 4] = 0x00000000;
    smmu_regs[0x03c / 4] = 0x00000000;
    smmu_regs[0x040 / 4] = 0x00000000;
    smmu_regs[0x048 / 4] = 0x00000000;
    smmu_regs[0x050 / 4] = 0x00000000;
    smmu_regs[0x054 / 4] = 0x00000000;
    for (unsigned i = 0; i < 5; i++) {
        smmu_regs[(0x800 + i * 4) / 4] = 0x00000000; /* device: SMR invalid */
        smmu_regs[(0xc00 + i * 4) / 4] = 0x000200ff; /* device: FAULT, cbndx=0xff */
        smmu_regs[(0x1000 + i * 4) / 4] = (i << 24) | (i + 1); /* synthetic CBAR */
        smmu_regs[(0x8000 + i * 0x1000 + 0x58) / 4] = 0;       /* synthetic CB FSR */
    }
    memcpy(smmu_snapshot, smmu_regs, sizeof(smmu_regs));
    power_smmu_bad_map = 0;
}
void pg_pwr_test_reset(void);
void polaris_gpu_test_reset(void);
EXPORT const char *power_probe(unsigned write_probe, int enabled, int board) {
    for (unsigned i = 0; i < sizeof(power_regs) / sizeof(power_regs[0]); i++)
        power_regs[i] = 0x5a5a5a5a;
    power_regs[0x6c / 4] = 0x80000001;
    power_regs[0x540 / 4] = 0x11223344;
    power_regs[0x0c / 4] = 0xaabbccdd;
    power_regs[0x98 / 4] = 0x80004220;
    power_regs[0x120 / 4] = 0x80000000;
    power_regs[0x124 / 4] = 0;
    memcpy(power_snapshot, power_regs, sizeof(power_regs));
    power_enabled = enabled; power_on_arg = enabled; power_smmu_arg = 0;
    power_board = board;
    power_model = 0; power_clk_model = 0; power_bus_model = 0; power_writes = 0;
    power_maps = 0; power_bad_map = 0; power_text_len = 0; power_text[0] = 0;
    smmu_syncs = 0;
    pg_pwr_test_reset();
    power_pll_init();
    power_bus_init();
    power_gmu_init();
    power_smmu_init();
    if (write_probe) (void)polaris_gpu_rails_enter(); else polaris_gpu_pwr_probe();
    return power_text;
}
EXPORT unsigned power_map_count(void) { return power_maps; }
EXPORT int power_memory_unchanged(void) {
    return !power_bad_map && memcmp(power_snapshot, power_regs, sizeof(power_regs)) == 0;
}
void pg_pwr_test_after_write(unsigned page, uint32_t off, uint32_t value) {
    power_writes++;
    if (page == 3) {
        if (!(off >= 0x3000u && off < 0x3000u + 0x8000u) &&
            gmu_log_count < 128u) {
            gmu_log_off[gmu_log_count] = off;
            gmu_log_val[gmu_log_count] = value;
            gmu_log_count++;
        }
        if (off >= 0x3000u && off < 0x3000u + 0x8000u) {
            if (gmu_itcm_writes == 0) gmu_itcm_first = off;
            gmu_itcm_last = off;
            gmu_itcm_writes++;
        } else if (off != 0x14730u && off != 0x14000u && off != 0x14070u &&
                   off != 0x14004u && off != 0x140b4u && off != 0x24c44u &&
                   off != 0x14608u && off != 0x14610u && off != 0x14614u &&
                   off != 0x14618u && off != 0x14644u && off != 0x1464cu &&
                   off != 0x14650u && off != 0x13000u && off != 0x13004u &&
                   off != 0x1303cu && off != 0x14300u && off != 0x14308u &&
                   off != 0x14340u && off != 0x143a0u && off != 0x14400u &&
                   off != 0x14404u && off != 0x8fe0u && off != 0x8fe4u &&
                   off != 0x8fe8u && off != 0x204u) {
            gmu_bad_write = off;
        }
        if (off == 0x14000u && value == 0 && gmu_itcm_writes == 8192u &&
            !gmu_boot_fault)
            gmu_regs[0x14070 / 4] = 0xbabefaceu;
        if (off == 0x14618u && value == 1u && !hfi_ctrl_fault_mode)
            gmu_regs[0x14600 / 4] |= 1u;
        if (off == 0x14644u && value)
            gmu_regs[0x14648 / 4] &= ~value;
        if (off == 0x14650u && (value & (1u << 22)))
            gmu_regs[0x14648 / 4] |= (1u << 30);
        if (off == 0x204u && value == 0x00778000u)
            gmu_regs[0x14340 / 4] =
                (gmu_regs[0x14340 / 4] & ~0x38u) | 0x28u;
        if (off == 0x14650u && (value & 1u) && !hfi_ack_timeout_mode) {
            uint32_t *t = hfi_reserve_pa ? hfi_reserved_mem : hfi_mem;
            t[1070] = 0x0002137eu;             /* id=126 size=19 type=2 */
            t[1071] = 0x00100500u;             /* HFI_MSG_INIT */
            t[1072] = (uint32_t)hfi_ack_fault_mode;
            t[1073] = 0x11223344u;             /* synthetic payload */
            t[29] = 19;                        /* MSG write index */
            gmu_regs[0x14648 / 4] |= 1u;       /* GMU2HOST_INTR_INFO */
        }
        return;
    }
    if (page == 2) {
        uint32_t *regs = NULL;
        if (off == 0x38) regs = gcc_axi_regs;
        else if (off == 0x0c || off == 0x04) regs = gcc_gfx_regs;
        else { power_bad_map = 1; return; }
        if (off == 0x04) {
            power_cfg_ahb_write_count++;
            regs[off / 4] = value;
            return;
        }
        regs[off / 4] = value;
        if (value & 1u) {
            if ((off == 0x38 && power_bus_model == 1) ||
                (off == 0x0c && power_bus_model == 2))
                regs[off / 4] |= 0x80000000u;
            else
                regs[off / 4] &= ~0x80000000u;
        } else {
            regs[off / 4] |= 0x80000000u;
        }
        return;
    }
    if (page == 1) {
        /* Fabia PLL1: LOCK_DET appears once OPMODE=RUN with L/FRAC set. */
        if (off == 0x2c) {
            pll_regs[(PLL1_PAGE_OFFSET + 0x2c) / 4] = value;
            if (value == 1u && power_clk_model != 4 &&
                pll_regs[(PLL1_PAGE_OFFSET + 0x04) / 4] == 0x1au &&
                pll_regs[(PLL1_PAGE_OFFSET + 0x38) / 4] == 0xaabu)
                pll_regs[PLL1_PAGE_OFFSET / 4] |= 0x80000000u;
        } else {
            pll_regs[(PLL1_PAGE_OFFSET + off) / 4] = value;
        }
        return;
    }
    if (off == 0x6c && power_model == 1 && !(value & 1u))
        power_regs[0x6c / 4] = value | 0x80000000u;
    if (off == 0x6c && power_model == 2)
        power_regs[0x6c / 4] = value | 0x80000000u;
    if (off == 0x98) {
        uint32_t v = value;
        if (v & 1u) {
            if (power_clk_model == 3) v |= 0x80000000u;  /* halt never clears */
            else v &= ~0x80000000u;
        }
        power_regs[0x98 / 4] = v;
    }
    if (off == 0x120) {
        uint32_t v = value;
        if (power_clk_model == 1) v |= 0x80000000u;      /* ROOT_OFF stuck */
        else if (v & 2u) v &= ~0x80000000u;
        if ((power_clk_model == 2 || power_clk_model == 6) && (v & 1u)) {
            /* UPDATE never self-clears. */
        } else {
            v &= ~1u;
            v &= ~0x10u;
        }
        power_regs[0x120 / 4] = v;
    }
    if (off == 0x124) {
        if (power_clk_model == 5)
            power_regs[0x124 / 4] = 0;  /* CFG write never lands */
        else
            power_regs[0x124 / 4] = value;
        power_regs[0x120 / 4] |= 0x10u; /* CFG is dirty until UPDATE. */
    }
}
EXPORT void power_rails_reset(unsigned gdscr, int model, int on, int board) {
    for (unsigned i = 0; i < sizeof(power_regs) / sizeof(power_regs[0]); i++)
        power_regs[i] = 0x5a5a5a5a;
    power_regs[0x6c / 4] = gdscr;
    power_regs[0x98 / 4] = 0x80004220;
    power_regs[0x120 / 4] = 0x80000000;
    power_regs[0x124 / 4] = 0;
    power_enabled = on; power_on_arg = on; power_smmu_arg = 0; power_board = board;
    power_model = model; power_clk_model = 0; power_bus_model = 0; power_writes = 0;
    power_maps = 0; power_bad_map = 0; power_text_len = 0; power_text[0] = 0;
    smmu_syncs = 0;
    pg_pwr_test_reset();
    polaris_gpu_test_reset();
    power_pll_init();
    power_bus_init();
    power_gmu_init();
    power_smmu_init();
}
EXPORT int rails_enter(void) { return polaris_gpu_rails_enter(); }
EXPORT void rails_exit(void) { polaris_gpu_rails_exit(); }
EXPORT int clocks_enter(void) { return polaris_gpu_clocks_enter(); }
EXPORT void clocks_exit(void) { polaris_gpu_clocks_exit(); }
EXPORT int bus_enter(void) { return polaris_gpu_bus_enter(); }
EXPORT void bus_exit(void) { polaris_gpu_bus_exit(); }
EXPORT int gmu_enter(void) { return polaris_gpu_gmu_enter(); }
EXPORT int gmu_boot(uint64_t pa, unsigned size) {
    return polaris_gpu_gmu_boot(pa, size, hfi_reserve_pa, hfi_reserve_size);
}
EXPORT void hfi_reserve(uint64_t pa, unsigned size) {
    hfi_reserve_pa = (uint32_t)pa;
    hfi_reserve_size = size;
}
EXPORT void hfi_map_fault(int on) { hfi_map_fault_mode = on; }
EXPORT void power_gmu_boot_optin(int on) { gmu_boot_arg = on; }
EXPORT void power_gmu_boot_fault(unsigned mode) { gmu_boot_fault = (int)mode; }
EXPORT unsigned power_gmu_itcm_count(void) { return gmu_itcm_writes; }
EXPORT unsigned power_gmu_itcm_first(void) { return gmu_itcm_first; }
EXPORT unsigned power_gmu_itcm_last(void) { return gmu_itcm_last; }
EXPORT unsigned power_gmu_bad_off(void) { return gmu_bad_write; }
EXPORT void power_hfi_optin(int on) { hfi_arg = on; }
EXPORT void hfi_enable(int on) { hfi_arg = on; }
EXPORT int hfi_start(void) { return polaris_gpu_hfi_start(); }
EXPORT void hfi_alloc_fault(unsigned mode) { hfi_alloc_fault_mode = (int)mode; }
EXPORT void hfi_pa_high(int on) { hfi_pa_high_mode = on; }
EXPORT void hfi_ctrl_fault(int on) { hfi_ctrl_fault_mode = on; }
EXPORT void hfi_ack_fault(unsigned error) { hfi_ack_fault_mode = (int)error; }
EXPORT void hfi_ack_timeout(int on) { hfi_ack_timeout_mode = on; }
EXPORT unsigned hfi_table_word(unsigned i) {
    const uint32_t *table = hfi_reserve_pa ? hfi_reserved_mem : hfi_mem;
    return i < sizeof(hfi_mem) / sizeof(hfi_mem[0]) ? table[i] : 0;
}
EXPORT unsigned hfi_table_pa(void) { return (unsigned)hfi_pa; }
EXPORT unsigned hfi_alloc_count_get(void) { return hfi_alloc_count; }
EXPORT unsigned hfi_flush_count_get(void) { return hfi_flush_count; }
EXPORT unsigned gmu_write_count(void) { return gmu_log_count; }
EXPORT unsigned gmu_write_off(unsigned i) {
    return i < gmu_log_count ? gmu_log_off[i] : 0xffffffffu;
}
EXPORT unsigned gmu_write_val(unsigned i) {
    return i < gmu_log_count ? gmu_log_val[i] : 0xffffffffu;
}
EXPORT unsigned power_gmu_fw_word(unsigned i) {
    return i < sizeof(gmu_fw_regs) / sizeof(gmu_fw_regs[0]) ? gmu_fw_regs[i] : 0;
}
EXPORT int smmu_probe(void) { return polaris_gpu_smmu_probe(); }
EXPORT void power_smmu_optin(int level) { power_smmu_arg = level; }
EXPORT void power_clock_fault(unsigned mode) { power_clk_model = (int)mode; }
EXPORT void power_bus_fault(unsigned mode) { power_bus_model = (int)mode; }
EXPORT void power_bus_map_fault(int bad) { power_bus_bad_map = bad; }
EXPORT void power_gmu_map_fault(int bad) { power_gmu_bad_map = bad; }
EXPORT void power_smmu_map_fault(int bad) { power_smmu_bad_map = bad; }
EXPORT void power_boot_optin(int on) { power_on_arg = on; }
EXPORT unsigned power_reg(unsigned off) { return power_regs[off / 4]; }
EXPORT unsigned power_gcc_reg(unsigned which, unsigned off) {
    return (which ? gcc_gfx_regs : gcc_axi_regs)[off / 4];
}
EXPORT unsigned power_gmu_reg(unsigned off) { return gmu_regs[off / 4]; }
EXPORT void power_gmu_set(unsigned off, unsigned value) { gmu_regs[off / 4] = value; }
EXPORT int power_gmu_unchanged(void) {
    return !power_gmu_bad_map &&
        memcmp(gmu_snapshot, gmu_regs, sizeof(gmu_regs)) == 0;
}
EXPORT unsigned power_smmu_reg(unsigned off) { return smmu_regs[off / 4]; }
EXPORT void power_smmu_set(unsigned off, unsigned value) { smmu_regs[off / 4] = value; }
EXPORT int power_smmu_unchanged(void) {
    return !power_smmu_bad_map &&
        memcmp(smmu_snapshot, smmu_regs, sizeof(smmu_regs)) == 0;
}
EXPORT unsigned power_pll_reg(unsigned off) { return pll_regs[(PLL1_PAGE_OFFSET + off) / 4]; }
EXPORT void power_pll_set(unsigned off, unsigned value) { pll_regs[(PLL1_PAGE_OFFSET + off) / 4] = value; }
EXPORT void power_pll_snapshot(void) { memcpy(pll_snapshot, pll_regs, sizeof(pll_regs)); }
EXPORT int power_pll_unchanged(void) {
    return memcmp(pll_snapshot, pll_regs, sizeof(pll_regs)) == 0;
}
EXPORT void power_pll_map_fault(int bad) { power_pll_bad_map = bad; }
EXPORT unsigned power_write_count(void) { return power_writes; }
EXPORT unsigned power_cfg_ahb_writes(void) { return power_cfg_ahb_write_count; }
EXPORT int power_bus_unchanged(void) {
    return !power_bus_bad_map &&
        memcmp(gcc_axi_snapshot, gcc_axi_regs, sizeof(gcc_axi_regs)) == 0 &&
        memcmp(gcc_gfx_snapshot, gcc_gfx_regs, sizeof(gcc_gfx_regs)) == 0;
}
EXPORT const char *power_log(void) { return power_text; }
/* Fake ADT properties deliberately start at unaligned addresses, as real ADT
 * properties may. No firmware bytes, MMIO or device are needed by this test. */
static const char *const blob_names[6] = {
    "GPU-SQE", "GPU-GMU", "GPU-ZAP-MDT", "GPU-ZAP-B00", "GPU-ZAP-B01", "GPU-ZAP-B02"
};
static uint64_t dt_dram[2];
static unsigned char dt_blob[6][17];
static unsigned dt_blob_len[6], dt_reads;
static unsigned char dt_hfi[17];
static unsigned dt_hfi_len;
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
    if (!strcmp(name, "GPU-HFI") && dt_hfi_len) {
        *out = &dt_hfi[1];
        *len = dt_hfi_len;
        return kSuccess;
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
EXPORT void diag_set_hfi(uint64_t addr, uint64_t size, unsigned len) {
    memcpy(&dt_hfi[1], &addr, 8);
    memcpy(&dt_hfi[9], &size, 8);
    dt_hfi_len = len;
}
EXPORT void diag_reset(int historical, int enabled, int board) {
    const unsigned sizes[6] = {31980, 32768, 6684, 148, 6536, 1968};
    power_enabled = enabled; power_on_arg = enabled; power_smmu_arg = 0;
    power_board = board;
    power_model = 0; power_writes = 0; pg_pwr_test_reset();
    polaris_gpu_test_reset();
    smmu_syncs = 0;
    power_gmu_init();
    power_smmu_init();
    dt_hfi_len = 0;
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
                           '-DARM64_BOARD_CONFIG_SWEET=1', '-DPG_RH_TEST', '-DPG_PWR_TEST',
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
        cls.lib.power_rails_reset.argtypes = [ctypes.c_uint, ctypes.c_int,
                                              ctypes.c_int, ctypes.c_int]
        cls.lib.rails_enter.restype = ctypes.c_int
        cls.lib.clocks_enter.restype = ctypes.c_int
        cls.lib.bus_enter.restype = ctypes.c_int
        cls.lib.bus_exit.restype = None
        cls.lib.gmu_enter.restype = ctypes.c_int
        cls.lib.gmu_boot.argtypes = [ctypes.c_uint64, ctypes.c_uint]
        cls.lib.gmu_boot.restype = ctypes.c_int
        cls.lib.power_gmu_boot_optin.argtypes = [ctypes.c_int]
        cls.lib.power_gmu_boot_fault.argtypes = [ctypes.c_uint]
        cls.lib.power_gmu_itcm_count.restype = ctypes.c_uint
        cls.lib.power_gmu_itcm_first.restype = ctypes.c_uint
        cls.lib.power_gmu_itcm_last.restype = ctypes.c_uint
        cls.lib.power_gmu_bad_off.restype = ctypes.c_uint
        cls.lib.power_gmu_fw_word.argtypes = [ctypes.c_uint]
        cls.lib.power_gmu_fw_word.restype = ctypes.c_uint
        cls.lib.power_hfi_optin.argtypes = [ctypes.c_int]
        cls.lib.hfi_enable.argtypes = [ctypes.c_int]
        cls.lib.hfi_start.restype = ctypes.c_int
        cls.lib.hfi_alloc_fault.argtypes = [ctypes.c_uint]
        cls.lib.hfi_pa_high.argtypes = [ctypes.c_int]
        cls.lib.hfi_ctrl_fault.argtypes = [ctypes.c_int]
        cls.lib.hfi_ack_fault.argtypes = [ctypes.c_uint]
        cls.lib.hfi_ack_timeout.argtypes = [ctypes.c_int]
        cls.lib.hfi_reserve.argtypes = [ctypes.c_uint64, ctypes.c_uint]
        cls.lib.hfi_map_fault.argtypes = [ctypes.c_int]
        cls.lib.hfi_table_word.argtypes = [ctypes.c_uint]
        cls.lib.hfi_table_word.restype = ctypes.c_uint
        cls.lib.hfi_table_pa.restype = ctypes.c_uint
        cls.lib.hfi_alloc_count_get.restype = ctypes.c_uint
        cls.lib.hfi_flush_count_get.restype = ctypes.c_uint
        cls.lib.gmu_write_count.restype = ctypes.c_uint
        cls.lib.gmu_write_off.argtypes = [ctypes.c_uint]
        cls.lib.gmu_write_off.restype = ctypes.c_uint
        cls.lib.gmu_write_val.argtypes = [ctypes.c_uint]
        cls.lib.gmu_write_val.restype = ctypes.c_uint
        cls.lib.smmu_probe.restype = ctypes.c_int
        cls.lib.power_gmu_map_fault.argtypes = [ctypes.c_int]
        cls.lib.power_smmu_map_fault.argtypes = [ctypes.c_int]
        cls.lib.power_smmu_optin.argtypes = [ctypes.c_int]
        cls.lib.power_gmu_reg.argtypes = [ctypes.c_uint]
        cls.lib.power_gmu_reg.restype = ctypes.c_uint
        cls.lib.power_gmu_set.argtypes = [ctypes.c_uint, ctypes.c_uint]
        cls.lib.power_gmu_unchanged.restype = ctypes.c_int
        cls.lib.power_smmu_reg.argtypes = [ctypes.c_uint]
        cls.lib.power_smmu_reg.restype = ctypes.c_uint
        cls.lib.power_smmu_set.argtypes = [ctypes.c_uint, ctypes.c_uint]
        cls.lib.power_smmu_unchanged.restype = ctypes.c_int
        cls.lib.smmu_sync_count.restype = ctypes.c_uint
        cls.lib.power_bus_fault.argtypes = [ctypes.c_uint]
        cls.lib.power_bus_map_fault.argtypes = [ctypes.c_int]
        cls.lib.power_boot_optin.argtypes = [ctypes.c_int]
        cls.lib.power_reg.argtypes = [ctypes.c_uint]
        cls.lib.power_reg.restype = ctypes.c_uint
        cls.lib.power_gcc_reg.argtypes = [ctypes.c_uint, ctypes.c_uint]
        cls.lib.power_gcc_reg.restype = ctypes.c_uint
        cls.lib.power_pll_reg.argtypes = [ctypes.c_uint]
        cls.lib.power_pll_reg.restype = ctypes.c_uint
        cls.lib.power_pll_set.argtypes = [ctypes.c_uint, ctypes.c_uint]
        cls.lib.power_pll_unchanged.restype = ctypes.c_int
        cls.lib.power_pll_map_fault.argtypes = [ctypes.c_int]
        cls.lib.power_write_count.restype = ctypes.c_uint
        cls.lib.power_cfg_ahb_writes.restype = ctypes.c_uint
        cls.lib.power_bus_unchanged.restype = ctypes.c_int
        cls.lib.power_log.restype = ctypes.c_char_p
        cls.lib.power_map_count.restype = ctypes.c_uint
        cls.lib.power_memory_unchanged.restype = ctypes.c_int
        cls.lib.diag_reset.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        cls.lib.diag_set_blob.argtypes = [ctypes.c_uint, ctypes.c_uint64,
                                         ctypes.c_uint64, ctypes.c_uint]
        cls.lib.diag_set_dram.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
        cls.lib.diag_set_hfi.argtypes = [ctypes.c_uint64, ctypes.c_uint64,
                                        ctypes.c_uint]
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
        # 0x208 is the recovery DTB's SMMU provider phandle, not a SID.
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
                log = self.lib.power_probe(write, enabled, board)
                expected = (b'POLARIS PWR: rails write not opt-in; CX untouched\n'
                            if write and board and not enabled else b'')
                self.assertEqual(log, expected)
                self.assertEqual(self.lib.power_map_count(), 0)
                self.assertEqual(self.lib.power_write_count(), 0)
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

    def test_bringup_rails_refuses_foreign_on_domain_without_write(self):
        # Both power flags are 1 in this mock, but the inherited PWR_ON=1 bit
        # means the domain belongs to someone else. The stage may observe it,
        # never write or claim it, and the CPU display must remain.
        self.lib.power_probe(0, 1, 1)
        self.lib.diag_reset(0, 1, 1)
        log = self.lib.diag_run(1).decode()
        self.assertIn('CX GDSCR before=0x80000001', log)
        self.assertIn('CX already on and not ours; no write, no ownership', log)
        self.assertIn('rails request refused; no ownership claimed', log)
        self.assertIn('acceleration unavailable; CPU display unchanged', log)
        self.assertEqual(self.lib.power_map_count(), 2)
        self.assertEqual(self.lib.power_memory_unchanged(), 1)

    def test_rails_requires_optin_and_board_before_mapping(self):
        for on, board in ((0, 1), (1, 0)):
            self.lib.power_rails_reset(0x00222001, 1, on, board)
            self.assertEqual(self.lib.rails_enter(), 0)
            self.assertEqual(self.lib.power_map_count(), 0)
            self.assertEqual(self.lib.power_write_count(), 0)
            self.assertEqual(self.lib.power_reg(0x6c), 0x00222001)

    def test_rails_foreign_on_domain_is_observed_without_write(self):
        self.lib.power_rails_reset(0x80000001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 0)
        log = self.lib.power_log().decode()
        self.assertIn('CX GDSCR before=0x80000001', log)
        self.assertIn('already on and not ours', log)
        self.assertEqual(self.lib.power_write_count(), 0)
        self.assertEqual(self.lib.power_reg(0x6c), 0x80000001)

    def test_rails_timeout_restores_original_and_claims_nothing(self):
        self.lib.power_rails_reset(0x00222001, 0, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 0)
        log = self.lib.power_log().decode()
        self.assertIn('timed out after 200 polls', log)
        self.assertIn('domain not claimed', log)
        self.assertEqual(self.lib.power_reg(0x6c), 0x00222001)
        self.assertEqual(self.lib.power_write_count(), 2)

    def test_rails_enter_owns_pwr_on_and_exit_restores_exact_value(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        log = self.lib.power_log().decode()
        self.assertIn('CX owned, rollback=0x00222001', log)
        self.assertEqual(self.lib.power_reg(0x6c), 0x80222000)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.power_write_count(), 1)
        self.lib.rails_exit()
        log = self.lib.power_log().decode()
        self.assertIn('rails exit collapsed after 1 polls GDSCR=0x00222001; CX released', log)
        self.assertEqual(self.lib.power_reg(0x6c), 0x00222001)
        self.assertEqual(self.lib.power_write_count(), 2)

    def test_rails_exit_reports_unconfirmed_when_pwr_on_sticks(self):
        # Model 2 keeps PWR_ON set after every GDSCR write. Enter may still
        # claim the domain (it saw PWR_ON), but exit must not claim release.
        self.lib.power_rails_reset(0x00222001, 2, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.lib.rails_exit()
        log = self.lib.power_log().decode()
        self.assertIn('wrote 0x00222001 but PWR_ON stayed set for 200 polls', log)
        self.assertIn('CX state unconfirmed', log)
        self.assertNotIn('CX released', log)
        self.assertEqual(self.lib.power_reg(0x6c), 0x80222001)
        self.assertEqual(self.lib.power_write_count(), 2)
        self.lib.rails_exit()
        self.assertEqual(self.lib.power_write_count(), 2)

    def test_clocks_enter_starts_gmu_source_and_branch_then_exit_restores(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        log = self.lib.power_log().decode()
        self.assertIn('clocks enter cx_gmu_cbcr=0x80004220', log)
        self.assertIn('gmu clock parent pll1', log)
        self.assertIn('PLL1 locked after', log)
        self.assertIn('gmu clock source root on; cfg=0x00000300', log)
        self.assertIn('gmu branch enabled; CBCR=0x00004ff1', log)
        self.assertEqual(self.lib.power_pll_reg(0x00) & 0x80000005, 0x80000005)
        self.assertEqual(self.lib.power_pll_reg(0x04), 0x0000001a)
        self.assertEqual(self.lib.power_pll_reg(0x0c) & 0x7, 0x7)
        self.assertEqual(self.lib.power_pll_reg(0x2c), 0x00000001)
        self.assertEqual(self.lib.power_pll_reg(0x38), 0x00000aab)
        self.assertEqual(self.lib.power_reg(0x98), 0x00004ff1)
        self.assertEqual(self.lib.power_reg(0x120), 0x00000000)
        self.assertEqual(self.lib.power_reg(0x124), 0x00000300)
        self.lib.clocks_exit()
        log = self.lib.power_log().decode()
        self.assertIn('clocks exit restored cbcr=0x80004220 '
                      'cmd=0x80000000 cfg=0x00000000', log)
        self.assertEqual(self.lib.power_reg(0x98), 0x80004220)
        self.assertEqual(self.lib.power_reg(0x120), 0x80000000)
        self.assertEqual(self.lib.power_reg(0x124), 0)
        self.assertEqual(self.lib.power_reg(0x120) & 0x10, 0)
        self.assertEqual(self.lib.power_bus_unchanged(), 1)
        self.assertEqual(self.lib.power_reg(0x6c), 0x80222000)
        self.assertEqual(self.lib.power_pll_unchanged(), 1)

    def test_clocks_refuse_without_cx_ownership(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.clocks_enter(), 0)
        self.assertIn('clocks refused; CX not owned', self.lib.power_log().decode())
        self.assertEqual(self.lib.power_write_count(), 0)
        self.assertEqual(self.lib.power_reg(0x98), 0x80004220)

    def test_clocks_root_off_timeout_rolls_back_all_three(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.lib.power_clock_fault(1)
        self.assertEqual(self.lib.clocks_enter(), 0)
        log = self.lib.power_log().decode()
        self.assertIn('GMU clock bring-up failed; rolled back', log)
        self.assertEqual(self.lib.power_reg(0x98), 0x80004220)
        self.assertEqual(self.lib.power_reg(0x120), 0x80000000)
        self.assertEqual(self.lib.power_reg(0x124), 0)

    def test_clocks_update_busy_times_out_and_rolls_back(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.lib.power_clock_fault(2)
        self.assertEqual(self.lib.clocks_enter(), 0)
        self.assertIn('GMU clock bring-up failed; rolled back',
                      self.lib.power_log().decode())
        self.assertEqual(self.lib.power_reg(0x98), 0x80004220)
        self.assertEqual(self.lib.power_reg(0x120), 0x80000000)
        self.assertEqual(self.lib.power_reg(0x124), 0)

    def test_clocks_branch_halt_timeout_rolls_back(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.lib.power_clock_fault(3)
        self.assertEqual(self.lib.clocks_enter(), 0)
        self.assertIn('GMU clock bring-up failed; rolled back',
                      self.lib.power_log().decode())
        self.assertEqual(self.lib.power_reg(0x98), 0x80004220)
        self.assertEqual(self.lib.power_reg(0x120), 0x80000000)
        self.assertEqual(self.lib.power_reg(0x124), 0)

    def test_clocks_touch_pll1_but_never_gx_and_restore_it(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        gx = self.lib.power_reg(0x0c)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertEqual(self.lib.power_reg(0x0c), gx)
        self.assertEqual(self.lib.power_pll_reg(0x00) & 0x80000005, 0x80000005)
        self.assertEqual(self.lib.power_map_count(), 2)
        self.lib.clocks_exit()
        self.assertEqual(self.lib.power_reg(0x0c), gx)
        self.assertEqual(self.lib.power_pll_unchanged(), 1)

    def test_clocks_pll_lock_timeout_restores_and_falls_back_to_gpll0(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.lib.power_clock_fault(4)
        self.assertEqual(self.lib.clocks_enter(), 1)
        log = self.lib.power_log().decode()
        self.assertIn('PLL1 lock timeout', log)
        self.assertIn('gmu clock parent gpll0 (PLL1 unavailable)', log)
        self.assertIn('gmu clock source root on; cfg=0x00000602', log)
        self.assertEqual(self.lib.power_reg(0x124), 0x00000602)
        self.assertEqual(self.lib.power_pll_unchanged(), 1)

    def test_clocks_pll_fsm_busy_is_refused_without_writes(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.lib.power_pll_set(0x00, 0x00100000)
        self.lib.power_pll_snapshot()
        self.assertEqual(self.lib.clocks_enter(), 1)
        log = self.lib.power_log().decode()
        self.assertIn('refusing to fight the FSM', log)
        self.assertIn('gmu clock parent gpll0 (PLL1 unavailable)', log)
        self.assertEqual(self.lib.power_reg(0x124), 0x00000602)
        self.assertEqual(self.lib.power_pll_unchanged(), 1)

    def test_clocks_pll_already_running_exit_leaves_it_alone(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.lib.power_pll_set(0x00, 0x80000001)
        self.lib.power_pll_set(0x04, 0x0000001a)
        self.lib.power_pll_set(0x2c, 0x00000001)
        self.lib.power_pll_set(0x38, 0x00000aab)
        self.lib.power_pll_snapshot()
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertIn('already running at 500 MHz',
                      self.lib.power_log().decode())
        self.assertEqual(self.lib.power_reg(0x124), 0x00000300)
        self.lib.clocks_exit()
        self.assertEqual(self.lib.power_pll_unchanged(), 1)

    def test_clocks_pll_map_failure_falls_back_to_gpll0(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.lib.power_pll_map_fault(1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        log = self.lib.power_log().decode()
        self.assertIn('cannot map GPUCC PLL1 page; falling back to GPLL0', log)
        self.assertIn('gmu clock parent gpll0 (PLL1 unavailable)', log)
        self.assertEqual(self.lib.power_reg(0x124), 0x00000602)

    def test_clocks_cfg_write_fault_rolls_back_and_restores_pll(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.lib.power_clock_fault(5)
        self.assertEqual(self.lib.clocks_enter(), 0)
        self.assertIn('GMU clock bring-up failed; rolled back',
                      self.lib.power_log().decode())
        self.assertEqual(self.lib.power_reg(0x124), 0)
        self.assertEqual(self.lib.power_pll_unchanged(), 1)

    def test_clocks_update_stuck_after_cfg_rolls_back_and_restores_pll(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.lib.power_clock_fault(6)
        self.assertEqual(self.lib.clocks_enter(), 0)
        self.assertIn('GMU clock bring-up failed; rolled back',
                      self.lib.power_log().decode())
        self.assertEqual(self.lib.power_reg(0x124), 0)
        self.assertEqual(self.lib.power_pll_unchanged(), 1)

    def test_bus_refuses_without_owned_clocks_before_mapping(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.bus_enter(), 0)
        self.assertIn('bus refused; clocks not owned', self.lib.power_log().decode())
        self.assertEqual(self.lib.power_map_count(), 0)
        self.assertEqual(self.lib.power_write_count(), 0)

    def test_bus_requires_separate_optin_after_clocks(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        maps = self.lib.power_map_count()
        writes = self.lib.power_write_count()
        self.lib.power_boot_optin(0)
        self.assertEqual(self.lib.bus_enter(), 0)
        self.assertIn('bus write not opt-in; bus untouched',
                      self.lib.power_log().decode())
        self.assertEqual(self.lib.power_map_count(), maps)
        self.assertEqual(self.lib.power_write_count(), writes)
        self.assertEqual(self.lib.power_gcc_reg(0, 0x38), 0x80000000)
        self.assertEqual(self.lib.power_gcc_reg(1, 0x0c), 0x80000000)

    def test_bus_axi_timeout_restores_axi_and_leaves_memnoc(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.lib.power_bus_fault(1)
        self.assertEqual(self.lib.bus_enter(), 0)
        log = self.lib.power_log().decode()
        self.assertIn('bus axi halt timeout after 200 polls; '
                      'axi restored=0x80000000; memnoc untouched=0x80000000', log)
        self.assertEqual(self.lib.power_gcc_reg(0, 0x38), 0x80000000)
        self.assertEqual(self.lib.power_gcc_reg(1, 0x0c), 0x80000000)
        self.assertEqual(self.lib.power_cfg_ahb_writes(), 0)

    def test_bus_memnoc_timeout_restores_memnoc_then_axi(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.lib.power_bus_fault(2)
        self.assertEqual(self.lib.bus_enter(), 0)
        log = self.lib.power_log().decode()
        self.assertIn('bus memnoc halt timeout after 200 polls; '
                      'memnoc restored=0x80000000 axi restored=0x80000000', log)
        self.assertEqual(self.lib.power_gcc_reg(0, 0x38), 0x80000000)
        self.assertEqual(self.lib.power_gcc_reg(1, 0x0c), 0x80000000)
        self.assertEqual(self.lib.power_cfg_ahb_writes(), 0)

    def test_bus_enables_both_branches_readonly_cfg_ahb_and_exit_restores(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertEqual(self.lib.bus_enter(), 1)
        log = self.lib.power_log().decode()
        self.assertIn('bus enter axi=0x80000000 memnoc=0x80000000 '
                      'cfg_ahb=0x00000001', log)
        self.assertIn('bus axi enabled after 1 polls; CBCR=0x00000001', log)
        self.assertIn('bus memnoc enabled after 1 polls; CBCR=0x00000001', log)
        self.assertEqual(self.lib.power_gcc_reg(0, 0x38), 0x00000001)
        self.assertEqual(self.lib.power_gcc_reg(1, 0x0c), 0x00000001)
        self.assertEqual(self.lib.power_gcc_reg(1, 0x04), 0x00000001)
        self.assertEqual(self.lib.power_cfg_ahb_writes(), 0)
        self.assertEqual(self.lib.bus_enter(), 1)
        self.lib.bus_exit()
        log = self.lib.power_log().decode()
        self.assertIn('bus exit restored axi=0x80000000 memnoc=0x80000000 '
                      'cfg_ahb=0x00000001', log)
        self.assertEqual(self.lib.power_gcc_reg(0, 0x38), 0x80000000)
        self.assertEqual(self.lib.power_gcc_reg(1, 0x0c), 0x80000000)
        self.lib.bus_exit()
        self.assertEqual(self.lib.power_gcc_reg(0, 0x38), 0x80000000)

    def test_bus_failed_second_map_claims_nothing(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.lib.power_bus_map_fault(1)
        self.assertEqual(self.lib.bus_enter(), 0)
        self.assertIn('cannot map GCC GPU AXI branch page',
                      self.lib.power_log().decode())
        self.assertEqual(self.lib.power_gcc_reg(0, 0x38), 0x80000000)
        self.assertEqual(self.lib.power_gcc_reg(1, 0x0c), 0x80000000)

    def test_gmu_refuses_without_bus_before_mapping(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        maps = self.lib.power_map_count()
        writes = self.lib.power_write_count()
        self.assertEqual(self.lib.gmu_enter(), 0)
        self.assertIn('gmu refused; bus not owned', self.lib.power_log().decode())
        self.assertEqual(self.lib.power_map_count(), maps)
        self.assertEqual(self.lib.power_write_count(), writes)

    def test_gmu_reads_identify_registers_without_any_write(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertEqual(self.lib.bus_enter(), 1)
        writes = self.lib.power_write_count()
        self.assertEqual(self.lib.gmu_enter(), 1)
        log = self.lib.power_log().decode()
        self.assertIn('GMU CSR sysreset=0x00000000 boot=0x00000000 '
                      'cfg=0x00000000 fw_busy=0x00000000 init=0x00000000', log)
        self.assertIn('GMU HFI status=0x00000000 version=0x00010000 '
                      'qtbl_info=0x00000000 general7=0x00000000', log)
        self.assertIn('GMU AO intr_status=0x00000000 mask=0x00000000 '
                      'cx_busy=0x00000000 rscc_ack=0x00000000 fence=0x00000000', log)
        self.assertIn('GMU cx_always_on=0x0000000200000010; registers readable, '
                      'fw=not-started, hfi=not-initialized', log)
        self.assertEqual(self.lib.power_write_count(), writes)
        self.assertEqual(self.lib.power_gmu_unchanged(), 1)

    def test_gmu_decodes_firmware_magic_without_writing(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertEqual(self.lib.bus_enter(), 1)
        self.lib.power_gmu_set(0x14070, 0xbabeface)
        self.lib.power_gmu_set(0x14600, 1)
        writes = self.lib.power_write_count()
        self.assertEqual(self.lib.gmu_enter(), 1)
        log = self.lib.power_log().decode()
        self.assertIn('fw=mainline-magic, hfi=initialized', log)
        self.assertEqual(self.lib.power_write_count(), writes)

    def test_gmu_map_failure_claims_nothing(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertEqual(self.lib.bus_enter(), 1)
        self.lib.power_gmu_map_fault(1)
        writes = self.lib.power_write_count()
        self.assertEqual(self.lib.gmu_enter(), 0)
        self.assertIn('cannot map GMU CSRs; probe skipped',
                      self.lib.power_log().decode())
        self.assertEqual(self.lib.power_write_count(), writes)

    def test_gmu_boot_requires_optin_and_writes_nothing(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertEqual(self.lib.bus_enter(), 1)
        writes = self.lib.power_write_count()
        self.assertEqual(self.lib.gmu_boot(0x110010000, 0x8000), 0)
        self.assertIn('gmu boot not opt-in; CM3 untouched',
                      self.lib.power_log().decode())
        self.assertEqual(self.lib.power_write_count(), writes)
        self.assertEqual(self.lib.power_gmu_unchanged(), 1)

    def test_gmu_boot_refuses_bad_size_or_alignment(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertEqual(self.lib.bus_enter(), 1)
        self.lib.power_gmu_boot_optin(1)
        writes = self.lib.power_write_count()
        self.assertEqual(self.lib.gmu_boot(0x110010000, 0x7fff), 0)
        self.assertIn('size=32767 expected=32768',
                      self.lib.power_log().decode())
        self.assertEqual(self.lib.gmu_boot(0x110010001, 0x8000), 0)
        self.assertIn('not page aligned', self.lib.power_log().decode())
        self.assertEqual(self.lib.power_write_count(), writes)

    def test_gmu_boot_loads_itcm_and_completes(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertEqual(self.lib.bus_enter(), 1)
        self.lib.power_gmu_boot_optin(1)
        self.assertEqual(self.lib.gmu_boot(0x110010000, 0x8000), 1)
        log = self.lib.power_log().decode()
        self.assertIn('GMU fw pa=0x110010000 size=32768 word0=0x00043f80 '
                      'entry=0x00000009 last=0x00000000', log)
        self.assertIn('GMU ITCM loaded 8192 words; readback first=0x00043f80 '
                      'last=0x00000000', log)
        self.assertIn('GMU boot complete init=0xbabeface fw_busy=0x00000000 '
                      'cfg=0x00004052 general7=0x00000001 hfi_status=0x00000000; '
                      'HFI not initialized', log)
        self.assertEqual(self.lib.power_gmu_itcm_count(), 8192)
        self.assertEqual(self.lib.power_gmu_itcm_first(), 0x3000)
        self.assertEqual(self.lib.power_gmu_itcm_last(), 0xaffc)
        self.assertEqual(self.lib.power_gmu_bad_off(), 0)
        self.assertEqual(self.lib.power_gmu_reg(0x14000), 0)
        self.assertEqual(self.lib.power_gmu_reg(0x14070), 0xbabeface)
        self.assertEqual(self.lib.power_gmu_reg(0x14610), 0)
        self.assertEqual(self.lib.power_gmu_reg(0x14614), 0x5a5a5a5a)
        self.assertEqual(self.lib.power_gmu_reg(0x14618), 0x5a5a5a5a)

    def test_gmu_boot_timeout_holds_cm3_in_reset(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertEqual(self.lib.bus_enter(), 1)
        self.lib.power_gmu_boot_optin(1)
        self.lib.power_gmu_boot_fault(1)
        self.assertEqual(self.lib.gmu_boot(0x110010000, 0x8000), 0)
        log = self.lib.power_log().decode()
        self.assertIn('GMU boot timed out; init=0x00000000 boot=0x00000002 '
                      'cfg=0x00004052 fw_busy=0x00000000; CM3 held in reset', log)
        self.assertEqual(self.lib.power_gmu_reg(0x14000), 1)

    def _boot_gmu(self, hfi=True, ctrl_fault=0, alloc_fault=0, pa_high=0,
                  reserve=None, map_fault=0):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertEqual(self.lib.bus_enter(), 1)
        self.lib.power_gmu_boot_optin(1)
        if hfi:
            self.lib.power_hfi_optin(1)
        if ctrl_fault:
            self.lib.hfi_ctrl_fault(1)
        if alloc_fault:
            self.lib.hfi_alloc_fault(1)
        if pa_high:
            self.lib.hfi_pa_high(1)
        if reserve:
            self.lib.hfi_reserve(*reserve)
        if map_fault:
            self.lib.hfi_map_fault(1)
        return self.lib.gmu_boot(0x110010000, 0x8000)

    def test_hfi_disabled_allocates_nothing(self):
        self.assertEqual(self._boot_gmu(hfi=False), 1)
        log = self.lib.power_log().decode()
        self.assertIn('HFI not initialized', log)
        self.assertEqual(self.lib.hfi_alloc_count_get(), 0)
        self.assertEqual(self.lib.hfi_flush_count_get(), 0)
        self.assertEqual(self.lib.power_gmu_reg(0x14610), 0)
        self.assertEqual(self.lib.power_gmu_reg(0x14614), 0x5a5a5a5a)
        self.assertEqual(self.lib.power_gmu_reg(0x14618), 0x5a5a5a5a)

    def test_hfi_table_layout_matches_kgsl(self):
        self.assertEqual(self._boot_gmu(), 1)
        self.assertEqual(self.lib.hfi_table_pa(), 0x80000000)
        self.assertEqual([self.lib.hfi_table_word(i) for i in range(6)],
                         [0, 42, 6, 12, 3, 3])
        types = [0x0a00, 0x0a04, 0x2805]
        for i, qtype in enumerate(types):
            base = 6 + 12 * i
            q = [self.lib.hfi_table_word(base + j) for j in range(12)]
            self.assertEqual(q, [1, (0x80000000 + 168 + 4112 * i) & 0xffffffff,
                                 qtype, 1024, 0, 0, 1, 1, 1, 0, 0, 0])

    def test_hfi_registers_written_in_boot_order(self):
        self.assertEqual(self._boot_gmu(), 1)
        writes = [(self.lib.gmu_write_off(i), self.lib.gmu_write_val(i))
                  for i in range(self.lib.gmu_write_count())]
        qtbl = writes.index((0x14614, 0x80000000))
        info = writes.index((0x14610, 1))
        sfr = writes.index((0x14608, 0x06030000))
        release = max(i for i, (off, value) in enumerate(writes)
                      if off == 0x14000 and value == 0)
        ctrl = writes.index((0x14618, 1))
        self.assertLess(qtbl, release)
        self.assertLess(info, release)
        self.assertLess(sfr, release)
        self.assertLess(release, ctrl)
        self.assertLess(qtbl, info)
        self.assertLess(sfr, writes.index((0x140b4, 0x4052)))
        self.assertEqual(self.lib.gmu_write_val(0), 1)   # GENERAL_7
        self.assertEqual(self.lib.gmu_write_off(0), 0x14730)

    def test_hfi_boot_completes_ctrl_init(self):
        self.assertEqual(self._boot_gmu(), 1)
        log = self.lib.power_log().decode()
        self.assertIn('POLARIS PWR: 0121 checkpoint cm3-up', log)
        self.assertIn('POLARIS PWR: 0121 checkpoint after-ctrl-init', log)
        self.assertIn('POLARIS PWR: 0121 checkpoint done', log)
        self.assertIn('HFI ctrl initialized status=0x00000001', log)
        self.assertIn('GMU boot complete init=0xbabeface', log)
        self.assertIn('HFI ctrl initialized', log)
        self.assertIn('HFI table pa=0x80000000', log)
        self.assertIn('qtbl_info=0x00000001 sfr=0x06030000', log)
        self.assertEqual(self.lib.power_gmu_reg(0x14600) & 1, 1)
        self.assertEqual(self.lib.power_gmu_reg(0x14614), 0x80000000)
        self.assertEqual(self.lib.power_gmu_reg(0x14610), 1)
        self.assertEqual(self.lib.power_gmu_reg(0x14608), 0x06030000)
        self.assertEqual(self.lib.hfi_alloc_count_get(), 1)
        self.assertGreater(self.lib.hfi_flush_count_get(), 0)

    def test_hfi_start_sends_init_message(self):
        self.assertEqual(self._boot_gmu(), 1)
        self.assertEqual(self.lib.hfi_start(), 1)
        log = self.lib.power_log().decode()
        self.assertIn('HFI INIT sent cmd=0x00100500 dbg=0x80004000', log)
        self.assertEqual([self.lib.hfi_table_word(42 + i) for i in range(5)],
                         [0x00100500, 0, 0x80004000, 0x4000, 1])
        self.assertEqual(self.lib.hfi_table_word(17), 5)

    def test_hfi_ack_success_advances_msg_read_index(self):
        self.assertEqual(self._boot_gmu(), 1)
        self.assertEqual(self.lib.hfi_start(), 1)
        log = self.lib.power_log().decode()
        self.assertIn('HFI ACK id=126 size=19 seq=1 error=0 '
                      'payload0=0x11223344', log)
        self.assertEqual(self.lib.hfi_table_word(28), 19)
        self.assertEqual(self.lib.hfi_table_word(29), 19)
        self.assertEqual(self.lib.power_gmu_reg(0x14648) & 1, 0)

    def test_hfi_ack_error_is_reported(self):
        self.assertEqual(self._boot_gmu(), 1)
        self.lib.hfi_ack_fault(5)
        self.assertEqual(self.lib.hfi_start(), 0)
        self.assertIn('HFI ACK error=5', self.lib.power_log().decode())
        self.assertEqual(self.lib.power_gmu_reg(0x14648) & 1, 0)

    def test_hfi_ack_timeout_is_reported(self):
        self.assertEqual(self._boot_gmu(), 1)
        self.lib.hfi_ack_timeout(1)
        self.assertEqual(self.lib.hfi_start(), 0)
        self.assertIn('HFI ACK timeout info=0x00000000',
                      self.lib.power_log().decode())

    def test_hfi_ctrl_timeout_blocks_start(self):
        self.assertEqual(self._boot_gmu(ctrl_fault=1), 1)
        log = self.lib.power_log().decode()
        self.assertIn('HFI CTRL_INIT timeout status=0x00000000', log)
        self.assertIn('HFI ctrl not initialized', log)
        self.assertEqual(self.lib.hfi_start(), 0)
        self.assertIn('HFI not ready; GMU boot or CTRL_INIT missing',
                      self.lib.power_log().decode())

    def test_hfi_allocation_failure_holds_cm3_in_reset(self):
        self.assertEqual(self._boot_gmu(alloc_fault=1), 0)
        log = self.lib.power_log().decode()
        self.assertIn('HFI table allocation failed kr=1', log)
        self.assertIn('HFI table unavailable; CM3 held in reset', log)
        self.assertEqual(self.lib.hfi_alloc_count_get(), 1)
        self.assertEqual(self.lib.power_gmu_reg(0x14000), 1)
        self.assertEqual(self.lib.power_gmu_reg(0x14614), 0x5a5a5a5a)

    def test_hfi_rejects_physical_address_above_4gib(self):
        self.assertEqual(self._boot_gmu(pa_high=1), 0)
        log = self.lib.power_log().decode()
        self.assertIn('HFI table pa=0x100000000 is not 4K-aligned below 4 GiB',
                      log)
        self.assertEqual(self.lib.power_gmu_reg(0x14000), 1)

    def test_hfi_reserved_region_is_mapped_without_kmem(self):
        self.assertEqual(self._boot_gmu(reserve=(0x8c420000, 0x8000)), 1)
        log = self.lib.power_log().decode()
        self.assertIn('HFI table reserved pa=0x8c420000', log)
        self.assertIn('POLARIS PWR: 0121 checkpoint hfi-mapped', log)
        self.assertIn('POLARIS PWR: 0121 checkpoint hfi-zero-done', log)
        self.assertIn('POLARIS PWR: 0121 checkpoint hfi-fill-done', log)
        self.assertNotIn('HFI table reservation missing', log)
        self.assertEqual(self.lib.hfi_alloc_count_get(), 0)
        self.assertEqual(self.lib.hfi_flush_count_get(), 0)
        self.assertEqual(self.lib.power_gmu_reg(0x14614), 0x8c420000)
        self.assertEqual([self.lib.hfi_table_word(i) for i in range(6)],
                         [0, 42, 6, 12, 3, 3])
        self.assertEqual(self.lib.hfi_table_word(7), 0x8c420000 + 168)

    def test_hfi_reserved_region_too_small_fails_closed(self):
        self.assertEqual(self._boot_gmu(reserve=(0x8c420000, 0x4000)), 0)
        log = self.lib.power_log().decode()
        self.assertIn('HFI reserved region too small (16384 < 32768)', log)
        self.assertIn('HFI table unavailable; CM3 held in reset', log)
        self.assertEqual(self.lib.power_gmu_reg(0x14000), 1)

    def test_hfi_reserved_map_failure_fails_closed(self):
        self.assertEqual(self._boot_gmu(reserve=(0x8c420000, 0x8000),
                                        map_fault=1), 0)
        log = self.lib.power_log().decode()
        self.assertIn('HFI table map failed pa=0x8c420000', log)
        self.assertIn('HFI table unavailable; CM3 held in reset', log)
        self.assertEqual(self.lib.power_gmu_reg(0x14000), 1)
        self.assertEqual(self.lib.power_gmu_reg(0x14614), 0x5a5a5a5a)

    def test_hfi_reserved_path_sends_init_and_acks_uncached(self):
        self.assertEqual(self._boot_gmu(reserve=(0x8c420000, 0x8000)), 1)
        self.assertEqual(self.lib.hfi_start(), 1)
        log = self.lib.power_log().decode()
        self.assertIn('HFI INIT sent cmd=0x00100500 dbg=0x8c424000', log)
        self.assertIn('HFI ACK id=126 size=19 seq=1 error=0', log)
        self.assertEqual([self.lib.hfi_table_word(42 + i) for i in range(5)],
                         [0x00100500, 0, 0x8c424000, 0x4000, 1])
        self.assertEqual(self.lib.hfi_table_word(28), 19)
        self.assertEqual(self.lib.hfi_flush_count_get(), 0)

    def test_handoff_accepts_and_reports_low_dram_hfi(self):
        self.lib.diag_reset(0, 1, 1)
        self.lib.diag_set_hfi(0x8c420000, 0x8000, 16)
        log = self.lib.diag_run(1).decode()
        self.assertIn('handoff hfi=0x8c420000+0x8000 (low DRAM)', log)
        self.assertNotIn('handoff refused', log)
        self.assertEqual(self.lib.hfi_alloc_count_get(), 0)

    def test_handoff_refuses_bad_hfi_reservations(self):
        for address, size, length, reason in (
                (0x8c420000, 0x4000, 16,
                 'GPU-HFI reservation has an invalid length'),
                (0x8c420008, 0x8000, 16,
                 'GPU-HFI reservation is not 4K aligned'),
                (0x100000000, 0x8000, 16,
                 'GPU-HFI reservation leaves low 4 GiB'),
                (0x8c415000, 0x8000, 16,
                 'GPU-HFI reservation collides with a platform carve-out'),
                (0x8bf80000, 0x8000, 16,
                 'GPU-HFI reservation collides with a platform carve-out'),
                (0x9d400000, 0x8000, 16,
                 'GPU-HFI reservation collides with a platform carve-out')):
            self.lib.diag_reset(0, 1, 1)
            self.lib.diag_set_hfi(address, size, length)
            log = self.lib.diag_run(1).decode()
            self.assertIn('handoff refused (' + reason, log)
            self.assertEqual(self.lib.power_map_count(), 0)

    def test_hfi_start_without_gmu_boot_is_refused(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertEqual(self.lib.bus_enter(), 1)
        self.lib.power_gmu_boot_optin(0)
        self.lib.power_hfi_optin(1)
        self.assertEqual(self.lib.gmu_boot(0x110010000, 0x8000), 0)
        self.assertEqual(self.lib.hfi_start(), 0)
        self.assertIn('HFI not ready; GMU boot or CTRL_INIT missing',
                      self.lib.power_log().decode())
        writes = [self.lib.gmu_write_off(i)
                  for i in range(self.lib.gmu_write_count())]
        self.assertNotIn(0x14650, writes)
        self.assertEqual(self.lib.hfi_alloc_count_get(), 0)

    def test_smmu_refuses_without_bus_before_mapping(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        maps = self.lib.power_map_count()
        writes = self.lib.power_write_count()
        self.assertEqual(self.lib.smmu_probe(), 0)
        self.assertIn('smmu refused; bus not owned', self.lib.power_log().decode())
        self.assertEqual(self.lib.power_map_count(), maps)
        self.assertEqual(self.lib.power_write_count(), writes)

    def test_smmu_default_is_not_opted_in_and_never_maps(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertEqual(self.lib.bus_enter(), 1)
        maps = self.lib.power_map_count()
        writes = self.lib.power_write_count()
        self.assertEqual(self.lib.smmu_probe(), 0)
        log = self.lib.power_log().decode()
        self.assertIn('smmu probe not opted in; no access', log)
        self.assertEqual(self.lib.power_map_count(), maps)
        self.assertEqual(self.lib.power_write_count(), writes)

    def test_smmu_level_one_reads_only_idr0(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertEqual(self.lib.bus_enter(), 1)
        self.lib.power_smmu_optin(1)
        self.assertEqual(self.lib.smmu_probe(), 1)
        log = self.lib.power_log().decode()
        self.assertIn('SMMU read begin off=0x020 level=1', log)
        self.assertIn('SMMU IDR0=0x48016605', log)
        self.assertIn('SMMU probe limited to level 1; context banks not read', log)
        self.assertIn('SMMU read-only; level=1 contexts=0 smr=5 sid_bits=3 '
                      'irpt=1 granule=unknown; no attach', log)
        self.assertNotIn('SMMU read begin off=0x024', log)
        self.assertNotIn('SMMU CB0', log)

    def test_smmu_read_is_flushed_before_the_value(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertEqual(self.lib.bus_enter(), 1)
        self.lib.power_smmu_optin(1)
        self.assertEqual(self.lib.smmu_probe(), 1)
        log = self.lib.power_log().decode()
        begin = log.index('SMMU read begin off=0x020 level=1')
        sync = log.index('<smmu-sync>', begin)
        value = log.index('SMMU IDR0=', begin)
        self.assertLess(begin, sync)
        self.assertLess(sync, value)
        self.assertEqual(self.lib.smmu_sync_count(), 1)

    def test_smmu_level_two_stops_before_idr5(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertEqual(self.lib.bus_enter(), 1)
        self.lib.power_smmu_optin(2)
        self.assertEqual(self.lib.smmu_probe(), 1)
        log = self.lib.power_log().decode()
        self.assertIn('SMMU read begin off=0x024 level=2', log)
        self.assertIn('SMMU IDR1=0x20008005 IDR2=0x00007511', log)
        self.assertNotIn('SMMU read begin off=0x034', log)
        self.assertNotIn('SMMU read begin off=0x02c', log)
        self.assertIn('SMMU read-only; level=2 contexts=5 smr=5 sid_bits=3 '
                      'irpt=1 granule=4K; no attach', log)
        self.assertEqual(self.lib.smmu_sync_count(), 3)

    def test_smmu_reads_global_and_context_registers_without_any_write(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertEqual(self.lib.bus_enter(), 1)
        self.lib.power_smmu_optin(4)
        writes = self.lib.power_write_count()
        self.assertEqual(self.lib.smmu_probe(), 1)
        log = self.lib.power_log().decode()
        self.assertIn('SMMU IDR0=0x48016605', log)
        self.assertIn('SMMU IDR1=0x20008005 IDR2=0x00007511', log)
        self.assertIn('SMMU IDR5=0x00000002 IDR6=0x00000000 '
                      'IDR7=0x00000000', log)
        self.assertIn('SMMU GFAR=0x00000000 GFSR=0x00000000 '
                      'GFSYNR0=0x00000000 GFSYNR1=0x00000000', log)
        self.assertIn('SMMU CB0 CBAR=0x00000001 SMR=0x00000000 '
                      'S2CR=0x000200ff type=fault cbndx=255 FSR=0x00000000', log)
        self.assertIn('SMMU CB4 CBAR=0x04000005 SMR=0x00000000 '
                      'S2CR=0x000200ff type=fault cbndx=255 FSR=0x00000000', log)
        self.assertIn('SMMU read-only; level=4 contexts=5 smr=5 sid_bits=3 '
                      'irpt=1 granule=4K; no attach', log)
        self.assertNotIn('SMMU read begin off=0x02c', log)
        self.assertEqual(self.lib.smmu_sync_count(), 30)
        self.assertEqual(self.lib.power_write_count(), writes)
        self.assertEqual(self.lib.power_smmu_unchanged(), 1)

    def test_smmu_bad_geometry_is_refused_without_writes(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertEqual(self.lib.bus_enter(), 1)
        self.lib.power_smmu_optin(4)
        self.lib.power_smmu_set(0x24, 0)  # IDR1.NUMCB = 0
        writes = self.lib.power_write_count()
        self.assertEqual(self.lib.smmu_probe(), 0)
        self.assertIn('SMMU IDR is not usable', self.lib.power_log().decode())
        self.assertEqual(self.lib.power_write_count(), writes)

    def test_smmu_map_failure_claims_nothing(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.assertEqual(self.lib.rails_enter(), 1)
        self.assertEqual(self.lib.clocks_enter(), 1)
        self.assertEqual(self.lib.bus_enter(), 1)
        self.lib.power_smmu_optin(1)
        self.lib.power_smmu_map_fault(1)
        writes = self.lib.power_write_count()
        self.assertEqual(self.lib.smmu_probe(), 0)
        self.assertIn('cannot map SMMU; probe skipped',
                      self.lib.power_log().decode())
        self.assertEqual(self.lib.power_write_count(), writes)

    def test_bringup_clocks_bus_gmu_read_then_hfi_refuses_and_unwinds(self):
        self.lib.diag_reset(0, 1, 1)
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.lib.power_smmu_optin(4)
        log = self.lib.diag_run(1).decode()
        self.assertIn('CX owned, rollback=0x00222001', log)
        self.assertIn('gmu clock source root on; cfg=0x00000300', log)
        self.assertIn('POLARIS GPU: GMU clock running', log)
        self.assertIn('POLARIS GPU: GMU bus clocks running', log)
        self.assertIn('GMU CSR sysreset=0x00000000 boot=0x00000000 '
                      'cfg=0x00000000 fw_busy=0x00000000 init=0x00000000', log)
        self.assertIn('POLARIS GPU: GMU registers readable; '
                      'firmware not started', log)
        self.assertIn('POLARIS GPU: gmu boot not opted in; skipped', log)
        self.assertIn('POLARIS PWR: SMMU read-only; level=4 contexts=5 smr=5 '
                      'sid_bits=3 irpt=1 granule=4K; no attach', log)
        self.assertIn('POLARIS GPU: SMMU registers readable; no attach', log)
        self.assertLess(log.index('POLARIS GPU: SMMU registers readable'),
                        log.index('POLARIS GPU: HFI backend not implemented'))
        self.assertIn('POLARIS GPU: HFI backend not implemented; '
                      'no hardware access', log)
        self.assertIn('bus exit restored axi=0x80000000 memnoc=0x80000000', log)
        self.assertIn('clocks exit restored cbcr=0x80004220 '
                      'cmd=0x80000000 cfg=0x00000000', log)
        self.assertIn('rails exit collapsed after 1 polls GDSCR=0x00222001; CX released', log)
        self.assertIn('acceleration unavailable; CPU display unchanged', log)
        self.assertEqual(self.lib.power_reg(0x6c), 0x00222001)
        self.assertEqual(self.lib.power_reg(0x98), 0x80004220)
        self.assertEqual(self.lib.power_reg(0x120), 0x80000000)
        self.assertEqual(self.lib.power_reg(0x124), 0)
        self.assertEqual(self.lib.power_gmu_unchanged(), 1)

    def test_bringup_gmuboot_quarantines_without_collapsing_rails(self):
        self.lib.diag_reset(0, 1, 1)
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.lib.power_smmu_optin(4)
        self.lib.power_gmu_boot_optin(1)
        log = self.lib.diag_run(1).decode()
        self.assertIn('GMU boot complete init=0xbabeface', log)
        self.assertIn('POLARIS GPU: GMU firmware started; HFI not initialized', log)
        self.assertIn('POLARIS GPU: HFI backend not implemented; '
                      'no hardware access', log)
        self.assertIn('POLARIS GPU: idle unconfirmed; quarantined, '
                      'CPU display unchanged', log)
        self.assertNotIn('rails exit collapsed', log)
        self.assertNotIn('clocks exit restored', log)
        self.assertEqual(self.lib.power_reg(0x6c), 0x80222000)
        self.assertEqual(self.lib.power_gmu_reg(0x14070), 0xbabeface)

    def test_bringup_hfi_success_still_quarantines(self):
        self.lib.diag_reset(0, 1, 1)
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.lib.power_smmu_optin(4)
        self.lib.power_gmu_boot_optin(1)
        self.lib.power_hfi_optin(1)
        log = self.lib.diag_run(1).decode()
        self.assertIn('POLARIS GPU: GMU firmware started; '
                      'HFI ctrl stage attempted', log)
        self.assertIn('POLARIS PWR: HFI ACK id=126 size=19 seq=1 error=0', log)
        self.assertIn('POLARIS GPU: HFI initialized', log)
        self.assertIn('POLARIS GPU: idle unconfirmed; quarantined, '
                      'CPU display unchanged', log)
        self.assertNotIn('rails exit collapsed', log)
        self.assertNotIn('clocks exit restored', log)

    def test_bringup_hfi_ack_timeout_quarantines(self):
        self.lib.diag_reset(0, 1, 1)
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.lib.power_smmu_optin(4)
        self.lib.power_gmu_boot_optin(1)
        self.lib.power_hfi_optin(1)
        self.lib.hfi_ack_timeout(1)
        log = self.lib.diag_run(1).decode()
        self.assertIn('HFI ACK timeout info=0x00000000', log)
        self.assertIn('POLARIS GPU: HFI not initialized; '
                      'acceleration unavailable', log)
        self.assertIn('POLARIS GPU: idle unconfirmed; quarantined, '
                      'CPU display unchanged', log)
        self.assertNotIn('rails exit collapsed', log)

    def test_bringup_without_gpuon_writes_nothing(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.lib.diag_reset(0, 0, 1)
        self.assertEqual(self.lib.diag_run(1), b'')
        self.assertEqual(self.lib.power_map_count(), 0)
        self.assertEqual(self.lib.power_write_count(), 0)

    def test_rails_exit_without_enter_is_a_noop(self):
        self.lib.power_rails_reset(0x00222001, 1, 1, 1)
        self.lib.rails_exit()
        self.assertEqual(self.lib.power_write_count(), 0)
        self.assertEqual(self.lib.power_reg(0x6c), 0x00222001)


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
