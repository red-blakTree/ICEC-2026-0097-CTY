# ESP32-CAM 主基线固件：采集查看器（P0）

> 状态：**已在 AI-Thinker ESP32-CAM 上烧录运行**（esp32 核心 3.3.12）。
> 作用：每小时拍一张存 SD，WiFi 常开并起网页；这是本项目的**主基线**——省电版同样保留 WiFi，只是改成需要时才连。

## 1. 行为

- 采集节奏：`kCaptureIntervalMs = 60 min`，开机先拍一张，之后每小时一张，JPEG 存 SD。
- **WiFi 全程常开**，起一个网页：看照片墙、`/api.json`、下载 `/POWER.CSV`。
- 每 5 分钟向 `/POWER.CSV` 追加一行（模型推算：`kModelIdleMa = 45 mA`，电压需外接分压才可测）。
- 网页每秒拉一次 `/api.json`；**测功耗时请把网页关掉**，否则这一秒一次的请求本身就是负载。

## 2. 网页接口

| 地址 | 说明 |
|---|---|
| `/` | 卡片式照片墙：缩略图、文件名、大小、拍摄时间；顶部状态栏显示 IP、时间、运行时长、照片数 |
| `/api.json` | 状态 + 照片列表（JSON），网页每 1 秒拉一次 |
| `/IMG_xxxxx.jpg` | 原图 |
| `/POWER.CSV` | 下载功耗日志 |
| `/capture` | 立即拍一张，返回 `{"ok":true}`；页面按钮原地刷新 |
| `/reset` | **仅 POST**：删光照片与 `POWER.CSV`，从 `IMG_00001` 重新开始并立即拍一张 |

## 3. 基线实测值

| 项 | 值 | 来源 |
|---|---|---|
| P6 常开空闲 | `0.09 A / 5.04 V / 0.45 W` | 表直读 + 24 h 端点 |
| P6 开网页 | `0.11–0.14 A` | 录屏 |
| 24 h 健康空闲 | `2.16 Ah / 10.8 Wh`，平均 `90 mA` | 24 h 表端点 |
| 本轮 24 h（含异常档） | `≈16.38 Wh / 135.4 mA`（≈140） | 表累计 `16384 mWh / 24 h`；12:08 前约 3.8 h 断连 + 之后 8.8 h 仍在 0.18 A 档 |
| 24 h 异常日（含 ~12.6 h WiFi 断连） | `≈3.25 Ah / ≈16.38 Wh`，平均 `135.4 mA` | 24 h 表累计 |
| 拍照 + 写卡（P3） | 连拍推断 `130–160 mA`；视频 1 s 表读 `0.10–0.13 A` | 连拍 / 视频 |

**为什么 `POWER.CSV` 是低估值**：固件模型只按 `kModelIdleMa = 45 mA` 记账，**不含 WiFi 电流**；实测常开空闲是 `0.09 A`，是它的 2 倍。`POWER.CSV` 只能证明拍照时间线，不能当电量。

## 4. 编译与烧录

```bash
cd 02-20Days-Challenge
export ARDUINO_DIRECTORIES_DATA=$PWD/.arduino/data ARDUINO_DIRECTORIES_USER=$PWD/.arduino/user
# 新克隆先创建本机凭据（secrets.h 已被 .gitignore 忽略）
cp firmware/esp32cam-viewer/viewer/secrets.example.h firmware/esp32cam-viewer/viewer/secrets.h
# 再编辑 secrets.h，填入 SSID / 密码

./arduino-cli compile --fqbn esp32:esp32:esp32cam --build-path .arduino/build-viewer firmware/esp32cam-viewer/viewer
./arduino-cli upload -p /dev/ttyUSB0 --fqbn esp32:esp32:esp32cam --build-path .arduino/build-viewer firmware/esp32cam-viewer/viewer
```

串口会打印网页地址：

```text
[WIFI] 已连接，IP 192.168.16.105
[TIME] 2026-11-16 17:29:51
[CAP] /IMG_00004.jpg size=16553B 2026-11-16 17:29:51 capture=0ms save=69ms
[WEB] http://192.168.16.105/
```

## 5. 证据映射

| 证据 | 内容 |
|---|---|
| [baseline-viewer-meter-2026-11-10](../../process_logs/baseline-viewer-meter-2026-11-10/README.md) | 常开空闲 `0.09 A` 直读 + 开网页 `0.11–0.14 A` 录屏 |
| [baseline-24h-2026-11-09](../../process_logs/baseline-24h-2026-11-09/README.md) | 24.00 h、24 张逐小时照片、322 行模型 `POWER.CSV` |
| [baseline-24h-meter-2026-11-10](../../process_logs/baseline-24h-meter-2026-11-10/README.md) | 24 h 表端点、10 个表盘点、WiFi 断连段 `0.18 A` |
| [baseline-viewer-meter-2026-11-16](../../process_logs/baseline-viewer-meter-2026-11-16/README.md) | P3 24 s/10 次连拍视频（1 s 表读 `0.10–0.13 A`） |

## 6. 时间与凭据

- 开机联网后同步 NTP（东八区），之后写卡的照片 FAT 时间戳就是真实时间。
- NTP 同步之前拍的照片（例如基线固件留下的旧图）没有时间基准，网页上显示“无时间戳”。
- WiFi 账号密码放 `viewer/secrets.h`（已 gitignore，不会进仓库；模板是 `viewer/secrets.example.h`）：

```cpp
static const char *kWifiSsid = "...";
static const char *kWifiPass = "...";
```

## 7. 目录

```text
firmware/esp32cam-viewer/viewer/
├─ viewer.ino          # 采集 + Web 服务器逻辑
├─ web/
│   ├─ index.html      # 网页源码（改这个）
│   └─ build_header.py # 把 index.html 打包成 web_page.h
├─ web_page.h          # 由脚本生成，别手改
├─ secrets.example.h   # 模板（入库）
└─ secrets.h           # WiFi 凭据（已 gitignore）
```

网页改完跑一次：

```bash
cd 02-20Days-Challenge/firmware/esp32cam-viewer/viewer
python3 web/build_header.py     # → 生成 web_page.h
```

## 8. 局限

- 单张照片只有 `capture=0 ms / save=60–90 ms`，0.01 A 表抓不到峰值；P3 的定量值靠连拍放大。
- `POWER.CSV` 是模型值（45 mA、`v5_mv=-1`），不是表实测曲线；24 h 电量以表端点/累计为准。
- 只有一块板，板间差异未覆盖。
