# ESP32-CAM 省电版（开机 WiFi 窗口 15 分钟 + 深睡占空比）

采集与网页沿用 [esp32cam-viewer](../esp32cam-viewer/README.md)，在此基础上按
[ESP32-CAM 极致省电实现方案](../ESP32-CAM-Ultra-Low-Power-Solution.md) 加了软件侧省电项。

> 状态：**尚未烧录**。只做了 `arduino-cli compile` 编译验证（esp32 核心 3.3.12）。

## 行为

**冷启动（上电/复位）**

1. 初始化摄像头 / SD 卡 → 连 WiFi + NTP（东八区）→ 立即拍一张存 SD
2. 网页服务与 WiFi 射频**只开 15 分钟**（页面顶部有「WiFi 剩余」倒计时）
3. 时间到：停网页服务 → 断 WiFi → 关射频
4. 关摄像头（`esp_camera_deinit()` + PWDN 拉高并保持）→ 卸载 SD → **进 deep sleep**

**定时唤醒（deep sleep 计时器，每小时一次）**

1. 释放 PWDN 保持、恢复时间与累计能耗
2. 初始化摄像头 / SD → 拍一张存 SD
3. 关摄像头、卸载 SD、继续深睡；**不连 WiFi**

窗口结束后网页不可用；要再看网页必须重启（重启会重新开 15 分钟窗口）。

网页的「重置测试」：删除 SD 卡上的 `IMG_*.jpg` 与 `POWER.CSV` 后自动 `ESP.restart()`，
复位后按冷启动流程重新连 WiFi/NTP、重开 15 分钟窗口，并从 `IMG_00001` 重新拍照。

## 省电措施

已实现（软件，全部在本固件里）：

| 措施 | 说明 | 对应方案里的 |
|---|---|---|
| 深睡占空比 | 除拍照与 15 分钟窗口外，CPU/射频全部休眠；`RTC_DATA_ATTR` 保存状态 | 3.1 / 3.2 ③ |
| WiFi 用完即关 | 窗口结束 `server.stop()` → `WiFi.disconnect(true)` → `WiFi.mode(WIFI_OFF)` | 3.2 ⑥ |
| 定时唤醒不连 WiFi | `esp_sleep_get_wakeup_cause()` 区分冷启动与定时唤醒 | 3.2 ② |
| 摄像头断电保持 | `esp_camera_deinit()` 后 PWDN 拉高，`gpio_hold_en` + `gpio_deep_sleep_hold_en` 保持到唤醒 | 3.2 ④ |
| 睡眠前卸载 SD | `SD_MMC.end()`，避免卡在睡眠中继续耗电 | 2.4 |
| 睡眠能耗记账 | `kModelSleepMa` + RTC 内存累计，`POWER.CSV` 的 `e_mwh` 不会被低估 | 2.3 |
| 关闭闪光灯 | GPIO4 输出低，开机即关 | — |

已经在默认值、无需改动的：

- **WiFi modem sleep**：Arduino ESP32 核心对 ESP32 的默认值就是 `WIFI_PS_MIN_MODEM`，不用再调。
- **未 hold 的数字 IO 自动隔离**：ESP32 的 deep sleep 入口会调用 IDF 的 `esp_sleep_isolate_digital_gpio()`，把没被 hold 的 IO 全部隔离，所以没有手写 `rtc_gpio_isolate()`。若实测深睡电流仍偏高，再按实际接线补。

没有做（及原因）：

| 措施 | 原因 |
|---|---|
| CPU 降频（240 → 80 MHz） | 本方案活跃阶段只有约 1 s/小时，省下的电 < 0.1%；反而给 SDMMC/摄像头时序引入风险 |
| BSSID + channel 直连、静态 IP | 只在冷启动连一次，能省 1~2 s × 120 mA ≈ 0.06 mAh，占 15 分钟窗口的 0.1% |
| 降低 TX 功率 | 窗口内基本是空闲收包，TX 占比极低；降功率有掉线风险 |
| `sdkconfig` 内核/系统配置 | 那是 ESP-IDF 的选项，Arduino 核心用的是预编译库，改不了 |
| 移除板载电源 LED | 硬件操作，收益 1~3 mA，最容易做，建议无论软件怎么改都做 |
| 换 LDO（AMS1117 → HT7333 等） | 硬件操作，5 mA 静态电流是当前深睡电流的硬上限 |
| MOSFET 切摄像头 / SD 供电 | 硬件操作，需割线；本固件已用 PWDN 把摄像头置待机 |

## 目录

```
esp32cam-powersave/powersave/
├─ powersave.ino        # 采集 + 15 分钟 WiFi/网页窗口 + 深睡
├─ web/
│   ├─ index.html       # 网页源码（改这个）
│   └─ build_header.py  # 生成 web_page.h
├─ web_page.h           # 由脚本生成，别手改
└─ secrets.h            # WiFi 凭据（已 gitignore）
```

网页改完跑一次：

```bash
cd 02-20Days-Challenge/esp32cam-powersave/powersave
python3 web/build_header.py
```

## 编译与烧录

```bash
cd 02-20Days-Challenge
arduino-cli compile --fqbn esp32:esp32:esp32cam esp32cam-powersave/powersave
# 确认后再烧（本次未执行）：
# arduino-cli upload -p /dev/ttyUSB0 --fqbn esp32:esp32:esp32cam esp32cam-powersave/powersave
```

可调参数都在 `powersave.ino` 顶部：

```cpp
static const uint32_t kCaptureIntervalMs = 60UL * 60UL * 1000UL;  // 拍照周期
static const uint32_t kWebWindowMs = 15UL * 60UL * 1000UL;        // WiFi 窗口
```

## 串口预期输出

```
=== ESP32-CAM 省电版（冷启动：WiFi + 网页开 15 分钟）===
[OK] 摄像头初始化完成
[OK] SD 卡初始化完成
[WIFI] 已连接，IP 192.168.x.x
[TIME] 2026-11-06 21:30:00
[CAP] /IMG_00001.jpg size=...B 2026-11-06 21:30:00 ...
[WEB] http://192.168.x.x/  窗口 15 分钟
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

## 功耗日志

`/POWER.CSV` 表头不变，事件行有四种：

| event | 含义 |
|---|---|
| `CAPTURE` | 拍照，`i_ma` 是该采集周期（含深睡）的平均电流模型值 |
| `SAMPLE` | 窗口期间每 5 分钟一次，WiFi 开着时按 45 + 120 mA 记 |
| `WEB_ON` | 窗口开始（`window_s=0` 表示瞬时事件） |
| `WEB_CLOSE` | 窗口结束，`window_s=900` 是这 15 分钟的平均电流 |

两点必须知道：

- **深睡期间不写日志**（SD 已卸载），所以 `SAMPLE` 只在窗口内出现；`e_mwh` 把深睡能耗按 `kModelSleepMa`（5 mA，AMS1117 静态电流主导）在入睡时一次性补上。
- **冷启动那一小时的 `CAPTURE` 行偏低**：它按「1 小时 - 15 分钟窗口」的模型算，没算窗口本身的 165 mA。看窗口能耗请看 `WEB_CLOSE` 行。

## 时间

- 只在**冷启动**同步 NTP；之后靠 RTC 和睡眠前记下的 epoch 延续。
- `deep sleep` 后 TZ 环境变量会丢，固件每次启动都重设 `CST-8`。
- RTC 慢钟有漂移（内部 RC，分钟级/天），需要精确时间就定期断电重启让 NTP 重新校准。

## 与方案文档的对应

- 方案里的 P1（软件零成本项）：除「移除 LED」（硬件）外都已落地。
- P2（`sdkconfig`）：Arduino 核心不可用，只能换 ESP-IDF 才能做。
- P3（BSSID/channel/静态 IP）：未做，收益 < 0.1%。
- P4（换 LDO、切外设供电）：硬件项，未做。
