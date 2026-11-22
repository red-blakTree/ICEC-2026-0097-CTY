# 统一入口：所有目标都在仓库根目录执行；分模块的详细命令仍以各 README 为准。
# 依赖：python3 常备；topic8 需要 01-Field-Discovery/topic_8/.venv；
#       speedtest 需要 cargo；firmware 需要 arduino-cli（默认 02-20Days-Challenge/arduino-cli）与 .arduino/。

PYTHON    ?= python3
MPLCONFIG ?= /tmp/mplcfg
ARDUINO_ENV = ARDUINO_DIRECTORIES_DATA=$$PWD/.arduino/data ARDUINO_DIRECTORIES_USER=$$PWD/.arduino/user
ARDUINO_CLI ?= ./arduino-cli

.DEFAULT_GOAL := help

help:
	@echo "make check     全仓库检查：Markdown 断链 + 暂存区大文件（>25 MB 拦截）"
	@echo "make verify    02 自检 34 项 + 7 个回归测试 + 全仓库检查"
	@echo "make data      重跑课题 3 建表脚本，并校验产物与已提交版本一致"
	@echo "make topic8    课题 8 不变性自检（需 topic_8/.venv）"
	@echo "make speedtest 测速服务 Rust 测试（需 cargo 与网络取依赖）"
	@echo "make firmware  编译三个 ESP32-CAM 固件（需 arduino-cli 与 .arduino/，较慢）"

check:
	$(PYTHON) tools/check_repo.py

verify: check
	cd 02-20Days-Challenge && $(PYTHON) measurement/verify.py
	cd 02-20Days-Challenge && $(PYTHON) -m unittest discover -s measurement -p 'test_*.py'

data:
	cd 01-Field-Discovery/topic_3 && $(PYTHON) src/build_dataset.py && $(PYTHON) src/build_delivery.py
	git diff --exit-code --stat -- 01-Field-Discovery/topic_3/raw_data

topic8:
	cd 01-Field-Discovery/topic_8 && MPLCONFIGDIR=$(MPLCONFIG) .venv/bin/python src/v6/invariants.py

speedtest:
	cd 01-Field-Discovery/topic_3/SpeedMeasurement && cargo test

firmware:
	cd 02-20Days-Challenge && $(ARDUINO_ENV) $(ARDUINO_CLI) compile --fqbn esp32:esp32:esp32cam --build-path .arduino/build-viewer firmware/esp32cam-viewer/viewer
	cd 02-20Days-Challenge && $(ARDUINO_ENV) $(ARDUINO_CLI) compile --fqbn esp32:esp32:esp32cam --build-path .arduino/build-powersave firmware/esp32cam-powersave/powersave
	cd 02-20Days-Challenge && $(ARDUINO_ENV) $(ARDUINO_CLI) compile --fqbn esp32:esp32:esp32cam --build-path .arduino/build-demo firmware/esp32cam-sleep-demo/sleep_demo
