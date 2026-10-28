# MIX 2S iOS/XNU GPU：当前阻塞与下一步（2026-10-28）

**后续修复状态：**0099 已在代码中修正 ARC 地址/selector 语义，并把
0095 的错误 SID/context-bank 表改为原始 phandle/specifier 引用。主机工具
现在能解析完整 DTB，先解析 provider 和 `#iommu-cells`，再得到 SID/mask，
context bank 保持未分配。二进制 command-db 解码器也保留 OFF 和重复档位。
82 项 Python 测试和 7 项实际 C 补丁执行测试通过。0102 还修复了并发修改
引入的 GPUCC 映射起点与寄存器偏移重复相加问题；模拟 RAM 测试先复现
错误，再验证修复，没有访问真实 MMIO。完整 XNU 构建与新的
真机测试尚待完成；仍缺 GPU 硬件后端，卡顿不会因这次修正而消失。

以下诊断记录描述修复前的 0095/0096；运行时由 0099 覆盖这些错误解释。

本次是代码、文件格式、保存的真机日志及上游源码核查。没有运行手机测试、
重启手机、刷写分区或实现硬件后端。GPU 加速仍未完成。

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

## 接入上电前，先修正两处数据解释

### 1. ARC 等级、硬件 selector 和 VRM 电压是不同的数据

当前 `tools/polaris_rpmh_vote.py` 和补丁 0096 把 `gfx.lvl` 等 AUX 表的
等级值用作请求数据，并让 `rail_vote()` 把它送往 `vrm.gfx` 等地址。
这不符合厂商 RPMh regulator 实现：

- ARC AUX 表定义 consumer level 到硬件 selector 的映射。ARC 请求使用
  对应 `*.lvl` 资源地址和 selector；保留表首的 OFF 项，才能保留原始下标。
- VRM 电压请求使用 VRM 资源及电压单位，厂商实现采用毫伏；不能把 ARC
  level 值直接作为 VRM 电压。
- AUX 表的重复值也占用原始下标，不能通过删除零项、去重来重新编号。

本机保存的 command-db 中 `gfx.lvl` 地址为 `0x30050`，`vrm.gfx` 为
`0x42700`。这些事实不能证明 XNU 已拥有相应 TCS 或供电资源。

**下一项代码工作：**修正纯离线 Python/C 请求模型，区分 resource address、
consumer level、selector 和 VRM 电压；增加针对厂商语义的回归测试。
保留无发送路径的状态。现有 8 个 composer 测试重复了旧假设，测试通过
不能证明编码正确。

### 2. iommus 的第一个 cell 是 provider phandle

`D:\ios\recon\dt_gpu_binary.txt` 保存了如 `gfx3d_user` 的
`iommus = <0x208 0x0>`，以及 GMU 对应的参数 4/5。
通用 IOMMU binding 定义该属性为 phandle/specifier 对：第一个 cell
`0x208` 是 provider 的设备树句柄，不能当作 stream ID。

`tools/polaris_cmddb.py` 的 `SID_MAP`、0095 的 `pg_sid_map` 和旧的
`handset-cmd-db-and-domain-facts.md` 第 7 节把它解释成 SID，并把后一个
参数解释成 context bank，证据不足；这次更正优先于这些旧描述。

**下一项数据工作：**解析 provider 的 phandle、`#iommu-cells` 和厂商
SMMU binding/驱动；分别确认 SID、mask、动态 context bank 分配和 HYP
限制。不能直接把现有表用于 SMR/S2CR/CB 编程。

## 真正启用 GPU 的开发顺序和验收

1. 完成上述编码、DT 解析修正，然后实现 Polaris 专用 RPMh/TCS、供电、
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
