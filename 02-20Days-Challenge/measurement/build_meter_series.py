#!/usr/bin/env python3
"""把 USB 表盘读数转写成 24 h 实测能量区间序列。

USB 表是一个真实积分器：累计 `mWh` 是测量值，瞬时 `A` 只是快照。
两次读数之间的 `ΔmWh / Δt` 就是该区间的**实测平均功率**，再除以区间平均电压得到
等效平均电流。本脚本只做这一件事，并显式丢弃三类不能当区间的行：

  - 同一分钟内的重复读数（tab 计时 0:00，ΔmWh = 0）；
  - 设备拔掉后的鼠标续测（note 含「鼠标」）；
  - 终点显示停顿（16384 → 16384，7 min 内没有进位）。

输入: process_logs/baseline-24h-meter-2026-11-10/meter-readings.csv
输出: measurement/24h-meter-series.csv

用法:
  python3 measurement/build_meter_series.py
  python3 measurement/build_meter_series.py --check   # 只校验，不写文件
"""
import argparse
import csv
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
READINGS = ROOT / "process_logs" / "baseline-24h-meter-2026-11-10" / "meter-readings.csv"
OUT = ROOT / "measurement" / "24h-meter-series.csv"

FIELDS = [
    "interval", "start_local", "end_local", "duration_min", "duration_h",
    "start_mwh", "end_mwh", "delta_mwh", "avg_mw",
    "v_start_v", "v_end_v", "v_used_v", "avg_ma", "note",
]


def _parse_ts(s):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析时间: {s}")


def load_anchors(path=READINGS):
    """读出可用锚点：去掉鼠标续测、同分钟重复读数。"""
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    anchors = []
    seen = set()
    for r in rows:
        note = r["note"]
        if "鼠标" in note or r["photo"].startswith("IMG_2026"):
            continue
        ts = _parse_ts(r["wall_local"])
        if ts in seen:
            continue
        seen.add(ts)
        anchors.append({
            "ts": ts,
            "mwh": int(r["mwh"]),
            "mv": int(r["v5_mv"]),
            "note": note,
            "photo": r["photo"],
        })
    return anchors


def build(anchors):
    """相邻锚点差分，生成区间行；跳过 0 增量的显示停顿段。"""
    out = []
    for i, (a, b) in enumerate(zip(anchors, anchors[1:]), start=1):
        minutes = (b["ts"] - a["ts"]).total_seconds() / 60.0
        delta = b["mwh"] - a["mwh"]
        if minutes <= 0 or delta < 0:
            raise SystemExit(f"锚点顺序/累计量异常: {a} -> {b}")
        if delta == 0:
            continue
        v_used = (a["mv"] + b["mv"]) / 2000.0
        hours = minutes / 60.0
        avg_mw = delta / hours
        out.append({
            "interval": len(out) + 1,
            "start_local": a["ts"].strftime("%Y-%m-%d %H:%M"),
            "end_local": b["ts"].strftime("%Y-%m-%d %H:%M"),
            "duration_min": f"{minutes:.0f}",
            "duration_h": f"{hours:.3f}",
            "start_mwh": a["mwh"],
            "end_mwh": b["mwh"],
            "delta_mwh": delta,
            "avg_mw": f"{avg_mw:.1f}",
            "v_start_v": f"{a['mv'] / 1000:.2f}",
            "v_end_v": f"{b['mv'] / 1000:.2f}",
            "v_used_v": f"{v_used:.3f}",
            "avg_ma": f"{avg_mw / v_used:.1f}",
            "note": _note(a, b),
        })
    return out


def _note(a, b):
    if a["ts"].strftime("%H:%M") == "21:02" and b["ts"].strftime("%H:%M") == "12:04":
        return "含 08:20 起的断连段（12:08 才重连成功），区间平均被 0.18 A 抬高"
    if a["ts"].strftime("%H:%M") == "12:04":
        return "重连过程中的 4 min（12:08 成功）"
    if a["ts"].strftime("%H:%M") == "12:08":
        return "12:08 后累计量反推仍主要处于 0.18 A 档"
    return "上电稳定段（8 min）"


def totals(rows):
    minutes = sum(float(r["duration_min"]) for r in rows)
    delta = sum(int(r["delta_mwh"]) for r in rows)
    hours = minutes / 60.0
    return {
        "minutes": minutes,
        "hours": hours,
        "mwh": delta,
        "avg_mw": delta / hours,
        "avg_ma": (delta / hours) / 5.04,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验已有 CSV，不重写")
    a = ap.parse_args()

    rows = build(load_anchors())
    if not rows:
        raise SystemExit("没有可用的区间")

    body = [",".join(FIELDS)]
    for r in rows:
        body.append(",".join(str(r[k]) for k in FIELDS))
    text = "\n".join(body) + "\n"

    t = totals(rows)
    print(text, end="")
    print(f"合计: {t['hours']:.2f} h / {t['mwh']} mWh / "
          f"{t['avg_mw']:.1f} mW / {t['avg_ma']:.1f} mA @5.04 V")
    if not 23.9 <= t["hours"] <= 24.2:
        raise SystemExit("跨度不是 24 h 左右，检查锚点")
    if t["mwh"] != 16384:
        raise SystemExit("累计量与证据 README 的 16384 mWh 不一致")

    if a.check:
        if not OUT.exists():
            raise SystemExit(f"缺少 {OUT.relative_to(ROOT)}")
        if OUT.read_text(encoding="utf-8") != text:
            raise SystemExit("CSV 与按锚点重算的结果不一致，请重跑生成")
        print("check: OK（CSV 与重算一致，未写文件）")
        return
    OUT.write_text(text, encoding="utf-8")
    print(f"写入 {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
