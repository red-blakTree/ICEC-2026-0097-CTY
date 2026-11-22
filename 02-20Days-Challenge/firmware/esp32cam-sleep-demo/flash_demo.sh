#!/bin/sh
# 宿主机烧录脚本：容器内先编译好 .arduino/build-demo，这里只做 upload。
# 用法（容器内）：
#   distrobox-host-exec 02-20Days-Challenge/firmware/esp32cam-sleep-demo/flash_demo.sh
# 端口可用 PORT 覆盖；arduino-cli 在 PATH 时用 ARDUINO_CLI=arduino-cli。
set -eu
cd "$(dirname "$0")/../.."
export ARDUINO_DIRECTORIES_DATA=$PWD/.arduino/data
export ARDUINO_DIRECTORIES_USER=$PWD/.arduino/user
ARDUINO_CLI="${ARDUINO_CLI:-./arduino-cli}"
"$ARDUINO_CLI" upload -p "${PORT:-/dev/ttyUSB0}" --fqbn esp32:esp32:esp32cam --input-dir .arduino/build-demo
