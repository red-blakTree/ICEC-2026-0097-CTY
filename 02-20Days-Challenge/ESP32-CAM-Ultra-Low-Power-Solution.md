# ESP32-CAM 极致省电实现方案

> 目标硬件：AI-Thinker ESP32-CAM（ESP32-D0WDQ6 双核 + OV2640 + microSD）
> 软件基础：ESP-IDF（内核为其内置 FreeRTOS）
> 工作模式：定时拍照（周期 ≥ 数十秒），数据 WiFi 上传 + SD 卡本地缓存兼有
>
> ⚠ **所有电流数值为社区典型值/量级估计，必须用实测校准**。ESP32-CAM 存在多个改版（LDO 型号、LED 是否有、PSRAM 容量不同），板间差异可达数倍。文档中每一处需要实测的地方都以 `【实测】` 标注。

---

## 一、结论先行：功耗由谁主导？

在做任何优化前，必须认清一个事实：**在"数十秒"这类周期下，决定平均电流的不是睡眠电流，而是每次唤醒的工作阶段。**

平均电流公式：

$$I_{avg} = \frac{I_{active} \times t_{active} + I_{sleep} \times (T - t_{active})}{T}$$

三个可调量、三个杠杆：

| 杠杆 | 现状 | 优化后 | 对平均电流的影响 |
|---|---|---|---|
| **① 工作阶段耗时 `t_active`** | 4.5 s（含 WiFi 连接） | 0.6 s（只存 SD）/ 带 BSSID 直连的快速上传 | **最大** |
| **② 工作阶段电流 `I_active`** | ~130-180 mA | 降频 + 降低 TX 功率 | 中等 |
| **③ 睡眠电流 `I_sleep`** | **5 mA**（AMS1117 静态电流主导） | 0.08 mA（换 LDO + 切断外设） | **周期越长越关键** |

**关键判断**：`I_sleep` 只有在周期足够长时才开始主导。短周期下改硬件收益有限，长周期下改硬件是决定性的——详见第二章测算。

---

## 二、功耗测算：改造 vs 不改造

### 2.1 工作阶段拆解（单次唤醒）

| 阶段 | 典型电流 | 典型耗时 | 优化手段与可省时间 |
|---|---|---|---|
| WiFi 扫描 + 关联 + DHCP | ~120 mA | **2.5 s** | 静态 IP（省 1 s）+ **BSSID+channel 直连跳过扫描（省 1.5 s）** |
| 摄像头 init + JPEG 捕获 | ~180 mA | **0.4 s** | 掉电后必须重新 init（这是硬件改造的代价） |
| SD 卡写入（~100 KB） | ~50 mA | **0.15 s** | 用 4-bit SDMMC 模式 |
| WiFi 上传（~100 KB，局域网） | ~150 mA | **1.5 s** | 降 TX 功率；或改为批量上传 |
| **合计（每次都上传）** | 加权 ~135 mA | **~4.5 s** | |
| **合计（只存 SD）** | 加权 ~130 mA | **~0.6 s** | **这就是最大杠杆** |

> 峰值电流参考：ESP32 射频 TX 瞬时可达 ~300 mA，摄像头捕获瞬时 ~200 mA。设计电源时必须按峰值留余量（否则会掉电重启），但续航计算用平均值。

### 2.2 睡眠电流

| 配置 | `I_sleep` | 构成 |
|---|---|---|
| 原板不改 | **~5 mA** | AMS1117 静态电流（典型 5 mA，最大 11 mA）占绝对主导，加 LED、SD 卡座漏电 |
| 仅软件优化（PWDN 拉高 + GPIO isolate） | ~3-4 mA | 摄像头省掉一部分，但 LDO 静态电流不变 |
| **换 LDO + MOSFET 切断摄像头/SD + 去 LED** | **~0.05-0.15 mA** | 目标值，需 `【实测】` 确认 |

### 2.3 平均电流与续航对比（2000 mAh 锂电，按可用 80% = 1600 mAh·h 计算）

> 下表是「T=60 s 每次都上传」的旧测算口径，用于说明各杠杆的相对大小；
> 当前项目的基线形态以第五章 P0 为准。

| 场景 | `I_avg` | 续航 | 相对基线 |
|---|---|---|---|
| **基线**：T=60 s，每次都上传，不改硬件 | **17.1 mA** | **~3.9 天** | — |
| T=60 s，每次都上传，**改硬件** | 12.6 mA | ~5.3 天 | ↓26% |
| T=60 s，**只存 SD，每小时批量上传 1 次**，不改硬件 | 6.4 mA | ~10.4 天 | ↓63% |
| **推荐组合**：T=60 s，只存 SD，每小时批量上传，**改硬件** | **1.54 mA** | **~43 天** | **↓91%** |
| T=300 s，只存 SD，每小时上传，改硬件 | 0.28 mA | ~238 天 | ↓98% |
| T=600 s，只存 SD，每天上传 1 次，改硬件 | 0.13 mA | ~513 天 | 受自放电主导 |

**读表要点**：

1. **改硬件的收益高度依赖周期**：T=60 s 每次都上传时只有 26%，但配合"降低上传频率"后达 91%。
2. **"每次都上传"是最大的浪费**。把上传改为每小时/每天批量一次，单项就把 17.1 mA 降到 6.4 mA——**这一步零硬件成本，收益却超过改硬件**。
3. **周期超过约 10 分钟后，电池自放电与 LDO 静态电流成为主导**，继续优化 MCU 已无意义。

### 2.4 硬件改造的收益/成本对比（供你决策）

| 改造项 | 成本 | 收益（T=60 s，每小时上传场景） | 风险 |
|---|---|---|---|
| **换 LDO**（AMS1117 → HT7333/MCP1700，静态 1~4 µA） | 元件 ~¥1 + 焊接 | 5 mA → ~1 mA 级，**收益最大** | 需确认原板 LDO 封装（多为 SOT-223），焊接难度中等 |
| **P-MOSFET 切断摄像头 VCC**（GPIO 控制） | 元件 ~¥0.5 | 再降至 ~0.2 mA；顺带消除 SCCB 上拉漏电 | 需割线，摄像头每次唤醒要重新 init（+0.4 s） |
| **MOSFET 切断 SD 卡 VCC** | 同上 | 省 0.1~数 mA（视卡而定） | 插卡时收益明显；需注意卡的上电初始化时间 |
| **移除板载电源 LED** | 0 | 省 1~3 mA | 无风险，最简单，**建议无论如何都做** |
| 仅软件（PWDN + RTC GPIO isolate） | 0 | 5 mA → ~3-4 mA，**受 LDO 拖累无法更低** | 无 |

> **决策建议**：
> - 若目标续航 **< 2 周**：只做软件优化 + 移除 LED 即可，不必动 LDO。
> - 若目标续航 **> 1 个月**：必须换 LDO，否则 5 mA 的静态电流就是硬上限（1600/5 ≈ 13 天，且这还是不含工作阶段的理论值）。

---

## 三、软件架构（ESP-IDF）

### 3.1 核心设计：Deep sleep 占空比 + 分层上传

选择 **deep sleep 占空比**路线（CPU 完全断电，唤醒即从复位重启），因为定时拍照无需保持 WiFi 关联。

```
         ┌──────────────────────────────────────────────┐
         │  上电 / deep sleep 唤醒                      │
         └──────────────────┬───────────────────────────┘
                            ▼
              ┌──────────────────────────┐
              │ 读取 RTC_DATA_ATTR 状态  │  ← 唤醒原因、待上传计数、
              │ (不清零，跨 deep sleep)  │     上次上传时间、重试次数
              └────────────┬─────────────┘
                           ▼
              ┌──────────────────────────┐
              │ 打开摄像头电源 (MOSFET)  │
              │ init → 捕获 JPEG         │  ~0.4 s
              └────────────┬─────────────┘
                           ▼
              ┌──────────────────────────┐
              │ 写入 SD 卡（本地缓存）   │  ~0.15 s
              │ 断电摄像头               │
              └────────────┬─────────────┘
                           ▼
                  ┌─────────────────┐
                  │ 到批量上传时机？ │
                  └───┬─────────┬───┘
                    否│         │是
                      ▼         ▼
      ┌──────────────────┐  ┌──────────────────────────┐
      │ 进入 deep sleep  │  │ 启动 WiFi（BSSID 直连）  │ ~1.0 s
      │ 设置 RTC 定时唤醒│  │ 批量上传 SD 中未上传文件 │
      └──────────────────┘  │ 标记已上传 → 关 WiFi     │
                            └────────────┬─────────────┘
                                         ▼
                                ┌────────────────┐
                                │ 进入 deep sleep│
                                └────────────────┘
```

### 3.2 关键实现点

**① 用 RTC 内存保存状态，避免重复初始化**

```c
RTC_DATA_ATTR static uint32_t s_pending_uploads;   /* 待上传文件数 */
RTC_DATA_ATTR static uint32_t s_last_upload_epoch; /* 上次上传时间 */
RTC_DATA_ATTR static uint32_t s_boot_count;        /* 用于调试 */
```

**② 唤醒原因判定**

```c
esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
/* ESP_SLEEP_WAKEUP_TIMER = 定时拍照；ESP_SLEEP_WAKEUP_EXT0/1 = 传感器中断 */
```

**③ WiFi 快速连接（省掉扫描，这是最有价值的单项优化）**

```c
wifi_config_t cfg = {
    .sta = {
        .ssid = WIFI_SSID,
        .password = WIFI_PASS,
        .bssid_set = true,              /* 关键：锁定 AP 的 BSSID */
        .channel = WIFI_CHANNEL,        /* 关键：跳过全信道扫描 */
        .scan_method = WIFI_FAST_SCAN,
        .sort_method = WIFI_CONNECT_AP_BY_SIGNAL,
        .threshold.rssi = -70,
    },
};
/* 配合静态 IP，省掉 DHCP */
/* 配合静态 IP，省掉 DHCP（v5.x 用 esp_netif_set_ip_info，旧版为 tcpip_adapter_set_ip_info） */
esp_netif_ip_info_t ip = { ... };
```
> 实测可把连接时间从 ~2.5 s 压到 ~0.6-1.0 s，收益显著。

**④ 摄像头供电控制（若做了硬件改造）**

```c
#define CAM_PWR_GPIO  GPIO_NUM_13   /* 自选空闲脚，注意避开引脚冲突表 */
gpio_set_level(CAM_PWR_GPIO, 1);     /* P-MOSFET 栅极：低=导通，按电路定 */
vTaskDelay(pdMS_TO_TICKS(50));       /* 等电源稳定 */
esp_camera_init(&config);
/* ... 捕获 ... */
esp_camera_deinit();
gpio_set_level(CAM_PWR_GPIO, 0);
```

**⑤ 进入 deep sleep 前：防止引脚漏电（极易漏掉，能省几百 µA）**

```c
/* 1. 未使用的 GPIO 全部隔离，避免通过外部上拉/下拉漏电 */
rtc_gpio_isolate(GPIO_NUM_12);
rtc_gpio_isolate(GPIO_NUM_15);
/* 2. 控制 MOSFET 的 GPIO 必须保持电平，否则外设又被上电 */
gpio_hold_en(CAM_PWR_GPIO);
gpio_deep_sleep_hold_en();

esp_sleep_enable_timer_wakeup(PERIOD_US);
esp_deep_sleep_start();
```

> **`rtc_gpio_isolate()` 和 `gpio_hold_en()` 是 deep sleep 漏电的两个主要来源，务必逐脚检查。**

**⑥ 任务结构（避免"高频唤醒"破坏省电）**

ESP-IDF 中 `esp_pm` 的 light sleep 时长由"最近的任务阻塞超时 + 最近的 esp_timer"决定。在 deep sleep 方案里这一点不直接适用，但**只要设备处于活跃阶段，同样的规律成立**：

- **禁止 `vTaskDelay(1)` 轮询**；改用事件/信号量驱动。
- **用 `esp_timer` 替代 FreeRTOS 软件定时器**做长周期调度，并设 `skip_unhandled_events = true`（跳过无效唤醒）。
- 上传任务与 SD 写入任务用队列解耦，避免忙等。
- WiFi 用完立即 `esp_wifi_stop()` + `esp_wifi_deinit()`——**WiFi 在 `esp_wifi_start()` 到 `esp_wifi_stop()` 之间持有 `ESP_PM_APB_FREQ_MAX` 锁**，只要不停止，调频和省电都会被阻止。

---

## 四、ESP-IDF 内核与系统配置（"内核层优化"的真实落点）

在 ESP-IDF 下，**不建议修改 FreeRTOS 内核源码**（其 fork 与 `esp_pm`、WiFi 深度耦合，改动会破坏集成）。内核层能做的、且收益明确的全部是配置项：

```ini
# ── 电源管理（核心）──
CONFIG_PM_ENABLE=y
CONFIG_FREERTOS_USE_TICKLESS_IDLE=y     # 不开启则 esp_pm_configure() 返回 ESP_ERR_NOT_SUPPORTED
CONFIG_PM_DFS_INIT_AUTO=y
CONFIG_PM_LIGHTSLEEP_TICK_OVERFLOW_PROTECTION=y   # 防止过睡触发 vTaskStepTick 断言崩溃

# ── FreeRTOS 节拍 ──
CONFIG_FREERTOS_HZ=100                  # 默认 1000 → 100，唤醒次数降 90%

# ── 关闭调试开销（每个都是实测可省的电）──
CONFIG_FREERTOS_GENERATE_RUN_TIME_STATS=n   # 需要额外高频定时器
CONFIG_FREERTOS_USE_TRACE_FACILITY=n
CONFIG_FREERTOS_VTASKLIST_INCLUDE_COREID=n
CONFIG_LOG_DEFAULT_LEVEL_WARN               # 关闭 INFO 级日志（串口输出本身耗电）
CONFIG_ESP_CONSOLE_UART_NONE                # 产品阶段彻底关闭串口
CONFIG_COMPILER_OPTIMIZATION_SIZE=y

# ── WiFi 省电 ──
CONFIG_ESP_WIFI_STATIC_RX_BUFFER_NUM=4      # 减小缓冲，省 RAM 与功耗
CONFIG_ESP_WIFI_DYNAMIC_RX_BUFFER_NUM=16
CONFIG_ESP_WIFI_AMPDU_TX_ENABLED=y
CONFIG_ESP_WIFI_PS_MIN_MODEM=y              # 若必须常连，开 modem sleep
```

> **注意**：`CONFIG_FREERTOS_HZ=100` 会把 `vTaskDelay` 的最小粒度变为 10 ms，需确认应用时序能接受。

### 若走"light sleep 常驻"路线（备选，非本方案主路线）

```c
esp_pm_config_t pm = {
    .max_freq_mhz = 240,
    .min_freq_mhz = 40,
    .light_sleep_enable = true,
};
esp_pm_configure(&pm);
```
- 此时**必须排查 PM 锁**：`esp_pm_dump_locks(stdout)` 会列出谁在阻止睡眠。
- 目标平均电流约 **0.8-2 mA**，响应快但比 deep sleep 高一个数量级。

---

## 五、实施路径（建议顺序，每步都可独立验证）

| 阶段 | 内容 | 周期 | 验证方法 |
|---|---|---|---|
| **P0 基线测量** | 基线固件 `esp32cam-viewer/viewer`：**WiFi 常开**、每小时拍一张存 SD、网页可查；测出平均电流与各阶段耗时 | 1 天 | USB 电流表 / INA219 + `/POWER.CSV` |
| **P1 零成本软件优化** | PWDN 拉高、`rtc_gpio_isolate`、`gpio_hold_en`、移除 LED、上传改批量 | 2-3 天 | 复测 `I_sleep` 与续航 |
| **P2 内核/系统配置** | 第四章全部 sdkconfig | 1 天 | 复测 `I_active`、连接耗时 |
| **P3 WiFi 快速连接** | BSSID + channel + 静态 IP | 1-2 天 | 测连接耗时（目标 <1 s） |
| **P4 硬件改造（可选）** | 换 LDO → 切摄像头 → 切 SD | 3-5 天 | **必须在 P0-P3 之后做**，否则无法区分收益来源 |
| **P5 长稳测试** | 连续运行 72 h，记录电量曲线 | 3 天 | 电压记录仪 |

> **基线口径（本项目统一）**：基线 = 「WiFi 常开 + 每小时一张 + 网页可查」，对应固件
> [esp32cam-viewer](esp32cam-viewer/README.md)。省电方案同样保留 WiFi，只是改成
> 「需要时才连、连上就干活、干完就睡」，所以比的是「同样开着 WiFi，谁更省」。
> [esp32cam-baseline](esp32cam-baseline/README.md)（WiFi 关闭、CPU 空转）降为**下限参考**，
> 不再作为主基线。
>
> **P0 绝不能跳过**。ESP32-CAM 版本差异极大，任何网上数字都可能与你的板子不符；没有基线就无法判断优化是否有效。

---

## 六、陷阱清单（踩过的坑，按严重程度）

1. **`vTaskStepTick()` 断言崩溃**：ESP-IDF 用预测式时间补偿，若唤醒开销被低估导致过睡，`vTaskStepTick` 会收到过大的 tick 补偿值并断言失败。解决：开 `CONFIG_PM_LIGHTSLEEP_TICK_OVERFLOW_PROTECTION`。这是与本仓库 V11.3.1 中 `vTaskStepTick` 边界约束（`tasks.c:4678` 的 `configASSERT`）同源的机制。
2. **WiFi 不 `esp_wifi_stop()`**：持续持有 `ESP_PM_APB_FREQ_MAX`，DFS 与 light sleep 全部失效。
3. **`gpio_hold_en` 忘记**：控制外设供电的 GPIO 在 deep sleep 时变为高阻，外设可能被意外上电。
4. **`rtc_gpio_isolate` 忘记**：未使用引脚通过外部上/下拉漏电，常见几十到几百 µA。
5. **引脚冲突**：AI-Thinker ESP32-CAM 的 `GPIO 6-11` 接内部 flash **动了必然变砖**；`GPIO 0` 是摄像头 XCLK 且 boot 时须为高；`GPIO 12` boot 时为高会启动失败；`GPIO 34/35/36/39` 仅输入。
6. **摄像头掉电后必须重新 `esp_camera_init()`**：硬件改造的固有代价（+0.4 s），但远小于省下的睡眠能耗。
7. **调试器/串口连接会阻止低功耗**：产品验证时必须断开 USB-TTL，且关闭串口日志。
8. **SD 卡在 deep sleep 期间的漏电**：卡座若仍有供电，部分卡会持续耗电，需实测。
9. **电源峰值能力**：WiFi TX + 摄像头同时工作时峰值可达 400-500 mA，电池 + LDO 必须能供得上，否则会欠压重启（表现为"随机重启"，很容易误判为软件 bug）。

---

## 七、预期结果

按推荐组合（T=60 s、只存 SD、每小时批量上传、完成 P1-P4）：

| 指标 | 优化前 | 优化后 |
|---|---|---|
| 深睡电流 | 5 mA | **0.05-0.15 mA** `【实测】` |
| 单次唤醒工作耗时 | 4.5 s | **0.6 s**（普通周期）/ 2.7 s（上传周期） |
| 平均电流 | 17.1 mA | **1.54 mA** |
| 2000 mAh 电池续航 | ~3.9 天 | **~43 天** |

**若把周期放宽到 5 分钟**，平均电流可降到 **0.28 mA**，续航 **~238 天**——此时瓶颈转移到电池自放电，MCU 侧已无优化空间。

---

## 附：本方案的验证状态说明

- **基线固件**：`esp32cam-baseline`（WiFi 关闭）与 `esp32cam-viewer`（WiFi 常开 + 网页）
  均已在 AI-Thinker ESP32-CAM + esp32 核心 3.3.12 上实机跑通（拍照、写卡、续号、网页、NTP 时间）。
- **省电方案代码与配置**：基于 ESP-IDF 官方电源管理文档与 AI-Thinker ESP32-CAM 引脚约束编写，**尚未在目标硬件上编译/运行**（当前环境无 ESP-IDF 与 Xtensa 工具链）。
- **电流数值**：全部为社区典型值，**必须通过 P0 基线测量校准**后再作为决策依据。
- **硬件改造项**：需先确认你自己板子的 LDO 型号与封装、以及 OV2640 的 PWDN/供电走线。
- **`CONFIG_*` 选项名**：以你实际使用的 ESP-IDF 版本 `idf.py menuconfig` 为准（不同大版本有重命名）。
- **API 名称**：文中代码为示意骨架，`esp_netif` / `tcpip_adapter`、`esp_camera_*` 等接口在不同 IDF 大版本间有变更，落地前需对照对应版本的 API 文档核对。
- **未验证项**：`rtc_gpio_isolate()` 的具体引脚集合、`gpio_hold_en()` 的启用时机，需结合你的实际接线与 LDO/ MOSFET 电路确定。
