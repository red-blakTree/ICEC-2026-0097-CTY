#!/usr/bin/env python3
"""课题 08 v5 —— 2026-10-25 跨日盲测图与对比表。

协议：v2/v3 用 data/calib/data_2 标定；v4/v5 用 data_2 + data/calib/2026-10-24 标定；
`data/blind/2026-10-25` 只做测试，不参与任何阈值/权重选择。

输出：output/v5_2026-10-25/{compare.txt,fig21_date_blind.png}
用法：MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/v5/make_figure_date.py
"""
import argparse
import os
import sys
from collections import Counter

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager, rcParams

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
for sub in ("v2", "v3", "v4", "v5"):
    sys.path.insert(0, os.path.join(SRC, sub))

import gait_analysis_v2 as v2  # noqa: E402
import gait_analysis_v3 as v3  # noqa: E402
import gait_analysis_v4 as v4  # noqa: E402
import gait_analysis_v5 as v5  # noqa: E402

ROOT = v2.ROOT
CJK = "/run/host/usr/share/fonts/google-droid-sans-fonts/DroidSansFallbackFull.ttf"
STATES = ("stand", "walk", "run", "up", "down")
CN = v2.STATE_CN
COLOR = {"stand": "#2ca02c", "walk": "#1f77b4", "run": "#d62728",
         "up": "#ff7f0e", "down": "#9467bd"}


def setup():
    if os.path.exists(CJK):
        font_manager.fontManager.addfont(CJK)
        rcParams["font.family"] = ["DejaVu Sans", "Droid Sans Fallback"]
    rcParams["axes.unicode_minus"] = False
    rcParams["figure.dpi"] = 130
    rcParams["savefig.dpi"] = 130
    rcParams["axes.grid"] = True
    rcParams["grid.alpha"] = 0.25


def tag(rows, name):
    for r in rows:
        r["dataset"] = name
    return rows


def collect_v2(root):
    return tag(v2.collect(root, 8.0, 1.0), os.path.basename(os.path.normpath(root)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", default=os.path.join(ROOT, "data", "blind", "2026-10-25"))
    ap.add_argument("--out", default=os.path.join(ROOT, "output", "v5", "blind_2026-10-25"))
    a = ap.parse_args()
    test_dir = a.test if os.path.isabs(a.test) else os.path.join(ROOT, a.test)
    out_dir = a.out if os.path.isabs(a.out) else os.path.join(ROOT, a.out)
    os.makedirs(out_dir, exist_ok=True)
    setup()
    test_name = os.path.basename(os.path.normpath(test_dir))

    # v2 / v3：data_2 标定
    d2_2 = collect_v2(os.path.join(ROOT, "data", "calib", "data_2"))
    te_2 = collect_v2(test_dir)
    th2, th3 = v2.calibrate(d2_2), v3.calibrate(d2_2)
    for r in te_2:
        r["m2"] = v2.classify(r, th2)
        r["m3"] = v3.classify(r, th3)
        r["pred"] = r["m3"]
    v3.smooth(te_2)
    for r in te_2:
        r["m3s"] = r["pred_smooth"]
        r["pred_smooth_m2"] = r["m2"]

    # v4 / v5：data_2 + 2026-10-24 标定
    d2_4 = tag(v4.collect(os.path.join(ROOT, "data", "calib", "data_2")), "data_2")
    r24_4 = tag(v4.collect(os.path.join(ROOT, "data", "calib", "2026-10-24")), "data_routine")
    te_4 = tag(v4.collect(test_dir), test_name)
    th4 = v4.calibrate(d2_4 + r24_4)
    for r in te_4:
        r["m4"] = v4.classify(r, th4)
        r["pred"] = r["m4"]
    v4.smooth(te_4)
    for r in te_4:
        r["m4s"] = r["pred_smooth"]

    d2_5 = tag(v5.collect(os.path.join(ROOT, "data", "calib", "data_2"), "data_2"), "data_2")
    r24_5 = tag(v5.collect(os.path.join(ROOT, "data", "calib", "2026-10-24"), "data_routine"), "data_routine")
    te_5 = tag(v5.collect(test_dir), test_name)
    th5 = v5.calibrate(d2_5 + r24_5)
    for r in te_5:
        r["m5"] = v5.classify(r, th5)
        r["pred"] = r["m5"]
    v5.smooth(te_5)
    for r in te_5:
        r["m5s"] = r["pred_smooth"]

    methods = [("v2", te_2, "pred_smooth_m2"), ("v3+平滑", te_2, "m3s"),
               ("v4+平滑", te_4, "m4s"), ("v5+平滑", te_5, "m5s")]
    rows = [r for r in te_5]
    recs = sorted({r["record"] for r in rows}, key=lambda n: (v2.infer_truth(n), n))
    states = [s for s in STATES if any(r["state"] == s for r in rows)]

    def per_record(rws, key):
        out = {}
        for name in recs:
            v = [r for r in rws if r["record"] == name]
            out[name] = Counter(r[key] for r in v).most_common(1)[0][0] == v[0]["state"]
        return out

    def per_class(rws, key):
        return {s: sum(r[key] == s for r in rws if r["state"] == s) / max(1, sum(1 for r in rws if r["state"] == s))
                for s in states}

    def window_acc(rws, key):
        return sum(r[key] == r["state"] for r in rws) / len(rws)

    lines = ["%s 跨日盲测（%d 窗 / %d 段）" % (test_name, len(rows), len(recs)),
             "标定：v2/v3 = data_2；v4/v5 = data_2 + data/calib/2026-10-24", ""]
    for label, rws, key in methods:
        pr = per_record(rws, key)
        lines.append("%-8s 窗口 %.4f  记录 %d/%d  %s" % (
            label, window_acc(rws, key), sum(pr.values()), len(recs),
            "  ".join("%s:%s" % (n, "OK" if ok else "X") for n, ok in pr.items())))

    # 图：逐记录 / 逐类 / 混淆
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    labels = [n.replace("go_", "").replace("2026-10-24/", "") for n in recs]
    x = np.arange(len(recs))
    for j, (label, rws, key) in enumerate(methods[-2:]):
        vals = []
        for n in recs:
            v = [r for r in rws if r["record"] == n]
            vals.append(100 * sum(r[key] == r["state"] for r in v) / len(v))
        axes[0].bar(x + (j - 0.5) * 0.38, vals, 0.36, label=label.split("+")[0],
                    color="#8c8c8c" if j == 0 else "#1f77b4")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    axes[0].set_ylim(0, 108)
    axes[0].set_ylabel("逐记录窗口准确率（%，平滑后）")
    axes[0].set_title("逐记录：上楼/慢走是主要失分点", fontsize=10)
    axes[0].legend(fontsize=8, loc="lower left")

    x = np.arange(len(states))
    for j, (label, rws, key) in enumerate(methods[-2:]):
        pc = per_class(rws, key)
        axes[1].bar(x + (j - 0.5) * 0.38, [100 * pc[s] for s in states], 0.36,
                    label=label.split("+")[0], color="#8c8c8c" if j == 0 else "#1f77b4")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels([CN[s] for s in states])
    axes[1].set_ylim(0, 108)
    axes[1].set_ylabel("窗口级逐类召回（%）")
    axes[1].set_title("逐类：上楼只剩 %.0f%%" % (100 * per_class(te_5, "m5s")["up"]), fontsize=10)
    axes[1].legend(fontsize=8, loc="lower left")

    mat = np.array([[sum(1 for r in te_5 if r["state"] == a and r["m5s"] == b) for b in states] for a in states])
    im = axes[2].imshow(mat, cmap="Blues")
    axes[2].set_xticks(range(len(states)))
    axes[2].set_xticklabels([CN[s] for s in states], fontsize=8)
    axes[2].set_yticks(range(len(states)))
    axes[2].set_yticklabels([CN[s] for s in states], fontsize=8)
    axes[2].set_xlabel("判决")
    axes[2].set_ylabel("真值")
    axes[2].set_title("v5 混淆（行=真值）", fontsize=10)
    for i in range(len(states)):
        for j in range(len(states)):
            if mat[i, j]:
                axes[2].text(j, i, "%d" % mat[i, j], ha="center", va="center",
                             color="white" if mat[i, j] > mat.max() * 0.55 else "#222", fontsize=9)
    fig.colorbar(im, ax=axes[2], fraction=0.046, pad=0.04)
    fig.suptitle("图 21　2026-10-25 跨日盲测：记录级 9/9，窗口级 79.7 %；主要错误是把上楼/慢走判成下楼", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "fig21_date_blind.png"))

    lines += [
        "",
        "v5 窗口混淆（行=真值，列=判决）:",
        "        " + "".join("%8s" % CN[s] for s in states),
    ]
    for a in states:
        lines.append("%-6s" % CN[a] + "".join("%8d" % mat[states.index(a), states.index(b)] for b in states))
    lines += ["",
              "注：窗口级 79.7 % 是严格跨日盲测；记录级 9/9 说明每段的活动类型仍可由多数票判对，",
              "但窗口级受 ptn/acp 的跨日基线漂移影响，不能把同集 98.0 % 当泛化数字。"]
    with open(os.path.join(out_dir, "compare.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
