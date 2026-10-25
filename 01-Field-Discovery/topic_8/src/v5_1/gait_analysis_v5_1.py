#!/usr/bin/env python3
"""课题 08 v5.1 —— v5 的补丁版：只把"下楼/非下楼"的判决量从 ptn 换成稳健偏度。

为什么只改这一处：`ptn = (mean(pv)-mean(tv))/(mean(pv)+mean(tv))` 的分子分母含
`pv+tv`，给窗内所有样本加一个常数 c 时峰抬 c、谷的绝对值降 c，ptn 随之改变。
所以"窗内减中位数"只能压掉当天的零偏，压不掉重力方向估计滞后带来的水平加速度
泄漏；跨日时 ptn 的类条件分布整体平移，固定的 ptn 阈值就跨类了（README §8.6）。

v5.1 换成 5 %/95 % 分位的稳健偏度：

    rob_skew = (q95 + q05 - 2*q50) / (q95 - q05)

分子、分母都是同类差值：加常数 c 时 q95、q05、q50 各加 c，分子分母都不变；
乘系数 a 时分子分母同乘 a。即对"加性零偏"和"增益"都不变。

其余一律不动：8 s 窗 / 1 s 步长、Gravity 解耦、清洗、分位标定、acp/zcr 等权打分、
±2 窗多数票平滑，全部沿用 v5，因此 v5.1 与 v5 的差异可归因到这一个判决量。
实现上复用 v5 的流水线（v5 增加了 --asym 开关，默认 ptn 时行为与改造前逐位一致）。

用法：
    MPLCONFIGDIR=/tmp/mplcfg .venv/bin/python src/v5_1/gait_analysis_v5_1.py
    # 等价于：... src/v5/gait_analysis_v5.py --asym rob_skew --out output/v5_1/features
输出：output/v5_1/features/{windows.csv,report.txt}
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "v5"))

from gait_analysis_v5 import ROOT, main  # noqa: E402

OUT = os.path.join(ROOT, "output", "v5_1", "features")

if __name__ == "__main__":
    main(asym="rob_skew", default_out=OUT, title="v5.1")
