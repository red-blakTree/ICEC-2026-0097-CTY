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

// ── 功耗日志（5V 输入端的模型电流，典型值，未标定）──
static const float kModelIdleMa = 45.0f;   // 240 MHz 空转 + AMS1117 静态电流
static const float kModelShotMa = 180.0f;  // 摄像头 init + JPEG 捕获
static const float kModelSaveMa = 50.0f;   // SD 卡写入

// 电压采样需要外接分压：5V ──100k── IO16 ──100k── GND
static const bool  kHasVbatDivider = false;
static const int   kPinVbat        = 16;
static const float kDividerRatio   = 2.0f;

static const uint32_t kPowerLogIntervalMs = 5UL * 60UL * 1000UL;
static const char *kPowerLogPath = "/POWER.CSV";

// 跑正式数据集前临时改为 true 烧一次：删除 SD 上的 IMG_*.jpg 与 POWER.CSV
static const bool kClearDataOnBoot = false;
static uint32_t s_next_index = 1;
static uint32_t s_next_capture_ms = 0;
static uint32_t s_next_log_ms = 0;
static uint32_t s_last_sample_ms = 0;
static float    s_energy_mwh = 0.0f;

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

static int readV5Mv() {
  if (!kHasVbatDivider) {
    return -1;
  }
  return (int)(analogReadMilliVolts(kPinVbat) * kDividerRatio + 0.5f);
}

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

static const char kIndexHtml[] PROGMEM = R"HTML(<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ESP32-CAM 采集</title>
<style>
:root{--bg:#0e1014;--card:#161a21;--line:#252a34;--text:#e7eaf0;--muted:#8b93a5;--accent:#4f8cff;--ok:#3ecf8e}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:14px/1.55 system-ui,-apple-system,"Segoe UI","Noto Sans SC",sans-serif;
  background-image:radial-gradient(1200px 600px at 80% -10%,rgba(79,140,255,.10),transparent)}
header{position:sticky;top:0;z-index:9;display:flex;flex-wrap:wrap;gap:14px;align-items:center;
  padding:14px 20px;border-bottom:1px solid var(--line);
  background:rgba(14,16,20,.82);backdrop-filter:blur(10px)}
h1{margin:0;font-size:15px;font-weight:650;letter-spacing:.4px;display:flex;align-items:center;gap:8px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 3px rgba(62,207,142,.16)}
.stat{color:var(--muted);font-size:13px;white-space:nowrap}
.stat b{color:var(--text);font-weight:600;font-variant-numeric:tabular-nums;margin-left:4px}
.spacer{flex:1}
.btn{color:var(--text);text-decoration:none;border:1px solid var(--line);padding:6px 12px;
  border-radius:8px;font-size:13px;transition:.15s}
.btn:hover{border-color:var(--accent);color:var(--accent)}
main{padding:20px;display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(230px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;
  transition:transform .15s,border-color .15s;animation:in .25s ease-out}
@keyframes in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.card:hover{transform:translateY(-2px);border-color:var(--accent)}
.card img{width:100%;aspect-ratio:4/3;object-fit:cover;display:block;background:#0a0c0f}
.meta{padding:10px 12px}
.name{font-size:13px;font-weight:600}
.sub{color:var(--muted);font-size:12px;margin-top:2px;font-variant-numeric:tabular-nums}
.empty{grid-column:1/-1;text-align:center;color:var(--muted);padding:48px}
</style>
</head><body>
<header>
  <h1><span class="dot"></span>ESP32-CAM 采集</h1>
  <div class="stat">IP<b id="ip">-</b></div>
  <div class="stat">现在<b id="now">-</b></div>
  <div class="stat">运行<b id="up">-</b></div>
  <div class="stat">照片<b id="cnt">-</b></div>
  <span class="spacer"></span>
  <a class="btn" href="/POWER.CSV">下载 POWER.CSV</a>
  <a class="btn" href="/capture">立即拍一张</a>
</header>
<main id="grid"><div class="empty">加载中…</div></main>
<script>
const grid=document.getElementById('grid');
const el=id=>document.getElementById(id);
let ready=false;
const fmtUp=s=>{const h=(s/3600)|0,m=((s%3600)/60)|0;return h?h+'h '+m+'m':m+'m '+(s%60)+'s';};
async function tick(){
  try{
    const d=await (await fetch('/api.json',{cache:'no-store'})).json();
    el('ip').textContent=d.ip; el('now').textContent=d.now;
    el('up').textContent=fmtUp(d.uptime); el('cnt').textContent=d.count;
    if(!ready){grid.innerHTML='';ready=true;}
    if(!d.count){grid.innerHTML='<div class="empty">还没有照片</div>';return;}
    for(const f of d.files){
      let c=document.getElementById(f.name);
      const sub=f.time+' · '+(f.size/1024).toFixed(1)+' KB';
      if(!c){
        c=document.createElement('div'); c.className='card'; c.id=f.name;
        c.innerHTML='<a href="/'+f.name+'"><img loading="lazy" src="/'+f.name+'"></a>'+
          '<div class="meta"><div class="name">'+f.name+'</div><div class="sub">'+sub+'</div></div>';
        grid.prepend(c);
      }else{
        c.querySelector('.sub').textContent=sub;
      }
    }
  }catch(e){}
}
tick(); setInterval(tick,8000);
</script>
</body></html>)HTML";

// 状态 + 照片列表，供网页每 8 秒拉取一次；按目录顺序返回，新图由前端插到最前
static void handleApi() {
  String json;
  json.reserve(3072);
  json += "{\"ip\":\"" + WiFi.localIP().toString() + "\",\"now\":\"" +
          fmtTime(time(nullptr)) + "\",\"uptime\":" + String(millis() / 1000) +
          ",\"files\":[";

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

  clearDataIfRequested();
  powerLogHeaderIfNeeded();
  s_last_sample_ms = millis();
  s_next_log_ms = millis() + kPowerLogIntervalMs;

  connectWifi();
  syncClock();
  captureOnce();

  server.on("/", handleRoot);
  server.on("/api.json", handleApi);
  server.on("/capture", handleCapture);
  server.onNotFound(handleFile);
  server.begin();
  Serial.printf("[WEB] http://%s/\n", WiFi.localIP().toString().c_str());

  s_next_capture_ms = millis() + kCaptureIntervalMs;
}

void loop() {
  server.handleClient();

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
