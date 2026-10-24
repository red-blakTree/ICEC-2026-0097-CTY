#!/usr/bin/env python3
"""课题 3 汇总表生成脚本（仅标准库）。

输入
    data/results.json   SpeedMeasurement 原始记录，只读不改
    SIGNAL              下面的人工转录表：PureHub 截图逐张读数（第三方 App 不并入）

输出
    data/measurements.csv   一次测速一行：点位 + 标签 + 延迟 / 速率
    data/signal.csv         一张截图一行：RSSI / SIR / 信道 / BSSID / 链路速率

口径
    - 点位编号见 POINTS；seq 在点内按时间戳升序编号，标签写入 raw_label（列名沿用旧名，存已更正的点位名称）。
    - RSSI / SIR 是截图时刻的点位级读数，不是逐轮读数：只有能明确对上点位的才填，
      对不上的留空，并写进 note。逐张证据见 signal.csv。
    - PureHub 的「距离」是按 RSSI 与频段换算的估计值（−72 dBm 时 5G 显示 16.4 m、2.4G 显示 38.9 m），不是测距，
      因此 distance_m 一律留空。
"""

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CST = timezone(timedelta(hours=8))

# 点位表。distance_m 未采集，obstruction 中「待确认」表示只能从文件夹命名推断。
POINTS = {
    "T5-01": ("教学楼", "5F", "514 门前（走廊基准）", "无（开阔走廊）"),
    "T5-02": ("教学楼", "5F", "514 教室前后门", "教室门 / 门后（待确认）"),
    "T5-03": ("教学楼", "5F", "507 后", "墙体 / 门后（待确认）"),
    "T5-04": ("教学楼", "5F", "电梯门口（基准）", "无（开阔）"),
    "T5-05": ("教学楼", "5F", "电梯轿厢内", "金属轿厢"),
    "T5-06": ("教学楼", "5F", "512 拐角", "转角"),
    "T5-07": ("教学楼", "5F", "楼梯间", "楼梯间 / 楼板"),
    "T5-08": ("教学楼", "5F", "防火门前", "金属防火门"),
    "L1-01": ("图书馆", "1F", "玻璃隔断旁", "玻璃"),
}

# results.json 的 id -> (point_id, note)
MEASUREMENT_MAP = {
    1: ("T5-01", "基准点，仅 1 轮"),
    2: ("T5-02", "3 轮"),
    3: ("T5-02", "3 轮"),
    4: ("T5-02", "3 轮"),
    5: ("T5-03", "第 1 轮"),
    6: ("T5-03", "第 2 轮"),
    7: ("T5-03", "第 3 轮"),
    8: ("T5-03", "第 4 轮"),
    9: ("T5-04", "基准点，仅 1 轮"),
    10: ("T5-05", "3 轮跨度 7 分 22 秒，可能含轿厢运行"),
    11: ("T5-05", "3 轮跨度 7 分 22 秒，可能含轿厢运行"),
    12: ("T5-05", "3 轮跨度 7 分 22 秒，可能含轿厢运行"),
    13: ("T5-06", ""),
    14: ("T5-06", ""),
    15: ("T5-06", ""),
    16: ("T5-07", ""),
    17: ("T5-07", ""),
    18: ("T5-07", ""),
    19: ("T5-08", ""),
    20: ("T5-08", ""),
    21: ("T5-08", ""),
    22: ("L1-01", "4 轮"),
    23: ("L1-01", "4 轮"),
    24: ("L1-01", "4 轮"),
    25: ("L1-01", "4 轮"),
}

# 点位级无线读数，能明确对上点位的才填。格式：(rssi_dbm, sir_db)
POINT_SIGNAL = {
    "T5-02": ("-63", "-9.9"),
    "T5-03": ("-83", "-35.3"),
    "T5-05": ("-81", "-9.9"),
    "T5-06": ("-80", "-33.4"),
    "T5-07": ("-73", "-13.3"),
    "T5-08": ("-69", "-21.5"),
    "L1-01": ("-72", "-9.2"),
}

# PureHub 截图逐张转录（口径：RSSI 以 PureHub 为准，第三方分析 App 的读数不并入）。
# point_id 为空表示归属存疑，不做合并。
SIGNAL = [
    ("514-507/504-507.1.jpg", "11:44", "T5-03", "扫描", "-78", "-35.3", 0, ""),
    ("514-507/504-507.2.jpg", "11:44", "T5-03", "概览", "-83", "", 51, "样本 30/30"),
    ("514(supplementary_survey)/514.1.jpg", "11:48", "T5-02", "概览", "-63", "", 229, "样本 30/30"),
    ("514(supplementary_survey)/514.2.jpg", "11:48", "T5-02", "扫描", "-65", "-9.9", 0, ""),
    ("in_elevator/in_elevator.3.jpg", "11:55:29", "T5-05", "扫描", "-65", "-9.9", 0, ""),
    ("in_elevator/in_elevator.4.jpg", "11:55:32", "T5-05", "扫描（暂停）", "-76", "", 0, "该行未显示 SIR"),
    ("in_elevator/in_elevator.5.jpg", "11:55:35", "T5-05", "概览", "-81", "", 103, "样本 30/30"),
    ("512(corner)/512.1.jpg", "12:01", "T5-06", "概览", "-80", "", 68, "样本 30/30"),
    ("512(corner)/512.2.jpg", "12:01", "T5-06", "扫描", "-82", "-33.4", 0, ""),
    ("stairs/stairs.3.jpg", "12:07", "T5-07", "扫描", "-74", "-13.3", 0, ""),
    ("stairs/stairs.4.jpg", "12:08", "T5-07", "概览", "-73", "", 206, "样本 30/30"),
    ("fireproof_door/fireproof_door.1.jpg", "12:16", "T5-08", "概览", "-69", "", 17, "样本 30/30"),
    ("fireproof_door/fireproof_door.2.jpg", "12:16", "T5-08", "扫描", "-80", "-21.5", 0, ""),
    ("glass/glass.1.jpg", "12:36", "L1-01", "扫描", "-72", "-9.2", 0, ""),
    ("glass/glass.2.jpg", "12:37", "L1-01", "概览", "-72", "", 129, "样本 30/30"),
]

MEASUREMENT_FIELDS = [
    "point_id", "building", "floor", "location", "obstruction", "distance_m",
    "ssid", "bssid", "band", "channel", "seq", "time",
    "rssi_dbm", "sir_db", "ping_ms", "p95_ms", "jitter_ms", "loss_pct",
    "down_mbps", "up_mbps", "raw_label", "note",
]

SIGNAL_FIELDS = [
    "point_id", "source_file", "time", "page_type", "rssi_dbm", "sir_db",
    "band", "channel", "bssid", "link_mbps", "note",
]


def load_items():
    with (ROOT / "data" / "results.json").open(encoding="utf-8") as handle:
        return json.load(handle)["items"]


def fmt_time(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, CST).strftime("%Y-%m-%d %H:%M:%S")


def build_measurements(items):
    seen = {}
    rows = []
    for item in sorted(items, key=lambda row: row["ts"]):
        point_id, note = MEASUREMENT_MAP[item["id"]]
        seen[point_id] = seen.get(point_id, 0) + 1
        building, floor, location, obstruction = POINTS[point_id]
        rssi, sir = POINT_SIGNAL.get(point_id, ("", ""))
        if rssi:
            note = f"{note}；RSSI/SIR 为点位级读数，非本轮" if note else "RSSI/SIR 为点位级读数，非本轮"
        rows.append({
            "point_id": point_id,
            "building": building,
            "floor": floor,
            "location": location,
            "obstruction": obstruction,
            "distance_m": "",
            "ssid": "wireless_2.4G",
            "bssid": "a2:1e:09:30:b6:a3",
            "band": "2.4G",
            "channel": "7",
            "seq": seen[point_id],
            "time": fmt_time(item["ts"]),
            "rssi_dbm": rssi,
            "sir_db": sir,
            "ping_ms": f"{item['ping_ms']:.2f}",
            "p95_ms": f"{item['p95_ms']:.2f}",
            "jitter_ms": f"{item['jitter_ms']:.2f}",
            "loss_pct": f"{item['loss_pct']:.1f}",
            "down_mbps": f"{item['down_mbps']:.2f}",
            "up_mbps": f"{item['up_mbps']:.2f}",
            "raw_label": item["label"],
            "note": note,
        })
    rows.sort(key=lambda row: (row["point_id"], row["seq"]))
    return rows


def build_signal():
    rows = []
    for path, time, point_id, page, rssi, sir, link, note in SIGNAL:
        rows.append({
            "point_id": point_id,
            "source_file": f"picture/{path}",
            "time": time,
            "page_type": page,
            "rssi_dbm": rssi,
            "sir_db": sir,
            "band": "2.4 GHz",
            "channel": "7（2442 MHz）",
            "bssid": "a2:1e:09:30:b6:a3",
            "link_mbps": link or "",
            "note": note,
        })
    return rows


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    items = load_items()
    measurements = build_measurements(items)
    signal = build_signal()
    write_csv(ROOT / "data" / "measurements.csv", MEASUREMENT_FIELDS, measurements)
    write_csv(ROOT / "data" / "signal.csv", SIGNAL_FIELDS, signal)
    print(f"measurements.csv: {len(measurements)} 行")
    print(f"signal.csv: {len(signal)} 行")


if __name__ == "__main__":
    main()
