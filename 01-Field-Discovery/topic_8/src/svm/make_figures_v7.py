#!/usr/bin/env python3
"""课题 08 v7 作图：学习模型分支与 v6 规则的对照。

输出：output/svm/figures/fig24_v7_methods.png
      output/svm/figures/fig25_v7_blind.png
      output/svm/figures/fig26_v7_confusion.png
用法：MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/svm/make_figures_v7.py

数据来自已落盘的结果：cv_windows.csv（段级分组折外）、
external_2026-10-25_windows.csv（外部抽样检查）与
output/reports/blind_2026-10-25/windows.csv（v6 规则同一天），
所以画图不重算特征，图与报告的数字必然一致。
"""
import csv
import os
import sys
from collections import Counter, defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams
from matplotlib.colors import LinearSegmentedColormap

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "v6"))
from features import ROOT  # noqa: E402

OUT = os.path.join(ROOT, "output", "svm")
FIG = os.path.join(OUT, "figures")
CV_CSV = os.path.join(OUT, "cv_windows.csv")
EXT_CSV = os.path.join(OUT, "external_2026-10-25_windows.csv")
V6_CSV = os.path.join(ROOT, "output", "reports", "blind_2026-10-25", "windows.csv")
CJK = "/run/host/usr/share/fonts/google-droid-sans-fonts/DroidSansFallbackFull.ttf"

STATES = ("stand", "walk", "run", "up", "down")
CN = {"stand": "静止", "walk": "慢走", "run": "快跑", "up": "上楼", "down": "下楼"}
METHODS = [("pred_v6", "v6 规则", "#9e9e9e"),
           ("pred_lr", "LR", "#a6cee3"),
           ("pred_linsvc", "LinearSVC", "#1f78b4"),
           ("pred_rbf", "RBF-SVM", "#d62728"),
           ("pred_rf", "RF", "#33a02c")]
V7_RED = "#d62728"
V6_GRAY = "#9e9e9e"


def setup():
    if os.path.exists(CJK):
        font_manager.fontManager.addfont(CJK)
        rcParams["font.family"] = ["DejaVu Sans", "Droid Sans Fallback"]
    rcParams["axes.unicode_minus"] = False
    rcParams["figure.dpi"] = 130
    rcParams["savefig.dpi"] = 130
    rcParams["axes.grid"] = True
    rcParams["grid.alpha"] = 0.25
    rcParams["axes.axisbelow"] = True
    os.makedirs(FIG, exist_ok=True)


def load(path):
    rows = list(csv.DictReader(open(path)))
    for r in rows:
        for k in ("t0", "prob"):
            if k in r and r[k] != "":
                r[k] = float(r[k])
    return rows


def record_key(r):
    return (r.get("day", ""), r["record"])


def win_acc(rows, col):
    return 100.0 * sum(r[col] == r["state"] for r in rows) / len(rows)


def rec_level(rows, col):
    groups = defaultdict(list)
    for r in rows:
        groups[record_key(r)].append(r)
    ok = sum(Counter(r[col] for r in rs).most_common(1)[0][0] == rs[0]["state"]
             for rs in groups.values())
    return ok, len(groups)


def short_label(day, record):
    return "%s %s" % (day[5:], record.replace("go_", "").replace("-noswing", "-ns"))


def join_v6(ext, v6):
    """外部窗口与 v6 规则逐窗判决按（记录, t0）对齐。"""
    by_key = {(r["record"], round(float(r["t0"]), 3)): r["pred_v6"] for r in v6}
    out = []
    for r in ext:
        out.append(dict(r, pred_v6=by_key[(r["record"], round(float(r["t0"]), 3))]))
    return out


def fig_methods(cv):
    std = [r for r in cv if "noswing" not in r["record"]]
    ns = [r for r in cv if "noswing" in r["record"]]
    groups = [("全部 2785 窗", cv), ("标准段 1662 窗", std), ("不摆臂段 1123 窗", ns)]

    fig = plt.figure(figsize=(13.8, 6.2))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.0, 1.25], wspace=0.42)

    # (a) 折外：五方法 × 三种段类型
    ax = fig.add_subplot(gs[0, 0])
    width = 0.15
    for k, (col, label, color) in enumerate(METHODS):
        xs = [i + (k - 2) * width for i in range(len(groups))]
        vals = [win_acc(sub, col) for _, sub in groups]
        bars = ax.bar(xs, vals, width=width, label=label, color=color,
                      edgecolor="white", linewidth=0.4)
        for bar, v in zip(bars, vals):
            ax.annotate("%.0f" % v, (bar.get_x() + bar.get_width() / 2, v),
                        ha="center", va="bottom", fontsize=6.5, rotation=90)
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([g for g, _ in groups], fontsize=9)
    ax.set_ylim(0, 132)
    ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.set_ylabel("窗口级准确率（%）")
    ax.set_title("（a）段级分组 5 折折外：学习模型救的是不摆臂段", fontsize=11)
    ax.legend(fontsize=7.5, ncol=3, loc="upper center", framealpha=0.95)

    # (b) 不摆臂 13 段逐段：v6 规则 vs RBF-SVM
    ax = fig.add_subplot(gs[0, 1])
    groups = defaultdict(list)
    for r in ns:
        groups[record_key(r)].append(r)
    keys = sorted(groups)
    ys = list(range(len(keys)))[::-1]
    h = 0.38
    v6v = [win_acc(groups[k], "pred_v6") for k in keys]
    v7v = [win_acc(groups[k], "pred_rbf") for k in keys]
    ax.barh([y + h / 2 for y in ys], v6v, height=h, color=V6_GRAY,
            label="v6 规则（平均 %.1f %%）" % win_acc(ns, "pred_v6"))
    ax.barh([y - h / 2 for y in ys], v7v, height=h, color=V7_RED,
            label="RBF-SVM 折外（平均 %.1f %%）" % win_acc(ns, "pred_rbf"))
    for y, a, b in zip(ys, v6v, v7v):
        if a >= 1:
            ax.annotate("%.0f" % a, (a, y + h / 2), xytext=(2, 0),
                        textcoords="offset points", va="center", ha="left",
                        fontsize=6.5, color="#555555")
        if b >= 1:
            ax.annotate("%.0f" % b, (b, y - h / 2), xytext=(2, 0),
                        textcoords="offset points", va="center", ha="left",
                        fontsize=6.5, color=V7_RED)
    ax.set_yticks(ys)
    ax.set_yticklabels([short_label(*k) for k in keys], fontsize=8)
    ax.yaxis.tick_right()
    ax.set_xlim(0, 118)
    ax.set_xlabel("窗口级准确率（%）")
    ax.set_title("（b）不摆臂段逐段：固定门限失效 vs 学习模型", fontsize=11, pad=26)
    ax.legend(fontsize=8, ncol=2, loc="lower center", bbox_to_anchor=(0.5, 1.0),
              framealpha=0.95)

    fig.savefig(os.path.join(FIG, "fig24_v7_methods.png"), bbox_inches="tight")
    plt.close(fig)


def fig_blind(joined):
    """外部 2026-10-25：逐段 v6 规则 vs v7。"""
    groups = defaultdict(list)
    for r in joined:
        groups[r["record"]].append(r)
    keys = sorted(groups, key=lambda k: (STATES.index(groups[k][0]["state"]), k))
    ys = list(range(len(keys)))[::-1]
    h = 0.38

    fig, ax = plt.subplots(figsize=(9.6, 5.4))
    v6v = [win_acc(groups[k], "pred_v6") for k in keys]
    v7v = [win_acc(groups[k], "pred") for k in keys]
    ax.barh([y + h / 2 for y in ys], v6v, height=h, color=V6_GRAY,
            label="v6 规则（94.5 %%，记录级 %d/%d）" % rec_level(joined, "pred_v6"))
    ax.barh([y - h / 2 for y in ys], v7v, height=h, color=V7_RED,
            label="RBF-SVM v7（92.8 %%，记录级 %d/%d）" % rec_level(joined, "pred"))
    for y, a, b in zip(ys, v6v, v7v):
        ax.annotate("%.0f" % a, (a, y + h / 2), va="center", ha="left",
                    fontsize=7, color="#555555")
        ax.annotate("%.0f" % b, (b, y - h / 2), va="center", ha="left",
                    fontsize=7, color=V7_RED)
    labels = ["%s（%s，%d 窗）" % (k, CN[groups[k][0]["state"]], len(groups[k]))
              for k in keys]
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=8.5)
    ax.set_xlim(0, 118)
    ax.set_xlabel("窗口级准确率（%）")
    ax.set_title("外部抽样检查 2026-10-25（704 窗 / 9 段，未参与训练）", fontsize=11, pad=26)
    ax.legend(fontsize=8, ncol=2, loc="lower center", bbox_to_anchor=(0.5, 1.0),
              framealpha=0.95)
    fig.savefig(os.path.join(FIG, "fig25_v7_blind.png"), bbox_inches="tight")
    plt.close(fig)


def fig_confusion(joined):
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.6))
    cmap = LinearSegmentedColormap.from_list("bw", ["#ffffff", "#0b559f"])
    panels = [("v6 规则", "pred_v6"), ("RBF-SVM v7", "pred")]
    im = None
    for ax, (title, col) in zip(axes, panels):
        rows = [(r["state"], r[col]) for r in joined]
        M = [[sum(1 for t, q in rows if t == a and q == b) for b in STATES]
             for a in STATES]
        acc = 100.0 * sum(1 for t, q in rows if t == q) / len(rows)
        norm = [[100.0 * c / sum(row) if sum(row) else 0 for c in row] for row in M]
        im = ax.imshow(norm, cmap=cmap, vmin=0, vmax=100)
        for i in range(len(STATES)):
            for j in range(len(STATES)):
                ax.text(j, i, M[i][j], ha="center", va="center", fontsize=9,
                        color="white" if norm[i][j] > 55 else "#222222",
                        fontweight="bold" if i == j else "normal")
        ax.set_xticks(range(5))
        ax.set_yticks(range(5))
        ax.set_xticklabels([CN[s] for s in STATES], fontsize=9)
        ax.set_yticklabels([CN[s] for s in STATES], fontsize=9)
        ax.set_xlabel("判决")
        ax.set_ylabel("真值")
        ax.set_title("%s（窗口级 %.1f %%）" % (title, acc), fontsize=11)
        ax.grid(False)
    fig.colorbar(im, ax=axes, fraction=0.035, pad=0.02, label="行内占比（%）")
    fig.suptitle("外部 2026-10-25 混淆矩阵：v6 与 v7 的错法不同", fontsize=12)
    fig.savefig(os.path.join(FIG, "fig26_v7_confusion.png"), bbox_inches="tight")
    plt.close(fig)


def main():
    setup()
    cv = load(CV_CSV)
    joined = join_v6(load(EXT_CSV), load(V6_CSV))
    fig_methods(cv)
    fig_blind(joined)
    fig_confusion(joined)
    print("输出：%s" % FIG)


if __name__ == "__main__":
    main()
