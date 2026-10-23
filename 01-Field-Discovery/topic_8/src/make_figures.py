#!/usr/bin/env python3
"""课题 08 —— 生成报告用的可视化图。

输出：output/figures/fig1..fig7 *.png
用法：.venv/bin/python src/make_figures.py
"""
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager, rcParams
from matplotlib.patches import Patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gait_analysis import (  # noqa: E402
    DATA, RECORDS, ROOT, STATE_CN, T_RUN_SD, T_STAND_SD, T_STAIRS_RATIO,
    classify, clean, dominant_freq, read_phyphox, sample_rate, windows,
)

FIG = os.path.join(ROOT, "output", "figures")
COLOR = {"walk": "#1f77b4", "run": "#d62728", "stairs": "#ff7f0e", "stand": "#2ca02c"}
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


def load_clean(name):
    """返回 (原始数组, 清洗后数组, 清洗区间)。"""
    raw = read_phyphox(os.path.join(DATA, name, "Raw Data.csv"))
    i, j = clean(*raw)
    return raw, tuple(a[i:j] for a in raw), (i, j)


def fig1_raw_overview():
    """四类状态的原始 |a| 波形，标出被剔除的启停异常段。"""
    items = [("walk-1", "walk"), ("run", "run"), ("go_downstairs-1", "stairs"), ("stand", "stand")]
    fig, axes = plt.subplots(4, 1, figsize=(11, 10.5))
    for ax, (name, state) in zip(axes, items):
        t, ax_, ay_, az_, mag = read_phyphox(os.path.join(DATA, name, "Raw Data.csv"))
        i, j = clean(t, ax_, ay_, az_, mag)
        ax.plot(t, mag, lw=0.5, color=COLOR[state])
        ax.axvspan(t[0], t[i], color="#e41a1c", alpha=0.18, lw=0)
        ax.axvspan(t[j - 1], t[-1], color="#e41a1c", alpha=0.18, lw=0)
        ax.axhline(9.81, color="k", ls="--", lw=0.8, alpha=0.6)
        ax.set_ylabel("|a| (m/s²)")
        ax.set_title("%s —— %s（%.1f s，剔除首尾 %.2f s / %.2f s）"
                     % (STATE_CN[state], name, t[-1] - t[0], t[i] - t[0], t[-1] - t[j - 1]),
                     fontsize=10)
        ax.set_xlim(t[0], t[-1])
        if state == "stand":
            ax.axvspan(36, 41, color="#ff7f0e", alpha=0.12, lw=0)
            ax.annotate("录制中段拿起手机（真实运动，未剔除）", xy=(38.5, 15), xytext=(18, 21),
                        fontsize=8, color="#b35c00",
                        arrowprops=dict(arrowstyle="->", color="#b35c00", lw=0.8))
    axes[-1].set_xlabel("时间 t (s)   红底 = 开/关采集产生的异常段")
    fig.suptitle("图 1  四类步态的原始加速度模长波形与采集启停异常段", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig1_raw_overview.png"))
    plt.close(fig)


def show_window(t, span=10.0):
    """取清洗后信号中间一段 10 s 用于展示。"""
    t0 = t[0] + max(0.0, (t[-1] - t[0] - span) / 2)
    return (t >= t0) & (t <= t0 + span), t0


def fig2_axes_clean():
    """四类状态清洗后 10 s 的三轴波形（展示姿态与轴向差异）。"""
    items = [("walk-1", "walk"), ("run", "run"), ("go_downstairs-1", "stairs"), ("stand", "stand")]
    fig, axes = plt.subplots(2, 2, figsize=(12, 7.2))
    for ax, (name, state) in zip(axes.ravel(), items):
        _, (t, ax_, ay_, az_, mag), _ = load_clean(name)
        m, t0 = show_window(t)
        tt = t[m] - t0
        for sig, lab, c in ((ax_[m], "ax", "#1f77b4"), (ay_[m], "ay", "#ff7f0e"), (az_[m], "az", "#2ca02c")):
            ax.plot(tt, sig, lw=0.8, label=lab, color=c)
        ax.set_title("%s（%s）" % (STATE_CN[state], name), fontsize=10)
        ax.set_xlabel("相对时间 (s)")
        ax.set_ylabel("加速度 (m/s²)")
        ax.set_xlim(0, 10)
    handles = [plt.Line2D([], [], color=c, label=l) for l, c in
               (("ax", "#1f77b4"), ("ay", "#ff7f0e"), ("az", "#2ca02c"))]
    fig.legend(handles=handles, loc="lower center", ncol=3, fontsize=9, frameon=False)
    fig.suptitle("图 2  清洗后 10 s 三轴加速度波形（三个轴的贡献随握持姿态而变）", fontsize=13)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(os.path.join(FIG, "fig2_axes_clean.png"))
    plt.close(fig)


def collect_windows():
    """与 gait_analysis 完全一致的滑窗特征（保证图与表同源）。"""
    out = []
    for name, truth in RECORDS:
        _, (t, ax, ay, az, mag), _ = load_clean(name)
        for k, f in windows(t, ax, ay, az, mag):
            f["record"], f["state"], f["t0"] = name, truth, float(t[k])
            f["pred"] = classify(f)
            out.append(f)
    return out


def fig3_feature_scatter(rows):
    """二维特征平面：|a| 标准差 vs 竖向/横向标准差比。"""
    fig, ax = plt.subplots(figsize=(9.2, 6.6))
    for st in ("walk", "run", "stairs", "stand"):
        v = [r for r in rows if r["state"] == st]
        ax.scatter([r["ratio"] for r in v], [r["std_mag"] for r in v], s=16, alpha=0.7,
                   color=COLOR[st], label="%s（%d 窗）" % (STATE_CN[st], len(v)), edgecolors="none")
    ax.axhline(T_STAND_SD, color="k", ls="--", lw=1.2)
    ax.axhline(T_RUN_SD, color="k", ls="--", lw=1.2)
    ax.axvline(T_STAIRS_RATIO, color="k", ls="--", lw=1.2)
    ax.set_xlim(0.3, 5.6)
    ax.set_ylim(0.025, 40)
    ax.set_yscale("log")
    ax.set_xlabel("竖向/横向标准差比  r = σ_v / σ_h")
    ax.set_ylabel("|a| 标准差  σ  (m/s²)")
    ax.text(0.35, 0.13, "σ < 0.30\n→ 静止", fontsize=9.5, va="bottom")
    ax.text(0.36, 9.6, "r ≤ 1.50\n(且 0.3 ≤ σ ≤ 8)\n→ 平地慢走", fontsize=9.5, va="bottom")
    ax.text(2.35, 12.5, "σ > 8.0 或 峰值 > 40 m/s²\n→ 快跑", fontsize=9.5, va="bottom")
    ax.text(2.35, 0.6, "r > 1.50 → 上下楼梯", fontsize=9.5, va="bottom")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.09), ncol=4, fontsize=9, frameon=False)
    ax.set_title("图 3  4 s 滑窗特征平面与三级阈值（虚线：σ=0.30 / σ=8.0 / r=1.50）", fontsize=12)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(os.path.join(FIG, "fig3_feature_scatter.png"))
    plt.close(fig)


def fig4_distribution(rows):
    """四个关键特征的分布对比。"""
    states = ["walk", "run", "stairs", "stand"]
    specs = [("std_mag", "σ(|a|)  (m/s²)", "log", (T_STAND_SD, T_RUN_SD)),
             ("ratio", "σ_v / σ_h", "linear", (T_STAIRS_RATIO,)),
             ("peak", "峰值 |a| (m/s²)", "log", (40.0,)),
             ("f_dom", "主频 f (Hz)（不参与判决）", "linear", ())]
    fig, axes = plt.subplots(1, 4, figsize=(14.5, 4.6))
    for ax, (key, label, scale, ths) in zip(axes, specs):
        data = [[r[key] for r in rows if r["state"] == st] for st in states]
        bp = ax.boxplot(data, patch_artist=True, widths=0.55, showfliers=False,
                        medianprops=dict(color="k"))
        for patch, st in zip(bp["boxes"], states):
            patch.set_facecolor(COLOR[st])
            patch.set_alpha(0.55)
        ax.set_xticklabels([STATE_CN[s] for s in states], fontsize=8, rotation=15)
        ax.set_ylabel(label, fontsize=9)
        ax.set_yscale(scale)
        if scale == "log":
            ax.yaxis.set_major_formatter(matplotlib.ticker.ScalarFormatter())
            ax.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
        for th in ths:
            ax.axhline(th, color="r", ls="--", lw=1)
    fig.suptitle("图 4  四类步态的滑窗特征分布（红虚线为阈值）", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig4_distribution.png"))
    plt.close(fig)


def psd(mag, fs, seg_s=8.0):
    n = int(seg_s * fs)
    hann = np.hanning(n)
    acc = np.zeros(n // 2 + 1)
    cnt = 0
    step = n // 2
    for k in range(0, len(mag) - n + 1, step):
        x = mag[k:k + n]
        x = (x - x.mean()) * hann
        acc += np.abs(np.fft.rfft(x)) ** 2
        cnt += 1
    f = np.fft.rfftfreq(n, 1 / fs)
    return f, acc / max(cnt, 1)


def fig5_spectrum():
    """|a| 的功率谱：周期成分的位置与强弱。"""
    items = [("walk-1", "walk"), ("run", "run"), ("go_downstairs-1", "stairs"), ("stand", "stand")]
    fig, ax = plt.subplots(figsize=(9.8, 5.4))
    curves = []
    for name, state in items:
        _, (t, axx, ayy, azz, mag), _ = load_clean(name)
        fs = sample_rate(t)
        f, p = psd(mag, fs)
        m = (f >= 0.5) & (f <= 6)
        curves.append((f[m], p[m], state))
    top = max(float(c[1].max()) for c in curves)
    for f, p, state in curves:
        pn = p / top
        ax.semilogy(f, pn, color=COLOR[state], lw=1.4,
                    label="%s（峰 %.2f Hz）" % (STATE_CN[state], f[np.argmax(pn)]))
        ax.plot(f[np.argmax(pn)], pn.max(), "o", color=COLOR[state], ms=5)
    ax.set_xlabel("频率 (Hz)")
    ax.set_ylabel("功率谱（以四者最大值为 1，对数坐标）")
    ax.set_xlim(0.5, 6)
    ax.set_ylim(1e-4, 2)
    ax.legend(fontsize=8.5, loc="upper right")
    ax.set_title("图 5  |a| 功率谱（8 s 分段平均）：静止比行走低约 3 个数量级", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig5_spectrum.png"))
    plt.close(fig)


def fig6_timeline(rows):
    """整段记录上的逐窗判决时间线。"""
    names = [n for n, _ in RECORDS]
    fig, ax = plt.subplots(figsize=(11, 5.4))
    for yi, name in enumerate(names):
        v = [r for r in rows if r["record"] == name]
        for r in v:
            ax.barh(yi, 0.52, left=r["t0"], height=0.62, color=COLOR[r["pred"]], lw=0)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(["%-16s 真值:%s" % (n, STATE_CN[s]) for n, s in RECORDS], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("时间 t (s)")
    ax.set_xlim(0, 120)
    ax.legend(handles=[Patch(color=COLOR[k], label=STATE_CN[k]) for k in ("walk", "run", "stairs", "stand")],
              ncol=4, fontsize=9, loc="lower right")
    ax.set_title("图 6  逐窗判决时间线（每格 0.5 s；仅 stand 录制中段的手持扰动被判错）", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig6_timeline.png"))
    plt.close(fig)


def fig8_gravity_estimate():
    """0.5 s 均值向量轨迹：姿态不变时应停在 |g|=9.8 的圆上。"""
    items = [("data/stand", "静止（姿态不变）", "#2ca02c"),
             ("data/walk-1", "标定·慢走（手持）", "#1f77b4"),
             ("test_data/walk", "测试·慢走（他人/他机）", "#9467bd"),
             ("test_data/go_upstairs/2", "测试·上楼（裤兜）", "#8c564b")]
    fig, axes = plt.subplots(1, 4, figsize=(15, 4.0))
    for ax, (d, lab, c) in zip(axes, items):
        t, axx, ayy, azz, mag = read_phyphox(os.path.join(ROOT, d, "Raw Data.csv"))
        i, j = clean(t, axx, ayy, azz, mag)
        axx, ayy, azz = axx[i:j], ayy[i:j], azz[i:j]
        fs = sample_rate(t)
        n = int(0.5 * fs)
        k = np.ones(n) / n
        x = np.convolve(axx, k, "valid")
        y = np.convolve(ayy, k, "valid")
        z = np.convolve(azz, k, "valid")
        seg = slice(0, min(len(x), int(10 * fs)))
        ax.plot(x[seg], y[seg], lw=0.7, color=c)
        ax.plot(x[seg][0], y[seg][0], "o", color=c, ms=4)
        ax.axhline(0, color="k", lw=0.4)
        ax.axvline(0, color="k", lw=0.4)
        th = np.linspace(0, 2 * np.pi, 300)
        ax.plot(9.8 * np.cos(th), 9.8 * np.sin(th), "k--", lw=0.8, alpha=0.55)
        ax.set_aspect("equal")
        ax.set_title("%s\n|mean| = %.1f m/s²" % (lab, float(np.linalg.norm([x.mean(), y.mean(), z.mean()]))),
                     fontsize=9.5)
        ax.set_xlabel("0.5 s 均值的 ax")
        ax.tick_params(labelsize=8)
    axes[0].set_ylabel("0.5 s 均值的 ay")
    fig.suptitle("图 8  含 g 的加速度：姿态不变时均值应停在 |g|=9.8 的虚线圆上；手持时轨迹在漂移", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig8_gravity_estimate.png"))
    plt.close(fig)


def fig9_test_waveforms():
    """测试集：每段清洗后 |a| 的 10 s 波形 + 判决结果。"""
    import glob as _glob

    paths = sorted(_glob.glob(os.path.join(ROOT, "test_data", "**", "Raw Data.csv"),
                              recursive=True))
    fig, axes = plt.subplots(len(paths), 1, figsize=(11, 2.2 * len(paths)), squeeze=False)
    for ax, p in zip(axes.ravel(), paths):
        t, ax_, ay, az, mag = read_phyphox(p)
        i, j = clean(t, ax_, ay, az, mag)
        t, mag = t[i:j], mag[i:j]
        seg = (t >= t[0] + max(0.0, (t[-1] - t[0] - 10) / 2)) & \
              (t <= t[0] + max(0.0, (t[-1] - t[0] - 10) / 2) + 10)
        votes = {}
        for _, f in windows(t, ax_[i:j], ay[i:j], az[i:j], mag):
            votes[classify(f)] = votes.get(classify(f), 0) + 1
        major = max(votes, key=votes.get)
        ax.plot(t[seg] - t[0], mag[seg], lw=0.8)
        ax.set_ylabel("|a| (m/s²)")
        ax.set_title("%s   σ=%.2f  峰值=%.1f  fs=%.0f Hz  → 判为 %s"
                     % (os.path.relpath(p, os.path.join(ROOT, "test_data")).replace("/Raw Data.csv", ""),
                        mag.std(), mag.max(), sample_rate(t), STATE_CN[major]), fontsize=10)
    axes.ravel()[-1].set_xlabel("相对时间 (s)")
    fig.suptitle("图 9  测试集：清洗后 |a| 波形（各取 10 s）", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig9_test_waveforms.png"))
    plt.close(fig)


def fig7_decision():
    """阈值判决流程图。"""
    fig, ax = plt.subplots(figsize=(10.5, 7.0))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 10)
    ax.axis("off")

    def box(x, y, w, h, text, fc, fs=10.5):
        ax.add_patch(plt.Rectangle((x - w / 2, y - h / 2), w, h, facecolor=fc,
                                   edgecolor="#444", lw=1.2, zorder=2))
        ax.text(x, y, text, ha="center", va="center", fontsize=fs, zorder=3)

    def arrow(p1, p2, label):
        ax.annotate("", xy=p2, xytext=p1,
                    arrowprops=dict(arrowstyle="->", lw=1.3, color="#333"))
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        if abs(p1[0] - p2[0]) < 1e-9:
            ax.text(mx + 0.15, my, label, fontsize=9.5, color="#1f77b4", ha="left", va="center")
        else:
            ax.text(mx, my + 0.22, label, fontsize=9.5, color="#1f77b4", ha="center")

    box(3.2, 9.2, 4.8, 0.9, "输入：4 s 三轴加速度滑窗（步长 0.5 s）", "#e8e8e8")
    box(3.2, 7.5, 4.8, 0.9, "σ(|a|) < 0.30 m/s² ？", "#dbe9f6")
    box(9.0, 7.5, 2.8, 0.9, "静止", "#c8e6c9", 13)
    box(3.2, 5.7, 4.8, 0.9, "σ(|a|) > 8.0 ？（或峰值 > 40 m/s²）", "#fbdcdc")
    box(9.0, 5.7, 2.8, 0.9, "快跑", "#f8c9c9", 13)
    box(3.2, 3.9, 4.8, 0.9, "σ_v / σ_h > 1.50 ？", "#ffe6cc")
    box(1.6, 2.1, 2.7, 0.9, "上下楼梯", "#ffd7a8", 13)
    box(5.2, 2.1, 2.7, 0.9, "平地慢走", "#bcd7ea", 13)

    arrow((3.2, 8.75), (3.2, 7.95), "")
    arrow((5.6, 7.5), (7.6, 7.5), "是")
    arrow((3.2, 7.05), (3.2, 6.15), "否")
    arrow((5.6, 5.7), (7.6, 5.7), "是")
    arrow((3.2, 5.25), (3.2, 4.35), "否")
    arrow((2.5, 3.45), (1.6, 2.55), "是")
    arrow((4.0, 3.45), (5.2, 2.55), "否")

    ax.set_title("图 7  四级顺序判决的阈值规则（先判易分的静止/跑步，再用轴向能量比区分楼梯与平地）",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig7_decision_tree.png"))
    plt.close(fig)


def main():
    setup()
    fig1_raw_overview()
    fig2_axes_clean()
    rows = collect_windows()
    fig3_feature_scatter(rows)
    fig4_distribution(rows)
    fig5_spectrum()
    fig6_timeline(rows)
    fig7_decision()
    fig8_gravity_estimate()
    fig9_test_waveforms()
    print("figures written to", FIG)


if __name__ == "__main__":
    main()
