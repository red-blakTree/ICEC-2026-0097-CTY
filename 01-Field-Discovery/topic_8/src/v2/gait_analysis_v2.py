#!/usr/bin/env python3
"""课题 08 v2 —— 用 Gravity 传感器做姿态无关的五类步态判别。

v1（gait_analysis.py）把“4 s 窗内三轴均值方向”当作重力方向，但手机绕手腕转动时
该假设不成立：实测标定集手持慢走的均值模长只有 4.2~4.6 m/s²（真实重力 9.8），
所以 v1 的 σ_v/σ_h 编码的其实是“某一种手腕摆动风格”，换人/换机即失效。

v2 改用 Phyphox 同时导出的 Gravity 传感器（硬件融合，|g| 恒为 9.81），逐样本把
加速度分解成竖向 / 横向，并用 a - g 得到不含重力的动态加速度：

    ĝ(t) = g(t) / |g(t)|
    a_v  = a·ĝ - |g|            竖向动态加速度（扣掉 9.8 常量）
    d    = a - g                动态加速度向量
    a_h  = |d - (d·ĝ)ĝ|         横向动态幅值

输入：<dir>/<记录>/{Accelerometer,Gravity}.csv
输出：output/v2/features/{windows,summary}.csv、eval.txt

用法：
    .venv/bin/python src/v2/gait_analysis_v2.py                 # 主数据集 data/calib/data_2
    .venv/bin/python src/v2/gait_analysis_v2.py --win 4 --hop 0.5
    .venv/bin/python src/v2/gait_analysis_v2.py --sweep         # 窗长对比
"""
import argparse
import csv
import os
import shutil
from collections import Counter

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "output", "v2", "features")

# 提交用：5 类各取一段 Accelerometer.csv
SUBMISSION = [
    ("01_walk_flat.csv", "walk-1"),
    ("02_run.csv", "run-2"),
    ("03_upstairs.csv", "go_upstairs"),
    ("04_downstairs.csv", "go_downstairs"),
    ("05_static.csv", "stand"),
]


def write_submission_csvs(src_root, out_dir):
    """把 5 类各一段 Accelerometer.csv 复制成提交用 CSV。"""
    os.makedirs(out_dir, exist_ok=True)
    for dst, rec in SUBMISSION:
        src = os.path.join(src_root, rec, "Accelerometer.csv")
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(out_dir, dst))

STATE_CN = {"stand": "静止", "walk": "平地慢走", "run": "快跑", "up": "上楼", "down": "下楼"}
STATES = ("stand", "walk", "run", "up", "down")

# 默认 8 s 窗：4 s 只含约 7 个步态周期，σ_v/σ_h 的估计方差过大
# （4 s -> 91.8 %，6 s -> 94.9 %，8 s -> 97.4 %，见 README 第 2.3 节末的窗长对比）。
WIN_S = 8.0
HOP_S = 1.0

# ---- 清洗参数 ----
STILL_FRAC = 0.3     # 0.5 s 标准差 < 0.3 倍中位数 -> 首尾静止段
TRANSIENT_K = 3.0    # 0.5 s 标准差 > 3 倍中位数 -> 启停瞬态
STILL_FLOOR = 0.5    # 中位数低于此值（如静止记录）时不启用静止段判据
GUARD_S = 0.5        # 两端保护带


def read_sensor_csv(path):
    """读取 Phyphox 导出的传感器 csv（表头带引号，可能含空行）。"""
    rows = []
    with open(path, newline="") as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if len(row) < 4:
                continue
            try:
                rows.append([float(v) for v in row[:4]])
            except ValueError:
                continue
    return np.array(rows, dtype=float)


def sample_rate(t):
    return (len(t) - 1) / (t[-1] - t[0])


def load_record(path):
    """读一段记录，并把 201.6 Hz 的重力插值到 403.1 Hz 的加速度时间轴上。"""
    acc = read_sensor_csv(os.path.join(path, "Accelerometer.csv"))
    grav = read_sensor_csv(os.path.join(path, "Gravity.csv"))
    t = acc[:, 0]
    ax, ay, az = acc[:, 1], acc[:, 2], acc[:, 3]
    tg = grav[:, 0]
    gx = np.interp(t, tg, grav[:, 1])
    gy = np.interp(t, tg, grav[:, 2])
    gz = np.interp(t, tg, grav[:, 3])
    return t, ax, ay, az, gx, gy, gz


def moving_std(x, n):
    """长度不短于输入的滑动标准差（中心对齐，边界收缩）。"""
    pad = n // 2
    xp = np.pad(x, (pad, pad), mode="edge")
    c1 = np.convolve(xp, np.ones(n), "valid")
    c2 = np.convolve(xp * xp, np.ones(n), "valid")
    m = c1 / n
    var = np.maximum(c2 / n - m * m, 0.0)
    return np.sqrt(var)[: len(x)]


def clean(t, dyn_mag):
    """去掉采集启停造成的首尾异常，返回保留区间 [i, j)。

    规则 1（静止段）：两端 0.5 s 标准差低于全段中位数的 0.3 倍。只对含明显运动的
            记录启用（中位数 < 0.5 的静止记录本身就该保留）。
    规则 2（瞬态）：两端 0.5 s 标准差高于全段中位数的 3 倍，即拿起/放下手机。
    规则 3（保护带）：两端再各留 0.5 s。
    """
    n = len(dyn_mag)
    fs = sample_rate(t)
    nw = max(3, int(round(0.5 * fs)))
    msd = moving_std(dyn_mag, nw)
    med = float(np.median(msd))
    lo = STILL_FRAC * med if med > STILL_FLOOR else 0.0
    hi = TRANSIENT_K * med

    i, j = 0, n
    while i < j and (msd[i] < lo or msd[i] > hi):
        i += 1
    while j > i and (msd[j - 1] < lo or msd[j - 1] > hi):
        j -= 1

    guard = int(round(GUARD_S * fs))
    if j - i <= 2 * guard + 2:
        return 0, 0
    return i + guard, j - guard


def dominant_freq(x, fs, lo=0.8, hi=5.0):
    """0.8~5 Hz 内的频谱主峰（步频 / 摆臂频率）。"""
    n = len(x)
    y = (x - x.mean()) * np.hanning(n)
    power = np.abs(np.fft.rfft(y)) ** 2
    freqs = np.fft.rfftfreq(n, 1 / fs)
    m = (freqs >= lo) & (freqs <= hi)
    return float(freqs[m][int(np.argmax(power[m]))])


def window_features(t, ax, ay, az, gx, gy, gz):
    """单个窗口的姿态无关特征。"""
    gn = np.sqrt(gx * gx + gy * gy + gz * gz)
    ux, uy, uz = gx / gn, gy / gn, gz / gn

    a_v = ax * ux + ay * uy + az * uz - gn          # 竖向动态（扣掉 9.8）
    dx, dy, dz = ax - gx, ay - gy, az - gz           # 动态加速度向量
    dyn = np.sqrt(dx * dx + dy * dy + dz * dz)       # 动态幅值 |a - g|
    a_h = np.sqrt(np.maximum(dyn * dyn - a_v * a_v, 0.0))

    fs = sample_rate(t)
    return dict(
        fs=fs,
        n=len(t),
        std_mag=float(dyn.std()),
        p99=float(np.percentile(dyn, 99)),
        peak=float(dyn.max()),
        std_v=float(a_v.std()),
        std_h=float(a_h.std()),
        ratio=float(a_v.std() / (a_h.std() + 1e-9)),
        f_dom=dominant_freq(dyn, fs),
    )


def windows(t, ax, ay, az, gx, gy, gz, win_s, hop_s):
    fs = sample_rate(t)
    w = int(round(win_s * fs))
    h = int(round(hop_s * fs))
    k = 0
    while k + w <= len(t):
        sl = slice(k, k + w)
        yield k, window_features(t[sl], ax[sl], ay[sl], az[sl], gx[sl], gy[sl], gz[sl])
        k += h


def infer_truth(path):
    low = path.lower()
    for truth, keys in (("down", ("downstair",)), ("up", ("upstair",)),
                        ("run", ("run", "jog", "sprint")), ("walk", ("walk",)),
                        ("stand", ("stand", "static"))):
        if any(k in low for k in keys):
            return truth
    return "unknown"


def find_records(root):
    return sorted(cur for cur, _, files in os.walk(root) if "Accelerometer.csv" in files)


def _vals(rows, states, key):
    return np.array([r[key] for r in rows if r["state"] in states])


def _best_split(rows, low_states, high_states, key):
    """在 key 上找分开 low/high 的阈值：有空隙取空隙几何中点，重叠则取误判最少处。"""
    lo, hi = _vals(rows, low_states, key), _vals(rows, high_states, key)
    if lo.max() < hi.min():
        a, b = float(lo.max()), float(hi.min())
        return float(np.sqrt(a * b)) if a > 1e-9 else 0.5 * (a + b)
    grid = np.unique(np.concatenate([lo, hi]))
    grid = (grid[:-1] + grid[1:]) / 2
    err = np.array([np.sum(lo > t) + np.sum(hi <= t) for t in grid])
    cand = grid[err == err.min()]
    center = 0.5 * (np.median(lo) + np.median(hi))
    return float(cand[int(np.argmin(np.abs(cand - center)))])


def calibrate(rows):
    """按判决顺序逐级标定阈值（只用传入的窗口，便于留一记录验证）。"""
    missing = set(STATES) - {r["state"] for r in rows}
    if missing:
        raise ValueError("标定需要五类样本，缺少: %s" % ", ".join(sorted(missing)))
    return dict(
        stand=_best_split(rows, ("stand",), ("walk", "run", "up", "down"), "std_mag"),
        run_sd=_best_split(rows, ("walk", "up", "down"), ("run",), "std_mag"),
        run_peak=_best_split(rows, ("walk", "up", "down"), ("run",), "peak"),
        down_sv=_best_split(rows, ("walk", "up"), ("down",), "std_v"),
        up_p99=_best_split(rows, ("up",), ("walk",), "p99"),
    )


def classify(f, th):
    if f["std_mag"] < th["stand"]:
        return "stand"
    if f["std_mag"] > th["run_sd"] or f["peak"] > th["run_peak"]:
        return "run"
    if f["std_v"] > th["down_sv"]:
        return "down"
    if f["p99"] < th["up_p99"]:
        return "up"
    return "walk"


def collect(root, win_s, hop_s):
    rows = []
    for path in find_records(root):
        name = os.path.relpath(path, root)
        truth = infer_truth(name)
        t, ax, ay, az, gx, gy, gz = load_record(path)
        dyn = np.sqrt((ax - gx) ** 2 + (ay - gy) ** 2 + (az - gz) ** 2)
        i, j = clean(t, dyn)
        if j - i < 2:
            continue
        sl = slice(i, j)
        for k, f in windows(t[sl], ax[sl], ay[sl], az[sl], gx[sl], gy[sl], gz[sl], win_s, hop_s):
            f.update(record=name, state=truth, t0=float(t[i + k]))
            rows.append(f)
    return rows


def leave_one_record_out(rows):
    """留一记录检验：只有同类的记录 >= 2 段时才能留出（否则训练集没有该类样本）。

    满足条件的是 walk-1/2 与 run-1/2；stand / up / down 各只有 1 段，无法留出。
    """
    by_state = {}
    for r in rows:
        by_state.setdefault(r["state"], set()).add(r["record"])
    holdable = sorted(n for names in by_state.values() if len(names) >= 2 for n in names)
    hits = total = 0
    for name in holdable:
        train = [r for r in rows if r["record"] != name]
        th = calibrate(train)
        for r in rows:
            if r["record"] == name:
                total += 1
                hits += classify(r, th) == r["state"]
    return hits, total, holdable


def write_outputs(rows, th, root, win_s, hop_s, loro):
    os.makedirs(OUT, exist_ok=True)
    lines = ["阈值 (%s, %.0f s 窗 / %.1f s 步长):" % (root, win_s, hop_s)]
    for k, v in th.items():
        lines.append("  %-9s = %8.3f" % (k, v))
    lines.append("")

    fields = ["record", "state", "t0", "fs", "n", "std_mag", "p99", "peak",
              "std_v", "std_h", "ratio", "f_dom", "pred"]
    with open(os.path.join(OUT, "windows.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(r[k], 4) if isinstance(r[k], float) else r[k]) for k in fields})

    summary = []
    for name in sorted(set(r["record"] for r in rows)):
        v = [r for r in rows if r["record"] == name]
        votes = Counter(r["pred"] for r in v)
        majority = votes.most_common(1)[0][0]
        summary.append(dict(
            record=name, state=v[0]["state"], fs=v[0]["fs"], n_win=len(v),
            sd_med=float(np.median([r["std_mag"] for r in v])),
            sv_med=float(np.median([r["std_v"] for r in v])),
            ratio_med=float(np.median([r["ratio"] for r in v])),
            p99_med=float(np.median([r["p99"] for r in v])),
            peak_max=max(r["peak"] for r in v),
            fdom_med=float(np.median([r["f_dom"] for r in v])),
            hit=sum(1 for r in v if r["pred"] == r["state"]),
            majority=majority,
        ))
        lines.append("%-14s truth=%-5s windows=%3d correct=%3d acc=%.3f  votes=%-40s majority=%s"
                     % (name, v[0]["state"], len(v), summary[-1]["hit"],
                        summary[-1]["hit"] / len(v),
                        str({STATE_CN[k]: c for k, c in sorted(votes.items())}),
                        STATE_CN[majority]))

    correct = sum(s["hit"] for s in summary)
    total = sum(s["n_win"] for s in summary)
    rec_ok = sum(1 for s in summary if s["majority"] == s["state"])
    lines.append("")
    lines.append("窗口级总准确率: %d/%d = %.4f" % (correct, total, correct / total))
    lines.append("记录级（多数票）: %d/%d" % (rec_ok, len(summary)))
    if loro[1]:
        lines.append("留一记录（%s；重新标定阈值）: %d/%d = %.4f"
                     % (",".join(loro[2]), loro[0], loro[1], loro[0] / loro[1]))
    else:
        lines.append("留一记录：没有可留出的记录（每类都只有 1 段）")
    lines.append("")
    lines.append("混淆矩阵（行=真值，列=判决）:")
    lines.append("%-6s" % "" + "".join("%7s" % STATE_CN[s] for s in STATES))
    for a in STATES:
        row = [sum(1 for r in rows if r["state"] == a and r["pred"] == b) for b in STATES]
        lines.append("%-6s" % STATE_CN[a] + "".join("%7d" % v for v in row))

    with open(os.path.join(OUT, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        for s in summary:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items()})

    with open(os.path.join(OUT, "eval.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


def write_test_eval(th, root, win_s, hop_s):
    """用 data_2 标定的阈值（不重标定）在独立目录上逐段判决。"""
    rows = collect(root, win_s, hop_s)
    if not rows:
        raise SystemExit("在 %s 下没找到 Accelerometer.csv" % root)
    for r in rows:
        r["pred"] = classify(r, th)

    tag = os.path.basename(os.path.normpath(root))
    lines = ["独立测试集: %s（%d 个窗）" % (os.path.relpath(root, ROOT), len(rows)),
             "阈值来源: %s" % ", ".join("%s=%.3f" % (k, v) for k, v in th.items()), ""]
    summary = []
    for name in sorted(set(r["record"] for r in rows)):
        v = [r for r in rows if r["record"] == name]
        votes = Counter(r["pred"] for r in v)
        majority = votes.most_common(1)[0][0]
        hit = sum(1 for r in v if r["pred"] == r["state"])
        summary.append((name, v[0]["state"], len(v), hit, majority))
        lines.append("%-16s truth=%-5s windows=%3d correct=%3d acc=%.3f  votes=%-40s majority=%s"
                     % (name, v[0]["state"], len(v), hit, hit / len(v),
                        str({STATE_CN[k]: c for k, c in sorted(votes.items())}),
                        STATE_CN[majority]))

    total = sum(s[2] for s in summary)
    correct = sum(s[3] for s in summary)
    rec_ok = sum(1 for s in summary if s[4] == s[1])
    lines.append("")
    lines.append("窗口级总准确率: %d/%d = %.4f" % (correct, total, correct / total))
    lines.append("记录级（多数票）: %d/%d" % (rec_ok, len(summary)))
    lines.append("")
    lines.append("混淆矩阵（行=真值，列=判决）:")
    lines.append("%-6s" % "" + "".join("%7s" % STATE_CN[s] for s in STATES))
    for a in STATES:
        row = [sum(1 for r in rows if r["state"] == a and r["pred"] == b) for b in STATES]
        if any(row):
            lines.append("%-6s" % STATE_CN[a] + "".join("%7d" % v for v in row))

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "%s_eval.txt" % tag), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines))


def sweep(root, wins, hop_s):
    print("窗长对比（每档都重新标定阈值）:")
    for win_s in wins:
        rows = collect(root, win_s, hop_s)
        th = calibrate(rows)
        acc = sum(classify(r, th) == r["state"] for r in rows) / len(rows)
        n_rec = len(set(r["record"] for r in rows))
        print("  %.0f s 窗 / %.1f s 步长: %d 个窗（%d 段记录），准确率 %.4f"
              % (win_s, hop_s, len(rows), n_rec, acc))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/calib/data_2")
    ap.add_argument("--win", type=float, default=WIN_S)
    ap.add_argument("--hop", type=float, default=HOP_S)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--test", default=None, help="独立测试目录，用主目录标定的阈值直接判")
    a = ap.parse_args()

    root = a.dir if os.path.isabs(a.dir) else os.path.join(ROOT, a.dir)
    if a.sweep:
        sweep(root, (4.0, 6.0, 8.0, 10.0), a.hop)
        return

    rows = collect(root, a.win, a.hop)
    if not rows:
        raise SystemExit("在 %s 下没找到 Accelerometer.csv" % root)
    th = calibrate(rows)
    for r in rows:
        r["pred"] = classify(r, th)
    write_outputs(rows, th, os.path.relpath(root, ROOT), a.win, a.hop,
                  leave_one_record_out(rows))
    write_submission_csvs(root, os.path.join(ROOT, "output", "v2", "csv"))
    if a.test:
        test_root = a.test if os.path.isabs(a.test) else os.path.join(ROOT, a.test)
        write_test_eval(th, test_root, a.win, a.hop)


if __name__ == "__main__":
    main()
