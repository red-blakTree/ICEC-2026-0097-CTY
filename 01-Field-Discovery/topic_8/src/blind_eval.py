#!/usr/bin/env python3
"""课题 08 通用盲测脚本：一条命令评估 v2 / v3 / v4 / v5，不用改代码。

标定集与测试集都用命令行传：
    --calib       v4/v5 的标定目录（默认 data/calib/data_2 + data/calib/2026-10-24）
    --calib-v23   v2/v3 的标定目录（默认只用 data/calib/data_2，保持原协议）
    --test        测试目录（目录下每段一个子目录，含 Accelerometer.csv / Gravity.csv）

示例：
    MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/blind_eval.py \
        --test data/blind/2026-10-25 --out output/blind_2026-10-25

    # 新采一天（本人）：
    MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/blind_eval.py \
        --test data/blind/2026-10-26 --out output/reports/blind_2026-10-26

输出：
    <out>/report.txt     逐方法、逐记录、逐类、混淆矩阵、置信区间
    <out>/windows.csv    每个测试窗的 v5 特征 + 四个版本的判决

说明：
  - 测试集不参与任何阈值/权重选择；脚本不会读写测试集的标签以外的信息。
  - v2/v3 用 8 s 窗 / 1 s 步长（与其原实现一致）；v4/v5 固定 8 s 窗 / 1 s 步长。
  - 状态真值从目录名推断（walk/run/upstairs/downstairs/stand），未知目录会被跳过并提示。
"""
import argparse
import csv
import os
import sys
from collections import Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
for sub in ("v2", "v3", "v4", "v5", "v6"):
    sys.path.insert(0, os.path.join(HERE, sub))

import gait_analysis_v2 as v2  # noqa: E402
import gait_analysis_v3 as v3  # noqa: E402
import gait_analysis_v4 as v4  # noqa: E402
import gait_analysis_v5 as v5  # noqa: E402
import features as v6f  # noqa: E402
import model as v6m  # noqa: E402

ROOT = v2.ROOT
STATES = ("stand", "walk", "run", "up", "down")
CN = v2.STATE_CN
WIN_S, HOP_S = 8.0, 1.0
BOOT = 2000
STRIDE = 8
DEFAULT_CALIB = ("data/calib/data_2", "data/calib/2026-10-24")
DEFAULT_CALIB_V23 = ("data/calib/data_2",)


def resolve(path):
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def tag(rows, name):
    for r in rows:
        r["dataset"] = name
    return rows


def collect_v2(path):
    return tag(v2.collect(path, WIN_S, HOP_S), os.path.basename(os.path.normpath(path)))


def collect_v4(path):
    return tag(v4.collect(path), os.path.basename(os.path.normpath(path)))


def collect_v5(path, prefix):
    return v5.collect(path, "%s:%s" % (prefix, os.path.basename(os.path.normpath(path))))


def collect_v6(path, prefix):
    return v6f.collect(path, "%s:%s" % (prefix, os.path.basename(os.path.normpath(path))))


def check_calib(rows, label):
    missing = [s for s in STATES if not any(r["state"] == s for r in rows)]
    if missing:
        raise SystemExit("标定集 %s 缺少类别 %s，无法标定。请用 --calib/--calib-v23 补全。"
                         % (label, ", ".join(missing)))


def read_meta(test_dir):
    """从测试集 meta/ 里读设备型号与最早 START，仅用于报告标识。"""
    model = "?"
    starts = []
    for cur, _, files in os.walk(test_dir):
        if model == "?" and "device.csv" in files:
            try:
                with open(os.path.join(cur, "device.csv"), newline="") as f:
                    for row in csv.DictReader(f):
                        if row.get("property") == "deviceModel":
                            model = row.get("value", "?")
                            break
            except Exception:
                pass
        if "time.csv" in files:
            try:
                with open(os.path.join(cur, "time.csv"), newline="") as f:
                    for row in csv.DictReader(f):
                        if row.get("event") == "START" and row.get("system time text"):
                            starts.append(row["system time text"])
            except Exception:
                pass
    return model, (min(starts) if starts else "?")


def wilson(k, n, z=1.959964):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, center - half), min(1.0, center + half)


def macro_f1(rows, key):
    truth = [r["state"] for r in rows]
    pred = [r[key] for r in rows]
    f1s = []
    for c in sorted(set(truth)):
        tp = sum(a == c and b == c for a, b in zip(truth, pred))
        fp = sum(a != c and b == c for a, b in zip(truth, pred))
        fn = sum(a == c and b != c for a, b in zip(truth, pred))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return float(np.mean(f1s)) if f1s else 0.0


def per_class(rows, key):
    out = {}
    for s in STATES:
        v = [r for r in rows if r["state"] == s]
        if v:
            out[s] = sum(r[key] == s for r in v) / len(v)
    return out


def record_correct(rows, key):
    hit = 0
    n = 0
    for name in sorted({r["record"] for r in rows}):
        v = [r for r in rows if r["record"] == name]
        major = Counter(r[key] for r in v).most_common(1)[0][0]
        hit += major == v[0]["state"]
        n += 1
    return hit, n


def record_bootstrap(rows, key, b=BOOT, seed=0):
    by = {}
    for r in rows:
        by.setdefault(r["record"], []).append(r)
    names = sorted(by)
    if len(names) < 2:
        acc = sum(r[key] == r["state"] for r in rows) / len(rows)
        return acc, acc
    rng = np.random.default_rng(seed)
    accs = []
    for _ in range(b):
        idx = rng.integers(0, len(names), len(names))
        hit = tot = 0
        for i in idx:
            for r in by[names[i]]:
                tot += 1
                hit += r[key] == r["state"]
        accs.append(hit / tot)
    lo, hi = np.percentile(accs, [2.5, 97.5])
    return float(lo), float(hi)


def stride_rows(rows, stride=STRIDE):
    out = []
    for name in sorted({r["record"] for r in rows}):
        v = sorted((r for r in rows if r["record"] == name), key=lambda r: r["t0"])
        out.extend(v[::stride])
    return out


def fmt_th(name, th):
    keys = [k for k in th if isinstance(th[k], (int, float))]
    return "%s: %s" % (name, ", ".join("%s=%.3f" % (k, th[k]) for k in keys))


def evaluate(test_rows, test_key):
    """返回 (窗口级准确率, macroF1, Wilson, bootstrap, 记录级, 去重叠, 逐类)。"""
    hit = sum(r[test_key] == r["state"] for r in test_rows)
    n = len(test_rows)
    acc = hit / n
    lo, hi = wilson(hit, n)
    blo, bhi = record_bootstrap(test_rows, test_key)
    rh, rn = record_correct(test_rows, test_key)
    srows = stride_rows(test_rows)
    sacc = sum(r[test_key] == r["state"] for r in srows) / len(srows)
    return dict(acc=acc, f1=macro_f1(test_rows, test_key), wilson=(lo, hi),
                boot=(blo, bhi), rec=(rh, rn), stride=sacc, per=per_class(test_rows, test_key))


def main():
    ap = argparse.ArgumentParser(description="v2/v3/v4/v5 通用盲测")
    ap.add_argument("--test", required=True, help="测试目录（每段一个子目录）")
    ap.add_argument("--calib", nargs="+", default=list(DEFAULT_CALIB),
                    help="v4/v5 标定目录，默认 data_2 + data/calib/2026-10-24")
    ap.add_argument("--calib-v23", nargs="+", default=list(DEFAULT_CALIB_V23),
                    help="v2/v3 标定目录，默认只用 data_2")
    ap.add_argument("--out", default=None, help="输出目录，默认 output/blind_<测试目录名>")
    a = ap.parse_args()

    test_dir = resolve(a.test)
    if not os.path.isdir(test_dir):
        raise SystemExit("测试目录不存在：%s" % test_dir)
    calib = [resolve(p) for p in a.calib]
    calib_v23 = [resolve(p) for p in a.calib_v23]
    tp = os.path.abspath(test_dir)
    for p in calib + calib_v23:
        if not os.path.isdir(p):
            raise SystemExit("标定目录不存在：%s" % p)
        cp = os.path.abspath(p)
        if cp == tp or cp.startswith(tp + os.sep) or tp.startswith(cp + os.sep):
            raise SystemExit("标定目录 %s 与测试目录 %s 互相包含，会泄漏标签；请换一个互不包含的目录。" % (p, test_dir))

    test_name = os.path.basename(os.path.normpath(test_dir))
    out_dir = resolve(a.out) if a.out else os.path.join(ROOT, "output", "reports", "blind_" + test_name)
    os.makedirs(out_dir, exist_ok=True)

    # 标定
    c23 = []
    for p in calib_v23:
        c23 += collect_v2(p)
    check_calib(c23, "v2/v3")
    c45_v4 = []
    for p in calib:
        c45_v4 += collect_v4(p)
    check_calib(c45_v4, "v4")
    c45_v5 = []
    for p in calib:
        c45_v5 += collect_v5(p, "calib")
    check_calib(c45_v5, "v5")
    c6 = []
    for p in calib:
        c6 += collect_v6(p, "calib")
    check_calib(c6, "v6")

    th2, th3 = v2.calibrate(c23), v3.calibrate(c23)
    th4 = v4.calibrate(c45_v4)
    th5 = v5.calibrate(c45_v5)
    th6 = v6m.calibrate(c6)

    # 测试集：v2/v3、v4、v5 分别取各自特征
    t2 = collect_v2(test_dir)
    t2 = [r for r in t2 if r["state"] in STATES]
    if not t2:
        raise SystemExit("测试集没有可识别的记录（目录名需含 walk/run/upstairs/downstairs/stand）。")
    for r in t2:
        r["m2"] = v2.classify(r, th2)
        r["m3"] = v3.classify(r, th3)
        r["pred"] = r["m3"]
    v3.smooth(t2)
    for r in t2:
        r["m3s"] = r["pred_smooth"]
        r["m2s"] = r["m2"]  # v2 没有平滑，保留原始判决

    t4 = [r for r in collect_v4(test_dir) if r["state"] in STATES]
    for r in t4:
        r["m4"] = v4.classify(r, th4)
        r["pred"] = r["m4"]
    v4.smooth(t4)
    for r in t4:
        r["m4s"] = r["pred_smooth"]

    th51 = v5.calibrate(c45_v5, "rob_skew")

    t5 = [r for r in collect_v5(test_dir, "test") if r["state"] in STATES]
    for r in t5:
        r["m5"] = v5.classify(r, th5)
        r["pred"] = r["m5"]
    v5.smooth(t5)
    for r in t5:
        r["m5s"] = r["pred_smooth"]
        r["m51"] = v5.classify(r, th51)
        r["pred"] = r["m51"]
    v5.smooth(t5)
    for r in t5:
        r["m51s"] = r["pred_smooth"]

    t6 = [r for r in collect_v6(test_dir, "test") if r["state"] in STATES]
    v6m.run(t6, th6, "viterbi", v6m.DEFAULT_PENALTY)
    for r in t6:
        r["m6"] = r["pred"]
        r["m6s"] = r["pred_smooth"]

    # 方法 -> (rows, 预测字段)
    methods = [("v2", t2, "m2s"), ("v3+平滑", t2, "m3s"),
               ("v4+平滑", t4, "m4s"), ("v5+平滑", t5, "m5s"),
               ("v5.1+平滑", t5, "m51s"), ("v6", t6, "m6s")]
    model, start = read_meta(test_dir)
    recs = sorted({r["record"] for r in t5})
    counts = Counter(r["state"] for r in t5)

    lines = [
        "盲测评估：%s" % test_dir,
        "设备：%s；最早 START：%s" % (model, start),
        "标定（v2/v3）：%s" % ", ".join(os.path.relpath(p, ROOT) for p in calib_v23),
        "标定（v4/v5）：%s" % ", ".join(os.path.relpath(p, ROOT) for p in calib),
        "测试：%d 窗 / %d 段；%s" % (
            len(t5), len(recs), "，".join("%s %d" % (CN[s], counts[s]) for s in STATES if counts[s])),
        "",
        fmt_th("v2", th2),
        fmt_th("v3", th3),
        fmt_th("v4", th4),
        "v5: stand=%.3f, run=%.3f, ptn=%.3f, up_score=%.3f"
        % (th5["stand"], th5["run"], th5["down"], th5["up"]),
        "v5.1: down(rob_skew)=%.3f；v6: down(rob_skew)=%.3f, 解码 penalty=%.1f"
        % (th51["down"], th6["down"], v6m.DEFAULT_PENALTY),
        "",
        "%-8s %7s %8s  %-14s %-16s %7s %8s" % (
            "方法", "窗口级", "macroF1", "Wilson 95%", "记录bootstrap 95%", "记录级", "去重叠"),
    ]
    stats = {}
    for label, rows, key in methods:
        st = evaluate(rows, key)
        stats[label] = st
        lines.append("%-8s %6.1f%% %8.3f  [%5.1f, %5.1f]  [%5.1f, %5.1f] %5d/%-2d %7.1f%%" % (
            label, 100 * st["acc"], st["f1"],
            100 * st["wilson"][0], 100 * st["wilson"][1],
            100 * st["boot"][0], 100 * st["boot"][1],
            st["rec"][0], st["rec"][1], 100 * st["stride"]))

    lines += ["", "逐记录窗口准确率：", "%-22s %-5s %5s" % ("记录", "真值", "窗数")
              + "".join("%9s" % l.split("+")[0] for l, _, _ in methods)]
    for name in recs:
        v5rows = [r for r in t5 if r["record"] == name]
        cells = []
        for label, rows, key in methods:
            v = [r for r in rows if r["record"] == name]
            cells.append("%8.1f%%" % (100 * sum(r[key] == r["state"] for r in v) / len(v)))
        lines.append("%-22s %-5s %5d" % (name, CN[v5rows[0]["state"]], len(v5rows)) + "".join(cells))

    lines += ["", "逐类召回：", "%-8s %s" % ("方法", "  ".join("%6s" % CN[s] for s in STATES))]
    for label, _, _ in methods:
        per = stats[label]["per"]
        lines.append("%-8s %s" % (label, "  ".join(
            "%5.1f%%" % (100 * per[s]) if s in per else "     —" for s in STATES)))

    lines += ["", "v5 混淆矩阵（行=真值，列=判决）：", "%-6s" % "" + "".join("%7s" % CN[s] for s in STATES)]
    for a_ in STATES:
        row = [sum(1 for r in t5 if r["state"] == a_ and r["m5s"] == b) for b in STATES]
        lines.append("%-6s" % CN[a_] + "".join("%7d" % x for x in row))

    lines += ["", "注：窗口级数字按 8 s 窗 / 1 s 步长统计，相邻窗重叠 7/8；"
                  "记录级 = 每段多数票；去重叠 = 每段每 %d 窗取 1 窗。" % STRIDE]

    with open(os.path.join(out_dir, "report.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))

    # 逐窗 CSV：以 v5 行为主，合并另外三版的判决
    key = lambda r: (r["record"], round(r["t0"], 4))
    p2 = {key(r): r["m2s"] for r in t2}
    p3 = {key(r): r["m3s"] for r in t2}
    p4 = {key(r): r["m4s"] for r in t4}
    p51 = {key(r): r["m51s"] for r in t5}
    p6 = {key(r): r["m6s"] for r in t6}
    fields = ["record", "state", "t0", "bias", "n_steps", "cadence", "i_cv",
              "sigma", "pt_raw", "ptn", "rob_skew", "acp", "zcr",
              "pred_v2", "pred_v3", "pred_v4", "pred_v5", "pred_v51", "pred_v6"]
    with open(os.path.join(out_dir, "windows.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in t5:
            w.writerow({
                "record": r["record"], "state": r["state"], "t0": round(r["t0"], 4),
                "bias": round(r["bias"], 4), "n_steps": r["n_steps"],
                "cadence": round(r["cadence"], 4), "i_cv": round(r["i_cv"], 4),
                "sigma": round(r["sigma"], 4), "pt_raw": round(r["pt_raw"], 4),
                "ptn": round(r["ptn"], 4), "rob_skew": round(r["rob_skew"], 4),
                "acp": round(r["acp"], 4), "zcr": round(r["zcr"], 4),
                "pred_v2": p2.get(key(r), ""), "pred_v3": p3.get(key(r), ""),
                "pred_v4": p4.get(key(r), ""), "pred_v5": r["m5s"],
                "pred_v51": p51.get(key(r), ""), "pred_v6": p6.get(key(r), ""),
            })
    print("\n输出：%s" % out_dir)


if __name__ == "__main__":
    main()
