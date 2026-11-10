# ESP32-CAM 实机电流实测（USB 电压电流表）

目标：用实测的 V/I/时间替换 `POWER.CSV` 里的模型常量（`kModelIdleMa` / `kModelShotMa` / `kModelSaveMa` / `kModelWifiMa` / `kModelSleepMa`），三个固件同口径各测一遍。

## 接线（关键，接错就白测）

```
USB 电源 ── USB 电压电流表 ── 5V/GND 直连板子 5V、GND
USB-TTL ── 只接 TX / RX / GND（不接 5V、不接 3V3）
```

- **不许用 USB-TTL 给板子供电**：TTL 的 5V 与表后段并联会绕开电流表，且 CH340+LDO 自身几 mA 会淹没深睡电流。
- 每轮开始前确认：相机、SD 卡、供电、室温不变；记下开始时的 `IMG_*` 张数。

## 表的限制（决定省电版怎么测）

| 限制 | 后果 |
|---|---|
| 分辨率 0.01 A（10 mA） | 深睡电流（模型 5 mA）只读得到 `0.00` / `0.01` A，给不出数值 |
| 电流到 0 A 时表自动停表 | 深睡一小时，表直接停止计量，整段采不到 |

省电版 24 h 里约 99 % 时间是深睡，所以**「直读深睡」在这块表上不成立**。省电版改为只实测表能分辨的段，深睡用占空比 + 表上界推算；viewer（主基线）与 baseline（下限基线）平均电流在 45–165 mA 量级，表至少能读出数值、也不会停表，仍按原 P1 / P3 / P6 全时段打点。

## 省电版：三段法

| 段 | 24 h 里占多久 | 表能不能测 | 怎么处理 |
|---|---|---|---|
| 窗口段：冷启动后 WiFi + 网页 | 15 min | 能（实测 0.09–0.10 A） | 直接读 V / I / P，记成 `P2 窗口空闲`（1 h 正式固件或测量档 A） |
| 唤醒拍照段 | 24 次 × 1.4–2.1 s（复位→入睡，实测） | 能（0.13–0.16 A 级），但脉冲太短 | 烧 30 s 短周期固件（档 B）放大脉冲频率，记成 `P3 拍照瞬间` |
| 深睡段 | 其余约 23.7 h | 不能（<0.01 A，且会停表） | 只记表上界（读数 0.00 / 0.01 A），推算时按区间 [5 mA 模型, 10 mA 上界] |

## 省电版专用的 30 s 短周期固件

两种档，按要测的段选：

| 档 | 编译宏 | 行为 | 用途 |
|---|---|---|---|
| A 带窗口 | `-DCAPTURE_INTERVAL_MS=30000` | 冷启动先开 15 分钟 WiFi 窗口，窗口结束后每 30 s 深睡→拍照 | 一次跑里同时复核窗口段和循环段 |
| B 不开网页 | `-DCAPTURE_INTERVAL_MS=30000 -DWEB_WINDOW_MS=0` | 上电直接进深睡 30 s → 拍照循环，不连 WiFi、不开网页 | 只测「深睡 + 唤醒拍照」，表上不会被 0.09 A 的窗口段盖住 |

档 B 的代价：没有 NTP，照片和串口里的时间显示「无时间戳」，对齐用宿主机时间戳（`serial_capture.py`）。
串口每个周期还是会打 `[CAP]` / `[SLEEP] 深睡 30s`，拿来和表读数对齐。

正式固件仍是默认 1 h（不带宏）；两种测量档都是一天 2880 次抓拍，别拿来做正式采集。

```bash
cd 02-20Days-Challenge
export ARDUINO_DIRECTORIES_DATA=$PWD/.arduino/data ARDUINO_DIRECTORIES_USER=$PWD/.arduino/user
./arduino-cli compile --fqbn esp32:esp32:esp32cam --build-path .arduino/build-30s-noweb \
  --build-property "compiler.cpp.extra_flags=-DCAPTURE_INTERVAL_MS=30000 -DWEB_WINDOW_MS=0" \
  esp32cam-powersave/powersave
./arduino-cli upload -p /dev/ttyUSB0 --fqbn esp32:esp32:esp32cam \
  --build-path .arduino/build-30s-noweb esp32cam-powersave/powersave
```

两个坑：

- **别用 `--build-property build.extra_flags=...` 传宏**。那会覆盖核心的 `-DBOARD_HAS_PSRAM` / `-mfix-esp32-psram-cache-*` / 板级宏，编出来的镜像能烧、启动后串口一句不打（2026-11-10 踩过）。改用 `compiler.cpp.extra_flags` 追加。
- **烧录和看串口在宿主机上做**（本环境 `distrobox-host-exec`）。容器里能烧成功、但读不到应用输出；而且转换板的 DTR/RTS 接在 GPIO0/EN 上，`open()` 默认把 GPIO0 拉低，芯片会停在下载模式，必须打开后释放控制线再复位——`serial_capture.py --reset` 已经处理。

## 每轮要打点的阶段

| 阶段 | 起止判据 | 用在哪 |
|---|---|---|
| P1 冷启动 | 上电 → 拍照开始 | 启动能量（相机 init + SD + WiFi + NTP） |
| P2 窗口空闲 | 首张写完 → 窗口关闭 | `kModelWifiMa` + `kModelIdleMa`（**省电版主测段**） |
| P3 拍照瞬间 | 拍照开始 → 写卡完成 | `kModelShotMa` / `kModelSaveMa`、峰值 |
| P4 深睡 | 入睡稳定后 ≥10 min | `kModelSleepMa`：省电版只能给上界 |
| P5 定时唤醒 | 唤醒 → 拍完继续睡 | 稳态单周期（30 s 固件把这一段的脉冲频率放大） |
| P6 常开空闲 | 上一次写卡完成 → 下一次拍照开始 | viewer / baseline 的持续空闲电流 |

P1 在 P3 起点结束，两者首尾相接不重叠，可直接相加。

## 打点工具

```bash
cd 02-20Days-Challenge

# 1. 抓串口（宿主机执行），每行带宿主机时间戳；--reset 让芯片从 flash 启动
distrobox-host-exec python3 $PWD/power-measure-2026-11-10/serial_capture.py \
  --seconds 1020 --reset --out $PWD/.arduino/serial_powersave30s.log

# 2. 切分阶段 → 写进记录表（v/i 按表上读数填）
python3 power-measure-2026-11-10/phases.py .arduino/serial_powersave30s.log \
  --append power-measure-2026-11-10/measure-record.csv --summary
```

- `phases.py` 认三种固件的启动标记，输出毫秒级 start/end，可直接和 USB 表的录制时间轴对齐。
- 缺 `[CAP]` 行、窗口被断电、会话未收尾都会写进 `note`，不会静默跳过。
- 表没有录制功能时，就在阶段 start/end 那几个时刻读表并记录电流电压。
- 30 s 固件一轮会切出几十段（每分钟 2 个会话），记录表只填 **1 个代表周期**，其余用 `--summary` 看统计。

## 推算理论功耗

深睡测不出，所以只把实测的窗口段、唤醒段代进公式，深睡给区间：

```
窗口段  e_win   = V × I_win  × 900 s              （每天 1 次，实测）
唤醒段  e_wake  = V × I_wake × t_wake × 24        （每天 24 次，实测电流 + [CAP] 时长）
深睡段  e_sleep = V × I_sleep × (86400 − 900 − 24·t_wake)   （I_sleep ∈ [5 mA 模型, 10 mA 表上界]）
24 h 平均电流 = 总能量 / (V × 24 h)
```

`theory.py` 就是这条式子：

```bash
python3 power-measure-2026-11-10/theory.py
```

2026-11-10 这轮的输入与结果（`i_win=95 mA` 实测、`i_wake=145 mA` 实测且偏保守、`t_wake=1.4 s` 由 30 s 固件实测的复位→入睡时长 18:02:34.757→18:02:36.123 推得）：

| 口径 | 24 h 电量 | 平均电流 | 续航（1600 mAh 可用） |
|---|---|---|---|
| 深睡按模型 5 mA | 143.8 mAh | 5.99 mA | 11.1 天 |
| 深睡按表上界 10 mA | 262.5 mAh | 10.94 mA | 6.1 天 |

同样的口径算窗口段：实测 95 mA × 15 min = 23.75 mAh，而模型按 165 mA 记的是 41.25 mAh——**模型把窗口段高估了约 1.7 倍**，这是这次实测最直接的一个修正。

## 基线：正常测量，不改方案

主基线 `esp32cam-viewer`（WiFi 常开）与下限基线 `esp32cam-baseline`（WiFi 全关）电流都在表的量程中段，停不了表，按原来的 P1 / P3 / P6 全时段打点即可，本节的三段法只适用于省电版。

## 已知误差（要写进结论，不许抹掉）

- 0.01 A 量化对 0.09–0.10 A 的窗口段是 ±5 %，对 0.13–0.16 A 的拍照段是 ±4 %。
- 深睡项只能给上界：`0.01 A` 这条上界让 24 h 平均电流在 5.99–10.94 mA 之间浮动，**结论必须写成区间**，不能报成单值。
- 30 s 固件把唤醒次数从 24 次/天放大到 2880 次/天，测的是「同一次唤醒的电流和时长」，不是 24 h 的真实占空比；`t_wake` 必须用 `[CAP]` / `[SLEEP]` 的时间戳取，不能拿周期长度代替。
- 唤醒时长会随 SD 上的照片数变长（每次开机都扫目录取下一个编号）：约 40 张时复位→入睡 1.4 s，约 110 张时 2.1 s。按 24 次/天算这一项只占 1–2 mAh，但报 `t_wake` 时要说明是在多少张照片下测的。
- USB 表测的是表后整条路径（含板载 AMS1117 与 SD），不等于芯片电流；表本身有压降，深睡电压偏低会让功率偏高估。

## 记录

`measure-record.csv` 每阶段一行；实测读数回填后再用 `theory.py` 重算 24 h 与续航，并替换 `POWER.CSV` 的模型口径。
