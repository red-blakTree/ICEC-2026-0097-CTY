#!/usr/bin/env python3
"""课题 08 v2 —— 生成报告用图（output/v2/figures/fig1..fig8.png）。

用法：MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/v2/make_figures_v2.py
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
from gait_analysis_v2 import (  # noqa: E402
    ROOT, STATE_CN, calibrate, classify, clean, collect,
    load_record, sample_rate,
)

FIG = os.path.join(ROOT, "output", "v2", "figures")
DATA = os.path.join(ROOT, "data", "calib", "data_2")
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


def load_clean(name):
    t, ax, ay, az, gx, gy, gz = load_record(os.path.join(DATA, name))
    dyn = np.sqrt((ax - gx) ** 2 + (ay - gy) ** 2 + (az - gz) ** 2)
    i, j = clean(t, dyn)
    sl = slice(i, j)
    return (t, ax, ay, az, gx, gy, gz, dyn), (i, j), sl


def show_window(t, span=10.0):
    t0 = t[0] + max(0.0, (t[-1] - t[0] - span) / 2)
    return (t >= t0) & (t <= t0 + span), t0


def fig1_waveforms():
    items = [("stand", "stand"), ("walk-1", "walk"), ("run-2", "run"),
             ("go_upstairs", "up"), ("go_downstairs", "down")]
    fig, axes = plt.subplots(5, 1, figsize=(11, 11))
    for ax, (name, state) in zip(axes, items):
        (t, _, _, _, _, _, _, dyn), (i, j), _ = load_clean(name)
        ax.plot(t, dyn, lw=0.45, color=COLOR[state])
        ax.axvspan(t[0], t[i], color="#e41a1c", alpha=0.16, lw=0)
        ax.axvspan(t[j - 1], t[-1], color="#e41a1c", alpha=0.16, lw=0)
        ax.set_ylabel("|a-g| (m/s²)")
        ax.set_title("%s —— %s（%.1f s，剔除首尾 %.2f / %.2f s）"
                     % (STATE_CN[state], name, t[-1] - t[0], t[i] - t[0], t[-1] - t[j - 1]),
                     fontsize=10)
        ax.set_xlim(t[0], t[-1])
    axes[-1].set_xlabel("时间 t (s)　红底 = 清洗剔除的启停异常段")
    fig.suptitle("图 1　五类步态的纯动态加速度 |a-g| 波形（重力已扣掉，静止基线为 0）", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig1_waveforms.png"))
    plt.close(fig)


def fig2_decompose():
    (t, ax, ay, az, gx, gy, gz, _), _, _ = load_clean("walk-1")
    m, t0 = show_window(t)
    tt = t[m] - t0
    gn = np.sqrt(gx * gx + gy * gy + gz * gz)
    a_v = ax * gx / gn + ay * gy / gn + az * gz / gn - gn
    a_h = np.sqrt(np.maximum((ax - gx) ** 2 + (ay - gy) ** 2 + (az - gz) ** 2 - a_v ** 2, 0))

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 7.4), sharex=True)
    for sig, lab, c in ((ax[m], "ax", "#1f77b4"), (ay[m], "ay", "#ff7f0e"), (az[m], "az", "#2ca02c")):
        a1.plot(tt, sig, lw=0.9, label=lab, color=c)
    a1.set_ylabel("原始加速度 (m/s²)")
    a1.legend(ncol=3, fontsize=9, loc="upper right")
    a1.set_title("手机坐标系下的三轴：随握持姿态整体旋转，不能直接当特征", fontsize=10)

    a2.plot(tt, a_v[m], lw=1.0, color="#d62728", label="竖向动态 a_v")
    a2.plot(tt, a_h[m], lw=1.0, color="#1f77b4", label="横向动态 a_h")
    a2.axhline(0, color="k", lw=0.5)
    a2.set_ylabel("重力投影后的分量 (m/s²)")
    a2.set_xlabel("相对时间 (s)")
    a2.legend(ncol=2, fontsize=9, loc="upper right")
    a2.set_title("用 Gravity 传感器逐样本投影：与手机怎么拿无关", fontsize=10)
    fig.suptitle("图 2　姿态解耦（walk-1 取 10 s）", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig2_decompose.png"))
    plt.close(fig)


def collect_rows():
    rows = collect(DATA, 8.0, 1.0)
    th = calibrate(rows)
    for r in rows:
        r["pred"] = classify(r, th)
    return rows, th


def fig3_feature_plane(rows, th):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.5, 5.8))
    for st in ORDER:
        v = [r for r in rows if r["state"] == st]
        a1.scatter([r["std_mag"] for r in v], [r["peak"] for r in v], s=16, alpha=0.7,
                   color=COLOR[st], label="%s（%d 窗）" % (STATE_CN[st], len(v)), edgecolors="none")
        a2.scatter([r["std_v"] for r in v], [r["p99"] for r in v], s=16, alpha=0.7,
                   color=COLOR[st], edgecolors="none")
    a1.axvline(th["stand"], color="k", ls="--", lw=1.1)
    a1.axvline(th["run_sd"], color="k", ls="--", lw=1.1)
    a1.axhline(th["run_peak"], color="k", ls="--", lw=1.1)
    a1.set_xscale("log")
    a1.set_yscale("log")
    a1.set_xlabel("σ(|a-g|)  (m/s²)")
    a1.set_ylabel("峰值 |a-g|  (m/s²)")
    a1.set_title("① 静止 / 快跑：强度判据\nσ<%.2f→静止；σ>%.2f 或 峰值>%.1f→快跑"
                 % (th["stand"], th["run_sd"], th["run_peak"]), fontsize=10)
    a1.legend(fontsize=8, loc="lower right", frameon=False)

    a2.axvline(th["down_sv"], color="k", ls="--", lw=1.1)
    a2.axhline(th["up_p99"], color="k", ls="--", lw=1.1)
    a2.set_xlabel("竖向动态标准差 σ_v  (m/s²)")
    a2.set_ylabel("99 分位冲击幅值 p99  (m/s²)")
    a2.set_title("② 上楼 / 慢走 / 下楼：方向与冲击判据\nσ_v>%.2f→下楼；p99<%.2f→上楼"
                 % (th["down_sv"], th["up_p99"]), fontsize=10)
    a2.set_xlim(1.0, 6.8)
    a2.set_ylim(7, 19)
    fig.suptitle("图 3　8 s 滑窗特征平面与阈值（虚线）", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig3_feature_plane.png"))
    plt.close(fig)


def fig4_distribution(rows, th):
    specs = [("std_mag", "σ(|a-g|)  (m/s²)", "log", (th["stand"],)),
             ("std_v", "σ_v  (m/s²)", "linear", (th["down_sv"],)),
             ("p99", "p99 |a-g|  (m/s²)", "linear", (th["up_p99"],)),
             ("peak", "峰值 |a-g|  (m/s²)", "log", (th["run_peak"],))]
    fig, axes = plt.subplots(1, 4, figsize=(15, 4.8))
    for ax, (key, label, scale, ths) in zip(axes, specs):
        data = [[r[key] for r in rows if r["state"] == st] for st in ORDER]
        bp = ax.boxplot(data, patch_artist=True, widths=0.6, showfliers=False,
                        medianprops=dict(color="k"))
        for patch, st in zip(bp["boxes"], ORDER):
            patch.set_facecolor(COLOR[st])
            patch.set_alpha(0.6)
        ax.set_xticklabels([STATE_CN[s] for s in ORDER], fontsize=8, rotation=20)
        ax.set_ylabel(label, fontsize=9)
        ax.set_yscale(scale)
        if scale == "log":
            ax.yaxis.set_major_formatter(matplotlib.ticker.ScalarFormatter())
            ax.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
        for t in ths:
            ax.axhline(t, color="r", ls="--", lw=1)
    fig.suptitle("图 4　五类步态的滑窗特征分布（红虚线为对应阈值）", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig4_distribution.png"))
    plt.close(fig)


def psd(x, fs, seg_s=8.0):
    n = int(seg_s * fs)
    hann = np.hanning(n)
    acc = np.zeros(n // 2 + 1)
    cnt = 0
    for k in range(0, len(x) - n + 1, n // 2):
        y = (x[k:k + n] - x[k:k + n].mean()) * hann
        acc += np.abs(np.fft.rfft(y)) ** 2
        cnt += 1
    f = np.fft.rfftfreq(n, 1 / fs)
    return f, acc / max(cnt, 1)


def fig5_spectrum():
    items = [("stand", "stand"), ("walk-1", "walk"), ("run-2", "run"),
             ("go_upstairs", "up"), ("go_downstairs", "down")]
    fig, ax = plt.subplots(figsize=(9.8, 5.4))
    curves = []
    for name, state in items:
        (t, _, _, _, _, _, _, dyn), _, _ = load_clean(name)
        fs = sample_rate(t)
        f, p = psd(dyn, fs)
        m = (f >= 0.5) & (f <= 6)
        curves.append((f[m], p[m], state, name))
    top = max(float(c[1].max()) for c in curves)
    for f, p, state, name in curves:
        pn = p / top
        ax.semilogy(f, pn, color=COLOR[state], lw=1.4,
                    label="%s（%s，峰 %.2f Hz）" % (STATE_CN[state], name, f[np.argmax(pn)]))
        ax.plot(f[np.argmax(pn)], pn.max(), "o", color=COLOR[state], ms=5)
    ax.set_xlabel("频率 (Hz)")
    ax.set_ylabel("功率谱（以五者最大值为 1）")
    ax.set_xlim(0.5, 6)
    ax.set_ylim(1e-5, 2)
    ax.legend(fontsize=8.5, loc="upper right")
    ax.set_title("图 5　纯动态加速度 |a-g| 的功率谱（8 s 分段平均）", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig5_spectrum.png"))
    plt.close(fig)


def fig6_timeline(rows):
    names = []
    seen = set()
    for r in rows:
        if r["record"] not in seen:
            seen.add(r["record"])
            names.append(r["record"])
    names.sort()
    fig, ax = plt.subplots(figsize=(11.5, 0.42 * len(names) + 1.8))
    for yi, name in enumerate(names):
        v = [r for r in rows if r["record"] == name]
        for r in v:
            ax.barh(yi, 0.98, left=r["t0"], height=0.62,
                    color=COLOR[r["pred"]], lw=0)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(["%-14s 真值:%s" % (n, STATE_CN[[r["state"] for r in rows if r["record"] == n][0]])
                        for n in names], fontsize=8.5)
    ax.invert_yaxis()
    ax.set_xlabel("时间 t (s)")
    ax.set_xlim(0, max(r["t0"] for r in rows) + 9)
    ax.legend(handles=[Patch(color=COLOR[k], label=STATE_CN[k]) for k in ORDER],
              ncol=5, fontsize=9, loc="upper center", bbox_to_anchor=(0.5, -0.18))
    ax.set_title("图 6　逐窗判决时间线（8 s 窗 / 1 s 步长）", fontsize=12)
    fig.tight_layout(rect=(0, 0.09, 1, 1))
    fig.savefig(os.path.join(FIG, "fig6_timeline.png"))
    plt.close(fig)


def fig7_rule(th):
    fig, ax = plt.subplots(figsize=(11, 8.2))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 11)
    ax.axis("off")

    def box(x, y, w, h, text, fc, fs=10.5):
        ax.add_patch(plt.Rectangle((x - w / 2, y - h / 2), w, h, facecolor=fc,
                                   edgecolor="#444", lw=1.2, zorder=2))
        ax.text(x, y, text, ha="center", va="center", fontsize=fs, zorder=3)

    def arrow(p1, p2, label=""):
        ax.annotate("", xy=p2, xytext=p1,
                    arrowprops=dict(arrowstyle="->", lw=1.3, color="#333"))
        if label:
            mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
            if abs(p1[0] - p2[0]) < 1e-9:
                ax.text(mx + 0.15, my, label, fontsize=9.5, color="#1f77b4",
                        ha="left", va="center")
            else:
                ax.text(mx, my + 0.2, label, fontsize=9.5, color="#1f77b4", ha="center")

    box(3.3, 10.1, 5.0, 0.85, "输入：8 s 三轴加速度窗（步长 1 s）", "#e8e8e8")
    box(3.3, 8.4, 5.0, 0.85, "σ(|a-g|) < %.2f ？" % th["stand"], "#dbe9f6")
    box(9.1, 8.4, 2.5, 0.85, "静止", "#c8e6c9", 13)
    box(3.3, 6.7, 5.0, 0.85, "σ > %.2f 或 峰值 > %.1f ？" % (th["run_sd"], th["run_peak"]), "#fbdcdc")
    box(9.1, 6.7, 2.5, 0.85, "快跑", "#f8c9c9", 13)
    box(3.3, 5.0, 5.0, 0.85, "σ_v > %.2f ？" % th["down_sv"], "#e6d8f0")
    box(9.1, 5.0, 2.5, 0.85, "下楼", "#d9c4ea", 13)
    box(3.3, 3.3, 5.0, 0.85, "p99 < %.2f ？" % th["up_p99"], "#ffe6cc")
    box(1.7, 1.6, 2.6, 0.85, "上楼", "#ffd7a8", 13)
    box(5.4, 1.6, 2.6, 0.85, "平地慢走", "#bcd7ea", 13)

    arrow((3.3, 9.67), (3.3, 8.83))
    arrow((5.8, 8.4), (7.85, 8.4), "是")
    arrow((3.3, 7.97), (3.3, 7.13), "否")
    arrow((5.8, 6.7), (7.85, 6.7), "是")
    arrow((3.3, 6.27), (3.3, 5.43), "否")
    arrow((5.8, 5.0), (7.85, 5.0), "是")
    arrow((3.3, 4.57), (3.3, 3.73), "否")
    arrow((2.6, 2.87), (1.8, 2.03), "是")
    arrow((4.0, 2.87), (5.3, 2.03), "否")

    ax.set_title("图 7　五级顺序判决（阈值由 data_2 标定）", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig7_rule.png"))
    plt.close(fig)


def fig8_gravity():
    """左图看 xy 投影，右图看 |0.5 s 均值| 随时间；两图的图例各按自己画出的数据算范围。"""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5.6))

    th = np.linspace(0, 2 * np.pi, 400)
    a1.plot(9.81 * np.cos(th), 9.81 * np.sin(th), "k--", lw=0.9, alpha=0.6,
            label="|g| = 9.81")

    outside = {}
    for name, state, hold_s in (("stand", "stand", 25.0), ("walk-1", "walk", None)):
        (t, ax, ay, az, gx, gy, gz, _), _, sl = load_clean(name)
        ax, ay, az = ax[sl], ay[sl], az[sl]
        fs = sample_rate(t[sl])
        n = int(0.5 * fs)
        k = np.ones(n) / n
        mx = np.convolve(ax, k, "valid")
        my = np.convolve(ay, k, "valid")
        mz = np.convolve(az, k, "valid")
        norm = np.sqrt(mx * mx + my * my + mz * mz)
        tm = (np.arange(len(norm)) + n / 2) / fs
        outside[state] = float((norm > 9.81).mean())

        # 左图是 xy 投影：手机竖直握持时 |g| 落在该平面，平放时大头在 z 轴上。
        # 静止段只取 0–25 s（竖直握持）；27 s 拿起手机后手机转过约 90°。
        sel = tm < hold_s if hold_s else np.ones(len(tm), bool)
        a1.plot(mx[sel], my[sel], lw=0.8, color=COLOR[state],
                label="%s%s（|mean|=%.1f~%.1f）"
                      % (STATE_CN[state], " 0–25 s" if hold_s else "",
                         norm[sel].min(), norm[sel].max()))

        # 右图用全段：静止段 27 s 的手持事件是真实动作，清洗只去首尾，不会被剔除。
        a2.plot(tm, norm, lw=0.7, color=COLOR[state],
                label="%s（|mean|=%.1f~%.1f）" % (STATE_CN[state], norm.min(), norm.max()))
        if hold_s:
            k_min = int(np.argmin(norm))
            a2.annotate("27 s 拿起手机\n|mean| 掉到 %.1f" % norm[k_min],
                        (tm[k_min], norm[k_min]), xytext=(tm[k_min] + 6, norm[k_min] - 0.8),
                        fontsize=8, color=COLOR[state],
                        arrowprops=dict(arrowstyle="->", lw=0.7, color=COLOR[state]))

    (t, _, _, _, gx, gy, gz, _), _, sl = load_clean("walk-1")
    gm = np.sqrt(gx[sl] ** 2 + gy[sl] ** 2 + gz[sl] ** 2)
    a2.plot(t[sl], gm, lw=0.8, color="#7f7f7f", alpha=0.7,
            label="Gravity 传感器 |g|（≡9.81）")

    a1.axhline(0, color="k", lw=0.4)
    a1.axvline(0, color="k", lw=0.4)
    a1.set_aspect("equal")
    a1.set_xlabel("0.5 s 均值 ax (m/s²)　（xy 投影）")
    a1.set_ylabel("0.5 s 均值 ay (m/s²)")
    a1.legend(fontsize=8, loc="upper right")
    a1.set_title("① 窗口均值方向 ≠ 重力：慢走 %.0f %% 的窗均值在圆外" % (100 * outside["walk"]),
                 fontsize=10)

    a2.axhline(9.81, color="k", ls="--", lw=0.9)
    a2.set_xlabel("时间 t (s)")
    a2.set_ylabel("|0.5 s 均值 a|  (m/s²)")
    a2.set_ylim(6, 17)
    a2.set_xlim(0, 95)
    a2.legend(fontsize=8, loc="upper right")
    a2.set_title("② 真实重力传感器恒定；窗口均值不是", fontsize=10)

    fig.suptitle("图 8　为什么必须用 Gravity 传感器（v1 的“均值方向=重力”不成立）", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig8_gravity.png"))
    plt.close(fig)


def main():
    setup()
    rows, th = collect_rows()
    fig1_waveforms()
    fig2_decompose()
    fig3_feature_plane(rows, th)
    fig4_distribution(rows, th)
    fig5_spectrum()
    fig6_timeline(rows)
    fig7_rule(th)
    fig8_gravity()
    print("figures written to", FIG)


if __name__ == "__main__":
    main()
