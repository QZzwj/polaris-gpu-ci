# MIX 2S iOS/XNU GPU：当前阻塞与下一步（2026-10-29）

**后续修复状态：**0099 已在代码中修正 ARC 地址/selector 语义，并把
0095 的错误 SID/context-bank 表改为原始 phandle/specifier 引用。主机工具
现在能解析完整 DTB，先解析 provider 和 `#iommu-cells`，再得到 SID/mask，
context bank 保持未分配。二进制 command-db 解码器也保留 OFF 和重复档位。
0102 的 82 项 Python 测试和 7 项实际 C 补丁执行测试通过。0102 还修复了并发修改
引入的 GPUCC 映射起点与寄存器偏移重复相加问题；模拟 RAM 测试先复现
错误，再验证修复，没有访问真实 MMIO。完整 XNU 构建
`40677321846` 已成功；用户确认 0102 进入 iOS，2026-10-29 通过临时
recovery 只读提取的新日志确认 ARC 修正代码执行、8/8 CPU 启动，以及
GPUCC 读回 `cx_gdscr=0x00222001`、`cx_hw_ctrl=0x00005ff4`、
`gx_gdscr=0x00222001`。日志随后明确停止于
`rails backend not implemented` 和 `acceleration unavailable; CPU display unchanged`；
另有 302 次 `IOAcceleratorES` 匹配结果为零。GPU 加速仍未启用。

新补丁 0103 统一旧诊断与 0094 的固件校验，消除官方 SQE 31980 字节
被旧诊断的固定 32136 字节误拒绝的问题；这条旧报错不是本次阻塞点。
0103 也移除初始化阶段对独立 CX 写入实验的直接调用，使它不能绕过
缺失的 rails 后端。其函数与既有补丁保留，未启用供电写入。
修复前的实际 C 源码复现两项问题；修复后 **95 项测试通过**
（82 Python + 13 实际 C），涵盖两套已注册长度、缺失/畸形属性、越界、
对齐、重叠、保留区及双开关下禁止调用 CX 写入实验。
0103 尚未完成完整 XNU 构建或手机验证，不能把主机测试说成硬件结果。

读日志后，在 2026-10-29 01:36 UTC 再次临时启动用户已确认进入过 iOS 的
同一 0102 镜像；fastboot Sending/Booting OKAY，本次返回的屏幕状态尚未观察。
没有刷写分区，手机不包含尚未构建的 0103。

以下诊断记录描述修复前的 0095/0096；运行时由 0099 覆盖这些错误解释。

以下 0095/0096 诊断与上游源码核查是历史记录，后续真机验证以本页顶部和
`NOTES.md` 的 2026-10-29 条目为准。GPU 硬件后端仍未实现。

## 为什么安装 adreno-630-gpu-driver 解决不了

`D:\ios\adreno-630-gpu-driver` 的 README 和安装脚本针对 Android 9/10
Magisk，版本分别为 v331/v415。包内是 Android 用户态 `.so`；抽查两套
`lib64/egl/libGLESv2_adreno.so` 都是 ELF/AArch64。未发现 C/H 源码或
`.fw`、`.bin`、`.mdt` 固件文件。它没有 XNU 的上电、时钟、SMMU、GMU/HFI
或命令提交实现，不能直接装入当前 iOS 移植。

保存的 `D:\ios\ring-decoded.txt:94-96` 已显示 handoff 校验之后停止于
`rails backend not implemented`，并保留 CPU 显示。该日志来自此前 0094
测试，不能算作 0096 的真机结果。0096 的源码只打印请求、没有发送路径，
因此重新打包它也不会得到 GPU 加速。

## 2026-10-29 补充：Android OpenCL 示例的适用范围

用户提供了《在 Android 上实现 Metal 的计算 Demo》（2022-06-06）全文。
其中把 Metal 数组加法改写为 OpenCL kernel，使用 Android 已有的
`libOpenCL.so`、`dlopen`/`dlsym` 和 GPU context/queue。它演示相同的计算任务，
没有提供 Metal API、MSL 编译器或 iOS 图形驱动的实现。

只读核对本地 `D:\ios\adreno-630-gpu-driver`：没有名称含 OpenCL 的文件；
抽查 Android 10 的 64 位 `libgsl.so`、`libGLESv2_adreno.so`、`libEGL_adreno.so`
及 `vulkan.sdm845.so` 均是 ELF64/AArch64。ELF 动态段列出 Android 的
`libcutils.so`、`liblog.so` 等依赖；`libgsl.so` 导入 `ioctl`、`mmap`、
`mmap64`、`property_get`，并包含 `/dev/kgsl-3d0`、`/dev/ion` 等路径字符串。
这不是实际执行追踪，但结合 KGSL 的公开 ioctl/mmap 接口，足以否定
“直接用 iOS dlopen 加载这些文件即可获得 GPU”的建议。iOS 的原生 dyld
加载 Mach-O；即使增加 ELF/Bionic 兼容层，内核接口和真正的硬件后端仍需实现。

检查脚本及每个抽查文件的 SHA256、DT_NEEDED、未定义符号、路径字符串保存在
`D:\ios\gpu-fix\inspect_android_gpu_libs.py` 和
`D:\ios\gpu-fix\android-gpu-libs-local.json`；没有执行这些库或操作手机。
本次对照了 Apple 的 Metal 计算示例、dlopen 手册和 Android Bionic 说明，
以及 AOSP libdrm 的 KGSL 源码；没有复制第三方驱动代码。
所查 AOSP KGSL 示例来自旧版 libdrm，仅用于核对设备接口形式，不能用于
推导 A630 的寄存器、上电或提交序列。

可复用的是验证方法：先完成受控上电、SMMU、GMU/HFI、PAS13 和 CP
sentinel/fence，再验证真实 GPU 数组加法；接下来才是用户态接口及 iOS
合成接入。通过计算用例也不能单独证明系统界面已由 GPU 加速。

## 2026-10-29: 0104 RPMh transport and read-only probe

Added `0104-polaris-rpmh-transport-and-readonly-probe.patch`, generated against
the booting board's DTB and the XNU source tree that already compiled. The DRV2
slice is at `0x179e0000`, TCS offset `0xd00`, slot stride `0x2a0`, ACTIVE 2 /
SLEEP 3 / WAKE 3, and command stride `0x14`. `qcom,tcs-config` is ordered ACTIVE,
SLEEP, WAKE, so slots 0/1 are ACTIVE; positions are not CONTROL/SLEEP/WAKE.
AOSP `rpmh-rsc.c` at commit `43062a37ef7a0d352d6550c45e2f49c10303eb1e` was read
before the implementation.

`bsd/dev/polaris_rpmh_core.c` is an original implementation, not copied driver
code. It uses only ACTIVE slots, rejects unknown geometry, refuses an address
already enabled in either ACTIVE slot, checks IRQ status before mutation,
requires each command's completion bit, and quarantines after a timeout or any
uncertain write. It never retries, resets a TCS, or sends a compensating rail
vote. Only proven completion restores payload words and its own IRQ-enable bit;
SLEEP and WAKE are untouched. Both an overall deadline and a finite polling
budget bound the wait.

The XNU adapter `bsd/dev/polaris_rpmh.c` installs a read callback only, mapping
`0x179e0000..0x179e3fff` behind its own `polarisrpmhdiag=1`. It prints geometry,
IRQ state and ACTIVE contents. It has no write, timer or authority certificate,
so no other GPU boot argument can make it send a rail vote. A log can establish
register layout, not ownership of inherited ARC votes. Firmware leases or kernel
resource ownership must be proven before sending; an empty TCS is insufficient.

The same patched C sources were compiled against a simulated register device for
unknown geometry, missing authority, in-flight conflicts, concurrency, stale IRQ,
completion timeout, frozen clock, readback failure and invalid selectors. The
success path was checked to restore an empty slot and preserve SLEEP/WAKE. All
117 regressions pass (Python protocol plus actual C patches). 104 patches are
contiguous and format-valid; all 49 Python tools parse. `validate-repo.py`'s shell
pass crashes on Windows without `bash` because it reads `stderr=None`; that is a
validator defect, so its patch and Python checks were invoked separately. A full
XNU build and phone boot remain outstanding and GPU acceleration is still off.


## 接入上电前，先修正两处数据解释

### 1. ARC 等级、硬件 selector 和 VRM 电压是不同的数据

修复前的 `tools/polaris_rpmh_vote.py` 和补丁 0096 把 `gfx.lvl` 等 AUX 表的
等级值用作请求数据，并让 `rail_vote()` 把它送往 `vrm.gfx` 等地址。
这不符合厂商 RPMh regulator 实现：

- ARC AUX 表定义 consumer level 到硬件 selector 的映射。ARC 请求使用
  对应 `*.lvl` 资源地址和 selector；保留表首的 OFF 项，才能保留原始下标。
- VRM 电压请求使用 VRM 资源及电压单位，厂商实现采用毫伏；不能把 ARC
  level 值直接作为 VRM 电压。
- AUX 表的重复值也占用原始下标，不能通过删除零项、去重来重新编号。

本机保存的 command-db 中 `gfx.lvl` 地址为 `0x30050`，`vrm.gfx` 为
`0x42700`。这些事实不能证明 XNU 已拥有相应 TCS 或供电资源。

**已由 0099 完成：**修正纯离线 Python/C 请求模型，区分 resource address、
consumer level、selector 和 VRM 电压；增加针对厂商语义的回归测试。
保留无发送路径的状态。此前 8 个 composer 测试重复了旧假设，测试通过
不能证明编码正确。

### 2. iommus 的第一个 cell 是 provider phandle

`D:\ios\recon\dt_gpu_binary.txt` 保存了如 `gfx3d_user` 的
`iommus = <0x208 0x0>`，以及 GMU 对应的参数 4/5。
通用 IOMMU binding 定义该属性为 phandle/specifier 对：第一个 cell
`0x208` 是 provider 的设备树句柄，不能当作 stream ID。

`tools/polaris_cmddb.py` 的 `SID_MAP`、0095 的 `pg_sid_map` 和旧的
`handset-cmd-db-and-domain-facts.md` 第 7 节把它解释成 SID，并把后一个
参数解释成 context bank，证据不足；这次更正优先于这些旧描述。

**离线解析已完成：**`tools/polaris_iommu.py` 解析 provider 的 phandle、
`#iommu-cells` 后得到 SID/mask；本地 boot DTB 解析出 SID 0/2/1/4/5、mask 0。
动态 context bank 分配、HYP 限制及 XNU 所有权仍待实现；不能直接把原始
phandle 表用于 SMR/S2CR/CB 编程。

## 真正启用 GPU 的开发顺序和验收

1. 编码和离线 DT 解析修正已完成；实现 Polaris 专用 RPMh/TCS、供电、
   GPUCC 时钟及带宽后端。每步需要确认资源归属、ACK/读回、超时和回退。
   第一项真机目标是证明确实完成可控上电，而不是继续增加打印信息。
2. 在任何设备 DMA 前完成 GMU/3D 的受限 SMMU 映射；再完成 A630 GMU
   固件加载、HFI v1 和带宽表，以及 PAS13 zap 认证。具体依赖以
   [实现契约](../research/polaris/gmu-secure-implementation.md)为基础，
   其中旧的数据状态由本记录及较新的 NOTES 条目修正。
3. 首次执行只验证一个小缓冲区：GPU 写入指定 sentinel，fence 完成，
   CPU 读回一致且没有 SMMU/GMU/CP 错误。它才是硬件执行的首个证明。
4. 通过上述测试之后，再接入适用于 XNU 的用户态渲染、IOSurface 和
   iOS 图形接口。命令执行成功本身仍不代表界面已获得 GPU 加速。

新实验镜像应先以临时 `fastboot boot` 取得日志并逐项验收。此文没有生成
GPU 加速镜像；目前无法通过安装这个 Magisk 包或改一个启动参数完成。

## 本次核对的一手来源

- MiCode Polaris kernel，提交
  `c7cb50c18f812629b9620b2b8fa684bc40d82080`：
  [rpmh-regulator.c](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/c7cb50c18f812629b9620b2b8fa684bc40d82080/drivers/regulator/rpmh-regulator.c)
  的 ARC/VRM 类型、`rpmh_regulator_arc_set_voltage_sel()`、
  `rpmh_regulator_load_arc_level_mapping()` 和 VRM 电压设置路径；
  [iommu.txt](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/c7cb50c18f812629b9620b2b8fa684bc40d82080/Documentation/devicetree/bindings/iommu/iommu.txt)
  的 phandle/specifier 定义。
- Linux 上游，提交 `65ba8f34ec886ec72b2c07ddc8cf3d815c32869d`：
  [rpmhpd.c](https://github.com/torvalds/linux/blob/65ba8f34ec886ec72b2c07ddc8cf3d815c32869d/drivers/pmdomain/qcom/rpmhpd.c)
  的 level 到 corner 映射与发送路径，及
  [qcom-rpmh-regulator.c](https://github.com/torvalds/linux/blob/65ba8f34ec886ec72b2c07ddc8cf3d815c32869d/drivers/regulator/qcom-rpmh-regulator.c)
  对 VRM 电压单位的定义。

上游源文件通过 HTTPS 读取，没有将第三方驱动源码复制进 XNU。
