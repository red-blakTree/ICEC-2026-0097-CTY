#!/usr/bin/env python3
"""课题 08 v6 特征层：把"物理上应该不变"的量单独隔离出来。

分层（这是 v6 与 v2–v5.1 的主要区别）：

  不变核 invariant core
      rob_skew  稳健偏度 (q95+q05-2*q50)/(q95-q05)
      acp       自相关峰（0.30–1.20 s 滞后）
      zcr       过零率
      以上对 s→s+c（任意零偏）与 s→a·s（任意增益）都不变，见 invariants.py 的自检。
  协变量
      rob_skew 在 s→−s 时变号（下楼的负偏度就是这条），是协变不是不变。
  非不变（显式声明）
      sigma = std(|a−g|)，绝对幅值，只用于静止/快跑两个门限，不得混进不变核。
      它经过了本人跨日数据的检验，但换另一台设备时第一个要复查的就是它。

窗长 8 s / 步长 1 s、Gravity 解耦、清洗、0.08 s 滑动平均与 v2–v5 一致；CSV 读取、
清洗、峰检测直接复用 v2/v4 的实现，避免同一个约定在两处漂移。
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "v2"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "v4"))

from gait_analysis_v2 import (  # noqa: E402
    ROOT, STATE_CN, clean, find_records, infer_truth, load_record, sample_rate,
)
from gait_analysis_v4 import detect_peaks, moving_average  # noqa: E402

STATES = ("stand", "walk", "run", "up", "down")
WIN_S, HOP_S = 8.0, 1.0
SMOOTH_S = 0.08          # 与 v4/v5 相同的低通
AC_LAG_MIN, AC_LAG_MAX = 0.30, 1.20
INVARIANT = ("rob_skew", "acp", "zcr")
DIAGNOSTIC = ("cadence", "i_cv", "ac_lag", "n_steps", "bias")
NON_INVARIANT = ("sigma",)


def signal_features(s, fs):
    """只看竖向波形 s 的特征。这是不变核的唯一入口，invariants.py 直接测它。"""
    s0 = s - s.mean()
    std = float(s0.std() + 1e-12)

    q05, q50, q95 = np.percentile(s0, [5, 50, 95])
    rob_skew = float((q95 + q05 - 2 * q50) / (q95 - q05 + 1e-12))

    ac = np.correlate(s0, s0, "full")[len(s0) - 1:]
    ac = ac / (ac[0] + 1e-12)
    lo, hi = max(1, int(AC_LAG_MIN * fs)), min(len(ac) - 1, int(AC_LAG_MAX * fs))
    acp = float(ac[lo:hi].max()) if hi > lo else 0.0
    ac_lag = (lo + int(np.argmax(ac[lo:hi]))) / fs if hi > lo else 0.0

    peaks = detect_peaks(s0, fs)
    dur = len(s) / fs
    intervals = np.diff(peaks) / fs if len(peaks) >= 2 else np.array([])
    i_cv = float(np.std(intervals) / (abs(np.mean(intervals)) + 1e-12)) if len(intervals) >= 2 else 0.0

    return dict(
        rob_skew=rob_skew, acp=acp, ac_lag=ac_lag,
        zcr=float(np.sum(np.diff(np.signbit(s0)) != 0) / dur),
        n_steps=len(peaks), cadence=len(peaks) / dur, i_cv=i_cv,
        std=std,
    )


def window_features(t, ax, ay, az, gx, gy, gz):
    """一个窗的全部特征：不变核 + 诊断量 + 一个声明的非不变量（sigma）。"""
    gn = np.sqrt(gx * gx + gy * gy + gz * gz)
    a_v = ax * gx / gn + ay * gy / gn + az * gz / gn - gn
    dyn = np.sqrt((ax - gx) ** 2 + (ay - gy) ** 2 + (az - gz) ** 2)
    fs = sample_rate(t)
    s = moving_average(a_v, SMOOTH_S * fs)
    f = signal_features(s, fs)
    f.update(fs=fs, bias=float(np.median(s)), sigma=float(dyn.std()))
    return f


def collect(root, tag=None):
    """把一个目录下的记录切成 8 s / 1 s 窗。"""
    tag = tag or os.path.basename(os.path.normpath(root))
    rows = []
    for path in find_records(root):
        name = os.path.relpath(path, root)
        truth = infer_truth(name)
        t, ax, ay, az, gx, gy, gz = load_record(path)
        dyn = np.sqrt((ax - gx) ** 2 + (ay - gy) ** 2 + (az - gz) ** 2)
        i, j = clean(t, dyn)
        if j - i < 2:
            continue
        fs = sample_rate(t[i:j])
        w, h = int(WIN_S * fs), int(HOP_S * fs)
        for k in range(0, j - i - w + 1, h):
            sl = slice(i + k, i + k + w)
            f = window_features(t[sl], ax[sl], ay[sl], az[sl], gx[sl], gy[sl], gz[sl])
            f.update(record=name, state=truth, t0=float(t[i + k]), dataset=tag)
            rows.append(f)
    return rows
