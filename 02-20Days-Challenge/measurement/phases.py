#!/usr/bin/env python3
"""把带宿主机时间戳的串口日志切成 P1–P6 阶段，输出可填 V/I 的记录表。

输入: serial_capture.py 产出的日志，每行 `YYYY-MM-DD HH:MM:SS.mmm|原文`
输出: firmware,phase,start,end,dur_s,v_mv,i_mA_min,i_mA_avg,i_mA_max,e_mwh,note
      （v/i/e 列留空，实测读数自己补；可直接追加到 measure-record.csv）

用法:
  python3 phases.py coldboot.log
  python3 phases.py coldboot.log --append measure-record.csv
"""
import argparse
import csv
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta

TS = re.compile(r"^\[?(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)\]?\s*\|?\s?(.*)$")
CAP = re.compile(r"capture=(\d+)ms\s+save=(\d+)ms")
CAP_SIZE = re.compile(r"size=(\d+)B")
SLEEP = re.compile(r"\[SLEEP\]\s*深睡\s*(\d+)s")

HEADER = ["firmware", "phase", "start", "end", "dur_s",
          "v_mv", "i_mA_min", "i_mA_avg", "i_mA_max", "e_mwh", "note"]


@dataclass
class Capture:
    t_end: datetime
    shot_ms: int
    save_ms: int
    size: int | None

    @property
    def t_start(self):
        return self.t_end - timedelta(milliseconds=self.shot_ms + self.save_ms)


@dataclass
class Session:
    kind: str
    t0: datetime
    t_last: datetime
    caps: list = field(default_factory=list)
    web_on: datetime | None = None
    web_off: datetime | None = None
    sleep_t: datetime | None = None
    sleep_s: int | None = None


def parse(path):
    sessions, unparsed = [], 0
    cur = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            m = TS.match(line.rstrip("\n"))
            if not m:
                unparsed += 1
                continue
            ts = datetime.strptime(m.group(1) + " " + m.group(2), "%Y-%m-%d %H:%M:%S.%f"
                                   if "." in m.group(2) else "%Y-%m-%d %H:%M:%S")
            body = m.group(3)

            kind = None
            if "=== ESP32-CAM 省电版" in body:
                kind = "cold" if "冷启动" in body else "wake"
            elif "=== ESP32-CAM 采集查看器" in body:
                kind = "viewer"

            if kind:
                cur = Session(kind=kind, t0=ts, t_last=ts)
                sessions.append(cur)
                continue
            if cur is None:
                unparsed += 1
                continue
            cur.t_last = ts

            if "[CAP]" in body:
                c = CAP.search(body)
                if not c:
                    print("警告: 第 %d 行有 [CAP] 但没有 capture/save 字段" % lineno, file=sys.stderr)
                    continue
                s = CAP_SIZE.search(body)
                cur.caps.append(Capture(t_end=ts, shot_ms=int(c.group(1)),
                                        save_ms=int(c.group(2)),
                                        size=int(s.group(1)) if s else None))
            elif "[WEB]" in body and "http://" in body:
                cur.web_on = ts
            elif "[WEB]" in body and "窗口结束" in body:
                cur.web_off = ts
            elif SLEEP.search(body):
                cur.sleep_t = ts
                cur.sleep_s = int(SLEEP.search(body).group(1))

    if unparsed:
        print("提示: %d 行没有时间戳或不在任何会话内，已跳过" % unparsed, file=sys.stderr)
    if not sessions:
        sys.exit("错误: 日志里没有任何固件启动标记（=== ESP32-CAM ... ===），请检查串口接线或日志格式")
    return sessions


def rows_for(sessions):
    rows = []

    def fmt_ms(t):
        return t.strftime("%Y-%m-%d %H:%M:%S.") + "%03d" % (t.microsecond // 1000)

    def add(fw, phase, t0, t1, note=""):
        if t1 <= t0:
            return
        rows.append({
            "firmware": fw, "phase": phase,
            "start": fmt_ms(t0),
            "end": fmt_ms(t1),
            "dur_s": "%.1f" % (t1 - t0).total_seconds(),
            "note": note,
        })

    for i, s in enumerate(sessions):
        nxt = sessions[i + 1].t0 if i + 1 < len(sessions) else None

        if s.kind == "cold":
            cap = s.caps[0] if s.caps else None
            if cap:
                add("powersave", "P1 冷启动", s.t0, cap.t_start, "上电→拍照开始（init+WiFi+NTP）")
                add("powersave", "P3 拍照瞬间", cap.t_start, cap.t_end,
                    "size=%sB capture=%dms save=%dms" % (cap.size or "?", cap.shot_ms, cap.save_ms))
                p2_start = cap.t_end
            else:
                p2_start = s.web_on
                add("powersave", "P1 冷启动", s.t0, p2_start or s.t_last, "无 [CAP] 行，拍照可能失败")
            p2_end = s.web_off or s.sleep_t or (nxt or s.t_last)
            if s.web_on and p2_start and p2_end > p2_start:  # 没开过窗口（如“不开网页”测量档）就不记 P2
                add("powersave", "P2 窗口空闲", p2_start, p2_end,
                    "" if s.web_off else "窗口未正常关闭（断电/复位）")

        elif s.kind == "wake":
            cap = s.caps[0] if s.caps else None
            if cap:
                add("powersave", "P5 定时唤醒", s.t0, cap.t_end,
                    "size=%sB capture=%dms save=%dms（不连 WiFi）"
                    % (cap.size or "?", cap.shot_ms, cap.save_ms))
            else:
                add("powersave", "P5 定时唤醒", s.t0, s.sleep_t or (nxt or s.t_last), "无 [CAP] 行")

        elif s.kind == "viewer":
            fw = "viewer"
            gap = "P6 WiFi常开空闲"
            if not s.caps:
                add(fw, "P1 冷启动", s.t0, s.t_last, "无 [CAP] 行")
                continue
            add(fw, "P1 冷启动", s.t0, s.caps[0].t_start, "上电→拍照开始")
            for k, cap in enumerate(s.caps):
                note = "size=%sB capture=%dms save=%dms" % (cap.size or "?", cap.shot_ms, cap.save_ms)
                add(fw, "P3 拍照瞬间", cap.t_start, cap.t_end, note)
                gap_end = s.caps[k + 1].t_start if k + 1 < len(s.caps) else (nxt or s.t_last)
                add(fw, gap, cap.t_end, gap_end)

        if s.sleep_t:
            add("powersave", "P4 深睡", s.sleep_t, nxt or s.t_last,
                "计划深睡 %ss（表上取这段稳定值）" % (s.sleep_s or "?"))

    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--append", default=None, help="追加到记录表；不存在则新建并写表头")
    ap.add_argument("--summary", action="store_true", help="按阶段汇总到 stderr")
    args = ap.parse_args()

    rows = rows_for(parse(args.log))

    if args.append:
        new = not os.path.exists(args.append) or os.path.getsize(args.append) == 0
        with open(args.append, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=HEADER)
            if new:
                w.writeheader()
            w.writerows(rows)
        print("已写入 %d 行到 %s" % (len(rows), args.append))
    else:
        w = csv.DictWriter(sys.stdout, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)

    if args.summary:
        agg = {}
        for r in rows:
            k = (r["firmware"], r["phase"])
            n, t = agg.get(k, (0, 0.0))
            agg[k] = (n + 1, t + float(r["dur_s"]))
        print("\n阶段汇总:", file=sys.stderr)
        for (fw, ph), (n, t) in sorted(agg.items()):
            print("  %-10s %-16s %2d 段 %8.1f s" % (fw, ph, n, t), file=sys.stderr)


if __name__ == "__main__":
    main()
