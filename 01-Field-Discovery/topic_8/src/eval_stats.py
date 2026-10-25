#!/usr/bin/env python3
"""课题 08 统计口径：置信区间、macro-F1、逐类召回、去重叠窗估计。

背景：8 s 窗 / 1 s 步长，相邻窗重叠 7/8，盲测的 149 个窗远不是 149 个独立样本。
本脚本不改变任何判决，只给已有预测配三种不确定性口径：

  - Wilson 区间：把窗当独立样本，偏窄，只作下限参考；
  - 记录级 bootstrap：对记录有放回重采样（B=2000），偏保守；
  - 去重叠估计：每段每 8 窗取 1 窗（相当于 8 s 步长），窗间不重叠。

输出：output/reports/stats_2026-10-25/report.txt
用法：MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/eval_stats.py
     换新数据：--test data/blind/2026-10-26
"""
import argparse
import os
import sys
from collections import Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
for sub in ("v2", "v3", "v4", "v5"):
    sys.path.insert(0, os.path.join(HERE, sub))

import gait_analysis_v2 as v2  # noqa: E402
import gait_analysis_v3 as v3  # noqa: E402
import gait_analysis_v4 as v4  # noqa: E402
import gait_analysis_v5 as v5  # noqa: E402

ROOT = v2.ROOT
ORDER = ("stand", "walk", "run", "up", "down")
STRIDE = 8
BOOT = 2000


def wilson(k, n, z=1.959964):
    """二项比例的 Wilson 95 % 区间。"""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, center - half), min(1.0, center + half)


def macro_f1(rows, key):
    truth = [r["state"] for r in rows]
    pred = [r[key] for r in rows]
    f1s = []
    for c in sorted(set(truth)):
        tp = sum(a == c and b == c for a, b in zip(truth, pred))
        fp = sum(a != c and b == c for a, b in zip(truth, pred))
        fn = sum(a == c and b != c for a, b in zip(truth, pred))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return float(np.mean(f1s)) if f1s else 0.0


def per_class_recall(rows, key):
    out = []
    for c in ORDER:
        v = [r for r in rows if r["state"] == c]
        if v:
            out.append((c, sum(r[key] == c for r in v) / len(v)))
    return out


def cluster_ci(rows, key, b=BOOT, seed=0):
    """按记录有放回重采样，返回准确率的 2.5/97.5 分位。"""
    by = {}
    for r in rows:
        by.setdefault(r["record"], []).append(r)
    names = sorted(by)
    rng = np.random.default_rng(seed)
    accs = []
    for _ in range(b):
        idx = rng.integers(0, len(names), len(names))
        hit = tot = 0
        for i in idx:
            for r in by[names[i]]:
                tot += 1
                hit += r[key] == r["state"]
        accs.append(hit / tot)
    lo, hi = np.percentile(accs, [2.5, 97.5])
    return float(lo), float(hi)


def stride_rows(rows, stride=STRIDE):
    """每段按 t0 排序后每隔 stride 个窗取一个，去掉 7/8 重叠。"""
    out = []
    for name in sorted(set(r["record"] for r in rows)):
        v = sorted((r for r in rows if r["record"] == name), key=lambda r: r["t0"])
        out.extend(v[::stride])
    return out


def collect_predictions(test_dir):
    d2 = v2.collect(os.path.join(ROOT, "data", "calib", "data_2"), 8.0, 1.0)
    rt = v2.collect(os.path.join(ROOT, "data", "calib", "2026-10-24"), 8.0, 1.0)
    t2 = v2.collect(test_dir, 8.0, 1.0)
    th2 = v2.calibrate(d2)
    th3 = v3.calibrate(d2)
    for r in d2 + rt + t2:
        r["m2"] = v2.classify(r, th2)

    groups = (("data_2", d2), ("data_routine", rt), ("blind", t2))
    for tag, rows in groups:
        for r in rows:
            r["m3"] = v3.classify(r, th3)
            r["pred"] = r["m3"]
            r["dataset"] = tag
        v3.smooth(rows)
        for r in rows:
            r["m3s"] = r["pred_smooth"]

    d2v = v4.collect(os.path.join(ROOT, "data", "calib", "data_2"))
    rtv = v4.collect(os.path.join(ROOT, "data", "calib", "2026-10-24"))
    t2v = v4.collect(test_dir)
    th4 = v4.calibrate(d2v + rtv)
    v4groups = (("data_2", d2v), ("data_routine", rtv), ("blind", t2v))
    for tag, rows in v4groups:
        for r in rows:
            r["m4"] = v4.classify(r, th4)
            r["pred"] = r["m4"]
            r["dataset"] = tag
        v4.smooth(rows)
        for r in rows:
            r["m4s"] = r["pred_smooth"]

    d2v5 = v5.collect(os.path.join(ROOT, "data", "calib", "data_2"))
    rtv5 = v5.collect(os.path.join(ROOT, "data", "calib", "2026-10-24"))
    t2v5 = v5.collect(test_dir)
    th5 = v5.calibrate(d2v5 + rtv5)
    v5groups = (("data_2", d2v5), ("data_routine", rtv5), ("blind", t2v5))
    for tag, rows in v5groups:
        for r in rows:
            r["m5"] = v5.classify(r, th5)
            r["pred"] = r["m5"]
            r["dataset"] = tag
        v5.smooth(rows)
        for r in rows:
            r["m5s"] = r["pred_smooth"]

    return groups, v4groups, v5groups, th2, th3, th4, th5


def block(title, entries):
    """entries = [(方法名, rows, 预测字段), ...]；同一数据集下各方法共用真值。"""
    lines = ["== %s ==" % title]
    rows0 = entries[0][1]
    n = len(rows0)
    cnt = Counter(r["state"] for r in rows0)
    base = max(cnt.values()) / n
    lines.append("真值分布：%s；多数类基线 %.1f %%"
                 % ("，".join("%s %d" % (v2.STATE_CN[c], cnt[c]) for c in ORDER if cnt[c]),
                    100 * base))
    lines.append("%-8s %5s %7s %8s  %-14s %-16s %9s %9s"
                 % ("方法", "窗数", "准确率", "macroF1", "Wilson 95%", "记录bootstrap 95%",
                    "去重叠n", "去重叠acc"))
    for label, rows, key in entries:
        hit = sum(r[key] == r["state"] for r in rows)
        lo, hi = wilson(hit, n)
        blo, bhi = cluster_ci(rows, key)
        srows = stride_rows(rows)
        shit = sum(r[key] == r["state"] for r in srows)
        lines.append("%-8s %5d %6.1f%% %8.3f  [%5.1f, %5.1f]  [%5.1f, %5.1f] %9d %9.1f%%"
                     % (label, n, 100 * hit / n, macro_f1(rows, key),
                        100 * lo, 100 * hi, 100 * blo, 100 * bhi,
                        len(srows), 100 * shit / len(srows)))
    lines.append("逐类召回：")
    for label, rows, key in entries:
        lines.append("  %-8s %s" % (label, "  ".join(
            "%s %5.1f%%" % (v2.STATE_CN[c], 100 * r) for c, r in per_class_recall(rows, key))))
    lines.append("")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", default=os.path.join(ROOT, "data", "blind", "2026-10-25"))
    ap.add_argument("--out", default=os.path.join(ROOT, "output", "reports", "stats_2026-10-25"))
    a = ap.parse_args()
    test_dir = a.test if os.path.isabs(a.test) else os.path.join(ROOT, a.test)
    out_dir = a.out if os.path.isabs(a.out) else os.path.join(ROOT, a.out)
    groups, v4groups, v5groups, th2, th3, th4, th5 = collect_predictions(test_dir)
    d2, rt, t2 = (g[1] for g in groups)
    d2v, rtv, t2v = (g[1] for g in v4groups)
    d2v5, rtv5, t2v5 = (g[1] for g in v5groups)
    lines = ["课题 08 统计口径（8 s 窗 / 1 s 步长，相邻窗重叠 7/8）",
             "Wilson 把窗当独立样本（偏窄）；记录级 bootstrap 对记录重采样（B=%d，偏保守）；" % BOOT,
             "去重叠 = 每段每 %d 窗取 1 窗（8 s 步长，窗间不重叠）。" % STRIDE,
             "",
             "阈值（未改变）：v2 %s；v3 %s；v4 %s"
             % (", ".join("%s=%.3f" % (k, v) for k, v in th2.items()),
                ", ".join("%s=%.3f" % (k, v) for k, v in th3.items()),
                ", ".join("%s=%.3f" % (k, v) for k, v in th4.items())),
             "阈值（v5）：stand=%.3f run=%.3f ptn=%.3f up_score=%.3f"
             % (th5["stand"], th5["run"], th5["down"], th5["up"]),
             ""]
    lines += block("data_2 同集（302 窗 / 7 段，in-sample）",
                    [("v2", d2, "m2"), ("v3", d2, "m3"), ("v3+平滑", d2, "m3s"),
                     ("v4", d2v, "m4"), ("v4+平滑", d2v, "m4s"),
                     ("v5", d2v5, "m5"), ("v5+平滑", d2v5, "m5s")])
    lines += block("data_routine（640 窗 / 9 段；v2/v3 跨数据集，v4 in-sample）",
                    [("v2", rt, "m2"), ("v3", rt, "m3"), ("v3+平滑", rt, "m3s"),
                     ("v4", rtv, "m4"), ("v4+平滑", rtv, "m4s"),
                     ("v5", rtv5, "m5"), ("v5+平滑", rtv5, "m5s")])
    test_name = os.path.basename(os.path.normpath(test_dir))
    lines += block("%s 盲测（%d 窗 / %d 段）"
                    % (test_name, len(t2), len(set(r["record"] for r in t2))),
                    [("v2", t2, "m2"), ("v3", t2, "m3"), ("v3+平滑", t2, "m3s"),
                     ("v4", t2v, "m4"), ("v4+平滑", t2v, "m4s"),
                     ("v5", t2v5, "m5"), ("v5+平滑", t2v5, "m5s")])
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
