#!/usr/bin/env python3
"""课题 08 v6 评估：一次跑完全部口径。

    MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/v6/evaluate.py
    # 换盲测集只改 --blind-day
    MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/v6/evaluate.py \
        --blind-day data/blind/2026-10-26

口径（标定集固定为 data/calib/data_2 + data/calib/2026-10-24，均为本人 PKG110）：
  同集            标定集自身，只看拟合度
  留一记录        16 段全部轮留，每折重标定（最严格的同人同机协议）
  留一 walk/run   只留 data_2 的 4 段 walk/run（与 v4 协议一致，便于对照）
  跨日盲测        data/blind/2026-10-25（严格盲测，不参与任何选择）
  段级解码对照    none / ±2 多数票 / Viterbi，penalty 只在留一上选
  因果模式        只用过去窗的解码（在线可用）
  去重叠          每段每 8 窗取 1 窗，降低重叠窗对点准确率的放大

输出：<out>/report.txt、<out>/windows.csv
"""
import argparse
import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import features as F  # noqa: E402
import model as M  # noqa: E402
from features import ROOT, STATES, collect  # noqa: E402

DEFAULT_CALIB = ("data/calib/data_2", "data/calib/2026-10-24")
DEFAULT_BLIND_DAY = "data/blind/2026-10-25"
OUT = os.path.join(ROOT, "output", "v6")
CN = F.STATE_CN
STRIDE = 8
PENALTIES = (0.3, 0.6, 1.0)


def resolve(path):
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def tag(rows, name):
    for r in rows:
        r["dataset"] = name
    return rows


def load(paths):
    out = []
    for p in paths:
        full = resolve(p)
        out += tag(collect(full), os.path.basename(os.path.normpath(full)))
    missing = [s for s in STATES if not any(r["state"] == s for r in out)]
    if missing:
        raise SystemExit("标定集缺少类别 %s" % ", ".join(missing))
    return out


def wilson(k, n, z=1.959964):
    if n == 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - h), min(1.0, c + h)


def bootstrap_records(rows, key="pred_smooth", n_boot=2000, seed=0):
    """按记录重采样：窗之间高度重叠，独立样本数应记在记录上。"""
    groups = {}
    for r in rows:
        groups.setdefault(r["record"], []).append(r)
    names = sorted(groups)
    rng = np.random.default_rng(seed)
    accs = []
    for _ in range(n_boot):
        pick = rng.choice(len(names), len(names), replace=True)
        sub = [r for i in pick for r in groups[names[i]]]
        accs.append(sum(r[key] == r["state"] for r in sub) / len(sub))
    return float(np.percentile(accs, 2.5)), float(np.percentile(accs, 97.5))


def stride_subset(rows, stride=STRIDE):
    out = []
    for v in M._groups(rows):
        out += v[::stride]
    return out


def per_class(rows, key="pred_smooth"):
    out = {}
    for s in STATES:
        hit = sum(1 for r in rows if r["state"] == s and r[key] == s)
        tot = sum(1 for r in rows if r["state"] == s)
        if tot:
            out[s] = (hit, tot)
    return out


def confusion(rows, key="pred_smooth"):
    return [[sum(1 for r in rows if r["state"] == a and r[key] == b) for b in STATES]
            for a in STATES]


def loro(rows, mode="viterbi", penalty=0.6, states=None, dataset=None):
    """留一记录：每折重标定，返回 (命中, 总数, 逐类)。states/dataset 可限定协议。"""
    hit = tot = 0
    per = {s: [0, 0] for s in STATES}
    for v in M._groups(rows):
        if states and v[0]["state"] not in states:
            continue
        if dataset and v[0]["dataset"] != dataset:
            continue
        key = (v[0]["dataset"], v[0]["record"])
        train = [r for r in rows if (r["dataset"], r["record"]) != key]
        held = [r for r in rows if (r["dataset"], r["record"]) == key]
        th = M.calibrate(train)
        M.run(held, th, mode, penalty)
        for r in held:
            tot += 1
            ok = r["pred_smooth"] == r["state"]
            hit += ok
            per[r["state"]][1] += 1
            per[r["state"]][0] += ok
    return hit, tot, per


def gnb_loro(rows, keys=("rob_skew", "acp", "zcr", "log_sigma")):
    """学习型基线：对角高斯朴素贝叶斯，同样的留一协议，只用来回答"要不要上模型"。"""
    for r in rows:
        r["log_sigma"] = float(np.log(max(r["sigma"], 1e-3)))
    hit = tot = 0
    for v in M._groups(rows):
        key = (v[0]["dataset"], v[0]["record"])
        fit = [r for r in rows if (r["dataset"], r["record"]) != key]
        mu, var, prior = [], [], []
        for c in STATES:
            X = np.array([[r[k] for k in keys] for r in fit if r["state"] == c])
            mu.append(X.mean(0))
            var.append(X.var(0) + 1e-6)
            prior.append(np.log(len(X) / len(fit)))
        mu, var, prior = np.array(mu), np.array(var), np.array(prior)
        for r in v:
            x = np.array([r[k] for k in keys])
            ll = -0.5 * np.sum(np.log(2 * np.pi * var) + (x - mu) ** 2 / var, axis=1) + prior
            tot += 1
            hit += STATES[int(np.argmax(ll))] == r["state"]
    return hit / tot


def scored(rows, th, mode="viterbi", penalty=0.6):
    M.run(rows, th, mode, penalty)
    return M.accuracy(rows), M.record_accuracy(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calib", nargs="+", default=list(DEFAULT_CALIB))
    ap.add_argument("--blind-day", default=DEFAULT_BLIND_DAY)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--penalty", type=float, default=None, help="默认只在留一上选")
    a = ap.parse_args()

    train = load(a.calib)
    blind_sets = []
    for opt in (a.blind_day,):
        if opt:
            full = resolve(opt)
            if os.path.isdir(full):
                blind_sets.append((os.path.basename(os.path.normpath(full)),
                                   tag(collect(full), os.path.basename(os.path.normpath(full)))))

    # 1) 解码方式与 penalty 只在留一上选
    abl = []
    for mode, pen in [("none", 0.0), ("vote", 0.0)] + [("viterbi", p) for p in PENALTIES]:
        hit, tot, _ = loro(train, mode, pen)
        abl.append((mode, pen, hit / tot))
    if a.penalty is None:
        best = max(abl, key=lambda x: (x[2], -x[1]))
    else:
        best = next((x for x in abl if x[0] == "viterbi" and x[1] == a.penalty),
                    ("viterbi", a.penalty, 0.0))
    mode, penalty = best[0], best[1]
    if mode != "viterbi":
        mode, penalty = "viterbi", 0.6

    th = M.calibrate(train)
    lines = []
    lines.append("v6 评估：不变核 + 分位标定 + 段级解码")
    lines.append("标定：%s" % ", ".join(os.path.relpath(resolve(p), ROOT) for p in a.calib))
    lines.append("阈值：stand(sigma)=%.3f  run(sigma)=%.3f  down(%s)=%+.4f  up(score)=%+.3f"
                 % (th["stand"], th["run"], M.DOWN_KEY, th["down"], th["up"]))
    lines.append("解码：%s，penalty=%.2f（只在留一上选，不进盲测）" % (mode, penalty))
    lines.append("")
    lines.append("== 解码方式消融（留一记录，16 段 %d 窗）==" % len(train))
    for m, p, acc in abl:
        mark = " <= 选中" if (m, p) == (mode, penalty) else ""
        lines.append("  %-8s penalty=%.1f  留一 %.4f%s" % (m, p, acc, mark))
    gnb = gnb_loro(train)
    lines.append("  学习型基线（对角 GNB，[rob_skew, acp, zcr, log sigma]）留一 %.4f"
                 "（规则 %.4f）：16 段撑不起判别模型，v6 不引入学习层" % (gnb, max(x[2] for x in abl)))
    lines.append("")

    # 2) 同集与两个跨集
    lines.append("== 各口径（窗口级 / 记录级）==")
    for name in sorted({r["dataset"] for r in train}):
        rows = [r for r in train if r["dataset"] == name]
        acc, rec = scored(rows, th, mode, penalty)
        lines.append("  %-22s 窗口级 %.4f  记录级 %d/%d" % ("同集 " + name, acc, rec[0], rec[1]))
    hit, tot, per = loro(train, mode, penalty)
    lines.append("  %-22s 窗口级 %.4f  逐类 %s" % (
        "留一记录（16 段）", hit / tot,
        "  ".join("%s %d/%d" % (CN[s], per[s][0], per[s][1]) for s in STATES if per[s][1])))
    hit4, tot4, _ = loro(train, mode, penalty, states=("walk", "run"), dataset="data_2")
    lines.append("  %-22s 窗口级 %.4f" % ("留一 walk/run（data_2 4 段）", hit4 / tot4))
    for name, rows in blind_sets:
        acc, rec = scored(rows, th, mode, penalty)
        lo, hi = wilson(round(acc * len(rows)), len(rows))
        lines.append("  %-22s 窗口级 %.4f [%.3f, %.3f]  记录级 %d/%d  逐类 %s" % (
            "盲测 " + name, acc, lo, hi, rec[0], rec[1],
            "  ".join("%s %d/%d" % (CN[s], h, t) for s, (h, t) in per_class(rows).items())))
    lines.append("")

    # 3) 稳健性口径：因果解码、去重叠、bootstrap
    lines.append("== 稳健性与口径 ==")
    for name, rows in blind_sets:
        M.run(rows, th, mode, penalty, causal=True)
        acc_causal = M.accuracy(rows)
        M.run(rows, th, mode, penalty)                          # 恢复离线解码
        sub = stride_subset(rows)
        acc_stride = M.accuracy(sub)
        lo, hi = bootstrap_records(rows)
        lines.append("  %-22s 因果 %.4f | 去重叠 %.4f (%d 窗) | 记录 bootstrap [%.3f, %.3f]"
                     % (name, acc_causal, acc_stride, len(sub), lo, hi))
    lines.append("")

    # 4) 混淆矩阵（跨日盲测为主）
    if blind_sets:
        name, rows = blind_sets[0]
        M.run(rows, th, mode, penalty)
        lines.append("== 混淆矩阵：%s（行=真值，列=判决）==" % name)
        lines.append("%-6s" % "" + "".join("%8s" % CN[s] for s in STATES))
        for i, s in enumerate(STATES):
            lines.append("%-6s" % CN[s] + "".join("%8d" % x for x in confusion(rows)[i]))
        lines.append("")

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "report.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))

    # 5) 逐窗落盘（同集 + 两个盲测集，用离线解码的判决）
    fields = ["dataset", "record", "state", "t0", "rob_skew", "acp", "zcr",
              "sigma", "cadence", "i_cv", "pred", "pred_smooth"]
    allrows = train + [r for _, rows in blind_sets for r in rows]
    for rows in [train] + [rows for _, rows in blind_sets]:
        M.run(rows, th, mode, penalty)
    with open(os.path.join(a.out, "windows.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in allrows:
            w.writerow({k: (round(r[k], 5) if isinstance(r[k], float) else r[k]) for k in fields})
    print("\n输出：%s" % a.out)


if __name__ == "__main__":
    main()
