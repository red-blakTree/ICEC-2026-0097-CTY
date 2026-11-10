# ESP32-CAM 实机电流实测（USB 电压电流表）

目标：用实测的 V/I/时间替换 `POWER.CSV` 里的模型常量（`kModelIdleMa` / `kModelShotMa` / `kModelSaveMa` / `kModelWifiMa` / `kModelSleepMa`），三个固件同口径各测一遍。

## 接线（关键，接错就白测）

```
USB 电源 ── USB 电压电流表 ── 5V/GND 直连板子 5V、GND
USB-TTL ── 只接 TX / RX / GND（不接 5V、不接 3V3）
```

- **不许用 USB-TTL 给板子供电**：TTL 的 5V 与表后段并联会绕开电流表，且 CH340+LDO 自身几 mA 会淹没深睡电流。
- 表要看得到 1 mA 变化才测得了深睡（AMS1117 静态电流约 5 mA 量级）；有录制功能的把采样间隔设 ≤1 s，直接导出 CSV。
- 每轮开始前确认：相机、SD 卡、供电、室温不变；记下开始时的 `IMG_*` 张数。

## 三轮（每轮 ≥ 1 个完整周期）

| 轮次 | 固件 | 测什么 |
|---|---|---|
| 1 | `esp32cam-powersave` | 深睡、15 min 窗口、定时唤醒拍照 |
| 2 | `esp32cam-viewer` | WiFi 常开、每小时拍照（对 24 h 主基线） |
| 3 | `esp32cam-baseline` | WiFi 全关，下限参考 |

烧录：`arduino-cli upload -p /dev/ttyUSB0 --fqbn esp32:esp32:esp32cam <固件目录>`

## 每轮要打点的 5 个阶段

| 阶段 | 起止判据 | 用途 |
|---|---|---|
| P1 冷启动 | 上电 → 拍照开始 | 启动能量（相机 init + SD + WiFi + NTP） |
| P2 窗口空闲 | 首张写完 → 窗口关闭 | `kModelWifiMa` + `kModelIdleMa` |
| P3 拍照瞬间 | 拍照开始 → 写卡完成 | `kModelShotMa` / `kModelSaveMa`、峰值 |
| P4 深睡 | 入睡稳定后 ≥10 min | `kModelSleepMa`（最关键的未知量） |
| P5 定时唤醒 | 唤醒 → 拍完继续睡 | 稳态单周期 |
| P6 常开空闲 | 上一次写卡完成 → 下一次拍照开始 | viewer / baseline 的持续空闲电流 |

P1 在 P3 起点结束，两者首尾相接不重叠，可直接相加。

## 打点工具

```bash
# 1. 抓串口（TTL 只接 TX/RX/GND），每行带宿主机时间戳
python3 serial_capture.py --seconds 1200 --out coldboot.log

# 2. 切分阶段 → 写进记录表（v/i/e 留空，按表上读数填）
python3 phases.py coldboot.log --append measure-record.csv --summary
```

- `phases.py` 认三种固件的启动标记，输出毫秒级 start/end，可直接和 USB 表的录制时间轴对齐。
- 缺 `[CAP]` 行、窗口被断电、会话未收尾都会写进 `note`，不会静默跳过。
- 表没有录制功能时，就在阶段 start/end 那几个时刻读表并记录电流电压。

## 换算

```
阶段能量  e_mwh = Σ(V_i × I_i) × Δt / 3600        # V 用 V，I 用 mA，Δt 用 s
单周期    = P3 + P4 + P5（省电版）；= P3 + 5min 空闲（基线）
24 h 能耗 = 1×P1 + 23×P5 + 24×P4（省电版，纯深睡为主）
平均电流  i_avg = 24 h 能量 / (5 V × 24 h) × 1000
```

## 已知误差（要写进结论，不许抹掉）

- 1 mA 分辨率测 5 mA 深睡 → ±20%；表本身有压降，深睡电压偏低会让功率偏高估。
- USB 表测的是表后整条路径（含板载 AMS1117 与 SD），不等于芯片电流。
- 深睡电流若低于表的分辨率，只能给上限，不能报成实测值。

## 记录

`measure-record.csv` 每阶段一行；三轮测完再用它回填固件常量、重算 24 h 与续航，并替换 `POWER.CSV` 的模型口径。
