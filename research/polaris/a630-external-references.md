# External A630 references: what they are, what they are not

Two public projects were reviewed on 2026-10-28 at the user's request. Both were
cloned read-only through a proxy (no direct GitHub route from this workspace) and
are **references only** — no code was copied into XNU, which is APSL and must not
absorb GPL sources.

## `worthdoingbadly/patch-a630`

- **What it is:** a ~14-line script that patches one instruction of the Pixel 3 XL
  `a630_sqe.fw` so that `CP_SMMU_TABLE_UPDATE` stops being gated. The author says it
  reproduces CVE-2025-21479 (an A7xx issue) on an A6xx device. The README shows the
  resulting `CP Illegal instruction` / GPU page-fault / hang log.
- **The reusable fact:** `a630_sqe.fw` is a 4-byte header followed by flat 32-bit
  instruction words, so instruction index `n` is at file offset `n*4 + 4`; the
  reference patch site is index `0x092c`, whose pre-patch word the comment prints as
  `c240fa26` (a `brne`), replaced by the nop bytes `00 00 00 01`.
- **What it does not give us:** nothing about power, GMU, HFI, SMMU or the ring. It
  is a security demo on a different handset and a different firmware build.

Our own image (registered MIUI set, `a630_sqe.fw` 31,980 B): **7,994 instructions,
header word `0x00000000`, word at index `0x092c` = `0x0a2921fc`** — different from
both the reference pre-patch and post-patch words. So the firmware generation
differs: do not copy that patch, and do not assume the same gate exists here.
`tools/polaris_sqe_inspect.py` reports this offline (read-only, nothing patched).

## `beejmaxx/a630-rs`

- **What it is:** a dependency-free Rust **shader** interpreter for a declared A630
  instruction subset: wave/lane state, `E_32_4` compiler artifacts, predication,
  constant registers, float rounding. Semantics are derived from pinned Mesa sources;
  its own docs insist on separating hand-assembled examples, compiler output, CPU
  comparisons and hardware observations, and on preserving unknown state.
- **Scope check:** the repository contains no CP, PM4, SQE, GMU or SMMU material
  (grep of README/RESEARCH/HANDOFF finds none; `src/` is `isa.rs`, `wave.rs`,
  `memory.rs`, `e32.rs`). It runs entirely on the CPU and needs no GPU.
- **Where it will matter:** the last stage of this port — once the CP can submit work
  and Mesa/EAGL is being brought up, an interpreter of exactly this kind is a way to
  check what a shader should do without trusting the GPU. It is not an input to
  power, GMU/HFI, SMMU or the CP fence.

## Consequence for this port

Neither project unblocks the current four steps (owned CX/GX power with rollback,
PAS13 authentication, GMU ITCM load + HFI v1, SMMU programming + CP fence). They are
recorded here as stage-5/6 references; the immediate blockers still need the
handset-derived data already captured in
[handset-cmd-db-and-domain-facts.md](handset-cmd-db-and-domain-facts.md) plus an
implementation of the power path.

## Android Adreno 630 driver module (Magisk) and a Windows driver database

Evaluated 2026-10-28 because the user supplied the links.

- **`Magisk-Modules-Repo/adreno-630-gpu-driver`** (author P1N2O, versions v415/v331)
  and its mirror `aleksartx7/...`: 76 `.so` files under `system_09/` and `system_10/`
  (`libGLESv2_adreno.so`, `vulkan.sdm845.so`, `libllvm-qcom.so`, `libllvm-glnext.so`,
  ...), installed by a Magisk `install.sh`. This is an **Android userspace** driver
  set: Bionic ABI, Android EGL/Vulkan entry points, talking to the Android `kgsl`
  kernel driver over ioctls.
- **No firmware and no kernel logic.** There is no `a630_sqe.fw`, `a630_gmu.bin` or
  `a630_zap.*` in the module, so it cannot compensate for this handset's empty vendor
  partition, and it says nothing about power, GMU, HFI or SMMU.
- **Why it is unusable here:** iOS userland asks for Metal, our port renders through a
  CPU-side framebuffer, and XNU is not Android: these blobs cannot be loaded, cannot
  link against XNU's IOKit surface, and have no path to a kgsl-compatible kernel
  interface. Treat the module as a source of *version numbers* for Adreno 630
  userspace drivers (v415 / v331) and nothing more.
- **`treexy.com` Adreno 630 entry:** a Windows driver-database listing for Adreno 630
  display adapters (Windows-on-Snapdragon territory). Not a phone firmware or XNU
  source; no action.