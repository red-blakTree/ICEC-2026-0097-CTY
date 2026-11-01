#!/usr/bin/env python3
"""四个基线（LR / LinearSVC / RBF-SVM / RF）的最小对照。

口径：
  - 数据：data/blind/2026-10-30、10-31、11-01 共 36 段、2785 窗（8 s / 1 s）；
  - 特征：复用 src/v6/features.py 的 11 个窗特征（rob_skew/acp/ac_lag/zcr/
          n_steps/cadence/i_cv/std/bias/sigma），不另造特征；
  - 验证：StratifiedGroupKFold(5) 按 (日期, 记录) 分组，取折外预测；
          另做留一天（LODO，训练另两天、测试留出天）；
  - 指标：窗口级、记录级（每段多数票）、macro-F1，分列标准段 / 不摆臂段；
  - 参照：v6 规则判决（output/reports/blind_<日期>/windows.csv 的 pred_v6）。

输出：output/svm/cv_windows.csv、output/svm/report.txt
用法：MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/svm/baseline_compare.py
"""
import csv
import os
import sys
from collections import Counter, defaultdict

import numpy as np
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, f1_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC, LinearSVC

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "v6"))
import features as v6f  # noqa: E402

ROOT = v6f.ROOT
DAYS = ("2026-10-30", "2026-10-31", "2026-11-01")
STATES = ("stand", "walk", "run", "up", "down")
CN = {"stand": "静止", "walk": "慢走", "run": "快跑", "up": "上楼", "down": "下楼"}
FEATS = ("rob_skew", "acp", "ac_lag", "zcr", "n_steps", "cadence", "i_cv",
         "std", "bias", "sigma")
OUT = os.path.join(ROOT, "output", "svm")


def load():
    rows = []
    for day in DAYS:
        rows += v6f.collect(os.path.join(ROOT, "data", "blind", day), tag=day)
    return rows


def build_models():
    return {
        "LR": make_pipeline(StandardScaler(), LogisticRegression(
            C=1.0, max_iter=3000, class_weight="balanced")),
        "LinearSVC": make_pipeline(StandardScaler(), LinearSVC(
            C=1.0, max_iter=20000, class_weight="balanced")),
        "RBF-SVM": make_pipeline(StandardScaler(), SVC(
            C=10.0, gamma="scale", class_weight="balanced")),
        "RF": RandomForestClassifier(
            n_estimators=400, min_samples_leaf=3, max_features="sqrt",
            class_weight="balanced_subsample", random_state=0, n_jobs=1),
    }


def load_v6(rows):
    table = {}
    for day in DAYS:
        path = os.path.join(ROOT, "output", "reports", "blind_" + day, "windows.csv")
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                table[(day, r["record"], round(float(r["t0"]), 4))] = r["pred_v6"]
    pred = np.empty(len(rows), dtype=object)
    miss = 0
    for i, r in enumerate(rows):
        k = (r["dataset"], r["record"], round(r["t0"], 4))
        if k in table:
            pred[i] = table[k]
        else:
            miss += 1
    return pred, miss


def wilson(k, n):
    if n == 0:
        return 0.0, 0.0
    z = 1.96
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def record_level(rows, idx, pred):
    groups = defaultdict(list)
    for i in idx:
        groups[(rows[i]["dataset"], rows[i]["record"])].append(i)
    ok = 0
    for ii in groups.values():
        truth = rows[ii[0]]["state"]
        maj = Counter(pred[i] for i in ii).most_common(1)[0][0]
        ok += maj == truth
    return ok, len(groups)


def evaluate(rows, pred, idx):
    out = {}
    for name, sub in (
        ("all", list(idx)),
        ("std", [i for i in idx if "noswing" not in rows[i]["record"]]),
        ("ns", [i for i in idx if "noswing" in rows[i]["record"]]),
    ):
        if not sub:
            out[name] = None
            continue
        ok = sum(pred[i] == rows[i]["state"] for i in sub)
        rok, rn = record_level(rows, sub, pred)
        out[name] = dict(ok=ok, n=len(sub), acc=ok / len(sub), rok=rok, rn=rn)
    yy = [rows[i]["state"] for i in idx]
    pp = [pred[i] for i in idx]
    out["f1"] = f1_score(yy, pp, labels=list(STATES), average="macro", zero_division=0)
    return out


def pct(cell):
    return "  —  " if cell is None else "%5.1f%%" % (100.0 * cell["acc"])


def rec_cell(cell):
    return "  —  " if cell is None else "%2d/%-2d" % (cell["rok"], cell["rn"])


def main():
    rows = load()
    n = len(rows)
    X = np.array([[r[f] for f in FEATS] for r in rows], dtype=float)
    y = np.array([r["state"] for r in rows])
    groups = np.array([r["dataset"] + "/" + r["record"] for r in rows])
    print("窗数 %d，段数 %d" % (n, len(set(groups))))

    os.makedirs(OUT, exist_ok=True)
    models = build_models()
    oof = {k: np.empty(n, dtype=object) for k in models}
    for tr, te in StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=0).split(X, y, groups):
        for name, model in models.items():
            m = clone(model).fit(X[tr], y[tr])
            oof[name][te] = m.predict(X[te])

    lodo = {k: np.empty(n, dtype=object) for k in models}
    for day in DAYS:
        tr = np.array([i for i, r in enumerate(rows) if r["dataset"] != day])
        te = np.array([i for i, r in enumerate(rows) if r["dataset"] == day])
        for name, model in models.items():
            m = clone(model).fit(X[tr], y[tr])
            lodo[name][te] = m.predict(X[te])

    v6pred, miss = load_v6(rows)
    print("v6 对齐缺失 %d 窗" % miss)

    lines = []
    lines.append("四个基线最小对照（v6 特征，8 s 窗 / 1 s 步长）")
    lines.append("数据：%s，共 %d 段 %d 窗；标准段 %d 窗，不摆臂段 %d 窗" % (
        "、".join(DAYS), len(set(groups)), n,
        sum(1 for r in rows if "noswing" not in r["record"]),
        sum(1 for r in rows if "noswing" in r["record"])))
    lines.append("特征（%d 维）：%s" % (len(FEATS), ", ".join(FEATS)))
    lines.append("模型超参（固定，未调参）：LR C=1；LinearSVC C=1；RBF-SVM C=10, gamma=scale；"
                 "RF 400 树, min_samples_leaf=3, max_features=sqrt")
    lines.append("验证：StratifiedGroupKFold(5) 按（日期,记录）分组取折外；LODO = 留一天；"
                 "记录级 = 每段多数票")
    lines.append("")

    def add_table(title, preds):
        lines.append(title)
        lines.append("%-10s %8s %8s %8s   %7s %7s %7s %8s" % (
            "方法", "窗口·全部", "窗口·标准", "窗口·不摆臂",
            "记录·全部", "记录·标准", "记录·不摆臂", "macroF1"))
        for label, pred in preds:
            m = evaluate(rows, pred, np.arange(n))
            lines.append("%-10s %8s %8s %8s   %7s %7s %7s %8.3f" % (
                label, pct(m["all"]), pct(m["std"]), pct(m["ns"]),
                rec_cell(m["all"]), rec_cell(m["std"]), rec_cell(m["ns"]), m["f1"]))
        lines.append("")

    add_table("== 段级分组 5 折折外（GroupKFold）==",
              [("v6 规则", v6pred)] + [(k, oof[k]) for k in models])
    add_table("== 留一天（LODO）==",
              [("v6 规则", v6pred)] + [(k, lodo[k]) for k in models])

    # 混淆矩阵与逐类召回（GroupKFold 折外）
    lines.append("== 窗口级混淆矩阵（GroupKFold 折外；行=真值，列=判决）==")
    for label, pred in [("v6 规则", v6pred)] + [(k, oof[k]) for k in models]:
        yy = [r["state"] for r in rows]
        pp = [pred[i] for i in range(n)]
        M = confusion_matrix(yy, pp, labels=list(STATES))
        lines.append("")
        lines.append("%s" % label)
        lines.append("%-6s" % "" + "".join("%7s" % CN[s] for s in STATES))
        for i, a in enumerate(STATES):
            lines.append("%-6s" % CN[a] + "".join("%7d" % x for x in M[i]))
        rec = ["%s %.1f%%" % (CN[s], 100 * M[i, i] / M[i].sum())
               for i, s in enumerate(STATES) if M[i].sum() > 0]
        lines.append("逐类召回：" + "，".join(rec))

    lines.append("")
    lines.append("注：窗口级数字按 8 s 窗 / 1 s 步长统计，相邻窗重叠 7/8；"
                 "记录级为每段多数票；两套拆分下 v6 都是固定规则，不参与训练。")

    with open(os.path.join(OUT, "report.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")

    with open(os.path.join(OUT, "cv_windows.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "day", "record", "state", "t0", "noswing",
            "pred_lr", "pred_linsvc", "pred_rbf", "pred_rf", "pred_v6"])
        w.writeheader()
        for i, r in enumerate(rows):
            w.writerow({
                "day": r["dataset"], "record": r["record"], "state": r["state"],
                "t0": round(r["t0"], 4), "noswing": int("noswing" in r["record"]),
                "pred_lr": oof["LR"][i], "pred_linsvc": oof["LinearSVC"][i],
                "pred_rbf": oof["RBF-SVM"][i], "pred_rf": oof["RF"][i],
                "pred_v6": v6pred[i]})

    print("\n".join(lines))
    print("\n输出：%s" % OUT)


if __name__ == "__main__":
    main()
