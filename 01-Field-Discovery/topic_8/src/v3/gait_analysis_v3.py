#!/usr/bin/env python3
"""课题 08 v3 —— 步频阶梯 + 竖向能量比。

`data/calib/data_2`（7 段）上 v2 的 σ_v / p99 同集 97.4 %、留一 90.5 %，但跨到
`data_routine` 只有 73.9 %；而 f_dom（步频）在两套数据上都稳：

    上楼 1.63 Hz ／ 慢走 1.75 Hz ／ 下楼 1.88–2.00 Hz

于是 v3 把判决从“绝对能量”改成“步频阶梯 + 竖向能量比”：

    ① σ < t_stand                              → 静止
    ② σ > t_run 或 峰值 > t_peak               → 快跑
    ③ f_dom > t_fd_down 且 r > t_r_down        → 下楼
    ④ f_dom <= t_fd_up                         → 上楼
    ⑤ 其余                                     → 平地慢走

并在逐窗判决后加 ±2 窗（前后各 1 s，共 5 窗）多数票平滑。

用法：
    .venv/bin/python src/v3/gait_analysis_v3.py
    .venv/bin/python src/v3/gait_analysis_v3.py --eval data/calib/data_2 data_routine
"""
import argparse
import csv
import os
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "v2"))
from gait_analysis_v2 import (  # noqa: E402
    ROOT, STATE_CN, _best_split, collect, write_submission_csvs,
)

OUT = os.path.join(ROOT, "output", "v3", "features")
SMOOTH_K = 2
CMDS = ("stand", "walk", "run", "up", "down")


def _down_split(rows):
    """在下楼 vs (慢走+上楼) 上联合搜索 (f_dom, r) 两个阈值。"""
    down = [r for r in rows if r["state"] == "down"]
    other = [r for r in rows if r["state"] in ("walk", "up")]
    if not down or not other:
        raise ValueError("标定下楼阈值需要下楼与慢走/上楼样本")
    fds = np.unique([r["f_dom"] for r in down])
    rts = np.percentile([r["ratio"] for r in rows], np.arange(5, 96, 2.5))
    best = None
    for fd in fds:
        for rt in rts:
            err = (sum(not (r["f_dom"] > fd and r["ratio"] > rt) for r in down)
                   + sum(r["f_dom"] > fd and r["ratio"] > rt for r in other))
            if best is None or err < best[0]:
                best = (err, float(fd), float(rt))
    return best[1], best[2]


def calibrate(rows):
    missing = set(CMDS) - {r["state"] for r in rows}
    if missing:
        raise ValueError("标定需要五类样本，缺少: %s" % ", ".join(sorted(missing)))
    fd_down, r_down = _down_split(rows)
    return dict(
        stand=_best_split(rows, ("stand",), ("walk", "run", "up", "down"), "std_mag"),
        run_sd=_best_split(rows, ("walk", "up", "down"), ("run",), "std_mag"),
        run_peak=_best_split(rows, ("walk", "up", "down"), ("run",), "peak"),
        fd_up=_best_split(rows, ("up",), ("walk",), "f_dom"),
        fd_down=fd_down,
        r_down=r_down,
    )


def classify(f, th):
    if f["std_mag"] < th["stand"]:
        return "stand"
    if f["std_mag"] > th["run_sd"] or f["peak"] > th["run_peak"]:
        return "run"
    if f["f_dom"] > th["fd_down"] and f["ratio"] > th["r_down"]:
        return "down"
    if f["f_dom"] <= th["fd_up"]:
        return "up"
    return "walk"


def smooth(rows, k=SMOOTH_K):
    """按 (数据集, 记录) 内的时间顺序做 ±k 窗多数票。"""
    for ds, name in sorted(set((r["dataset"], r["record"]) for r in rows)):
        v = sorted((r for r in rows if r["dataset"] == ds and r["record"] == name),
                   key=lambda r: r["t0"])
        raw = [r["pred"] for r in v]
        for i, r in enumerate(v):
            win = raw[max(0, i - k):i + k + 1]
            vals, cnts = np.unique(win, return_counts=True)
            r["pred_smooth"] = vals[int(np.argmax(cnts))]


def _acc(rows, key):
    return sum(r[key] == r["state"] for r in rows) / len(rows)


def report(rows, name):
    lines = ["== %s ==" % name,
             "窗数 %d；原始准确率 %.4f；平滑后 %.4f"
             % (len(rows), _acc(rows, "pred"), _acc(rows, "pred_smooth")), ""]
    rec_raw = rec_smooth = 0
    for rec in sorted(set(r["record"] for r in rows)):
        v = [r for r in rows if r["record"] == rec]
        truth = v[0]["state"]
        votes = Counter(r["pred_smooth"] for r in v)
        maj = votes.most_common(1)[0][0]
        rec_raw += (Counter(r["pred"] for r in v).most_common(1)[0][0] == truth)
        rec_smooth += (maj == truth)
        lines.append("%-16s truth=%-5s raw %3d/%3d  smooth %3d/%3d  majority=%s"
                     % (rec, truth,
                        sum(r["pred"] == truth for r in v), len(v),
                        sum(r["pred_smooth"] == truth for r in v), len(v),
                        STATE_CN[maj]))
    lines.append("记录级：原始 %d/%d，平滑 %d/%d"
                 % (rec_raw, len(set(r["record"] for r in rows)),
                    rec_smooth, len(set(r["record"] for r in rows))))
    lines.append("")
    lines.append("混淆矩阵（平滑后；行=真值，列=判决）:")
    lines.append("%-6s" % "" + "".join("%7s" % STATE_CN[s] for s in CMDS))
    for a in CMDS:
        row = [sum(1 for r in rows if r["state"] == a and r["pred_smooth"] == b) for b in CMDS]
        lines.append("%-6s" % STATE_CN[a] + "".join("%7d" % v for v in row))
    return lines


def loro(rows):
    """留一记录：只留出同类 >= 2 段的记录（否则训练集没有该类样本）。"""
    by_state = {}
    for r in rows:
        by_state.setdefault(r["state"], set()).add(r["record"])
    holdable = sorted(n for names in by_state.values() if len(names) >= 2 for n in names)
    hits = tot = 0
    for name in holdable:
        th = calibrate([r for r in rows if r["record"] != name])
        for r in rows:
            if r["record"] == name:
                tot += 1
                hits += classify(r, th) == r["state"]
    return hits, tot, holdable


def write_outputs(all_rows, th, train_names, eval_names, loro_hit):
    os.makedirs(OUT, exist_ok=True)
    lines = ["v3 规则：f_dom 阶梯 + 竖向能量比 + ±%d 窗多数票平滑" % SMOOTH_K,
             "训练集: %s" % ", ".join(train_names),
             "阈值: " + ", ".join("%s=%.3f" % (k, v) for k, v in th.items()), ""]
    for name in eval_names:
        rows = [r for r in all_rows if r["dataset"] == name]
        lines += report(rows, name) + [""]
    if loro_hit[1]:
        lines.append("留一记录（%s，重标定阈值，原始判决）: %d/%d = %.4f"
                     % (",".join(loro_hit[2]), loro_hit[0], loro_hit[1],
                        loro_hit[0] / loro_hit[1]))
    else:
        lines.append("留一记录：没有可留出的记录（每类都只有 1 段）")
    lines.append("")
    tag = "" if train_names == ["data/calib/data_2"] else "_multi"
    path = os.path.join(OUT, "eval%s.txt" % tag)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))

    fields = ["dataset", "record", "state", "t0", "std_mag", "std_v", "ratio", "p99",
              "peak", "f_dom", "pred", "pred_smooth"]
    with open(os.path.join(OUT, "windows%s.csv" % tag), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in all_rows:
            w.writerow({k: (round(r[k], 4) if isinstance(r[k], float) else r[k]) for k in fields})


def collect_all(dirs):
    rows = []
    for name in dirs:
        path = name if os.path.isabs(name) else os.path.join(ROOT, name)
        for r in collect(path, 8.0, 1.0):
            r["dataset"] = name
            rows.append(r)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", nargs="+", default=["data/calib/data_2"])
    ap.add_argument("--eval", nargs="+", default=["data/calib/data_2"])
    a = ap.parse_args()

    train = collect_all(a.train)
    th = calibrate(train)
    all_rows = collect_all(a.eval)
    for r in all_rows:
        r["pred"] = classify(r, th)
    smooth(all_rows)
    write_outputs(all_rows, th, a.train, a.eval, loro(train))
    write_submission_csvs(os.path.join(ROOT, "data", "calib", "data_2"),
                          os.path.join(ROOT, "output", "v3", "csv"))


if __name__ == "__main__":
    main()
