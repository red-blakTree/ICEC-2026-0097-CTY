#!/usr/bin/env python3
"""课题 08 v3 —— data_2（7 段）与 data_routine（9 段）上的 v2 / v3 对比图。

输出：output/v3/figures/fig9_compare.png、fig10_plane.png、fig11_confusion.png
用法：MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/v3/make_figures_v3.py
"""
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager, rcParams

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "v2"))

import gait_analysis_v2 as v2
import gait_analysis_v3 as v3

ROOT = v2.ROOT
FIG = os.path.join(ROOT, "output", "v3", "figures")
COLOR = {"stand": "#2ca02c", "walk": "#1f77b4", "run": "#d62728",
         "up": "#ff7f0e", "down": "#9467bd"}
ORDER = ["stand", "walk", "run", "up", "down"]
CJK = "/run/host/usr/share/fonts/google-droid-sans-fonts/DroidSansFallbackFull.ttf"


def setup():
    if os.path.exists(CJK):
        font_manager.fontManager.addfont(CJK)
        rcParams["font.family"] = ["DejaVu Sans", "Droid Sans Fallback"]
    rcParams["axes.unicode_minus"] = False
    rcParams["figure.dpi"] = 130
    rcParams["savefig.dpi"] = 130
    rcParams["axes.grid"] = True
    rcParams["grid.alpha"] = 0.25
    os.makedirs(FIG, exist_ok=True)


def load(tag):
    rows = v2.collect(os.path.join(ROOT, tag), 8.0, 1.0)
    for r in rows:
        r["dataset"] = tag
    return rows


def add_preds(d2, routine):
    th2 = v2.calibrate(d2)
    th3 = v3.calibrate(d2)
    for r in d2:
        r["p2"] = v2.classify(r, th2)
        r["p3"] = v3.classify(r, th3)
    for r in routine:
        r["p2x"] = v2.classify(r, th2)
        r["p3x"] = v3.classify(r, th3)
    by_state = {}
    for r in d2:
        by_state.setdefault(r["state"], set()).add(r["record"])
    holdable = sorted(n for names in by_state.values() if len(names) >= 2 for n in names)
    for name in holdable:
        tr = [r for r in d2 if r["record"] != name]
        a, b = v2.calibrate(tr), v3.calibrate(tr)
        for r in d2:
            if r["record"] == name:
                r["p2l"] = v2.classify(r, a)
                r["p3l"] = v3.classify(r, b)
    return th2, th3


def acc(rows, key):
    sel = [r for r in rows if key in r]
    return sum(r[key] == r["state"] for r in sel) / len(sel)


def fig9_compare(d2, routine):
    metrics = [
        ("data_2\n同集", acc(d2, "p2"), acc(d2, "p3")),
        ("data_2\n留一", acc(d2, "p2l"), acc(d2, "p3l")),
        ("data_routine\n跨数据集", acc(routine, "p2x"), acc(routine, "p3x")),
    ]
    x = np.arange(len(metrics))
    w = 0.36
    fig, ax = plt.subplots(figsize=(9.8, 5.2))
    b1 = ax.bar(x - w / 2, [m[1] for m in metrics], w, label="v2（σ_v/p99）", color="#9e9e9e")
    b2 = ax.bar(x + w / 2, [m[2] for m in metrics], w, label="v3（f_dom/r）", color="#1f77b4")
    for bars in (b1, b2):
        for b in bars:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.01,
                    "%.1f" % (100 * b.get_height()), ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([m[0] for m in metrics])
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("窗口级准确率")
    ax.legend(fontsize=9, loc="lower left")
    ax.set_title("图 9　v2 / v3：同集、留一记录、跨到 data_routine", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig9_compare.png"))
    plt.close(fig)


def fig10_plane(d2, routine, th3):
    rng = np.random.default_rng(0)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.4), sharey=True)
    for ax, (tag, rows) in zip(axes, (("data_2（7 段）", d2), ("data_routine（9 段）", routine))):
        for st in ORDER:
            v = [r for r in rows if r["state"] == st]
            jit = rng.uniform(-0.035, 0.035, len(v))
            ax.scatter([r["f_dom"] + j for r, j in zip(v, jit)], [r["ratio"] for r in v],
                       s=14, alpha=0.6, color=COLOR[st], edgecolors="none",
                       label="%s（%d）" % (v2.STATE_CN[st], len(v)))
        ax.axvline(th3["fd_up"], color="k", ls="--", lw=1.1)
        ax.axvline(th3["fd_down"], color="k", ls=":", lw=1.1)
        ax.axhline(th3["r_down"], color="k", ls="--", lw=1.1)
        ax.set_xlim(1.3, 4.4)
        ax.set_ylim(0.5, 3.6)
        ax.set_xlabel("主频 f_dom (Hz)")
        ax.set_title(tag, fontsize=10)
        ax.legend(fontsize=7.5, loc="upper right", ncol=2, frameon=False)
    axes[0].set_ylabel("竖向/横向能量比 r")
    fig.suptitle("图 10　v3 判决平面（阈值只在 data_2 上标定）", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig10_plane.png"))
    plt.close(fig)


def fig11_confusion(routine):
    M = np.array([[sum(1 for r in routine if r["state"] == a and r["p3x"] == b) for b in ORDER]
                  for a in ORDER])
    fig, ax = plt.subplots(figsize=(6.8, 5.6))
    im = ax.imshow(M, cmap="Blues")
    for i in range(len(ORDER)):
        for j in range(len(ORDER)):
            ax.text(j, i, M[i, j], ha="center", va="center",
                    color="white" if M[i, j] > M.max() * 0.6 else "black", fontsize=11)
    ax.set_xticks(range(len(ORDER)))
    ax.set_xticklabels([v2.STATE_CN[s] for s in ORDER])
    ax.set_yticks(range(len(ORDER)))
    ax.set_yticklabels([v2.STATE_CN[s] for s in ORDER])
    ax.set_xlabel("判决")
    ax.set_ylabel("真值")
    ax.set_title("图 11　v3 在 data_routine 上的混淆矩阵（data_2 标定）", fontsize=12)
    fig.colorbar(im, ax=ax, fraction=0.046)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig11_confusion.png"))
    plt.close(fig)


def main():
    setup()
    d2, routine = load("data/calib/data_2"), load("data/calib")
    th2, th3 = add_preds(d2, routine)
    print("thresholds v2:", {k: round(v, 3) for k, v in th2.items()})
    print("thresholds v3:", {k: round(v, 3) for k, v in th3.items()})
    fig9_compare(d2, routine)
    fig10_plane(d2, routine, th3)
    fig11_confusion(routine)
    print("figures written to", FIG)


if __name__ == "__main__":
    main()
