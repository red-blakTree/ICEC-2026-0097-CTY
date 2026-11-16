# ESP32-CAM 拍照电流探针（标定用临时固件）

> 用途：给 `kModelShotMa` / `kModelSaveMa` 标定一个可读的稳定值。**不连 WiFi、不开网页、不睡眠，连续拍照**，让 0.01 A 分辨率的 USB 表读到“拍照 + 写卡”工况下的平均电流。

## 1. 为什么需要它

单次拍照只有 `capture=0 ms / save=60–90 ms`，USB 表按秒刷新根本抓不到峰值；连续拍照把占空比拉到接近 100 %，表才能读到稳定值。

## 2. 两种模式

```cpp
#define SAVE_TO_SD 1
```

| `SAVE_TO_SD` | 行为 | 对应 |
|---|---|---|
| `1` | 拍照 + 写卡 | `kModelShotMa` + `kModelSaveMa` |
| `0` | 拍照后丢帧 | 只对应 `kModelShotMa` |

## 3. 编译与烧录

```bash
cd 02-20Days-Challenge
export ARDUINO_DIRECTORIES_DATA=$PWD/.arduino/data ARDUINO_DIRECTORIES_USER=$PWD/.arduino/user
./arduino-cli compile --fqbn esp32:esp32:esp32cam --build-path .arduino/build-probe firmware/esp32cam-capture-probe/capture_probe
./arduino-cli upload -p /dev/ttyUSB0 --fqbn esp32:esp32:esp32cam --build-path .arduino/build-probe firmware/esp32cam-capture-probe/capture_probe
```

烧录/看串口在宿主机执行（`distrobox-host-exec`）；转换板 DTR/RTS 接 GPIO0/EN，`open()` 默认会把 GPIO0 拉低，需释放控制线再复位。

## 4. 它能测什么、不能测什么

- **能测**：无 WiFi 条件下“拍照 + 写卡”的平均电流（表读稳定值），用于回填 `kModelShotMa` / `kModelSaveMa`。
- **不能测**：60–90 ms 的瞬时峰值（表仍是秒级窗口）；也不能替代基线 P3（基线是 WiFi 关联 + 拍照写卡，和本探针的无 WiFi 条件不同）。
- 现有 `0.13–0.16 A` 是 **WiFi 关联下**的连拍，属于偏保守的 P3 值；无 WiFi 的拍照电流仍未测。

## 5. 注意

- 这个固件会以一秒两张左右的速度连拍写卡，SD 卡很快被填满，**标定完就刷回** `esp32cam-powersave` 或 `esp32cam-viewer`。
- 测量时表仍串在 5 V 输入端；读数用 `A × V` 或累计 `mWh ÷ 时间` 算，不要用 `W` 反推电流（`W` 是时段平均）。
- 相关测量口径见 [measurement/README.md](../../measurement/README.md)。
