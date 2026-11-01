#!/usr/bin/env python3
"""课题 3 分析图生成脚本（matplotlib）。

输入
    data/measurements.csv   点位级 RSSI / SIR + 每轮延迟 / 吞吐
    data/signal.csv          逐张截图的读数（用于「另一页」RSSI）

输出
    picture/analysis/fig1_rssi_sir.png       两页 RSSI 对照 + SIR
    picture/analysis/fig2_latency_throughput.png  延迟范围 + 吞吐范围
    picture/analysis/fig3_distance_profile.png    514 走廊距离剖面
    picture/analysis/fig4_corridor.png            514–507 走廊 1D 标定示意

运行（任意装有 matplotlib / numpy 的 Python）：
    ../topic_8/.venv/bin/python src/make_figures.py
    # 或 pip install matplotlib numpy 后 python3 src/make_figures.py
"""

import csv
import os
import tempfile
from pathlib import Path
from statistics import mean, median

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "mplcache-topic3"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "picture" / "analysis"

POINTS = [
    ("T5-01", "zero"), ("T5-02", "test"), ("T5-03", "test"), ("T5-04", "zero"),
    ("T5-05", "test"), ("T5-06", "test"), ("T5-07", "test"), ("T5-08", "test"),
    ("L1-01", "test"), ("D-01", "zero"), ("D-02", "test"),
]

# signal.csv 中「概览页 / 扫描页」的对应截图（同一会话、同一位置）
OVERVIEW_FILE = {
    "T5-01": "datum_mark/514-after.2.jpg", "T5-02": "514(supplementary_survey)/514.1.jpg",
    "T5-03": "514-507/504-507.2.jpg", "T5-04": "datum_mark/elevator-after.2.jpg",
    "T5-05": "in_elevator/in_elevator.5.jpg", "T5-06": "512(corner)/512.1.jpg",
    "T5-07": "stairs/stairs.4.jpg", "T5-08": "fireproof_door/fireproof_door.1.jpg",
    "L1-01": "glass/glass.2.jpg", "D-01": "dormitory/dormitory-before.1.jpg",
    "D-02": "dormitory/dormitory-after.2.jpg",
}
SCAN_FILE = {
    "T5-01": "datum_mark/514-after.1.jpg", "T5-02": "514(supplementary_survey)/514.2.jpg",
    "T5-03": "514-507/504-507.1.jpg", "T5-04": "datum_mark/elevator-after.1.jpg",
    "T5-05": "in_elevator/in_elevator.3.jpg", "T5-06": "512(corner)/512.2.jpg",
    "T5-07": "stairs/stairs.3.jpg", "T5-08": "fireproof_door/fireproof_door.2.jpg",
    "L1-01": "glass/glass.1.jpg", "D-01": "dormitory/dormitory-before.2.jpg",
    "D-02": "dormitory/dormitory-after.1.jpg",
}

C_OV, C_SC, C_SIR = "#3b6ea5", "#d07a3f", "#6a4c93"
C_DN, C_UP = "#2a9d8f", "#e76f51"

plt.rcParams.update({
    "figure.dpi": 160, "savefig.dpi": 160, "font.size": 9,
    "axes.titlesize": 11, "axes.labelsize": 9,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.6,
    "axes.axisbelow": True, "legend.frameon": False,
})


def load_data():
    with (ROOT / "data" / "measurements.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    stats = {}
    for pid, _ in POINTS:
        rs = [r for r in rows if r["point_id"] == pid]
        assert rs, pid
        stats[pid] = {
            "rssi": float(rs[0]["rssi_dbm"]),
            "sir": float(rs[0]["sir_db"]),
            "ping": [float(r["ping_ms"]) for r in rs],
            "p95": [float(r["p95_ms"]) for r in rs],
            "down": [float(r["down_mbps"]) for r in rs],
            "up": [float(r["up_mbps"]) for r in rs],
        }
    with (ROOT / "data" / "signal.csv").open(encoding="utf-8-sig") as f:
        signal = {r["source_file"].split("/", 1)[1]: r for r in csv.DictReader(f)}
    return stats, signal


def rssi_of(signal, rel):
    return float(signal[rel]["rssi_dbm"])


def fig1(stats, signal):
    names = [p for p, _ in POINTS]
    ov = [rssi_of(signal, OVERVIEW_FILE[p]) for p in names]
    sc = [rssi_of(signal, SCAN_FILE[p]) for p in names]
    sir = [stats[p]["sir"] for p in names]

    fig, (ax, bx) = plt.subplots(
        2, 1, figsize=(10, 6.4), sharex=True,
        gridspec_kw={"height_ratios": [2.4, 1.0]}, constrained_layout=True,
    )
    x = range(len(names))
    w = 0.38
    base = -90
    ax.bar([i - w / 2 for i in x], [v - base for v in ov], w, bottom=base,
           color=C_OV, label="overview page")
    ax.bar([i + w / 2 for i in x], [v - base for v in sc], w, bottom=base,
           color=C_SC, label="scan page")
    for i, v in enumerate(ov):
        ax.annotate(f"{v:.0f}", (i - w / 2, v), textcoords="offset points",
                    xytext=(0, 3), ha="center", fontsize=7, color="#222222")
    for i, v in enumerate(sc):
        ax.annotate(f"{v:.0f}", (i + w / 2, v), textcoords="offset points",
                    xytext=(0, 3), ha="center", fontsize=7, color="#222222")
    ax.axhline(-70, color="#555555", ls="--", lw=0.9)
    ax.axhline(-80, color="#555555", ls=":", lw=0.9)
    ax.set_ylim(-90, -50)
    ax2 = ax.twinx()
    ax2.set_ylim(-90, -50)
    ax2.set_yticks([-70, -80])
    ax2.set_yticklabels(["-70 dBm (edge)", "-80 dBm (blind)"])
    ax2.tick_params(axis="y", length=0, labelsize=7, colors="#555555")
    for side in ("top", "right", "left"):
        ax2.spines[side].set_visible(False)
    ax2.grid(False)
    ax.set_ylabel("RSSI (dBm)")
    ax.set_title("RSSI by PureHub page (bar) and SIR (lower panel), per point")
    ax.legend(ncol=2, loc="lower center", frameon=True, facecolor="white", edgecolor="none", framealpha=0.95)

    bx.axhline(0, color="#888888", lw=0.8)
    bx.stem(x, sir, linefmt="-", markerfmt="D", basefmt=" ")
    for i, v in enumerate(sir):
        bx.annotate(f"{v:+.1f}", (i, v), textcoords="offset points",
                    xytext=(0, 5 if v >= 0 else -12), ha="center", fontsize=7)
    bx.set_ylim(-45, 40)
    bx.set_ylabel("SIR (dB)")
    bx.set_xticks(list(x))
    bx.set_xticklabels(names, rotation=25, ha="right")
    fig.savefig(OUT / "fig1_rssi_sir.png", bbox_inches="tight")
    plt.close(fig)


def fig2(stats):
    names = [p for p, _ in POINTS]
    x = list(range(len(names)))
    ping_med = [median(stats[p]["ping"]) for p in names]
    ping_lo = [min(stats[p]["ping"]) for p in names]
    ping_hi = [max(stats[p]["ping"]) for p in names]
    p95_med = [median(stats[p]["p95"]) for p in names]
    p95_lo = [min(stats[p]["p95"]) for p in names]
    p95_hi = [max(stats[p]["p95"]) for p in names]

    fig, (ax, bx) = plt.subplots(1, 2, figsize=(11.5, 4.9), constrained_layout=True)
    ax.errorbar([i - 0.13 for i in x], ping_med,
                yerr=[[m - lo for m, lo, hi in zip(ping_med, ping_lo, ping_hi)],
                      [hi - m for m, lo, hi in zip(ping_med, ping_lo, ping_hi)]],
                fmt="o", color=C_DN, ms=4, lw=1, capsize=2, label="PING median (min–max)")
    ax.errorbar([i + 0.13 for i in x], p95_med,
                yerr=[[m - lo for m, lo, hi in zip(p95_med, p95_lo, p95_hi)],
                      [hi - m for m, lo, hi in zip(p95_med, p95_lo, p95_hi)]],
                fmt="s", color=C_UP, ms=4, lw=1, capsize=2, label="P95 (min–max)")
    ax.set_yscale("log")
    ax.set_ylim(18, 700)
    ax.set_ylabel("latency (ms, log)")
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=25, ha="right")
    ax.set_title("Latency per point (per-round values)")
    ax.legend(loc="upper left")
    ax.annotate("473.8 ms\n(elevator, first round)", (4 + 0.13, 473.8),
                textcoords="offset points", xytext=(18, 8), fontsize=7,
                arrowprops=dict(arrowstyle="-", lw=0.7, color="#555555"))

    y = list(range(len(names)))[::-1]
    for yy, p in zip(y, names):
        dn, up_ = stats[p]["down"], [u if u > 0 else None for u in stats[p]["up"]]
        bx.plot([min(dn), max(dn)], [yy + 0.16, yy + 0.16], color=C_DN, lw=2.2,
                solid_capstyle="round")
        bx.plot([min(dn), max(dn)], [yy + 0.16, yy + 0.16], "|", color=C_DN, ms=6)
        ups = [u for u in up_ if u is not None]
        bx.plot([min(ups), max(ups)], [yy - 0.16, yy - 0.16], color=C_UP, lw=2.2,
                solid_capstyle="round")
        bx.plot([min(ups), max(ups)], [yy - 0.16, yy - 0.16], "|", color=C_UP, ms=6)
    bx.set_xscale("log")
    bx.set_xlim(2, 500)
    bx.set_yticks(y)
    bx.set_yticklabels(names)
    bx.set_xlabel("throughput (Mbps, log)")
    bx.set_title("Download / upload range per point")
    bx.grid(axis="y", visible=False)
    bx.legend(handles=[
        Line2D([], [], color=C_DN, lw=2.2, label="download (min–max)"),
        Line2D([], [], color=C_UP, lw=2.2, label="upload (min–max)"),
    ], loc="lower left")
    fig.savefig(OUT / "fig2_latency_throughput.png", bbox_inches="tight")
    plt.close(fig)


def fig3(stats, signal):
    def rssi(rel):
        return float(signal[rel]["rssi_dbm"])

    d1 = [1, 8.5, 42.5]
    r1 = [stats["T5-01"]["rssi"], stats["T5-02"]["rssi"], stats["T5-03"]["rssi"]]
    near = [rssi(f"supplementary_data/514-nearfield.{i}.jpg") for i in (1, 2, 3)]
    far = [rssi("supplementary_data/514-507.jpg"),
           rssi("supplementary_data/514-507(retest).2.jpg"),
           rssi("supplementary_data/514-507(retest).3.jpg"),
           rssi("supplementary_data/514-507(retest).4.jpg")]
    d2 = [8.5, 17, 25.5, 34]
    r2 = [rssi("supplementary_data/514-513.2.jpg"),
          rssi("supplementary_data/514-511.jpg"),
          rssi("supplementary_data/514-509.jpg"),
          mean(far)]
    fig, ax = plt.subplots(figsize=(8.6, 5.4), constrained_layout=True)
    ax.plot(d1, r1, "o-", color=C_OV, ms=6, lw=1.4, label="2026-10-24 overview (1 m zero → 42.5 m)")
    ax.plot(d2, r2, "s-", color=C_SC, ms=6, lw=1.4, label="2026-11-01 scan (front-to-front ladder)")
    ax.scatter([d2[2]], [r2[2]], s=70, facecolor="white", edgecolor=C_SC, lw=1.6, zorder=6)
    ax.annotate("25.5 m suspect\n(SIR −47.8)", (d2[2], r2[2]), textcoords="offset points",
                xytext=(-4, 26), ha="center", fontsize=7, color="#c0392b")

    ax.scatter([0.01] * 3, near, marker="x", color="#777777", s=40,
               label="1 cm near field (upper bound only)")
    ax.annotate("1 cm near-field\n(not an anchor)", (0.01, -40), textcoords="offset points",
                xytext=(12, 6), fontsize=7, color="#555555")

    import math
    dd = [0.008, 42.5]
    ax.plot(dd, [-61 - 20 * math.log10(d) for d in dd], "--", color="#999999", lw=1,
            label="free space, n = 2 (anchored at −61 dBm @ 1 m)")
    ax.plot(dd, [-61 - 13.5 * math.log10(d) for d in dd], ":", color="#444444", lw=1.1,
            label="full-span fit, n = 1.35")
    ax.plot([8.5, 42.5], [-72 - 5.8 * math.log10(d / 8.5) for d in [8.5, 42.5]], "-.",
            color="#bb7733", lw=1, label="same-session ladder, n = 0.58")

    conv = mean(far) - 20 * math.log10(42.5 / 34)
    ax.scatter([42.5], [conv], marker="*", s=140, facecolor="none",
               edgecolor="#c0392b", lw=1.2, zorder=5)
    ax.annotate(f"{mean(far):.1f} → {conv:.1f} dBm\n(34 → 42.5 m, n = 2)", (42.5, conv),
                textcoords="offset points", xytext=(12, 14), ha="left",
                fontsize=7, color="#c0392b")
    ax.annotate("", xy=(42.5, r1[-1] + 0.4), xytext=(42.5, conv - 0.4),
                arrowprops=dict(arrowstyle="<->", lw=1, color="#c0392b"))
    ax.annotate(f"≈ {conv - r1[-1]:.0f} dB\n(cross-session)", (42.5, (conv + r1[-1]) / 2), textcoords="offset points",
                xytext=(-88, -18), fontsize=7, color="#c0392b")

    ax.set_xscale("log")
    ax.set_xlim(0.007, 70)
    ax.set_ylim(-90, -35)
    ax.set_xlabel("distance from hotspot (m, log)")
    ax.set_ylabel("RSSI (dBm)")
    ax.set_title("514 corridor distance profile: two sessions, four slopes")
    ax.legend(loc="lower left", fontsize=7)
    ax.set_xticks([0.01, 0.1, 1, 3, 8.5, 17, 25.5, 42.5])
    ax.set_xticklabels(["0.01", "0.1", "1", "3", "8.5", "17", "25.5", "42.5"],
                       rotation=0, fontsize=7)
    fig.savefig(OUT / "fig3_distance_profile.png", bbox_inches="tight")
    plt.close(fig)


def fig4():
    fig, ax = plt.subplots(figsize=(11, 3.9), constrained_layout=True)
    rooms = [(0, 8.5, "514"), (8.5, 17, "513"), (17, 25.5, "511"),
             (25.5, 34, "509"), (34, 42.5, "507")]
    south = [(8.5, 17, "512"), (17, 25.5, "510"), (25.5, 34, "508")]
    ax.add_patch(Rectangle((0, 2.1), 42.5, 1.1, fc="#eef2f7", ec="#33415c", lw=1.2))
    for x0, x1, name in rooms:
        ax.plot([x0, x0], [2.1, 3.2], color="#33415c", lw=1.1)
        ax.text((x0 + x1) / 2, 3.45, name, ha="center", va="bottom", fontsize=10,
                fontweight="bold")
    ax.plot([42.5, 42.5], [2.1, 3.2], color="#33415c", lw=1.1)
    for x0, x1, name in south:
        ax.text((x0 + x1) / 2, 1.85, name, ha="center", va="top", fontsize=8,
                color="#555555")
    ax.add_patch(Rectangle((17, 2.1), 8.5, 0.16, fc="none", hatch="////",
                           ec="#c0392b", lw=0))
    ax.text(21.25, 2.55, "510 protrusion\n(17–25.5 m)", ha="center", va="bottom",
            fontsize=7, color="#c0392b")

    for d, name, off, ha in [(1, "T5-01", (-4, 10), "right"),
                             (8.5, "T5-02", (6, 12), "left"),
                             (42.5, "T5-03", (-4, 10), "right")]:
        ax.scatter([d], [2.65], s=55, color="#c0392b", zorder=6)
        ax.annotate(name, (d, 2.65), textcoords="offset points", xytext=off,
                    ha=ha, fontsize=9, color="#c0392b", fontweight="bold")
    for d in [17, 25.5, 34]:
        ax.scatter([d], [2.65], s=30, facecolor="white", edgecolor="#d07a3f",
                   lw=1.2, zorder=6)
    ax.scatter([8.5], [2.65], s=30, facecolor="white", edgecolor="#d07a3f", lw=1.2, zorder=5)
    ax.text(21.25, 1.28, "ladder points 8.5 / 17 / 25.5 / 34 m (11-01)",
            ha="center", va="top", fontsize=7, color="#d07a3f")

    ax.annotate("", xy=(8.5, 0.62), xytext=(0, 0.62),
                arrowprops=dict(arrowstyle="<->", lw=0.9, color="#444444"))
    ax.text(4.25, 0.72, "8.5 m", ha="center", fontsize=8)
    ax.annotate("", xy=(34, 0.22), xytext=(0, 0.22),
                arrowprops=dict(arrowstyle="<->", lw=0.9, color="#444444"))
    ax.text(17, 0.32, "34 m (507 front door)", ha="center", fontsize=8)
    ax.annotate("", xy=(42.5, -0.18), xytext=(0, -0.18),
                arrowprops=dict(arrowstyle="<->", lw=0.9, color="#444444"))
    ax.text(21.25, -0.08, "42.5 m (507 back door, 10-24 point T5-03)", ha="center", fontsize=8)
    ax.scatter([0], [2.65], marker="^", s=80, color="#2a9d8f", zorder=6)
    ax.text(-1.5, 1.5, "hotspot (514 front door)", ha="left", va="top",
            fontsize=7, color="#2a9d8f")

    ax.set_xlim(-2, 47)
    ax.set_ylim(-0.5, 4.6)
    ax.set_yticks([])
    ax.set_xlabel("distance from 514 front door (m)")
    ax.set_title("514–507 corridor, 1D calibration (8.5 m per classroom bay)")
    ax.grid(axis="y", visible=False)
    ax.spines["left"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.savefig(OUT / "fig4_corridor.png", bbox_inches="tight")
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stats, signal = load_data()
    fig1(stats, signal)
    fig2(stats)
    fig3(stats, signal)
    fig4()
    for name in ("fig1_rssi_sir.png", "fig2_latency_throughput.png",
                 "fig3_distance_profile.png", "fig4_corridor.png"):
        print(OUT / name)


if __name__ == "__main__":
    main()
