/*
 * ESP32-CAM 基础采集 —— P0 功耗基线
 *
 * 行为：上电初始化摄像头与 SD 卡 -> 立即拍一张 -> 之后每 1 小时拍一张 JPEG 存 SD 卡。
 * 特点：CPU 240 MHz 满速、WiFi 全程关闭、不降频、不进入任何睡眠、不做任何外设断电。
 *
 * 用途：作为"项目一：极致省电"的对照基线。后续 Deep-Sleep / 断电控制 / 降频版本
 * 的电流与续航数据，都应该和本版本对比。
 *
 * 板卡：AI-Thinker ESP32-CAM
 * FQBN：esp32:esp32:esp32cam:PSRAM=enabled（PSRAM 必须开启，否则高分辨率存图会失败）
 */

#include "esp_camera.h"
#include "SD_MMC.h"

// 采集周期：1 小时。上板验证时可临时改小，例如 10 秒 = 10000UL。
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

// SD 卡：1-bit SDMMC 模式
static const int kSdClk = 14;
static const int kSdCmd = 15;
static const int kSdD0  = 2;

static uint32_t s_next_index = 1;       // 下一张照片的编号，启动时从 SD 卡已有文件续号
static uint32_t s_next_capture_ms = 0;  // 下一张照片的毫秒时刻

static void fatal(const char *msg) {
  Serial.printf("[FATAL] %s\n", msg);
  while (true) {
    delay(1000);
  }
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
  config.frame_size   = FRAMESIZE_SVGA;  // 800x600
  config.jpeg_quality = 12;
  config.fb_count     = 1;
  config.fb_location  = CAMERA_FB_IN_PSRAM;
  config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[ERR] esp_camera_init 失败: %s\n", esp_err_to_name(err));
    return false;
  }
  return true;
}

static bool initSdCard() {
  SD_MMC.setPins(kSdClk, kSdCmd, kSdD0);
  return SD_MMC.begin("/sdcard", true);
}

// 扫描 SD 根目录中已有的 IMG_*.jpg，返回下一个可用编号，避免重启后覆盖旧照片
static uint32_t nextIndexFromSd() {
  uint32_t max_idx = 0;
  File root = SD_MMC.open("/");
  if (!root) {
    Serial.println("[WARN] 无法打开 SD 根目录，编号从 1 开始");
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

static void captureOnce() {
  uint32_t t_start = millis();

  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.printf("[ERR] 第 %lu 张拍照失败（esp_camera_fb_get 返回 NULL）\n",
                  (unsigned long)s_next_index);
    return;
  }
  uint32_t t_shot = millis();

  char path[32];
  snprintf(path, sizeof(path), "/IMG_%05lu.jpg", (unsigned long)s_next_index);

  File f = SD_MMC.open(path, FILE_WRITE);
  if (!f) {
    Serial.printf("[ERR] 无法创建 %s\n", path);
    esp_camera_fb_return(fb);
    return;
  }
  size_t written = f.write(fb->buf, fb->len);
  f.close();
  uint32_t t_saved = millis();
  size_t size = fb->len;
  esp_camera_fb_return(fb);

  if (written != size) {
    Serial.printf("[ERR] %s 写入不完整 %u/%u\n", path,
                  (unsigned)written, (unsigned)size);
    return;
  }

  Serial.printf("[CAP] %s size=%luB capture=%lums save=%lums uptime=%lus\n",
                path, (unsigned long)size,
                (unsigned long)(t_shot - t_start),
                (unsigned long)(t_saved - t_shot),
                (unsigned long)(millis() / 1000));
  s_next_index++;
}

void setup() {
  Serial.begin(115200);
  delay(200);

  pinMode(CAM_PIN_FLASH, OUTPUT);
  digitalWrite(CAM_PIN_FLASH, LOW);  // 关闭闪光灯

  Serial.println("\n=== ESP32-CAM 基础采集（P0 基线，未做任何省电优化）===");
  Serial.printf("采集周期: %lu s\n", (unsigned long)(kCaptureIntervalMs / 1000));

  if (!initCamera()) {
    fatal("摄像头初始化失败");
  }
  Serial.println("[OK] 摄像头初始化完成");

  if (!initSdCard()) {
    Serial.println("[WARN] SD 卡初始化失败，每 5 秒重试（插卡后会自动继续）");
    while (!initSdCard()) {
      delay(5000);
    }
  }
  Serial.println("[OK] SD 卡初始化完成");

  s_next_index = nextIndexFromSd();
  Serial.printf("[OK] 从 %s 开始编号\n", s_next_index == 1 ? "IMG_00001.jpg" : "已有照片之后");

  Serial.println("[INFO] 上电立即拍一张，随后每小时一张");
  captureOnce();
  s_next_capture_ms = millis() + kCaptureIntervalMs;
}

void loop() {
  // 未到点：CPU 空转（基线就是要这样，不睡眠、不降频）
  if ((int32_t)(millis() - s_next_capture_ms) < 0) {
    return;
  }
  captureOnce();
  s_next_capture_ms += kCaptureIntervalMs;
}
