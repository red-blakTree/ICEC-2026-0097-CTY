#!/usr/bin/env python3
"""功耗模型与 24 h 序列的回归测试。

跑法:
  cd 02-20Days-Challenge
  python3 -m unittest discover -s measurement -p 'test_*.py' -v
"""
import unittest
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_meter_series as bms  # noqa: E402
import theory  # noqa: E402


class BudgetTest(unittest.TestCase):
    def test_default_matches_documented_numbers(self):
        b = theory.compute_budget()
        self.assertAlmostEqual(b["total_mah"], 167.5, delta=0.2)
        self.assertAlmostEqual(b["avg_ma"], 6.98, delta=0.01)
        self.assertAlmostEqual(b["runtime_days"], 9.5, delta=0.1)

    def test_upper_bound_is_eight_point_two_times(self):
        b = theory.compute_budget(i_sleep=10.0)
        self.assertAlmostEqual(b["avg_ma"], 10.94, delta=0.01)
        self.assertAlmostEqual(90.0 * 24 / b["total_mah"], 8.2, delta=0.05)

    def test_ten_x_needs_sleep_at_or_below_8_04_ma(self):
        b0 = theory.compute_budget(i_sleep=0.0)
        threshold = (9.0 * 24 - b0["total_mah"]) * 3600 / b0["t_sleep_s"]
        self.assertAlmostEqual(threshold, 8.04, delta=0.02)
        at = theory.compute_budget(i_sleep=threshold)
        self.assertAlmostEqual(at["avg_ma"], 9.0, delta=0.01)

    def test_short_cycle_costs_more(self):
        fast = theory.compute_budget(i_sleep=6.0, t_wake=2.1)
        slow = theory.compute_budget(i_sleep=6.0, t_wake=1.4)
        self.assertGreater(fast["total_mah"], slow["total_mah"])

    def test_full_day_window_is_rejected(self):
        with self.assertRaises(ValueError):
            theory.compute_budget(t_win=86400.0)


class MeterSeriesTest(unittest.TestCase):
    def test_anchors_cover_24h_and_16384_mwh(self):
        rows = bms.build(bms.load_anchors())
        self.assertEqual(len(rows), 4)
        minutes = sum(float(r["duration_min"]) for r in rows)
        mwh = sum(int(r["delta_mwh"]) for r in rows)
        self.assertEqual(minutes, 1440)
        self.assertEqual(mwh, 16384)

    def test_every_interval_has_v_and_current(self):
        for r in bms.build(bms.load_anchors()):
            self.assertGreater(float(r["avg_ma"]), 0)
            self.assertGreater(float(r["v_used_v"]), 4.5)


if __name__ == "__main__":
    unittest.main()
