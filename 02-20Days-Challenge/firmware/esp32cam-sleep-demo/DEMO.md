# 睡眠模式演示：现场流程与预检

> 配套固件：[README.md](README.md)；本页只讲「怎么演示、看什么、出问题怎么退」。
> 口径：2 min 会话是 24 h 的压缩示意，不是真实占空比；省电数字仍以 powersave 的 24 h 实测为准。
> 当前限制：`POWER.CSV` 的电流是模型值；`normal` / `deep` 的表锚点、录屏、原始日志尚未入库；`modem` / `light` 未实测（测法见 §0，归档见 §5）。

## 0. 表只能记总量时怎么测

USB 表只给累计 mWh，不给连续曲线；用**锚点差分**，不需要连续记录：

1. 每个模式开始记 `E0 / t0`，结束记 `E1 / t1`（抄数或拍照）；
2. `I_avg = (E1 − E0) / ((t1 − t0) / 3600) / V`；
3. normal / modem 的 2 min 约 15–17 mWh，1 mWh 分辨率够用；
4. light / deep 若表不累计（显示 `0.00 A`），记 `≤10 mA` 上界，不拿 0 mWh 算平均；
5. 只有整场一个总也能用：normal 和 modem 分两次会话各记一个总；至少做 normal + deep 两组。

**时间只够一组时，做 normal 2 min + deep 2 min**；`modem` / `light` 未实测，跑通前不要写结果；四模式全跑是加分项，不是交付门槛。

## 1. 演示前 5 分钟

- 网络：手机热点或 2.4 GHz AP，RSSI ≥ −60 dBm；确认 `secrets.h` 的静态 IP / 网关与热点同网段。
- 供电：USB 表串在 5 V 输入；USB-TTL 只接 TX / RX / GND（不接 5 V / 3V3）。
- 数据：清空旧照片和 `POWER.CSV`（`POST /admin/reset`），确认 `/api.json` 的 `count=0`。
- 烧录：容器内编译，宿主机执行 [`flash_demo.sh`](flash_demo.sh)；串口只做短时抓取（DTR/RTS 会复位板子）。
- 页面：打开 `http://<静态IP>/`，确认 4 个按钮、`POWER.CSV` 链接、`/api.json` 正常。

## 2. 四模式顺序与时间（modem / light 未实测）

| 顺序 | 模式 | 页面 | 预计耗时 | 看点 |
|---|---|---|---|---|
| 1 | modem | 全程可达 | 约 2 min | 网页不掉线；5 张 30 s 间隔 |
| 2 | light | 约 80 s 不可达 | 约 2 min | 页面「设备睡眠中」→ 自动恢复 |
| 3 | deep | 约 90 s 不可达 | 约 2 min | 每次唤醒 `uptime` 归零；照片仍写入 |
| 4 | normal | 全程可达 | 约 2 min | 温度最高；建议短跑或放最后 |

- 4 轮 + 切换约 10 min；时间紧只跑 normal + deep（或 modem + deep），其余用截图或录屏补。
- 每轮固定 5 张（0/30/60/90/120 s）；light / deep 中途离线是设计结果，不是故障。

## 3. 每步看什么

- 页面：`session` 从 `idle → running → idle`，`shots_done` 到 5；照片墙新增 5 张。
- `/api.json`：`mode` / `mode_label` / `shots_done` / `files`；light / deep 恢复后同一 IP 可访问。
- `POWER.CSV`：`MODE_*` → 5×`CAPTURE` → 4×`*_SLEEP` / `*_WAKE` → `SESSION_END`；normal / modem 没有 `*_SLEEP`。
- 表：normal / modem 读稳定段；light / deep 通常读 `0.00 A`，只能给 ≤10 mA 上界。5 V 侧浅睡可能被 AMS1117 掩盖，不要写「浅睡比深睡省」。
- 温度：页面 `temp_c`；normal 会话峰约 57.8 °C，超过 65 °C 先停。

## 4. 回退

- WiFi 连不上：换手机热点，改 `secrets.h` 的静态 IP / 网关，重烧；或先跑 normal / modem。
- 页面卡住：断电或按 EN，照片和 `POWER.CSV` 仍在 SD；重新打开页面。
- 串口打开后板子停在下载态：关串口，按 EN 复位；验证以页面 / API 为准。
- 清空失败：会话中返回 409，先 `POST /stop` 或等会话结束。

## 5. 记录与归档（待补）

- 录：至少 normal + deep 各一段 30–60 s，页面和表盘同框；四模式全跑可各录一段（`modem` / `light` 先跑通再写结果）；`/api.json` 快照；串口日志；`POWER.CSV`；页面截图。
- 存：`process_logs/sleep-demo-4modes-<date>/`，附 `manifest.sha256` 和 README；在 [02 README §6](../../README.md) 登记。
- 当前仓库还没有这组证据；上面的表读 / 录屏需要上硬件后补。

### 锚点表模板

> `modem` / `light` 未实测，跑完再填；不要先填数。

| 模式 | E0 (mWh) | t0 | E1 (mWh) | t1 | ΔE (mWh) | 时长 (s) | I_avg (mA) |
|---|---|---|---|---|---|---|---|
| normal | | | | | | | |
| modem | | | | | | | |
| light | | | | | | | ≤10（上界） |
| deep | | | | | | | ≤10（上界，手册 6 mA） |

## 6. 演示话术边界

- 电流是模型值，表读才能证明省电；没有表读就说「行为演示」。
- 2 min ≠ 24 h；15 min 窗口 + 1 h 深睡是 powersave 的口径。
- normal 用 `WIFI_PS_NONE`，不是 viewer 的 90 mA 基线；跨固件比较只看同条件模式差。
- 深睡 6 mA 来自手册，表只能给 ≤10 mA 上界；两个口径并列，不合并。
- `modem` / `light` 未实测，不要讲已验证；只讲代码路径。
