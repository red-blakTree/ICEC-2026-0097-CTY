# 课题 3 · 教学楼与宿舍无线信号盲区测绘实验方案

> 版本 v2.1 ｜ 信号源：Linux 笔记本热点（NetworkManager）｜ 规模：8 个点位 × 3 次重复

## 1. 目标与问题

**目标**：以 Linux 笔记本热点作为固定、可控的信号源，在教学楼与宿舍选取 8 个遮挡特征不同的点位，采集信号强度（RSSI）、信干比（SIR）与端到端延迟，识别覆盖盲区与边缘区，比较遮挡类型对信号和延迟的影响。

**研究问题**

- RQ1：8 个点位的 RSSI 与 SIR 分布如何？哪些点位低于可用阈值？
- RQ2：RSSI / SIR 与延迟（中位数、P95、丢包）是否同向劣化？
- RQ3：走廊距离、转角、电梯口、隔墙、卫生间、楼板等遮挡特征，各自造成多大相对衰减？

**成功标准**

1. 8 个点位 × 3 轮数据完整，字段无缺失（含 RSSI 与 SIR）；
2. 产出覆盖标注图与一份可复现报告；
3. 热点重启、BSSID 变化、100% 丢包等异常均有记录与处理说明；
4. 频段、信道、热点位置等关键设置可追溯。

## 2. 实验设计

| 项目 | 设计 |
|---|---|
| 类型 | 现场观察性测量，单因素（点位 / 遮挡特征）重复 3 次 |
| 自变量 | 点位及其相对热点的遮挡特征（开阔、距离、转角、金属井道、楼板、隔墙、管道） |
| 因变量 | RSSI（dBm）、SIR（dB）、PING 中位数、P95、抖动、丢包率 |
| 控制变量 | 同一 Linux 笔记本与热点参数、热点位置 / 高度 / 朝向、同一手机、同一握持 / 高度 / 朝向、同一时段 |

### 2.1 点位设计（8 个，待填）

8 个点位覆盖教学楼与宿舍的典型遮挡位置。先完成现场踏勘，再把楼栋、楼层、位置、遮挡特征与到热点的距离填入下表。每个测量区域布置一次热点，位置固定；若两栋楼分别布置热点，跨栋数据不直接比较。

| 编号 | 楼栋 / 楼层 | 位置 | 遮挡特征 | 与热点的关系 | 备注 |
|---|---|---|---|---|---|
| P1 |  |  |  |  |  |
| P2 |  |  |  |  |  |
| P3 |  |  |  |  |  |
| P4 |  |  |  |  |  |
| P5 |  |  |  |  |  |
| P6 |  |  |  |  |  |
| P7 |  |  |  |  |  |
| P8 |  |  |  |  |  |

选点原则：可安全停留 ≥ 3 分钟；位置可复现（有明确参照物）；避开人流高峰与施工区域；8 个点尽量覆盖不同的遮挡类型与不同距离。

> 距离按热点实际覆盖能力调整：2.4G 热点在走廊通常可到 15–25 m，隔墙后明显缩短；5G 在本机只能开 UNII-3（149–165 信道），频率最高、穿墙最差，覆盖通常只有 2.4G 的六到七成，隔墙后更短。若预实验发现某点完全不可达，保留该点作为「盲区」样本，不删除。

### 2.2 重复与顺序

- 每个点位连续测 3 轮，轮间静置 30 s；
- 按点位表顺序 P1→P8 采集，记录每轮开始时间；
- 3 轮内若热点重启或 BSSID 变化，该点数据作废并重测，不与其他点合并。

## 3. 工具与设置

### 3.1 工具分工

| 数据 | 工具 | 记录项 |
|---|---|---|
| 信号强度 / 信干比 | PureHub | RSSI（dBm）、SIR（dB）、SSID、BSSID、频段 / 信道 |
| 延迟 | SpeedMeasurement（自建） | PING 中位数、P95、抖动、丢包率 |

> **工具选择与 SNR 的替代**：实测 PureHub 与 Cellular-Z 在同一位置、同一时刻读到的 RSSI 相同，因此本方案只使用 PureHub 采集信号强度。**未找到能在手机上测 SNR 的应用**，PureHub 只提供 SIR（信干比），故本实验以 SIR 代替 SNR；报告中需注明二者不可等同，SIR 绝对值不与文献中的 SNR 直接比较。

**组网方式**：Linux 笔记本同时充当热点与 SpeedMeasurement 服务端，手机连接该热点，访问 `http://<热点网关IP>:8080` 运行测速。延迟是「手机 → 笔记本」的 RTT，只经过热点空口与笔记本协议栈，不含互联网，链路干净且可控。

**SpeedMeasurement 口径**：每次发 32 次 `GET /api/ping`，丢弃前 3 次连接开销，输出中位数、P95、抖动与丢包率。

### 3.2 热点与设备设置（Linux）

**笔记本 / 热点**

- 记录发行版 / 内核、无线网卡型号与驱动、NetworkManager 版本、热点频段 / 信道 / SSID / BSSID / 网关 IP；
- **频段选择**：主测 2.4G（绕射与穿墙更好，适合覆盖测绘），固定信道 1 / 6 / 11 中较空闲者；
- 5G 受监管要求只能使用 UNII-3（149–165 信道），无法选 36–48；该频段频率最高、穿墙最差，覆盖明显短于 2.4G。5G 只做近距离对照（建议 2–3 个点），作为**独立一轮实验**，点位距离缩短，不与 2.4G 混算；不要尝试修改监管域绕过限制。
- 用 `iw reg get` 与 `iw list` 确认本机允许的 5G 信道与带宽，记录监管域和实际可用信道；热点固定 149 / 153 / 157 / 161 中可用的一个信道。
- 同一轮只用一个频段；切换频段视为新一轮实验，需重新记录热点参数并重测基准点；
- 用 NetworkManager 共享模式建热点（`ipv4.method shared`），无需 Internet；先用 `iw list` 确认网卡支持 AP 模式与目标信道，用 `iw reg get` 确认监管域允许；
- 固定 MAC / BSSID（`wifi.cloned-mac-address permanent`），关闭其他 WiFi 的自动连接，避免热点被切走；
- 关闭 WiFi 省电（`iw dev <if> set power_save off`），减少延迟抖动；
- 笔记本接电源，禁用挂起 / 休眠 / 合盖休眠（`systemd-inhibit` 或电源设置）；
- 防火墙放行 8080/TCP（firewalld / ufw / nftables）；热点位置、屏幕角度、朝向在整个测量期间不变。

**手机**

- 同一部手机；**关闭移动数据**（不只是「WLAN 助理」），防止热点无 Internet 时自动切到蜂窝；
- 关闭 VPN、蓝牙；亮度固定、屏幕常亮，电量 > 50%，测试期间不充电；
- 手机壳、握持手、手机朝向保持一致；
- 记录手机型号、系统版本、App 版本。

**PureHub**

- 固定使用同一版本；读数前静置约 10 s，等待 RSSI / SIR 稳定；
- 每次同时记录 RSSI 与 SIR（概览页给 RSSI，扫描页给 SIR），并核对 SSID / BSSID / 频段 / 信道；
- 若 SIR 字段暂不出数，记录原始界面截图，不以估算值代替；SIR 在界面上显示为负值，按原样抄录，不做符号修正。

## 4. 测量流程（SOP）

### 4.1 准备（每个测量区域开始前）

1. 选热点位置：有电源、平稳、不挡路，记录高度与朝向；
2. 确认网卡与能力：`nmcli device status` 查网卡，`iw list` 看是否支持 AP 模式与目标信道，`iw reg get` 确认监管域；
3. 避免干扰与切换：关闭其他 WiFi 的自动连接，`sudo iw dev <if> set power_save off`；
4. 建热点：用 NetworkManager 共享模式（`ipv4.method shared`），固定 SSID、密码、频段、信道与 MAC，命令见附录；
5. 启动 SpeedMeasurement；手机连上热点并关闭移动数据，打开 `http://<网关IP>:8080` 预跑一次；
6. 防火墙放行 8080/TCP，记录热点 SSID、BSSID、频段、信道、网关 IP 与笔记本位置照片。

### 4.2 单点单轮（约 60 s）

1. 到达点位，站定，手机置于胸前约 1.2 m 高度、固定朝向，静置 30 s；
2. 确认手机仍连在热点上（PureHub 中核对 SSID / BSSID），未被切到移动数据；
3. 打开 PureHub，记录 RSSI、SIR、SSID、BSSID、频段 / 信道；
4. 立即打开 SpeedMeasurement，点「开始测试」，完成后记录 PING、P95、抖动、丢包；
5. 标签填 `点位-轮次`（如 `P1-R2`）并保存；静置 30 s，进入下一轮。

> 延迟取结果卡片中的延迟字段；下载 / 上传字段不参与本实验分析，仅为让延迟结果正常显示与落盘。

### 4.3 单点收尾

- 3 轮完成后核对 BSSID 与热点状态，检查极差是否过大（见第 7 节）；
- 拍摄点位照片（含手机朝向），记录现场异常（人流、门开闭、施工、电梯运行）。

### 4.4 收工

- 导出并备份 `data/results.json` 与截图；
- 当天完成数据初检：缺项、时间戳、BSSID、明显异常。

## 5. 记录字段与命名

- 命名：`点位-轮次`，如 `P1-R1`、`P8-R3`；
- 一行 = 一次测量（长表），字段如下。

| 字段 | 说明 |
|---|---|
| point_id | P1–P8 |
| building / floor / location | 楼栋、楼层、位置描述 |
| obstruction | 遮挡特征 |
| distance_m | 与笔记本热点的直线距离（估） |
| ssid / bssid / band / channel | 热点连接信息 |
| round | 1–3 |
| time | 本轮开始时间 |
| rssi_dbm | PureHub 读数 |
| sir_db | PureHub 扫描页读数（信干比） |
| ping_ms / p95_ms / jitter_ms / loss_pct | SpeedMeasurement 读数 |
| temp / battery | 手机温度与电量（可选） |
| note | 人流、门状态、热点状态、异常 |

CSV 模板：

```csv
point_id,building,floor,location,obstruction,distance_m,ssid,bssid,band,channel,round,time,rssi_dbm,sir_db,ping_ms,p95_ms,jitter_ms,loss_pct,note
P1,,,,,,,,,,,,,,,,,,
```

## 6. 数据处理与判定

### 6.1 预处理

- 每个点位 3 轮：RSSI、SIR 取中位数并给出极差；延迟取 PING / P95 / 抖动中位数，丢包取均值；
- BSSID 变化、100% 丢包、手机过热等先标记，必要时补测；
- 不剔除「看起来不好」的数据；异常值保留并说明原因。

### 6.2 盲区判定（多指标交叉）

| 等级 | RSSI | P95 | 丢包率 |
|---|---|---|---|
| 正常 | > −70 dBm | < 50 ms | < 2% |
| 边缘 | −80 ~ −70 dBm | 50 ~ <100 ms | 2% ~ <5% |
| 盲区 | < −80 dBm | ≥ 100 ms | ≥ 5% |

规则：**任一指标落入「盲区」即列为盲区候选**，需结合 3 轮重复与现场情况确认，单次读数不得判定。阈值参考 WLAN 覆盖设计的常用经验值（−70 dBm 可用、−80 dBm 接近不可用），报告中需说明这是工程判据而非强制标准。

SIR 作为解释性指标，用于说明「RSSI 尚可但延迟变差」是否由同频干扰等因素造成，不单独作为定级依据。注意本实验测的是 SIR 而非 SNR，二者不可等同。

### 6.3 分析内容

1. 每点 3 轮 RSSI、SIR 柱状图（含散点 / 极差）与延迟箱线图；
2. 相对衰减 ΔRSSI = 点位中位数 − 参照点中位数；参照点优先取点位表中的开阔基准点，未指定时取 8 点中 RSSI 中位数最高者，并在报告中注明；
3. RSSI 与 P95、SIR 与 P95 的散点图（8 点），计算 Spearman 秩相关作为探索性指标（n = 8，不作因果结论）；
4. 覆盖标注图：在平面图上用三色标出 8 个点；**不做连续热力图**（8 个点不足以插值，避免过度解读）；
5. 遮挡类型对比：走廊距离、转角、金属井道、隔墙、管道、楼板各点的 ΔRSSI、SIR 与延迟。

## 7. 质量控制

- **热点状态**：每点前确认热点开启、手机连接同一 SSID / BSSID、移动数据关闭；
- **位置固定**：笔记本位置、高度、朝向、屏幕角度在整个测量期间不变；不放在金属表面；
- **电源与睡眠**：接电源，用 `systemd-inhibit` 阻止挂起，关闭合盖休眠与屏幕节能；
- **干扰**：2.4G 固定信道，记录同频热点数量；实验期间不改信道；
- **重复性**：RSSI 极差 > 6 dBm 或延迟变异系数 > 30% 时，加测 1–3 轮并记录原因；
- **异常**：热点重启、BSSID 变化、手机掉线均记录；该点作废重测；
- **安全**：不阻挡通道，不进入机房 / 弱电间，不影响他人网络。

## 8. 进度安排

| 阶段 | 内容 | 时间 |
|---|---|---|
| D1 | 热点调试、点位踏勘与填写、预实验 | 0.5 天 |
| D2 | P1–P4 采集 | 0.5 天 |
| D3 | P5–P8 采集 | 0.5 天 |
| D4 | 补测与数据初检 | 0.5 天 |
| D5 | 统计、绘图、覆盖标注图 | 1 天 |
| D6 | 报告与复现说明 | 1 天 |

## 9. 风险与预案

| 风险 | 影响 | 预案 |
|---|---|---|
| 网卡 / 驱动不支持 AP 模式，或 5G 信道被监管域禁用 | 热点起不来 / 5G 不可用 | 先 `iw list`、`iw reg get`；退回 2.4G 或换信道，记录实际能力 |
| NetworkManager 自动连回其他 WiFi | 热点掉线 | 其他连接设为 `autoconnect no`；热点配置 `autoconnect no`；每点前确认 |
| 防火墙 / 路由未放行 8080 | 手机打不开 | firewalld / ufw 放行；用手机浏览器验证 |
| 挂起、合盖或 WiFi 省电 | 断网或延迟抖动 | `systemd-inhibit` 阻止挂起；关闭合盖休眠；`iw dev <if> set power_save off` |
| 热点无 Internet 导致手机切蜂窝 | 延迟测到移动网络 | 关闭移动数据与 WLAN 助理；每点前核对 SSID |
| 2.4G 信道拥挤 / 干扰 | RSSI 与延迟抖动 | 预扫信道选较空闲者并固定；记录同频热点数 |
| 热点发射功率低、覆盖短 | 远端不可达 | 视为盲区样本保留；必要时调整点位距离并记录 |
| 5G 只能开 UNII-3（149–165） | 高频段穿墙差、可选信道少 | 5G 只做近距离对照；固定 149 / 153 / 157 / 161 中可用者；不与 2.4G 比较绝对值 |
| 手机在远端掉线 | 数据缺失 | 标「不可达」并补测 1 次确认 |
| MAC / BSSID 随机化 | 无法识别热点 | NetworkManager 设 `wifi.cloned-mac-address permanent`；记录实际 BSSID |

## 10. 交付物

1. 原始数据：`data/results.json`、汇总 CSV、点位照片；
2. 覆盖标注图：按点位所在楼层绘制；
3. 实验报告：目的、方法、结果、盲区清单、限制与建议；
4. 复现说明：发行版 / 内核 / 无线网卡驱动、NetworkManager、热点参数（频段、信道、SSID、BSSID、网关 IP）、手机与 App 版本、点位与时段。

## 11. 限制说明（写进报告）

- 8 个点位、每点 3 次属于小样本现场测量，结论只针对本次热点配置、设备与点位，不外推到其他设备或场景；
- RSSI、SIR 受手机型号、握持、人体遮挡与 App 平滑策略影响，绝对值有 ±2–3 dB 量级不确定性；SIR 不能当作 SNR 使用；
- 延迟是到笔记本的 RTT，不含其他网络回程与互联网时延；
- 单时段采集无法区分「位置差」与「时段负载高」；如需区分，应在高峰与低峰各采一轮；
- 本机 5G 受监管限制只能开 UNII-3（149–165 信道），频率最高、衰减快、绕射弱，同样点位的 RSSI 与盲区范围会明显差于 2.4G；不要与 2.4G 的 dBm 绝对值直接比较，也不要把结论外推到低信道 5G 或其他地区。

## 附录：Linux 热点启动（NetworkManager）

以下命令以网卡 `wlan0`、2.4G 信道 6 为例；先用 `nmcli device status` 换成实际网卡名。

```bash
# 1. 能力检查：是否支持 AP、目标信道是否允许
iw list | sed -n '/Supported interface modes/,/Band/p'
iw reg get

# 2. 关闭 WiFi 省电，避免延迟抖动
sudo iw dev wlan0 set power_save off

# 3. 创建热点配置（共享模式，无需 Internet）
nmcli connection add type wifi ifname wlan0 con-name sm-hotspot autoconnect no ssid Hotspot-Study
nmcli connection modify sm-hotspot 802-11-wireless.mode ap
nmcli connection modify sm-hotspot 802-11-wireless.band bg
nmcli connection modify sm-hotspot 802-11-wireless.channel 6
nmcli connection modify sm-hotspot wifi.cloned-mac-address permanent
nmcli connection modify sm-hotspot wifi-sec.key-mgmt wpa-psk
nmcli connection modify sm-hotspot wifi-sec.psk '12345678'
nmcli connection modify sm-hotspot ipv4.method shared
nmcli connection modify sm-hotspot ipv6.method ignore

# 4. 启动
nmcli connection up sm-hotspot

# 5. 查地址（手机访问 http://<该地址>:8080）
ip -4 addr show wlan0

# 6. 放行 8080（按发行版二选一）
sudo firewall-cmd --add-port=8080/tcp
sudo ufw allow 8080/tcp
```

5G 对照时把频段 / 信道改为 `band a` + `channel 149`（本机监管域仅允许 UNII-3，按 `iw list` 选 149 / 153 / 157 / 161 中可用者），并确认该信道对 AP 可用；不要修改监管域绕过限制。

实验期间不要 `nmcli connection up` 其他 WiFi；结束后用 `nmcli connection down sm-hotspot` 关闭热点。若 NetworkManager 版本较老不支持 `band` / `channel` 属性，改用 `nmcli device wifi hotspot band bg channel 6 ssid ... password ...` 或 hostapd，并记录实际方案。
