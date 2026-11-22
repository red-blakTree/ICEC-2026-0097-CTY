# ICEC 2026 实验班入选测试 · 项目与课题提交

## 0. 选题说明

**课题 3（2.4 GHz 无线信号测绘）**：用一台参数可控的热点当信号源，在遮挡与距离不同的点位上采 RSSI、SIR 和端到端延迟 / 吞吐。「信号差」这个日常判断能被拆成可测的量——同一位置的重复性、同一条走廊的距离衰减指数、隔墙与金属轿厢的净损耗；所以它值得做：结论要么可回查，要么就写进局限。

**课题 8（多姿态步态加速度判别）**：只用一个手机加速度计区分静止 / 慢走 / 快跑 / 上下楼梯。难点不在同日准确率，而在换一天还能不能判对；因此这份提交的主线是找一个对零偏和增益都不变的判决量，而不是堆特征或换模型。

**20 天挑战（ESP32-CAM 极致省电）**：要求给出优化前后各阶段电流对照、24 h 电压 / 功耗时序、预算推导模型与状态机源码。它把「改了什么」和「省了多少」用一块 USB 表直接连起来，每个数字都要有实测或明确口径。

**03 AI 排障记录**：不是独立课题，收的是上面三个模块推进时关键提问的对话截图，以及哪些判断最后回到了报告和代码里。

---

本仓库是实验班入选测试的完整提交物，分三个模块：**现场发现（两个课题）**、**20 天挑战（嵌入式项目）**、**AI 提问排障对话记录**。

每个课题都有独立报告、原始数据、可复跑的脚本和图表；报告中所有结论都标注强弱与适用边界，未达成的部分写在各自「局限」一节，不做补白。

| 模块 | 内容 | 一句话结果 | 入口 |
|---|---|---|---|
| 01 现场发现 | 课题 3：2.4 GHz 无线信号测绘 | 8 点位 × 3 轮 = **24 组主数据**（共 40 轮）/ 43 条 PureHub 读数（29 扫描 + 14 概览）；宿舍隔墙净损耗 13–19 dB、电梯轿厢 18–24 dB；走廊衰减指数四个口径 0.22 / 2.86 / 1.35 / 0.58；盲区只列候选 | [topic_3/README.md](01-Field-Discovery/topic_3/README.md) |
| 01 现场发现 | 课题 8：多姿态步态加速度判别 | 4 类交付 97.5 %（记录级 4/4）；5 类跨日 86.8–94.6 %（记录级全对）；2026-11-17 完全未参与选型，v7 94.5 %（v6 87.8 %），不摆臂段 v7 94.5 %（v6 37.1 %） | [topic_8/README.md](01-Field-Discovery/topic_8/README.md) |
| 02 20 天挑战 | ESP32-CAM 极致省电 | 24 h 平均 `90 mA → 6.98 mA`（**12.9 倍**，手册 6 mA 口径）/ `10.94 mA`（8.2 倍，表上界 10 mA）；「10 倍」临界是深睡 `≤ 8.04 mA`；三项均有交付，① 与 ② 各有受限项（见 2.1） | [02-20Days-Challenge/README.md](02-20Days-Challenge/README.md) |
| 02 20 天挑战 | FreeRTOS V11.3.1 源码分析 | 以「一条链表 + 一种同步对象」为主线，附功耗专题 | [docs/FreeRTOS-V11.3.1-Source-Analysis.md](02-20Days-Challenge/docs/FreeRTOS-V11.3.1-Source-Analysis.md) |
| 03 AI 排障记录 | 7 张关键提问排障对话截图 | 课题 3 归因、课题 8 选型 / 对照 / 采集协议三类排障 | [03-AI-Collaboration/](03-AI-Collaboration/README.md) |

---

## 1. 现场发现（01-Field-Discovery）

### 1.1 课题 3：教学楼、图书馆与宿舍 2.4 GHz 无线信号测绘

**问题**：用一台参数可控的热点做信号源，在遮挡 / 距离不同的点位上采集 RSSI、SIR 和端到端延迟 / 吞吐，找出候选盲区与边缘区，并在「同一热点位置 + 本地 1 m 零点」的组内估算相对衰减。

**做法**

- 信号源：Linux 笔记本热点（SSID `wireless_2.4G`，BSSID `a2:1e:09:30:b6:a3`，信道 7 / 2442 MHz，20 MHz，开放网络，发射功率 22.00 dBm），频段 / 信道 / 功率全程可追溯。
- 测速：自写 Rust 测速服务 [`SpeedMeasurement/`](01-Field-Discovery/topic_3/SpeedMeasurement/README.md)（axum；每轮 32 次 PING 取后 29 次、4 并发下载 / 上传各 8 s），手机浏览器直接测。
- 无线读数：PureHub 1.0.0-beta.58 读点位级 RSSI（概览页）/ SIR（扫描页），截图存档并逐条转录，`signal.csv` 的每一行都能用 `source_file` 回查。
- 点位：教学楼 5F、图书馆 1F、宿舍 6F 共 8 个测试点位（覆盖走廊近 / 远、转角、电梯轿厢、楼梯间、金属防火门、玻璃隔断、混凝土 + 瓷砖隔墙 7 类遮挡特征）+ 3 个 1 m 本地零点。距离由平面图 + 500 mm 瓷砖推算（单开间 8.5 m），**不是卷尺实测**。

**关键结果**

| 指标 | 结果 |
|---|---|
| 规模 | 24 组主数据（`delivery_24.csv`，record id 2–37）+ 16 轮补测 / 零点 = 40 轮；43 条 PureHub 读数 = 测试点位 28 + 零点 13 + 2 条走廊距离阶梯 |
| 丢包 | 0 / 40 轮（1160 次请求 0 失败，真实失败率低于约 0.3 %；单轮 0 % 只能表述为低于约 10 %） |
| PING 中位 / P95 | 15.9–29.5 ms / 22.9–473.8 ms（仅电梯首轮超 100 ms）；抖动 3.07–115.14 ms |
| 吞吐 | 下载 3.14–158.32 Mbps；有效上传 34.11–242.08 Mbps（2 个失败轮不计） |
| RSSI / SIR | 28 条测试点位读数：−83 ~ −63 dBm / −35.3 ~ +4.2 dB（43 条里 27 条带 SIR） |
| 低于 −70 dBm | 6 / 8 个点位：T5-03 −83、T5-05 −81、T5-06 −80、D-02 −74、T5-07 −73、L1-01 −72 dBm |
| 可配对 ΔRSSI | 走廊 8.5 m −2 dB、42.5 m −22 dB（扫描页）；电梯 −24 dB；宿舍隔墙 −19 dB（扫描）/ +2 dB（概览，符号相反，未定稿） |
| 走廊衰减指数 n | 近段 0.22 / 远段 2.86 / 全程 1.35 / 同会话 0.58（三点最小二乘另得 1.29） |
| 墙体材质（可配对） | 10 cm 混凝土 + 瓷砖净损耗 13–19 dB（扫描口径）；金属轿厢 18–24 dB（概览口径）；均与文献量级一致 |
| 多径规律 | 6 条（波导增强、近场饱和、快衰落 0–17 dB、深衰落长尾、吞吐非单调、频率选择性），逐条标强度 |
| 换页重复性 | 同一点位换页差 0–17 dB，半极差 8.5 dB（是重复性上限，不是置信区间） |

**结论强度**：报告第 12 节把局限分成四类——采样与配对（影响最大）、几何与材质、证据与记录、外推边界。RSSI / SIR 是**点位级快照**（每点位 1–2 个时刻的 2–6 张截图，3–7 轮测速共用同一点位读数），4 个点位缺本地零点，单次快照重复性上限已有 8.5 dB 半极差，阈值 −70 / −80 dBm 是工程经验值，所以**盲区只列候选、不做定级**；走廊 n 只在「本走廊几何 + 本热点高度」内成立，远段 2.86 只在 10-24 那批出现，同会话阶梯只给 0.58，跨会话不可直接比较。

**交付**：报告 [README.md](01-Field-Discovery/topic_3/README.md)（v6.0）· 原始记录 [raw_data/results.json](01-Field-Discovery/topic_3/raw_data/results.json) · **24 组明细 [delivery_24.csv](01-Field-Discovery/topic_3/raw_data/delivery_24.csv)** · 汇总 [measurements.csv](01-Field-Discovery/topic_3/raw_data/measurements.csv) / [signal.csv](01-Field-Discovery/topic_3/raw_data/signal.csv) · 分析图 [picture/analysis/](01-Field-Discovery/topic_3/picture/analysis/)（`fig1_rssi_sir` · `fig2_latency_throughput` · `fig3_distance_profile` · `fig4_corridor` · `fig5_paired_delta`）· 采集脚本 [src/](01-Field-Discovery/topic_3/src/)。

### 1.2 课题 8：多姿态步态加速度判别（v1 → v7）

**问题**：只用一个手机加速度计，把「静止 / 平地慢走 / 快跑 / 上下楼梯」从波形里判出来（课题要求 4 类，把上下楼梯拆成上楼 / 下楼作 5 类扩展）；难点不是同日准确率，而是**换一天还能不能判对**。

**数据**：本人采集，OnePlus Ace 5（PKG110，Android 16）+ Phyphox 1.2.1；加速度约 403 Hz、Gravity 约 201.6 Hz；**6 组 85 段**：

| 数据组 | 日期 | 段数 | 8 s 窗 | 角色 |
|---|---|---|---|---|
| `data_1` | 10-23 | 11 | —（4 s 窗 1058） | v1 的 4 类验证 |
| `data_2` | 10-24 | 7 | 302 | 主标定集 |
| `2026-10-24` | 10-24 | 9 | 640 | 标定集 |
| `2026-10-25` | 10-25 | 9 | 704 | 跨日 1（曾参与 v5.1 / v6 方向选择） |
| `10-30`、`10-31`、`11-01` | 10-30～11-01 | 36 | 2785 | 跨日 2；v7 训练集 |
| `2026-11-17` | 11-17 | 13 | 1078 | 跨日 3（完全未参与任何选型） |

**方法主线**：逐样本重力解耦（`a_v` / `a_h`）→ 首尾清洗 → 8 s 窗 / 1 s 步长（4 类为 4 s / 0.5 s）→ 选**对零偏与增益都不变**的判决量（稳健偏度 `rob_skew`）→ 分位标定 + 分层规则 → Viterbi 段级解码；v7 另加 RBF-SVM（10 维特征）监督学习分支，用于覆盖「不摆臂」这类协议外持机方式。

**关键结果**

| 口径 | 结果 |
|---|---|
| 课题 4 类交付（v1，4 s 窗） | 346 / 355 = 97.5 %，记录级 4/4（`data_1` 全量 1049 / 1058 = 99.15 %，11/11） |
| 5 类同集（v6） | 98.0 %（`data_2`）、98.9 %（2026-10-24） |
| 留一 16 段（v6） | 95.86 %（903 / 942 窗） |
| 跨日 2026-10-25（704 窗 / 9 段） | v6 **94.5 %**、v5.1 94.6 %，记录级 9/9 |
| 三天标准段 10-30～11-01（1662 窗 / 23 段） | v6 92.7 %、v5.1 93.3 %，记录级 23/23 |
| 2026-11-17 标准段（623 窗 / 8 段） | v6 87.8 %、**v7 94.5 %**，记录级 8/8 |
| 2026-11-17 不摆臂段（455 窗 / 5 段） | v6 37.1 %、**v7 94.5 %**，记录级 2/5 → 5/5 |
| 学习模型 v7 | 5 折折外 94.2 %（不摆臂 94.0 %）；留一天 94.0 %（标准 95.4 %、不摆臂 91.9 %）；外部 10-25 92.8 %、11-17 94.5 % |

**最有价值的一步**：v2–v5 在同批数据上 97–99 %，换一天只剩 42.8–79.7 %。定位到根因是判下楼的 `ptn = (峰−谷)/(峰+谷)` 会随窗内残余零偏平移；只把这一个判决量换成 `rob_skew`（并改用算术中点），跨日就从 79.7 % 拉到 94.6 %。这说明瓶颈是**不变性**，不是特征数量或模型复杂度。

**边界（报告第 7 节 9 条）**：一人一机（v7 换人换机必须重训重验）；4 类 97.5 % 是同集标定结果，只能当拟合度；2026-10-25 曾用于 v5.1 / v6 方向选择，2026-11-17 完全未参与；「不摆臂」是协议外变量，引用跨日数字时只用标准段；窗重叠 7/8（704 窗去重叠只剩 90），引用以记录级为主；照片只覆盖 `data_1` / `data_2`。

**交付**：报告 [README.md](01-Field-Discovery/topic_8/README.md)（v1 → v7）· 4 份原始 CSV [output/v1/csv/](01-Field-Discovery/topic_8/output/v1/csv/) · 8 张图 [output/v1/figures/](01-Field-Discovery/topic_8/output/v1/figures/) · 版本对比图 A–F [output/compare/figures/](01-Field-Discovery/topic_8/output/compare/figures/) · 逐窗结果 [output/reports/](01-Field-Discovery/topic_8/output/reports/) 与 [output/svm/](01-Field-Discovery/topic_8/output/svm/) · 全部代码 [src/](01-Field-Discovery/topic_8/src/)（v1–v7 + 对比作图）· 采集照片与截图 [picture/](01-Field-Discovery/topic_8/picture/)。

---

## 2. 20 天挑战（02-20Days-Challenge）

项目一按三项要求交付，交付索引、全量对照表与证据清单统一收在 [02-20Days-Challenge/README.md](02-20Days-Challenge/README.md)。

### 2.1 项目一：ESP32-CAM 极致省电

**三项交付状态**

| 交付项 | 内容 | 状态 |
|---|---|---|
| ① 优化前后各阶段实测电流对照表与视频 | P1–P6 对照表 + [current-comparison.csv](02-20Days-Challenge/measurement/current-comparison.csv) + 6 段录屏（合计约 3.8 min） | 🟡 对照表与视频齐；基线 P3 只有 1 s 视频表读、无 WiFi 拍照段未测，逐项见 [02 README 交付状态](02-20Days-Challenge/README.md) |
| ② 连续 24 h 以上电压 / 功耗时序 CSV | 3 份 `POWER.CSV` + [24 h 表实测能量区间](02-20Days-Challenge/measurement/24h-meter-series.csv) + 10 个表盘点 + 5 点能量曲线 | 🟡 24 h 数据齐套（设备日志 + 表实测区间）；省电版连续电压 / 电流曲线受 0.01 A 表限制不可得（见 02 README 2.5） |
| ③ 功耗预算推导模型与状态机源码 | [theory.py](02-20Days-Challenge/measurement/theory.py) + [power-budget-model.md](02-20Days-Challenge/docs/power-budget-model.md) + [state-machine.md](02-20Days-Challenge/docs/state-machine.md) + [powersave.ino](02-20Days-Challenge/firmware/esp32cam-powersave/powersave/powersave.ino) | ✅ 模型可复跑（`verify.py` 34 项自检 + 7 个回归测试），状态机源码 / 行号映射完整 |

**图**：[图 1 表盘对比](02-20Days-Challenge/docs/figures/fig1-meter-compare.png) · [图 2 24 h 能量曲线](02-20Days-Challenge/docs/figures/fig2-24h-energy.png) · [图 3 占空比](02-20Days-Challenge/docs/figures/fig3-duty-cycle.png) · [图 4 电量预算](02-20Days-Challenge/docs/figures/fig4-energy-budget.png) · [图 5 分组电流](02-20Days-Challenge/docs/figures/fig5-stage-current.png)（源文件与口径见 [SOURCES.md](02-20Days-Challenge/docs/figures/SOURCES.md)）。

**结论**：24 h 平均电流 **`90 mA → 6.98 mA`（12.9 倍，手册 6 mA 口径）**；按表分辨率上界 10 mA 记则 `10.94 mA`（8.2 倍）。10 倍要求的判据是 `I_avg ≤ 9.0 mA`，代入三段式模型 `I_avg ≈ 1.05 + 0.989 × I_sleep` 得临界深睡 `≤ 8.04 mA`。10 mA 是仪器分辨率上界，不是实测值；本板整板电流无法用万用表从源头串入（见 [测量方案](02-20Days-Challenge/measurement/README.md) 第 6 节），深睡只能取「表上界 + 手册点值」这个区间，两种口径并列给出：6 mA → `6.98 mA / 12.9 倍 / 9.5 天`；10 mA → `10.94 mA / 8.2 倍 / 6.1 天`；全保守（窗口 90 mA、其余 10 mA）→ `10.83 mA / 8.3 倍`。

**各阶段实测（USB 表串在 5 V 输入端，0.01 A 分辨率）**

| 阶段 | 基线 viewer | 省电版 powersave | 性质 |
|---|---|---|---|
| P1 冷启动（上电 → 首拍） | `0.09–0.15 A`（约 6 s） | `0.09–0.15 A`（约 6 s） | 瞬态，无稳定均值 |
| P2 窗口空闲（仅省电版） | 不适用（基线无窗口） | `0.09–0.10 A / 4.90 V`（95 mA） | 窗口段直读 + 录屏 |
| P6 常开空闲（WiFi 关联） | `0.09 A / 5.04 V` | 不适用（窗口外深睡） | 基线端直读 |
| P6 开网页（浏览器翻图） | `0.11–0.14 A` | `0.12–0.19 A`，峰值 `0.22 A` | 直读 + 录屏 |
| P3 拍照 + 写卡 | 1 s 表读 `0.10–0.13 A`（旁证）；60–90 ms 平均未测 | `0.13–0.16 A`（24 s / 10 次连拍放大占空比） | 两种口径不互换 |
| P4 深睡 | 不休眠 | 表 `≤ 0.01 A`；手册 `6 mA @ 5 V` | 表只给上界 |
| P5 单次唤醒（复位 → 再入睡） | 不适用 | `1.4–2.1 s` | 串口 `[CAP]` / `[SLEEP]` 时间戳 |
| 24 h 平均 | `90 mA`（健康段直读） | `6.98–10.94 mA`（推算） | 见第 2、3 节 |

**24 h 数据怎么读（两个口径必须分开）**

- 基线健康段：`0.09 A / 5.04 V` 直读 → `2.16 Ah / 10.8 Wh`，平均 `90 mA`。
- 2026-11-11 异常日：08:20 起约 12.6 h WiFi 断连，电流抬到 `0.18 A`，表累计 `≈16.38 Wh`、等效平均 `135.4 mA @5.04 V`（`power-budget-model.md` 记作 ≈136 mA，同一事实两种取整）；按 4 个实测区间差分见 [24h-meter-series.csv](02-20Days-Challenge/measurement/24h-meter-series.csv)，异常日单列、不进倍数表。
- 省电版没有 24 h 表曲线：深睡（手册 6 mA）低于 0.01 A 分辨率，且表在电流低于阈值时停表不累计；24 h 里约 99 % 时间是深睡，所以「直读深睡」在这块表上不成立。现有的是 [24 h 连续设备日志](02-20Days-Challenge/process_logs/baseline-24h-meter-2026-11-10/POWER.CSV) + [表实测能量区间](02-20Days-Challenge/measurement/24h-meter-series.csv) + [15.20 h 省电版运行片段](02-20Days-Challenge/process_logs/powersave-15h-2026-11-10/README.md)，以及窗口 / 唤醒段的实测值。
- 表盘点与建曲线不是一回事：`meter-readings.csv` 有 10 个锚点，图 2 与区间 CSV 只用其中 5 个（`0 → 64 → 8508 → 8567 → 16384 mWh`）。
- 模型修正：窗口段模型按 `165 mA` 记，实测 `95 mA`，高估约 1.7 倍；基线 `POWER.CSV` 的 `45 mA` 固件模型不含 WiFi，实测 `90 mA` 是它的 2 倍。

**三个固件**

| 固件 | 形态 | 用途 |
|---|---|---|
| [esp32cam-viewer](02-20Days-Challenge/firmware/esp32cam-viewer/README.md) | 每小时一张 + WiFi 常开 + 网页查图 / 下载 `POWER.CSV` | 主基线：省电方案同样保留 WiFi，比的是「同样开 WiFi 谁更省」 |
| [esp32cam-powersave](02-20Days-Challenge/firmware/esp32cam-powersave/README.md) | 开机 15 min WiFi / 网页窗口，窗口结束断射频进深睡；定时唤醒只拍照不连 WiFi | 省电方案落地版，实机运行 |
| [esp32cam-capture-probe](02-20Days-Challenge/firmware/esp32cam-capture-probe/README.md) | 连拍放大占空比的拍照电流探针 | 让 60–90 ms 的拍照脉冲在秒级表上可读 |

**省电手段**：深睡占空比、WiFi 用完即关、定时唤醒不连 WiFi、摄像头 `esp_camera_deinit()` 后 PWDN 拉高并 `gpio_hold` 保持、睡眠前卸载 SD、把睡眠能耗记进账。三项策略里，外设断电控制与 Deep-Sleep 已落地；**时钟降频已定量评估、未启用**——活跃段合计 33.6–50.4 s/天，上限收益 `≤0.42 mAh/天`（<0.25 %），却会给 OV2640 XCLK / SDMMC 时序引入风险，取舍表见 [state-machine.md](02-20Days-Challenge/docs/state-machine.md) 第 6 节。硬件改造（换 LDO、MOSFET 切供电、去 LED）只写进方案，未实做。

**证据**：[process_logs/](02-20Days-Challenge/process_logs/) 下 6 组目录——两份 24 h 日志（[11-09](02-20Days-Challenge/process_logs/baseline-24h-2026-11-09/README.md) / [11-10 表端点](02-20Days-Challenge/process_logs/baseline-24h-meter-2026-11-10/README.md)）、[基线常开直读](02-20Days-Challenge/process_logs/baseline-viewer-meter-2026-11-10/README.md)、[基线 P3 连拍](02-20Days-Challenge/process_logs/baseline-viewer-meter-2026-11-16/README.md)、[省电版窗口录屏](02-20Days-Challenge/process_logs/powersave-meter-2026-11-10/README.md)、[省电版 15.2 h 运行](02-20Days-Challenge/process_logs/powersave-15h-2026-11-10/README.md)，含 6 段视频（合计约 3.8 min）、表盘照片与 `manifest.sha256`。新增的 [24 h 区间 CSV](02-20Days-Challenge/measurement/24h-meter-series.csv) 由 [build_meter_series.py](02-20Days-Challenge/measurement/build_meter_series.py) 生成，[verify.py](02-20Days-Challenge/measurement/verify.py) 可一键复核 34 项（`--manifest` 为 40 项，多校验 6 份 SHA256）。

> [docs/ESP32-CAM-Ultra-Low-Power-Solution.md](02-20Days-Challenge/docs/ESP32-CAM-Ultra-Low-Power-Solution.md) 是设计推演（架构、`sdkconfig`、陷阱清单、早期 `17.1 mA → 1.54 mA` 测算，数值为社区典型值）。量化结论以实机口径为准，早期测算不再作为交付数字；三段式推导见 [power-budget-model.md](02-20Days-Challenge/docs/power-budget-model.md)，状态机见 [state-machine.md](02-20Days-Challenge/docs/state-machine.md)。

### 2.2 FreeRTOS Kernel V11.3.1 源码分析

以**设计原理**为主线通读官方发行版：整个内核只建立在一条双向链表（`list.c`）和一种同步对象（`queue.c`）之上，任务状态、延时、优先级轮转、事件等待都由它们演化而来。报告覆盖任务管理、队列与同步原语、软件定时器 / 事件组 / 流缓冲、移植层（PendSV 上下文切换、BASEPRI 临界区、首个任务的伪造异常返回）、内存管理，并单列「⚡ 功耗专题」把内核决策链与低功耗设计对应起来。所有结论标注 `文件:行号`，可回源码核对。

---

## 3. AI 提问排障对话记录（03-AI-Collaboration）

[03-AI-Collaboration/](03-AI-Collaboration/README.md) 存了 7 张关键提问排障对话截图：我提出具体问题、把已知条件和数据边界一并给出，AI 定位根因并给修正方案，结论再回到报告和代码里核对。

| 截图 | 排障问题 | AI 回答与落地 |
|---|---|---|
| [1.png](03-AI-Collaboration/1.png) | 课题 3 走廊衰减怎么归因（T5-02 同走廊直线无遮挡、开口在 514 侧） | 删掉「过道开口泄漏」，改为「507 端附加损耗 / 驻波节点」，并给每 2 m 停一次的补测 SOP |
| [2.png](03-AI-Collaboration/2.png) | 课题 8「还能用什么更好的算法」 | 单特征 AUC 0.981 / 0.996，判断算法不是瓶颈；推荐先做 LR / 线性 SVM 对照，否决堆模型 |
| [3.png](03-AI-Collaboration/3.png) | 课题 8「四个基线做最小对照」 | v6 规则 vs LR / LinearSVC / RBF-SVM / RF；RBF-SVM 折外 94.2 %，收益来自绕开 v6 固定门限 |
| [4.png](03-AI-Collaboration/4.png) | 课题 8 测试数据的真实采集条件（口袋 / 他人手机 / 相同姿势） | 推翻 AI 先前「机型运动读数有偏」的判断，按真实条件重写结论 |
| [5.png](03-AI-Collaboration/5.png) | 课题 8「这个加速度是含 g 的」——含 g 就能直接用吗 | 含 g 只保证瞬时 `‖a‖ ≈ 9.8`，手持摆动时窗均值会落到 4.2 / 12.6 / 14.5；用 0.5 s 均值轨迹（图 9）证明问题不在「有没有 g」，而在「这段数据能不能定出 g 的方向」，据此引入逐样本重力解耦 |
| [6.png](03-AI-Collaboration/6.png) | 课题 8「补录要怎么做」——要补什么、怎么补 | 给出 Phyphox 同步录加速度 + 陀螺仪的 SOP、每段开头 10 s 静止的标定理由、20 段 / 15 分钟的最小补录清单（2 人 × 2 机 × 5 状态 × 2 次）与「统一平端手机」替代方案 |
| [7.png](03-AI-Collaboration/7.png) | 课题 8「Phyphox 里勾哪些传感器」 | 勾加速度计 + 重力传感器、不勾陀螺仪（手机自带重力方向，比陀螺仪积分更稳），采样率保持最快；导出前静置看重力三轴模长是否 ≈ 9.8，CSV 须同时出现 `Acceleration` 与 `Gravity` 两组列 |

这些对话的共同点：提问时把已知条件和数据边界一起给出，AI 负责定位根因、给可执行的修正方案，能落回报告和代码的才留下；被数据推翻的判断按真实条件改写，而不是留着好看的解释（第 4 张）。前 4 张偏算法选型与结论复核，后 3 张转到**采集协议**：从「换什么算法」改问「怎么让数据支持这个算法」——含 g 的数据怎么解耦、补录流程怎么设计、传感器勾哪几项。

---

## 4. 环境与复现

**课题 3**

```bash
cd 01-Field-Discovery/topic_3
python3 src/build_dataset.py    # 重新生成 measurements.csv / signal.csv
python3 src/build_delivery.py   # 由 measurements.csv + results.json 生成 delivery_24.csv（校验 24 组）
python3 src/make_figures.py     # 重新生成 picture/analysis/ 的 5 张图（需要 matplotlib）

cd SpeedMeasurement
cargo run --release             # 测速服务，默认 0.0.0.0:8080，可用 PORT 覆盖
```

**课题 8**

```bash
cd 01-Field-Discovery/topic_8
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export MPLCONFIGDIR=/tmp/mplcfg

.venv/bin/python src/v1/gait_analysis.py         # 4 类交付：逐窗结果 + 图 1–8
.venv/bin/python src/v1/make_figures.py
.venv/bin/python src/v1/make_delivery_figure.py   # 图 8 交付核对
.venv/bin/python src/v6/invariants.py            # 不变性自检，失败非零退出
.venv/bin/python src/v6/evaluate.py
.venv/bin/python src/svm/train_svm.py            # v7：5 折折外 + 留一天
.venv/bin/python src/svm/blind_svm.py --input raw_data/blind/2026-10-25
.venv/bin/python src/svm/blind_svm.py --input raw_data/blind/2026-11-17
.venv/bin/python src/make_comparison_figures.py  # 图 A–F
```

实测环境：Python 3.14.8（11-17 复跑用 3.13.16）、numpy 2.5.4、matplotlib 3.11.2、scikit-learn 1.9.1。

**ESP32-CAM**

```bash
cd 02-20Days-Challenge
export ARDUINO_DIRECTORIES_DATA=$PWD/.arduino/data ARDUINO_DIRECTORIES_USER=$PWD/.arduino/user

./arduino-cli compile --fqbn esp32:esp32:esp32cam --build-path .arduino/build-viewer    firmware/esp32cam-viewer/viewer
./arduino-cli compile --fqbn esp32:esp32:esp32cam --build-path .arduino/build-powersave firmware/esp32cam-powersave/powersave

python3 measurement/theory.py                      # 24 h 预算（默认手册 6 mA）
python3 measurement/theory.py --i-sleep 10         # 表上界口径
python3 measurement/build_meter_series.py --check  # 24 h 区间 CSV 只校验不重写
python3 measurement/verify.py                      # 34 项自检
python3 measurement/verify.py --manifest           # 40 项，额外校验 6 份 SHA256
python3 -m unittest discover -s measurement -p 'test_*.py'   # 7 个回归测试
python3 measurement/phases.py <串口日志> --summary  # 串口日志切 P1–P6
```

esp32 核心 3.3.12。烧录与看串口在本机走宿主机（`distrobox-host-exec`），板子带 DTR/RTS 自动复位（GPIO0 由 DTR 控制）。WiFi 凭据放在各固件目录的 `secrets.h`（已 gitignore）；`arduino-cli` 二进制（36 MB）与 `.arduino/` 本地数据目录同样不入库。

---

## 5. 目录结构

```
.
├── README.md            # 个人简介与选题说明
├── 01-Field-Discovery/  # 阶段一：报告、照片与 raw_data/
│   ├── topic_3/         # 课题 3：无线信号测绘（报告 / raw_data / picture / src / Rust 测速服务）
│   └── topic_8/         # 课题 8：步态判别（报告 / raw_data / output 逐版本结果 / src v1–v7 / picture）
├── 02-20Days-Challenge/ # 阶段二：源码、process_logs/ 与 iterations/
│   ├── README.md        # 项目交付索引：三项要求 / 对照表 / 24 h 数据 / 模型
│   ├── docs/            # 省电方案（测算 / 架构 / sdkconfig / 图 1–5）与 FreeRTOS 源码分析
│   ├── firmware/        # 阶段二源码：viewer 主基线 / powersave 省电版 / capture-probe 拍照探针
│   ├── measurement/     # 电流对照表、24 h 预算模型、区间 CSV、阶段切分、自检与回归测试
│   ├── process_logs/    # 过程记录：时序 CSV、表盘照片、6 段录屏与抽帧
│   └── iterations/      # 迭代记录：固件 F1–F3 与测量口径 M1–M4
└── 03-AI-Collaboration/ # 关键 AI 提问排障对话记录（README + 7 张截图）
```

---

## 6. 边界与未完成项

- 课题 3：RSSI / SIR 是点位级快照（每点位 1–2 个时刻的 2–6 张截图，3–7 轮测速共用），43 条读数里只有 27 条带 SIR；`distance_m` 未实测，距离由平面图 + 500 mm 瓷砖推算；只有 1D 走廊标定，5F 平面图上的点位坐标叠加未产出；盲区只到候选，T5-03（507 后门）缺位置照。
- 课题 8：一人一机；4 类 97.5 % 属同集拟合度；2026-10-25 参与过 v5.1 / v6 方向选择（11-17 完全未参与）；「不摆臂」是协议外变量；窗重叠 7/8（704 窗去重叠只剩 90）；照片证据只覆盖 `data_1` / `data_2`。
- ESP32-CAM 测量：P3 的 60–90 ms 平均电流测不到（秒级表），现有 `0.13–0.16 A` 是连拍放大值；深睡只有表上界 `≤ 10 mA` + 手册 `6 mA`；`POWER.CSV` 的电压字段是 `-1`（未接分压，按 5.0 V 记账，`Wh` 约有 ±2 % 误差）。
- ESP32-CAM 24 h：设备侧日志是固件模型值，不是表实测曲线；异常日（约 12.6 h 断连）单列、不进倍数表；省电版没有 24 h 表记录是仪器限制（低于 0.01 A 停表），要连续曲线需 INA219 一类低阻分流记录模块（万用表无法从源头串入）。
- ESP32-CAM 未做：换 LDO、MOSFET 切外设供电、去 LED（硬件项）；时钟降频（三策略唯一未落地，理由见第 2.1 节）；供电用充电宝 / 充电器代替电池（基线用充电宝、省电版用充电器，因为充电宝会把 5 mA 深睡判为「无负载」断电），续航为 1600 mAh 折算的预算值（非实测电池）。
