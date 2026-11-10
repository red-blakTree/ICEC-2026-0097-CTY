/*
 * ESP32-CAM 拍照电流探针（临时固件，不连 WiFi、不开网页、不睡眠）
 *
 * 为什么需要它：USB 电压电流表精度 0.01 A、刷新慢，单次拍照只有 0.3–0.8 s，
 * 峰值读不出来。本固件连续拍照，让表读到稳定值，用来标定拍照/写卡电流。
 *
 * SAVE_TO_SD = 1：拍照 + 写卡（对应固件里的 kModelShotMa + kModelSaveMa）
 * SAVE_TO_SD = 0：拍照后丢帧（对应 kModelShotMa）
 *
 * 板卡：AI-Thinker ESP32-CAM
 * FQBN：esp32:esp32:esp32cam:PSRAM=enabled
 */

#include "esp_camera.h"
#include "SD_MMC.h"

#define SAVE_TO_SD 1

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

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[FATAL] esp_camera_init: %s\n", esp_err_to_name(err));
    return false;
  }
  return true;
}

static uint32_t nextIndexFromSd() {
  uint32_t max_idx = 0;
  File root = SD_MMC.open("/");
  if (!root) {
    return 1;
  }
  for (File f = root.openNextFile(); f; f = root.openNextFile()) {
    const char *base = strrchr(f.name(), '/');
    base = base ? base + 1 : f.name();
    unsigned idx = 0;
    if (sscanf(base, "IMG_%u.jpg", &idx) == 1 && idx > max_idx) {
      max_idx = idx;
    }
  }
  root.close();
  return max_idx + 1;
}

void setup() {
  Serial.begin(115200);
  delay(300);

  pinMode(CAM_PIN_FLASH, OUTPUT);
  digitalWrite(CAM_PIN_FLASH, LOW);

  Serial.println("\n=== ESP32-CAM 拍照电流探针（不连 WiFi，连续拍照）===");
  if (!initCamera()) {
    while (true) {
      delay(1000);
    }
  }
  Serial.println("[OK] 摄像头初始化完成");

#if SAVE_TO_SD
  SD_MMC.setPins(kSdClk, kSdCmd, kSdD0);
  if (!SD_MMC.begin("/sdcard", true)) {
    Serial.println("[FATAL] SD 卡初始化失败");
    while (true) {
      delay(1000);
    }
  }
  s_next_index = nextIndexFromSd();
  Serial.printf("[OK] SD 卡初始化完成，从 IMG_%05lu.jpg 开始\n", (unsigned long)s_next_index);
#else
  Serial.println("[INFO] SAVE_TO_SD=0：只拍照不写卡");
#endif
  Serial.println("[INFO] 表上看稳定值即为该模式的平均电流");
}

void loop() {
  uint32_t t0 = millis();
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[ERR] 拍照失败");
    delay(500);
    return;
  }
  uint32_t t_shot = millis();
  size_t len = fb->len;
  uint32_t t_save = t_shot;

#if SAVE_TO_SD
  char path[32];
  snprintf(path, sizeof(path), "/IMG_%05lu.jpg", (unsigned long)s_next_index);
  File f = SD_MMC.open(path, FILE_WRITE);
  if (f) {
    f.write(fb->buf, fb->len);
    f.close();
  }
  s_next_index++;
  t_save = millis();
#endif

  esp_camera_fb_return(fb);
  Serial.printf("[CAP] size=%luB shot=%lums save=%lums\n", (unsigned long)len,
                (unsigned long)(t_shot - t0), (unsigned long)(t_save - t_shot));
  delay(200);
}
