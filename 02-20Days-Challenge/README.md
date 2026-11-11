# 项目一：ESP32-CAM 极致省电（Ultra-Low Power）方案设计与实证

硬件：AI-Thinker ESP32-CAM（ESP32-D0WDQ6 + OV2640 + microSD）+ USB 电压电流表。
同一块板、同一套拍照逻辑、同样保留 WiFi，两级固件对照：`viewer`（主基线，WiFi 常开）与
`powersave`（开机 15 分钟 WiFi / 网页窗口，窗口结束断射频进深睡，定时唤醒只拍照不联网）。

**一句话结论**：24 h 平均电流从基线的 `90 mA`（USB 表直读）降到 `5.99–10.94 mA`（实测段 + 深睡区间推算），
即 **8.3–15 倍**；按 1600 mAh 可用电量，续航 `17.8 h → 6.1–11.1 天`。
10 倍能否成立取决于深睡电流（判据见 §4）。

## 评分项对照

| 评分项 | 题目要求 | 本仓库对应文件 | 状态 |
|---|---|---|---|
| **①** 15 分 | 优化前后各阶段实测电流对照表与视频 | [current-comparison.csv](measurement/current-comparison.csv) + 5 段表读数录屏（§1） | ✅ 冷启动 / 窗口 / 拍照 / 唤醒 / 深睡（上界）都有表读数；基线 P3 未单测 |
| **②** 25 分 | 连续 24 小时以上电池电压 / 功耗实测时序 CSV 日志 | 3 份 `POWER.CSV` + 1 份表盘读数转写：基线 24.00 h ×2、省电版 15.20 h（§2） | 🟡 基线 24 h 日志齐；省电版窗口外 < 0.01 A，表停表不记录（仪器限制），只能按段推算 |
| **③** 20 分 | 功耗预算推导模型与状态机源码 | [theory.py](measurement/theory.py)、[phases.py](measurement/phases.py)、[powersave.ino](firmware/esp32cam-powersave/powersave/powersave.ino)（§3） | ✅ 模型与状态机均可复跑 |

> 口径提醒：[方案文档](docs/ESP32-CAM-Ultra-Low-Power-Solution.md) 里的 `17.1 mA → 1.54 mA / 11 倍` 是**设计测算**（T=60 s、每次都上传）；
> 本页的 `90 → 5.99–10.94 mA / 8.3–15 倍` 是**实机口径**（WiFi 常开基线 vs 15 min 窗口 + 深睡）。两者基线不同，不要混用。

---

## 1. 评分项 ①：优化前后各阶段电流对照（15 分）

**测法**：USB 表串在 5 V 输入端，量的是表后整条路径（AMS1117 + 摄像头 + SD + 芯片）；0.01 A 分辨率、秒级刷新。
全量对照表（含单位、电压、方法与证据列）在 [measurement/current-comparison.csv](measurement/current-comparison.csv)，摘要：

| 阶段 | 基线 viewer | 省电版 powersave | 性质 |
|---|---|---|---|
| P1 冷启动（上电 → WiFi/NTP → 首拍） | `0.09–0.16 A` | `0.09–0.16 A` | 上电瞬间在区间内波动 |
| P6 常开空闲（WiFi 关联、不看网页） | `0.09 A / 5.04 V` | `0.09–0.10 A / 4.90 V` | 两次独立直读，1 个字内一致 |
| P6 开网页（浏览器翻图） | `0.11–0.14 A` | `0.12–0.19 A`，峰值 `0.22 A` | 直读 + 录屏 |
| P3 拍照 + 写卡（连拍放大占空比） | 未单测 | `0.13–0.16 A` | 直读，拍照时 WiFi 仍关联 |
| P4 深睡 | 不适用（不休眠） | `≤ 0.01 A` | 表上界，测不出具体值 |
| P5 单次唤醒（复位→再入睡） | 不适用 | `1.4–2.1 s` | 串口 `[CAP]`/`[SLEEP]` 时间戳 |
| 24 h 平均 | `90 mA`（健康段）/ `136 mA`（异常日） | `5.99–10.94 mA`（推算） | 见 §2 |

**视频**（均在 [evidence/](evidence/) 下，抽帧图同目录）：

| 视频 | 内容 | 时长 |
|---|---|---|
| [meter_sleep_vs_capture.mp4](evidence/powersave-meter-2026-11-10/meter_sleep_vs_capture.mp4) | 深睡 ↔ 拍照，表始终 `0.00 A`：证明变化小于表分辨率 | 60.7 s |
| [meter_window_idle.mp4](evidence/powersave-meter-2026-11-10/meter_window_idle.mp4) | 省电版窗口空闲 `0.09–0.10 A` | 38.9 s |
| [meter_window_web_load.mp4](evidence/powersave-meter-2026-11-10/meter_window_web_load.mp4) | 省电版窗口内开网页：`0.09 → 0.18 A`，峰值 `0.22 A` | 35.0 s |
| [video_20261110_212524772.mp4](evidence/baseline-viewer-meter-2026-11-10/video_20261110_212524772.mp4) | 基线常开空闲 `0.09 A`，开网页 `0.11–0.14 A` | 49.4 s |
| [video_20261111_120804103.mp4](evidence/baseline-24h-meter-2026-11-10/video_20261111_120804103.mp4) | 24 h 轮次中 12:08 WiFi 重连：`0.18 → 0.09 A` | 10.5 s |

**这张表能证明什么、不能证明什么**

- 能证明：两条固件「开着 WiFi 不干活」的底值相同（`0.09 A`），所以跨固件比较成立；窗口段、拍照段的量级与电压都有现场读数。
- 不能证明：深睡的定量值（`0.00 A` 只说明 < 10 mA，3 mA 与 8 mA 分不开）；拍照峰值（`capture=0 ms / save=60–90 ms` 的脉冲落在秒级采样窗之间）；基线的 P3 单独电流（未测）。
- 表内 `A` 是瞬时值、`W` 是时段平均，功率/能量一律用 `A × V` 或累计 `mWh ÷ 时间` 计算，不用 `W` 反推电流。

## 2. 评分项 ②：24 h 连续时序 CSV（25 分）

| 目录 | 固件 | 跨度 | 数据行 | 电压字段 | 电流字段 | 性质 |
|---|---|---|---|---|---|---|
| [baseline-24h-2026-11-09](evidence/baseline-24h-2026-11-09/README.md) | viewer（基线） | 24.00 h | 322 | `v5_mv=-1`（未接分压，按 5.0 V 记） | 固定 `45 mA` 模型 | 设备侧模型日志 |
| [baseline-24h-meter-2026-11-10](evidence/baseline-24h-meter-2026-11-10/README.md) | viewer（基线） | 24.00 h | 317 | 同上 | 固定 `45 mA` 模型 | 设备侧模型日志 + 表端点实测 |
| [powersave-15h-2026-11-10](evidence/powersave-15h-2026-11-10/README.md) | powersave（省电版） | 15.20 h | 50 | 同上 | `95 mA`（窗口）/ `5 mA`（深睡模型） | 设备侧模型日志，**不足 24 h** |
| [meter-readings.csv](evidence/baseline-24h-meter-2026-11-10/meter-readings.csv) | viewer（基线） | 24.01 h（10 点稀疏） | 10 | 表读 `5.04 / 4.93 V` | 表读 `90 / 180 / 190 mA` | **表实测，稀疏转写** |

**为什么省电版没有 24 h 表记录**：深睡电流只有 5 mA 量级，低于表的 0.01 A 分辨率；每小时唤醒拍照又只有 60–90 ms 的脉冲，摊进秒级采样窗读不出稳定值（§1 里 `0.13–0.16 A` 是连拍放大占空比后的读数）。表在电流归零/低于阈值时**停表不再累计**，整段 24 h 采不到曲线——这是仪器限制，不是漏跑。能采的只有窗口段 `0.09–0.10 A`，其余按 §3.1 的占空比推算；要 24 h 连续实测得换 INA219 / 带记录的表，或用万用表 mA 档分时采样。

**表实测到的 24 h 端点**（[baseline-24h-meter README](evidence/baseline-24h-meter-2026-11-10/README.md)）：
2026-11-10 20:53 → 11-11 20:53，健康段两端都是 `0.09 A`；08:20 起 WiFi 断连抬到 `0.18 A`，表累计 `≈16.38 Wh ≈ 136 mA` 平均。
表计时 24 h 慢 7 min，按墙钟当分母。10 个读数点（含断连段与两次鼠标续测）逐点转写在
[meter-readings.csv](evidence/baseline-24h-meter-2026-11-10/meter-readings.csv)。

**必须说清的口径**：三份 `POWER.CSV` 是设备写的**时序日志**，其中的电流/电压字段来自固件常量与 `-1` 占位，
**不是表实测的连续曲线**；`meter-readings.csv` 是 10 个表盘读数的转写，点与点之间没有采样。
表的连续记录能力受 0.01 A 分辨率与「小电流停表」限制——省电版深睡时表直接停表，所以没有它的 24 h 表曲线；真正实测的是阶段直读、10 个读数点与 24 h 端点。
所以本项的交付是「24 h 连续日志 + 表读数点」，不把它写成「24 h 实测曲线」。
另外，所有电流都在 5 V 输入侧测得，**不是电池端**；续航按 1600 mAh 可用折算，不是电池放电实测。

**补齐 ② 的路径**：0.01 A USB 表在省电版深睡时会停表，直接跑 24 h 也采不到曲线，必须换 INA219 / 带记录的表（或用万用表 mA 档分时采样）才能拿到连续实测；固件与日志表头不用改。

## 3. 评分项 ③：功耗预算模型与状态机源码（20 分）

### 3.1 功耗预算推导模型

[theory.py](measurement/theory.py) 把 24 h 拆成「窗口段 + 唤醒拍照段 + 深睡段」，只把实测值代进公式：

```text
e_win   = I_win  × 900 s                       （窗口段，每天 1 次；实测 95 mA）
e_wake  = I_wake × t_wake × 24                 （唤醒段，每天 24 次；实测 145 mA × 1.4 s）
e_sleep = I_sleep × (86400 − 900 − 24 × t_wake)（深睡段；I_sleep ∈ [5 mA 模型, 10 mA 表上界]）
I_avg   = (e_win + e_wake + e_sleep) / 24 h
```

电量单位 mAh；秒换算小时在 `theory.py` 内部按 ÷3600 处理。

| 口径 | 24 h 电量 | 平均电流 | 续航（1600 mAh 可用） | 相对基线 |
|---|---|---|---|---|
| 深睡按模型 5 mA | 143.8 mAh | 5.99 mA | 11.1 天 | 15.0× |
| 深睡按表上界 10 mA | 262.5 mAh | 10.94 mA | 6.1 天 | 8.2× |
| 全部按保守上限（窗口 0.09 A，其余 0.01 A） | 260.0 mAh | 10.83 mA | 6.15 天 | 8.3× |
| 基线 viewer（健康段 0.09 A，含 24 次拍照修正） | 2160.5 mAh | 90.0 mA | 0.74 天 | 1× |

模型的两个已知修正：窗口段模型原按 `165 mA`，实测 `95 mA`，高估约 1.7 倍；基线的 `45 mA` 固件模型不含 WiFi 电流，实测是它的 2 倍。

### 3.2 状态机

```text
上电/复位 ─► 冷启动：连 WiFi+NTP ─► 拍照 ─► Web 窗口 15 min ─► 停网页/断射频 ─► 关摄像头、卸载 SD ─► deep sleep 1 h
                                                        └─ 窗口内可查图、下载 POWER.CSV
deep sleep 定时唤醒 ─► 释放 PWDN 保持、恢复时间/能耗 ─► 拍照（不连 WiFi）─► deep sleep
```

| 状态 / 动作 | 源码位置 |
|---|---|
| 唤醒原因分叉（冷启动 vs 定时唤醒）、重新上电自动复位 | `setup()` |
| 拍照 + 写卡 + 记录 `[CAP]` | `captureOnce()` |
| 关摄像头：`esp_camera_deinit()` + PWDN 拉高 + `gpio_hold_en` | `powerDownCamera()` / `releaseCameraPowerHold()` |
| 卸载 SD → 设置定时器唤醒 → `esp_deep_sleep_start()` | `sleepUntil()` |
| Web 窗口开关、`WiFi.mode(WIFI_OFF)` | `startWeb()` / `stopWeb()` |
| 能耗记账、`POWER.CSV` 追加 | `accumulateEnergy()` / `powerLogAppend()` |
| 串口日志切阶段（P1–P6） | [phases.py](measurement/phases.py) |

### 3.3 题面三项策略的落地情况

| 题面策略 | 落地 | 证据 | 状态 |
|---|---|---|---|
| 外设断电控制 | 拍照后 `esp_camera_deinit()` + PWDN 保持高电平；睡眠前 `SD_MMC.end()`；闪光灯 GPIO4 拉低 | `powerDownCamera()`、`sleepUntil()` | ✅ 软件侧；MOSFET 切供电未做（硬件项） |
| Deep-Sleep 深度唤醒 | 每小时 timer 唤醒，唤醒只拍照、不连 WiFi；状态与能耗存 `RTC_DATA_ATTR` | `sleepUntil()`、`kCaptureIntervalMs` | ✅ |
| 时钟降频 | 未做（默认 240 MHz） | 固件 README「没有做（及原因）」 | ❌ 收益与风险不成比例：活跃段合计约 34–50 s/天（24 次唤醒 × 1.4–2.1 s），相机/SD 电流不随 CPU 主频下降，固件 README 估算省不到 0.1 %，却要给 OV2640 XCLK / SDMMC 时序引入风险 |

## 4. 「10 倍」怎么判

按 24 h 平均电流算，10 倍要求 `I_avg ≤ 90 / 10 = 9.0 mA`。代入 §3.1 的式子：

```text
I_avg ≈ 1.05 + 0.989 × I_sleep  (mA)
→ I_sleep ≤ 8.0 mA 时达到 10 倍（更精确 8.04 mA）
```

- 深睡 = 模型 5 mA → `5.99 mA`，**15.0×**；
- 深睡 = 表上界 10 mA → `10.94 mA`，**8.2×**，不到 10 倍；
- 全保守上限 → `10.83 mA`，**8.3×**。

结论：**「省十倍」这个量级成立，但严格按表上界不算达标**；它取决于深睡电流是否落在模型值附近。下一步用万用表 mA 档串测深睡即可收口（补齐路径见 §2 末）。

## 5. 目录结构

```text
02-20Days-Challenge/
├── README.md                        # 本页：评分项 → 交付物索引
├── docs/
│   ├── ESP32-CAM-Ultra-Low-Power-Solution.md  # 方案：功耗测算、架构、sdkconfig、陷阱
│   └── FreeRTOS-V11.3.1-Source-Analysis.md     # 内核源码分析（附功耗专题）
├── firmware/
│   ├── esp32cam-viewer/             # 主基线：WiFi 常开 + 每小时一张 + 网页
│   ├── esp32cam-powersave/          # 省电版：15 min 窗口 + 深睡占空比（状态机源码）
│   └── esp32cam-capture-probe/      # 拍照电流标定探针（连拍放大占空比）
├── measurement/                     # 评分项 ①③：对照表、24 h 预算模型、阶段切分工具
│   ├── current-comparison.csv       # 优化前后各阶段电流对照表（本页 §1 的全量表）
│   ├── README.md                    # 测量方案、接线、表限制、已知误差
│   ├── theory.py                    # 24 h 功耗预算推导
│   ├── phases.py                    # 串口日志切 P1–P6
│   ├── serial_capture.py            # 宿主机抓串口（带时间戳、--reset）
│   └── measure-record.csv           # 每阶段实测打点原始记录
└── evidence/                        # 评分项 ①②：时序 CSV + 视频 + 照片
    ├── baseline-24h-2026-11-09/          # 基线 24.00 h：24 张逐小时照片 + 模型 CSV
    ├── baseline-24h-meter-2026-11-10/    # 基线 24 h 表端点 + 逐小时照片 + 模型 CSV
    ├── baseline-viewer-meter-2026-11-10/ # 基线常开直读 + 开网页录屏
    ├── powersave-15h-2026-11-10/         # 省电版 15.20 h 运行片段（模型 CSV）
    └── powersave-meter-2026-11-10/       # 省电版三段录屏 + 抽帧 + 拍照抽样
```

## 6. 复现

```bash
cd 02-20Days-Challenge
export ARDUINO_DIRECTORIES_DATA=$PWD/.arduino/data ARDUINO_DIRECTORIES_USER=$PWD/.arduino/user

# 两级固件（esp32 核心 3.3.12；WiFi 凭据放各固件目录的 secrets.h，已 gitignore）
./arduino-cli compile --fqbn esp32:esp32:esp32cam --build-path .arduino/build-viewer    firmware/esp32cam-viewer/viewer
./arduino-cli compile --fqbn esp32:esp32:esp32cam --build-path .arduino/build-powersave firmware/esp32cam-powersave/powersave

# 24 h 预算（不需要硬件）
python3 measurement/theory.py

# 把串口日志切成阶段（P1–P6，可追加到 measure-record.csv）
python3 measurement/phases.py <串口日志> --summary
```

30 s 短周期测量档的编译宏、烧录与串口抓取见 [measurement/README.md](measurement/README.md)；
烧录/看串口在本机走宿主机（`distrobox-host-exec`），板子 DTR/RTS 已接 GPIO0/EN。

## 7. 局限与未完成（主动说明）

- **深睡电流只有上界**：0.01 A 表读 `0.00 A`，只能写 `≤ 10 mA`；24 h 能量里 80 %+ 是深睡项，这是倍数区间 8.3–15× 的全部来源。
- **拍照峰值测不到**：`capture=0 ms / save=60–90 ms`，秒级表抓不到，只有连拍放大后的平均值。
- **P1 冷启动只有区间**：时长约 6 s，电流在上电瞬间于 `0.09–0.16 A` 之间波动，没有稳定均值；对 24 h 占比 < 0.1 %。
- **省电版没有 24 h 表记录**：深睡与唤醒拍照时表读 `0.00 A`（低于 0.01 A 分辨率），表停表不累计，24 h 曲线采不到——仪器限制，不是漏跑；现有的是 15.20 h 设备侧模型日志。基线有 24 h 端点实测，两边不是同一种「实测」。
- **CSV 的电压字段是 `-1`**：未接分压电阻，按 5.0 V 名义值记账，所以 `Wh` 换算有约 ±2 % 误差；`mAh` 与平均电流不受影响。
- **基线异常日**：2026-11-11 有约 12.6 h WiFi 断连（`0.18 A`），单列为异常日，不进倍数表。
- **未做硬件改造**：换 LDO（AMS1117 静态约 5 mA 是深睡硬上限）、MOSFET 切摄像头/SD 供电、去板载 LED，都只写入方案未实做。
- **没有接电池**：全部读数在 5 V USB 输入侧，`v5_mv=-1` 未接分压；「续航 N 天」是按 1600 mAh 可用折算的预算值。
- **未做时钟降频**：题面三项策略里唯一未落地的软件项，理由见 §3.3。

## 8. 相关文档

- 方案与测算：[docs/ESP32-CAM-Ultra-Low-Power-Solution.md](docs/ESP32-CAM-Ultra-Low-Power-Solution.md)
- 内核源码分析（含功耗专题）：[docs/FreeRTOS-V11.3.1-Source-Analysis.md](docs/FreeRTOS-V11.3.1-Source-Analysis.md)
- 测量方案、接线与误差：[measurement/README.md](measurement/README.md)
- 总仓库入口：[../README.md](../README.md)
