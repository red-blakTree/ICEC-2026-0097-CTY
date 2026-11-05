/*
 * ESP32-CAM 采集查看器
 *
 * 用途：联网后起一个网页，直接看 SD 卡上拍到哪些照片、每张的拍摄时间和预览，
 *       不用拔卡、不用串口。采集节奏与 P0 基线一致（每小时一张）。
 *
 * 注意：WiFi 全程常开，功耗远高于 esp32cam-baseline，**不能用来测功耗**。
 *       要交基线数据就切回 esp32cam-baseline。
 */

#include "esp_camera.h"
#include "SD_MMC.h"
#include <WiFi.h>
#include <WebServer.h>
#include <time.h>

#include "secrets.h"

static const uint32_t kCaptureIntervalMs = 60UL * 60UL * 1000UL;

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

static uint32_t s_next_index = 1;
static uint32_t s_next_capture_ms = 0;

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

static bool captureOnce() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[ERR] 拍照失败（esp_camera_fb_get 返回 NULL）");
    return false;
  }

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
  size_t size = fb->len;
  esp_camera_fb_return(fb);

  if (written != size) {
    Serial.printf("[ERR] %s 写入不完整 %u/%u\n", path, (unsigned)written, (unsigned)size);
    return false;
  }
  Serial.printf("[CAP] %s size=%luB %s\n", path, (unsigned long)size,
                fmtTime(time(nullptr)).c_str());
  s_next_index++;
  return true;
}

static void connectWifi() {
  Serial.printf("[WIFI] 连接 %s ...\n", kWifiSsid);
  WiFi.mode(WIFI_STA);
  WiFi.begin(kWifiSsid, kWifiPass);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) {
    delay(500);
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[WIFI] 已连接，IP %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("[WIFI] 连接失败，继续拍照但网页不可用");
  }
}

static void syncClock() {
  configTime(8 * 3600, 0, "ntp.aliyun.com", "ntp.tencent.com");
  for (int i = 0; i < 20 && time(nullptr) < 1600000000L; i++) {
    delay(500);
  }
  Serial.printf("[TIME] %s\n", fmtTime(time(nullptr)).c_str());
}

static void handleRoot() {
  static const int kMaxListed = 32;
  String names[kMaxListed];
  size_t sizes[kMaxListed];
  time_t shots[kMaxListed];
  int count = 0;

  File root = SD_MMC.open("/");
  if (root) {
    for (File f = root.openNextFile(); f && count < kMaxListed; f = root.openNextFile()) {
      const char *name = f.name();
      const char *base = strrchr(name, '/');
      base = base ? base + 1 : name;
      if (strncmp(base, "IMG_", 4) == 0) {
        names[count] = String(base);
        sizes[count] = f.size();
        shots[count] = f.getLastWrite();
        count++;
      }
      f.close();
    }
    root.close();
  }

  String page;
  page.reserve(6144);
  page += F("<!doctype html><meta charset=utf-8><title>ESP32-CAM 采集</title>");
  page += F("<style>body{font-family:sans-serif;margin:16px}"
            "table{border-collapse:collapse}"
            "td,th{padding:4px 10px;border-bottom:1px solid #ddd;font-size:14px}"
            "img{display:block;border:1px solid #ccc}</style>");
  page += F("<h2>ESP32-CAM 采集查看</h2>");
  page += "<p>IP " + WiFi.localIP().toString() + " ｜ 现在 " +
          fmtTime(time(nullptr)) + " ｜ 运行 " + String(millis() / 1000) + " s</p>";
  page += F("<p><a href=\"/POWER.CSV\">下载 POWER.CSV</a> ｜ "
            "<a href=\"/capture\">立即拍一张</a></p>");

  if (count == 0) {
    page += F("<p>还没有照片。</p>");
  } else {
    page += F("<table><tr><th>文件</th><th>大小</th><th>拍摄时间</th><th>预览</th></tr>");
    for (int i = count - 1; i >= 0; i--) {
      page += "<tr><td><a href=\"/" + names[i] + "\">" + names[i] + "</a></td><td>" +
              String((unsigned long)sizes[i]) + " B</td><td>" + fmtTime(shots[i]) +
              "</td><td><a href=\"/" + names[i] + "\"><img src=\"/" + names[i] +
              "\" width=\"200\"></a></td></tr>";
    }
    page += F("</table>");
  }
  server.send(200, "text/html; charset=utf-8", page);
}

static void handleCapture() {
  bool ok = captureOnce();
  server.send(200, "text/html; charset=utf-8",
              ok ? "<meta charset=utf-8><p>已拍一张，<a href=\"/\">回去看</a></p>"
                 : "<meta charset=utf-8><p>拍照失败，看串口日志</p>");
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

void setup() {
  Serial.begin(115200);
  delay(200);

  pinMode(CAM_PIN_FLASH, OUTPUT);
  digitalWrite(CAM_PIN_FLASH, LOW);

  Serial.println("\n=== ESP32-CAM 采集查看器（WiFi 常开，非功耗基线）===");

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

  connectWifi();
  syncClock();
  captureOnce();

  server.on("/", handleRoot);
  server.on("/capture", handleCapture);
  server.onNotFound(handleFile);
  server.begin();
  Serial.printf("[WEB] http://%s/\n", WiFi.localIP().toString().c_str());

  s_next_capture_ms = millis() + kCaptureIntervalMs;
}

void loop() {
  server.handleClient();

  if ((int32_t)(millis() - s_next_capture_ms) < 0) {
    return;
  }
  captureOnce();
  s_next_capture_ms += kCaptureIntervalMs;
}
