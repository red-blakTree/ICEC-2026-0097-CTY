#!/usr/bin/env python3
"""课题 08 v6 判决层：分位标定 + 分层规则 + 段级解码。

与 v5.1 相比只换了两件事：
  1. 下楼判据用不变核里的 rob_skew（v5.1 已换成它），阈值取 2 %/98 % 分位间隔的
     **算术中点**——有符号量上几何中点会被 0 附近的 q98 拉向多数类；
  2. ±2 窗多数票换成段级解码（Viterbi）。规则给出的逐窗判决是"观测"，
     段级解码在此基础上加一个状态切换代价：切换一次的代价是 penalty×图上距离，
     留在错误状态的代价是每窗 1。penalty<1 时等价于"只抹掉孤立的单窗跳变"，
     比固定 ±2 多数票更少误伤真实的状态切换（README §9）。

判决顺序（与 v4/v5 一致，静止/快跑门限在前）：
    sigma < stand      -> 静止
    sigma > run        -> 快跑
    rob_skew > down    -> 下楼
    score_up > up      -> 上楼
    否则                -> 平地慢走

`sigma` 是唯一依赖绝对幅值的量（见 features.py 声明）；换第三台设备时先复查它。
"""
import numpy as np

from features import STATES

QUANT = 0.02
DOWN_KEY = "rob_skew"
# 段级解码的切换代价；在 16 段留一上选出来的（见 evaluate.py 的消融表）
DEFAULT_PENALTY = 1.0

# 状态图：walk 是中心，其余四个都只在走路时进出；上/下楼之间要经过平地。
_CENTER = "walk"
GRAPH_DIST = {(a, b): (0 if a == b else (1 if _CENTER in (a, b) else 2))
              for a in STATES for b in STATES}


def _values(rows, states, key):
    return np.array([r[key] for r in rows if r["state"] in states])


def _quantile(rows, states, key, p):
    v = _values(rows, states, key)
    if len(v) == 0:
        raise ValueError("标定集缺少类别 %s，无法计算 %s 的 %.0f %% 分位" % (states, key, p))
    return float(np.percentile(v, p))


def _geometric(a, b):
    a, b = float(a), float(b)
    return float(np.sqrt(a * b)) if a > 0 and b > 0 else 0.5 * (a + b)


def _midpoint(a, b):
    return 0.5 * (float(a) + float(b))


def _zstats(rows, key):
    v = _values(rows, ("walk", "up"), key)
    return float(v.mean()), float(v.std() + 1e-9)


def up_score(f, th):
    a_m, a_s = th["acp"]
    z_m, z_s = th["zcr"]
    return -(f["acp"] - a_m) / a_s - (f["zcr"] - z_m) / z_s


def _best_split(scores, labels):
    """score 越大越像上楼；返回使 walk/up 命中数最大的阈值（只在训练行上调用）。"""
    order = np.argsort(scores)
    v, y = scores[order], labels[order]
    n = len(v)
    best = (-1, float(v[0] - 1e-9))
    for k in range(n + 1):
        th = v[0] - 1e-9 if k == 0 else (v[-1] + 1e-9 if k == n else 0.5 * (v[k - 1] + v[k]))
        hit = int((y[:k] == 0).sum() + (y[k:] == 1).sum())
        if hit > best[0]:
            best = (hit, float(th))
    return best[1]


def calibrate(rows):
    """阈值只在传入的训练行上标定；全部用分位数，不用极值。"""
    motion = ("walk", "run", "up", "down")
    t_stand = _geometric(_quantile(rows, ("stand",), "sigma", 100 - 100 * QUANT),
                         min(_quantile(rows, (s,), "sigma", 100 * QUANT) for s in motion))
    t_run = _geometric(max(_quantile(rows, (s,), "sigma", 100 - 100 * QUANT) for s in ("walk", "up", "down")),
                       _quantile(rows, ("run",), "sigma", 100 * QUANT))
    t_down = _midpoint(max(_quantile(rows, (s,), DOWN_KEY, 100 - 100 * QUANT) for s in ("walk", "up")),
                       _quantile(rows, ("down",), DOWN_KEY, 100 * QUANT))

    th = dict(stand=t_stand, run=t_run, down=t_down,
              acp=_zstats(rows, "acp"), zcr=_zstats(rows, "zcr"), up=0.0)
    scores, labels = [], []
    for r in rows:
        if r["sigma"] < t_stand or r["sigma"] > t_run or r[DOWN_KEY] > t_down:
            continue
        if r["state"] in ("walk", "up"):
            scores.append(up_score(r, th))
            labels.append(1 if r["state"] == "up" else 0)
    th["up"] = _best_split(np.array(scores), np.array(labels))
    return th


def predict(f, th):
    """逐窗判决（未平滑）。"""
    if f["sigma"] < th["stand"]:
        return "stand"
    if f["sigma"] > th["run"]:
        return "run"
    if f[DOWN_KEY] > th["down"]:
        return "down"
    return "up" if up_score(f, th) > th["up"] else "walk"


def _groups(rows):
    groups = {}
    for r in rows:
        groups.setdefault((r.get("dataset", ""), r["record"]), []).append(r)
    for v in groups.values():
        v.sort(key=lambda r: r["t0"])
    return list(groups.values())


def decode_vote(rows, radius=2):
    """v5.1 的口径：±radius 窗多数票。保留它是为了做消融。"""
    from collections import Counter
    for v in _groups(rows):
        raw = [r["pred"] for r in v]
        for i, r in enumerate(v):
            r["pred_smooth"] = Counter(raw[max(0, i - radius):i + radius + 1]).most_common(1)[0][0]
    return rows


def decode_viterbi(rows, penalty=0.6, causal=False):
    """段级解码：状态切换付 penalty×图上距离，留在错误状态每窗付 1。

    causal=True 时只允许看过去（在线可用），否则整段一次性解码。
    """
    for v in _groups(rows):
        seq = [r["pred"] for r in v]
        n = len(seq)
        emit = np.array([[0.0 if s == p else 1.0 for s in STATES] for p in seq])
        trans = np.array([[0.0 if a == b else penalty * GRAPH_DIST[(a, b)] for b in STATES]
                          for a in STATES])
        if causal:
            cost = emit[0].copy()
            paths = []
            for i in range(n):
                if i:
                    cost = emit[i] + (cost[:, None] + trans).min(axis=0)
                paths.append(int(np.argmin(cost)))
            # 在线解码只有当前最优状态可用，历史不回溯
            for i, r in enumerate(v):
                r["pred_smooth"] = STATES[paths[i]]
        else:
            cost = emit[0].copy()
            back = np.zeros((n, len(STATES)), dtype=int)
            for i in range(1, n):
                total = cost[:, None] + trans
                back[i] = np.argmin(total, axis=0)
                cost = emit[i] + total.min(axis=0)
            state = int(np.argmin(cost))
            for i in range(n - 1, -1, -1):
                v[i]["pred_smooth"] = STATES[state]
                state = int(back[i, state])
    return rows


def decode(rows, mode="viterbi", penalty=0.6, causal=False):
    if mode == "vote":
        return decode_vote(rows)
    if mode == "none":
        for r in rows:
            r["pred_smooth"] = r["pred"]
        return rows
    return decode_viterbi(rows, penalty, causal)


def run(rows, th, mode="viterbi", penalty=0.6, causal=False):
    """标定好的阈值 + 解码，返回原地写入 pred/pred_smooth 的 rows。"""
    for r in rows:
        r["pred"] = predict(r, th)
    return decode(rows, mode, penalty, causal)


def accuracy(rows, key="pred_smooth"):
    return sum(r[key] == r["state"] for r in rows) / len(rows)


def record_decisions(rows):
    """记录级：每段多数票。返回 [(record, truth, decision, n)]。"""
    from collections import Counter
    out = []
    for v in _groups(rows):
        major = Counter(r["pred_smooth"] for r in v).most_common(1)[0][0]
        out.append((v[0]["record"], v[0]["state"], major, len(v)))
    return out


def record_accuracy(rows):
    dec = record_decisions(rows)
    return sum(d == t for _, t, d, _ in dec), len(dec)
