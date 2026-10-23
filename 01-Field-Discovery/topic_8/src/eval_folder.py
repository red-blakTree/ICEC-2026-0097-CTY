#!/usr/bin/env python3
"""在任意数据目录上批量运行阈值规则（用于新数据 / 测试集回归）。

用法：
    .venv/bin/python src/eval_folder.py --dir test_data [--truth stairs]

目录约定：`--dir` 下任意深度的子目录中，凡含 `Raw Data.csv` 的都算一段记录。
真值（--truth）缺省时按目录名猜测：含 stair/upstairs/downstairs → 上下楼梯，
含 run → 快跑，含 walk → 平地慢走，含 stand/static → 静止；猜不出则记为 unknown。

输出：终端表格 + output/features/<目录名>_eval.txt
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gait_analysis import (  # noqa: E402
    ROOT, STATE_CN, T_RUN_PEAK, T_RUN_SD, T_STAND_SD, T_STAIRS_RATIO,
    classify, clean, read_phyphox, sample_rate, windows,
)

KEYWORDS = [("stairs", ("stair", "upstairs", "downstairs")), ("run", ("run",)),
            ("walk", ("walk",)), ("stand", ("stand", "static"))]


def infer_truth(path):
    low = path.lower()
    for truth, keys in KEYWORDS:
        if any(k in low for k in keys):
            return truth
    return "unknown"


def find_records(root):
    out = []
    for cur, _, files in os.walk(root):
        if "Raw Data.csv" in files:
            out.append(cur)
    return sorted(out)


def evaluate(dirs, forced_truth, root):
    lines = []
    for d in dirs:
        name = os.path.relpath(d, root)
        truth = forced_truth or infer_truth(d)
        t, ax, ay, az, mag = read_phyphox(os.path.join(d, "Raw Data.csv"))
        i, j = clean(t, ax, ay, az, mag)
        if j - i < 2:
            lines.append("%-14s 清洗后无有效数据" % name)
            continue
        t, ax, ay, az, mag = t[i:j], ax[i:j], ay[i:j], az[i:j], mag[i:j]
        feats = [f for _, f in windows(t, ax, ay, az, mag)]
        votes = {}
        for f in feats:
            p = classify(f)
            votes[p] = votes.get(p, 0) + 1
        major = max(votes, key=votes.get)
        sd = [f["std_mag"] for f in feats]
        rt = [f["ratio"] for f in feats]
        lines.append(
            "%-14s fs=%5.1fHz 时长=%5.1fs 窗数=%3d 票数=%-34s 多数票=%s  σ[%.2f,%.2f] r[%.2f,%.2f]"
            % (name, feats[0]["fs"], t[-1] - t[0], len(feats),
               str({STATE_CN[k]: v for k, v in sorted(votes.items())}),
               STATE_CN.get(major, major), min(sd), max(sd), min(rt), max(rt)))
        if truth != "unknown":
            hit = votes.get(truth, 0)
            lines.append("               真值=%s 逐窗准确率=%.1f%%  记录级=%s"
                         % (STATE_CN[truth], 100.0 * hit / len(feats),
                            "命中" if major == truth else "错判"))
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="test_data")
    ap.add_argument("--truth", default=None, choices=sorted(STATE_CN) + ["unknown"])
    a = ap.parse_args()

    root = a.dir if os.path.isabs(a.dir) else os.path.join(ROOT, a.dir)
    dirs = find_records(root)
    if not dirs:
        sys.exit("在 %s 下没找到任何 Raw Data.csv" % root)

    head = ["阈值: σ<%.2f→静止 | σ>%.2f 或 峰值>%.0f→快跑 | r>%.2f→上下楼梯 | 其余→平地慢走"
            % (T_STAND_SD, T_RUN_SD, T_RUN_PEAK, T_STAIRS_RATIO),
            "共 %d 段记录" % len(dirs)]
    lines = head + evaluate(dirs, a.truth, root)

    out_dir = os.path.join(ROOT, "output", "features")
    os.makedirs(out_dir, exist_ok=True)
    tag = os.path.basename(os.path.normpath(root))
    path = os.path.join(out_dir, "%s_eval.txt" % tag)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("\n已写入 %s" % os.path.relpath(path, ROOT))


if __name__ == "__main__":
    main()
