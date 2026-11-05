# ESP32-CAM 基础采集（P0 功耗基线）

项目一「智能终端极致省电」的**对照基线**：一小时拍一张照，存 SD 卡，其余什么都不做。

- 不降频、不进任何睡眠、不做外设断电、WiFi 全程关闭
- CPU 240 MHz 空转，`millis()` 轮询等一小时
- 上电立即拍一张，之后每小时一张，JPEG 存 SD 卡，串口打印耗时

后续所有省电方案的电流/续航，都应该和这个版本对比（见
[ESP32-CAM-Ultra-Low-Power-Solution.md](../ESP32-CAM-Ultra-Low-Power-Solution.md) 的 P0 阶段）。

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
[OK] 从 IMG_00001.jpg 开始编号
[INFO] 上电立即拍一张，随后每小时一张
[CAP] /IMG_00001.jpg size=48321B capture=312ms save=45ms uptime=5s
```

## 上板验证（建议先改短周期）

正式跑 24 小时前，把 `kCaptureIntervalMs` 临时改成 `10000UL`（10 秒），确认：

- 每次都能成功写卡且编号递增
- 拔插重启后编号接着涨、不覆盖旧图
- 串口 `[CAP]` 行的 `capture` / `save` 耗时合理（SVGA 约 200–500 ms / 几十 ms）

验证通过后改回 `3600UL * 1000UL` 再烧录。

## 怎么用它测基线

1. 摄像头和 SD 卡都装好，串口接上（基线测量允许串口常连）
2. USB 电流表串在 5V 供电线上
3. 读取 10–30 分钟的平均电流，记作 `I_avg(基线)`
4. 连续跑满 24 小时，用电压记录仪或定时读数记下电压/电流时序
5. 这些数据就是后续 Deep-Sleep、断电控制、降频版本的对比基准

注意：本版本测的是「一直通电、CPU 全速、WiFi 关闭」的平均电流，**不含 AMS1117
静态电流之外任何睡眠贡献**——它的 `I_sleep` 实际上就是 CPU 空转电流，这正是
优化要打掉的量。

## 已知限制

- **没有真实时间戳**：不联网就没有 RTC，文件名只有序号，日志里的时间是
  `uptime`（开机秒数）
- **不上传**：只存 SD 卡；需要 WiFi 上传的话另加
- **重启会续号**：靠扫描 SD 根目录 `IMG_*.jpg` 的最大编号 +1
- **SD 卡未插**：会每 5 秒重试初始化，不会崩溃，但也不会拍照
- **未实测验证**：本文档与代码尚未在目标硬件上编译运行，编译命令与
  `esp32-camera` 库版本字段（`pin_sccb_sda` 需要 2.x）均需首次上板时确认
