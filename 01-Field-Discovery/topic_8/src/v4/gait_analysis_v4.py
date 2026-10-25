#!/usr/bin/env python3
"""课题 08 v4 —— 波形检测 + 自相关阈值 + ±2 窗多数票平滑。

v2 / v3 用窗口统计量（σ、σ_v、p99、f_dom），换一天（2026-10-25）后崩到
42.8 % / 45.3 %。v4 改成“先检测波形，再判形态”：

  - 在竖向动态加速度 a_v 上检测每一步的峰（脚离地）和谷（落地）；
  - 特征：步间隔变异系数 i_cv、峰/谷幅值比 pt、自相关峰 acp；
  - 判决：σ 门限 → 静止/快跑，pt → 下楼，acp → 上楼/慢走；
  - ±2 窗（5 窗）多数票平滑，抹平边界单窗抖动。

标定：data/calib/data_2 + data_routine（都是本人数据，PKG110）
盲测：data/blind/2026-10-25（跨日，本人 PKG110），不参与标定。

输出：output/v4/features/{windows.csv,report.txt}、output/v4/figures/
用法：MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/v4/gait_analysis_v4.py
"""
import argparse
import csv
import os
import sys
from collections import Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "v2"))
from gait_analysis_v2 import (  # noqa: E402
    ROOT, STATE_CN, clean, find_records, infer_truth, load_record, sample_rate,
)

OUT = os.path.join(ROOT, "output", "v4", "features")
TRAIN = os.path.join(ROOT, "data", "calib", "data_2")
# 2026-10-25 起，data_routine 下出现新日期；新日期留作跨日盲测，标定只用 10-24。
ROUTINE = os.path.join(ROOT, "data", "calib", "2026-10-24")
BLIND = os.path.join(ROOT, "data", "blind", "2026-10-25")
STATES = ("stand", "walk", "run", "up", "down")


def moving_average(x, n):
    n = max(3, int(n))
    return np.convolve(x, np.ones(n) / n, "same")


def detect_peaks(x, fs, min_dist_s=0.30, min_prom=0.30):
    """局部极大值 + 最小间距（贪心按高度取峰）。"""
    cand = np.where((x[1:-1] > x[:-2]) & (x[1:-1] >= x[2:]))[0] + 1
    if len(cand) == 0:
        return np.array([], dtype=int)
    cand = cand[x[cand] > x.max() * min_prom]
    order = cand[np.argsort(-x[cand])]
    acc = []
    for i in order:
        if all(abs(i - j) >= min_dist_s * fs for j in acc):
            acc.append(i)
    return np.array(sorted(acc), dtype=int)


def waveform_features(t, ax, ay, az, gx, gy, gz):
    """检测峰/谷并算步态形态特征。"""
    gn = np.sqrt(gx * gx + gy * gy + gz * gz)
    ux, uy, uz = gx / gn, gy / gn, gz / gn
    a_v = ax * ux + ay * uy + az * uz - gn
    dx, dy, dz = ax - gx, ay - gy, az - gz
    dyn = np.sqrt(dx * dx + dy * dy + dz * dz)

    fs = sample_rate(t)
    s = moving_average(a_v, 0.08 * fs)
    peaks = detect_peaks(s, fs)
    troughs = detect_peaks(-s, fs)
    dur = len(s) / fs

    intervals = np.diff(peaks) / fs if len(peaks) >= 2 else np.array([])
    pv = s[peaks] if len(peaks) else np.array([0.0])
    tv = -s[troughs] if len(troughs) else np.array([0.0])

    ac = np.correlate(s - s.mean(), s - s.mean(), "full")[len(s) - 1:]
    ac = ac / (ac[0] + 1e-9)
    lo, hi = max(1, int(0.30 * fs)), min(len(ac) - 1, int(1.20 * fs))
    acp = float(ac[lo:hi].max()) if hi > lo else 0.0
    ac_lag = (lo + int(np.argmax(ac[lo:hi]))) / fs if hi > lo else 0.0

    i_cv = float(np.std(intervals) / (abs(np.mean(intervals)) + 1e-9)) if len(intervals) >= 2 else 0.0
    p_cv = float(np.std(pv) / (abs(np.mean(pv)) + 1e-9)) if len(pv) >= 2 else 0.0
    pt = float(np.mean(pv) / (np.mean(tv) + 1e-9))
    skew = float(((s - s.mean()) ** 3).mean() / (s.std() ** 3 + 1e-9))
    kurt = float(((s - s.mean()) ** 4).mean() / (s.std() ** 4 + 1e-9))
    zcr = float(np.sum(np.diff(np.signbit(s - s.mean())) != 0) / dur)

    return dict(
        fs=fs, n=len(t), n_steps=len(peaks), cadence=len(peaks) / dur,
        sigma=float(dyn.std()), i_cv=i_cv, p_cv=p_cv, pt=pt, acp=acp, ac_lag=ac_lag,
        score=acp - 2.0 * i_cv, skew=skew, kurt=kurt, zcr=zcr,
    )


def collect(root):
    tag = os.path.basename(os.path.normpath(root))
    rows = []
    for path in find_records(root):
        name = os.path.relpath(path, root)
        truth = infer_truth(name)
        t, ax, ay, az, gx, gy, gz = load_record(path)
        dyn = np.sqrt((ax - gx) ** 2 + (ay - gy) ** 2 + (az - gz) ** 2)
        i, j = clean(t, dyn)
        if j - i < 2:
            continue
        fs = sample_rate(t[i:j])
        w, h = int(8 * fs), int(fs)
        for k in range(0, j - i - w + 1, h):
            sl = slice(i + k, i + k + w)
            f = waveform_features(t[sl], ax[sl], ay[sl], az[sl], gx[sl], gy[sl], gz[sl])
            f.update(record=name, state=truth, t0=float(t[i + k]), dataset=tag)
            rows.append(f)
    return rows


def _geometric(a, b):
    a, b = float(a), float(b)
    return float(np.sqrt(a * b)) if a > 0 else 0.5 * (a + b)


def _vals(rows, states, key):
    return np.array([r[key] for r in rows if r["state"] in states])


def calibrate(rows):
    """四个阈值只在传入的 rows（本人数据）上标定。"""
    motion = np.concatenate([_vals(rows, (s,), "sigma") for s in ("walk", "run", "up", "down")])
    t_stand = _geometric(_vals(rows, ("stand",), "sigma").max(), motion.min())
    t_run = _geometric(max(_vals(rows, (s,), "sigma").max() for s in ("walk", "up", "down")),
                       _vals(rows, ("run",), "sigma").min())
    t_pt = _geometric(max(_vals(rows, (s,), "pt").max() for s in ("walk", "up")),
                      _vals(rows, ("down",), "pt").min())

    # acp 阈值：只在传入的 rows 上，以“该数据上的准确率最高”选；不看测试集
    def acc(ta):
        hit = 0
        for r in rows:
            if r["sigma"] < t_stand:
                p = "stand"
            elif r["sigma"] > t_run:
                p = "run"
            elif r["pt"] > t_pt:
                p = "down"
            elif r["acp"] < ta:
                p = "up"
            else:
                p = "walk"
            hit += p == r["state"]
        return hit / len(rows)

    t_acp = max((acc(t), float(t)) for t in np.arange(0.40, 0.86, 0.005))[1]
    return dict(stand=t_stand, run=t_run, pt=t_pt, acp=float(t_acp))


def classify(f, th):
    if f["sigma"] < th["stand"]:
        return "stand"
    if f["sigma"] > th["run"]:
        return "run"
    if f["pt"] > th["pt"]:
        return "down"
    if f["acp"] < th["acp"]:
        return "up"
    return "walk"


def smooth(rows):
    """±2 窗（5 窗）多数票平滑，按 (dataset, record) 分组并按 t0 排序。"""
    groups = {}
    for r in rows:
        groups.setdefault((r.get("dataset", ""), r["record"]), []).append(r)
    for v in groups.values():
        v.sort(key=lambda r: r["t0"])
        raw = [r["pred"] for r in v]
        for i, r in enumerate(v):
            r["pred_smooth"] = Counter(raw[max(0, i - 2):i + 3]).most_common(1)[0][0]
    return rows


def loro(rows, base=()):
    """在 data_2 上留出 walk/run 记录；每折用 (其余 data_2 + base) 重标定。"""
    by_state = {}
    for r in rows:
        by_state.setdefault(r["state"], set()).add(r["record"])
    holdable = sorted(n for names in by_state.values() if len(names) >= 2 for n in names)
    hits = tot = 0
    for name in holdable:
        th = calibrate([r for r in rows if r["record"] != name] + list(base))
        held = [r for r in rows if r["record"] == name]
        for r in held:
            r["pred"] = classify(r, th)
        smooth(held)
        for r in held:
            tot += 1
            hits += r["pred_smooth"] == r["state"]
    return hits, tot, holdable


def report(rows, th, title):
    for r in rows:
        r["pred"] = classify(r, th)
    smooth(rows)
    lines = ["== %s ==" % title,
             "阈值: " + ", ".join("%s=%.3f" % (k, v) for k, v in th.items()), ""]
    for name in sorted(set(r["record"] for r in rows)):
        v = [r for r in rows if r["record"] == name]
        truth = v[0]["state"]
        raw = sum(r["pred"] == truth for r in v)
        sm = sum(r["pred_smooth"] == truth for r in v)
        major = Counter(r["pred_smooth"] for r in v).most_common(1)[0][0]
        lines.append("%-16s truth=%-5s windows=%3d raw=%3d/%-3d smooth=%3d/%-3d majority=%s"
                     % (name, truth, len(v), raw, len(v), sm, len(v), STATE_CN[major]))
    raw = sum(r["pred"] == r["state"] for r in rows)
    sm = sum(r["pred_smooth"] == r["state"] for r in rows)
    lines.append("窗口级: raw %d/%d = %.4f; 平滑 %d/%d = %.4f"
                 % (raw, len(rows), raw / len(rows), sm, len(rows), sm / len(rows)))
    recs = sorted(set(r["record"] for r in rows))
    ok = 0
    for name in recs:
        v = [r for r in rows if r["record"] == name]
        major = Counter(r["pred_smooth"] for r in v).most_common(1)[0][0]
        ok += major == v[0]["state"]
    lines.append("记录级（平滑）: %d/%d" % (ok, len(recs)))
    lines.append("混淆矩阵（平滑后，行=真值，列=判决）:")
    lines.append("%-6s" % "" + "".join("%7s" % STATE_CN[s] for s in STATES))
    for a in STATES:
        row = [sum(1 for r in rows if r["state"] == a and r["pred_smooth"] == b) for b in STATES]
        lines.append("%-6s" % STATE_CN[a] + "".join("%7d" % x for x in row))
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blind", default=BLIND)
    a = ap.parse_args()

    d2 = collect(TRAIN)
    routine = collect(ROUTINE)
    blind = collect(a.blind)
    th = calibrate(d2 + routine)
    for r in d2 + routine + blind:
        r["pred"] = classify(r, th)
    smooth(d2 + routine + blind)
    hit, tot, hold = loro(d2, routine)

    lines = ["v4 波形检测：阈值在 data/calib/data_2 + data_routine（均为本人数据）上标定",
             "留一记录（data_2，%s）: %d/%d = %.4f" % (",".join(hold), hit, tot, hit / tot), ""]
    lines += report(d2, th, "本人 data_2") + [""]
    lines += report(routine, th, "本人 data_routine") + [""]
    lines += report(blind, th, "跨日 2026-10-25（盲测）") + [""]
    for tr, te, name in ((d2, routine, "data_routine"), (routine, d2, "data_2")):
        th_x = calibrate(tr)
        held = [dict(r) for r in te]
        for r in held:
            r["pred"] = classify(r, th_x)
        smooth(held)
        lines.append("跨数据集（同日另一时段）→ %s: %.4f"
                     % (name, sum(r["pred_smooth"] == r["state"] for r in held) / len(held)))
    lines.append("")
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "report.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))

    fields = ["dataset", "record", "state", "t0", "fs", "n_steps", "cadence", "sigma", "i_cv",
              "p_cv", "pt", "acp", "ac_lag", "score", "skew", "kurt", "zcr", "pred", "pred_smooth"]
    with open(os.path.join(OUT, "windows.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in d2 + routine + blind:
            w.writerow({k: (round(r[k], 4) if isinstance(r[k], float) else r[k]) for k in fields})


if __name__ == "__main__":
    main()
