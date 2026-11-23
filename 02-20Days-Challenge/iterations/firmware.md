# 固件迭代明细

三个固件是**迭代关系**，不是三个并列方案：F1 建立可比基线，F2 在同样的 WiFi 需求下压时间占比，F3 是标定用的临时固件。烧录环境统一为 esp32 核心 3.3.12，AI-Thinker ESP32-CAM。

## F1 基线 viewer

- **改动**：`kCaptureIntervalMs = 60 min`，开机先拍一张；WiFi 全程常开；网页提供 `/api.json`、`/IMG_xxxxx.jpg`、`/POWER.CSV`、`/capture`、`/reset`；每 5 分钟向 `POWER.CSV` 追加一行。
- **动机**：省电版要保留「同样开 WiFi 能查图」的能力才可比，否则会变成拿「不联网」比「联网」。
- **验证**：健康段 `2.16 Ah / 10.8 Wh`，平均 `90 mA`；本轮 24 h 表累计 `16.38 Wh / 135.4 mA`（≈140，含异常档）；常开直读 `0.09 A / 5.04 V`；开网页 `0.11–0.14 A`。原始记录见 [`../process_logs/baseline-viewer-meter-2026-11-10/`](../process_logs/baseline-viewer-meter-2026-11-10/README.md) 与 [`../process_logs/baseline-24h-2026-11-09/`](../process_logs/baseline-24h-2026-11-09/README.md)。
- **边界**：`POWER.CSV` 按 `kModelIdleMa = 45 mA` 记账且不含 WiFi，是低估值；只能证明拍照时间线，不能当电量。

## F2 省电版 powersave

- **改动**：冷启动连 WiFi + NTP → 拍照 → 开 15 min 网页窗口 → 停网页、`WiFi.disconnect(true)` + `WIFI_OFF` → `esp_camera_deinit()` 后 PWDN 拉高并 `gpio_hold` → `SD_MMC.end()` → 深睡 1 h；定时唤醒释放 PWDN、恢复时间与累计能耗，拍照后继续深睡，**不连 WiFi**。
- **动机**：常开空闲 `0.09 A` 里射频占大头，把射频从 24 h 压到 15 min，比抠 CPU 频率更划算（活跃段仅 33.6–50.4 s/天）。
- **验证**：24 h 平均 `6.98 / 10.94 mA` 是模型输出；实测锚点只有基线 `90/140 mA`；深睡 `<0.01 A` 是表上界（省电版测不出来）；窗口 `95 mA` / 唤醒 `145 mA` / `1.4 s` 是模型假设，不是实测。15.20 h 设备日志见 [`../process_logs/powersave-15h-2026-11-10/README.md`](../process_logs/powersave-15h-2026-11-10/README.md)。状态机与源码行号映射见 [`../docs/state-machine.md`](../docs/state-machine.md)。
- **未做（有原因的）**：

| 项 | 结论 |
|---|---|
| CPU 降频 240 → 80 MHz | 已定量评估、未启用：收益 `≤0.42 mAh/天`（<0.25 %），风险是 OV2640 XCLK / SDMMC 时序 |
| BSSID + channel 直连 | 省 1–2 s × 120 mA ≈ 0.06 mAh，占窗口 0.1 %，不值得改连接逻辑 |
| 换 LDO / MOSFET 切外设供电 / 去 LED | 属硬件改造，只写进方案，未实做 |

## F3 拍照探针 capture-probe

- **改动**：不连 WiFi、不睡眠，按秒连拍写卡；`SAVE_TO_SD` 决定「拍照 + 写卡」还是「只拍照丢帧」。
- **动机**：单次 `capture = 0 ms / save = 60–90 ms`，0.01 A 秒级表抓不到；连拍把占空比推到接近 100 %，表才读得到稳定均值。
- **验证**：WiFi 关联下连拍 `0.13–0.16 A` 是模型/探针推断，未作为实测。
- **不能测**：60–90 ms 的瞬时峰值；也不能替代基线 P3——探针是无 WiFi 条件，基线 P3 是 WiFi 关联 + 拍照写卡。
- **注意**：连拍会很快填满 SD 卡，标定完刷回 F1 或 F2。

## 附：演示固件 esp32cam-sleep-demo

不是 F1–F3 的迭代：它不参与 24 h 省电测量，只把「正常 / modem sleep / 浅睡 / 深睡」四种状态放到网页上切换，用于现场对比行为（normal/deep 已实测，modem/light 未实测）。说明见 [README](../firmware/esp32cam-sleep-demo/README.md)，现场流程见 [DEMO](../firmware/esp32cam-sleep-demo/DEMO.md)。
