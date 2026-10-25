#!/usr/bin/env python3
"""课题 08 v5 —— 零偏校正 / 打分 / 与 v4 的对比。

输出：output/v5/figures/fig18_ptn.png、fig19_score.png、fig20_compare.png
用法：MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/v5/make_figures_v5.py
"""
import csv
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager, rcParams

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SRC, "v2"))
sys.path.insert(0, os.path.join(SRC, "v4"))
sys.path.insert(0, HERE)

import gait_analysis_v2 as v2  # noqa: E402
import gait_analysis_v5 as v5  # noqa: E402

ROOT = v2.ROOT
FIG = os.path.join(ROOT, "output", "v5", "figures")
COLOR = {"stand": "#2ca02c", "walk": "#1f77b4", "run": "#d62728",
         "up": "#ff7f0e", "down": "#9467bd"}
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


def load(path):
    rows = list(csv.DictReader(open(path)))
    for r in rows:
        for k in r:
            if k not in ("dataset", "record", "state", "pred", "pred_smooth"):
                r[k] = float(r[k])
    return rows


def fig18_ptn(rows, th):
    from matplotlib.lines import Line2D

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), sharex=True)
    groups = [("walk", "平地慢走"), ("up", "上楼"), ("down", "下楼")]
    rng = np.random.default_rng(0)
    for ax, key, title in ((axes[0], "pt_raw", "v4：原始峰谷比 pt = mean(峰)/mean(谷)"),
                           (axes[1], "ptn", "v5：零偏校正 + 归一化 ptn")):
        for i, (st, label) in enumerate(groups, start=1):
            for blind, marker, alpha in ((False, "o", 0.45), (True, "s", 0.75)):
                v = [r[key] for r in rows
                     if r["state"] == st and (r["dataset"] == "2026-10-25") == blind]
                if not v:
                    continue
                x = i + rng.uniform(-0.18, 0.18, len(v))
                ax.scatter(x, v, s=14, marker=marker, alpha=alpha, color=COLOR[st],
                           edgecolors="none")
        ax.set_xticks([1, 2, 3])
        ax.set_xticklabels([g[1] for g in groups])
        ax.set_title(title, fontsize=10)
        ax.set_ylabel("比值")
    handles = [Line2D([], [], marker="o", ls="", color=COLOR[s], label=lab) for s, lab in groups]
    handles += [Line2D([], [], marker="o", ls="", color="#666", label="本人"),
                Line2D([], [], marker="s", ls="", color="#666", label="跨日盲测 10-25")]
    axes[0].legend(handles=handles, fontsize=7, loc="upper left", frameon=False, ncol=2)
    # v4 阈值与重叠
    wu = [r["pt_raw"] for r in rows if r["state"] in ("walk", "up") and r["dataset"] != "2026-10-25"]
    dv = [r["pt_raw"] for r in rows if r["state"] == "down" and r["dataset"] != "2026-10-25"]
    axes[0].axhline(1.1743, color="#333", ls="--", lw=1.0)
    axes[0].axhspan(min(dv), max(wu), color="#d62728", alpha=0.12)
    axes[0].text(1.55, max(wu) + 0.03, "极值重叠 %.2f–%.2f" % (min(dv), max(wu)), fontsize=8)
    axes[0].text(2.35, 1.1743 + 0.01, "v4 阈值 1.174", fontsize=8)
    # v5 阈值与间隔
    axes[1].axhline(th["down"], color="#333", ls="--", lw=1.0)
    ptn_dv = np.array([r["ptn"] for r in rows if r["state"] == "down" and r["dataset"] != "2026-10-25"])
    lo = max(float(np.percentile([r["ptn"] for r in rows if r["state"] == s and r["dataset"] != "2026-10-25"], 98)) for s in ("walk", "up"))
    hi = float(np.percentile(ptn_dv, 2))
    axes[1].axhspan(lo, hi, color="#2ca02c", alpha=0.15)
    axes[1].text(1.55, hi + 0.008, "98/2 分位间隔 %.3f–%.3f" % (lo, hi), fontsize=8)
    axes[1].text(2.35, th["down"] + 0.008, "v5 阈值 %.3f" % th["down"], fontsize=8)
    fig.suptitle("图 18　零偏校正前（左）后（右）：标定集上 ptn 留出间隔，跨日盲测的上尾仍越线", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig18_ptn.png"))


def fig19_score(rows, th):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    a_m, a_s = th["acp"]
    z_m, z_s = th["zcr"]
    t = th["up"]
    for st, label in (("walk", "平地慢走"), ("up", "上楼")):
        for blind, marker, alpha in ((False, "o", 0.45), (True, "s", 0.8)):
            v = [r for r in rows if r["state"] == st and (r["dataset"] == "2026-10-25") == blind]
            if not v:
                continue
            axes[0].scatter([r["acp"] for r in v], [r["zcr"] for r in v], s=14, marker=marker,
                            alpha=alpha, color=COLOR[st], edgecolors="none",
                            label="%s%s" % (label, "（跨日盲测）" if blind else ""))
    acp = np.linspace(0.35, 0.90, 50)
    zz = z_m + z_s * (-t - (acp - a_m) / a_s)
    axes[0].plot(acp, zz, "k--", lw=1.0, label="score_up = 阈值")
    axes[0].set_xlabel("acp（自相关峰）")
    axes[0].set_ylabel("zcr（过零率 /s）")
    axes[0].set_title("两个特征平面：虚线以上判上楼", fontsize=10)
    axes[0].legend(fontsize=7, loc="lower left", ncol=1, frameon=False)
    axes[0].set_xlim(0.35, 0.90)

    for st, label in (("walk", "平地慢走"), ("up", "上楼")):
        for blind, alpha, hatch in ((False, 0.55, None), (True, 0.30, "//")):
            s = [v5.up_score(r, th) for r in rows if r["state"] == st and (r["dataset"] == "2026-10-25") == blind]
            axes[1].hist(s, bins=28, alpha=alpha, color=COLOR[st], hatch=hatch,
                         label="%s%s" % (label, "（跨日盲测）" if blind else ""))
    axes[1].axvline(t, color="k", ls="--", lw=1.0)
    axes[1].text(t, axes[1].get_ylim()[1] * 0.92, " 阈值 %.2f" % t, fontsize=8)
    axes[1].set_xlabel("score_up = -z(acp) - z(zcr)")
    axes[1].set_ylabel("窗数")
    axes[1].set_title("score 分布：等权，权重不在测试集上调", fontsize=10)
    axes[1].legend(fontsize=7, loc="upper left", frameon=False)
    fig.suptitle("图 19　上楼/慢走的两特征打分：acp 之外再加一个过零率", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig19_score.png"))


def fig20_compare(v4rows, v5rows):
    # v4 的 routine 数据集名为 2026-10-24，v5 改名为 data_routine
    for r in v4rows:
        if r["dataset"] == "2026-10-24":
            r["dataset"] = "data_routine"
    datasets = [("data_2", "data_2 同集"), ("data_routine", "2026-10-24"), ("2026-10-25", "跨日盲测")]
    v4acc = [np.mean([r["pred_smooth"] == r["state"] for r in v4rows if r["dataset"] == d]) for d, _ in datasets]
    v5acc = [np.mean([r["pred_smooth"] == r["state"] for r in v5rows if r["dataset"] == d]) for d, _ in datasets]
    states = [("walk", "慢走"), ("run", "快跑"), ("up", "上楼"), ("down", "下楼")]
    v4cls = [np.mean([r["pred_smooth"] == r["state"] for r in v4rows if r["dataset"] == "2026-10-25" and r["state"] == s]) for s, _ in states]
    v5cls = [np.mean([r["pred_smooth"] == r["state"] for r in v5rows if r["dataset"] == "2026-10-25" and r["state"] == s]) for s, _ in states]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    x = np.arange(len(datasets))
    axes[0].bar(x - 0.2, [100 * a for a in v4acc], 0.38, label="v4", color="#8c8c8c")
    axes[0].bar(x + 0.2, [100 * a for a in v5acc], 0.38, label="v5", color="#1f77b4")
    for i, (a, b) in enumerate(zip(v4acc, v5acc)):
        axes[0].text(i - 0.2, 100 * a + 0.4, "%.1f" % (100 * a), ha="center", fontsize=8)
        axes[0].text(i + 0.2, 100 * b + 0.4, "%.1f" % (100 * b), ha="center", fontsize=8)
    axes[0].set_xticks(x)
    axes[0].set_xticklabels([n for _, n in datasets])
    axes[0].set_ylim(55, 102)
    axes[0].set_ylabel("窗口级准确率（平滑后，%）")
    axes[0].set_title("三个数据集", fontsize=10)
    axes[0].legend(fontsize=8)

    x = np.arange(len(states))
    axes[1].bar(x - 0.2, [100 * a for a in v4cls], 0.38, label="v4", color="#8c8c8c")
    axes[1].bar(x + 0.2, [100 * a for a in v5cls], 0.38, label="v5", color="#1f77b4")
    for i, (a, b) in enumerate(zip(v4cls, v5cls)):
        axes[1].text(i - 0.2, 100 * a + 1, "%.0f" % (100 * a), ha="center", fontsize=8)
        axes[1].text(i + 0.2, 100 * b + 1, "%.0f" % (100 * b), ha="center", fontsize=8)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels([n for _, n in states])
    axes[1].set_ylim(0, 108)
    axes[1].set_ylabel("逐类召回（盲测，%）")
    axes[1].set_title("跨日盲测 2026-10-25 逐类", fontsize=10)
    axes[1].legend(fontsize=8)
    fig.suptitle("图 20　v4 → v5：同集/同日跨时段小幅提升，跨日盲测 68.6 → 79.7", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig20_compare.png"))


def main():
    setup()
    rows = load(os.path.join(ROOT, "output", "v5", "features", "windows.csv"))
    train = [r for r in rows if r["dataset"] != "2026-10-25"]
    th = v5.calibrate(train)
    fig18_ptn(rows, th)
    fig19_score(rows, th)
    v4rows = load(os.path.join(ROOT, "output", "v4", "features", "windows.csv"))
    fig20_compare(v4rows, rows)
    print("figures ->", FIG)


if __name__ == "__main__":
    main()
