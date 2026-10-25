#!/usr/bin/env python3
"""课题 08 v6 不变性自检：把"物理上应该不变"变成可执行的断言。

背景：v5 的 `ptn=(mean(pv)-mean(tv))/(mean(pv)+mean(tv))` 看起来像"比例"，其实
对加性零偏不是不变的——峰抬 c、谷的绝对值降 c，ptn 随之改变。2026-10-25 的跨日
盲测里，这个残余零偏让 ptn 的类条件分布整体上移，窗口级准确率从 96 % 掉到 79.7 %
（README §8.6）。这个 bug 不需要更多数据就能发现，只需要一条"特征在 s→s+c 下必须
不变"的测试。v6 把它补上，并让它可执行：

    MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/v6/invariants.py

检查内容：
  1. 不变核 rob_skew / acp / zcr 在 s→s+c、s→a·s、s→a·s+c 下不变；
  2. rob_skew 在 s→−s 下变号（协变，下楼判据正是靠这个符号）；
  3. 明确声明的非不变量（std / sigma 一类绝对幅值）*确实会*随增益变化——
     如果哪天有人把它悄悄挪进不变核，这条会失败。

任何一条不满足就以非零码退出。
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from features import INVARIANT, ROOT, signal_features  # noqa: E402

RTOL = 1e-9
ATOL = 1e-12


def synthetic_gait(fs=400.0, dur=8.0, seed=0):
    """合成一段竖向加速度：步频 + 二次谐波 + 单侧冲击 + 噪声。"""
    rng = np.random.default_rng(seed)
    t = np.arange(int(fs * dur)) / fs
    step = 0.55
    phase = (t % step) / step
    s = (0.6 * np.sin(2 * np.pi * t / step)
         + 0.25 * np.sin(4 * np.pi * t / step + 1.0)
         - 0.9 * np.exp(-((phase - 0.08) / 0.03) ** 2))   # 落地冲击：单侧，负偏度
    return s + 0.05 * rng.standard_normal(len(t))


def real_signals():
    """从仓库里取几段真实竖向波形，覆盖走路/上楼/下楼/静止。"""
    from features import moving_average
    from gait_analysis_v2 import load_record

    root = os.path.join(ROOT, "data", "calib", "data_2")
    out = []
    for sub in ("walk-1", "go_upstairs", "go_downstairs", "stand"):
        path = os.path.join(root, sub)
        if not os.path.isdir(path):
            continue
        t, ax, ay, az, gx, gy, gz = load_record(path)
        gn = np.sqrt(gx * gx + gy * gy + gz * gz)
        a_v = ax * gx / gn + ay * gy / gn + az * gz / gn - gn
        fs = (len(t) - 1) / (t[-1] - t[0])
        s = moving_average(a_v, 0.08 * fs)
        start = int(1.0 * fs)
        out.append(("%s[1:9]s" % sub, s[start:start + int(8 * fs)]))
    return out


def check(signal, fs, label):
    base = signal_features(signal, fs)
    cases = [
        ("s + 37.5", signal + 37.5, 1.0),
        ("s x 2.5", signal * 2.5, 1.0),
        ("2.5s - 1.3", signal * 2.5 - 1.3, 1.0),
    ]
    failed = []
    print("-- %s" % label)
    for name, xformed, sign in cases:
        got = signal_features(xformed, fs)
        cells = []
        for key in INVARIANT:
            want = sign * base[key]
            ok = np.isclose(got[key], want, rtol=RTOL, atol=ATOL)
            cells.append("%s %s" % (key, "ok" if ok else "FAIL(%.6g vs %.6g)" % (got[key], want)))
            if not ok:
                failed.append((label, name, key))
        print("   %-12s %s" % (name, "  ".join(cells)))

    # 协变：s -> -s 时 rob_skew 反号，acp/zcr 不变
    neg = signal_features(-signal, fs)
    for key, want in (("rob_skew", -base["rob_skew"]), ("acp", base["acp"]), ("zcr", base["zcr"])):
        ok = np.isclose(neg[key], want, rtol=1e-6, atol=1e-6)
        print("   %-12s %s %s" % ("s -> -s", key, "ok" if ok else "FAIL"))
        if not ok:
            failed.append((label, "s -> -s", key))

    # 声明的非不变量必须真的不不变：std 随增益线性变化
    scaled = signal_features(signal * 2.5, fs)
    if np.isclose(scaled["std"], base["std"], rtol=1e-6):
        print("   %-12s std 未随增益变化：它不该被当作“不变”，声明与实现不一致" % "声明检查")
        failed.append((label, "declared-non-invariant", "std"))
    else:
        print("   %-12s std x%.3f（按声明变化，未混入不变核）"
              % ("声明检查", scaled["std"] / base["std"]))
    return failed


def main():
    fs = 400.0
    print("不变性自检：RTOL=%g" % RTOL)
    failed = []
    failed += check(synthetic_gait(fs), fs, "合成步态 (8 s, 400 Hz)")
    for label, sig in real_signals():
        if len(sig) > 32:
            failed += check(sig, fs, "真实波形 %s" % label)
    if failed:
        print("\n失败 %d 项：" % len(failed))
        for item in failed:
            print("  %s" % (item,))
        return 1
    print("\n全部通过：不变核在 s→s+c、s→a·s、s→a·s+c 下不变；rob_skew 在镜像下变号；"
          "非不变量仍按声明变化。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
