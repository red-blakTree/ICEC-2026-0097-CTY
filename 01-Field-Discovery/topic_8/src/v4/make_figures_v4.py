#!/usr/bin/env python3
"""课题 08 v4 —— 波形检测版的可视化。

输出：output/v4/figures/fig13_steps.png、fig14_acp.png、fig15_blind.png、fig16_v4_blind.png、fig17_compare.png
用法：MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/v4/make_figures_v4.py
"""
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
sys.path.insert(0, os.path.join(SRC, "v3"))
sys.path.insert(0, HERE)

import gait_analysis_v2 as v2  # noqa: E402
import gait_analysis_v3 as v3  # noqa: E402
import gait_analysis_v4 as v4  # noqa: E402

ROOT = v2.ROOT
FIG = os.path.join(ROOT, "output", "v4", "figures")
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


def fig13_steps():
    items = [("data/calib/data_2", "walk-1", "平地慢走"),
             ("data/calib/data_2", "go_upstairs", "上楼"),
             ("data/calib/data_2", "run-2", "快跑")]
    fig, axes = plt.subplots(3, 1, figsize=(11, 8.8))
    for ax, (root, name, label) in zip(axes, items):
        t, ax_, ay, az, gx, gy, gz = v2.load_record(os.path.join(ROOT, root, name))
        dyn = np.sqrt((ax_ - gx) ** 2 + (ay - gy) ** 2 + (az - gz) ** 2)
        i, j = v2.clean(t, dyn)
        fs = v2.sample_rate(t[i:j])
        w = int(8 * fs)
        k = max(0, (j - i - w) // 2)
        sl = slice(i + k, i + k + w)
        t, ax_, ay, az, gx, gy, gz = (t[sl], ax_[sl], ay[sl], az[sl], gx[sl], gy[sl], gz[sl])
        gn = np.sqrt(gx * gx + gy * gy + gz * gz)
        a_v = ax_ * gx / gn + ay * gy / gn + az * gz / gn - gn
        s = v4.moving_average(a_v, 0.08 * fs)
        p = v4.detect_peaks(s, fs)
        tr = v4.detect_peaks(-s, fs)
        f = v4.waveform_features(t, ax_, ay, az, gx, gy, gz)
        tt = t - t[0]
        ax.plot(tt, s, lw=1.0, color="#444")
        ax.plot(tt[p], s[p], "o", color="#d62728", ms=5, label="峰（%d）" % len(p))
        ax.plot(tt[tr], s[tr], "o", color="#1f77b4", ms=5, label="谷（%d）" % len(tr))
        ax.set_ylabel("a_v (m/s²)")
        ax.set_title("%s（%s）：步数 %d，cadence %.2f Hz，i_cv %.2f，acp %.2f，score %.2f"
                     % (label, name, f["n_steps"], f["cadence"], f["i_cv"], f["acp"], f["score"]),
                     fontsize=10)
        ax.legend(fontsize=8, loc="upper right", ncol=2)
        ax.set_xlim(0, tt[-1])
    axes[-1].set_xlabel("时间 t (s)")
    fig.suptitle("图 13　v4 的波形检测：在竖向动态加速度上逐拍找峰/谷", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig13_steps.png"))
    plt.close(fig)


def fig14_acp():
    d2 = v4.collect(os.path.join(ROOT, "data", "calib", "data_2"))
    t2 = v4.collect(os.path.join(ROOT, "data", "blind", "2026-10-25"))
    th = v4.calibrate(d2 + v4.collect(os.path.join(ROOT, "data", "calib")))
    fig, ax = plt.subplots(figsize=(9.4, 5.4))
    for rows, marker, dy, label in ((d2, "o", -0.14, "data_2"), (t2, "^", 0.14, "2026-10-25")):
        for st in ORDER:
            v = [r for r in rows if r["state"] == st]
            if not v:
                continue
            ax.scatter([r["acp"] for r in v], np.full(len(v), ORDER.index(st) + dy), s=20,
                       marker=marker, alpha=0.5, color=COLOR[st], edgecolors="none",
                       label="%s·%s" % (label, v2.STATE_CN[st]))
    ax.axvline(th["acp"], color="k", ls="--", lw=1.2, label="acp = %.2f" % th["acp"])
    ax.set_yticks(range(len(ORDER)))
    ax.set_yticklabels([v2.STATE_CN[s] for s in ORDER])
    ax.set_xlabel("自相关峰 acp（步态规律性）")
    ax.set_xlim(0, 1.0)
    ax.legend(fontsize=7, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.16), frameon=False)
    ax.set_title("图 14　acp 阈值：本人数据上选 0.72，低于它判上楼", fontsize=12)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(os.path.join(FIG, "fig14_acp.png"))
    plt.close(fig)


def fig15_blind():
    d2_v2 = v2.collect(os.path.join(ROOT, "data", "calib", "data_2"), 8.0, 1.0)
    t2_v2 = v2.collect(os.path.join(ROOT, "data", "blind", "2026-10-25"), 8.0, 1.0)
    th2 = v2.calibrate(d2_v2)
    th3 = v3.calibrate(d2_v2)
    for r in t2_v2:
        r["p2"] = v2.classify(r, th2)
        r["p3"] = v3.classify(r, th3)
        r["pred"] = r["p3"]
        r["dataset"] = "test"
    v3.smooth(t2_v2)
    acc2 = sum(r["p2"] == r["state"] for r in t2_v2) / len(t2_v2)
    acc3 = sum(r["pred_smooth"] == r["state"] for r in t2_v2) / len(t2_v2)

    d2_v4 = v4.collect(os.path.join(ROOT, "data", "calib", "data_2"))
    t2_v4 = v4.collect(os.path.join(ROOT, "data", "blind", "2026-10-25"))
    th4 = v4.calibrate(d2_v4 + v4.collect(os.path.join(ROOT, "data", "calib")))
    for r in t2_v4:
        r["p4"] = v4.classify(r, th4)
        r["pred"] = r["p4"]
        r["dataset"] = "test"
    v4.smooth(t2_v4)

    names = sorted(set(r["record"] for r in t2_v4))
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.5, 5.2), gridspec_kw={"width_ratios": [1.1, 1]})
    y = np.arange(len(names))
    for key, label, color, off in (("p2", "v2（σ_v/p99）", "#9e9e9e", -0.24),
                                   ("pred_smooth", "v3 平滑（f_dom/r）", "#1f77b4", 0.0),
                                   ("p4", "v4（波形检测）", "#2ca02c", 0.24)):
        vals = []
        for name in names:
            v = [r for r in t2_v4 if r["record"] == name]
            if key == "p4":
                vals.append(sum(r["pred_smooth"] == r["state"] for r in v) / len(v))
            else:
                # v2/v3 的行是按同一记录名对齐的
                vv = [r for r in t2_v2 if r["record"] == name]
                vals.append(sum(r[key] == r["state"] for r in vv) / len(vv))
        a1.barh(y + off, vals, 0.22, color=color, label=label)
    a1.set_yticks(y)
    a1.set_yticklabels(names)
    a1.invert_yaxis()
    a1.set_xlim(0, 1.05)
    a1.set_xlabel("窗口级准确率")
    a1.legend(fontsize=8.5, loc="lower right")
    a1.set_title("① 跨日 2026-10-25：逐段", fontsize=10)

    present = [s for s in ORDER if any(r["state"] == s for r in t2_v4)]
    M = np.array([[sum(1 for r in t2_v4 if r["state"] == a and r["pred_smooth"] == b) for b in ORDER]
                  for a in present])
    im = a2.imshow(M, cmap="Greens", aspect="auto")
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            a2.text(j, i, M[i, j], ha="center", va="center",
                    color="white" if M[i, j] > M.max() * 0.6 else "black", fontsize=10)
    a2.set_xticks(range(len(ORDER)))
    a2.set_xticklabels([v2.STATE_CN[s] for s in ORDER], fontsize=9)
    a2.set_yticks(range(len(present)))
    a2.set_yticklabels([v2.STATE_CN[s] for s in present], fontsize=9)
    a2.set_xlabel("判决")
    a2.set_ylabel("真值")
    acc4 = sum(r["pred_smooth"] == r["state"] for r in t2_v4) / len(t2_v4)
    a2.set_title("② v4 混淆矩阵（盲测 %d/%d = %.1f %%）" % (sum(r["pred_smooth"] == r["state"] for r in t2_v4), len(t2_v4), 100 * acc4), fontsize=10)
    fig.colorbar(im, ax=a2, fraction=0.046)
    fig.suptitle("图 15　盲测：v2 %.1f %% → v3 %.1f %% → v4 %.1f %%" % (100 * acc2, 100 * acc3, 100 * acc4), fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig15_blind.png"))
    plt.close(fig)


def fig16_v4_blind():
    d2 = v4.collect(os.path.join(ROOT, "data", "calib", "data_2"))
    routine = v4.collect(os.path.join(ROOT, "data", "calib"))
    t2 = v4.collect(os.path.join(ROOT, "data", "blind", "2026-10-25"))
    th = v4.calibrate(d2 + routine)
    for r in t2:
        r["pred"] = v4.classify(r, th)
        r["dataset"] = "test"
    v4.smooth(t2)

    names = sorted(set(r["record"] for r in t2))
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5.2))
    y = np.arange(len(names))
    vals = []
    for name in names:
        v = [r for r in t2 if r["record"] == name]
        vals.append(sum(r["pred_smooth"] == r["state"] for r in v) / len(v))
    colors = [COLOR[[r for r in t2 if r["record"] == n][0]["state"]] for n in names]
    a1.barh(y, vals, 0.55, color=colors)
    for i, val in enumerate(vals):
        a1.text(min(val + 0.01, 0.98), i, "%.1f %%" % (100 * val), va="center", fontsize=9)
    a1.set_yticks(y)
    a1.set_yticklabels(names)
    a1.invert_yaxis()
    a1.set_xlim(0, 1.1)
    a1.set_xlabel("窗口级准确率（平滑后）")
    a1.set_title("① 逐段准确率", fontsize=10)

    present = [s for s in ORDER if any(r["state"] == s for r in t2)]
    M = np.array([[sum(1 for r in t2 if r["state"] == a and r["pred_smooth"] == b) for b in ORDER]
                  for a in present])
    im = a2.imshow(M, cmap="Greens", aspect="auto")
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            a2.text(j, i, M[i, j], ha="center", va="center",
                    color="white" if M[i, j] > M.max() * 0.6 else "black", fontsize=10)
    a2.set_xticks(range(len(ORDER)))
    a2.set_xticklabels([v2.STATE_CN[s] for s in ORDER], fontsize=9)
    a2.set_yticks(range(len(present)))
    a2.set_yticklabels([v2.STATE_CN[s] for s in present], fontsize=9)
    a2.set_xlabel("判决")
    a2.set_ylabel("真值")
    a2.set_title("② v4 混淆矩阵", fontsize=10)
    fig.colorbar(im, ax=a2, fraction=0.046)

    hit = sum(r["pred_smooth"] == r["state"] for r in t2)
    recs = sorted(set(r["record"] for r in t2))
    ok = 0
    for name in recs:
        v = [r for r in t2 if r["record"] == name]
        votes = {}
        for r in v:
            votes[r["pred_smooth"]] = votes.get(r["pred_smooth"], 0) + 1
        ok += max(votes, key=votes.get) == v[0]["state"]
    fig.suptitle("图 16　v4 在跨日盲测 2026-10-25 上：%d/%d = %.1f %%，记录级 %d/%d"
                 % (hit, len(t2), 100 * hit / len(t2), ok, len(recs)), fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig16_v4_blind.png"))
    plt.close(fig)


def fig17_compare():
    """v2 / v3 / v4 对比；数值与 output/{v2,v3,v4}/features/report.txt 一致（硬编码，重跑分析后需同步）。"""
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(17, 5.2),
                                     gridspec_kw={"width_ratios": [1.15, 1.15, 0.9]})
    w = 0.25
    x = np.arange(3)
    series = [
        ("v2（σ_v/p99）", [97.4, 73.9, 42.8], "#9e9e9e"),
        ("v3 平滑（f_dom/r）", [91.1, 82.2, 45.3], "#1f77b4"),
        ("v4（波形）", [97.4, 98.9, 68.6], "#2ca02c"),
    ]
    for i, (label, vals, color) in enumerate(series):
        bars = a1.bar(x + (i - 1) * w, vals, w, label=label, color=color)
        if i == 2:
            bars[1].set_hatch("//")
            bars[1].set_edgecolor("white")
        for b, v in zip(bars, vals):
            a1.text(b.get_x() + b.get_width() / 2, v + 1.5, "%.1f" % v, ha="center", fontsize=8)
    a1.set_xticks(x)
    a1.set_xticklabels(["data_2\n同集", "2026-10-24\n同日跨时段", "2026-10-25\n跨日盲测"], fontsize=9)
    a1.set_ylim(0, 108)
    a1.set_ylabel("窗口级准确率 (%)")
    a1.set_title("① 三个数据集（v4·routine 为 in-sample）", fontsize=10)
    a1.legend(fontsize=8, loc="lower left")

    labels = ["慢走", "快跑", "上楼", "下楼"]
    x = np.arange(4)
    series = [
        ("v2", [30.1, 100, 0.0, 83.3], "#9e9e9e"),
        ("v3", [0.3, 100, 70.4, 75.3], "#1f77b4"),
        ("v4", [56.1, 100, 49.7, 96.3], "#2ca02c"),
    ]
    for i, (label, vals, color) in enumerate(series):
        bars = a2.bar(x + (i - 1) * w, vals, w, label=label, color=color)
        for b, v in zip(bars, vals):
            a2.text(b.get_x() + b.get_width() / 2, v + 1.5, "%.0f" % v, ha="center", fontsize=8)
    a2.set_xticks(x)
    a2.set_xticklabels(labels, fontsize=9)
    a2.set_ylim(0, 108)
    a2.set_ylabel("窗口级准确率 (%)")
    a2.set_title("② 跨日盲测：逐类", fontsize=10)
    a2.legend(fontsize=8, loc="lower left")

    x = np.arange(3)
    vals = [5 / 9, 7 / 9, 8 / 9]
    bars = a3.bar(x, vals, 0.55, color=["#9e9e9e", "#1f77b4", "#2ca02c"])
    for b, v in zip(bars, vals):
        a3.text(b.get_x() + b.get_width() / 2, v + 0.02, "%d/9" % round(v * 9), ha="center", fontsize=11)
    a3.set_xticks(x)
    a3.set_xticklabels(["v2", "v3", "v4"], fontsize=10)
    a3.set_ylim(0, 1.15)
    a3.set_ylabel("记录级准确率")
    a3.set_title("③ 跨日盲测：记录级", fontsize=10)

    fig.suptitle("图 17　v2 / v3 / v4 对比：同集、同日跨时段、跨日盲测", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig17_compare.png"))
    plt.close(fig)


def main():
    setup()
    fig13_steps()
    fig14_acp()
    fig15_blind()
    fig16_v4_blind()
    fig17_compare()
    print("figures written to", FIG)


if __name__ == "__main__":
    main()
