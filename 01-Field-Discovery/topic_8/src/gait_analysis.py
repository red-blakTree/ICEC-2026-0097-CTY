#!/usr/bin/env python3
"""课题 08 —— 多姿态步态加速度特征采集与对比：清洗、特征提取与阈值判定。

输入：data/<记录名>/Raw Data.csv（Phyphox 原始导出，列：t, ax, ay, az, |a|）
输出：output/features/windows.csv（4 s 滑窗特征 + 判定结果）
      output/features/summary.csv （每段记录的统计汇总）
      output/features/eval.txt    （阈值规则的窗口级准确率）

用法：.venv/bin/python src/gait_analysis.py
"""
import csv
from collections import Counter
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "output", "features")

# 记录名 -> (状态键, 说明)
RECORDS = [
    ("walk-1", "walk"), ("walk-2", "walk"), ("walk-3", "walk"),
    ("run", "run"),
    ("go_upstairs-1", "stairs"), ("go_upstairs-2", "stairs"), ("go_upstairs-3", "stairs"),
    ("go_downstairs-1", "stairs"), ("go_downstairs-2", "stairs"), ("go_downstairs-3", "stairs"),
    ("stand", "stand"),
]
STATE_CN = {"walk": "平地慢走", "run": "快跑", "stairs": "上下楼梯", "stand": "静止"}

# ---- 阈值（由 data/ 全部 11 段记录标定，见 README 第 5 节）----
T_STAND_SD = 0.30    # |a| 标准差 < 0.30 m/s^2 -> 静止
T_RUN_SD = 8.00      # |a| 标准差 > 8.00 m/s^2 -> 快跑
T_RUN_PEAK = 40.0    # 峰值 |a| > 40 m/s^2 作为快跑的辅助判据
T_STAIRS_RATIO = 1.50  # 竖向/横向标准差比 > 1.50 -> 上下楼梯

# ---- 清洗参数 ----
DROPOUT_MAG = 2.0      # |a| < 2 m/s^2 视为传感器掉零
TRANSIENT_K = 3.0      # 窗内标准差 > 3 倍全段中位数视为启停瞬态
GUARD_S = 0.5          # 两端额外丢弃的保护带

WIN_S = 4.0
HOP_S = 0.5


def read_phyphox(path):
    """读取 Phyphox 导出的 Raw Data.csv。"""
    rows = []
    with open(path, newline="") as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if len(row) >= 5:
                rows.append([float(v) for v in row[:5]])
    arr = np.array(rows, dtype=float)
    return arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]


def sample_rate(t):
    return (len(t) - 1) / (t[-1] - t[0])


def moving_std(x, n):
    """长度相同的滑动标准差（中心对齐，边界收缩）。"""
    pad = n // 2
    xp = np.pad(x, (pad, pad), mode="edge")
    c1 = np.convolve(xp, np.ones(n), "valid")
    c2 = np.convolve(xp * xp, np.ones(n), "valid")
    m = c1 / n
    var = np.maximum(c2 / n - m * m, 0.0)
    return np.sqrt(var)[: len(x)]


def clean(t, ax, ay, az, mag):
    """去除采集启停造成的异常段，返回保留区间 [i, j)。

    规则 1（掉零）：两端 |a| < 2 m/s^2 的样本属于传感器未填充/关闭，直接丢弃。
    规则 2（启停瞬态）：两端 0.5 s 滑动标准差大于全段中位数 3 倍的样本，
            属于拿起/放下手机的动作，丢弃。
    规则 3（保护带）：两端再各留 0.5 s，避开半周期与耦合迟滞。
    """
    n = len(mag)
    i, j = 0, n
    while i < j and mag[i] < DROPOUT_MAG:
        i += 1
    while j > i and mag[j - 1] < DROPOUT_MAG:
        j -= 1
    if j - i < 2:
        return 0, 0

    fs = sample_rate(t[i:j])
    nw = max(3, int(round(0.5 * fs)))
    msd = moving_std(mag[i:j], nw)
    thr = TRANSIENT_K * float(np.median(msd))
    a, b = 0, len(msd)
    while a < b and msd[a] > thr:
        a += 1
    while b > a and msd[b - 1] > thr:
        b -= 1

    guard = int(round(GUARD_S * fs))
    return i + a + guard, i + b - guard


def window_features(t, ax, ay, az, mag):
    """单个窗口的加速度特征（均与手机姿态无关）。"""
    n = len(mag)
    fs = sample_rate(t)
    mean_mag = float(mag.mean())
    std_mag = float(mag.std())
    lo, hi = np.percentile(mag, [5, 95])

    # 以窗口平均重力向量为“竖向”，其余为“横向”
    g = np.array([ax.mean(), ay.mean(), az.mean()])
    gn = float(np.linalg.norm(g))
    if gn < 1e-6:
        g, gn = np.array([0.0, 0.0, 1.0]), 1.0
    u = g / gn
    vert = ax * u[0] + ay * u[1] + az * u[2]
    hor = np.sqrt(np.maximum(ax * ax + ay * ay + az * az - vert * vert, 0.0))

    return dict(
        fs=fs,
        n=n,
        mean_mag=mean_mag,
        std_mag=std_mag,
        p2p=float(hi - lo),
        peak=float(mag.max()),
        std_v=float(vert.std()),
        std_h=float(hor.std()),
        ratio=float(vert.std() / (hor.std() + 1e-9)),
        g_mag=gn,
        f_dom=dominant_freq(mag, fs),
    )


def dominant_freq(mag, fs, lo=0.8, hi=5.0, step=0.05):
    """0.8~5 Hz 内的频谱主峰（步频 / 摆臂频率）。"""
    n = len(mag)
    x = mag - mag.mean()
    x = x * np.hanning(n)
    freqs = np.arange(lo, hi + 1e-9, step)
    k = np.arange(n)
    basis = np.exp(-2j * np.pi * np.outer(freqs, k) / fs)
    power = np.abs(basis @ x) ** 2
    return float(freqs[int(np.argmax(power))])


def classify(f):
    """四级阈值判别（顺序执行，先判静止与快跑，再分楼梯与平地）。"""
    if f["std_mag"] < T_STAND_SD:
        return "stand"
    if f["std_mag"] > T_RUN_SD or f["peak"] > T_RUN_PEAK:
        return "run"
    if f["ratio"] > T_STAIRS_RATIO:
        return "stairs"
    return "walk"


def windows(t, ax, ay, az, mag):
    fs = sample_rate(t)
    w = int(round(WIN_S * fs))
    h = int(round(HOP_S * fs))
    k = 0
    while k + w <= len(mag):
        yield k, window_features(t[k:k + w], ax[k:k + w], ay[k:k + w], az[k:k + w], mag[k:k + w])
        k += h


def main():
    os.makedirs(OUT, exist_ok=True)
    rows, summary, eval_lines = [], [], []
    total = correct = 0

    for name, truth in RECORDS:
        t, ax, ay, az, mag = read_phyphox(os.path.join(DATA, name, "Raw Data.csv"))
        i, j = clean(t, ax, ay, az, mag)
        t, ax, ay, az, mag = t[i:j], ax[i:j], ay[i:j], az[i:j], mag[i:j]

        feats = []
        for k, f in windows(t, ax, ay, az, mag):
            f["record"] = name
            f["state"] = truth
            f["t0"] = float(t[k])
            f["pred"] = classify(f)
            feats.append(f)
        rows.extend(feats)

        hit = sum(1 for f in feats if f["pred"] == truth)
        total += len(feats)
        correct += hit
        sd = [f["std_mag"] for f in feats]
        rt = [f["ratio"] for f in feats]
        votes = Counter(f["pred"] for f in feats)
        summary.append(dict(
            record=name, state=truth, n_raw=j - i, fs=feats[0]["fs"],
            t_start=float(t[0]), t_end=float(t[-1]), n_win=len(feats),
            sd_min=min(sd), sd_med=float(np.median(sd)), sd_max=max(sd),
            ratio_min=min(rt), ratio_med=float(np.median(rt)), ratio_max=max(rt),
            peak_max=max(f["peak"] for f in feats),
            fdom_med=float(np.median([f["f_dom"] for f in feats])),
            hit=hit,
            majority=votes.most_common(1)[0][0],
        ))
        eval_lines.append(
            "%-16s truth=%-6s windows=%3d correct=%3d acc=%.3f  votes=%s  cleaned=%.1f-%.1fs"
            % (name, truth, len(feats), hit, hit / len(feats), dict(votes),
               t[0], t[-1]))

    eval_lines.append("")
    eval_lines.append("窗口级总准确率: %d/%d = %.4f" % (correct, total, correct / total))
    rec_ok = sum(1 for s in summary if s["majority"] == s["state"])
    eval_lines.append("记录级（多数票）准确率: %d/%d" % (rec_ok, len(summary)))

    fields = ["record", "state", "t0", "fs", "n", "mean_mag", "std_mag", "p2p", "peak",
              "std_v", "std_h", "ratio", "g_mag", "f_dom", "pred"]
    with open(os.path.join(OUT, "windows.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(r[k], 4) if isinstance(r[k], float) else r[k]) for k in fields})

    with open(os.path.join(OUT, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        for r in summary:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})

    with open(os.path.join(OUT, "eval.txt"), "w") as f:
        f.write("\n".join(eval_lines) + "\n")
    print("\n".join(eval_lines))


if __name__ == "__main__":
    main()
