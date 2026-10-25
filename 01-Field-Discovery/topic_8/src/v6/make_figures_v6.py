#!/usr/bin/env python3
"""课题 08 v6 作图：判决量的不变性与版本对比。

输出：output/v6/figures/fig22_asym.png、fig23_versions.png
用法：MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/v6/make_figures_v6.py

数据来自已落盘的 windows.csv（v5.1 的同集与跨日盲测、blind_eval 的六版逐窗判决），
所以画图不重算信号，图和报告的数字必然一致。
"""
import csv
import os
import sys
from collections import Counter

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "v5"))

import gait_analysis_v5 as v5  # noqa: E402
import model as M  # noqa: E402
from features import ROOT  # noqa: E402

FIG = os.path.join(ROOT, "output", "v6", "figures")
TRAIN_CSV = os.path.join(ROOT, "output", "v5_1", "features", "windows.csv")
BLIND_CSV = os.path.join(ROOT, "output", "v5_1", "blind_2026-10-25", "windows.csv")
VERSIONS_CSV = os.path.join(ROOT, "output", "reports", "blind_2026-10-25", "windows.csv")
CJK = "/run/host/usr/share/fonts/google-droid-sans-fonts/DroidSansFallbackFull.ttf"
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
    os.makedirs(FIG, exist_ok=True)


def load(path):
    rows = list(csv.DictReader(open(path)))
    for r in rows:
        for k in ("t0", "rob_skew", "ptn", "acp", "zcr", "sigma", "cadence", "i_cv"):
            if k in r and r[k] != "":
                r[k] = float(r[k])
    return rows


def fig_asym(train, blind):
    rows = [r for r in train if r["dataset"] in ("data_2", "data_routine")]
    th = M.calibrate(rows)
    # v5 的 ptn 阈值按它自己的口径（几何中点）重算，画在同一张图上做对照
    th_ptn = v5._geometric(max(v5._quantile(rows, (s,), "ptn", 98) for s in ("walk", "up")),
                           v5._quantile(rows, ("down",), "ptn", 2))
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.8))
    groups = [("walk", "平地慢走"), ("up", "上楼"), ("down", "下楼")]
    for ax, key, title, thr in ((axes[0], "ptn", "v5 的 ptn：峰谷比，对零偏不变？否", th_ptn),
                                (axes[1], "rob_skew", "v5.1/v6 的 rob_skew：稳健偏度，不变", th["down"])):
        positions, data, colors = [], [], []
        for i, (state, _) in enumerate(groups):
            positions += [i * 3 + 1, i * 3 + 2]
            data += [[r[key] for r in train if r["state"] == state],
                     [r[key] for r in blind if r["state"] == state]]
            colors += [COLOR[state], COLOR[state]]
        bp = ax.boxplot(data, positions=positions, widths=0.7, patch_artist=True,
                        showfliers=False, medianprops=dict(color="black", lw=1.4))
        for patch, c, i in zip(bp["boxes"], colors, range(len(data))):
            patch.set_facecolor(c)
            patch.set_alpha(0.85 if i % 2 == 0 else 0.35)
            patch.set_hatch("" if i % 2 == 0 else "//")
        ax.set_xticks([1.5 + 3 * i for i in range(len(groups))])
        ax.set_xticklabels([name for _, name in groups])
        ax.axhline(0, color="gray", lw=0.8, ls=":")
        if thr is not None:
            ax.axhline(thr, color="crimson", lw=1.2, ls="--")
            ax.annotate("阈值 %.3f" % thr, (0.02, thr), xycoords=("axes fraction", "data"),
                        color="crimson", fontsize=9, va="bottom")
        ax.set_title(title, fontsize=11)
        ax.set_ylabel(key)
    from matplotlib.patches import Patch
    axes[0].legend(handles=[Patch(facecolor="gray", alpha=0.85, label="标定集（data_2 + 10-24）"),
                            Patch(facecolor="gray", alpha=0.35, hatch="//", label="跨日盲测（10-25）")],
                   fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig22_asym.png"))
    plt.close(fig)


def fig_versions(rows):
    cols = [("pred_v2", "v2"), ("pred_v3", "v3"), ("pred_v4", "v4"),
            ("pred_v5", "v5"), ("pred_v51", "v5.1"), ("pred_v6", "v6")]
    names, accs, recs = [], [], []
    for col, label in cols:
        names.append(label)
        accs.append(100 * sum(r[col] == r["state"] for r in rows) / len(rows))
        by_rec = {}
        for r in rows:
            by_rec.setdefault(r["record"], []).append(r)
        ok = sum(Counter(r[col] for r in rows_of).most_common(1)[0][0] == rows_of[0]["state"]
                 for rows_of in by_rec.values())
        recs.append("%d/%d" % (ok, len(by_rec)))
    fig, ax = plt.subplots(figsize=(8.6, 4.4))
    bars = ax.bar(names, accs, color=["#bbbbbb"] * 4 + ["#1f77b4", "#d62728"])
    for bar, acc, rec in zip(bars, accs, recs):
        ax.annotate("%.1f%%\n记录 %s" % (acc, rec), (bar.get_x() + bar.get_width() / 2, acc),
                    ha="center", va="bottom", fontsize=9)
    ax.set_ylim(0, 112)
    ax.set_ylabel("窗口级准确率（%）")
    ax.set_title("跨日盲测 2026-10-25（704 窗 / 9 段，不参与任何选择）")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig23_versions.png"))
    plt.close(fig)


def main():
    setup()
    train = load(TRAIN_CSV)
    blind = load(BLIND_CSV)
    fig_asym(train, [r for r in blind if r["dataset"] == "2026-10-25"])
    fig_versions(load(VERSIONS_CSV))
    print("输出：%s" % FIG)


if __name__ == "__main__":
    main()
