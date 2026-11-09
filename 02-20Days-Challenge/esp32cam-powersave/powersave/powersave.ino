/*
 * ESP32-CAM 省电版 —— 开机 WiFi 窗口（15 分钟）+ 深睡占空比
 *
 * 冷启动（上电/复位）：
 *   初始化摄像头/SD → 连 WiFi + NTP → 立即拍一张存 SD
 *   → 网页服务与 WiFi 只开 15 分钟 → 关网页服务 + 关 WiFi 射频
 *   → 关摄像头（PWDN 保持高）、卸载 SD、进 deep sleep 到下一次拍照
 * 定时唤醒（deep sleep 计时器，每小时一次）：
 *   恢复时间 → 初始化摄像头/SD → 拍一张存 SD → 继续深睡，不连 WiFi
 *
 * 相对 esp32cam-viewer 多了：深睡占空比、摄像头 PWDN 断电保持、睡眠前卸载 SD、
 * 睡眠能耗计入 POWER.CSV。采集逻辑与网页不变。
 *
 * 窗口结束后网页不可用；要再看网页必须重启（断电或点网页「重置测试」都会重开 15 分钟窗口，
 * 后者会先清空 SD 数据并自动复位）。
 *
 * 板卡：AI-Thinker ESP32-CAM
 * FQBN：esp32:esp32:esp32cam:PSRAM=enabled（PSRAM 必须开启）
 */

#include "esp_camera.h"
#include "SD_MMC.h"
#include <WiFi.h>
#include <WebServer.h>
#include <time.h>
#include <sys/time.h>
#include "esp_sleep.h"
#include <driver/gpio.h>

#include "secrets.h"
#include "web_page.h"

static const uint32_t kCaptureIntervalMs = 60UL * 60UL * 1000UL;
// 开机后 WiFi + 网页的存活时长：15 分钟
static const uint32_t kWebWindowMs = 15UL * 60UL * 1000UL;
// 网页时间与 NTP 都用东八区；deep sleep 后 TZ 会丢，需要每次启动重设
static const char *kTzString = "CST-8";

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

// ── 功耗日志（5V 输入端的模型电流，典型值，未标定）──
static const float kModelIdleMa   = 45.0f;   // 240 MHz 空转 + AMS1117 静态电流（WiFi 关）
static const float kModelShotMa   = 180.0f;  // 摄像头 init + JPEG 捕获
static const float kModelSaveMa   = 50.0f;   // SD 卡写入
static const float kModelWifiMa  = 120.0f;  // STA 已连接、无流量时的平均电流
static const float kModelSleepMa  = 5.0f;    // 深睡电流：AMS1117 静态电流主导（未改硬件）

// 电压采样需要外接分压：5V ──100k── IO16 ──100k── GND
static const bool  kHasVbatDivider = false;
static const int   kPinVbat        = 16;
static const float kDividerRatio   = 2.0f;

static const uint32_t kPowerLogIntervalMs = 5UL * 60UL * 1000UL;
static const char *kPowerLogPath = "/POWER.CSV";

// 跑正式数据集前临时改为 true 烧一次：删除 SD 上的 IMG_*.jpg 与 POWER.CSV（仅冷启动生效）
static const bool kClearDataOnBoot = false;
static uint32_t s_next_index = 1;
static uint32_t s_next_capture_ms = 0;
static uint32_t s_next_log_ms = 0;
static uint32_t s_last_sample_ms = 0;
static uint32_t s_web_off_ms = 0;
static float    s_energy_mwh = 0.0f;
static bool     s_web_on = false;

// 跨 deep sleep 保留：累计能耗、睡眠前记下的 epoch
RTC_DATA_ATTR static float  s_energy_mwh_rtc = 0.0f;
RTC_DATA_ATTR static time_t s_rtc_epoch = 0;

static WebServer server(80);

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

// 累计能耗：WiFi 窗口内按「空转 + WiFi」算，窗口关闭后只算空转
static void accumulateEnergy() {
  uint32_t now = millis();
  uint32_t dt_ms = now - s_last_sample_ms;
  s_last_sample_ms = now;
  int mv = readV5Mv();
  float v = (mv > 0) ? mv / 1000.0f : 5.0f;
  float i_ma = s_web_on ? (kModelIdleMa + kModelWifiMa) : kModelIdleMa;
  s_energy_mwh += i_ma * v * ((float)dt_ms / 3600000.0f);
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

// i_ma 是 window_s 窗口内的平均电流，由模型推算，不是实测值；window_s=0 表示瞬时事件
static void powerLogAppend(const char *event, uint32_t window_s, float i_ma) {
  int mv = readV5Mv();
  float v = (mv > 0) ? mv / 1000.0f : 5.0f;
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
  float i_ma = s_web_on ? (kModelIdleMa + kModelWifiMa) : kModelIdleMa;
  powerLogAppend("SAMPLE", kPowerLogIntervalMs / 1000, i_ma);
}

// 一个采集周期（含深睡）的平均电流
static float cycleAverageMa(uint32_t shot_ms, uint32_t save_ms) {
  float period_s = kCaptureIntervalMs / 1000.0f;
  float shot_s = shot_ms / 1000.0f;
  float save_s = save_ms / 1000.0f;
  float idle_s = period_s - shot_s - save_s;
  if (idle_s < 0) {
    idle_s = 0;
  }
  return (kModelShotMa * shot_s + kModelSaveMa * save_s + kModelSleepMa * idle_s) / period_s;
}

// 删一个数据文件（IMG_*.jpg 或 POWER.CSV），每次重新遍历目录，避免边遍历边删
static bool deleteOneDataFile() {
  File root = SD_MMC.open("/");
  if (!root) {
    return false;
  }
  bool deleted = false;
  for (File f = root.openNextFile(); f; f = root.openNextFile()) {
    const char *name = f.name();
    const char *base = strrchr(name, '/');
    base = base ? base + 1 : name;
    bool match = (strncmp(base, "IMG_", 4) == 0) || (strcmp(base, "POWER.CSV") == 0);
    f.close();
    if (match) {
      SD_MMC.remove(String("/") + base);
      deleted = true;
      break;
    }
  }
  root.close();
  return deleted;
}

static void clearDataIfRequested() {
  if (!kClearDataOnBoot) {
    return;
  }
  uint32_t removed = 0;
  while (deleteOneDataFile()) {
    removed++;
  }
  Serial.printf("[CLEAN] 已删除 %lu 个文件，编号从 IMG_00001.jpg 重新开始\n",
                (unsigned long)removed);
}

static bool captureOnce() {
  uint32_t t_start = millis();
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[ERR] 拍照失败（esp_camera_fb_get 返回 NULL）");
    return false;
  }
  uint32_t t_shot = millis();

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
  powerLogAppend("CAPTURE", kCaptureIntervalMs / 1000, cycleAverageMa(shot_ms, save_ms));
  s_next_index++;
  return true;
}

static bool connectWifi() {
  Serial.printf("[WIFI] 连接 %s ...\n", kWifiSsid);
  WiFi.mode(WIFI_STA);
  WiFi.begin(kWifiSsid, kWifiPass);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) {
    delay(500);
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[WIFI] 已连接，IP %s\n", WiFi.localIP().toString().c_str());
    return true;
  }
  Serial.println("[WIFI] 连接失败，跳过网页服务");
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

// 睡眠前关摄像头：deinit + PWDN 拉高，并在深睡期间保持该电平
static void powerDownCamera() {
  esp_camera_deinit();
  pinMode(CAM_PIN_PWDN, OUTPUT);
  digitalWrite(CAM_PIN_PWDN, HIGH);
  gpio_hold_en((gpio_num_t)CAM_PIN_PWDN);
  gpio_deep_sleep_hold_en();
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

// 关外设 → 记能耗/时间 → 进 deep sleep 到 at_ms（不返回）
static void sleepUntil(uint32_t at_ms) {
  int32_t remain_ms = (int32_t)(at_ms - millis());
  if (remain_ms < 1000) {
    remain_ms = 1000;
  }

  int mv = readV5Mv();
  float v = (mv > 0) ? mv / 1000.0f : 5.0f;
  s_energy_mwh += kModelSleepMa * v * ((float)remain_ms / 3600000.0f);
  s_energy_mwh_rtc = s_energy_mwh;

  time_t now = time(nullptr);
  s_rtc_epoch = (now > 1600000000L) ? now + remain_ms / 1000 : 0;
  Serial.printf("[SLEEP] 深睡 %lds，预计 %s 醒来\n", (long)(remain_ms / 1000),
                fmtTime(s_rtc_epoch).c_str());
  Serial.flush();

  powerDownCamera();
  SD_MMC.end();
  esp_sleep_enable_timer_wakeup((uint64_t)remain_ms * 1000ULL);
  esp_deep_sleep_start();
}

// 网页源码在 web/index.html，用 web/build_header.py 生成 web_page.h

static uint32_t windowLeftS() {
  if (!s_web_on) {
    return 0;
  }
  int32_t left = (int32_t)(s_web_off_ms - millis());
  return left > 0 ? (uint32_t)(left / 1000) : 0;
}

// 状态 + 照片列表，供网页每 1 秒拉取一次；按目录顺序返回，新图由前端插到最前
static void handleApi() {
  String json;
  json.reserve(3072);
  json += "{\"ip\":\"" + WiFi.localIP().toString() + "\",\"now\":\"" +
          fmtTime(time(nullptr)) + "\",\"uptime\":" + String(millis() / 1000) +
          ",\"window_left\":" + String(windowLeftS()) + ",\"files\":[";

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
  server.send_P(200, "text/html; charset=utf-8", kIndexHtml);
}

static void handleCapture() {
  bool ok = captureOnce();
  // 前端点按钮后 fetch 这个地址，拍完直接刷新当前页，不跳转
  server.send(ok ? 200 : 500, "application/json",
              ok ? "{\"ok\":true}" : "{\"ok\":false}");
}

// 清空 SD 卡数据后自动复位（POST，避免被误触发）：冷启动会重新连 WiFi/NTP 并重开 15 分钟窗口
static void handleReset() {
  uint32_t removed = 0;
  while (deleteOneDataFile()) {
    removed++;
  }
  Serial.printf("[RESET] 已清空 %lu 个文件，复位重新开始测试\n", (unsigned long)removed);

  char body[64];
  snprintf(body, sizeof(body), "{\"ok\":true,\"removed\":%lu}", (unsigned long)removed);
  server.send(200, "application/json", body);

  delay(500);  // 等 HTTP 响应发出去再复位
  ESP.restart();
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

static void startWeb() {
  server.on("/", handleRoot);
  server.on("/api.json", handleApi);
  server.on("/capture", handleCapture);
  server.on("/reset", HTTP_POST, handleReset);
  server.onNotFound(handleFile);
  server.begin();
  s_web_off_ms = millis() + kWebWindowMs;
  s_web_on = true;
  Serial.printf("[WEB] http://%s/  窗口 %lu 分钟\n", WiFi.localIP().toString().c_str(),
                (unsigned long)(kWebWindowMs / 60000UL));
  powerLogAppend("WEB_ON", 0, kModelIdleMa + kModelWifiMa);
}

static void stopWeb() {
  server.stop();
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  s_web_on = false;
  Serial.println("[WEB] 窗口结束，已关闭网页服务与 WiFi");
  powerLogAppend("WEB_CLOSE", kWebWindowMs / 1000, kModelIdleMa + kModelWifiMa);
}

void setup() {
  const esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
  const bool cold_boot = (cause == ESP_SLEEP_WAKEUP_UNDEFINED);

  if (!cold_boot) {
    releaseCameraPowerHold();
    restoreTimeFromRtc();
    s_energy_mwh = s_energy_mwh_rtc;
  }

  Serial.begin(115200);
  delay(200);
  applyTimeZone();

  pinMode(CAM_PIN_FLASH, OUTPUT);
  digitalWrite(CAM_PIN_FLASH, LOW);

  Serial.printf("\n=== ESP32-CAM 省电版（%s）===\n",
                cold_boot ? "冷启动：WiFi + 网页开 15 分钟" : "定时唤醒：不连 WiFi");

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

  if (cold_boot) {
    clearDataIfRequested();  // 只在冷启动清卡，避免每小时唤醒都把数据删光
  }
  powerLogHeaderIfNeeded();
  s_last_sample_ms = millis();
  s_next_log_ms = millis() + kPowerLogIntervalMs;

  bool online = false;
  if (cold_boot) {
    online = connectWifi();
    if (online) {
      syncClock();
    }
  }

  captureOnce();
  s_next_capture_ms = millis() + kCaptureIntervalMs;

  if (online) {
    startWeb();  // 窗口由 loop 计时，结束后进 deep sleep
    return;
  }
  sleepUntil(s_next_capture_ms);
}

void loop() {
  if (s_web_on) {
    server.handleClient();
    if ((int32_t)(millis() - s_web_off_ms) >= 0) {
      stopWeb();
      sleepUntil(s_next_capture_ms);  // 深睡到下一次拍照，不返回
    }
  }

  if ((int32_t)(millis() - s_next_log_ms) >= 0) {
    powerLogSample();
    s_next_log_ms += kPowerLogIntervalMs;
  }

  if ((int32_t)(millis() - s_next_capture_ms) < 0) {
    return;
  }
  captureOnce();
  s_next_capture_ms += kCaptureIntervalMs;
}
