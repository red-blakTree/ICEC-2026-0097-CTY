#!/usr/bin/env python3
"""课题 08 盲测：v2 / v3 / v4 在指定测试目录上的对比 + 数据独立性检查。

训练：v2 / v3 用 data/calib/data_2；v4 用 data/calib/data_2 + data_routine（均本人）
测试：默认 data/blind/2026-10-25（本人，9 段 704 窗，PKG110），不参与任何标定

v2：绝对能量（σ_v / p99）
v3：f_dom / r + ±2 窗平滑
v4：峰/谷检测 + acp 阈值 + ±2 窗平滑

输出：<out>/report.txt、<out>/blind_test.png
用法：
    MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/blind_test.py
    MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/blind_test.py --test data/blind/2026-10-26 --out output/reports/blind_2026-10-26
"""
import argparse
import csv
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager, rcParams

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "v2"))
sys.path.insert(0, os.path.join(HERE, "v3"))
sys.path.insert(0, os.path.join(HERE, "v4"))

import gait_analysis_v2 as v2  # noqa: E402
import gait_analysis_v3 as v3  # noqa: E402
import gait_analysis_v4 as v4  # noqa: E402

ROOT = v2.ROOT
TRAIN = os.path.join(ROOT, "data", "calib", "data_2")
# 2026-10-25 起 data_routine 下多了一个日期；旧脚本的标定/对照仍只用 10-24。
ROUTINE = os.path.join(ROOT, "data", "calib", "2026-10-24")
DEFAULT_TEST = os.path.join(ROOT, "data", "blind", "2026-10-25")
DEFAULT_OUT = os.path.join(ROOT, "output", "reports", "blind_test")
ORDER = ["stand", "walk", "run", "up", "down"]
CJK = "/run/host/usr/share/fonts/google-droid-sans-fonts/DroidSansFallbackFull.ttf"


def setup(out_dir):
    if os.path.exists(CJK):
        font_manager.fontManager.addfont(CJK)
        rcParams["font.family"] = ["DejaVu Sans", "Droid Sans Fallback"]
    rcParams["axes.unicode_minus"] = False
    rcParams["figure.dpi"] = 130
    rcParams["savefig.dpi"] = 130
    rcParams["axes.grid"] = True
    rcParams["grid.alpha"] = 0.25
    os.makedirs(out_dir, exist_ok=True)


def acc_span(path):
    """加速度文件的时间跨度（s），用于估计记录的绝对结束时间。"""
    first = last = None
    with open(path, newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if not row:
                continue
            try:
                t = float(row[0])
            except ValueError:
                continue
            if first is None:
                first = t
            last = t
    return (last - first) if first is not None else 0.0


def read_meta(record_dir):
    """返回 (deviceModel, START 系统时间戳, START 文本, 加速度段时长 s)。"""
    dev = start = text = None
    dev_path = os.path.join(record_dir, "meta", "device.csv")
    if os.path.exists(dev_path):
        with open(dev_path, newline="") as f:
            for row in list(csv.reader(f))[1:]:
                if len(row) >= 2 and row[0] == "deviceModel":
                    dev = row[1]
    time_path = os.path.join(record_dir, "meta", "time.csv")
    if os.path.exists(time_path):
        with open(time_path, newline="") as f:
            for row in list(csv.reader(f))[1:]:
                if len(row) >= 4 and row[0] == "START":
                    start, text = float(row[2]), row[3]
    return dev, start, text, acc_span(os.path.join(record_dir, "Accelerometer.csv"))


def describe(root):
    rows = []
    for path in v2.find_records(root):
        dev, start, text, span = read_meta(path)
        rows.append(dict(record=os.path.relpath(path, root), device=dev or "?",
                         start=start, end=(start + span) if start is not None else None,
                         text=text))
    return rows


def independence(test_dir, train_dirs):
    """检查测试集与训练集的设备、日期与采集时段是否独立。"""
    test = describe(test_dir)
    train = []
    for d in train_dirs:
        for r in describe(d):
            r["src"] = os.path.relpath(d, ROOT)
            train.append(r)
    days = sorted(set((r["text"] or "?")[:10] for r in test))
    test_dev = set(r["device"] for r in test)
    train_dev = set(r["device"] for r in train)
    lines = ["== 数据独立性检查 ==",
             "测试目录: %s（%d 段）" % (os.path.relpath(test_dir, ROOT), len(test)),
             "测试设备: %s" % "、".join(sorted(test_dev)),
             "测试采集日期: %s" % "、".join(days),
             "训练集设备: %s；%s" % (
                 "、".join(sorted(train_dev)),
                 "测试设备均未在训练集中出现" if not (test_dev & train_dev)
                 else "测试设备 %s 与训练集相同" % "、".join(sorted(test_dev & train_dev)))]
    overl = []
    for a in test:
        if a["start"] is None or a["end"] is None:
            continue
        for b in train:
            if b["start"] is None or b["end"] is None:
                continue
            ov = min(a["end"], b["end"]) - max(a["start"], b["start"])
            if ov > 0:
                overl.append((a["record"], b["src"], b["record"], ov))
    if overl:
        lines.append("结论：以下测试记录与训练记录时间重叠——不能当作跨日期/跨环境泛化：")
        for rec, src, trec, ov in overl:
            lines.append("  %-22s 与 %-24s 重叠 %6.1f s" % (rec, "%s/%s" % (src, trec), ov))
    else:
        lines.append("结论：与训练集（data_2 + data_routine）无时间重叠，可按跨日/跨时段盲测解读。")
    return lines


def predict(test_dir):
    train = v2.collect(TRAIN, 8.0, 1.0)
    test2 = v2.collect(test_dir, 8.0, 1.0)
    th2 = v2.calibrate(train)
    th3 = v3.calibrate(train)
    for r in test2:
        r["p2"] = v2.classify(r, th2)
        r["p3"] = v3.classify(r, th3)
        r["pred"] = r["p3"]
        r["dataset"] = "test"
    v3.smooth(test2)

    th4 = v4.calibrate(v4.collect(TRAIN) + v4.collect(ROUTINE))
    test4 = v4.collect(test_dir)
    for r in test4:
        r["p4"] = v4.classify(r, th4)
        r["pred"] = r["p4"]
        r["dataset"] = "test"
    v4.smooth(test4)
    return test2, test4, th2, th3, th4


def present_states(rows):
    return [s for s in ORDER if any(r["state"] == s for r in rows)]


def conf(rows, key, true_states):
    return np.array([[sum(1 for r in rows if r["state"] == a and r[key] == b) for b in ORDER]
                     for a in true_states])


def rec_acc(rows, key, name):
    v = [r for r in rows if r["record"] == name]
    return sum(r[key] == r["state"] for r in v) / len(v)


def rec_ok(rows, key):
    recs = sorted(set(r["record"] for r in rows))
    ok = 0
    for name in recs:
        v = [r for r in rows if r["record"] == name]
        votes = {}
        for r in v:
            votes[r[key]] = votes.get(r[key], 0) + 1
        ok += max(votes, key=votes.get) == v[0]["state"]
    return ok, len(recs)


def report(test2, test4, th2, th3, th4, label):
    lines = ["盲测：v2/v3 训练 data/calib/data_2；v4 训练 data_2 + data_routine；"
             "测试 %s（%d 段 %d 窗）" % (label, len(set(r["record"] for r in test2)), len(test2)), "",
             "v2 阈值: " + ", ".join("%s=%.3f" % (k, v) for k, v in th2.items()),
             "v3 阈值: " + ", ".join("%s=%.3f" % (k, v) for k, v in th3.items()),
             "v4 阈值: " + ", ".join("%s=%.3f" % (k, v) for k, v in th4.items()), ""]
    lines.append("%-14s %-5s %5s  %-13s %-13s %-13s %-13s"
                 % ("记录", "真值", "窗数", "v2", "v3 原始", "v3 平滑", "v4 平滑"))
    for name in sorted(set(r["record"] for r in test2)):
        v = [r for r in test2 if r["record"] == name]
        truth = v[0]["state"]
        lines.append("%-14s %-5s %5d  %-13s %-13s %-13s %-13s"
                     % (name, v2.STATE_CN[truth], len(v),
                        "%d/%d (%.1f%%)" % (sum(r["p2"] == truth for r in v), len(v),
                                            100 * rec_acc(test2, "p2", name)),
                        "%d/%d (%.1f%%)" % (sum(r["p3"] == truth for r in v), len(v),
                                            100 * rec_acc(test2, "p3", name)),
                        "%d/%d (%.1f%%)" % (sum(r["pred_smooth"] == truth for r in v), len(v),
                                            100 * rec_acc(test2, "pred_smooth", name)),
                        "%d/%d (%.1f%%)" % (sum(r["pred_smooth"] == truth for r in test4 if r["record"] == name),
                                            len(v), 100 * rec_acc(test4, "pred_smooth", name))))
    for rows, key, lab in ((test2, "p2", "v2"), (test2, "p3", "v3 原始"),
                           (test2, "pred_smooth", "v3 平滑"), (test4, "pred_smooth", "v4 平滑")):
        hit = sum(r[key] == r["state"] for r in rows)
        ok, n = rec_ok(rows, key)
        lines.append("")
        lines.append("%s 窗口级: %d/%d = %.4f" % (lab, hit, len(rows), hit / len(rows)))
        lines.append("%s 记录级: %d/%d" % (lab, ok, n))
    lines.append("")
    lines.append("v2 混淆矩阵（行=真值，列=判决）:")
    M2 = conf(test2, "p2", present_states(test2))
    lines.append("%-6s" % "" + "".join("%7s" % v2.STATE_CN[s] for s in ORDER))
    for i, a in enumerate(present_states(test2)):
        lines.append("%-6s" % v2.STATE_CN[a] + "".join("%7d" % x for x in M2[i]))
    lines.append("")
    lines.append("v4 混淆矩阵（行=真值，列=判决；平滑后）:")
    M4 = conf(test4, "pred_smooth", present_states(test4))
    lines.append("%-6s" % "" + "".join("%7s" % v2.STATE_CN[s] for s in ORDER))
    for i, a in enumerate(present_states(test4)):
        lines.append("%-6s" % v2.STATE_CN[a] + "".join("%7d" % x for x in M4[i]))
    return lines, M2, M4


def figure(test2, test4, M2, M4, out_dir, label):
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(19, 5.2),
                                     gridspec_kw={"width_ratios": [1.3, 1, 1]})
    names = sorted(set(r["record"] for r in test2))
    y = np.arange(len(names))
    series = [
        ("v2（σ_v/p99）", "#9e9e9e", -0.30, test2, "p2"),
        ("v3 原始（f_dom/r）", "#1f77b4", -0.10, test2, "p3"),
        ("v3 平滑", "#17becf", 0.10, test2, "pred_smooth"),
        ("v4 平滑（波形）", "#2ca02c", 0.30, test4, "pred_smooth"),
    ]
    for title, color, off, rows, key in series:
        vals = [rec_acc(rows, key, n) for n in names]
        bars = a1.barh(y + off, vals, 0.19, color=color, label=title)
        if "v4" in title:
            for b, v in zip(bars, vals):
                a1.text(v + 0.01, b.get_y() + b.get_height() / 2, "%.0f%%" % (100 * v),
                        va="center", fontsize=7, color="#2ca02c")
    a1.set_yticks(y)
    a1.set_yticklabels(names, fontsize=9)
    a1.invert_yaxis()
    a1.set_xlim(0, 1.05)
    a1.set_xlabel("窗口级准确率")
    a1.legend(fontsize=8, loc="lower right")
    a1.set_title("① 逐段准确率（v4 绿色）", fontsize=10)

    for ax, M, title in ((a2, M2, "② v2 混淆矩阵"), (a3, M4, "③ v4 混淆矩阵（平滑后）")):
        im = ax.imshow(M, cmap="Blues" if ax is a2 else "Greens", aspect="auto")
        for i in range(M.shape[0]):
            for j in range(M.shape[1]):
                ax.text(j, i, M[i, j], ha="center", va="center",
                        color="white" if M[i, j] > M.max() * 0.6 else "black", fontsize=9)
        ax.set_xticks(range(len(ORDER)))
        ax.set_xticklabels([v2.STATE_CN[s] for s in ORDER], fontsize=8)
        ax.set_yticks(range(M.shape[0]))
        ax.set_yticklabels([v2.STATE_CN[s] for s in present_states(test2)], fontsize=8)
        ax.set_xlabel("判决")
        ax.set_ylabel("真值")
        ax.set_title(title, fontsize=10)
        fig.colorbar(im, ax=ax, fraction=0.046)

    hit2 = sum(r["p2"] == r["state"] for r in test2) / len(test2)
    hit3 = sum(r["pred_smooth"] == r["state"] for r in test2) / len(test2)
    hit4 = sum(r["pred_smooth"] == r["state"] for r in test4) / len(test4)
    fig.suptitle("盲测：%s（%d 段 %d 窗）；v2 %.1f %% → v3 %.1f %% → v4 %.1f %%"
                 % (label, len(names), len(test2), 100 * hit2, 100 * hit3, 100 * hit4), fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "blind_test.png"))
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description="v2/v3/v4 盲测 + 数据独立性检查")
    ap.add_argument("--test", default=DEFAULT_TEST, help="测试目录（含 Accelerometer/Gravity/meta）")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出目录")
    a = ap.parse_args()
    test_dir = a.test if os.path.isabs(a.test) else os.path.join(ROOT, a.test)
    out_dir = a.out if os.path.isabs(a.out) else os.path.join(ROOT, a.out)
    label = os.path.relpath(test_dir, ROOT)
    setup(out_dir)

    indep = independence(test_dir, (TRAIN, ROUTINE))
    test2, test4, th2, th3, th4 = predict(test_dir)
    if not test2:
        raise SystemExit("在 %s 下没找到 Accelerometer.csv" % test_dir)
    lines, M2, M4 = report(test2, test4, th2, th3, th4, label)
    lines = indep + [""] + lines
    with open(os.path.join(out_dir, "report.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    figure(test2, test4, M2, M4, out_dir, label)
    print("\n已写入", out_dir)


if __name__ == "__main__":
    main()
