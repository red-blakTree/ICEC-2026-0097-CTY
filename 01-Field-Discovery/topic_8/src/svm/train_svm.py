#!/usr/bin/env python3
"""课题 08 v7：RBF-SVM 有监督分支的训练、复核与外部抽样检查。

口径：
  - 数据：data/blind/2026-10-30、10-31、11-01 共 36 段 2785 窗（8 s / 1 s）；
  - 特征：复用 src/v6/features.py 的 10 维窗特征，不另造特征；
  - 模型：Pipeline(StandardScaler, SVC(rbf, C=10, gamma=scale,
          class_weight=balanced, probability=True))；
  - 验证：StratifiedGroupKFold(5) 按（日期,记录）分组取折外 + 留一天（LODO）；
          记录级 = 每段多数票；分列标准段 / 不摆臂段；macro-F1；
  - 外部检查：2026-10-25（9 段 704 窗，不参与训练），该日曾用于 v5.1/v6 选型。

输出：output/svm/model_rbf.joblib、train_report.txt、external_2026-10-25_windows.csv
用法：MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/svm/train_svm.py
"""
import csv
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
import warnings
import joblib
import numpy as np
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import baseline_compare as base  # noqa: E402
import svm_data  # noqa: E402
# sklearn 1.9 起把 SVC(probability=True) 标为将来弃用；课题规格明确要求这个参数，
# 这里只把这条重复告警按位置收敛为一次，不屏蔽其它警告。
warnings.filterwarnings("module", category=FutureWarning, module=r"sklearn\.svm\._base")
DAYS = base.DAYS
FEATS = base.FEATS
STATES = base.STATES
CN = base.CN
OUT = base.OUT
EXTERNAL_DAY = "2026-10-25"
RBF_PARAMS = dict(kernel="rbf", C=10.0, gamma="scale",
                  class_weight="balanced", probability=True, random_state=0)
RF_PARAMS = dict(n_estimators=400, min_samples_leaf=3, max_features="sqrt",
                 class_weight="balanced_subsample", random_state=0, n_jobs=1)


def build_model():
    return Pipeline([("scaler", StandardScaler()), ("svc", SVC(**RBF_PARAMS))])


def matrix(rows):
    X = np.array([[r[f] for f in FEATS] for r in rows], dtype=float)
    y = np.array([r["state"] for r in rows])
    groups = np.array([r["dataset"] + "/" + r["record"] for r in rows])
    return X, y, groups


def cv_splits(X, y, groups):
    return list(StratifiedGroupKFold(n_splits=5, shuffle=True,
                                     random_state=0).split(X, y, groups))


def add_table(lines, title, entries):
    lines.append(title)
    lines.append("%-16s %8s %8s %8s   %7s %7s %7s %8s" % (
        "方法", "窗口·全部", "窗口·标准", "窗口·不摆臂",
        "记录·全部", "记录·标准", "记录·不摆臂", "macroF1"))
    for label, m in entries:
        lines.append("%-16s %8s %8s %8s   %7s %7s %7s %8.3f" % (
            label, base.pct(m["all"]), base.pct(m["std"]), base.pct(m["ns"]),
            base.rec_cell(m["all"]), base.rec_cell(m["std"]),
            base.rec_cell(m["ns"]), m["f1"]))
    lines.append("")


def confusion_block(lines, title, rows, pred):
    yy = [r["state"] for r in rows]
    pp = list(pred)
    M = confusion_matrix(yy, pp, labels=list(STATES))
    lines.append(title)
    lines.append("%-6s" % "" + "".join("%7s" % CN[s] for s in STATES))
    for i, a in enumerate(STATES):
        lines.append("%-6s" % CN[a] + "".join("%7d" % x for x in M[i]))
    rec = ["%s %.1f%%" % (CN[s], 100 * M[i, i] / M[i].sum())
           for i, s in enumerate(STATES) if M[i].sum() > 0]
    lines.append("逐类召回：" + "，".join(rec))
    prec = ["%s %.1f%%" % (CN[s], 100 * M[i, i] / M[:, i].sum())
            for i, s in enumerate(STATES) if M[:, i].sum() > 0]
    lines.append("逐类精确率：" + "，".join(prec))
    lines.append("")


def external_check(model, lines):
    """2026-10-25 外部抽样检查，返回逐窗 CSV 行。"""
    day_dir = os.path.join(base.ROOT, "data", "blind", EXTERNAL_DAY)
    rows, _ = svm_data.collect_checked([day_dir])
    n = len(rows)
    X = np.array([[r[f] for f in FEATS] for r in rows], dtype=float)
    pred = model.predict(X)
    proba = model.predict_proba(X)
    classes = list(model.classes_)
    m = base.evaluate(rows, pred, np.arange(n))
    lo, hi = base.wilson(m["all"]["ok"], n)

    lines.append("== 5. 外部抽样检查：%s（未参与训练）==" % EXTERNAL_DAY)
    lines.append("窗口级 %.1f%%（%d/%d），Wilson 95%% [%.1f, %.1f]；记录级 %d/%d；"
                 "macroF1 %.3f" % (
                     100 * m["all"]["acc"], m["all"]["ok"], n,
                     100 * lo, 100 * hi, m["all"]["rok"], m["all"]["rn"], m["f1"]))
    lines.append("对照 v6 规则（output/reports/blind_2026-10-25/report.txt）："
                 "窗口级 94.5%、记录级 9/9。")
    lines.append("本组外部检查比 v6 低 1.7 个点（92.8% vs 94.5%），差距集中在 go_upstairs-2"
                 "（窗口级 63.6%，56/88：18 窗判慢走、14 窗判下楼；段级多数票仍为上楼）；"
                 "v7 相对 v6 的收益在不摆臂段（LODO 91.9% vs v6 27.6%），不在这组。")
    lines.append("")

    groups = defaultdict(list)
    for i, r in enumerate(rows):
        groups[(r["dataset"], r["record"])].append(i)
    lines.append("逐段（段级判决 = 多数票）：")
    lines.append("%-16s %-6s %5s %8s %-8s %4s %8s" % (
        "记录", "真值", "窗数", "窗口级", "多数票", "对错", "平均P"))
    out_rows = []
    for key in groups:
        idx = groups[key]
        truth = rows[idx[0]]["state"]
        votes = Counter(pred[i] for i in idx)
        maj, cnt = votes.most_common(1)[0]
        acc = np.mean([pred[i] == truth for i in idx])
        p_maj = float(proba[idx, classes.index(maj)].mean())
        lines.append("%-16s %-6s %5d %8.1f%% %-8s %4s %8.3f" % (
            key[1], CN[truth], len(idx), 100 * acc, CN[maj],
            "对" if maj == truth else "错", p_maj))
        for i in idx:
            out_rows.append({
                "day": rows[i]["dataset"], "record": rows[i]["record"],
                "state": rows[i]["state"], "t0": round(rows[i]["t0"], 4),
                "pred": pred[i], "prob": round(float(proba[i].max()), 6),
                **{("p_" + c): round(float(proba[i, k]), 6)
                   for k, c in enumerate(classes)},
            })
    lines.append("")
    confusion_block(lines, "外部检查 · 窗口级混淆矩阵（行=真值，列=判决）", rows, pred)
    lines.append("注：真值由段目录名推断（与仓库既有报告一致）。%s 曾用于 v5.1/v6 选型，"
                 "本次只能算外部抽样复核，不是完全未看过。" % EXTERNAL_DAY)
    lines.append("")
    return out_rows


def main():
    rows = base.load()
    n = len(rows)
    X, y, groups = matrix(rows)
    std_mask = np.array(["noswing" not in r["record"] for r in rows])
    n_rec = len(set(groups))
    n_std = len({(r["dataset"], r["record"]) for r in rows if "noswing" not in r["record"]})
    n_ns = len({(r["dataset"], r["record"]) for r in rows if "noswing" in r["record"]})
    stand_idx = [i for i, r in enumerate(rows) if r["state"] == "stand"]
    n_stand = len({(r["dataset"], r["record"]) for r in rows if r["state"] == "stand"})
    print("训练集：%d 段 %d 窗（标准 %d 段 %d 窗，不摆臂 %d 段 %d 窗）"
          % (n_rec, n, n_std, int(std_mask.sum()), n_ns, int((~std_mask).sum())))

    splits = cv_splits(X, y, groups)
    oof = np.empty(n, dtype=object)
    rf_imps = []
    for tr, te in splits:
        oof[te] = build_model().fit(X[tr], y[tr]).predict(X[te])
        rf_imps.append(RandomForestClassifier(**RF_PARAMS)
                       .fit(X[tr], y[tr]).feature_importances_)
    rf_imps = np.array(rf_imps)

    lodo = np.empty(n, dtype=object)
    for day in DAYS:
        tr = np.array([i for i, r in enumerate(rows) if r["dataset"] != day])
        te = np.array([i for i, r in enumerate(rows) if r["dataset"] == day])
        lodo[te] = build_model().fit(X[tr], y[tr]).predict(X[te])

    model = build_model().fit(X, y)
    train_acc = float((model.predict(X) == y).mean())

    os.makedirs(OUT, exist_ok=True)
    model_path = os.path.join(OUT, "model_rbf.joblib")
    meta = {
        "days": list(DAYS), "n_days": len(DAYS), "n_records": n_rec,
        "n_windows": n,
        "n_std_records": n_std, "n_std_windows": int(std_mask.sum()),
        "n_ns_records": n_ns, "n_ns_windows": int((~std_mask).sum()),
        "n_stand_records": n_stand, "n_stand_windows": len(stand_idx),
        "hyperparams": dict(RBF_PARAMS, pipeline="StandardScaler+SVC"),
        "feature_names": list(FEATS),
        "truth": "由段目录名推断",
        "device": "PKG110（OnePlus）",   # 训练集 meta/device.csv 均为该机型
        "sklearn": sklearn.__version__,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    joblib.dump({"pipeline": model, "feature_names": list(FEATS),
                 "classes": [str(c) for c in model.classes_], "meta": meta},
                model_path)
    back = joblib.load(model_path)
    reload_ok = (np.array_equal(back["pipeline"].predict(X[:64]), model.predict(X[:64]))
                 and back["feature_names"] == list(FEATS)
                 and list(back["classes"]) == [str(c) for c in model.classes_])

    lines = []
    lines.append("课题 08 v7：RBF-SVM 有监督分支（v6 特征，8 s 窗 / 1 s 步长）")
    lines.append("")
    lines.append("== 0. 定名与数据 ==")
    lines.append("定名 v7，不是 v6.1：本版引入了 v6 明确排除的学习层（README §4.7："
                 "“16 段记录撑不起判别模型，v6 因此不引入学习层”），判决从零训练、"
                 "固定阈值的规则变成随训练集走的模型文件。这是方法论换代，"
                 "不是参数修订，所以用 v7。v7 不替代 v6：v6 零训练、可解释、可审计，"
                 "是零重训基线；v7 依赖 36 段训练数据，换手机或换人必须重训。"
                 "两者并列引用，不要混用。")
    lines.append("数据：%s，共 %d 段 %d 窗（标准 %d 段 %d 窗；不摆臂 %d 段 %d 窗）" % (
        "、".join(DAYS), n_rec, n, n_std, int(std_mask.sum()),
        n_ns, int((~std_mask).sum())))
    lines.append("真值：由段目录名推断（walk/run/up/down/stand）；stand %d 段 %d 窗。"
                 % (n_stand, len(stand_idx)))
    lines.append("特征（%d 维，复用 src/v6/features.py，未另造）：%s"
                 % (len(FEATS), ", ".join(FEATS)))
    lines.append("模型：Pipeline(StandardScaler, SVC(kernel=rbf, C=10, gamma=scale, "
                 "class_weight=balanced, probability=True, random_state=0))")
    lines.append("训练：全量 %d 段；保存 %s" % (n_rec, os.path.relpath(model_path, base.ROOT)))
    lines.append("验证：StratifiedGroupKFold(5) 按（日期,记录）分组取折外；LODO = 训练另两天、"
                 "测试留出天；记录级 = 每段多数票；macro-F1 五类宏平均。")
    lines.append("保存回读校验：%s（pipeline / feature_names / classes 一致，预测一致）"
                 % ("通过" if reload_ok else "失败"))
    lines.append("")

    add_table(lines, "== 1. 段级分组 5 折折外（OOF）==",
              [("RBF-SVM", base.evaluate(rows, oof, np.arange(n)))])
    add_table(lines, "== 2. 留一天（LODO）==",
              [("RBF-SVM", base.evaluate(rows, lodo, np.arange(n)))])
    lines.append("LODO 逐天：")
    lines.append("%-12s %6s %8s %8s %8s" % ("天", "窗数", "窗口级", "记录级", "macroF1"))
    for day in DAYS:
        idx = np.array([i for i, r in enumerate(rows) if r["dataset"] == day])
        m = base.evaluate(rows, lodo, idx)
        lines.append("%-12s %6d %8.1f%% %8s %8.3f" % (
            day, len(idx), 100 * m["all"]["acc"],
            base.rec_cell(m["all"]), m["f1"]))
    lines.append("")
    lines.append("训练集自评（全量拟合后再预测训练集）：%.2f%%——只作 sanity check，"
                 "无泛化意义，不引用。" % (100 * train_acc))
    lines.append("")

    confusion_block(lines, "== 3. 窗口级混淆矩阵（OOF；行=真值，列=判决）==", rows, oof)
    confusion_block(lines, "== 3. 窗口级混淆矩阵（LODO；行=真值，列=判决）==", rows, lodo)

    lines.append("== 4. RF 特征重要性（5 折训练集上的不纯度重要性，均值±标准差）==")
    order = np.argsort(-rf_imps.mean(axis=0))
    for k in order:
        lines.append("%-10s %.3f ± %.3f" % (
            FEATS[k], rf_imps[:, k].mean(), rf_imps[:, k].std()))
    lines.append("注：不纯度重要性只说明树模型用了哪些特征、用得多不多，不是因果贡献；"
                 "与 v6 的不变核结论（rob_skew 判下楼、acp/zcr 分慢走与上楼）不冲突。")
    lines.append("")

    ext_rows = external_check(model, lines)

    lines.append("== 6. 已知边界与限定 ==")
    lines.append("1. stand 段 %d 段 %d 窗，采集时未区分持机方式。站立时手臂静止、不存在摆臂动作，"
                 "不要写成“不摆臂站立”。若测试采用不同持机方式（手持/口袋/支架）需重验。"
                 % (n_stand, len(stand_idx)))
    lines.append("2. 训练集一人一机（PKG110）、三天；换手机或换佩戴方式必须重验。")
    lines.append("3. 训练集自评（%.2f%%）只作 sanity check；可引用的泛化数字是 LODO："
                 "全部 %.1f%%、标准段 %.1f%%、不摆臂段 %.1f%%。"
                 % ((100 * train_acc,)
                    + tuple(100 * base.evaluate(rows, lodo, np.arange(n))[k]["acc"]
                            for k in ("all", "std", "ns"))))
    lines.append("4. 概率来自 Platt 校准（probability=True，内部 5 折），只作排序参考，"
                 "不是严格置信度；不要把 0.99 读成“99% 确定”。")
    lines.append("5. 窗重叠 7/8，相邻窗高度相关；记录级（每段多数票）比窗口级可信，"
                 "引用时以记录级为主。")
    lines.append("6. %s 曾用于 v5.1/v6 选型，本次外部检查“不是完全未看过”；"
                 "它只能当抽样复核，不能当独立盲测。" % EXTERNAL_DAY)
    lines.append("7. 不摆臂段（13 段）是协议外变量，训练与验证按段分组避免同段窗泄漏；"
                 "引用跨日数字时只能用标准段。")
    lines.append("")
    lines.append("复现：MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/svm/train_svm.py")

    report = os.path.join(OUT, "train_report.txt")
    with open(report, "w") as f:
        f.write("\n".join(lines) + "\n")

    ext_csv = os.path.join(OUT, "external_%s_windows.csv" % EXTERNAL_DAY)
    with open(ext_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ext_rows[0].keys()))
        w.writeheader()
        w.writerows(ext_rows)

    print("\n".join(lines))
    print("\n输出：%s\n      %s\n      %s" % (model_path, report, ext_csv))


if __name__ == "__main__":
    main()
