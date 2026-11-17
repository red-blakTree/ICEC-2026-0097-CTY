#!/usr/bin/env python3
"""课题 08 —— 用提交的 4 份 CSV 直接生成交付核对图。

输入：output/v1/csv/01_walk_flat.csv … 04_static.csv
输出：output/v1/figures/fig8_delivery.png
用法：MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/v1/make_delivery_figure.py
"""
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gait_analysis import (  # noqa: E402
    RECORDS, ROOT, STATE_CN, SUBMISSION, classify, clean, read_phyphox, windows,
)
from make_figures import COLOR, setup  # noqa: E402

CSV = os.path.join(ROOT, "output", "v1", "csv")
FIG = os.path.join(ROOT, "output", "v1", "figures")
STATE = dict(RECORDS)


def main():
    setup()
    fig, axes = plt.subplots(2, 2, figsize=(12.4, 7.8))
    for ax, (fname, record) in zip(axes.ravel(), SUBMISSION):
        t, ax_, ay_, az_, mag = read_phyphox(os.path.join(CSV, fname))
        i, j = clean(t, ax_, ay_, az_, mag)
        state = STATE[record]
        feats = [f for _, f in windows(t[i:j], ax_[i:j], ay_[i:j], az_[i:j], mag[i:j])]
        hit = sum(classify(f) == state for f in feats)
        n = len(feats)
        sig = float(np.median([f["std_mag"] for f in feats]))
        peak = float(mag[i:j].max())
        ratio = float(np.median([f["ratio"] for f in feats]))

        ax.plot(t, mag, lw=0.5, color=COLOR[state])
        ax.axvspan(t[0], t[i], color="#e41a1c", alpha=0.15, lw=0)
        ax.axvspan(t[j - 1], t[-1], color="#e41a1c", alpha=0.15, lw=0)
        ax.set_xlim(t[0], t[-1])
        ax.set_ylim(0, max(peak, 1.0) * 1.35)
        ax.set_xlabel("时间 t (s)")
        ax.set_ylabel("|a| (m/s²)")
        ax.set_title("%s —— %s（源记录 %s，%.1f s）"
                     % (STATE_CN[state], fname, record, t[-1] - t[0]), fontsize=10)
        ax.text(0.985, 0.95,
                "4 s 窗 %d 个\n判对 %d 个（%.1f %%）\nσ 中位 %.2f m/s²\n峰值 %.1f m/s²\nσ_v/σ_h 中位 %.2f"
                % (n, hit, 100.0 * hit / n, sig, peak, ratio),
                transform=ax.transAxes, ha="right", va="top", fontsize=8.5,
                bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="#bbbbbb", alpha=0.9))

    fig.suptitle("图 8  四份提交 CSV 的原始波形、清洗区间与 4 类阈值判定核对", fontsize=13)
    fig.text(0.5, 0.012,
             "判定顺序：σ(|a|) < 0.30 → 静止；σ > 8.0 或峰值 > 40 m/s² → 快跑；"
             "σ_v/σ_h > 1.50 → 上下楼梯；否则平地慢走。红底为采集启停异常段。",
             ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    out = os.path.join(FIG, "fig8_delivery.png")
    fig.savefig(out)
    plt.close(fig)
    print("written", out)


if __name__ == "__main__":
    main()
