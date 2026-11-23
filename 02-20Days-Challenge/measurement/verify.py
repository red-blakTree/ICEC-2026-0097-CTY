#!/usr/bin/env python3
"""复核 02-20Days-Challenge 的关键数字与文件完整性。

只用标准库，不读网络。检查四类东西：
  1. 24 h 表实测区间序列是否与锚点重算一致、总量是否 16384 mWh；
  2. theory.py 的 24 h 预算是否仍落在 README 写的 6.98 / 10.94 mA；
  3. current-comparison.csv / POWER.CSV 的字段与行数；
  4. 所有 markdown 相对链接是否指向存在的文件。

用法:
  python3 measurement/verify.py
  python3 measurement/verify.py --manifest   # 额外校验 process_logs 的 SHA256
"""
import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import build_meter_series as bms  # noqa: E402
import theory  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((ok, name, detail))


def rows_of(path, **kw):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, **kw))


def check_meter_series():
    path = HERE / "24h-meter-series.csv"
    check("24h-meter-series.csv 存在", path.exists(), str(path.relative_to(ROOT)))
    if not path.exists():
        return
    written = rows_of(path)
    rebuilt = [{k: str(v) for k, v in r.items()} for r in bms.build(bms.load_anchors())]
    check("区间序列与表盘锚点重算一致", written == rebuilt,
          f"{len(written)} 行")

    minutes = sum(float(r["duration_min"]) for r in written)
    mwh = sum(int(r["delta_mwh"]) for r in written)
    avg_ma = (mwh / (minutes / 60.0)) / 5.04
    check("24 h 跨度", abs(minutes - 1440) < 1, f"{minutes:.0f} min")
    check("累计能量", mwh == 16384, f"{mwh} mWh")
    check("24 h 平均电流", abs(avg_ma - 135.4) < 0.2, f"{avg_ma:.1f} mA @5.04 V（≈140）")


def check_budget():
    b = theory.compute_budget()
    bmax = theory.compute_budget(i_sleep=10.0)
    check("默认口径 24 h 电量", abs(b["total_mah"] - 167.5) < 0.2,
          f"{b['total_mah']:.1f} mAh")
    check("默认口径平均电流", abs(b["avg_ma"] - 6.98) < 0.01,
          f"{b['avg_ma']:.3f} mA")
    check("表上界平均电流", abs(bmax["avg_ma"] - 10.94) < 0.01,
          f"{bmax['avg_ma']:.3f} mA")

    baseline_mah = 90.0 * 24
    ratio = baseline_mah / b["total_mah"]
    ratio_max = baseline_mah / bmax["total_mah"]
    check("相对基线倍数（6 mA 口径）", abs(ratio - 12.9) < 0.05, f"{ratio:.2f}×")
    check("相对基线倍数（10 mA 上界）", abs(ratio_max - 8.2) < 0.05,
          f"{ratio_max:.2f}×")

    b0 = theory.compute_budget(i_sleep=0.0)
    i_sleep_10x = (9.0 * 24 - b0["total_mah"]) * 3600 / b0["t_sleep_s"]
    check("达到 10× 所需深睡电流", abs(i_sleep_10x - 8.04) < 0.02,
          f"≤ {i_sleep_10x:.2f} mA")


def check_comparison():
    path = HERE / "current-comparison.csv"
    rows = rows_of(path)
    check("current-comparison.csv 行数", len(rows) == 12, f"{len(rows)} 行")
    need = {"stage", "quantity", "baseline_value", "baseline_unit",
            "baseline_v", "powersave_value", "powersave_unit",
            "powersave_v", "method", "evidence"}
    check("对照表字段完整", need <= set(rows[0]), ",".join(sorted(need - set(rows[0]))))
    stages = " ".join(r["stage"] for r in rows)
    for s in ("P1", "P3", "P4", "P5", "P6", "24 h"):
        check(f"对照表覆盖 {s}", s in stages)
    empty = [r["stage"] for r in rows
             if not r["baseline_value"].strip() or not r["powersave_value"].strip()]
    check("对照表无空值", not empty, "; ".join(empty))

    missing = []
    for r in rows:
        for rel in r["evidence"].split(";"):
            rel = rel.strip()
            if rel and not (HERE / rel).resolve().exists():
                missing.append(f"{r['stage']} -> {rel}")
    check("对照表证据路径存在", not missing, "\n  ".join(missing[:8]))


def check_power_logs():
    specs = {
        "process_logs/baseline-24h-2026-11-09/POWER.CSV": (322, 86400),
        "process_logs/baseline-24h-meter-2026-11-10/POWER.CSV": (317, 86400),
        "process_logs/powersave-15h-2026-11-10/POWER.CSV": (50, 900),
    }
    for rel, (n, uptime_min) in specs.items():
        path = ROOT / rel
        if not path.exists():
            check(f"{rel} 存在", False)
            continue
        rows = rows_of(path)
        header = path.read_text(encoding="utf-8").splitlines()[0]
        check(f"{rel} 表头", header == "uptime_s,event,window_s,v5_mv,i_ma,p_mw,e_mwh")
        check(f"{rel} 行数", len(rows) == n, f"{len(rows)}")
        events = {r["event"] for r in rows}
        check(f"{rel} 事件类型", events <= {"CAPTURE", "SAMPLE", "WEB_ON", "WEB_CLOSE"},
              ",".join(sorted(events)))
        try:
            max_up = max(int(r["uptime_s"]) for r in rows)
            check(f"{rel} 时间跨度", max_up >= uptime_min, f"{max_up} s")
        except ValueError:
            check(f"{rel} uptime 可解析", False)


def check_links():
    md_files = [p for p in ROOT.rglob("*.md")
                if ".arduino" not in p.parts and "docs/figures" not in p.as_posix()]
    pat = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
    missing = []
    for p in md_files:
        for m in pat.finditer(p.read_text(encoding="utf-8")):
            target = m.group(1).strip().split("#")[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = target.strip("<>")
            path = (p.parent / target).resolve()
            if not path.exists():
                missing.append(f"{p.relative_to(ROOT)} -> {target}")
    check("markdown 相对链接", not missing,
          f"{len(md_files)} 个文件；缺失 {len(missing)} 个\n  " + "\n  ".join(missing[:12]))


def check_manifest():
    for manifest in ROOT.glob("process_logs/*/manifest.sha256"):
        r = subprocess.run(["sha256sum", "-c", manifest.name],
                           cwd=manifest.parent, capture_output=True, text=True)
        ok = r.returncode == 0
        check(f"{manifest.parent.name}/manifest.sha256", ok,
              "" if ok else r.stderr.strip().splitlines()[-1:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", action="store_true", help="额外校验证据 SHA256")
    a = ap.parse_args()

    check_meter_series()
    check_budget()
    check_comparison()
    check_power_logs()
    check_links()
    if a.manifest:
        check_manifest()

    failed = [r for r in RESULTS if not r[0]]
    for ok, name, detail in RESULTS:
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {name}" + (f"  ({detail})" if detail else ""))
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} 通过")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
