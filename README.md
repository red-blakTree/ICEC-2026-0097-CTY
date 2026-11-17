# ICEC 2026 实验班入选测试 · 项目与课题提交

本仓库是实验班入选测试的完整提交物，分三个模块：**现场发现（两个课题）**、**20 天挑战（嵌入式项目）**、**AI 提问排障对话记录**。

每个课题都有独立报告、原始数据、可复跑的脚本和图表；报告中所有结论都标注了强弱与适用边界，未达成的部分写在各自「局限」一节，不做补白。

| 模块 | 内容 | 一句话结果 | 入口 |
|---|---|---|---|
| 01 现场发现 | 课题 3：2.4 GHz 无线信号测绘 | 8 个点位 / 40 轮测速 / 43 条 RSSI·SIR 读数，盲区只列候选、不定级 | [topic_3/README.md](01-Field-Discovery/topic_3/README.md) |
| 01 现场发现 | 课题 8：多姿态步态加速度判别 | 跨日盲测 94.5 %（记录级 9/9），并定位到「跨日失效源于非不变判决量」 | [topic_8/README.md](01-Field-Discovery/topic_8/README.md) |
| 02 20 天挑战 | ESP32-CAM 极致省电 | 实机 24 h 平均 `90 mA → 6.98–10.94 mA`（**8.2–12.9 倍**；手册 6 mA 口径 12.9 倍），三项均有交付（②含 24 h 连续日志 + 表实测能量；连续电压/电流曲线受 0.01 A 表限制） | [02-20Days-Challenge/README.md](02-20Days-Challenge/README.md) |
| 02 20 天挑战 | FreeRTOS V11.3.1 源码分析 | 以「一条链表 + 一种同步对象」为主线，附功耗专题 | [docs/FreeRTOS-V11.3.1-Source-Analysis.md](02-20Days-Challenge/docs/FreeRTOS-V11.3.1-Source-Analysis.md) |
| 03 AI 排障记录 | 4 张关键提问排障对话截图 | 课题 3 归因、课题 8 选型 / 对照 / 数据条件四类排障 | [03-AI-Collaboration/](03-AI-Collaboration/) |

---

## 1. 现场发现（01-Field-Discovery）

### 1.1 课题 3：教学楼、图书馆与宿舍 2.4 GHz 无线信号测绘

**问题**：用一台参数可控的热点做信号源，在遮挡 / 距离不同的点位上采集 RSSI、SIR 和端到端延迟 / 吞吐，找出候选盲区与边缘区，并在「同一热点位置 + 本地 1 m 零点」的组内估算相对衰减。

**做法**

- 信号源：Linux 笔记本热点（SSID `wireless_2.4G`，BSSID `a2:1e:09:30:b6:a3`，信道 7 / 2442 MHz，20 MHz，开放网络），频段 / 信道 / 功率全程可追溯。
- 测速：自写 Rust 测速服务 [`SpeedMeasurement/`](01-Field-Discovery/topic_3/SpeedMeasurement/README.md)（axum，局域网内 32 次 PING + 4 并发下载 / 上传各 8 s），手机浏览器直接测。
- 无线读数：PureHub 读点位级 RSSI / SIR，截图存档并逐条转录进 CSV，可回查。
- 点位：教学楼 5F、图书馆 1F、宿舍 6F 共 8 个测试点位 + 514 走廊 / 电梯口 / 617 桌面 3 个 1 m 本地零点。

**关键结果**

| 指标 | 结果 |
|---|---|
| 规模 | 8 点位 + 3 零点；40 轮测速；43 条无线读数 |
| 丢包 | 0 / 40 轮 |
| PING 中位 | 15.9–29.5 ms；P95 22.9–473.8 ms（仅电梯首轮超 100 ms） |
| 吞吐 | 下载 3.14–158.32 Mbps；有效上传 34.11–242.08 Mbps |
| 采用页 RSSI / SIR | −83 ~ −63 dBm / −35.3 ~ +4.2 dB |
| 可配对 ΔRSSI | 走廊 −2、−22 dB；电梯 −24 dB（概览）；宿舍 −19 dB（扫描口径，概览页反向，未定稿） |
| 走廊衰减指数 n | 近段 0.22 / 远段 2.86 / 全程 1.35 / 同会话 0.58 |

**结论强度**：这是描述性汇总。RSSI / SIR 是点位级快照（同一位置换页差 0–17 dB），4 个点位缺本地零点，距离多为目测或按教室间距推算，所以盲区只给候选（T5-03、T5-06 至少边缘；T5-07、L1-01 边缘；T5-05、D-02 不稳定），不做定级；跨会话的 n 值不可直接比较。这些限制和补测建议写在报告第 6 节、第 8 节。

**交付**：报告 [README.md](01-Field-Discovery/topic_3/README.md)（v5.2）· 原始记录 [data/results.json](01-Field-Discovery/topic_3/data/results.json) · 汇总 [measurements.csv](01-Field-Discovery/topic_3/data/measurements.csv) / [signal.csv](01-Field-Discovery/topic_3/data/signal.csv) · 分析图 [picture/analysis/](01-Field-Discovery/topic_3/picture/analysis/) · 采集脚本 [src/](01-Field-Discovery/topic_3/src/)。

### 1.2 课题 8：多姿态步态加速度判别（v1 → v7）

**问题**：只用一个手机加速度计，把「静止 / 平地慢走 / 快跑 / 上楼 / 下楼」从波形里判出来；难点不是同日准确率，而是**换一天还能不能判对**。

**数据**：本人采集，OnePlus Ace 5（PKG110，Android 16）+ Phyphox；加速度约 403 Hz、Gravity 约 201.6 Hz；5 组共 72 段，61 段 / 4431 个 8 s 窗参与评估，另有 11 段早期数据用于 v1 的 4 类验证。采集照片与 Phyphox 截图在 [picture/](01-Field-Discovery/topic_8/picture/)。

**方法主线**：逐样本重力解耦 → 选**对零偏与增益都不变**的判决量（稳健偏度 `rob_skew`）→ 分位标定 + 分层规则 → Viterbi 段级解码；v7 另加 RBF-SVM 监督学习分支，用于覆盖「不摆臂」等协议外持机方式。

**关键结果**

| 口径 | 结果 |
|---|---|
| 课题 4 类交付（v1，4 s 窗） | 346 / 355 窗 = 97.5 % |
| 5 类同集（v6） | 98.0 % |
| 留一记录（16 段 942 窗） | 95.86 % |
| 跨日盲测 2026-10-25（704 窗 / 9 段） | **94.5 %**（v6）、94.6 %（v5.1），记录级 9/9 |
| 三天复核标准段（1662 窗 / 23 段） | 92.7 %（v6）、93.3 %（v5.1），记录级 23/23 |
| 不摆臂段（1123 窗 / 13 段） | 27.6 %（v6 固定门限失效）；v7 留一天 91.9 % |
| 学习模型 v7（36 段） | 折外 94.2 %、留一天 94.0 %；外部 2026-10-25 92.8 % |

**最有价值的一步**：v2–v5 在同批数据上 97–99 %，换一天只剩 42.8–79.7 %。定位到根因是判下楼的 `ptn = (峰−谷)/(峰+谷)` 会随窗内残余零偏平移；只把这一个判决量换成 `rob_skew`，跨日就从 79.7 % 拉到 94.6 %。这说明瓶颈是**不变性**，不是特征数量或模型复杂度。

**边界（报告第 6 节有 13 条）**：一人一机（两组跨日仍是同一人同一手机）；「不摆臂」是协议外变量，引用跨日数字时只用标准段；2026-10-25 曾用于 v5.1 / v6 选型，对 v7 只能算外部抽样复核。

**交付**：报告 [README.md](01-Field-Discovery/topic_8/README.md)（v7.0）· 全部代码 [src/](01-Field-Discovery/topic_8/src/) · 逐窗结果与图 [output/](01-Field-Discovery/topic_8/output/) · 原始 CSV [output/v1/csv/](01-Field-Discovery/topic_8/output/v1/csv/)。

---

## 2. 20 天挑战（02-20Days-Challenge）

项目一按题面三项要求交付，交付索引、全量对照表与证据清单统一收在 [02-20Days-Challenge/README.md](02-20Days-Challenge/README.md)。

### 2.1 项目一：ESP32-CAM 极致省电

**题面三项与交付状态**

| 题面要求 | 本仓库交付 | 状态 |
|---|---|---|
| ① 优化前后各阶段实测电流对照表与视频 | P1–P6 对照表 + [current-comparison.csv](02-20Days-Challenge/measurement/current-comparison.csv) + 6 段录屏 | ✅ 五阶段都有读数；基线 P3 只有 1 s 视频表读，60–90 ms 未测 |
| ② 连续 24 h 以上电压 / 功耗时序 CSV | 3 份 `POWER.CSV` + [24 h 表实测能量区间](02-20Days-Challenge/measurement/24h-meter-series.csv) + 10 点表读 + 24 h 表端点 | 🟡 24 h 连续日志与表实测能量齐；连续电压/电流曲线受 0.01 A 表限制（见 02 README 2.5） |
| ③ 功耗预算推导模型与状态机源码 | [theory.py](02-20Days-Challenge/measurement/theory.py) + [power-budget-model.md](02-20Days-Challenge/docs/power-budget-model.md) + [state-machine.md](02-20Days-Challenge/docs/state-machine.md) + [powersave.ino](02-20Days-Challenge/firmware/esp32cam-powersave/powersave/powersave.ino) | ✅ 模型可复跑（verify.py 34 项自检），状态机源码/行号映射完整 |

**结论**：24 h 平均电流 **`90 mA → 6.98–10.94 mA`，8.2–12.9 倍**。10 倍要求是 `I_avg ≤ 9.0 mA`，代入三段式模型约等于深睡 `≤ 8.04 mA`；按官方手册的整板深睡 `6 mA @ 5 V` 得 `6.98 mA / 12.9×`（达标），按表的分辨率上界 `10 mA` 得 `10.94 mA / 8.2×`（不到 10 倍）。10 mA 是仪器上界，不是实测值；本板整板电流无法用万用表测量（无法从源头串入，见 [测量方案](02-20Days-Challenge/measurement/README.md) 第 6 节），深睡只能取「表上界 + 手册点值」这个区间。

**各阶段实测（USB 表串在 5 V 输入端，0.01 A 分辨率）**

| 阶段 | 基线 viewer | 省电版 powersave |
|---|---|---|
| P1 冷启动（上电 → 首拍） | `0.09–0.15 A`（约 6 s） | `0.09–0.15 A` |
| P3 拍照 + 写卡 | 1 s 表读 `0.10–0.13 A`（旁证）；60–90 ms 平均未测 | `0.13–0.16 A`（24 s / 10 次连拍放大占空比） |
| P4 深睡 | 不休眠 | 表 `≤ 0.01 A`；手册 `6 mA @ 5 V` |
| P5 单次唤醒（复位 → 再入睡） | 不适用 | `1.4–2.1 s` |
| P6 常开空闲（WiFi 关联） | `0.09 A / 5.04 V` | `0.09–0.10 A / 4.90 V` |

**24 h 数据怎么读（两个口径必须分开）**

- 基线健康段：`0.09 A` 直读 → `2.16 Ah / 10.8 Wh`，平均 `90 mA`。
- 2026-11-11 异常日：08:20 起约 12.6 h WiFi 断连，电流抬到 `0.18 A`，表累计 `≈16.38 Wh`、平均 `135.4 mA`；按 4 个实测区间差分见 [24h-meter-series.csv](02-20Days-Challenge/measurement/24h-meter-series.csv)，异常日单列、不进倍数表。
- 省电版没有 24 h 表曲线：深睡（手册 6 mA）低于 0.01 A 分辨率，且表在电流低于阈值时停表不累计；24 h 里约 99 % 时间是深睡，所以「直读深睡」在这块表上不成立。现有的是 [24 h 连续设备日志](02-20Days-Challenge/evidence/baseline-24h-meter-2026-11-10/POWER.CSV) + [表实测能量区间](02-20Days-Challenge/measurement/24h-meter-series.csv) + [15.20 h 省电版运行片段](02-20Days-Challenge/evidence/powersave-15h-2026-11-10/README.md)，以及窗口 / 唤醒段的实测值。
- 模型修正：窗口段模型按 `165 mA` 记，实测 `95 mA`，高估约 1.7 倍；基线 `POWER.CSV` 的 `45 mA` 固件模型不含 WiFi，实测 `90 mA` 是它的 2 倍。

**三个固件**

| 固件 | 形态 | 用途 |
|---|---|---|
| [esp32cam-viewer](02-20Days-Challenge/firmware/esp32cam-viewer/README.md) | 每小时一张 + WiFi 常开 + 网页查图 / 下载 `POWER.CSV` | 主基线：省电方案同样保留 WiFi，比的是「同样开 WiFi 谁更省」 |
| [esp32cam-powersave](02-20Days-Challenge/firmware/esp32cam-powersave/README.md) | 开机 15 min WiFi / 网页窗口，窗口结束断射频进深睡；定时唤醒只拍照不连 WiFi | 省电方案落地版，实机运行 |
| [esp32cam-capture-probe](02-20Days-Challenge/firmware/esp32cam-capture-probe/README.md) | 连拍放大占空比的拍照电流探针 | 让 60–90 ms 的拍照脉冲在秒级表上可读 |

**省电手段**：深睡占空比、WiFi 用完即关、定时唤醒不连 WiFi、摄像头 `esp_camera_deinit()` 后 PWDN 拉高并 `gpio_hold` 保持、睡眠前卸载 SD、把睡眠能耗记进账。题面三项策略里，外设断电控制与 Deep-Sleep 已落地；**时钟降频已定量评估、未启用**——活跃段合计 33.6–50.4 s/天，上限收益 `≤0.42 mAh/天`（<0.25 %），却会给 OV2640 XCLK / SDMMC 时序引入风险，取舍表见 [state-machine.md](02-20Days-Challenge/docs/state-machine.md) 第 6 节。硬件改造（换 LDO、MOSFET 切供电、去 LED）只写进方案，未实做。

**证据**：[evidence/](02-20Days-Challenge/evidence/) 下 6 组目录——两份 24 h 日志（[11-09](02-20Days-Challenge/evidence/baseline-24h-2026-11-09/README.md) / [11-10 表端点](02-20Days-Challenge/evidence/baseline-24h-meter-2026-11-10/README.md)）、[基线常开直读](02-20Days-Challenge/evidence/baseline-viewer-meter-2026-11-10/README.md)、[基线 P3 连拍](02-20Days-Challenge/evidence/baseline-viewer-meter-2026-11-16/README.md)、[省电版窗口录屏](02-20Days-Challenge/evidence/powersave-meter-2026-11-10/README.md)、[省电版 15.2 h 运行](02-20Days-Challenge/evidence/powersave-15h-2026-11-10/README.md)，含 6 段视频、表盘照片与 `manifest.sha256`。新增的 [24 h 区间 CSV](02-20Days-Challenge/measurement/24h-meter-series.csv) 由 [build_meter_series.py](02-20Days-Challenge/measurement/build_meter_series.py) 生成，[verify.py](02-20Days-Challenge/measurement/verify.py) 可一键复核 34 项。

> [docs/ESP32-CAM-Ultra-Low-Power-Solution.md](02-20Days-Challenge/docs/ESP32-CAM-Ultra-Low-Power-Solution.md) 是设计推演（架构、`sdkconfig`、陷阱清单、早期 `17.1 mA → 1.54 mA` 测算）。量化结论以实机口径为准，早期测算不再作为交付数字；三段式推导见 [power-budget-model.md](02-20Days-Challenge/docs/power-budget-model.md)，状态机见 [state-machine.md](02-20Days-Challenge/docs/state-machine.md)。

### 2.2 FreeRTOS Kernel V11.3.1 源码分析

以**设计原理**为主线通读官方发行版：整个内核只建立在一条双向链表（`list.c`）和一种同步对象（`queue.c`）之上，任务状态、延时、优先级轮转、事件等待都由它们演化而来。报告覆盖任务管理、队列与同步原语、软件定时器 / 事件组 / 流缓冲、移植层（PendSV 上下文切换、BASEPRI 临界区、首个任务的伪造异常返回）、内存管理，并单列「⚡ 功耗专题」把内核决策链与低功耗设计对应起来。所有结论标注 `文件:行号`，可回源码核对。

---

## 3. AI 提问排障对话记录（03-AI-Collaboration）

[03-AI-Collaboration/](03-AI-Collaboration/) 存了 4 张关键提问排障对话截图：我提出具体问题、把已知条件和数据边界一并给出，AI 定位根因并给修正方案，结论再回到报告和代码里核对。

| 截图 | 排障问题 | AI 回答与落地 |
|---|---|---|
| [1.png](03-AI-Collaboration/1.png) | 课题 3 走廊衰减怎么归因（T5-02 同走廊直线无遮挡、开口在 514 侧） | 删掉「过道开口泄漏」，改为「507 端附加损耗 / 驻波节点」，并给每 2 m 停一次的补测 SOP |
| [2.png](03-AI-Collaboration/2.png) | 课题 8「还能用什么更好的算法」 | 单特征 AUC 0.981 / 0.996，判断算法不是瓶颈；推荐先做 LR / 线性 SVM 对照，否决堆模型 |
| [3.png](03-AI-Collaboration/3.png) | 课题 8「四个基线做最小对照」 | v6 规则 vs LR / LinearSVC / RBF-SVM / RF；RBF-SVM 折外 94.2 %，收益来自绕开 v6 固定门限 |
| [4.png](03-AI-Collaboration/4.png) | 课题 8 测试数据的真实采集条件（口袋 / 他人手机 / 相同姿势） | 推翻 AI 先前「机型运动读数有偏」的判断，按真实条件重写结论 |

这些对话的共同点：提问时把已知条件和数据边界一起给出，AI 负责定位根因、给可执行的修正方案，能落回报告和代码的才留下；被数据推翻的判断按真实条件改写，而不是留着好看的解释（第 4 张）。

---

## 4. 环境与复现

**课题 3**

```bash
cd 01-Field-Discovery/topic_3
python3 src/build_dataset.py    # 重新生成 measurements.csv / signal.csv
python3 src/make_figures.py     # 重新生成 picture/analysis/（需要 matplotlib）

cd SpeedMeasurement
cargo run --release             # 测速服务，默认 0.0.0.0:8080，可用 PORT 覆盖
```

**课题 8**

```bash
cd 01-Field-Discovery/topic_8
python3 -m venv .venv
.venv/bin/pip install numpy matplotlib scikit-learn
export MPLCONFIGDIR=/tmp/mplcfg

.venv/bin/python src/v6/invariants.py    # 不变性自检，失败非零退出
.venv/bin/python src/v6/evaluate.py
.venv/bin/python src/blind_eval.py --test data/blind/2026-10-25 --out output/reports/blind_2026-10-25
```

实测环境：Python 3.14.8、numpy 2.5.4、matplotlib 3.11.2、scikit-learn 1.9.1。

**ESP32-CAM**

```bash
cd 02-20Days-Challenge
export ARDUINO_DIRECTORIES_DATA=$PWD/.arduino/data ARDUINO_DIRECTORIES_USER=$PWD/.arduino/user

./arduino-cli compile --fqbn esp32:esp32:esp32cam --build-path .arduino/build-viewer    firmware/esp32cam-viewer/viewer
./arduino-cli compile --fqbn esp32:esp32:esp32cam --build-path .arduino/build-powersave firmware/esp32cam-powersave/powersave

python3 measurement/theory.py                      # 24 h 预算（默认手册 6 mA）
python3 measurement/theory.py --i-sleep 10         # 表上界口径
python3 measurement/phases.py <串口日志> --summary  # 串口日志切 P1–P6
```

esp32 核心 3.3.12。烧录与看串口在本机走宿主机（`distrobox-host-exec`），板子带 DTR/RTS 自动复位（GPIO0 由 DTR 控制）。WiFi 凭据放在各固件目录的 `secrets.h`（已 gitignore）。

---

## 5. 目录结构

```
.
├── 01-Field-Discovery/
│   ├── topic_3/          # 课题 3：无线信号测绘（报告 / 数据 / 图 / 脚本 / Rust 测速服务）
│   └── topic_8/          # 课题 8：步态判别（报告 / 数据 / output / src / 采集照片）
├── 02-20Days-Challenge/
│   ├── README.md         # 项目交付索引：三项要求 / 对照表 / 24 h 数据 / 模型
│   ├── docs/             # 省电方案（测算 / 架构 / sdkconfig）与 FreeRTOS 源码分析
│   ├── firmware/         # viewer 主基线 / powersave 省电版 / capture-probe 拍照探针
│   ├── measurement/      # 电流对照表、24 h 预算模型、阶段切分、串口抓取
│   └── evidence/         # 6 组证据：时序 CSV、表盘照片、录屏与抽帧
└── 03-AI-Collaboration/  # 关键 AI 提问排障对话截图
```

## 6. 边界与未完成项

- 课题 3：RSSI / SIR 是点位级快照，`distance_m` 未实测，盲区只到候选；5F 平面图上的点位坐标叠加未产出。
- 课题 8：一人一机；「不摆臂」是协议外变量；2026-10-25 参与过 v5.1 / v6 选型，对 v7 不是完全未看过。
- ESP32-CAM 测量：P3 的 60–90 ms 平均电流测不到（秒级表），现有 `0.13–0.16 A` 是连拍放大值；深睡只有表上界 `≤ 10 mA` + 手册 `6 mA`；`POWER.CSV` 的电压字段是 `-1`（未接分压，按 5.0 V 记账，`Wh` 约有 ±2 % 误差）。
- ESP32-CAM 24 h：设备侧日志是固件模型值，不是表实测曲线；异常日（约 12.6 h 断连）单列、不进倍数表；省电版没有 24 h 表记录是仪器限制（低于 0.01 A 停表），要连续曲线需 INA219 一类低阻分流记录模块（万用表无法从源头串入）。
- ESP32-CAM 未做：换 LDO、MOSFET 切外设供电、去 LED（硬件项）；时钟降频（题面三策略唯一未落地，理由见第 2.1 节）；供电用充电宝/充电器代替电池（基线用充电宝、省电版用充电器，因为充电宝会把 5 mA 深睡判为“无负载”断电），续航为 1600 mAh 折算的预算值（非实测电池）。
