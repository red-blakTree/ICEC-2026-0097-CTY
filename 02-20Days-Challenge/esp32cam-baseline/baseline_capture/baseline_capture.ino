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

// ── 功耗日志（5V 输入端的模型电流，典型值，未在硬件上标定）──
static const float kModelIdleMa = 45.0f;   // 240 MHz 空转 + AMS1117 静态电流
static const float kModelShotMa = 180.0f;  // 摄像头 init + JPEG 捕获
static const float kModelSaveMa = 50.0f;   // SD 卡写入

// 电压采样需要外接分压：5V ──100k── IO16 ──100k── GND
// 没接分压时保持 false：CSV 的 v5_mv 列写 -1，功耗按 5000 mV 名义值计算。
static const bool  kHasVbatDivider = false;
static const int   kPinVbat        = 16;
static const float kDividerRatio   = 2.0f;  // (R1 + R2) / R2

static const uint32_t kPowerLogIntervalMs = 5UL * 60UL * 1000UL;
static const char *kPowerLogPath = "/POWER.CSV";

// 跑正式数据集前临时改为 true 烧一次：删除 SD 上的 IMG_*.jpg 与 POWER.CSV
static const bool kClearDataOnBoot = false;

static uint32_t s_next_index = 1;       // 下一张照片的编号，启动时从 SD 卡已有文件续号
static uint32_t s_next_capture_ms = 0;  // 下一张照片的毫秒时刻
static uint32_t s_next_log_ms = 0;      // 下一次功耗采样的毫秒时刻
static uint32_t s_last_sample_ms = 0;   // 上一次功耗采样的毫秒时刻
static float    s_energy_mwh = 0.0f;    // 累计能耗（模型推算）

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

static int readV5Mv() {
  if (!kHasVbatDivider) {
    return -1;  // 未接分压，电压不可测
  }
  return (int)(analogReadMilliVolts(kPinVbat) * kDividerRatio + 0.5f);
}

// 用空转模型电流对上一区间积分，累计得到 mWh
static void accumulateEnergy() {
  uint32_t now = millis();
  uint32_t dt_ms = now - s_last_sample_ms;
  s_last_sample_ms = now;
  int mv = readV5Mv();
  float v = (mv > 0) ? mv / 1000.0f : 5.0f;
  s_energy_mwh += kModelIdleMa * v * ((float)dt_ms / 3600000.0f);
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

// i_ma 是 window_s 窗口内的平均电流，由模型推算，不是实测值
static void powerLogAppend(const char *event, uint32_t window_s, float i_ma) {
  int mv = readV5Mv();
  float v = (mv > 0) ? mv / 1000.0f : 5.0f;
  char line[128];
  snprintf(line, sizeof(line), "%lu,%s,%lu,%d,%.1f,%.1f,%.4f\n",
           (unsigned long)(millis() / 1000), event, (unsigned long)window_s,
           mv, i_ma, i_ma * v, s_energy_mwh);
  File f = SD_MMC.open(kPowerLogPath, FILE_APPEND);
  if (!f) {
    Serial.printf("[WARN] 无法追加 %s\n", kPowerLogPath);
    return;
  }
  f.print(line);
  f.close();
  Serial.printf("[PWR] %s", line);
}

static void powerLogSample() {
  accumulateEnergy();
  powerLogAppend("SAMPLE", kPowerLogIntervalMs / 1000, kModelIdleMa);
}

// 一个采集周期的平均电流：实测耗时 × 模型电流，其余时间按空转算
static float cycleAverageMa(uint32_t shot_ms, uint32_t save_ms) {
  float period_s = kCaptureIntervalMs / 1000.0f;
  float shot_s = shot_ms / 1000.0f;
  float save_s = save_ms / 1000.0f;
  float idle_s = period_s - shot_s - save_s;
  if (idle_s < 0) {
    idle_s = 0;
  }
  return (kModelShotMa * shot_s + kModelSaveMa * save_s + kModelIdleMa * idle_s) / period_s;
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

  uint32_t shot_ms = t_shot - t_start;
  uint32_t save_ms = t_saved - t_shot;
  powerLogAppend("CAPTURE", kCaptureIntervalMs / 1000, cycleAverageMa(shot_ms, save_ms));
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

  clearDataIfRequested();

  powerLogHeaderIfNeeded();
  s_last_sample_ms = millis();
  s_next_log_ms = millis() + kPowerLogIntervalMs;
  Serial.printf("[INFO] 功耗日志 %s：每 %lu s 一行（电流为模型推算，非实测）\n",
                kPowerLogPath, (unsigned long)(kPowerLogIntervalMs / 1000));

  s_next_index = nextIndexFromSd();
  Serial.printf("[OK] 从 %s 开始编号\n", s_next_index == 1 ? "IMG_00001.jpg" : "已有照片之后");

  Serial.println("[INFO] 上电立即拍一张，随后每小时一张");
  captureOnce();
  s_next_capture_ms = millis() + kCaptureIntervalMs;
}

void loop() {
  // 每 5 分钟采一次样，写一行功耗日志
  if ((int32_t)(millis() - s_next_log_ms) >= 0) {
    powerLogSample();
    s_next_log_ms += kPowerLogIntervalMs;
  }

  // 未到点：CPU 空转（基线就是要这样，不睡眠、不降频）
  if ((int32_t)(millis() - s_next_capture_ms) < 0) {
    return;
  }
  captureOnce();
  s_next_capture_ms += kCaptureIntervalMs;
}
