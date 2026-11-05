# ESP32-CAM 采集查看器

采集逻辑和 P0 基线一样（每小时一张，JPEG 存 SD 卡），额外常开 WiFi 起一个网页，
用来看拍到哪些照片、每张的拍摄时间，以及下载 `/POWER.CSV`。

> **不能用来测功耗**：WiFi 全程常开，平均电流远高于 `esp32cam-baseline`。
> 要交功耗基线数据就切回基线固件。

## 凭据

WiFi 账号密码放 `viewer/secrets.h`（已 gitignore，不会进仓库）：

```cpp
static const char *kWifiSsid = "...";
static const char *kWifiPass = "...";
```

## 编译与烧录

```bash
cd 02-20Days-Challenge

arduino-cli compile --fqbn esp32:esp32:esp32cam esp32cam-viewer/viewer
arduino-cli upload -p /dev/ttyUSB0 --fqbn esp32:esp32:esp32cam esp32cam-viewer/viewer
```

串口会打印网页地址：

```
[WIFI] 已连接，IP 192.168.16.109
[TIME] 2026-11-05 15:34:27
[CAP] /IMG_00003.jpg size=17128B 2026-11-05 15:34:27
[WEB] http://192.168.16.109/
```

## 网页功能

| 地址 | 说明 |
|---|---|
| `/` | 照片列表：文件名、大小、拍摄时间、缩略预览 |
| `/IMG_xxxxx.jpg` | 原图 |
| `/POWER.CSV` | 下载功耗日志 |
| `/capture` | 立即拍一张（不用等一小时） |

## 时间从哪来

开机联网后同步 NTP（东八区），之后写卡的照片 FAT 时间戳就是真实时间。
**NTP 同步之前**拍的照片（例如基线固件留下的旧图）没有时间基准，网页上显示
「无时间戳」。
