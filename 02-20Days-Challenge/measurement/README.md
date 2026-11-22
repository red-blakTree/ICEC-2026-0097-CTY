# 测量方案：ESP32-CAM 实机电流（USB 电压电流表，5 V 输入侧）

> 目标：用实测的 V/I/时间替换 `POWER.CSV` 里的模型常量，三个固件同口径各测一遍。
> 结论：实测锚点只有基线 `90/140 mA`；省电版测不出来，深睡 `<0.01 A` 只是表上界；窗口 95 / 唤醒 145 / 1.4 s / P3 130–160 是模型假设；`6.98–10.94 mA` 是模型输出，不是实测。

## 1. 接线与测法

```text
USB 电源 ── USB 电压电流表 ── 5V/GND 直连板子 5V、GND
USB-TTL ── 只接 TX / RX / GND（不接 5V、不接 3V3）
```

- **不许用 USB-TTL 给板子供电**：TTL 的 5 V 与表后段并联会绕开电流表，且 CH340+LDO 自身几 mA 会淹没深睡电流。
- 表串在 5 V 输入端，量的是**表后整条路径**（AMS1117 + 摄像头 + SD + 芯片），不是芯片电流。
- 0.01 A 分辨率、秒级刷新；电流到 0 A 时表自动停表。
- 每轮开始前确认：相机、SD 卡、供电、室温不变；记下开始时的 `IMG_*` 张数。

## 2. 表的限制（决定省电版怎么测）

| 限制 | 后果 |
|---|---|
| 分辨率 0.01 A（10 mA） | 深睡电流（手册 6 mA）只读得到 `0.00` / `0.01` A，给不出数值 |
| 电流到 0 A 时表自动停表 | 深睡一小时，表直接停止计量，整段采不到 |

省电版 24 h 里约 99 % 时间是深睡，所以**“直读深睡”在这块表上不成立**。深睡只能用表上界 + 手册 6 mA；窗口/唤醒/拍照是模型假设。viewer（主基线，WiFi 常开）的 `90 mA` 是实测锚点，表能读出数值、也不会停表。

后果：省电版**无法产出 24 h 连续表 CSV**（深睡时表停表），24 h 只能按“模型段 + 深睡区间”推算；要连续曲线需 INA219 / 带记录的表。

因此 24 h 交付拆成两层，别混为一谈：

1. **设备侧连续日志**（`POWER.CSV`，5 min 采样、322 行）：证明采样连续、事件完整、拍照时间线；电流字段是固件模型值，不当作实测能量。
2. **表实测能量区间**（[`24h-meter-series.csv`](24h-meter-series.csv)）：用表累计 `mWh` 相邻读数差分，得到 4 段实测平均功率/电流；总量 `16384 mWh / 24 h`，由 [`build_meter_series.py`](build_meter_series.py) 生成。

两层合起来是“24 h 连续日志 + 表实测能量”，不是“24 h 连续电流曲线”；[`verify.py`](verify.py) 会把这两层和 README 的数字对账。

## 3. 阶段定义（P1–P6）

| 阶段 | 起止判据 | 用在哪 |
|---|---|---|
| P1 冷启动 | 上电 → 拍照开始 | 启动能量（相机 init + SD + WiFi + NTP） |
| P2 窗口空闲 | 首张写完 → 窗口关闭 | `kModelWifiMa` + `kModelIdleMa`（省电版主测段） |
| P3 拍照瞬间 | 拍照开始 → 写卡完成 | `kModelShotMa` / `kModelSaveMa`、峰值 |
| P4 深睡 | 入睡稳定后 ≥10 min | `kModelSleepMa`：表给上界，手册 6 mA |
| P5 定时唤醒 | 唤醒 → 拍完继续睡 | 稳态单周期（30 s 固件把这一段的脉冲频率放大） |
| P6 常开空闲 | 上一次写卡完成 → 下一次拍照开始 | viewer 的持续空闲电流 |

P1 在 P3 起点结束，两者首尾相接不重叠，可直接相加。**P2 窗口空闲只在省电版存在**，`current-comparison.csv` 与主 README 单列一行（省电版 `95 mA` 为模型假设；基线无窗口，记“不适用”）；P6 是 viewer 的持续空闲，`90 mA` 为实测。

## 4. 实测锚点与模型输入（汇总）

| 项 | 值 | 来源/性质 |
|---|---|---|
| 基线健康空闲（viewer） | `90 mA / 5.04 V` | 实测（`0.09 A` 直读 + 24 h 端点） |
| 基线 24 h 平均 | `140 mA`（`135.4` 取整） | 实测（表累计 `16384 mWh` / 24 h / 5.04 V） |
| 基线开网页上限 | `140 mA`（`0.14 A`） | 实测上限（范围 `0.11–0.14 A`） |
| 省电版深睡 | `≤ 0.01 A`；手册 `6 mA` | 表上界 + 数据手册 |
| 窗口 / 唤醒 / P3 / P5 | `95 / 145 mA`、`130–160 mA`、`1.4 s` | **模型假设，未实测** |
| 省电版 24 h | `6.98–10.94 mA` / `167.5–262.5 mAh` | **模型输出**（输入含假设） |

## 5. 24 h 预算（三段法）

```text
窗口段  e_win   = V × I_win  × 900 s              （每天 1 次，模型假设 95 mA）
唤醒段  e_wake  = V × I_wake × t_wake × 24        （每天 24 次，模型假设 145 mA × 1.4 s）
深睡段  e_sleep = V × I_sleep × (86400 − 900 − 24·t_wake)   （I_sleep ∈ [6 mA 手册, 10 mA 表上界]）
24 h 平均电流 = 总能量 / (V × 24 h)
```

`theory.py` 就是这条式子：

```bash
python3 measurement/theory.py          # 默认 6 mA
python3 theory.py --i-sleep 10         # 表上界
python3 theory.py --i-sleep 5          # 旧 5 mA 模型（仅复现 5.99 mA / 15.0×）
```

2026-11-10 这轮的输入是**模型假设**：`i_win=95 mA`、`i_wake=145 mA`、`t_wake=1.4 s`；不是实测。实测锚点只有基线 `90/140 mA`；省电版测不出来，深睡 `<0.01 A` 只是表上界。

| 口径 | 24 h 电量 | 平均电流 | 续航（1600 mAh 可用） |
|---|---|---|---|
| 深睡按手册 6 mA | 167.5 mAh | 6.98 mA | 9.5 天 |
| 深睡按表上界 10 mA | 262.5 mAh | 10.94 mA | 6.1 天 |

同样的口径算窗口段：模型假设 `95 mA × 15 min = 23.75 mAh`，而旧模型按 `165 mA` 记的是 `41.25 mAh`——**这是模型参数的修正，不是实测修正**。

## 6. 官方参考值（补充数据，2026-11-13）

[ESP-IDF 睡眠模式文档](https://docs.espressif.com/projects/esp-idf/zh_CN/latest/esp32/api-reference/system/sleep_modes.html) 里确实有 `< 1 µA` 和 `10–30 µA`，但这两个数描述的是 **SPI Flash**，不是 ESP32 SoC，也不是开发板：

- DPD：`多数 SPI Flash 在 DPD 下电流可降至极低水平（常低于 1 µA）`
- 保持供电：`SPI Flash 的待机功耗通常低于 30 µA`，`约 10-30 µA`

按对象拆开（同一份文档里的数字不能跨层套用）：

| 层级 | 对象 | 典型值 | 来源 | 能否代入 24 h 模型 |
|---|---|---|---|---|
| SoC | ESP32 Deep-sleep | 10 µA（随保留的 RTC 块可到 150 µA 量级） | [ESP32 数据手册](https://www.espressif.com/sites/default/files/documentation/esp32_datasheet_cn.pdf) | 否，只是芯片 |
| SoC | ESP32 Light-sleep | 0.8 mA | [ESP32 数据手册](https://www.espressif.com/sites/default/files/documentation/esp32_datasheet_cn.pdf) | 否，只是芯片 |
| SPI Flash | Deep Power-Down | < 1 µA | 上方 IDF 文档 | 否 |
| SPI Flash | 待机（不掉电） | 10–30 µA | 上方 IDF 文档 | 否 |
| 开发板 | ESP32-CAM 原板 Deep-sleep | **6 mA @ 5 V** | [ESP32-CAM 数据手册](https://item.szlcsc.com/datasheet/ESP32-CAM/265266.html) | 是（官方点估计） |
| 开发板 | 表分辨率上界 | 10 mA（表） | USB 表 | 是（上界） |

手册（AI-Thinker ESP32-CAM 规格书 v1.0，2021-02-17）原文：`Power consumption: ... Deep-Sleep: 6mA @ 5V`（[同文 PDF](https://universal-solder.ca/downloads/ESP32-CAM.pdf)）。按 6 mA 代入 `theory.py`：24 h 平均约 `6.98 mA`、`12.9×`、续航约 `9.5 天`（1600 mAh）；旧模型 5 mA 只算 LDO 静态，手册 6 mA 是整板，差 1 mA 量级。主口径为 `[6, 10] mA`。

**口径结论**：`< 1 µA` 不能写成 ESP32-CAM 的板级深睡。原板 5 V 输入路径上，AMS1117 静态电流（典型 5 mA）单独就把深睡抬到 mA 级；实测表读 `0.00 A` 只给得出 `≤ 10 mA` 的上界，与手册 6 mA 相容。把 `< 1 µA` 代进 `theory.py`，24 h 平均电流会算成约 `1.05 mA`、倍数约 `86×`，与硬件和实测都冲突。

**为什么外侧测不到**：表串在 5 V 输入端，测的是表后所有并联支路的总电流（“电只走最短路径”不是原因）；深睡读不出数，是 0.01 A 分辨率、低于阈值自动停表、以及表后仍有 AMS1117 等 mA 级负载共同造成的。手册既然给了 `6 mA @ 5V`，就不必再靠串测。

**为什么万用表也不行**：万用表测电流必须把表串在供电路径里，而这块板无法从源头串入测量——表接不进整板电流路径，所以整板电流测不到。深睡只能取手册 6 mA + 表上界；要单板真值，只能改造源头供电路径、加 INA219 一类低阻分流（0.1 Ω 量级）记录。

## 7. 数据齐套检查（2026-11-16 更新）

表能直接测的只有基线 `90/140 mA`；深睡 `<0.01 A` 只是表上界（省电版测不出来）；窗口/唤醒/P3 未实测。深睡另有官方手册 6 mA；要真值需 INA219 一类低阻分流记录。

| 项 | 状态 | 说明 |
|---|---|---|
| 基线健康空闲 / 24 h 平均 | ✅ 实测 | `90 mA / 5.04 V`；`16384 mWh / 24 h / 5.04 V = 135.4 mA`（≈140） |
| 基线开网页上限 | ✅ 实测上限 | `0.14 A`；范围 `0.11–0.14 A` |
| 深睡 | 🟡 表上界 + 手册 | `≤ 0.01 A`；官方手册 `6 mA @5V`；无单板实测 |
| 窗口 / 唤醒 / P3 / P5 | 🟡 模型假设 | `95 / 145 mA`、`130–160 mA`、`1.4 s`；未实测，不作 ① 的实测证据 |
| 省电版 24 h | 🟡 模型 | `6.98–10.94 mA`；输入含假设 |
| 表限制 | ✅ 记录 | 0.01 A 分辨率；深睡停表；5 V 输入侧整条路径 |

**结论口径**：实测只能写“基线 `90/140 mA`”；深睡 `<0.01 A` 只是表上界，不是实测；窗口/唤醒/P3 是模型假设，`6.98–10.94 mA` 是模型输出，不写成实测。要复核到 ±10 %，需 INA219 一类低阻分流记录。

## 8. 已知误差

- 0.01 A 量化对基线 `90/140 mA` 是 ±5–7 %；窗口/拍照段没有实测，不给量化误差。
- 基线 P3 有视频证据（2026-11-16，10 次/24 s）：1 s 表读 `0.10–0.13 A`，峰值 `0.18 A`（另一段 15 s 视频，未入库）；这是 1 s 窗口，不是 60–90 ms 平均；P3 不写定量实测值，`0.13–0.16 A` 仅为模型/探针推断。
- 表计时慢 7 min/24 h（24 h 端点实测）：用表时间当分母会高估约 0.49 %。
- 表累计 `mWh` 显示会停顿/跳变；`W` 是时段平均、`A` 是瞬时，不能拿 `W` 反推瞬时电流。
- 深睡项：表只能给上界 `0.01 A`（模型输出 `10.94 mA / 8.2×`）；官方手册另给 `6 mA @ 5V`（模型输出 `6.98 mA / 12.9×`），主口径用 6 mA。**不能把表上界 10 mA 当实测值。**
- 深睡↔拍照的电流变化在 0.01 A 表上**不可分辨**（拍照本身只有 60–90 ms），现场读数与视频见 [powersave-meter-2026-11-10](../process_logs/powersave-meter-2026-11-10/README.md)。
- 本方案的局限（深睡只有表上界、峰值抽不到、能量不进位、测的是整条路径、抽样口径有限）逐条写在 [powersave-meter-2026-11-10](../process_logs/powersave-meter-2026-11-10/README.md#5-局限这个方案证明不了什么) 的「局限」一节；深睡另有官方手册 `6 mA @ 5V`，单板真值需 INA219 一类低阻分流记录（万用表无法从源头串入，原因见第 6 节）。
- 30 s 固件把唤醒次数从 24 次/天放大到 2880 次/天；`t_wake` 是模型假设 `1.4 s`，不是实测；若用串口 `[CAP]`/`[SLEEP]` 时间戳，要标明是观察值。
- `t_wake` 取模型假设 `1.4 s`；未实测。`2.1 s` 只作敏感性上限，不当作实测。
- USB 表测的是表后整条路径（含板载 AMS1117 与 SD），不等于芯片电流；表本身有压降，深睡电压偏低会让功率偏高估。

## 9. 30 s 短周期固件（放大脉冲）

两种档，按要测的段选：

| 档 | 编译宏 | 行为 | 用途 |
|---|---|---|---|
| A 带窗口 | `-DCAPTURE_INTERVAL_MS=30000` | 冷启动先开 15 分钟 WiFi 窗口，窗口结束后每 30 s 深睡→拍照 | 一次跑里同时复核窗口段和循环段 |
| B 不开网页 | `-DCAPTURE_INTERVAL_MS=30000 -DWEB_WINDOW_MS=0` | 上电直接进深睡 30 s → 拍照循环，不连 WiFi、不开网页 | 只测“深睡 + 唤醒拍照”，表上不会被 0.09 A 的窗口段盖住 |

档 B 的代价：没有 NTP，照片和串口里的时间显示“无时间戳”，对齐用宿主机时间戳（`serial_capture.py`）。串口每个周期还是会打 `[CAP]` / `[SLEEP] 深睡 30s`，拿来和表读数对齐。

正式固件仍是默认 1 h（不带宏）；两种测量档都是一天 2880 次抓拍，别拿来做正式采集。

```bash
cd 02-20Days-Challenge
export ARDUINO_DIRECTORIES_DATA=$PWD/.arduino/data ARDUINO_DIRECTORIES_USER=$PWD/.arduino/user
./arduino-cli compile --fqbn esp32:esp32:esp32cam --build-path .arduino/build-30s-noweb \
  --build-property "compiler.cpp.extra_flags=-DCAPTURE_INTERVAL_MS=30000 -DWEB_WINDOW_MS=0" \
  firmware/esp32cam-powersave/powersave
./arduino-cli upload -p /dev/ttyUSB0 --fqbn esp32:esp32:esp32cam \
  --build-path .arduino/build-30s-noweb firmware/esp32cam-powersave/powersave
```

两个坑：

- **别用 `--build-property build.extra_flags=...` 传宏**。那会覆盖核心的 `-DBOARD_HAS_PSRAM` / `-mfix-esp32-psram-cache-*` / 板级宏，编出来的镜像能烧、启动后串口一句不打（2026-11-10 踩过）。改用 `compiler.cpp.extra_flags` 追加。
- **烧录和看串口在宿主机上做**（本环境 `distrobox-host-exec`）。容器里能烧成功、但读不到应用输出；而且转换板的 DTR/RTS 接在 GPIO0/EN 上，`open()` 默认把 GPIO0 拉低，芯片会停在下载模式，必须打开后释放控制线再复位——`serial_capture.py --reset` 已经处理。

## 10. 打点工具与复现

```bash
cd 02-20Days-Challenge

# 0. 24 h 表实测区间：从表盘锚点重算（与证据 CSV 逐字段对比）
python3 measurement/build_meter_series.py
python3 measurement/build_meter_series.py --check

# 1. 抓串口（宿主机执行），每行带宿主机时间戳；--reset 让芯片从 flash 启动
distrobox-host-exec python3 $PWD/measurement/serial_capture.py \
  --seconds 1020 --reset --out $PWD/.arduino/serial_powersave30s.log

# 2. 切分阶段 → 写进记录表（v/i 按表上读数填）
python3 measurement/phases.py .arduino/serial_powersave30s.log \
  --append measurement/measure-record.csv --summary

# 3. 全量自检 + 回归测试
python3 measurement/verify.py
python3 -m unittest discover -s measurement -p 'test_*.py' -v
```

- `phases.py` 认两类固件的启动标记（省电版 / viewer 主基线），输出毫秒级 start/end，可直接和 USB 表的录制时间轴对齐。
- 缺 `[CAP]` 行、窗口被断电、会话未收尾都会写进 `note`，不会静默跳过。
- 表没有录制功能时，就在阶段 start/end 那几个时刻读表并记录电流电压。
- 30 s 固件一轮会切出几十段（每分钟 2 个会话），记录表只填 **1 个代表周期**，其余用 `--summary` 看统计。

## 11. 结论强度与补齐路径

- 实测只有基线 `90/140 mA`；深睡 `<0.01 A` 是表上界（省电版测不出来）；窗口/唤醒/P3 是模型假设，`6.98–10.94 mA` 是模型输出，不是实测结论。24 h 总能量另有表累计差分实测（[`24h-meter-series.csv`](24h-meter-series.csv)：`16384 mWh / 24 h`）。
- 省电版 24 h 连续表曲线：现有 0.01 A 表会停表，**做不到**；需 INA219 一类低阻分流记录模块或带记录的表。
- 单板深睡值：手册 6 mA 在模型上可支撑 10×，但不是实测；万用表无法从源头串入测量，要复核需 INA219 一类低阻分流记录。
- 无 WiFi 拍照电流：用 `capture_probe`（不连 WiFi、连续拍照）单独测；现有 `0.13–0.16 A` 是 WiFi 关联连拍的模型/探针推断，不是实测。
