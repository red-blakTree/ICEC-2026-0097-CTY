# 迭代记录：固件版本与测量口径

> 这里只收**改了什么、为什么改、怎么验证、产物在哪**，不重复存代码和数据。
> 源码在 [`../firmware/`](../firmware/)，原始记录在 [`../process_logs/`](../process_logs/)，脚本与表在 [`../measurement/`](../measurement/)，方案文档在 [`../docs/`](../docs/)。

判断标准只有一条：**改动必须有一次可回查的验证**。没有验证的改动记为「未落地」，不写进结论。

## 1. 固件迭代

| 轮次 | 固件 | 相对上一轮改了什么 | 动机 | 验证 | 明细 |
|---|---|---|---|---|---|
| F1 | [`esp32cam-viewer`](../firmware/esp32cam-viewer/README.md) | 建立基线：每小时一张 JPEG 存 SD，WiFi 全程常开，网页可查图 / 下载 `POWER.CSV` | 没有可比基线就判不出「省了多少」 | 24.00 h 表端点 `2.16 Ah / 10.8 Wh`（`90 mA`）；常开直读 `0.09 A / 5.04 V` | [firmware.md](firmware.md) |
| F2 | [`esp32cam-powersave`](../firmware/esp32cam-powersave/README.md) | 冷启动开 15 min WiFi 窗口，窗口结束断射频进深睡；定时唤醒只拍照不联网；关摄像头、卸载 SD、睡眠能耗记账 | 常开态的主要负载是射频，不是 CPU | 24 h 平均 `90 mA → 6.98–10.94 mA`；15.20 h 实跑；窗口 `95 mA`；单次唤醒 `1.4–2.1 s` | [firmware.md](firmware.md) |
| F3 | [`esp32cam-capture-probe`](../firmware/esp32cam-capture-probe/README.md) | 不连 WiFi、不睡眠、按秒连拍写卡，把拍照占空比拉满 | 单次拍照只有 60–90 ms，秒级表抓不到 | 连拍 `0.13–0.16 A`（WiFi 关联下，偏保守的 P3 值） | [firmware.md](firmware.md) |

未落地：CPU 降频（收益上限 `≤0.42 mAh/天`，<0.25 %，但给 OV2640 XCLK / SDMMC 时序引入风险），取舍见 [firmware.md](firmware.md)。

## 2. 测量口径迭代

口径修正比新增数据更重要：同一块表、同一块板，换个口径结论能差 2 倍。

| 轮次 | 口径 | 改了什么 | 为什么必须改 | 明细 |
|---|---|---|---|---|
| M1 | 深睡电流 | 主口径由「表读 `0.00 A`」改为官方手册 `6 mA`，表上界 `10 mA` 并列 | 深睡低于表的 0.01 A 分辨率，表只能给上界，不能当实测 | [measurement.md](measurement.md) |
| M2 | 窗口段模型 | 模型 `165 mA` → 模型假设 `95 mA`（未实测；高估 1.7×） | 模型值不能直接进结论表，95 mA 也不是实测 | [measurement.md](measurement.md) |
| M3 | 基线 `POWER.CSV` | 固件模型 `45 mA` 不含 WiFi，实测 `90 mA`（2×）；`POWER.CSV` 只证明时间线，不能当电量 | 把模型日志当实测会虚报省电倍数 | [measurement.md](measurement.md) |
| M4 | 24 h 能量区间 | 10 个表盘锚点取 5 个（`0 → 64 → 8508 → 8567 → 16384 mWh`）建 4 段差分，异常断连段单列 | 只画端点会被断连段稀释成一个平均 | [measurement.md](measurement.md) |

## 3. 目录重构

| 时间 | 提交 | 改了什么 |
|---|---|---|
| 2026-11-11 | `f948018` | 按 `docs/` `firmware/` `measurement/` `evidence/` 分组，修正全部引用路径 |
| 本次 | — | `evidence/` → `process_logs/`，与提交模板对齐；`firmware/`、`measurement/`、`docs/` 不变 |
