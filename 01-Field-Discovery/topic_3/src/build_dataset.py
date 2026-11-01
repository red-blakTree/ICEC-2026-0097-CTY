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
    - PureHub 的「距离」是按 RSSI 换算的估计值，不是测距，
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
    "T5-02": ("教学楼", "5F", "514 后门（同走廊，约 8.5 m，514 前门→后门）", "空气（测距点，无遮挡）"),
    "T5-03": ("教学楼", "5F", "507 后门（同走廊，约 42.5 m，514 前门→507 后门）", "空气（测距点，无遮挡）"),
    "T5-04": ("教学楼", "5F", "电梯门口（基准）", "无（开阔）"),
    "T5-05": ("教学楼", "5F", "电梯轿厢内", "金属轿厢"),
    "T5-06": ("教学楼", "5F", "512 拐角", "转角"),
    "T5-07": ("教学楼", "5F", "楼梯间", "楼梯间 / 楼板"),
    "T5-08": ("教学楼", "5F", "防火门前", "金属防火门"),
    "L1-01": ("图书馆", "1F", "玻璃隔断旁", "玻璃"),
    "D-01": ("宿舍", "6F", "617 房间内桌面（紧邻笔记本）", "无（同房间近场）"),
    "D-02": ("宿舍", "6F", "617→618 隔墙后", "混凝土 + 瓷砖隔断墙（约 10 cm）"),
}

# results.json 的 id -> (point_id, note)
MEASUREMENT_MAP = {
    1: ("T5-01", "基准点，10-24 首轮"),
    2: ("T5-02", "3 轮"),
    3: ("T5-02", "3 轮"),
    4: ("T5-02", "3 轮"),
    5: ("T5-03", "第 1 轮（上传失败，up = 0）"),
    6: ("T5-03", "第 2 轮"),
    7: ("T5-03", "第 3 轮（上传失败，up = 0）"),
    8: ("T5-03", "第 4 轮"),
    9: ("T5-04", "基准点，10-24 首轮"),
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
    26: ("T5-01", "10-25 补测 1/3"),
    27: ("T5-01", "10-25 补测 2/3"),
    28: ("T5-01", "10-25 补测 3/3"),
    29: ("T5-04", "10-25 补测 1/3"),
    30: ("T5-04", "10-25 补测 2/3"),
    31: ("T5-04", "10-25 补测 3/3"),
    32: ("D-01", "参照点，3 轮"),
    33: ("D-01", "参照点，3 轮"),
    34: ("D-01", "参照点，3 轮"),
    35: ("D-02", "隔墙，3 轮"),
    36: ("D-02", "隔墙，3 轮"),
    37: ("D-02", "隔墙，3 轮"),
    38: ("T5-03", "11-01 补测 1/3（前门→前门，约 34 m；本行 RSSI/SIR 取自 10-24 的 42.5 m，11-01 同位置扫描 −74 ~ −77）"),
    39: ("T5-03", "11-01 补测 2/3（前门→前门，约 34 m；本行 RSSI/SIR 取自 10-24 的 42.5 m，11-01 同位置扫描 −74 ~ −77）"),
    40: ("T5-03", "11-01 补测 3/3（前门→前门，约 34 m；本行 RSSI/SIR 取自 10-24 的 42.5 m，11-01 同位置扫描 −74 ~ −77）"),
}

# 点位级无线读数，能明确对上点位的才填。格式：(rssi_dbm, sir_db)
POINT_SIGNAL = {
    "T5-01": ("-61", "-12.4"),
    "T5-02": ("-63", "-9.9"),
    "T5-03": ("-83", "-35.3"),
    "T5-05": ("-81", "-9.9"),
    "T5-06": ("-80", "-33.4"),
    "T5-07": ("-73", "-13.3"),
    "T5-08": ("-69", "-21.5"),
    "L1-01": ("-72", "-9.2"),
    "T5-04": ("-57", "17.0"),
    "D-01": ("-55", "32.2"),
    "D-02": ("-74", "4.2"),
}

# PureHub 截图逐张转录（口径：RSSI 以 PureHub 为准，第三方分析 App 的读数不并入）。
# point_id 为空表示归属存疑，不做合并。
SIGNAL = [
    ("514-507/504-507.1.jpg", "11:44", "T5-03", "扫描", "-78", "-35.3", 0, ""),
    ("514-507/504-507.2.jpg", "11:44", "T5-03", "概览", "-83", "", 51, "样本 30/30"),
    ("514(supplementary_survey)/514.1.jpg", "11:48", "T5-02", "概览", "-63", "", 229, "样本 30/30"),
    ("514(supplementary_survey)/514.2.jpg", "11:48", "T5-02", "扫描", "-65", "-9.9", 0, ""),
    ("in_elevator/in_elevator.3.jpg", "11:55:29", "T5-05", "扫描", "-65", "-9.9", 0, ""),
    ("in_elevator/in_elevator.4.jpg", "11:55:32", "T5-05", "扫描", "-76", "", 0, "该行未显示 SIR；界面「暂停扫描」是按钮，扫描未停止"),
    ("in_elevator/in_elevator.5.jpg", "11:55:35", "T5-05", "概览", "-81", "", 103, "样本 30/30"),
    ("512(corner)/512.1.jpg", "12:01", "T5-06", "概览", "-80", "", 68, "样本 30/30"),
    ("512(corner)/512.2.jpg", "12:01", "T5-06", "扫描", "-82", "-33.4", 0, ""),
    ("stairs/stairs.3.jpg", "12:07", "T5-07", "扫描", "-74", "-13.3", 0, ""),
    ("stairs/stairs.4.jpg", "12:08", "T5-07", "概览", "-73", "", 206, "样本 30/30"),
    ("fireproof_door/fireproof_door.1.jpg", "12:16", "T5-08", "概览", "-69", "", 17, "样本 30/30"),
    ("fireproof_door/fireproof_door.2.jpg", "12:16", "T5-08", "扫描", "-80", "-21.5", 0, ""),
    ("glass/glass.1.jpg", "12:36", "L1-01", "扫描", "-72", "-9.2", 0, ""),
    ("glass/glass.2.jpg", "12:37", "L1-01", "概览", "-72", "", 129, "样本 30/30"),
    ("datum_mark/514-before.1.jpg", "15:30", "T5-01", "概览", "-57", "", 258, "仅 16/30 样本，测速前"),
    ("datum_mark/514-before.2.jpg", "15:30", "T5-01", "扫描", "-56", "-3.3", 0, "测速前；扫描页距离显示 ~6.2 m"),
    ("datum_mark/514-after.1.jpg", "15:32", "T5-01", "扫描", "-64", "-12.4", 0, "测速后；扫描页距离显示 ~15.5 m"),
    ("datum_mark/514-after.2.jpg", "15:32", "T5-01", "概览", "-61", "", 258, "仅 23/30 样本，测速后"),
    ("datum_mark/elevator-before.1.jpg", "15:33", "T5-04", "概览", "-56", "", 258, "样本 30/30；测速前"),
    ("datum_mark/elevator-before.2.jpg", "15:33", "T5-04", "扫描", "-64", "-12.4", 0, "测速前；扫描页距离显示 ~15.5 m"),
    ("datum_mark/elevator-after.1.jpg", "15:35", "T5-04", "扫描", "-52", "17.0", 0, "测速后；链路 229 Mbps"),
    ("datum_mark/elevator-after.2.jpg", "15:36", "T5-04", "概览", "-57", "", 286, "样本 30/30；测速后"),
    ("dormitory/dormitory-before.1.jpg", "20:18", "D-01", "概览", "-59", "", 286, "仅 2/30 样本，历史未刷新"),
    ("dormitory/dormitory-before.2.jpg", "20:18", "D-01", "扫描", "-55", "32.2", 0, "扫描页距离显示 ~5.5 m"),
    ("dormitory/dormitory-after.1.jpg", "20:20", "D-02", "扫描", "-74", "4.2", 0, "扫描页距离显示 ~49.0 m"),
    ("dormitory/dormitory-after.2.jpg", "20:20", "D-02", "概览", "-57", "", 172, "仅 11/30 样本，与扫描页差 17 dB"),
    # 11-01 补测（supplementary_data）：514 基准为距笔记本 1 cm 的近场读数，与 10-25 的 1 m 基准不可比。
    ("supplementary_data/514-nearfield.1.jpg", "14:45", "T5-01", "扫描", "-52", "-1.8", 229, "1 cm 近场；列表行 -50"),
    ("supplementary_data/514-nearfield.2.jpg", "14:46", "T5-01", "扫描", "-41", "13.7", 286, "1 cm 近场；列表行 -43"),
    ("supplementary_data/514-nearfield.3.jpg", "14:46", "T5-01", "扫描", "-40", "12.8", 229, "1 cm 近场；列表行 -42"),
    ("supplementary_data/514-513.1.jpg", "14:46", "T5-02", "概览", "-67", "", 229, "约 8.5 m；样本 30/30"),
    ("supplementary_data/514-513.2.jpg", "14:47", "T5-02", "扫描", "-72", "-15.6", 0, "约 8.5 m；与上一行概览差 5 dB"),
    ("supplementary_data/514-511.jpg", "14:47", "", "扫描", "-75", "-19.0", 0, "距离阶梯：514→511 前门约 17 m，非正式点位"),
    ("supplementary_data/514-509.jpg", "14:48", "", "扫描", "-77", "-47.8", 0, "距离阶梯：514→509 前门约 25.5 m；房间号已确认 509；单次扫描 SIR −47.8 异常、RSSI 存疑"),
    ("supplementary_data/514-507.jpg", "14:49", "T5-03", "扫描", "-77", "-35.8", 0, "约 34 m；列表行 -75"),
    ("supplementary_data/514-507(retest).2.jpg", "14:57", "T5-03", "扫描", "-74", "-33.8", 0, "约 34 m；列表行 -75"),
    ("supplementary_data/514-507(retest).3.jpg", "14:58", "T5-03", "扫描", "-75", "-29.9", 0, "约 34 m；列表行 -77"),
    ("supplementary_data/514-507(retest).4.jpg", "14:58", "T5-03", "扫描", "-76", "-29.8", 0, "约 34 m；列表行 -76"),
    ("supplementary_data/512(corner).jpg", "15:10", "T5-06", "扫描", "-81", "-29.0", 0, "重测，与 10-24 的 -80/-82 一致"),
    ("supplementary_data/fireproof_door.jpg", "15:02", "T5-08", "扫描", "-73", "-7.0", 0, "重测，落在 10-24 的 -69/-80 之间"),
    ("supplementary_data/in_elevator.jpg", "15:10", "T5-05", "扫描", "-75", "", 0, "重测；同屏列表把 wireless_2.4G 显示为 -52，与主卡片差 23 dB"),
    ("supplementary_data/stairs.1.jpg", "15:04", "T5-07", "扫描", "-75", "-3.7", 0, "重测；列表行 -73"),
    ("supplementary_data/stairs.2.jpg", "15:04", "T5-07", "扫描", "-78", "-2.0", 0, "重测；列表行 -79"),
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
        if rssi and "RSSI/SIR" not in note:
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
