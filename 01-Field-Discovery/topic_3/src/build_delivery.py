#!/usr/bin/env python3
"""课题 3 的 24 组交付明细（仅标准库）。

输入
    data/measurements.csv   一次测速一行（build_dataset.py 生成）
    data/results.json       原始记录，用于回填记录 id 便于回查

输出
    data/delivery_24.csv    8 个测试点位 × 每点位前 3 轮 = 24 组

口径
    - 只取 8 个测试点位（不含 3 个本地零点），每点位取 seq 最小的 3 轮，
      对应题面「8 个点位 × 连续测试 3 次」。
    - 第 4 轮及以后的补测、11-01 的走廊阶梯、三个零点的轮次不进本表，
      仍保留在 measurements.csv 与 results.json 里。
    - RSSI / SIR 是点位级读数，同一批轮次共用，不是逐轮读数（见报告第 4 节）。
"""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST_POINTS = ["T5-02", "T5-03", "T5-05", "T5-06", "T5-07", "T5-08", "L1-01", "D-02"]
ROUNDS = 3
FIELDS = [
    "group_id", "point_id", "round", "record_id", "time",
    "rssi_dbm", "sir_db", "ping_ms", "p95_ms", "jitter_ms", "loss_pct",
    "down_mbps", "up_mbps", "note",
]


def load(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def record_ids():
    with (ROOT / "data" / "results.json").open(encoding="utf-8") as handle:
        items = json.load(handle)["items"]
    return {item["label"]: item["id"] for item in items}


def build(measurements):
    ids = record_ids()
    rows = []
    for point_id in TEST_POINTS:
        rounds = sorted(
            (row for row in measurements if row["point_id"] == point_id),
            key=lambda row: int(row["seq"]),
        )[:ROUNDS]
        if len(rounds) < ROUNDS:
            raise SystemExit(f"{point_id} 只有 {len(rounds)} 轮，不足 {ROUNDS} 轮")
        for row in rounds:
            rows.append({
                "group_id": len(rows) + 1,
                "point_id": point_id,
                "round": row["seq"],
                "record_id": ids.get(row["raw_label"], ""),
                "time": row["time"],
                "rssi_dbm": row["rssi_dbm"],
                "sir_db": row["sir_db"],
                "ping_ms": row["ping_ms"],
                "p95_ms": row["p95_ms"],
                "jitter_ms": row["jitter_ms"],
                "loss_pct": row["loss_pct"],
                "down_mbps": row["down_mbps"],
                "up_mbps": row["up_mbps"],
                "note": row["note"],
            })
    return rows


def main():
    measurements = load(ROOT / "data" / "measurements.csv")
    rows = build(measurements)
    if len(rows) != len(TEST_POINTS) * ROUNDS:
        raise SystemExit(f"交付组数 {len(rows)} 不等于 {len(TEST_POINTS) * ROUNDS}")
    if any(not row["record_id"] for row in rows):
        missing = [row["point_id"] for row in rows if not row["record_id"]]
        raise SystemExit(f"以下点位无法回填记录 id：{missing}")
    out = ROOT / "data" / "delivery_24.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{out.relative_to(ROOT)}：{len(rows)} 组，"
          f"{len(TEST_POINTS)} 个点位 × {ROUNDS} 轮，记录 id {rows[0]['record_id']}–{rows[-1]['record_id']}")


if __name__ == "__main__":
    main()
