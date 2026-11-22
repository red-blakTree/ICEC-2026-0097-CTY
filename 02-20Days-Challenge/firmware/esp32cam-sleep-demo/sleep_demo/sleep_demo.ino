/*
 * ESP32-CAM 睡眠模式演示固件
 *
 * 网页上选择 4 种模式，每种模式都按「0/30/60/90/120 s 各拍 1 张，共 5 张」
 * 执行一次 2 分钟会话，拍完第 5 张后退出睡眠、回到正常模式等待下一次网页命令。
 *
 *   正常模式（基线）  WiFi/网页常开，WiFi 不进入 modem sleep
 *   WiFi modem sleep  WiFi/网页常开，WiFi 显式进入 MIN_MODEM 睡眠
 *   浅睡              关网页 + 关 WiFi，拍照间用 esp_light_sleep_start() 睡眠
 *   深睡              关网页 + 关 WiFi，拍照间用 esp_deep_sleep_start() 睡眠
 *
 * 浅睡/深睡期间网页不可访问；深睡每次唤醒都是一次完整重启，靠 RTC_DATA_ATTR
 * 保存会话进度、时间和能耗。2 分钟结束后重新连 WiFi、开网页，回到正常模式。
 *
 * 板卡：AI-Thinker ESP32-CAM
 * FQBN：esp32:esp32:esp32cam（板级默认已开 PSRAM）
 */
#include "esp_camera.h"
#include "SD_MMC.h"
#include <WiFi.h>
#include <WebServer.h>
#include <time.h>
#include <sys/time.h>
#include "esp_sleep.h"
#include <driver/gpio.h>
#include <vector>

#include "secrets.h"
#include "web_page.h"

// ── 会话参数 ──
// 5 张：0/30/60/90/120 s；第 5 张拍完即退出，正好覆盖 2 分钟
static const uint8_t kShotsPerSession = 5;
static const uint32_t kShotIntervalMs = 30UL * 1000UL;
// 浅睡唤醒后要重初始化摄像头/SD，预留一点时间，让拍照间隔仍接近 30 s
static const uint32_t kLightWakeReserveMs = 700;

// 网页时间与 NTP 都用东八区；deep sleep 后 TZ 会丢，需要每次启动重设
static const char *kTzString = "CST-8";

// 固定 IP：网关 192.168.16.1；DNS 用于解析 NTP 域名
static const IPAddress kStaticIp(192, 168, 16, 50);
static const IPAddress kGateway(192, 168, 16, 1);
static const IPAddress kSubnet(255, 255, 255, 0);
static const IPAddress kDns1(192, 168, 16, 1);
static const IPAddress kDns2(223, 5, 5, 5);

// AI-Thinker ESP32-CAM 引脚定义
#define CAM_PIN_PWDN   32
#define CAM_PIN_RESET  -1
#define CAM_PIN_XCLK    0
#define CAM_PIN_SIOD   26
#define CAM_PIN_SIOC   27
#define CAM_PIN_D7     35
#define CAM_PIN_D6     34
#define CAM_PIN_D5     39
#define CAM_PIN_D4     36
#define CAM_PIN_D3     21
#define CAM_PIN_D2     19
#define CAM_PIN_D1     18
#define CAM_PIN_D0      5
#define CAM_PIN_VSYNC  25
#define CAM_PIN_HREF   23
#define CAM_PIN_PCLK   22
#define CAM_PIN_FLASH   4

static const int kSdClk = 14;
static const int kSdCmd = 15;
static const int kSdD0  = 2;

// ── 功耗日志（5 V 输入端的模型电流，不是实测值）──
// 正常/modem 的绝对值受 WiFi 省电档位影响；本演示只用于模式间相对比较。
static const float kModelNormalMa = 110.0f;  // 正常模式：WiFi 常开、不进入 modem sleep
static const float kModelModemMa  = 95.0f;   // modem sleep：参考 powersave 窗口实测 95 mA
static const float kModelAwakeMa  = 45.0f;   // 醒着但 WiFi 关：240 MHz 空转 + AMS1117 静态电流
static const float kModelShotMa   = 180.0f;  // 摄像头 init + JPEG 捕获
static const float kModelSaveMa   = 50.0f;   // SD 卡写入
static const float kModelLightMa  = 1.0f;    // 浅睡：芯片级模型值，5 V 输入侧还有 LDO 静态电流
static const float kModelDeepMa   = 6.0f;    // 深睡：官方手册整板 6 mA @5V；表只能给 ≤10 mA 上界
// 电压：没接分压电阻时按 4.90 V 估算（与 powersave 一致）
static const float kFallbackV = 4.90f;

// 电压采样需要外接分压：5V ──100k── IO16 ──100k── GND
static const bool  kHasVbatDivider = false;
static const int   kPinVbat        = 16;
static const float kDividerRatio   = 2.0f;

static const uint32_t kPowerLogIntervalMs = 5UL * 60UL * 1000UL;
static const char *kPowerLogPath = "/POWER.CSV";

enum DemoMode : uint8_t {
  MODE_NORMAL = 0,
  MODE_MODEM  = 1,
  MODE_LIGHT  = 2,
  MODE_DEEP   = 3,
};

static DemoMode s_mode = MODE_NORMAL;
static bool     s_session_active = false;
static uint8_t  s_shots_done = 0;
static uint32_t s_next_shot_ms = 0;
static uint32_t s_next_log_ms = 0;
static uint32_t s_last_sample_ms = 0;
static uint32_t s_next_heartbeat_ms = 0;
static uint32_t s_wifi_retry_ms = 0;
static uint32_t s_next_index = 1;
static float    s_energy_mwh = 0.0f;
static bool     s_web_on = false;
static bool     s_routes_registered = false;
static bool     s_pending_start = false;
static bool     s_pending_stop = false;
static DemoMode s_pending_mode = MODE_NORMAL;

// 跨 deep sleep 保留：会话进度、模式、时间、能耗
RTC_DATA_ATTR static bool     s_rtc_session_active = false;
RTC_DATA_ATTR static uint8_t  s_rtc_mode = MODE_NORMAL;
RTC_DATA_ATTR static uint8_t  s_rtc_shots_done = 0;
RTC_DATA_ATTR static time_t   s_rtc_epoch = 0;
RTC_DATA_ATTR static float    s_rtc_energy_mwh = 0.0f;

static WebServer server(80);

static const char *modeName(DemoMode m) {
  switch (m) {
    case MODE_NORMAL: return "normal";
    case MODE_MODEM:  return "modem";
    case MODE_LIGHT:  return "light";
    case MODE_DEEP:   return "deep";
  }
  return "normal";
}

static const char *modeLabel(DemoMode m) {
  switch (m) {
    case MODE_NORMAL: return "正常模式（基线）";
    case MODE_MODEM:  return "WiFi modem sleep";
    case MODE_LIGHT:  return "浅睡";
    case MODE_DEEP:   return "深睡";
  }
  return "正常模式（基线）";
}

static bool parseMode(const String &s, DemoMode &out) {
  if (s == "normal") { out = MODE_NORMAL; return true; }
  if (s == "modem")  { out = MODE_MODEM;  return true; }
  if (s == "light")  { out = MODE_LIGHT;  return true; }
  if (s == "deep")   { out = MODE_DEEP;   return true; }
  return false;
}

static String fmtTime(time_t t) {
  if (t < 1600000000L) {
    return String("无时间戳");
  }
  struct tm info;
  localtime_r(&t, &info);
  char buf[24];
  strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &info);
  return String(buf);
}

// deep sleep 后 TZ 环境变量会丢，不重设的话时间会按 UTC 显示（差 8 小时）
static void applyTimeZone() {
  setenv("TZ", kTzString, 1);
  tzset();
}

static bool initCamera() {
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = CAM_PIN_D0;
  config.pin_d1       = CAM_PIN_D1;
  config.pin_d2       = CAM_PIN_D2;
  config.pin_d3       = CAM_PIN_D3;
  config.pin_d4       = CAM_PIN_D4;
  config.pin_d5       = CAM_PIN_D5;
  config.pin_d6       = CAM_PIN_D6;
  config.pin_d7       = CAM_PIN_D7;
  config.pin_xclk     = CAM_PIN_XCLK;
  config.pin_pclk     = CAM_PIN_PCLK;
  config.pin_vsync    = CAM_PIN_VSYNC;
  config.pin_href     = CAM_PIN_HREF;
  config.pin_sccb_sda = CAM_PIN_SIOD;
  config.pin_sccb_scl = CAM_PIN_SIOC;
  config.pin_pwdn     = CAM_PIN_PWDN;
  config.pin_reset    = CAM_PIN_RESET;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size   = FRAMESIZE_SVGA;
  config.jpeg_quality = 12;
  config.fb_count     = 1;
  config.fb_location  = CAMERA_FB_IN_PSRAM;
  config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;
  return esp_camera_init(&config) == ESP_OK;
}

static bool initSdCard() {
  SD_MMC.setPins(kSdClk, kSdCmd, kSdD0);
  return SD_MMC.begin("/sdcard", true);
}

static uint32_t nextIndexFromSd() {
  uint32_t max_idx = 0;
  File root = SD_MMC.open("/");
  if (!root) {
    return 1;
  }
  for (File f = root.openNextFile(); f; f = root.openNextFile()) {
    const char *name = f.name();
    const char *base = strrchr(name, '/');
    base = base ? base + 1 : name;
    unsigned idx = 0;
    if (sscanf(base, "IMG_%u.jpg", &idx) == 1 && idx > max_idx) {
      max_idx = idx;
    }
    f.close();
  }
  root.close();
  return max_idx + 1;
}

static int readV5Mv() {
  if (!kHasVbatDivider) {
    return -1;
  }
  return (int)(analogReadMilliVolts(kPinVbat) * kDividerRatio + 0.5f);
}

static float fallbackVoltage() {
  int mv = readV5Mv();
  return (mv > 0) ? mv / 1000.0f : kFallbackV;
}

// 板载温度传感器只反映芯片 die 温度，不是 AMS1117/环境温度；用于过热排查
static void logTemperature(const char *tag) {
  Serial.printf("[TEMP] %s %.1f C\n", tag, temperatureRead());
}

// 醒着但没在拍照时的模型电流；深睡/浅睡期间的睡眠电流单独记账
static float modeIdleMa(DemoMode m) {
  switch (m) {
    case MODE_NORMAL: return kModelNormalMa;
    case MODE_MODEM:  return kModelModemMa;
    default:          return kModelAwakeMa;
  }
}

static void accumulateEnergy() {
  uint32_t now = millis();
  uint32_t dt_ms = now - s_last_sample_ms;
  s_last_sample_ms = now;
  s_energy_mwh += modeIdleMa(s_mode) * fallbackVoltage() * ((float)dt_ms / 3600000.0f);
}

static void addSleepEnergy(uint32_t sleep_ms, float sleep_ma) {
  s_energy_mwh += sleep_ma * fallbackVoltage() * ((float)sleep_ms / 3600000.0f);
}

static void powerLogHeaderIfNeeded() {
  if (SD_MMC.exists(kPowerLogPath)) {
    return;
  }
  File f = SD_MMC.open(kPowerLogPath, FILE_WRITE);
  if (!f) {
    Serial.printf("[WARN] 无法创建 %s\n", kPowerLogPath);
    return;
  }
  f.print("uptime_s,event,window_s,v5_mv,i_ma,p_mw,e_mwh\n");
  f.close();
}

// i_ma 是 window_s 窗口内的平均电流，由模型推算，不是实测值。
// 深睡/浅睡会话的 CAPTURE 只覆盖唤醒拍照的那 1 s 左右；睡眠段由 *_SLEEP 事件记账。
static void powerLogAppend(const char *event, uint32_t window_s, float i_ma) {
  int mv = readV5Mv();
  float v = fallbackVoltage();
  char line[128];
  snprintf(line, sizeof(line), "%lu,%s,%lu,%d,%.1f,%.1f,%.4f\n",
           (unsigned long)(millis() / 1000), event, (unsigned long)window_s,
           mv, i_ma, i_ma * v, s_energy_mwh);
  File f = SD_MMC.open(kPowerLogPath, FILE_APPEND);
  if (!f) {
    return;
  }
  f.print(line);
  f.close();
  Serial.printf("[PWR] %s", line);
}

static void powerLogSample() {
  accumulateEnergy();
  powerLogAppend("SAMPLE", kPowerLogIntervalMs / 1000, modeIdleMa(s_mode));
}

// 正常/modem 模式一个 30 s 采集周期的平均电流；深睡/浅睡不用这个函数
static float cycleAverageMa(uint32_t shot_ms, uint32_t save_ms) {
  float period_s = kShotIntervalMs / 1000.0f;
  float shot_s = shot_ms / 1000.0f;
  float save_s = save_ms / 1000.0f;
  float idle_s = period_s - shot_s - save_s;
  if (idle_s < 0) {
    idle_s = 0;
  }
  return (kModelShotMa * shot_s + kModelSaveMa * save_s + modeIdleMa(s_mode) * idle_s) /
         period_s;
}

static bool captureOnce() {
  accumulateEnergy();
  uint32_t t_start = millis();
  Serial.printf("[CAP] start IMG_%05lu temp=%.1fC\n", (unsigned long)s_next_index,
                temperatureRead());
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[ERR] 拍照失败（esp_camera_fb_get 返回 NULL）");
    return false;
  }
  uint32_t t_shot = millis();
  Serial.printf("[CAP] fb ok temp=%.1fC\n", temperatureRead());

  char path[32];
  snprintf(path, sizeof(path), "/IMG_%05lu.jpg", (unsigned long)s_next_index);
  File f = SD_MMC.open(path, FILE_WRITE);
  if (!f) {
    Serial.printf("[ERR] 无法创建 %s\n", path);
    esp_camera_fb_return(fb);
    return false;
  }
  size_t written = f.write(fb->buf, fb->len);
  f.close();
  uint32_t t_saved = millis();
  size_t size = fb->len;
  esp_camera_fb_return(fb);

  if (written != size) {
    Serial.printf("[ERR] %s 写入不完整 %u/%u\n", path, (unsigned)written, (unsigned)size);
    return false;
  }

  uint32_t shot_ms = t_shot - t_start;
  uint32_t save_ms = t_saved - t_shot;
  Serial.printf("[CAP] %s size=%luB %s capture=%lums save=%lums\n", path,
                (unsigned long)size, fmtTime(time(nullptr)).c_str(),
                (unsigned long)shot_ms, (unsigned long)save_ms);

  if (s_mode == MODE_DEEP || s_mode == MODE_LIGHT) {
    // 睡眠会话：CAPTURE 只覆盖唤醒拍照段，睡眠段另记
    uint32_t awake_ms = shot_ms + save_ms;
    uint32_t window_s = (awake_ms + 999) / 1000;
    if (window_s == 0) {
      window_s = 1;
    }
    float i_ma = awake_ms
                     ? (kModelShotMa * shot_ms + kModelSaveMa * save_ms) / (float)awake_ms
                     : kModelShotMa;
    powerLogAppend("CAPTURE", window_s, i_ma);
  } else {
    powerLogAppend("CAPTURE", kShotIntervalMs / 1000, cycleAverageMa(shot_ms, save_ms));
  }
  s_next_index++;
  return true;
}

static bool connectWifi(bool modem_sleep) {
  Serial.printf("[WIFI] 连接 %s（modem sleep=%s）...\n", kWifiSsid,
                modem_sleep ? "on" : "off");
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(modem_sleep);
  WiFi.config(kStaticIp, kGateway, kSubnet, kDns1, kDns2);
  WiFi.begin(kWifiSsid, kWifiPass);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) {
    delay(500);
  }
  if (WiFi.status() == WL_CONNECTED) {
    // 驱动在关联时可能把 PS 重置回默认 MIN_MODEM，连上后再设一次
    WiFi.setSleep(modem_sleep);
    delay(100);
    Serial.printf("[WIFI] 已连接，IP %s RSSI %d dBm，PS=%s\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI(),
                  modem_sleep ? "MIN_MODEM" : "NONE");
    return true;
  }
  Serial.println("[WIFI] 连接失败，30 秒后重试");
  powerLogAppend("WIFI_FAIL", 0, 0);
  return false;
}

static void syncClock() {
  configTime(8 * 3600, 0, "ntp.aliyun.com", "ntp.tencent.com");
  for (int i = 0; i < 20 && time(nullptr) < 1600000000L; i++) {
    delay(500);
  }
  Serial.printf("[TIME] %s\n", fmtTime(time(nullptr)).c_str());
}

// 唤醒后释放 PWDN 的深睡保持，让摄像头能重新上电
static void releaseCameraPowerHold() {
  gpio_deep_sleep_hold_dis();
  gpio_hold_dis((gpio_num_t)CAM_PIN_PWDN);
  pinMode(CAM_PIN_PWDN, OUTPUT);
  digitalWrite(CAM_PIN_PWDN, LOW);
}

// 睡眠前关摄像头：deinit + PWDN 拉高；只有深睡才需要 GPIO hold
static void powerDownCamera(bool hold_for_deep) {
  esp_camera_deinit();
  pinMode(CAM_PIN_PWDN, OUTPUT);
  digitalWrite(CAM_PIN_PWDN, HIGH);
  if (hold_for_deep) {
    gpio_hold_en((gpio_num_t)CAM_PIN_PWDN);
    gpio_deep_sleep_hold_en();
  }
}

// 空闲（没有会话）时降温：摄像头 deinit + PWDN 拉高，WiFi 回到 MIN_MODEM。
// 网页长期开着时，PS_NONE + 摄像头常开会把 5 V 侧电流顶到 0.19 A、板温 60 °C 以上。
static void enterIdleState() {
  WiFi.setSleep(true);
  powerDownCamera(false);
  Serial.println("[IDLE] 摄像头已关闭，WiFi 转 MIN_MODEM");
}

// 会话开始前重新给摄像头上电并 init（约 200 ms）
static bool leaveIdleState() {
  releaseCameraPowerHold();
  if (!initCamera()) {
    Serial.println("[ERR] 摄像头重新初始化失败");
    return false;
  }
  return true;
}

// deep sleep 后 time() 的连续性不保证，用睡眠前记下的 epoch 兜底
static void restoreTimeFromRtc() {
  if (s_rtc_epoch > 1600000000L) {
    struct timeval tv;
    tv.tv_sec = s_rtc_epoch;
    tv.tv_usec = 0;
    settimeofday(&tv, nullptr);
  }
}

// 本次启动已经花掉多少时间；只用于深睡唤醒后把 30 s 周期扣回 30 s
static uint32_t remainingShotIntervalMs() {
  uint32_t elapsed = millis();
  if (elapsed >= kShotIntervalMs - 1000) {
    return 1000;
  }
  return kShotIntervalMs - elapsed;
}

// 关外设 → 记能耗/时间 → 进 deep sleep 到 sleep_ms 后（不返回）
static void sleepDeepFor(uint32_t sleep_ms) {
  if (sleep_ms < 1000) {
    sleep_ms = 1000;
  }
  // 防御：任何意外的超大值都不允许睡超过 60 s（首次进入时应传 30 s）
  if (sleep_ms > kShotIntervalMs * 2) {
    sleep_ms = kShotIntervalMs;
  }
  accumulateEnergy();
  addSleepEnergy(sleep_ms, kModelDeepMa);
  s_rtc_energy_mwh = s_energy_mwh;

  time_t now = time(nullptr);
  s_rtc_epoch = (now > 1600000000L) ? now + sleep_ms / 1000 : 0;
  s_rtc_session_active = true;
  s_rtc_mode = (uint8_t)MODE_DEEP;
  s_rtc_shots_done = s_shots_done;

  logTemperature("deep-sleep");
  powerLogAppend("DEEP_SLEEP", sleep_ms / 1000, kModelDeepMa);
  Serial.printf("[SLEEP] 深睡 %lus，会话进度 %u/%u\n", (unsigned long)(sleep_ms / 1000),
                (unsigned)s_shots_done, (unsigned)kShotsPerSession);
  Serial.flush();

  powerDownCamera(true);
  SD_MMC.end();
  esp_sleep_enable_timer_wakeup((uint64_t)sleep_ms * 1000ULL);
  esp_deep_sleep_start();
}

// 关外设 → 记能耗 → 浅睡 → 唤醒并重新初始化摄像头/SD
static bool sleepLightFor(uint32_t sleep_ms) {
  if (sleep_ms < 1000) {
    sleep_ms = 1000;
  }
  accumulateEnergy();
  addSleepEnergy(sleep_ms, kModelLightMa);
  logTemperature("light-sleep");
  powerLogAppend("LIGHT_SLEEP", sleep_ms / 1000, kModelLightMa);
  Serial.printf("[SLEEP] 浅睡 %lus，会话进度 %u/%u\n", (unsigned long)(sleep_ms / 1000),
                (unsigned)s_shots_done, (unsigned)kShotsPerSession);
  Serial.flush();

  powerDownCamera(false);
  SD_MMC.end();
  esp_sleep_enable_timer_wakeup((uint64_t)sleep_ms * 1000ULL);
  esp_err_t err = esp_light_sleep_start();
  s_last_sample_ms = millis();
  if (err != ESP_OK) {
    Serial.printf("[WARN] esp_light_sleep_start 失败：%d，改普通延时\n", (int)err);
    delay(sleep_ms);
  }

  releaseCameraPowerHold();
  if (!initCamera()) {
    Serial.println("[ERR] 浅睡唤醒后摄像头初始化失败");
    return false;
  }
  if (!initSdCard()) {
    Serial.println("[ERR] 浅睡唤醒后 SD 卡初始化失败");
    return false;
  }
  powerLogAppend("LIGHT_WAKE", 0, 0);
  return true;
}

static void handleApi();
static void handleRoot();
static void handleMode();
static void handleFile();
static void handleReset();
static void handleStop();

static void registerRoutes() {
  if (s_routes_registered) {
    return;
  }
  server.on("/", handleRoot);
  server.on("/api.json", handleApi);
  server.on("/mode", HTTP_POST, handleMode);
  server.on("/admin/reset", HTTP_POST, handleReset);
  server.on("/stop", HTTP_POST, handleStop);
  server.onNotFound(handleFile);
  s_routes_registered = true;
}

static void startWeb() {
  registerRoutes();
  server.begin();
  s_web_on = true;
  s_wifi_retry_ms = 0;
  powerLogAppend("WEB_ON", 0, 0);
  Serial.printf("[WEB] http://%s/\n", WiFi.localIP().toString().c_str());
}

static void stopWebAndWifi() {
  server.stop();
  s_web_on = false;
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  powerLogAppend("WEB_OFF", 0, 0);
  Serial.println("[WEB] 已关闭网页服务与 WiFi");
}

static void finishSession() {
  accumulateEnergy();
  powerLogAppend("SESSION_END", 0, 0);

  s_session_active = false;
  s_shots_done = 0;
  s_mode = MODE_NORMAL;
  s_rtc_session_active = false;
  s_rtc_shots_done = 0;

  if (s_web_on) {
    // 正常/modem 模式：网页一直开着，会话结束回到空闲低功耗状态
    enterIdleState();
    Serial.println("[MODE] 会话结束，回到空闲（摄像头关闭、WiFi MIN_MODEM）");
    return;
  }

  // 浅睡/深睡：重新连 WiFi + 校时 + 开网页
  if (!connectWifi(false)) {
    s_wifi_retry_ms = millis() + 30000;
    return;
  }
  syncClock();
  startWeb();
  enterIdleState();
  Serial.println("[MODE] 会话结束，已回到空闲（摄像头关闭、WiFi MIN_MODEM）");
}

// 浅睡会话：阻塞 2 分钟，期间网页不可用
static void runLightSession() {
  for (uint8_t i = 0; i < kShotsPerSession; i++) {
    captureOnce();
    s_shots_done = i + 1;
    if (s_shots_done >= kShotsPerSession) {
      break;
    }
    uint32_t sleep_ms = (kShotIntervalMs > kLightWakeReserveMs)
                            ? (kShotIntervalMs - kLightWakeReserveMs)
                            : kShotIntervalMs;
    if (!sleepLightFor(sleep_ms)) {
      Serial.println("[ERR] 浅睡会话中止");
      break;
    }
  }
  finishSession();
}

static void startSession(DemoMode mode) {
  s_mode = mode;
  s_session_active = true;
  s_shots_done = 0;

  if (!leaveIdleState()) {
    s_session_active = false;
    s_mode = MODE_NORMAL;
    return;
  }

  switch (mode) {
    case MODE_NORMAL:
    case MODE_MODEM:
      WiFi.setSleep(mode == MODE_MODEM);
      powerLogAppend(mode == MODE_MODEM ? "MODE_MODEM" : "MODE_NORMAL", 0, 0);
      s_next_shot_ms = millis();
      Serial.printf("[MODE] %s 会话开始（%u 张，每 %lus 一张）\n", modeLabel(mode),
                    (unsigned)kShotsPerSession, (unsigned long)(kShotIntervalMs / 1000));
      return;

    case MODE_DEEP:
    case MODE_LIGHT:
      // 等 HTTP 响应发出去，再断 WiFi/网页
      delay(300);
      stopWebAndWifi();
      powerLogAppend(mode == MODE_DEEP ? "MODE_DEEP" : "MODE_LIGHT", 0, 0);
      Serial.printf("[MODE] %s 会话开始（%u 张，每 %lus 一张）\n", modeLabel(mode),
                    (unsigned)kShotsPerSession, (unsigned long)(kShotIntervalMs / 1000));
      if (mode == MODE_DEEP) {
        captureOnce();
        s_shots_done = 1;
        sleepDeepFor(kShotIntervalMs);
        return;
      }
      runLightSession();
      return;
  }
}

static void handleMode() {
  if (s_session_active || s_pending_start) {
    server.send(409, "application/json", "{\"ok\":false,\"error\":\"session running\"}");
    return;
  }
  DemoMode mode;
  if (!parseMode(server.arg("m"), mode)) {
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"unknown mode\"}");
    return;
  }

  char body[128];
  snprintf(body, sizeof(body),
           "{\"ok\":true,\"mode\":\"%s\",\"label\":\"%s\",\"shots\":%u}",
           modeName(mode), modeLabel(mode), (unsigned)kShotsPerSession);
  server.send(200, "application/json", body);

  s_pending_mode = mode;
  s_pending_start = true;
}

static void handleApi() {
  String json;
  json.reserve(3072);

  uint32_t next_in_ms = 0;
  if (s_session_active) {
    int32_t left = (int32_t)(s_next_shot_ms - millis());
    next_in_ms = left > 0 ? (uint32_t)left : 0;
  }

  json += "{\"ip\":\"" + WiFi.localIP().toString() + "\",\"now\":\"" +
          fmtTime(time(nullptr)) + "\",\"uptime\":" + String(millis() / 1000) +
          ",\"mode\":\"" + modeName(s_mode) + "\",\"mode_label\":\"" + modeLabel(s_mode) +
          "\",\"session\":\"" + (s_session_active ? "running" : "idle") +
          "\",\"shots_done\":" + String(s_shots_done) +
          ",\"shots_total\":" + String(kShotsPerSession) +
          ",\"next_in_ms\":" + String(next_in_ms) +
          ",\"wifi\":" + (s_web_on ? "true" : "false") +
          ",\"temp_c\":" + String(temperatureRead(), 1) +
          ",\"rssi\":" + String(WiFi.RSSI()) + ",\"files\":[";

  int count = 0;
  File root = SD_MMC.open("/");
  if (root) {
    for (File f = root.openNextFile(); f; f = root.openNextFile()) {
      const char *name = f.name();
      const char *base = strrchr(name, '/');
      base = base ? base + 1 : name;
      if (strncmp(base, "IMG_", 4) == 0) {
        if (count) {
          json += ",";
        }
        json += "{\"name\":\"" + String(base) + "\",\"size\":" +
                String((unsigned long)f.size()) + ",\"time\":\"" +
                fmtTime(f.getLastWrite()) + "\"}";
        count++;
      }
      f.close();
    }
    root.close();
  }

  json += "],\"count\":" + String(count) + "}";
  server.send(200, "application/json", json);
}

static void handleRoot() {
  server.sendHeader("Cache-Control", "no-store");
  // 页面以 gzip 形式发给浏览器（web_page.h 里存的就是压缩后的字节），浏览器自动解压
  server.sendHeader("Content-Encoding", "gzip");
  server.send_P(200, "text/html; charset=utf-8", (PGM_P)kIndexHtmlGz, sizeof(kIndexHtmlGz));
}

// 其余路径按 SD 卡上的文件流式返回（照片、POWER.CSV）
static void handleFile() {
  String path = server.uri();
  if (path.indexOf("..") >= 0 || path == "/") {
    server.send(404, "text/plain", "not found");
    return;
  }
  if (!SD_MMC.exists(path)) {
    server.send(404, "text/plain", "not found");
    return;
  }
  File f = SD_MMC.open(path, FILE_READ);
  if (!f) {
    server.send(500, "text/plain", "open failed");
    return;
  }
  String type = path.endsWith(".jpg") ? "image/jpeg" : "text/csv; charset=utf-8";
  server.streamFile(f, type);
  f.close();
}
// 维护用：清空 SD 根目录所有文件，复位编号/能耗/会话状态，回到空闲态。
// 照片越多，/api.json 遍历 SD 目录越慢（59 张时 TTFB 约 0.95 s，清空后约 0.2 s）。
static void handleReset() {
  if (s_session_active) {
    server.send(409, "application/json", "{\"ok\":false,\"error\":\"session running\"}");
    return;
  }

  std::vector<String> names;
  File root = SD_MMC.open("/");
  if (!root) {
    server.send(500, "application/json", "{\"ok\":false,\"error\":\"sd open failed\"}");
    return;
  }
  for (File f = root.openNextFile(); f; f = root.openNextFile()) {
    const char *name = f.name();
    const char *base = strrchr(name, '/');
    base = base ? base + 1 : name;
    names.push_back(String("/") + base);
    f.close();
  }
  root.close();

  uint16_t removed = 0;
  for (size_t i = 0; i < names.size(); i++) {
    if (SD_MMC.remove(names[i])) {
      removed++;
    }
  }

  s_next_index = 1;
  s_energy_mwh = 0.0f;
  s_mode = MODE_NORMAL;
  s_shots_done = 0;
  s_rtc_session_active = false;
  s_rtc_shots_done = 0;
  s_rtc_energy_mwh = 0.0f;
  s_last_sample_ms = millis();
  powerLogHeaderIfNeeded();
  powerLogAppend("RESET", 0, 0);
  enterIdleState();

  Serial.printf("[MAINT] 已清空 %u 个文件，回到空闲\n", (unsigned)removed);
  char body[64];
  snprintf(body, sizeof(body), "{\"ok\":true,\"removed\":%u}", (unsigned)removed);
  server.send(200, "application/json", body);
}

// 网页手动结束会话：只置位，由 loop() 在 handleClient 返回后收尾，
// 避免 HTTP 响应还没发完就 deinit 摄像头 / 关 WiFi。
static void handleStop() {
  if (!s_session_active) {
    server.send(200, "application/json", "{\"ok\":true,\"state\":\"idle\"}");
    return;
  }
  if (s_mode != MODE_NORMAL && s_mode != MODE_MODEM) {
    server.send(409, "application/json", "{\"ok\":false,\"error\":\"session not interruptible\"}");
    return;
  }
  s_pending_stop = true;
  server.send(200, "application/json", "{\"ok\":true,\"state\":\"stopping\"}");
}

void setup() {
  const esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
  const bool cold_boot = (cause == ESP_SLEEP_WAKEUP_UNDEFINED);
  bool resume_deep = false;

  if (cold_boot) {
    // 上电/EN 复位：清掉可能残留的 RTC 会话标记
    s_rtc_session_active = false;
    s_rtc_shots_done = 0;
  } else {
    releaseCameraPowerHold();
    if (cause == ESP_SLEEP_WAKEUP_TIMER && s_rtc_session_active &&
        s_rtc_mode == (uint8_t)MODE_DEEP) {
      resume_deep = true;
      restoreTimeFromRtc();
      s_energy_mwh = s_rtc_energy_mwh;
      s_session_active = true;
      s_mode = MODE_DEEP;
      s_shots_done = s_rtc_shots_done;
    }
  }

  Serial.begin(115200);
  delay(200);
  applyTimeZone();

  pinMode(CAM_PIN_FLASH, OUTPUT);
  digitalWrite(CAM_PIN_FLASH, LOW);

  Serial.printf("\n=== ESP32-CAM 睡眠模式演示（%s）===\n",
                resume_deep ? "深睡定时唤醒" : "冷启动");

  if (!initCamera()) {
    Serial.println("[FATAL] 摄像头初始化失败");
    while (true) {
      delay(1000);
    }
  }
  Serial.println("[OK] 摄像头初始化完成");

  while (!initSdCard()) {
    Serial.println("[WARN] SD 卡初始化失败，5 秒后重试");
    delay(5000);
  }
  Serial.println("[OK] SD 卡初始化完成");

  s_next_index = nextIndexFromSd();
  Serial.printf("[OK] 下一张编号 IMG_%05lu.jpg\n", (unsigned long)s_next_index);

  powerLogHeaderIfNeeded();
  s_last_sample_ms = millis();
  s_next_log_ms = millis() + kPowerLogIntervalMs;
  s_next_heartbeat_ms = millis() + 10000;
  logTemperature("boot");

  if (resume_deep) {
    powerLogAppend("DEEP_WAKE", 0, 0);
    captureOnce();
    s_shots_done++;
    if (s_shots_done >= kShotsPerSession) {
      finishSession();
      return;
    }
    sleepDeepFor(remainingShotIntervalMs());
    return;
  }

  s_mode = MODE_NORMAL;
  s_session_active = false;
  s_shots_done = 0;

  if (connectWifi(false)) {
    syncClock();
    startWeb();
  } else {
    s_wifi_retry_ms = millis() + 30000;
  }
  enterIdleState();
}

void loop() {
  if ((int32_t)(millis() - s_next_heartbeat_ms) >= 0) {
    Serial.printf("[HB] up=%lus temp=%.1fC rssi=%d mode=%s session=%d shots=%u\n",
                  (unsigned long)(millis() / 1000), temperatureRead(), WiFi.RSSI(), modeName(s_mode),
                  s_session_active ? 1 : 0, (unsigned)s_shots_done);
    s_next_heartbeat_ms += 10000;
  }
  if (s_web_on) {
    server.handleClient();
  }

  // 网页 POST /mode 只负责置位；真正启动放到 handleClient 返回之后，
  // 这样深睡/浅睡模式切换时 HTTP 响应已经发完
  if (s_pending_start) {
    s_pending_start = false;
    startSession(s_pending_mode);
  }

  if (s_pending_stop) {
    s_pending_stop = false;
    if (s_session_active) {
      Serial.println("[MODE] 网页手动结束会话");
      finishSession();
    }
  }

  if (s_session_active && (s_mode == MODE_NORMAL || s_mode == MODE_MODEM)) {
    if ((int32_t)(millis() - s_next_shot_ms) >= 0) {
      captureOnce();
      s_shots_done++;
      if (s_shots_done >= kShotsPerSession) {
        finishSession();
      } else {
        s_next_shot_ms += kShotIntervalMs;
      }
    }
  }

  if (!s_web_on && !s_session_active && s_wifi_retry_ms != 0 &&
      (int32_t)(millis() - s_wifi_retry_ms) >= 0) {
    if (connectWifi(false)) {
      syncClock();
      startWeb();
    } else {
      s_wifi_retry_ms = millis() + 30000;
    }
  }

  if ((int32_t)(millis() - s_next_log_ms) >= 0) {
    powerLogSample();
    s_next_log_ms += kPowerLogIntervalMs;
  }
}
