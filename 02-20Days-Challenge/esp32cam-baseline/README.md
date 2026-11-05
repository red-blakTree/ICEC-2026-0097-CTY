# ESP32-CAM 基础采集（WiFi 关闭，下限参考）

项目一「智能终端极致省电」的**下限参考**：一小时拍一张照，存 SD 卡，其余什么都不做。

> **这不是主基线**。主基线是 [esp32cam-viewer](../esp32cam-viewer/README.md)（WiFi 常开 +
> 网页可查），因为后续省电方案仍会保留 WiFi。本固件只关掉 WiFi，用来标出
> 「WiFi 完全不开」时能到多低，作为下限参考。

- 不降频、不进任何睡眠、不做外设断电、WiFi 全程关闭
- CPU 240 MHz 空转，`millis()` 轮询等一小时
- 上电立即拍一张，之后每小时一张，JPEG 存 SD 卡，串口打印耗时
- 每 5 分钟向 SD 卡 `/POWER.CSV` 追加一行功耗日志（电压需外接分压才可测）

对比口径见 [ESP32-CAM-Ultra-Low-Power-Solution.md](../ESP32-CAM-Ultra-Low-Power-Solution.md)
的第五章 P0 段。

## 目录

```
esp32cam-baseline/
├── README.md
└── baseline_capture/
    └── baseline_capture.ino
```

## 环境准备

```bash
# 1. 安装 ESP32 核心（首次约几百 MB，需要网络）
arduino-cli core update-index
arduino-cli core install esp32:esp32

# 2. 安装摄像头驱动库
arduino-cli lib install "esp32-camera"
```

## 编译

```bash
cd 02-20Days-Challenge/esp32cam-baseline

# esp32 核心 3.3.x 的 esp32cam 板已硬编码 -DBOARD_HAS_PSRAM，没有 PSRAM 菜单项，不需要额外参数
arduino-cli compile --fqbn esp32:esp32:esp32cam baseline_capture
```

## 烧录

ESP32-CAM 没有板载 USB 口，需要用 USB-TTL 转接板：

| ESP32-CAM | USB-TTL |
|---|---|
| 5V | 5V |
| GND | GND |
| U0R | TX |
| U0T | RX |

1. **GPIO0 接 GND**（进入下载模式），插上 USB-TTL，再按一下板上的 RST 键
2. 烧录：

```bash
arduino-cli upload -p /dev/ttyUSB0 \
  --fqbn esp32:esp32:esp32cam baseline_capture
```

3. 拔掉 GPIO0 的 GND，按一下 RST，串口监视器看日志：

```bash
arduino-cli monitor -p /dev/ttyUSB0 --config baudrate=115200
```

正常输出：

```
=== ESP32-CAM 基础采集（P0 基线，未做任何省电优化）===
采集周期: 3600 s
[OK] 摄像头初始化完成
[OK] SD 卡初始化完成
[INFO] 功耗日志 /POWER.CSV：每 300 s 一行（电流为模型推算，非实测）
[OK] 从 IMG_00001.jpg 开始编号
[INFO] 上电立即拍一张，随后每小时一张
[CAP] /IMG_00001.jpg size=48321B capture=0ms save=57ms uptime=0s
[PWR] 0,CAPTURE,3600,-1,45.1,225.3,0.0000
```

## 上板验证（建议先改短周期）

正式跑 24 小时前，把 `kCaptureIntervalMs` 临时改成 `10000UL`（10 秒），确认：

- 每次都能成功写卡且编号递增
- 拔插重启后编号接着涨、不覆盖旧图
- 串口 `[CAP]` 行的 `capture` / `save` 耗时合理（SVGA 约 200–500 ms / 几十 ms）

验证通过后改回 `3600UL * 1000UL` 再烧录。

## 怎么用它测基线

2. 连续跑满 24 小时，固件会同时产出 `IMG_*.jpg` 和 `/POWER.CSV`
3. 用 `POWER.CSV` 的 `i_ma` / `e_mwh` 画电流与累计能耗时序
4. 这些数据就是后续 Deep-Sleep、断电控制、降频版本的对比基准

> **口径说明**：本版本没有电流表，`i_ma` 是「实测耗时 × 模型电流」推算出来的，
> 未接分压时 `v5_mv` 恒为 `-1`。要拿到真正的实测电流，必须串电流表或 INA219。
注意：本版本测的是「一直通电、CPU 全速、WiFi 关闭」的平均电流，**不含 AMS1117
静态电流之外任何睡眠贡献**——它的 `I_sleep` 实际上就是 CPU 空转电流，这正是
优化要打掉的量。

## 功耗日志（SD 卡 `/POWER.CSV`）

每 5 分钟追加一行，同时通过串口打印 `[PWR]`，不拔卡也能远程观察：

| 列 | 含义 |
|---|---|
| `uptime_s` | 开机秒数 |
| `event` | `SAMPLE`（5 分钟定时）/ `CAPTURE`（一次拍照） |
| `window_s` | 该行统计的时间窗口 |
| `v5_mv` | 5V 母线电压实测值，**未接分压时为 -1** |
| `i_ma` | 窗口内平均电流，**模型推算值** |
| `p_mw` | `i_ma × 电压`（未接分压时按 5000 mV 算） |
| `e_mwh` | 累计能耗，按空转电流积分（拍照瞬间的额外能耗未计入） |

模型常量在草图顶部，都是**典型值、未标定**，有电流表后按实测替换：

```cpp
static const float kModelIdleMa = 45.0f;   // 240 MHz 空转 + AMS1117 静态
static const float kModelShotMa = 180.0f;  // 摄像头 init + JPEG 捕获
static const float kModelSaveMa = 50.0f;   // SD 卡写入
```

### 接上分压后测电压

ESP32 的 ADC 引脚只能吃 3.3V，量 5V 必须分压：

```
5V ──[100k]──┬── IO16
             │
          [100k]
             │
            GND
```

改两个常量即可启用（`kDividerRatio = (R1 + R2) / R2`）：

```cpp
static const bool  kHasVbatDivider = true;
static const float kDividerRatio   = 2.0f;
```

## 已知限制

- **没有真实时间戳**：不联网就没有 RTC，文件名只有序号，日志里的时间是
  `uptime`（开机秒数）
- **不上传**：只存 SD 卡；需要 WiFi 上传的话另加
- **重启会续号**：靠扫描 SD 根目录 `IMG_*.jpg` 的最大编号 +1
- **SD 卡未插**：会每 5 秒重试初始化，不会崩溃，但也不会拍照
- **电压/电流不是实测**：没接分压就没有电压采样，`i_ma` 是模型推算值；
  24 小时 CSV 只能算「模型推算时序」，评分要的「实测」必须靠外接电流表
- **只在 AI-Thinker 板 + esp32 核心 3.3.12 上验证过**：换核心版本后需重新确认 FQBN 与库版本
