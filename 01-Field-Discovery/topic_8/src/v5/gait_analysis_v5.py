#!/usr/bin/env python3
"""课题 08 v5 —— 零偏校正 + 稳健标定 + 两特征打分。

v4 已经是波形检测，但有两处可被"设备/佩戴"带偏：
  1. a_v 在每个 8 s 窗内仍有残余直流（中位数 |bias| 0.36 m/s²，最大 6.2），
     峰/谷比 pt = mean(峰)/mean(谷) 会被这个直流系统性压低或抬高；
  2. 四个阈值用 max/min 极值定，单个异常窗就能把阈值拖走。

v5 的改动（只改这三处）：
  - 对 a_v 先减窗内中位数再做峰/谷检测，用归一化峰谷比
        ptn = (mean(pv) - mean(tv)) / (mean(pv) + mean(tv))
    判下楼；ptn 是幅值比，设备增益/佩戴角度只影响 pv、tv 的共同尺度，
    不影响 ptn，因而比原始 pt 更接近“不变”。
  - 阈值改用 2 % / 98 % 分位数之间的几何中点，避开极值。
  - 上楼/慢走不再只用 acp 一刀切，而是两特征等权打分：
        score_up = -z(acp) - z(zcr)
    其中 zcr 是竖向波形的过零率（8 s 窗内的过零次数 / 时长）。
    权重固定为 1，不在测试集上调参。
  - 判决仍是"静止/快跑门限 → 下楼 → 上楼/慢走"，后接 ±2 窗多数票平滑。

未采纳（见 README 第 8.1 节的逐条核查）：
  - scipy.signal.find_peaks / prominence 替换：无 scipy 依赖；
    自实现 prominence 版本在留一记录上从 95.6 % 掉到 87.5–90.0 %，故不替换。
  - i_cv / cadence 进打分：有涨有跌、无稳定增益，故只作为诊断量输出。
  - 幅值缩放类"设备对齐"：v5 的判决特征全是比值/无量纲量，不做缩放。

标定：data/calib/data_2 + data_routine（均为本人 PKG110）
盲测：data/blind/2026-10-25（跨日，本人 PKG110），不参与任何阈值/权重选择。
输出：output/v5/features/{windows.csv,report.txt}、output/v5/figures/
用法：MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/v5/gait_analysis_v5.py
"""
import argparse
import csv
import os
import sys
from collections import Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "v2"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "v4"))
from gait_analysis_v2 import (  # noqa: E402
    ROOT, STATE_CN, clean, find_records, infer_truth, load_record, sample_rate,
)
from gait_analysis_v4 import detect_peaks, moving_average, smooth  # noqa: E402

OUT = os.path.join(ROOT, "output", "v5", "features")
TRAIN = os.path.join(ROOT, "data", "calib", "data_2")
# 2026-10-25 起，data_routine 下出现新日期；新日期留作跨日盲测，标定只用 10-24。
ROUTINE = os.path.join(ROOT, "data", "calib", "2026-10-24")
BLIND = os.path.join(ROOT, "data", "blind", "2026-10-25")
STATES = ("stand", "walk", "run", "up", "down")
QUANT = 0.02  # 标定用 2 % / 98 % 分位，避开极值


def _quantile(rows, states, key, p):
    v = np.array([r[key] for r in rows if r["state"] in states])
    return float(np.percentile(v, p))


def _geometric(a, b):
    a, b = float(a), float(b)
    return float(np.sqrt(a * b)) if a > 0 and b > 0 else 0.5 * (a + b)


def _best_split(scores, labels):
    """score 越大越像上楼；返回使 walk/up 命中数最大的阈值。"""
    order = np.argsort(scores)
    v, y = scores[order], labels[order]
    n = len(v)
    suffix_up = np.zeros(n + 1)
    prefix_walk = np.zeros(n + 1)
    for i in range(n - 1, -1, -1):
        suffix_up[i] = suffix_up[i + 1] + (y[i] == 1)
    for i in range(n):
        prefix_walk[i + 1] = prefix_walk[i] + (y[i] == 0)
    k = int(np.argmax(suffix_up + prefix_walk))
    if k == 0:
        return float(v[0] - 1e-9)
    if k == n:
        return float(v[-1] + 1e-9)
    return float(0.5 * (v[k - 1] + v[k]))


def _zstats(rows, key):
    v = np.array([r[key] for r in rows if r["state"] in ("walk", "up")])
    return float(v.mean()), float(v.std() + 1e-9)


def up_score(f, th):
    a_m, a_s = th["acp"]
    z_m, z_s = th["zcr"]
    return -(f["acp"] - a_m) / a_s - (f["zcr"] - z_m) / z_s


def waveform_features(t, ax, ay, az, gx, gy, gz):
    """检测峰/谷，返回判决特征与诊断特征。"""
    gn = np.sqrt(gx * gx + gy * gy + gz * gz)
    ux, uy, uz = gx / gn, gy / gn, gz / gn
    a_v = ax * ux + ay * uy + az * uz - gn
    dyn = np.sqrt((ax - gx) ** 2 + (ay - gy) ** 2 + (az - gz) ** 2)
    fs = sample_rate(t)
    s = moving_average(a_v, 0.08 * fs)
    dur = len(s) / fs
    bias = float(np.median(s))
    s0 = s - bias

    # 未校正（v4 口径）的 pt，仅用于对照/作图
    raw_pk = detect_peaks(s, fs)
    raw_tr = detect_peaks(-s, fs)
    pv_raw = s[raw_pk] if len(raw_pk) else np.array([0.0])
    tv_raw = -s[raw_tr] if len(raw_tr) else np.array([0.0])
    pt_raw = float(pv_raw.mean() / (tv_raw.mean() + 1e-9))

    # 零偏校正后的峰/谷比
    peaks = detect_peaks(s0, fs)
    troughs = detect_peaks(-s0, fs)
    pv = s0[peaks] if len(peaks) else np.array([0.0])
    tv = -s0[troughs] if len(troughs) else np.array([0.0])
    ptn = float((pv.mean() - tv.mean()) / (pv.mean() + tv.mean() + 1e-9))

    # 稳健偏度：分子分母都是同类差值，对加性偏移与增益都不变。
    # ptn 的分子分母含 pv+tv，给窗内所有样本加常数会改变它们，
    # 跨日残余零偏/重力方向泄漏因此直接跨过阈值（README §8.6、§8.7）。
    q05, q95 = np.percentile(s0, [5, 95])
    rob_skew = float((q95 + q05 - 2 * np.median(s0)) / (q95 - q05 + 1e-9))

    # 自相关峰（对常数平移不变）
    ac = np.correlate(s0 - s0.mean(), s0 - s0.mean(), "full")[len(s0) - 1:]
    ac = ac / (ac[0] + 1e-9)
    lo, hi = max(1, int(0.30 * fs)), min(len(ac) - 1, int(1.20 * fs))
    acp = float(ac[lo:hi].max()) if hi > lo else 0.0
    ac_lag = (lo + int(np.argmax(ac[lo:hi]))) / fs if hi > lo else 0.0

    intervals = np.diff(peaks) / fs if len(peaks) >= 2 else np.array([])
    i_cv = float(np.std(intervals) / (abs(np.mean(intervals)) + 1e-9)) if len(intervals) >= 2 else 0.0
    return dict(
        fs=fs, bias=bias, n_steps=len(peaks), cadence=len(peaks) / dur, i_cv=i_cv,
        pt_raw=pt_raw, ptn=ptn, rob_skew=rob_skew, acp=acp, ac_lag=ac_lag,
        zcr=float(np.sum(np.diff(np.signbit(s - s.mean())) != 0) / dur),
        sigma=float(dyn.std()),
    )


def collect(root, tag=None):
    tag = tag or os.path.basename(os.path.normpath(root))
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


def calibrate(rows, asym="ptn"):
    """阈值只在传入的 rows（本人数据）上标定；asym 选下楼/非下楼的判决量。"""
    motion = ("walk", "run", "up", "down")
    t_stand = _geometric(_quantile(rows, ("stand",), "sigma", 100 - 100 * QUANT),
                         min(_quantile(rows, (s,), "sigma", 100 * QUANT) for s in motion))
    t_run = _geometric(max(_quantile(rows, (s,), "sigma", 100 - 100 * QUANT) for s in ("walk", "up", "down")), _quantile(rows, ("run",), "sigma", 100 * QUANT))
    a_down = max(_quantile(rows, (s,), asym, 100 - 100 * QUANT) for s in ("walk", "up"))
    b_down = _quantile(rows, ("down",), asym, 100 * QUANT)
    if asym == "ptn":
        # v5 历史口径冻结，保证 README 里的 79.7 % 可复现
        t_down = _geometric(a_down, b_down)
    else:
        # 有符号量用算术中点：几何中点会被 0 附近的 q98 拉向多数类，
        # 单侧标定时阈值贴着 walk/up 的上尾（routine→data_2 从 94 % 掉到 83 %，见 README §8.7）
        t_down = 0.5 * (a_down + b_down)
    th = dict(stand=t_stand, run=t_run, down=t_down, asym=asym,
              acp=_zstats(rows, "acp"), zcr=_zstats(rows, "zcr"), up=0.0)
    scores, labels = [], []
    for r in rows:
        if r["sigma"] < t_stand or r["sigma"] > t_run or r[asym] > t_down:
            continue
        if r["state"] in ("walk", "up"):
            scores.append(up_score(r, th))
            labels.append(1 if r["state"] == "up" else 0)
    th["up"] = _best_split(np.array(scores), np.array(labels))
    return th


def classify(f, th):
    if f["sigma"] < th["stand"]:
        return "stand"
    if f["sigma"] > th["run"]:
        return "run"
    if f[th.get("asym", "ptn")] > th["down"]:
        return "down"
    return "up" if up_score(f, th) > th["up"] else "walk"


def _accuracy(rows, key="pred_smooth"):
    return sum(r[key] == r["state"] for r in rows) / len(rows)


def _confusion(rows, lines):
    lines.append("混淆矩阵（平滑后，行=真值，列=判决）:")
    lines.append("%-6s" % "" + "".join("%7s" % STATE_CN[s] for s in STATES))
    for a in STATES:
        row = [sum(1 for r in rows if r["state"] == a and r["pred_smooth"] == b) for b in STATES]
        lines.append("%-6s" % STATE_CN[a] + "".join("%7d" % x for x in row))


def report(rows, th, title):
    for r in rows:
        r["pred"] = classify(r, th)
    smooth(rows)
    lines = ["== %s ==" % title,
             "阈值: " + ", ".join("%s=%.3f" % (k, v) for k, v in
                                  (("stand", th["stand"]), ("run", th["run"]),
                                   ("down", th["down"]), ("up", th["up"]))),
             "打分归一化: acp (%.3f, %.3f), zcr (%.3f, %.3f)"
             % (th["acp"][0], th["acp"][1], th["zcr"][0], th["zcr"][1]), ""]
    for name in sorted(set(r["record"] for r in rows)):
        v = [r for r in rows if r["record"] == name]
        truth = v[0]["state"]
        raw = sum(r["pred"] == truth for r in v)
        sm = sum(r["pred_smooth"] == truth for r in v)
        major = Counter(r["pred_smooth"] for r in v).most_common(1)[0][0]
        lines.append("%-18s truth=%-5s windows=%3d raw=%3d/%-3d smooth=%3d/%-3d majority=%s"
                     % (name, truth, len(v), raw, len(v), sm, len(v), STATE_CN[major]))
    lines.append("窗口级: raw %d/%d = %.4f; 平滑 %d/%d = %.4f"
                 % (sum(r["pred"] == r["state"] for r in rows), len(rows), _accuracy(rows, "pred"),
                    sum(r["pred_smooth"] == r["state"] for r in rows), len(rows), _accuracy(rows)))
    recs = sorted(set(r["record"] for r in rows))
    ok = 0
    for name in recs:
        v = [r for r in rows if r["record"] == name]
        major = Counter(r["pred_smooth"] for r in v).most_common(1)[0][0]
        ok += major == v[0]["state"]
    lines.append("记录级（平滑）: %d/%d" % (ok, len(recs)))
    _confusion(rows, lines)
    return lines


def _fit_eval(train, held, asym="ptn"):
    th = calibrate(train, asym)
    for r in held:
        r["pred"] = classify(r, th)
    smooth(held)
    return th


def leave_one_record_out(rows, states=None, dataset=None, asym="ptn"):
    """留一记录交叉验证；states/dataset 给定时只留这些记录（如 v4 的 walk/run 协议）。"""
    hit = tot = 0
    per = {st: [0, 0] for st in STATES}
    for key in sorted({(r["dataset"], r["record"]) for r in rows}):
        held_state = next(r["state"] for r in rows if (r["dataset"], r["record"]) == key)
        if states and held_state not in states:
            continue
        if dataset and key[0] != dataset:
            continue
        train = [r for r in rows if (r["dataset"], r["record"]) != key]
        held = [r for r in rows if (r["dataset"], r["record"]) == key]
        _fit_eval(train, held, asym)
        for r in held:
            tot += 1
            hit += r["pred_smooth"] == r["state"]
            per[r["state"]][1] += 1
            per[r["state"]][0] += r["pred_smooth"] == r["state"]
    return hit, tot, per


def leave_one_dataset_out(rows, asym="ptn"):
    out = []
    for train_tag, test_tag in (("data_2", "data_routine"), ("data_routine", "data_2")):
        train = [r for r in rows if r["dataset"] == train_tag]
        test = [r for r in rows if r["dataset"] == test_tag]
        th = calibrate(train, asym)
        for r in test:
            r["pred"] = classify(r, th)
        smooth(test)
        out.append((test_tag, _accuracy(test)))
    return out


def margins(rows, th):
    """阈值两侧的稳健间隔（2 %/98 % 分位）。"""
    wu = ("walk", "up")
    lines = ["特征间隔（2 %/98 % 分位，越大越稳）:"]
    lines.append("  sigma : stand q98=%.3f | motion q2=%.3f | 阈值 %.3f"
                 % (_quantile(rows, ("stand",), "sigma", 98), min(_quantile(rows, (s,), "sigma", 2) for s in ("walk", "run", "up", "down")), th["stand"]))
    lines.append("  sigma : non-run q98=%.3f | run q2=%.3f | 阈值 %.3f"
                 % (max(_quantile(rows, (s,), "sigma", 98) for s in ("walk", "up", "down")), _quantile(rows, ("run",), "sigma", 2), th["run"]))
    lines.append("  %-6s: walk/up q98=%.3f | down q2=%.3f | 阈值 %.3f"
                 % (th.get("asym", "ptn"), max(_quantile(rows, (s,), th.get("asym", "ptn"), 98) for s in wu),
                    _quantile(rows, ("down",), th.get("asym", "ptn"), 2), th["down"]))
    lines.append("  pt_raw: walk/up max=%.3f | down min=%.3f（v4 口径，极值标定；重叠说明它不稳）"
                 % (max(r["pt_raw"] for r in rows if r["state"] in wu), min(r["pt_raw"] for r in rows if r["state"] == "down")))
    lines.append("")
    return lines


def main(asym="ptn", default_out=OUT, title="v5"):
    ap = argparse.ArgumentParser()
    ap.add_argument("--blind", default=BLIND)
    ap.add_argument("--out", default=default_out)
    ap.add_argument("--asym", default=asym, choices=("ptn", "rob_skew"),
                    help="下楼/非下楼判决量：ptn=v5 口径，rob_skew=v5.1")
    a = ap.parse_args()

    d2 = collect(TRAIN, "data_2")
    routine = collect(ROUTINE, "data_routine")
    blind = collect(a.blind)
    train = d2 + routine
    th = calibrate(train, a.asym)

    lines = ["%s 零偏校正 + 分位标定 + acp/zcr 等权打分" % title,
             "下楼/非下楼判决量: %s" % a.asym,
             "标定集: data/calib/data_2 + data/calib/2026-10-24（本人 PKG110）；盲测: %s" % os.path.basename(os.path.normpath(a.blind)),
             "分位标定 q=%.2f；up 打分权重固定 1（不在测试集上调）" % QUANT, ""]
    lines += margins(train, th)
    lines += report(d2, th, "本人 data_2（in-sample）") + [""]
    lines += report(routine, th, "本人 data/calib/2026-10-24（in-sample）") + [""]
    lines += report(blind, th, "盲测 %s" % os.path.basename(os.path.normpath(a.blind))) + [""]

    # 先把 in-sample 判决落盘，再做留一/跨数据集（后者会覆盖 pred 字段）
    os.makedirs(a.out, exist_ok=True)
    fields = ["dataset", "record", "state", "t0", "fs", "bias", "n_steps", "cadence", "i_cv",
              "pt_raw", "ptn", "rob_skew", "acp", "ac_lag", "zcr", "sigma", "pred", "pred_smooth"]
    with open(os.path.join(a.out, "windows.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in train + blind:
            w.writerow({k: (round(r[k], 5) if isinstance(r[k], float) else r[k]) for k in fields})

    hit, tot, per = leave_one_record_out(train, asym=a.asym)
    hit_wr, tot_wr, _ = leave_one_record_out(train, states=("walk", "run"), dataset="data_2", asym=a.asym)
    lines.append("留一记录（全部 %d 段，含上/下楼/静止）: %d/%d = %.4f" % (len({r["record"] for r in train}), hit, tot, hit / tot))
    lines.append("留一逐类: " + "  ".join("%s %d/%d" % (STATE_CN[s], per[s][0], per[s][1]) for s in STATES))
    lines.append("留一记录（仅 data_2 walk/run，与 v4 协议一致）: %d/%d = %.4f" % (hit_wr, tot_wr, hit_wr / tot_wr))
    for tag, acc in leave_one_dataset_out(train, a.asym):
        lines.append("跨数据集（本人另一天）→ %s: %.4f" % (tag, acc))
    lines.append("")

    with open(os.path.join(a.out, "report.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
