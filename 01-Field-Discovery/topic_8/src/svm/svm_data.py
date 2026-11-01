#!/usr/bin/env python3
"""v7 预测/检查共用的输入层。

职责只有两件：把用户给的路径展开成段目录；在 v6f.collect 外层补上显式校验。
清洗 / 切窗 / 特征一律走 src/v6/features.py，这里不重复实现。

v6f.collect 内部对清洗后不足一窗的记录是 `continue`，用于批量统计没问题，但作为
预测入口会静默漏段。本模块把这种情况变成 InputError，一次报出所有不合格段。
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "v6"))
import features as v6f  # noqa: E402


class InputError(RuntimeError):
    """输入不可用：目录不存在、缺 CSV、时长不足或清洗后为空。"""


def segment_dirs(path):
    """输入路径 → 段目录列表；兼容单段目录与日期目录（递归找 Accelerometer.csv）。"""
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        raise InputError("输入不是目录：%s" % path)
    segs = v6f.find_records(path)
    if not segs:
        raise InputError("在 %s 下没有找到段目录（段目录需含 Accelerometer.csv）" % path)
    return segs


def _inspect(seg):
    """检查单段能否切出整窗，返回预期窗数；不合格直接抛 InputError。"""
    missing = [f for f in ("Accelerometer.csv", "Gravity.csv")
               if not os.path.isfile(os.path.join(seg, f))]
    if missing:
        raise InputError("%s：缺少 %s" % (seg, "、".join(missing)))

    t, ax, ay, az, gx, gy, gz = v6f.load_record(seg)
    fs = v6f.sample_rate(t)
    dur = (len(t) - 1) / fs if len(t) > 1 else 0.0
    if dur + 1e-9 < v6f.WIN_S:
        raise InputError("%s：记录时长 %.1f s，不足 %.0f s，无法切窗"
                         % (seg, dur, v6f.WIN_S))

    dyn = np.sqrt((ax - gx) ** 2 + (ay - gy) ** 2 + (az - gz) ** 2)
    i, j = v6f.clean(t, dyn)
    w, h = int(v6f.WIN_S * fs), int(v6f.HOP_S * fs)
    if j - i < w:
        raise InputError("%s：清洗后只剩 %.1f s（不足 %.0f s 或整段被剔除），无法切窗"
                         % (seg, (j - i) / fs, v6f.WIN_S))
    return (j - i - w) // h + 1


def collect_checked(paths):
    """展开输入路径并逐段取特征。

    返回 (rows, segs)，segs 为 (day, record, 段目录, 窗数)。
    任一段不合格都不预测，全部问题一次性抛出。
    """
    rows, segs, errors = [], [], []
    for path in paths:
        for seg in segment_dirs(path):
            day = os.path.basename(os.path.dirname(seg.rstrip(os.sep))) or "unknown"
            record = os.path.basename(seg.rstrip(os.sep))
            try:
                expect = _inspect(seg)
                part = v6f.collect(seg, tag=day)
            except InputError as exc:
                errors.append(str(exc))
                continue
            except Exception as exc:                     # CSV 损坏等
                errors.append("%s：%s" % (seg, exc))
                continue
            if len(part) != expect:
                errors.append("%s：预期 %d 窗，实际 %d 窗" % (seg, expect, len(part)))
                continue
            truth = v6f.infer_truth(day + "/" + record)
            for r in part:
                r["record"] = record
                r["state"] = truth
            rows += part
            segs.append((day, record, seg, len(part)))

    if errors:
        raise InputError("\n".join(errors))
    return rows, segs
