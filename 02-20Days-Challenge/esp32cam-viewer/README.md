# ESP32-CAM 采集查看器（P0 主基线）

采集逻辑：每小时一张，JPEG 存 SD 卡；**WiFi 常开**并起一个网页，看拍到哪些照片、
每张的拍摄时间，以及下载 `/POWER.CSV`。

> 这就是本项目的**主基线**：后续省电方案同样保留 WiFi（只是改成需要时才连、连上就干活、
> 干完就睡），所以对比的是「同样开着 WiFi，谁更省」。
> WiFi 完全关闭的版本是 [esp32cam-baseline](../esp32cam-baseline/README.md)，只作为下限参考。

- 每 5 分钟向 SD 卡 `/POWER.CSV` 追加一行功耗日志（模型推算，电压需外接分压才可测）
- 跑正式数据集前，把 `kClearDataOnBoot` 临时改 `true` 烧一次清卡，再改回

## 凭据

WiFi 账号密码放 `viewer/secrets.h`（已 gitignore，不会进仓库）：

```cpp
static const char *kWifiSsid = "...";
static const char *kWifiPass = "...";
```

## 目录

```
esp32cam-viewer/viewer/
├─ viewer.ino          # 采集 + Web 服务器逻辑
├─ web/
│   ├─ index.html      # 网页源码（改这个）
│   └─ build_header.py # 把 index.html 打包成 web_page.h
├─ web_page.h          # 由脚本生成，别手改
└─ secrets.h           # WiFi 凭据（已 gitignore）
```

网页是普通 HTML/CSS/JS，改完跑一次：

```bash
cd 02-20Days-Challenge/esp32cam-viewer/viewer
python3 web/build_header.py     # → 生成 web_page.h
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
| `/` | 卡片式照片墙：缩略图、文件名、大小、拍摄时间；顶部状态栏显示 IP、当前时间、运行时长、照片数 |
| `/api.json` | 状态 + 照片列表（JSON），网页每 1 秒拉一次 |
| `/IMG_xxxxx.jpg` | 原图 |
| `/POWER.CSV` | 下载功耗日志 |
| `/capture` | 立即拍一张（不用等一小时） |

页面不整页刷新：每 1 秒请求一次 `/api.json`，新照片才建卡片插到最前，
已有的卡片只更新时间与大小，所以看图过程中不会闪、也不会重复下载图片。

> 刷新频率高意味着设备每秒都要扫一遍 SD 目录、组一次 JSON。**测功耗时请把
> 网页关掉**，否则这一秒一次的请求本身就是一笔可观的负载。

## 时间从哪来

开机联网后同步 NTP（东八区），之后写卡的照片 FAT 时间戳就是真实时间。
**NTP 同步之前**拍的照片（例如基线固件留下的旧图）没有时间基准，网页上显示
「无时间戳」。
