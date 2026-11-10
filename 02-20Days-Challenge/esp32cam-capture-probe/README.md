# ESP32-CAM 拍照电流探针（标定用临时固件）

用来给 `kModelShotMa` / `kModelSaveMa` 标定一个可读的稳定值：不连 WiFi、不开网页、不睡眠，
**连续拍照**，让 0.01 A 分辨率的 USB 表读到「拍照 + 写卡」工况下的平均电流。

- `SAVE_TO_SD = 1`：拍照 + 写卡（对应 `kModelShotMa` + `kModelSaveMa`）
- `SAVE_TO_SD = 0`：拍完丢帧（只对应 `kModelShotMa`）

> 为什么需要它：单次拍照只有 `capture=0 ms / save=60–90 ms`，表按秒刷新根本抓不到峰值；
> 连续拍照把占空比拉到接近 100 %，表才能读到稳定值。

编译与烧录（`build-probe` 目录是本地构建缓存，已被 gitignore）：

```bash
cd 02-20Days-Challenge
export ARDUINO_DIRECTORIES_DATA=$PWD/.arduino/data ARDUINO_DIRECTORIES_USER=$PWD/.arduino/user
./arduino-cli compile --fqbn esp32:esp32:esp32cam --build-path .arduino/build-probe esp32cam-capture-probe/capture_probe
./arduino-cli upload -p /dev/ttyUSB0 --fqbn esp32:esp32:esp32cam --build-path .arduino/build-probe esp32cam-capture-probe/capture_probe
```

注意：这个固件会以一秒两张左右的速度连拍写卡，SD 卡很快被填满，**标定完就刷回**
`esp32cam-powersave` 或 `esp32cam-viewer`。拍照段的测量口径见
[power-measure-2026-11-10](../power-measure-2026-11-10/README.md)。
