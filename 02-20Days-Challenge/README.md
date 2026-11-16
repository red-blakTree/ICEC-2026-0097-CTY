# 项目一：ESP32-CAM 极致省电（Ultra-Low Power）方案设计与实证

> 硬件：AI-Thinker ESP32-CAM（ESP32-D0WDQ6 + OV2640 + microSD）+ USB 电压电流表（5 V 输入侧）
> 固件：`esp32cam-viewer`（主基线，WiFi 常开）与 `esp32cam-powersave`（15 min 窗口 + 深睡占空比）
> 结论：24 h 平均电流 `90 mA → 6.98–10.94 mA`，**8.2–12.9 倍**；按官方手册 6 mA 点值为 `6.98 mA / 12.9×`，满足“10 倍以上”。

## 0. 项目速览

| 模块 | 任务要求 | 本仓库交付 | 状态 |
|---|---|---|---|
| **①** | 优化前后各阶段实测电流对照表与视频 | 第 1 节对照表 + [current-comparison.csv](measurement/current-comparison.csv) + 6 段录屏 | ✅ 五阶段都有读数；基线 P3 为同条件推断 + 1 s 视频表读 |
| **②** | 连续 24 h 以上电池电压/功耗实测时序 CSV | 第 2 节 3 份 `POWER.CSV` + 表盘读数转写 + 24 h 表端点 | 🟡 24 h 设备侧时序与表端点齐；**连续表曲线受 0.01 A 表停表限制**，不是 24 h 实测曲线 |
| **③** | 功耗预算推导模型与状态机源码 | [theory.py](measurement/theory.py) + [powersave.ino](firmware/esp32cam-powersave/powersave/powersave.ino) | ✅ 模型可复跑，状态机源码完整 |

**阅读入口**：本节 → [measurement/README.md](measurement/README.md) 的「数据齐套检查」 → [evidence/](evidence/) 的 6 个证据目录。

## 1. 各阶段电流对照

### 1.1 测法

USB 表串在 5 V 输入端，量的是表后整条路径（AMS1117 + 摄像头 + SD + 芯片）；0.01 A 分辨率、秒级刷新。对照表按 P1–P6 分阶段，全量字段（单位、电压、方法、证据）在 [current-comparison.csv](measurement/current-comparison.csv)。

| 阶段 | 基线 viewer | 省电版 powersave | 性质 |
|---|---|---|---|
| P1 冷启动（上电 → WiFi/NTP → 首拍） | `0.09–0.16 A` | `0.09–0.16 A` | 上电瞬间在区间内波动 |
| P6 常开空闲（WiFi 关联、不看网页） | `0.09 A / 5.04 V` | `0.09–0.10 A / 4.90 V` | 两次独立直读，1 个字内一致 |
| P6 开网页（浏览器翻图） | `0.11–0.14 A` | `0.12–0.19 A`，峰值 `0.22 A` | 直读 + 录屏 |
| P3 拍照 + 写卡（连拍放大占空比） | `130–160 mA`（同条件推断；视频 1 s 表读 `0.10–0.13 A`） | `0.13–0.16 A` | 省电版连拍实测；基线未单测，见 1.3 |
| P4 深睡 | 不适用（不休眠） | `≤ 0.01 A`（表）；官方手册 `6 mA @ 5 V` | 表只给上界，手册给点值 |
| P5 单次唤醒（复位 → 再入睡） | 不适用 | `1.4–2.1 s` | 串口 `[CAP]`/`[SLEEP]` 时间戳 |
| 24 h 平均 | `90 mA`（健康段）/ `136 mA`（异常日） | `6.98–10.94 mA`（推算） | 见第 2、4 节 |

### 1.2 视频证据

| 视频 | 内容 | 时长 |
|---|---|---|
| [meter_sleep_vs_capture.mp4](evidence/powersave-meter-2026-11-10/meter_sleep_vs_capture.mp4) | 深睡 ↔ 拍照，表始终 `0.00 A`：证明变化小于表分辨率 | 60.7 s |
| [meter_window_idle.mp4](evidence/powersave-meter-2026-11-10/meter_window_idle.mp4) | 省电版窗口空闲 `0.09–0.10 A` | 38.9 s |
| [meter_window_web_load.mp4](evidence/powersave-meter-2026-11-10/meter_window_web_load.mp4) | 省电版窗口内开网页：`0.09 → 0.18 A`，峰值 `0.22 A` | 35.0 s |
| [video_20261110_212524772.mp4](evidence/baseline-viewer-meter-2026-11-10/video_20261110_212524772.mp4) | 基线常开空闲 `0.09 A`，开网页 `0.11–0.14 A` | 49.4 s |
| [video_20261111_120804103.mp4](evidence/baseline-24h-meter-2026-11-10/video_20261111_120804103.mp4) | 24 h 轮次中 12:08 WiFi 重连：`0.18 → 0.09 A` | 10.5 s |
| [video_20261116_184118896.mp4](evidence/baseline-viewer-meter-2026-11-16/video_20261116_184118896.mp4) | 基线 P3：24 s 内 10 次 `/capture`，表 1 s 读 `0.09 → 0.10–0.13 A` | 36.4 s |

### 1.3 P3 的口径

- 省电版 P3 的 `0.13–0.16 A` 是**连拍放大占空比**后的表读：窗口内 24 s 发 10 次 `/capture`，把 60–90 ms 的拍照+写卡脉冲摊到表能读的窗口。
- 基线 P3 没有单独跑同口径连拍，按“同硬件、同 WiFi 关联、同拍照/写卡”推断为 `130–160 mA`；2026-11-16 的基线连拍视频给出 **1 s 表读 `0.10–0.13 A`**，已作为视频证据归档，但它**不是** 60–90 ms 的 P3 平均。
- 结论：P3 的定量值仍用 `0.13–0.16 A`；视频的 `0.10–0.13 A` 只作 1 s 窗口旁证。两者不互换。

### 1.4 这张表能证明 / 不能证明

- 能证明：两条固件“开着 WiFi 不干活”的底值相同（`0.09 A`），跨固件比较成立；窗口段、P3、P5 都有现场读数或录屏。
- 不能证明：P4 的定量值（`0.00 A` 只说明 `< 10 mA`）；60–90 ms 的拍照峰值；基线的 P3 60–90 ms 平均值（只有 1 s 视频表读）。

## 2. 24 h 时序数据

### 2.1 数据清单

| 目录/文件 | 固件 | 跨度 | 数据行 | 电压字段 | 电流字段 | 性质 |
|---|---|---|---|---|---|---|
| [baseline-24h-2026-11-09](evidence/baseline-24h-2026-11-09/README.md) | viewer | 24.00 h | 322 | `v5_mv=-1`（未接分压，按 5.0 V 记） | 固定 `45 mA` 模型 | 设备侧模型日志 + 24 张逐小时照片 |
| [baseline-24h-meter-2026-11-10](evidence/baseline-24h-meter-2026-11-10/README.md) | viewer | 24.00 h | 317 | 同上 | 固定 `45 mA` 模型 | 设备侧模型日志 + 表端点实测 + 10 点转写 |
| [powersave-15h-2026-11-10](evidence/powersave-15h-2026-11-10/README.md) | powersave | 15.20 h | 50 | 同上 | `95 mA`（窗口）/ `5 mA`（深睡模型） | 设备侧模型日志，**不足 24 h** |
| [meter-readings.csv](evidence/baseline-24h-meter-2026-11-10/meter-readings.csv) | viewer | 24.01 h（10 点稀疏） | 10 | 表读 `5.04 / 4.93 V` | 表读 `90 / 180 / 190 mA` | **表实测，稀疏转写** |

### 2.2 基线 24 h 表端点

2026-11-10 20:53 → 11-11 20:53，健康段两端都是 `0.09 A / 5.04 V`；08:20 起 WiFi 断连抬到 `0.18 A`，表累计 `≈16.38 Wh ≈ 136 mA` 平均。健康口径 `2.16 Ah / 10.8 Wh`，异常日单列、不进倍数表。表计时 24 h 慢 7 min，按墙钟当分母（高估 0.49 %）。逐点读数见 [meter-readings.csv](evidence/baseline-24h-meter-2026-11-10/meter-readings.csv)。

### 2.3 为什么省电版没有 24 h 表曲线（仪器限制）

- 深睡电流只有 5–6 mA（官方手册 6 mA），低于表的 0.01 A 分辨率；表在电流归零/低于阈值时**停表不再累计**。
- 每小时唤醒拍照只有 60–90 ms，摊进秒级采样窗读不出稳定值。
- 所以省电版 24 h 里约 99 % 时间是深睡，**“直读深睡”在这块表上不成立**；能采的只有窗口段 `0.09–0.10 A`，其余按第 4 节占空比推算。
- 要 24 h 连续实测，需 INA219 一类低阻分流记录模块或带记录的表；**万用表在本板不可行**（无法从源头串入测量）。这是**仪器限制，不是漏跑**。

### 2.4 能证明 / 不能证明

- 能证明：基线 24 h 的设备侧时序、24 张逐小时照片、两端表读数、10 个表盘点、断连段 `0.18 A`。
- 不能证明：省电版的 24 h 连续实测曲线；充电宝端电压/放电（全部读数在 5 V USB 输入侧，`v5_mv=-1`）。
- **口径**：三份 `POWER.CSV` 的电流/电压字段来自固件常量与 `-1` 占位，不是表实测的连续曲线；`meter-readings.csv` 是 10 个表盘点，点与点之间没有采样。本项交付是“24 h 连续日志 + 表读数点”，不写成“24 h 实测曲线”。

## 3. 功耗预算模型与状态机

### 3.1 模型

[theory.py](measurement/theory.py) 把 24 h 拆成“窗口段 + 唤醒拍照段 + 深睡段”，只把实测值代进公式：

```text
e_win   = I_win  × 900 s                       （窗口段，每天 1 次；实测 95 mA）
e_wake  = I_wake × t_wake × 24                 （唤醒段，每天 24 次；实测 145 mA × 1.4 s）
e_sleep = I_sleep × (86400 − 900 − 24 × t_wake)（深睡段；I_sleep ∈ [6 mA 手册, 10 mA 表上界]）
I_avg   = (e_win + e_wake + e_sleep) / 24 h
```

### 3.2 结果

| 口径 | 24 h 电量 | 平均电流 | 续航（1600 mAh 可用） | 相对基线 |
|---|---|---|---|---|
| 深睡按官方手册 6 mA | 167.5 mAh | 6.98 mA | 9.5 天 | 12.9× |
| 深睡按表上界 10 mA | 262.5 mAh | 10.94 mA | 6.1 天 | 8.2× |
| 全部按保守上限（窗口 0.09 A，其余 0.01 A） | 260.0 mAh | 10.83 mA | 6.15 天 | 8.3× |
| 基线 viewer（健康段 0.09 A，含 24 次拍照修正） | 2160.5 mAh | 90.0 mA | 0.74 天 | 1× |

> 早期按 AMS1117 静态 5 mA 估的 `5.99 mA / 15.0×` 只是 LDO-only 下界，已被官方手册 6 mA 取代，不再列入主表（`theory.py --i-sleep 5` 可复现）。

模型的已知修正：窗口段模型原按 `165 mA`，实测 `95 mA`，高估约 1.7 倍；基线的 `45 mA` 固件模型不含 WiFi 电流，实测是它的 2 倍；深睡按官方手册整板 6 mA，旧 5 mA 只是 AMS1117 静态，已不作主口径。

### 3.3 状态机

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

### 3.4 题面三项策略的落地

| 策略 | 落地 | 证据 | 状态 |
|---|---|---|---|
| 外设断电控制 | 拍照后 `esp_camera_deinit()` + PWDN 保持高电平；睡眠前 `SD_MMC.end()`；闪光灯 GPIO4 拉低 | `powerDownCamera()`、`sleepUntil()` | ✅ 软件侧；MOSFET 切供电未做（硬件项） |
| Deep-Sleep 深度休眠唤醒 | 每小时 timer 唤醒，唤醒只拍照、不连 WiFi；状态与能耗存 `RTC_DATA_ATTR` | `sleepUntil()`、`kCaptureIntervalMs` | ✅ |
| 时钟降频 | 未做（默认 240 MHz） | [固件 README](firmware/esp32cam-powersave/README.md)「没有做（及原因）」 | ❌ 活跃段合计约 34–50 s/天，相机/SD 电流不随 CPU 主频下降，估算省不到 0.1 %，却要给 OV2640 XCLK / SDMMC 时序引入风险 |

## 4. “10 倍”怎么判

按 24 h 平均电流算，10 倍要求 `I_avg ≤ 90 / 10 = 9.0 mA`。代入第 3.1 节的式子：

```text
I_avg ≈ 1.05 + 0.989 × I_sleep  (mA)
→ I_sleep ≤ 8.0 mA 时达到 10 倍（更精确 8.04 mA）
```

- 深睡 = 官方手册 6 mA → `6.98 mA`，**12.9×**；
- 深睡 = 表上界 10 mA → `10.94 mA`，**8.2×**，不到 10 倍；
- 全保守上限 → `10.83 mA`，**8.3×**。

结论：**按官方手册 6 mA，“省十倍”达标（12.9×）**；只有把表分辨率上界 10 mA 当真实值时才掉到 8.2×，而 10 mA 是仪器上界、不是实测值。整板电流用万用表测不了：无法从源头串入（原因见 [测量方案](measurement/README.md) 第 6 节）；要单板真值需 INA219 一类低阻分流记录。

## 5. 局限与未完成

- **深睡电流：表只给上界，手册给 6 mA**：0.01 A 表读 `0.00 A`，只能写 `≤ 10 mA`；ESP32-CAM 数据手册写 `Deep-Sleep: 6 mA @ 5V`，作为板级主口径（6.98 mA / 12.9×）。24 h 能量里 80 %+ 是深睡项，倍数区间 8.2–12.9× 来自“6 mA 手册 / 10 mA 表上界”。官方文档里的 `< 1 µA` 是 SPI Flash DPD、`10–30 µA` 是 SPI Flash 待机，不能当板级深睡（见 [measurement/README.md](measurement/README.md) 的「官方参考值」）。
- **拍照峰值测不到**：`capture=0 ms / save=60–90 ms`，秒级表抓不到，只有连拍放大后的平均值。
- **P1 冷启动只有区间**：时长约 6 s，电流在上电瞬间于 `0.09–0.16 A` 之间波动，没有稳定均值；对 24 h 占比 < 0.1 %。
- **省电版没有 24 h 表记录**：深睡与唤醒拍照时表读 `0.00 A`（低于 0.01 A 分辨率），表停表不累计，24 h 曲线采不到——仪器限制，不是漏跑；现有的是 15.20 h 设备侧模型日志。基线有 24 h 端点实测，两边不是同一种“实测”。
- **CSV 的电压字段是 `-1`**：未接分压电阻，按 5.0 V 名义值记账，所以 `Wh` 换算有约 ±2 % 误差；`mAh` 与平均电流不受影响。
- **基线异常日**：2026-11-11 有约 12.6 h WiFi 断连（`0.18 A`），单列为异常日，不进倍数表。
- **未做硬件改造**：换 LDO（AMS1117 静态约 5 mA 是深睡主要构成，整板手册 6 mA）、MOSFET 切摄像头/SD 供电、去板载 LED，都只写入方案未实做。
- **供电是充电宝/充电器，不是电池**：基线 24 h 由充电宝经 USB 表供电；省电版平均约 5 mA，充电宝会判“无负载”自动断电，改用充电器。`v5_mv=-1` 未接分压；“续航 N 天”是按 1600 mAh 可用折算的预算值，不是实测电池续航。
- **未做时钟降频**：题面三项策略里唯一未落地的软件项，理由见第 3.4 节。

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

30 s 短周期测量档的编译宏、烧录与串口抓取见 [measurement/README.md](measurement/README.md)；烧录/看串口在本机走宿主机（`distrobox-host-exec`），板子 DTR/RTS 已接 GPIO0/EN。

## 7. 目录与证据索引

```text
02-20Days-Challenge/
├── README.md                        # 本页：项目 → 交付物索引
├── docs/
│   ├── ESP32-CAM-Ultra-Low-Power-Solution.md  # 方案：功耗测算、架构、sdkconfig、陷阱
│   └── FreeRTOS-V11.3.1-Source-Analysis.md     # 内核源码分析（附功耗专题）
├── firmware/
│   ├── esp32cam-viewer/             # 主基线：WiFi 常开 + 每小时一张 + 网页
│   ├── esp32cam-powersave/          # 省电版：15 min 窗口 + 深睡占空比（状态机源码）
│   └── esp32cam-capture-probe/      # 拍照电流标定探针（连拍放大占空比）
├── measurement/                     # 测量与预算：对照表、24 h 预算模型、阶段切分工具
│   ├── current-comparison.csv       # 优化前后各阶段电流对照表（本页第 1 节的全量表）
│   ├── README.md                    # 测量方案、接线、表限制、已知误差
│   ├── theory.py                    # 24 h 功耗预算推导
│   ├── phases.py                    # 串口日志切 P1–P6
│   ├── serial_capture.py            # 宿主机抓串口（带时间戳、--reset）
│   └── measure-record.csv           # 每阶段实测打点原始记录
└── evidence/                        # 证据：时序 CSV + 视频 + 照片
    ├── baseline-24h-2026-11-09/          # 基线 24.00 h：24 张逐小时照片 + 模型 CSV
    ├── baseline-24h-meter-2026-11-10/    # 基线 24 h 表端点 + 逐小时照片 + 模型 CSV
    ├── baseline-viewer-meter-2026-11-10/ # 基线常开直读 + 开网页录屏
    ├── baseline-viewer-meter-2026-11-16/ # 基线 P3 24 s/10 次连拍录屏（已静音）
    ├── powersave-15h-2026-11-10/         # 省电版 15.20 h 运行片段（模型 CSV）
    └── powersave-meter-2026-11-10/       # 省电版三段录屏 + 抽帧 + 拍照抽样
```

## 8. 相关文档

- 方案与测算：[docs/ESP32-CAM-Ultra-Low-Power-Solution.md](docs/ESP32-CAM-Ultra-Low-Power-Solution.md)
- 内核源码分析（含功耗专题）：[docs/FreeRTOS-V11.3.1-Source-Analysis.md](docs/FreeRTOS-V11.3.1-Source-Analysis.md)
- 测量方案、接线与误差：[measurement/README.md](measurement/README.md)
- 总仓库入口：[../README.md](../README.md)
