#!/usr/bin/env python3
"""课题 08 v7：用训练好的 RBF-SVM 做逐窗预测 + 段级多数票。

两种用法：
  一个一个测：--input data/blind/2026-10-30/walk-1/
  一起测：    --input data/blind/2026-11-02/
              --input data/blind/2026-10-30/walk-1 data/blind/2026-10-31/stand

输入是解压后的段目录（Accelerometer.csv + Gravity.csv + meta/）。不足 8 s、清洗后为空、
缺 CSV 都会显式报错，不静默跳过。测试时无真值，不输出 state。

输出：output/svm/predict/<tag>/windows.csv（day, record, t0, pred, prob）
      output/svm/predict/<tag>/report.txt（逐段多数票 + 平均概率 + 汇总）
用法：MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/svm/predict_svm.py \
          --input data/blind/2026-10-30/walk-1/
"""
import argparse
import csv
import os
import sys
from collections import Counter, defaultdict

import joblib
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import baseline_compare as base  # noqa: E402
import svm_data  # noqa: E402

CN = base.CN


def tag_of(inputs):
    names = [os.path.basename(os.path.normpath(os.path.abspath(p))) for p in inputs]
    return names[0] if len(names) == 1 else "_".join(names)


def vote_text(counter):
    return " / ".join("%s %d" % (CN[k], v)
                      for k, v in sorted(counter.items(),
                                         key=lambda kv: (-kv[1], kv[0])))


def main():
    ap = argparse.ArgumentParser(description="v7 RBF-SVM 预测：单段目录或日期目录")
    ap.add_argument("--input", nargs="+", required=True, metavar="PATH",
                    help="段目录或日期目录（可多个）")
    args = ap.parse_args()

    model_path = os.path.join(base.OUT, "model_rbf.joblib")
    if not os.path.isfile(model_path):
        sys.exit("模型不存在：%s\n请先运行 MPLCONFIGDIR=/tmp/mplcfg "
                 ".venv/bin/python src/svm/train_svm.py" % model_path)
    bundle = joblib.load(model_path)
    if bundle.get("feature_names") != list(base.FEATS):
        sys.exit("模型特征与当前脚本不一致：%r" % (bundle.get("feature_names"),))
    model = bundle["pipeline"]
    meta = bundle.get("meta", {})

    try:
        rows, _ = svm_data.collect_checked(args.input)
    except svm_data.InputError as exc:
        sys.exit("输入不合格：\n%s" % exc)
    n = len(rows)

    X = np.array([[r[f] for f in base.FEATS] for r in rows], dtype=float)
    pred = model.predict(X)
    proba = model.predict_proba(X)
    classes = list(model.classes_)
    prob = proba.max(axis=1)

    out = os.path.join(base.OUT, "predict", tag_of(args.input))
    os.makedirs(out, exist_ok=True)
    windows_csv = os.path.join(out, "windows.csv")
    with open(windows_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["day", "record", "t0", "pred", "prob"])
        w.writeheader()
        for i, r in enumerate(rows):
            w.writerow({"day": r["dataset"], "record": r["record"],
                        "t0": round(r["t0"], 4), "pred": pred[i],
                        "prob": round(float(prob[i]), 6)})

    groups = defaultdict(list)
    for i, r in enumerate(rows):
        groups[(r["dataset"], r["record"])].append(i)
    seg_counts = Counter()
    win_counts = Counter()
    lines = []
    lines.append("v7 RBF-SVM 预测（v6 特征，8 s 窗 / 1 s 步长）")
    lines.append("模型：%s" % os.path.relpath(model_path, base.ROOT))
    lines.append("  训练：%s，%d 段 %d 窗；sklearn %s" % (
        "、".join(meta.get("days", [])), meta.get("n_records", 0),
        meta.get("n_windows", 0), meta.get("sklearn", "?")))
    lines.append("输入：")
    for p in args.input:
        lines.append("  " + os.path.abspath(p))
    lines.append("段数 %d，窗数 %d" % (len(groups), n))
    lines.append("测试时无真值；段级判决 = 每段窗级多数票；概率为 Platt 校准"
                 "（probability=True，内部 5 折），仅作参考。")
    lines.append("")
    lines.append("逐段：")
    lines.append("%-12s %-18s %5s %8s %8s   %s" % (
        "日期", "记录", "窗数", "段级判决", "平均概率", "票型"))
    for (day, record), idx in groups.items():
        votes = Counter(pred[i] for i in idx)
        maj = votes.most_common(1)[0][0]
        p_maj = float(proba[idx, classes.index(maj)].mean())
        seg_counts[maj] += 1
        win_counts.update(pred[i] for i in idx)
        lines.append("%-12s %-18s %5d %8s %8.3f   %s" % (
            day, record, len(idx), CN[maj], p_maj, vote_text(votes)))
    if len(groups) == 1:
        (day, record), idx = next(iter(groups.items()))
        votes = Counter(pred[i] for i in idx)
        maj, cnt = votes.most_common(1)[0]
        lines.append("")
        lines.append("段级判决：%s（多数票 %d/%d，平均概率 %.3f）" % (
            CN[maj], cnt, len(idx), float(proba[idx, classes.index(maj)].mean())))
    lines.append("")
    lines.append("汇总（段级，按多数票）：" + "，".join(
        "%s %d 段" % (CN[k], v)
        for k, v in sorted(seg_counts.items(), key=lambda kv: (-kv[1], kv[0]))))
    lines.append("汇总（窗级）：" + "，".join(
        "%s %d 窗（%.1f%%）" % (CN[k], v, 100.0 * v / n)
        for k, v in sorted(win_counts.items(), key=lambda kv: (-kv[1], kv[0]))))
    lines.append("")
    lines.append("注：相邻窗重叠 7/8，记录级比窗口级可信。")
    report = "\n".join(lines) + "\n"
    report_path = os.path.join(out, "report.txt")
    with open(report_path, "w") as f:
        f.write(report)

    print(report)
    print("输出：%s\n      %s" % (windows_csv, report_path))


if __name__ == "__main__":
    main()
