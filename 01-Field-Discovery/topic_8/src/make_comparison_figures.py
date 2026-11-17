#!/usr/bin/env python3
"""生成 v1–v7 版本对比图（报告用，只读现有评估结果，不重跑模型）。

数据来源：
  output/v1/features/windows.csv           v1 4 类逐窗结果
  output/v1/features/eval.txt               v1 全量 1049/1058
  output/reports/blind_2026-11-17/          11-17 六版逐窗结果
  output/svm/blind_2026-11-17/              v7 11-17 逐窗结果
  各版本 report.txt / README 第 4.1 节     手工转录的窗口级准确率

输出：output/compare/figures/fig_compare_*.png
用法：MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/make_comparison_figures.py
"""
import csv
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager, rcParams

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output", "compare", "figures")
CJK = "/run/host/usr/share/fonts/google-droid-sans-fonts/DroidSansFallbackFull.ttf"

# ---- 5 类 / 8 s 窗，窗口级准确率（%）；来源见文件头 ----
VERSIONS = ["v2", "v3", "v4", "v5", "v5.1", "v6", "v7"]
SAME = {"v2": 97.4, "v3": 91.1, "v4": 97.4, "v5": 98.0, "v5.1": 98.0, "v6": 98.0}
LOO = {"v4": 91.9, "v5": 95.65, "v5.1": 95.54, "v6": 95.86}
BLIND = {"v2": 42.8, "v3": 45.3, "v4": 68.6, "v5": 79.7,
         "v5.1": 94.6, "v6": 94.5, "v7": 92.8}
THREE = {"v2": 66.5, "v3": 78.5, "v4": 89.2, "v5": 90.9,
         "v5.1": 93.3, "v6": 92.7}
D17 = {"v2": 59.6, "v3": 67.7, "v4": 80.6, "v5": 81.5,
       "v5.1": 86.8, "v6": 87.8, "v7": 94.5}
D17_NOSWING = {"v2": 0.4, "v3": 26.4, "v4": 35.4, "v5": 37.1,
               "v5.1": 37.1, "v6": 37.1, "v7": 94.5}

COLOR = {"v2": "#9ecae1", "v3": "#6baed6", "v4": "#3182bd", "v5": "#08519c",
         "v5.1": "#2ca02c", "v6": "#d62728", "v7": "#ff7f0e"}
CN = {"walk": "平地慢走", "run": "快跑", "stairs": "上下楼梯", "stand": "静止"}


def setup():
    if os.path.exists(CJK):
        font_manager.fontManager.addfont(CJK)
        rcParams["font.family"] = ["DejaVu Sans", "Droid Sans Fallback"]
    rcParams["axes.unicode_minus"] = False
    rcParams["figure.dpi"] = 140
    rcParams["savefig.dpi"] = 140
    rcParams["axes.grid"] = True
    rcParams["grid.alpha"] = 0.25
    os.makedirs(OUT, exist_ok=True)


def bar_labels(ax, bars, values, fmt="%.1f"):
    for bar, v in zip(bars, values):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        ax.text(bar.get_x() + bar.get_width() / 2, v + 1.5, fmt % v,
                ha="center", va="bottom", fontsize=8)


def fig_protocols():
    """六个评价口径 × 七个版本的小多图。"""
    panels = [
        ("同集（data_2）", SAME),
        ("留一 16 段", LOO),
        ("跨日 2026-10-25", BLIND),
        ("三天标准段", THREE),
        ("2026-11-17 标准段", D17),
        ("2026-11-17 不摆臂段", D17_NOSWING),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(13.2, 7.4))
    for ax, (title, data) in zip(axes.ravel(), panels):
        vals = [data.get(v) for v in VERSIONS]
        xs = np.arange(len(VERSIONS))
        bars = []
        for x, name, v in zip(xs, VERSIONS, vals):
            y = 0 if v is None else v
            bars.append(ax.bar(x, y, color=COLOR[name], width=0.72,
                               edgecolor="white", linewidth=0.6))
        for x, v in zip(xs, vals):
            if v is None:
                ax.text(x, 4, "—", ha="center", va="bottom", fontsize=9, color="#888888")
        bar_labels(ax, [b[0] for b in bars], vals)
        ax.set_xticks(xs)
        ax.set_xticklabels(VERSIONS, fontsize=9)
        ax.set_ylim(0, 108)
        ax.set_title(title, fontsize=10)
        ax.set_ylabel("窗口级准确率 (%)", fontsize=8)
    fig.suptitle("图 A  v2–v7 在六个评价口径上的窗口级准确率（5 类 / 8 s 窗）", fontsize=13)
    fig.text(0.5, 0.01, "空白「—」= 该版本无此口径；v7 的 10-30～11-01 是训练集，不能当外部盲测。",
             ha="center", fontsize=8.5, color="#555555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(os.path.join(OUT, "fig_compare_protocols.png"))
    plt.close(fig)


def fig_crossday():
    """跨日三条线：10-25、三天标准段、11-17 标准段。"""
    xs = np.arange(len(VERSIONS))
    fig, ax = plt.subplots(figsize=(10.8, 5.8))
    series = [("2026-10-25（704 窗）", BLIND, "o", "#d62728"),
              ("2026-10-30～11-01 标准段（1662 窗）", THREE, "s", "#2ca02c"),
              ("2026-11-17 标准段（623 窗）", D17, "^", "#1f77b4")]
    for label, data, marker, color in series:
        ys = [data.get(v, np.nan) for v in VERSIONS]
        ax.plot(xs, ys, marker=marker, lw=1.6, ms=7, color=color, label=label)
    ax.set_xticks(xs)
    ax.set_xticklabels(VERSIONS)
    ax.set_ylim(30, 102)
    ax.set_ylabel("窗口级准确率 (%)")
    ax.legend(fontsize=9, loc="lower right")
    ax.annotate("v5.1 换 rob_skew\n79.7 → 94.6", xy=(4, 94.6), xytext=(2.2, 84),
                fontsize=9, color="#2ca02c",
                arrowprops=dict(arrowstyle="->", color="#2ca02c", lw=1.0))
    ax.set_title("图 B  跨日盲测：换一天后的窗口级准确率", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_compare_crossday.png"))
    plt.close(fig)


def fig_overview():
    """v1–v7：同一天 vs 换一天。v1 是 4 类 / 4 s 窗，单独标注。"""
    names = ["v1"] + VERSIONS
    xs = np.arange(len(names))
    same = [97.5, 97.4, 91.1, 97.4, 98.0, 98.0, 98.0, 94.2]
    cross = [np.nan, 42.8, 45.3, 68.6, 79.7, 94.6, 94.5, 92.8]
    fig, ax = plt.subplots(figsize=(11.2, 5.8))
    ax.plot(xs[1:], same[1:], "o-", color="#1f77b4", lw=1.6, ms=7, label="同一天 / 同集（v2–v7）")
    ax.scatter(xs[0], same[0], marker="D", s=90, color="#1f77b4", zorder=6,
               label="v1（4 类 / 4 s 窗，仅同集）")
    ax.plot(xs[1:], cross[1:], "s--", color="#d62728", lw=1.6, ms=7, label="换一天（跨日）")
    for x, y in zip(xs, same):
        ax.annotate("%.1f" % y, (x, y), textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=8, color="#1f77b4")
    for x, y in zip(xs, cross):
        if not np.isnan(y):
            ax.annotate("%.1f" % y, (x, y), textcoords="offset points", xytext=(0, -14),
                        ha="center", fontsize=8, color="#d62728")
    ax.scatter([0], [97.5], s=140, facecolors="none", edgecolors="#555555", lw=1.4, zorder=5)
    ax.annotate("v1：4 类 / 4 s 窗，\n不可与 5 类直接横比", xy=(0, 97.5), xytext=(0.5, 78),
                fontsize=9, color="#555555",
                arrowprops=dict(arrowstyle="->", color="#555555", lw=1.0))
    ax.annotate("v7 同集点 = 折外 94.2 %", xy=(7, 94.2), xytext=(5.1, 84.5),
                fontsize=9, color="#1f77b4",
                arrowprops=dict(arrowstyle="->", color="#1f77b4", lw=1.0))
    ax.set_xticks(xs)
    ax.set_xticklabels(names)
    ax.set_ylim(35, 104)
    ax.set_ylabel("窗口级准确率 (%)")
    ax.legend(fontsize=9, loc="lower right")
    ax.set_title("图 C  v1–v7：同一天与换一天的窗口级准确率", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_compare_overview.png"))
    plt.close(fig)


def fig_v1_detail():
    """v1 的 4 类交付：逐记录准确率 + 全量混淆矩阵。"""
    rows = list(csv.DictReader(open(os.path.join(
        ROOT, "output", "v1", "features", "windows.csv"))))
    order = ["walk", "run", "stairs", "stand"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.6, 5.2),
                                   gridspec_kw={"width_ratios": [1.05, 1]})
    # windows.csv 的 record 字段是源记录名，按 4 份提交文件对应的源记录取
    pairs = [("walk-1", "walk", "01_walk_flat"), ("run", "run", "02_run"),
             ("go_downstairs-1", "stairs", "03_stairs"), ("stand", "stand", "04_static")]
    labels, accs, ann = [], [], []
    for rec, st, name in pairs:
        rs = [r for r in rows if r["record"] == rec]
        ok = sum(r["pred"] == st for r in rs)
        accs.append(100.0 * ok / len(rs))
        labels.append("%s\n%s" % (name, CN[st]))
        ann.append("%d/%d" % (ok, len(rs)))
    bars = ax1.bar(range(4), accs,
                   color=["#1f77b4", "#d62728", "#ff7f0e", "#2ca02c"])
    for b, a, t in zip(bars, accs, ann):
        ax1.text(b.get_x() + b.get_width() / 2, a + 1.5, "%.1f %%\n%s" % (a, t),
                 ha="center", va="bottom", fontsize=9)
    ax1.set_xticks(range(4))
    ax1.set_xticklabels(labels, fontsize=9)
    ax1.set_ylim(0, 118)
    ax1.set_ylabel("窗口级准确率 (%)")
    ax1.set_title("4 份提交 CSV：逐记录准确率", fontsize=11)

    M = np.zeros((4, 4), dtype=int)
    idx = {s: i for i, s in enumerate(order)}
    for r in rows:
        M[idx[r["state"]], idx[r["pred"]]] += 1
    ax2.imshow(M, cmap="Blues")
    for i in range(4):
        for j in range(4):
            ax2.text(j, i, str(M[i, j]), ha="center", va="center",
                     fontsize=10, color="white" if M[i, j] > M.max() * 0.55 else "#222222")
    ax2.set_xticks(range(4))
    ax2.set_xticklabels([CN[s] for s in order], fontsize=9)
    ax2.set_yticks(range(4))
    ax2.set_yticklabels([CN[s] for s in order], fontsize=9)
    ax2.set_xlabel("判决")
    ax2.set_ylabel("真值")
    ax2.set_title("data_1 全量 11 段：混淆矩阵（1049/1058 = 99.15 %）", fontsize=11)
    ax2.grid(False)
    fig.suptitle("图 D  v1 的 4 类交付", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_compare_v1.png"))
    plt.close(fig)


def fig_v7():
    """v6 规则 vs v7 在三个外部集上的对照。"""
    groups = ["2026-10-25\n（704 窗）", "2026-11-17 标准段\n（623 窗）", "2026-11-17 不摆臂段\n（455 窗）"]
    v6 = [94.5, 87.8, 37.1]
    v7 = [92.8, 94.5, 94.5]
    x = np.arange(3)
    fig, ax = plt.subplots(figsize=(9.6, 5.4))
    b1 = ax.bar(x - 0.19, v6, width=0.36, color="#d62728", label="v6 规则")
    b2 = ax.bar(x + 0.19, v7, width=0.36, color="#ff7f0e", label="v7 RBF-SVM")
    for bars, vals in ((b1, v6), (b2, v7)):
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 1.5, "%.1f" % v,
                    ha="center", va="bottom", fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels(groups, fontsize=9)
    ax.set_ylim(0, 108)
    ax.set_ylabel("窗口级准确率 (%)")
    ax.legend(fontsize=9, loc="lower left")
    ax.set_title("图 F  外部盲测：v6 规则 vs v7（记录级均全对）", fontsize=13)
    ax.text(0.98, 0.95, "v7 训练集内部：折外 94.2 %、留一天 94.0 %\n（不与外部数字混读）",
            transform=ax.transAxes, ha="right", va="top", fontsize=8.5,
            bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="#bbbbbb"))
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_compare_v7.png"))
    plt.close(fig)


STATE5 = ["stand", "walk", "run", "up", "down"]
CN5 = {"stand": "静止", "walk": "平地慢走", "run": "快跑", "up": "上楼", "down": "下楼"}


def _recall(path, cols, drop_noswing=False):
    rows = list(csv.DictReader(open(os.path.join(ROOT, path))))
    if drop_noswing:
        rows = [r for r in rows if "noswing" not in r["record"]]
    out = np.full((len(cols), len(STATE5)), np.nan)
    for i, col in enumerate(cols):
        for j, s in enumerate(STATE5):
            rs = [r for r in rows if r["state"] == s]
            if rs:
                out[i, j] = 100.0 * sum(r[col] == s for r in rs) / len(rs)
    return out


def fig_recall_heatmap():
    """每个版本的逐类召回；两张热图分别是 10-25 与 11-17 标准段。"""
    six = ["pred_v2", "pred_v3", "pred_v4", "pred_v5", "pred_v51", "pred_v6"]
    labels = ["v2", "v3", "v4", "v5", "v5.1", "v6", "v7"]
    m1 = np.vstack([_recall("output/reports/blind_2026-10-25/windows.csv", six),
                    _recall("output/svm/blind_2026-10-25/windows.csv", ["pred"])])
    m2 = np.vstack([_recall("output/reports/blind_2026-11-17/windows.csv", six, True),
                    _recall("output/svm/blind_2026-11-17/windows.csv", ["pred"], True)])
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.0))
    for ax, M, title in ((axes[0], m1, "2026-10-25（704 窗 / 9 段）"),
                         (axes[1], m2, "2026-11-17 标准段（623 窗 / 8 段）")):
        ax.imshow(M, cmap="RdYlGn", vmin=0, vmax=100, aspect="auto")
        for i in range(M.shape[0]):
            for j in range(M.shape[1]):
                ax.text(j, i, "%.0f" % M[i, j], ha="center", va="center", fontsize=9,
                        color="white" if M[i, j] > 90 or M[i, j] < 35 else "#222222")
        ax.set_xticks(range(5))
        ax.set_xticklabels([CN5[s] for s in STATE5], fontsize=9)
        ax.set_yticks(range(7))
        ax.set_yticklabels(labels, fontsize=9)
        ax.set_title(title, fontsize=11)
        ax.grid(False)
    fig.suptitle("图 E  各版本逐类召回：v6 的短板在上楼 / 下楼，v7 在 11-17 拉回但静止样本少", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_compare_recall.png"))
    plt.close(fig)


def main():
    setup()
    fig_protocols()
    fig_crossday()
    fig_overview()
    fig_v1_detail()
    fig_recall_heatmap()
    fig_v7()
    print("written to", OUT)


if __name__ == "__main__":
    main()
