# Polaris handset facts: command DB, GPU SMMU domains, rails (2026-10-28, read-only)

Source: this handset, recovery Linux (OrangeFox), over ADB. Everything below is a
**read**: `cat /sys/kernel/debug/cmd_db`, sysfs/procfs, `dmesg`, and a raw `dd` of
the vendor partition. No register writes, no `/dev/mem`, no vendor modification.
This describes what the **vendor kernel** configured; it is not proof of XNU
ownership and it is not a powered-GPU result.

## 1. RPMh command DB is readable on this build

`/sys/kernel/debug/cmd_db` is `0444` in this recovery (earlier sessions found it
absent). Dump: 5,600 bytes of text, one resource per line
(`Address: 0x.., id: <name>, aux data: <bytes>`). It supersedes the withdrawn 0092
fixed-PA mapping as a *source*: the data can be shipped as a hash-pinned table
instead of being read from physical memory at boot.

Level rows (aux is a little-endian `u16` level-index list):

| id | ARC address | level indices (0x) | count |
| --- | --- | --- | --- |
| `cx.lvl` | `0x30000` | 10, 30, 40, 80, c0, 100, 180 | 7 |
| `mx.lvl` | `0x30010` | 10, 10, 100, 180 | 4 |
| `gfx.lvl` | `0x30050` | 10, 30, 40, 80, c0, 100, 140, 180, 1a0 | **9** |
| `ddr.lvl` | `0x30070` | 20, 80, a0 | 3 |
| `xo.lvl` | `0x30080` | 20, 50, 80 | 3 |

`gfx.lvl` having 9 indices matters: the vendor GPU DTS pwrlevels and the live
KGSL table are 7 frequencies (257–710 MHz), so the HFI/BW table cannot be assumed
1:1 with the frequency list.

BCM resources present (aux carries base/width style fields, not vote words):
`MC0..MC2`, `SH0..SH7`, `MM0..MM3`, `SN0..SN15`, `CE0`, `IP0`, `CN0`, `QUP0`,
`ACV`, `ALC`, `NU0`.

Regulator/VRM resources relevant to the GPU path: `vrm.cx` @ `0x40800` (alias of
`smpa9`), `vrm.mx` @ `0x40700` (`smpa6`), `vrm.gfx` @ `0x42700` (alias of `smpc1`),
`vrm.ebi` @ `0x40400`, `vrm.lmx`, `vrm.mss`, `vrm.spmi`, `vrm.soc`, `vrm.xob`.

## 2. GPU SMMU domains on this handset

`dmesg`: `arm-smmu 5040000.arm,smmu-kgsl` with **5 context banks**, 8 context
interrupts, `stream matching with 5 register groups, mask 0x7`,
`IDR0.CTTW overridden by dma-coherent`.

`/sys/kernel/iommu_groups` shows four distinct GPU-side domains:

| group | device |
| --- | --- |
| 16 | `506a000.qcom,gmu:gmu_user` |
| 17 | `506a000.qcom,gmu:gmu_kernel` |
| 18 | `5040000.qcom,kgsl-iommu:gfx3d_user` |
| 19 | `5040000.qcom,kgsl-iommu:gfx3d_secure` |

So the "separate GMU and 3D contexts" in the implementation contract exist on this
board, and the secure 3D context is a distinct domain from the user one. Stream IDs
themselves are still to be derived (DT `iommus`/`qcom,stream-id-range` or vendor
probe logs); the mask `0x7` means low SID bits are shared.

## 3. Power/clock facts

- `dmesg`: `gpu_cx_gdsc: supplied by pm8998_s9_level`,
  `gpu_gx_gdsc: supplied by pm8005_s1_level`.
- `5090000.qcom,gpucc` registers GFX3D clock source with OPP pairs
  `180 MHz / 49` and `710 MHz / 417`, GMU clock source `19.2 MHz / 49` and
  `500 MHz / 129` (corner numbers, not volts).
- `kgsl-hyp` owns reserved memory `gpu_region@0x8c415000` (the 8 KiB zap carveout).
- `/proc/iomem`: `05000000-0503ffff kgsl-3d0`, `05040000-0504ffff arm,smmu-kgsl`,
  `85fe0000-85fe0dc0 c3f000c.qcom,cmd-db`.

## 4. KGSL state as observed (vendor kernel, not XNU)

`gpu_model=Adreno630v2`, `reset_count=0`, `devfreq/available_frequencies` =
257/342/414/520/596/675/710 MHz, `governor=msm-adreno-tz`,
`max_gpuclk=710000000`, `gpu_busy_percentage=0` (nothing rendering in recovery).

## 5. Vendor partition has no firmware left

`vendor` is `/dev/block/sde47` (1 GiB). It mounts read-only, `df` claims ~798 MiB
used, but the raw read contains **0.018% non-zero bytes (~190 KB)**: superblock,
group descriptors and inode tables survive, while the data blocks (root directory
included) read as zeros, and the image contains no `a630` string at all.

Consequence: the `device-2026-10-22` firmware set recorded earlier (SQE 32,136 B,
GMU 32,768 B) can no longer be re-extracted from this phone. Any payload must use
the registered `miui-v12.5.1.0-qdgcnxm-20210707` set, and `0091`'s hardcoded blob
sizes will keep reporting `invalid GPU-SQE range` on it — expected, not a fault.

## 6. What this unblocks, and what it does not

Unblocked (sources now authoritative, no guessing):

1. The RPMh ARC/BCM resource table for the GPU path can be shipped as a
   hash-pinned blob and validated offline, instead of mapping fixed physical
   memory (the reason 0092 was withdrawn).
2. The four GPU SMMU domains are confirmed to exist; the next step is deriving
   stream IDs from the device tree rather than inventing them.
3. Rail supplies (`pm8998_s9` for CX, `pm8005_s1` for GX) and the `gfx.lvl`
   index count are known, which the GMU/HFI bandwidth table needs.

Still missing before any powered patch:

- Actual stream ID → context bank routing and whether the non-protected banks are
  usable from XNU.
- Aggregated bus votes (13 DDR / 2 CNOC HFI rows) — cmd-db gives resources, not
  the aggregation result.
- A reversible, owned CX/GX power sequence with readback and rollback, plus the
  PAS13 SCM contract for the zap carveout.
- Any XNU GPU code beyond the 0094 handoff validation: no GMU load, no HFI, no
  SMMU programming, no CP ring, no rendering.

## 7. GPU SMMU routing and GMU registers (vendor DT, read 2026-10-28)

`/sys/firmware/devicetree/base` on the same recovery session:

| DT node | `iommus` | role |
| --- | --- | --- |
| `/soc/qcom,kgsl-iommu/gfx3d_user` | `<0x208 0x0>` | 3D, user |
| `/soc/qcom,kgsl-iommu/gfx3d_secure` | `<0x208 0x1>`, `<0x208 0x2>` | 3D, secure |
| `/soc/qcom,gmu/gmu_user` | `<0x208 0x4>` | GMU, user |
| `/soc/qcom,gmu/gmu_kernel` | `<0x208 0x5>` | GMU, kernel |

One stream ID (`0x208`) with mask bits selects all four contexts, which matches the
vendor SMMU probe line `stream matching with 5 register groups, mask 0x7`. This is
the routing the implementation contract demanded; it is now documented rather than
guessed, and it says nothing yet about whether XNU may use the non-protected banks.

Other constraints read from the same nodes:

- `/soc/qcom,gmu`: `compatible = qcom,gpu-gmu`,
  `reg = 0x0506a000 +0x30000, 0x0b200000 +0x300000` (the second window is the PDC),
  clocks `gmu_clk/cxo_clk/axi_clk/memnoc_clk`.
- `/soc/qcom,kgsl-3d0@5000000`: `reg = 0x05000000 +0x40000, 0x05061000 +0x800,
  0x0509e000 +0x1000`; clocks `core_clk/rbbmtimer_clk/mem_clk/mem_iface_clk/
  gmu_clk/l3_vote`.
- `/soc/qcom,kgsl-iommu` (`qcom,kgsl-smmu-v2`): `reg = 0x05040000 +0x10000`.
- `/soc/arm,smmu-kgsl@5040000` (`qcom,smmu-v2`): `#global-interrupts = 2`,
  interrupts 0xe5/0xe7 (global) plus 0x16c/0x16d (context).
- `/soc/qcom,kgsl-hyp` is `qcom,pil-tz-generic` with `qcom,pas-id = 13` and
  `memory-region` -> `gpu_region@0x8c415000` `reg = 0x8c415000 +0x2000` (8 KiB).
- `gfx.lvl` carries 9 level indices while KGSL has 7 frequencies, so any HFI
  bandwidth table must not be generated 1:1 from the pwrlevels.

## 8. What 0095 adds (and deliberately does not)

`xnu/patches/0095-polaris-gpu-arc-sid-facts.patch` compiles the pinned command-DB
rows and the SID map into the kernel as inert data and prints one summary line; it
does not map the command DB, vote anything, or touch a register. Content validation
of the dump happens at packaging time in `tools/polaris_cmddb.py` (10 pinned rows,
level counts included), because reading the blob in XNU would need exactly the
mapping that got 0092 withdrawn.

Still open, unchanged: owned CX/GX power with rollback, PAS13 SCM contract, GMU
ITCM load, HFI v1, SMMU programming, CP sentinel/fence, and any userland graphics.