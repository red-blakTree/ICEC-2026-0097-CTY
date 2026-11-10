#!/usr/bin/env python3
"""省电版 24 h 理论功耗推算（口径：5 V 输入侧）。

表只到 0.01 A，深睡电流测不出，所以只把「窗口段」「唤醒拍照段」的实测值代进来，
深睡项用模型值 + 表上界给区间。

用法:
  python3 theory.py
  python3 theory.py --i-win 97 --i-wake 150 --t-wake 1.1
"""
import argparse

DAY_S = 86400
DEFAULT_V = 5.0
DEFAULT_I_WIN = 95.0      # mA，2026-11-10 实测「窗口空闲」0.09–0.10 A；开着网页刷页面会到 0.12–0.19 A
DEFAULT_T_WIN = 900.0     # s，冷启动后 WiFi/网页窗口 15 分钟
DEFAULT_I_WAKE = 145.0    # mA，2026-11-10 /capture 连拍实测 0.13–0.16 A（含 WiFi 空闲，偏保守）
DEFAULT_T_WAKE = 1.4      # s，单次唤醒（复位→入睡），30 s 固件实测 18:02:34.757→18:02:36.123
DEFAULT_WAKES = 24        # 次/天，其余时段每小时唤醒拍照一次
DEFAULT_I_SLEEP = 5.0     # mA，模型值（AMS1117 静态电流主导）
DEFAULT_I_SLEEP_MAX = 10.0  # mA，表分辨率 0.01 A 给出的上界
DEFAULT_BATTERY_MAH = 2000.0  # 方案口径
DEFAULT_DOD = 0.8


def charge_mah(i_ma, t_s):
    """i_ma 是 5 V 输入侧电流，直接积分得 mAh。"""
    return i_ma * t_s / 3600.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v", type=float, default=DEFAULT_V)
    ap.add_argument("--i-win", type=float, default=DEFAULT_I_WIN)
    ap.add_argument("--t-win", type=float, default=DEFAULT_T_WIN)
    ap.add_argument("--i-wake", type=float, default=DEFAULT_I_WAKE)
    ap.add_argument("--t-wake", type=float, default=DEFAULT_T_WAKE)
    ap.add_argument("--wakes", type=int, default=DEFAULT_WAKES)
    ap.add_argument("--i-sleep", type=float, default=DEFAULT_I_SLEEP)
    ap.add_argument("--i-sleep-max", type=float, default=DEFAULT_I_SLEEP_MAX)
    ap.add_argument("--battery-mah", type=float, default=DEFAULT_BATTERY_MAH)
    ap.add_argument("--dod", type=float, default=DEFAULT_DOD)
    a = ap.parse_args()

    t_wake_total = a.wakes * a.t_wake
    t_sleep = DAY_S - a.t_win - t_wake_total
    if t_sleep <= 0:
        raise SystemExit("错误: 窗口 + 唤醒占满了 24 h，参数不对")

    e_win = charge_mah(a.i_win, a.t_win)
    e_wake = charge_mah(a.i_wake, t_wake_total)
    e_sleep = charge_mah(a.i_sleep, t_sleep)
    e_sleep_max = charge_mah(a.i_sleep_max, t_sleep)

    usable = a.battery_mah * a.dod
    print("输入: V=%.2f V  I_win=%.0f mA×%.0f s  I_wake=%.0f mA×%.1f s×%d 次/天"
          % (a.v, a.i_win, a.t_win, a.i_wake, a.t_wake, a.wakes))
    print("      深睡 %.0f s/天，实测上界 %.0f mA，模型 %.0f mA"
          % (t_sleep, a.i_sleep_max, a.i_sleep))
    print()
    print("段能量:")
    print("  窗口段  %8.2f mAh  %5.3f Wh" % (e_win, e_win * a.v / 1000))
    print("  唤醒段  %8.2f mAh  %5.3f Wh" % (e_wake, e_wake * a.v / 1000))
    print("  深睡    %8.2f mAh  %5.3f Wh（模型）" % (e_sleep, e_sleep * a.v / 1000))
    print("          %8.2f mAh  %5.3f Wh（表上界）" % (e_sleep_max, e_sleep_max * a.v / 1000))
    print()
    for label, e in (("模型", e_win + e_wake + e_sleep),
                     ("表上界", e_win + e_wake + e_sleep_max)):
        avg = e / 24.0
        print("24 h 合计（%s）: %7.1f mAh  %5.2f Wh  平均 %5.2f mA  "
              "续航 %.1f 天（按 %.0f mAh 可用）"
              % (label, e, e * a.v / 1000, avg, usable / avg / 24, usable))


if __name__ == "__main__":
    main()
