#!/usr/bin/env python3
"""省电版 24 h 理论功耗推算（口径：5 V 输入侧）。

表只到 0.01 A，深睡与窗口/唤醒都测不出，所以窗口/唤醒用模型假设、深睡用手册 6 mA + 表上界给区间。

用法:
  python3 theory.py
  python3 theory.py --i-win 97 --i-wake 150 --t-wake 1.1
  python3 theory.py --json
"""
import argparse
import json

DAY_S = 86400
DEFAULT_V = 4.9         # V，2026-11-10 USB 表实测 4.90 V（含表自身压降）
DEFAULT_I_WIN = 95.0      # mA，模型假设（未实测）；历史读数 0.09–0.10 A 只作参考，未作为阶段均值
DEFAULT_T_WIN = 900.0     # s，冷启动后 WiFi/网页窗口 15 分钟
DEFAULT_I_WAKE = 145.0    # mA，模型假设（未实测）；历史连拍 0.13–0.16 A 为模型/探针推断
DEFAULT_T_WAKE = 1.4      # s，模型假设（未实测）；串口观察 18:48:34.726→18:48:36.080 只作参考
DEFAULT_WAKES = 24        # 次/天，其余时段每小时唤醒拍照一次
DEFAULT_I_SLEEP = 6.0     # mA，官方 ESP32-CAM 数据手册 Deep-Sleep 6 mA @5V；旧 5 mA 仅 AMS1117 静态模型，可用 --i-sleep 5 复现
DEFAULT_I_SLEEP_MAX = 10.0  # mA，表分辨率 0.01 A 给出的上界
DEFAULT_BATTERY_MAH = 2000.0  # 方案口径
DEFAULT_DOD = 0.8


def charge_mah(i_ma, t_s):
    """i_ma 是 5 V 输入侧电流，直接积分得 mAh。"""
    return i_ma * t_s / 3600.0


def compute_budget(v=DEFAULT_V, i_win=DEFAULT_I_WIN, t_win=DEFAULT_T_WIN,
                   i_wake=DEFAULT_I_WAKE, t_wake=DEFAULT_T_WAKE,
                   wakes=DEFAULT_WAKES, i_sleep=DEFAULT_I_SLEEP,
                   battery_mah=DEFAULT_BATTERY_MAH, dod=DEFAULT_DOD):
    """算一天的窗口段 / 唤醒段 / 深睡段与平均值；纯函数，方便复核与测试。"""
    if min(v, i_win, t_win, i_wake, t_wake, wakes, i_sleep,
           battery_mah, dod) < 0:
        raise ValueError("参数不能为负")

    t_wake_total = wakes * t_wake
    t_sleep = DAY_S - t_win - t_wake_total
    if t_sleep <= 0:
        raise ValueError("窗口 + 唤醒占满了 24 h，参数不对")

    e_win = charge_mah(i_win, t_win)
    e_wake = charge_mah(i_wake, t_wake_total)
    e_sleep = charge_mah(i_sleep, t_sleep)
    total_mah = e_win + e_wake + e_sleep
    usable_mah = battery_mah * dod
    avg_ma = total_mah / 24.0

    return {
        "v": v,
        "t_wake_total_s": t_wake_total,
        "t_sleep_s": t_sleep,
        "win_mah": e_win,
        "wake_mah": e_wake,
        "sleep_mah": e_sleep,
        "total_mah": total_mah,
        "total_wh": total_mah * v / 1000.0,
        "avg_ma": avg_ma,
        "usable_mah": usable_mah,
        "runtime_days": usable_mah / avg_ma / 24.0 if avg_ma else float("inf"),
    }


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
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    a = ap.parse_args()

    common = dict(v=a.v, i_win=a.i_win, t_win=a.t_win, i_wake=a.i_wake,
                  t_wake=a.t_wake, wakes=a.wakes,
                  battery_mah=a.battery_mah, dod=a.dod)
    b = compute_budget(i_sleep=a.i_sleep, **common)
    bmax = compute_budget(i_sleep=a.i_sleep_max, **common)

    if a.json:
        print(json.dumps({"set": b, "max": bmax}, ensure_ascii=False, indent=2))
        return

    print("输入: V=%.2f V  I_win=%.0f mA×%.0f s  I_wake=%.0f mA×%.1f s×%d 次/天"
          % (a.v, a.i_win, a.t_win, a.i_wake, a.t_wake, a.wakes))
    print("      深睡 %.0f s/天，实测上界 %.0f mA，设定 %.0f mA"
          % (b["t_sleep_s"], a.i_sleep_max, a.i_sleep))
    print()
    print("段能量:")
    print("  窗口段  %8.2f mAh  %5.3f Wh" % (b["win_mah"], b["win_mah"] * a.v / 1000))
    print("  唤醒段  %8.2f mAh  %5.3f Wh" % (b["wake_mah"], b["wake_mah"] * a.v / 1000))
    print("  深睡    %8.2f mAh  %5.3f Wh（按设定）" % (b["sleep_mah"], b["sleep_mah"] * a.v / 1000))
    print("          %8.2f mAh  %5.3f Wh（表上界）"
          % (bmax["sleep_mah"], bmax["sleep_mah"] * a.v / 1000))
    print()
    for label, x in (("设定", b), ("表上界", bmax)):
        print("24 h 合计（%s）: %7.1f mAh  %5.2f Wh  平均 %5.2f mA  "
              "续航 %.1f 天（按 %.0f mAh 可用）"
              % (label, x["total_mah"], x["total_wh"], x["avg_ma"],
                 x["runtime_days"], x["usable_mah"]))


if __name__ == "__main__":
    main()
