# ESP32-CAM 省电版固件（15 min WiFi 窗口 + 深睡占空比）

> 状态：**已在 AI-Thinker ESP32-CAM 上烧录运行**（esp32 核心 3.3.12）。
> 作用：把“WiFi 常开 + 每小时一张”的主基线改成“开机 15 min 窗口 + 窗口外深睡、每小时只拍照不联网”。

## 1. 它解决什么

基线 `esp32cam-viewer` 的 WiFi 常开空闲是 `0.09 A`（实测），24 h 平均 `90 mA`。本固件把 WiFi 射频压到每天 15 min，其余时间 deep sleep；拍照仍每小时一次，照片存 SD。24 h 平均电流降到 `6.98–10.94 mA`（官方 6 mA / 表上界 10 mA），相对基线 `8.2–12.9×`（见 [主 README](../../README.md) 第 4 节）。

## 2. 行为与状态机

> 完整状态图、状态×动作×源码行号表、RTC 变量与失败模式见 [`docs/state-machine.md`](../../docs/state-machine.md)。

```text
上电/复位 ─► 冷启动：连 WiFi+NTP ─► 拍照 ─► Web 窗口 15 min ─► 停网页/断射频 ─► 关摄像头、卸载 SD ─► deep sleep 1 h
                                                        └─ 窗口内可查图、下载 POWER.CSV
deep sleep 定时唤醒 ─► 释放 PWDN 保持、恢复时间/能耗 ─► 拍照（不连 WiFi）─► deep sleep
```

**冷启动（上电/复位）**

1. 初始化摄像头 / SD → 连 WiFi + NTP（东八区）→ 立即拍一张存 SD
2. 网页服务与 WiFi 射频**只开 15 分钟**（页面顶部有“WiFi 剩余”倒计时）
3. 时间到：停网页服务 → 断 WiFi → 关射频
4. 关摄像头（`esp_camera_deinit()` + PWDN 拉高并保持）→ 卸载 SD → **进 deep sleep**

**定时唤醒（deep sleep 计时器，每小时一次）**

1. 释放 PWDN 保持、恢复时间与累计能耗
2. 初始化摄像头 / SD → 拍一张存 SD
3. 关摄像头、卸载 SD、继续深睡；**不连 WiFi**

**重新上电（断电再上电 / 按 EN 复位）**

只自动复位一次，**不清空 SD 数据**；复位后按冷启动流程继续采集，编号从 SD 上已有的下一张继续。

窗口结束后网页不可用；要再看网页必须重启（重启会重新开 15 分钟窗口）。网页的“重置测试”会删除 `IMG_*.jpg` 与 `POWER.CSV` 后 `ESP.restart()`，复位后从 `IMG_00001` 重新拍照。

WiFi 使用固定 IP `192.168.16.10`（网关 `192.168.16.1`，DNS `192.168.16.1` / `223.5.5.5`），网页地址固定为 `http://192.168.16.10/`。

## 3. 省电措施

| 措施 | 实现 | 对应方案 |
|---|---|---|
| 深睡占空比 | 除拍照与 15 分钟窗口外，CPU/射频全部休眠；`RTC_DATA_ATTR` 保存状态 | 3.1 / 3.2 ③ |
| WiFi 用完即关 | 窗口结束 `server.stop()` → `WiFi.disconnect(true)` → `WiFi.mode(WIFI_OFF)` | 3.2 ⑥ |
| 定时唤醒不连 WiFi | `esp_sleep_get_wakeup_cause()` 区分冷启动与定时唤醒 | 3.2 ② |
| 摄像头断电保持 | `esp_camera_deinit()` 后 PWDN 拉高，`gpio_hold_en` + `gpio_deep_sleep_hold_en` 保持到唤醒 | 3.2 ④ |
| 睡眠前卸载 SD | `SD_MMC.end()`，避免卡在睡眠中继续耗电 | 2.4 |
| 睡眠能耗记账 | `kModelSleepMa` + RTC 内存累计，`POWER.CSV` 的 `e_mwh` 不会被低估 | 2.3 |
| 关闭闪光灯 | GPIO4 输出低，开机即关 | — |
| WiFi modem sleep | Arduino ESP32 核心默认 `WIFI_PS_MIN_MODEM`，无需再调 | — |
| 数字 IO | 仅对 PWDN 做 `gpio_hold_en` + `gpio_deep_sleep_hold_en`；**未调用** `esp_sleep_isolate_digital_gpio()` | — |

## 4. 没有做（及原因）

| 措施 | 原因 |
|---|---|
| CPU 降频（240 → 80 MHz） | 已定量评估、未启用：活跃段仅 33.6–50.4 s/天，上限收益 `≤0.42 mAh/天`（<0.25 %），却给 OV2640 XCLK / SDMMC 时序引入风险；取舍表见 [`state-machine.md` 第 6 节](../../docs/state-machine.md#6-时钟降频专项点名要求但未落地) |
| BSSID + channel 直连 | 只在冷启动连一次，能省 1–2 s × 120 mA ≈ 0.06 mAh，占 15 分钟窗口的 0.1% |
| 降低 TX 功率 | 窗口内基本是空闲收包，TX 占比极低；降功率有掉线风险 |
| `sdkconfig` 内核/系统配置 | Arduino 核心用预编译库，改不了；要改只能换 ESP-IDF |
| 移除板载电源 LED | 硬件操作，收益 1–3 mA，最容易做，建议无论软件怎么改都做 |
| 换 LDO（AMS1117 → HT7333 等） | 硬件操作，5 mA 静态电流是当前深睡的主要构成（手册整板 6 mA） |
| MOSFET 切摄像头 / SD 供电 | 硬件操作，需割线；本固件已用 PWDN 把摄像头置待机 |

## 5. 关键常量与 POWER.CSV

```cpp
#ifndef CAPTURE_INTERVAL_MS
#define CAPTURE_INTERVAL_MS (60UL * 60UL * 1000UL)  // 拍照周期（含深睡）
#endif
static const uint32_t kWebWindowMs = 15UL * 60UL * 1000UL;  // WiFi 窗口
```

`/POWER.CSV` 表头不变，事件行有四种：

| event | 含义 |
|---|---|
| `CAPTURE` | 拍照，`i_ma` 是该采集周期（含深睡）的平均电流模型值 |
| `SAMPLE` | 窗口期间每 5 分钟一次，WiFi 开着时按 **95 mA（2026-11-10 实测）** 记 |
| `WEB_ON` | 窗口开始（`window_s=0` 表示瞬时事件） |
| `WEB_CLOSE` | 窗口结束，`window_s=900` 是这 15 分钟的平均电流（同样按实测 95 mA） |

两点必须知道：

- **深睡期间不写日志**（SD 已卸载），所以 `SAMPLE` 只在窗口内出现；`e_mwh` 把深睡能耗按 `kModelSleepMa`（5 mA，仍是模型值；官方手册整板 6 mA，可按 6 mA 回填）在入睡时一次性补上。
- 常量口径：窗口段 `kModelWindowMa = 95 mA` 是 2026-11-10 实测；`kModelIdleMa` / `kModelShotMa` / `kModelSaveMa` / `kModelSleepMa` 仍是模型值，等低阻分流补测后回填（万用表无法从源头串入）。
- **冷启动那一小时的 `CAPTURE` 行偏低**：它按“1 小时 − 15 分钟窗口”的模型算，没算窗口本身的电流。看窗口能耗请看 `WEB_CLOSE` 行。

## 6. 编译与烧录

```bash
cd 02-20Days-Challenge
export ARDUINO_DIRECTORIES_DATA=$PWD/.arduino/data ARDUINO_DIRECTORIES_USER=$PWD/.arduino/user

# 正式固件（1 h 周期）
./arduino-cli compile --fqbn esp32:esp32:esp32cam --build-path .arduino/build-powersave firmware/esp32cam-powersave/powersave
./arduino-cli upload -p /dev/ttyUSB0 --fqbn esp32:esp32:esp32cam --build-path .arduino/build-powersave firmware/esp32cam-powersave/powersave
```

功耗测量时烧 30 s 短周期版本（为什么需要它见 [measurement/README.md](../../measurement/README.md)）：

```bash
# 档 A：先开 15 分钟窗口，窗口结束后每 30 s 深睡→拍照
./arduino-cli compile --fqbn esp32:esp32:esp32cam --build-path .arduino/build-30s \
  --build-property compiler.cpp.extra_flags=-DCAPTURE_INTERVAL_MS=30000 \
  firmware/esp32cam-powersave/powersave

# 档 B：上电直接进 30 s 循环，不连 WiFi（宏值中间有空格，要加引号）
./arduino-cli compile --fqbn esp32:esp32:esp32cam --build-path .arduino/build-30s-noweb \
  --build-property "compiler.cpp.extra_flags=-DCAPTURE_INTERVAL_MS=30000 -DWEB_WINDOW_MS=0" \
  firmware/esp32cam-powersave/powersave
```

⚠ 不要用 `--build-property build.extra_flags=...` 传宏：那会覆盖核心的 PSRAM / 板级宏，镜像能烧但启动后串口无任何输出。要用 `compiler.cpp.extra_flags` 追加。

## 7. 串口预期输出

```text
=== ESP32-CAM 省电版（冷启动：WiFi + 网页开 15 分钟）===
[OK] 摄像头初始化完成
[OK] SD 卡初始化完成
[WIFI] 已连接，IP 192.168.16.10
[TIME] 2026-11-06 21:30:00
[CAP] /IMG_00001.jpg size=...B 2026-11-06 21:30:00 ...
[WEB] http://192.168.16.10/  窗口 15 分钟
...
[WEB] 窗口结束，已关闭网页服务与 WiFi
[SLEEP] 深睡 2699s，预计 2026-11-06 22:30:00 醒来
...
=== ESP32-CAM 省电版（定时唤醒：不连 WiFi）===
[OK] 摄像头初始化完成
[OK] SD 卡初始化完成
[CAP] /IMG_00002.jpg size=...B 2026-11-06 22:30:00 ...
[SLEEP] 深睡 3598s，预计 2026-11-06 23:30:00 醒来
```

WiFi 连接失败时不开网页，拍完直接睡到下个周期。

## 8. 证据映射

| 证据 | 内容 |
|---|---|
| [powersave-15h-2026-11-10](../../evidence/powersave-15h-2026-11-10/README.md) | 15.20 h 运行片段，50 行 `POWER.CSV`（模型值），21 张照片 |
| [powersave-meter-2026-11-10](../../evidence/powersave-meter-2026-11-10/README.md) | 深睡↔拍照 `0.00 A` 录屏、窗口空闲 `0.09–0.10 A`、开网页 `0.12–0.19 A` |
| [基线 P3 视频对照](../../evidence/baseline-viewer-meter-2026-11-16/README.md) | 基线 P3 连拍 1 s 表读，用于对照 |

## 9. 局限

- 深睡电流没有单板实测；表只能给 `≤ 0.01 A`，官方手册整板 `6 mA`。
- 拍照峰值（60–90 ms）测不到；现有一条 `0.13–0.16 A` 是连拍放大后的平均值。
- `POWER.CSV` 的电流/电压是模型值（`v5_mv=-1`），不是表实测曲线。
- 15 分钟窗口内是否有人刷页面，会让窗口段电流在 `0.09–0.22 A` 之间差 2.4 倍；24 h 平均跟着差 15–20 %。
- CPU 降频已定量评估、未启用（理由与收益表见 [`state-machine.md` 第 6 节](../../docs/state-machine.md#6-时钟降频专项点名要求但未落地)）；BSSID 直连、降 TX 功率、sdkconfig、换 LDO、切外设供电均未做，原因见第 4 节。
