# ESP32-CAM 睡眠模式演示固件（网页切换 + 2 分钟会话）

> 状态：本地编译通过；扩展演示，`normal` / `deep` 已实测（2026-11-22），`modem` / `light` 未实测（仅代码路径，见第 8 节）。
> 作用：网页上切换 4 种模式，对比「正常基线 / WiFi modem sleep / 浅睡 / 深睡」在
> 同一「30 s 一张、共 5 张」拍照节奏下的网页可达性与 `POWER.CSV` 事件。
>
> 口径：2 min 会话是 24 h 的压缩示意，不是真实占空比；省电数字仍以 powersave 的 24 h 实测为准。
> 现场演示脚本与预检见 [DEMO.md](DEMO.md)。

## 1. 它做什么

网页提供 4 个模式按钮。每次会话固定按 **0/30/60/90/120 s 各拍 1 张，共 5 张**，
第 5 张拍完即退出睡眠、回到正常模式，等待下一次网页命令。

| 模式 | WiFi / 网页 | 睡眠方式 | 睡眠中网页可达 | 唤醒后 | 实测 |
|---|---|---|---|---|---|
| `normal` 正常模式（基线） | 开 | 不休眠；会话中 WiFi `WIFI_PS_NONE`，空闲 `MIN_MODEM` | 是 | — | 已实测 |
| `modem` WiFi modem sleep | 开 | 不休眠；WiFi `WIFI_PS_MIN_MODEM` | 是（延迟略高） | — | 未实测 |
| `light` 浅睡 | 关 | `esp_light_sleep_start()` | 否；2 min 后恢复 | 重初始化摄像头 / SD | 未实测 |
| `deep` 深睡 | 关 | `esp_deep_sleep_start()` | 否；2 min 后恢复 | 完整重启，靠 RTC 续会话 | 已实测 |

> `modem` / `light` 只有代码路径，未实机验证；本表其余列是设计描述，不等于实测。

**空闲态（没有会话时）**：摄像头 `esp_camera_deinit()` 且 PWDN 拉高，WiFi 切回
`WIFI_PS_MIN_MODEM`；上表的 WiFi 档位只在**会话进行中**生效。空闲降档（关摄像头 + `MIN_MODEM`）的温升未系统测量，具体值引用前先复测。

浅睡/深睡期间 `server.stop()` + `WiFi.disconnect(true)` + `WiFi.mode(WIFI_OFF)`；
2 分钟结束后重新连 WiFi、校时、开网页。网页在睡眠期间会显示“设备睡眠中”，
恢复后自动继续轮询。

**与既有基线的关系**：`esp32cam-viewer` 的 WiFi 常开基线用的是 Arduino 默认
`WIFI_PS_MIN_MODEM`，实测常开空闲 `90 mA`。本演示的 `normal` 只在**会话进行中**显式
用 `WIFI_PS_NONE`（射频不睡，作最低延迟上界），空闲回到 `MIN_MODEM`；`modem` 全程
`MIN_MODEM`。比较时看同一条件下的模式差，不要跨固件抄绝对值。
## 2. 2 分钟会话时序

| 序号 | 相对进入时刻 | 动作 |
|---|---|---|
| 1 | 0 s | 立即拍照，写 `IMG_xxxxx.jpg` |
| 2 | 约 30 s | 拍照 |
| 3 | 约 60 s | 拍照 |
| 4 | 约 90 s | 拍照 |
| 5 | 约 120 s | 拍照，随后退出睡眠 / 结束会话，回到正常模式 |

- `normal` / `modem`：`loop()` 按 `s_next_shot_ms += 30000` 排程，5 张后 `SESSION_END`。
- `light` / `deep`：每次拍完先睡约 30 s（深睡会减去本次启动+拍照已用的时间，
  让拍照间隔仍接近 30 s）；第 5 张后不再睡，直接恢复 WiFi/网页。
- 深睡每次唤醒都是一次完整启动，串口会重新打印 banner；`RTC_DATA_ATTR` 保存
  `s_rtc_session_active` / `s_rtc_mode` / `s_rtc_shots_done` / `s_rtc_epoch` / `s_rtc_energy_mwh`。
- 深睡/浅睡期间 SD 已卸载，照片只写入 SD，不写 `POWER.CSV` 的 `SAMPLE`。

## 3. 网页与接口

网页源码在 [`sleep_demo/web/index.html`](sleep_demo/web/index.html)，由
[`sleep_demo/web/build_header.py`](sleep_demo/web/build_header.py) 生成
`sleep_demo/web_page.h` 后一起提交。`build_header.py` 会把页面 **gzip 压缩后**存成 C 数组（`10772 B → 3920 B`），
`/` 直接带 `Content-Encoding: gzip` 发出，浏览器自动解压——弱 2.4 GHz 链路上只有小响应才能稳定传完。

| 地址 | 方法 | 说明 |
|---|---|---|
| `/` | GET | 模式按钮 + 状态 + 照片墙 |
| `/api.json` | GET | 状态、会话进度、照片列表 |
| `/mode?m=normal\|modem\|light\|deep` | POST | 启动一次 2 分钟会话；会话进行中返回 `409` |
| `/stop` | POST | 提前结束当前会话，回到空闲；无会话时返回 `{"ok":true,"state":"idle"}` |
| `/IMG_xxxxx.jpg` | GET | 原图 |
| `/POWER.CSV` | GET | 下载功耗日志 |
| `/admin/reset` | POST | 清空 SD 根目录所有文件、复位编号/能耗/会话，回到空闲态；会话中返回 `409` |

`/api.json` 关键字段：

```json
{"ip":"192.168.16.50","now":"...","uptime":123,"mode":"deep",
 "mode_label":"深睡","session":"running","shots_done":2,"shots_total":5,
 "next_in_ms":12000,"wifi":true,"temp_c":49.4,"rssi":-63,"files":[...],"count":5}
```

- 睡眠期间设备不响应 HTTP，`wifi` 字段只在网页可达时有意义。
- 会话进行中再次 POST `/mode` 返回 `409 {"ok":false,"error":"session running"}`。
- 网页上**再次点当前选中（高亮）的模式按钮** = `POST /stop`，提前结束会话回空闲（`normal`/`modem`
  可用；浅睡/深睡期间网页离线，点不到）；该会话里已拍的照片保留。
- 网页上「清空全部数据」按钮就是 `POST /admin/reset`：删掉根目录所有文件（照片 + `POWER.CSV`），
  重建 `POWER.CSV` 并写一条 `RESET`，编号从 `IMG_00001` 重新开始，设备回到空闲（关摄像头）。
- 照片越多，`/api.json` 遍历 SD 目录越慢（59 张时 TTFB 约 `0.95 s`，清空后约 `0.2 s`）。
- `temp_c` / `rssi` 是 2026-11-22 加的，网页顶部显示为 `IP · dBm · °C`。

SSID、密码、静态 IP、网关、DNS 全部在 `sleep_demo/secrets.h`（已被 `.gitignore` 忽略，不入库）：
换 Wi-Fi 或换网段只改这一个文件，不用动 sketch。

本机示例是家庭网 `192.168.16.50`（网关 `192.168.16.1`）；2026-11-22 晚上实测切到
手机热点后改成了 `10.77.67.50`（网关 `10.77.67.199`），固件本身没改。新克隆先
`cp sleep_demo/secrets.example.h sleep_demo/secrets.h`，再填入自己的 SSID / 密码 / 静态 IP。

## 4. POWER.CSV 事件

表头与既有固件一致：

```text
uptime_s,event,window_s,v5_mv,i_ma,p_mw,e_mwh
```

| event | 含义 | `window_s` / `i_ma` |
|---|---|---|
| `WEB_ON` / `WEB_OFF` | 网页与 WiFi 开 / 关 | `0` / `0` |
| `MODE_NORMAL` / `MODE_MODEM` / `MODE_LIGHT` / `MODE_DEEP` | 会话开始 | `0` / `0` |
| `CAPTURE` | 拍照 + 写卡 | 正常/modem：`30`，按 30 s 周期平均；浅睡/深睡：拍照段向上取整到 1 s，按拍照段平均 |
| `LIGHT_SLEEP` / `DEEP_SLEEP` | 入睡 | 睡眠秒数 / 睡眠模型电流 |
| `LIGHT_WAKE` / `DEEP_WAKE` | 唤醒并重初始化完成 | `0` / `0` |
| `SESSION_END` | 5 张拍完，退出会话 | `0` / `0` |
| `SAMPLE` | 醒着时每 5 min 一次 | `300` / 当前模式模型电流 |
| `WIFI_FAIL` | 连接失败，30 s 后重试 | `0` / `0` |
| `RESET` | 网页/接口清空数据完成 | `0` / `0` |

- 深睡/浅睡的 `CAPTURE` **只覆盖唤醒拍照段**，睡眠段由 `*_SLEEP` 行单独记账；
  正常/modem 的 `CAPTURE` 覆盖整个 30 s 周期。两种口径不要混用。
- `e_mwh` 是模型累计值，不是实测电量；`SAMPLE` 在睡眠期间不会出现。

模型常量（`sleep_demo.ino` 顶部，**均为模型值，不是本固件实测**）：

| 常量 | 值 | 说明 |
|---|---|---|
| `kModelNormalMa` | `110.0` | 正常模式，WiFi 不睡；绝对值仅作上界参考 |
| `kModelModemMa` | `95.0` | 参考 powersave 窗口实测 `95 mA` 的口径 |
| `kModelAwakeMa` | `45.0` | 醒着但 WiFi 关，240 MHz 空转 + AMS1117 |
| `kModelShotMa` | `180.0` | 摄像头 init + JPEG 捕获 |
| `kModelSaveMa` | `50.0` | SD 写入 |
| `kModelLightMa` | `1.0` | 浅睡，芯片级模型；5 V 输入侧还有 LDO 静态电流 |
| `kModelDeepMa` | `6.0` | 官方手册整板 `6 mA @5V`；表只能给 `≤10 mA` 上界 |

没有接分压电阻（`kHasVbatDivider=false`），电压按 `4.90 V` 估算，`v5_mv` 记为 `-1`。

## 5. 状态机

```text
上电 ─► 初始化摄像头/SD ─► 连 WiFi + NTP ─► 开网页 ─► 空闲（normal）
                                                    │
       网页 POST /mode ────────────────────────────┘
         ├─ normal/modem：loop 每 30 s 拍照，5 张后 SESSION_END ─► 空闲
         ├─ light：关网页/WiFi ─► 拍照 ─► 关摄像头/SD ─► light sleep 29.3 s
         │         └─ 唤醒 ─► 重初始化摄像头/SD ─► 拍照 … 第 5 张 ─► 连 WiFi/开网页 ─► 空闲
         └─ deep：关网页/WiFi ─► 拍照 ─► 关摄像头/SD + GPIO hold ─► deep sleep 29 s
                   └─ 定时唤醒（完整启动）─► RTC 恢复会话 ─► 拍照 … 第 5 张 ─► 连 WiFi/开网页 ─► 空闲
```

| 动作 | 源码位置 |
|---|---|
| 模式解析与 `/mode` | `handleMode()` / `parseMode()` |
| 会话启动、深睡/浅睡分支 | `startSession()` |
| 浅睡会话循环 | `runLightSession()` / `sleepLightFor()` |
| 深睡入睡、RTC 记账 | `sleepDeepFor()` |
| 深睡唤醒恢复 | `setup()` 的 `resume_deep` 分支 |
| 会话结束、回空闲低功耗（关摄像头 + `MIN_MODEM`） | `finishSession()` / `enterIdleState()` |
| 会话开始前重新给摄像头上电 | `leaveIdleState()` |
| 网页状态 JSON | `handleApi()` |

## 6. 编译与烧录

```bash
cd 02-20Days-Challenge
export ARDUINO_DIRECTORIES_DATA=$PWD/.arduino/data ARDUINO_DIRECTORIES_USER=$PWD/.arduino/user
# 新克隆先创建本机凭据（secrets.h 已被 .gitignore 忽略）
cp firmware/esp32cam-sleep-demo/sleep_demo/secrets.example.h firmware/esp32cam-sleep-demo/sleep_demo/secrets.h
# 再编辑 secrets.h，填入 SSID / 密码 / 静态 IP

# 只编译本演示
./arduino-cli compile --fqbn esp32:esp32:esp32cam --build-path .arduino/build-demo \
  firmware/esp32cam-sleep-demo/sleep_demo
```

烧录必须在宿主机执行（容器内打开 `/dev/ttyUSB0` 会被文件沙箱拒绝）。仓库里有一个
只做 upload 的脚本 [`flash_demo.sh`](flash_demo.sh)，容器内先编译，再：

```bash
distrobox-host-exec 02-20Days-Challenge/firmware/esp32cam-sleep-demo/flash_demo.sh
```

仓库根目录的 `make firmware` 也会编译本演示（第三个编译目标；若 `arduino-cli` 在 PATH，用 `make firmware ARDUINO_CLI=arduino-cli`）。
`esp32cam` 板级定义已默认 `-DBOARD_HAS_PSRAM`，不需要额外 `PSRAM=enabled` 菜单。

串口日志可用 [`measurement/serial_capture.py`](../../measurement/serial_capture.py)，但打开/关闭串口会通过
DTR/RTS 复位板子，验证主体仍以网页/API 为准。
## 7. 串口预期输出（关键行）

冷启动：

```text
=== ESP32-CAM 睡眠模式演示（冷启动）===
[OK] 摄像头初始化完成
[OK] SD 卡初始化完成
[OK] 下一张编号 IMG_00001.jpg
[TEMP] boot 56.1 C
[WIFI] 连接 B-LINK_601（modem sleep=off）...
[WIFI] 已连接，IP 192.168.16.50
[TIME] 2026-11-22 20:30:00
[PWR] ... WEB_ON ...
[WEB] http://192.168.16.50/
[IDLE] 摄像头已关闭，WiFi 转 MIN_MODEM
[HB] up=10s temp=58.9C mode=normal session=0 shots=0
```

深睡会话：

```text
[MODE] 深睡 会话开始（5 张，每 30s 一张）
[WEB] 已关闭网页服务与 WiFi
[CAP] /IMG_00001.jpg size=... capture=...ms save=...ms
[PWR] ... DEEP_SLEEP ...
[SLEEP] 深睡 29s，会话进度 1/5
=== ESP32-CAM 睡眠模式演示（深睡定时唤醒）===
...
[PWR] ... DEEP_WAKE ...
[CAP] /IMG_00002.jpg ...
...
[MODE] 会话结束，已回到空闲（摄像头关闭、WiFi MIN_MODEM）
[WIFI] 已连接，IP 192.168.16.50
[WEB] http://192.168.16.50/
```

浅睡会话：不重启，串口连续输出 `LIGHT_SLEEP` / `LIGHT_WAKE` / `[CAP]` 交替 5 次，
最后 `[MODE] 会话结束，已回到空闲（摄像头关闭、WiFi MIN_MODEM）`。

正常/modem 会话：

```text
[MODE] 正常模式（基线） 会话开始（5 张，每 30s 一张）
[CAP] /IMG_00001.jpg ...
...
[PWR] ... SESSION_END ...
[MODE] 会话结束，回到正常模式
```

## 8. 实机验证

> 2026-11-22，AI-Thinker ESP32-CAM，USB 供电，USB-TTL 只接 TX/RX/GND。

**已实测**

- `normal`：22:00 一轮 5/5，5 张 30 s 间隔，`SESSION_END` 后回 idle。
- `deep`：23:07–23:09 一轮 5/5，4×`DEEP_SLEEP` / `DEEP_WAKE`，网页离线约 90 s 后恢复；每次唤醒 `uptime` 归零。
- 页面 gzip：`web_page.h` 压缩后 `3920 B`，可用 `sleep_demo/web/build_header.py` 复核。

**未实测**

- `modem` / `light`：只有代码路径，未实机验证；不能按「已验证」引用。
- `normal` / `deep` 的表锚点、串口原始日志、网页截图/录屏：未入库；`modem` / `light` 未实测。

**调试观察（未系统测量，引用前复测）**

- 弱 2.4 GHz 链路下大帧传输会卡；串口打开/关闭会通过 DTR/RTS 复位板子。

## 9. 限制与未做

- **扩展演示的边界**：本演示是自加的扩展，不是 20 天挑战的三项交付；只有 `normal` / `deep` 有实测，`modem` / `light` 未实测，别把设计描述当实机结论。
- **电流是模型值**：本固件没有接 USB 表自动采样，`POWER.CSV` 的 `i_ma` 是模型；
  不能把 `kModelLightMa=1.0` 当成 5 V 输入侧实测值。真值需要 INA219/低阻分流或
  人工读表。
- **5 V 输入侧浅睡不一定明显低于深睡**：板载 AMS1117 的静态电流在两种睡眠下都在，
  深睡手册整板 `6 mA`；浅睡芯片级更低，但 5 V 侧可能被 LDO 掩盖。这是硬件口径问题，
  不是固件把浅睡做成了深睡。
- **睡眠期间网页不可达**是设计结果：浅睡/深睡都关了 WiFi/网页，页面只能等设备
  2 分钟后回来；modem 模式才保持网页可访问。
- **深睡靠 RTC 续会话**：若 2 分钟内断电/按 EN，RTC 会话丢失，冷启动回到正常模式，
  已拍照片保留。
- **normal 与既有 90 mA 基线不同口径**：本演示 `normal` 只在会话中用 `WIFI_PS_NONE`，
  空闲和 `modem` 一样回 `MIN_MODEM`；`viewer` 基线全程默认 `MIN_MODEM`。跨固件比较请看
  同一条件下的模式差，不要直接抄绝对值。
- **WiFi 恢复失败**：退出睡眠后连不上会每 30 s 重试；照片已在 SD，网页恢复后可见。
- 没有实现：手动立即拍照、OTA、GPIO 按键唤醒（清 SD 已有 `POST /admin/reset`）。
- **串口抓取会干扰验证**：DTR/RTS 接 EN/GPIO0，打开或关闭 `/dev/ttyUSB0` 都可能复位
  板子；关闭后还可能停在下载态。需要串口时只做短时抓取，验证主体用网页/API。
- **发热与供电**：AMS1117 在 5 V 输入下发热明显（压差 1.7 V × 0.2~0.3 A 全变热）；摄像头常开
  + `PS_NONE` 时电流和温度会明显更高（具体值未复测）。固件降档是空闲关摄像头 + `MIN_MODEM`；
  会话中 `normal` 仍是 `PS_NONE`（最低延迟，也最热）。硬件上更有效的是
  3.3 V 直供（跳过 LDO）或 5V→3.3V DC-DC，其次散热片/风扇。传感器只测 die，不代表 LDO。
- **弱 2.4 GHz 链路下大响应会卡住**：小帧可靠，>1 kB 的响应在弱信号下经常只发出一部分就停。
  `/` 已用 gzip 压到 3.9 KB，可稳定送达；但单张照片 `20~36 KB` 仍可能传不完。
  缓解顺序：先改善信号（靠近路由器、换 2.4 GHz AP 或手机热点），再考虑降分辨率。

## 10. 目录

```text
firmware/esp32cam-sleep-demo/
├── README.md                 # 本页
├── DEMO.md                   # 现场流程与预检
├── flash_demo.sh             # 宿主机 upload
└── sleep_demo/
    ├── sleep_demo.ino        # 4 模式状态机 + 网页服务
    ├── web_page.h            # 由 web/index.html 生成，不手改
    ├── secrets.example.h     # 凭据模板（入库）
    ├── secrets.h             # 本机 WiFi 凭据（gitignore）
    └── web/
        ├── index.html        # 模式按钮 + 状态 + 照片墙
        └── build_header.py   # index.html -> web_page.h
```

相关：[主基线 viewer](../esp32cam-viewer/README.md)、
[省电版 powersave](../esp32cam-powersave/README.md)、
[项目 README](../../README.md)、[测量口径](../../measurement/README.md)。
