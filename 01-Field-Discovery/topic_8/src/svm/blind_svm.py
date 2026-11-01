#!/usr/bin/env python3
"""课题 08 v7：对“有真值的外部段目录”做盲测（换人/换机/换日复核）。

与 predict_svm.py 的区别：这里假定输入是带标签的段（目录名可推断真值），
因此输出窗口级 / 记录级 / 逐类 / 混淆矩阵，用于复核泛化；
predict_svm.py 面向无真值的新数据，只输出判决与概率。

真值由段目录名推断（walk/run/up/down/stand 或其英文变体，见 v6f.infer_truth）；
推断不出来的段直接报错，不静默跳过。

输出：output/svm/blind_<tag>/report.txt、windows.csv（含真值，供审计）
用法：MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/svm/blind_svm.py \
          --input data/blind/2026-10-25
"""
import argparse
import csv
import os
import sys
from collections import Counter, defaultdict

import joblib
import numpy as np
from sklearn.metrics import confusion_matrix, f1_score

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import baseline_compare as base  # noqa: E402
import svm_data  # noqa: E402

CN = base.CN


def read_device(seg):
    """段目录 meta/device.csv → “型号（品牌）”，缺失返回 unknown。"""
    path = os.path.join(seg, "meta", "device.csv")
    if not os.path.isfile(path):
        return "unknown"
    info = {}
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 2:
                info[row[0].strip('"')] = row[1].strip('"')
    model = info.get("deviceModel", "unknown")
    brand = info.get("deviceBrand", "")
    return "%s（%s）" % (model, brand) if brand else model


def drift_lines(train, rows, present):
    """换机/换持机方式时，看关键特征相对训练集同类的中位漂移（不参与判决）。"""
    lines = ["特征漂移（输入 vs 训练集同类中位数；不参与判决）"]
    lines.append("%-5s %12s %12s %8s %8s" % (
        "真值", "std/sigma·输入", "std/sigma·训练", "std比", "acp比"))
    for s in present:
        cur = [r for r in rows if r["state"] == s]
        ref = [r for r in train if r["state"] == s and "noswing" not in r["record"]]
        std_in = np.median([r["std"] for r in cur])
        std_tr = np.median([r["std"] for r in ref])
        sig_in = np.median([r["sigma"] for r in cur])
        sig_tr = np.median([r["sigma"] for r in ref])
        lines.append("%-5s %12.2f %12.2f %8.2f %8.2f" % (
            CN[s], std_in / sig_in, std_tr / sig_tr, std_in / std_tr,
            np.median([r["acp"] for r in cur]) / np.median([r["acp"] for r in ref])))
    lines.append("std/sigma 是竖向动态占比，随持机姿态变；v7 的 top 特征 sigma/std 含绝对幅值，"
                 "换机或换持机方式时最先漂移。")
    return lines


def main():
    ap = argparse.ArgumentParser(description="v7 带真值盲测：窗口级/记录级/逐类/混淆")
    ap.add_argument("--input", nargs="+", required=True, metavar="PATH",
                    help="含真值的外部段目录，或它们的上级目录（可多个）")
    args = ap.parse_args()

    model_path = os.path.join(base.OUT, "model_rbf.joblib")
    if not os.path.isfile(model_path):
        sys.exit("模型不存在：%s\n请先运行 src/svm/train_svm.py" % model_path)
    bundle = joblib.load(model_path)
    if bundle.get("feature_names") != list(base.FEATS):
        sys.exit("模型特征与当前脚本不一致：%r" % (bundle.get("feature_names"),))
    model, meta = bundle["pipeline"], bundle.get("meta", {})

    rows, segs = svm_data.collect_checked(args.input)
    bad = sorted({r["record"] for r in rows if r["state"] == "unknown"})
    if bad:
        sys.exit("这些段目录名推断不出真值：%s\n"
                 "请用 walk/run/up/down/stand（可带 -1 等后缀）命名段目录。" % "、".join(bad))
    n = len(rows)

    X = np.array([[r[f] for f in base.FEATS] for r in rows], dtype=float)
    pred = model.predict(X)
    proba = model.predict_proba(X)
    classes = list(model.classes_)
    y = np.array([r["state"] for r in rows])
    present = [s for s in base.STATES if s in set(y)]

    ok = int((pred == y).sum())
    lo, hi = base.wilson(ok, n)
    groups = defaultdict(list)
    for i, r in enumerate(rows):
        groups[(r["dataset"], r["record"])].append(i)
    rok = sum(Counter(pred[i] for i in idx).most_common(1)[0][0] == rows[idx[0]]["state"]
              for idx in groups.values())
    f1 = f1_score(y, pred, labels=present, average="macro", zero_division=0)

    devices = Counter()
    for _, _, seg, _ in segs:
        devices[read_device(seg)] += 1
    seg_path = {(d, r): seg for d, r, seg, _ in segs}
    train_device = meta.get("device", "unknown")

    out = os.path.join(base.OUT, "blind_" + os.path.basename(
        os.path.normpath(os.path.abspath(args.input[0]))))
    os.makedirs(out, exist_ok=True)

    lines = []
    lines.append("v7 盲测：%s（RBF-SVM，v6 特征，8 s 窗 / 1 s 步长）" % args.input[0])
    lines.append("模型：%s（训练 %s，%d 段 %d 窗；训练设备 %s）" % (
        os.path.relpath(model_path, base.ROOT), "、".join(meta.get("days", [])),
        meta.get("n_records", 0), meta.get("n_windows", 0), train_device))
    lines.append("输入：%s" % "，".join(os.path.abspath(p) for p in args.input))
    lines.append("段数 %d，窗数 %d；输入设备：%s" % (
        len(groups), n, "，".join("%s×%d" % (k, v) for k, v in devices.items())))
    if train_device != "unknown" and set(devices) != {train_device}:
        lines.append("输入设备与训练设备不同：本次是换人/换机复核，窗口级不能当同设备泛化数字。")
        drift = drift_lines(base.load(), rows, present)
    else:
        drift = None
    lines.append("真值由段目录名推断；记录级 = 每段多数票；macro-F1 按实际出现的 %d 类计算。"
                 % len(present))
    lines.append("")
    lines.append("窗口级 %.1f%%（%d/%d），Wilson 95%% [%.1f, %.1f]；记录级 %d/%d；macroF1 %.3f"
                 % (100.0 * ok / n, ok, n, 100 * lo, 100 * hi, rok, len(groups), f1))
    lines.append("")
    lines.append("逐段：")
    lines.append("%-14s %-5s %5s %8s %-6s %5s %8s %s" % (
        "记录", "真值", "窗数", "窗口级", "多数票", "对错", "平均P", "设备"))
    for (day, record), idx in groups.items():
        truth = rows[idx[0]]["state"]
        votes = Counter(pred[i] for i in idx)
        maj, cnt = votes.most_common(1)[0]
        acc = sum(pred[i] == truth for i in idx) / len(idx)
        p_maj = float(proba[idx, classes.index(maj)].mean())
        dev = read_device(seg_path[(day, record)])
        lines.append("%-14s %-5s %5d %8.1f%% %-6s %5s %8.3f %s" % (
            record, CN[truth], len(idx), 100 * acc, CN[maj],
            "对" if maj == truth else "错", p_maj, dev))
    lines.append("")

    M = confusion_matrix(y, pred, labels=present)
    lines.append("窗口级混淆矩阵（行=真值，列=判决）")
    lines.append("%-6s" % "" + "".join("%7s" % CN[s] for s in present))
    for i, a in enumerate(present):
        lines.append("%-6s" % CN[a] + "".join("%7d" % x for x in M[i]))
    rec = ["%s %.1f%%" % (CN[s], 100 * M[i, i] / M[i].sum())
           for i, s in enumerate(present)]
    lines.append("逐类召回：" + "，".join(rec))
    prec = ["%s %.1f%%" % (CN[s], 100 * M[i, i] / M[:, i].sum())
            for i, s in enumerate(present) if M[:, i].sum() > 0]
    lines.append("逐类精确率：" + "，".join(prec))
    lines.append("")
    if drift:
        lines.extend(drift)
        lines.append("")
    lines.append("注：窗重叠 7/8，记录级比窗口级可信；概率为 Platt 校准，仅作排序参考。")
    report = "\n".join(lines) + "\n"
    report_path = os.path.join(out, "report.txt")
    with open(report_path, "w") as f:
        f.write(report)

    windows_csv = os.path.join(out, "windows.csv")
    with open(windows_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=(["day", "record", "state", "t0", "pred", "prob"]
                                          + ["p_" + c for c in classes]))
        w.writeheader()
        for i, r in enumerate(rows):
            w.writerow(dict({"day": r["dataset"], "record": r["record"],
                             "state": r["state"], "t0": round(r["t0"], 4),
                             "pred": pred[i], "prob": round(float(proba[i].max()), 6)},
                            **{("p_" + c): round(float(proba[i, k]), 6)
                               for k, c in enumerate(classes)}))

    print(report)
    print("输出：%s\n      %s" % (report_path, windows_csv))


if __name__ == "__main__":
    main()
