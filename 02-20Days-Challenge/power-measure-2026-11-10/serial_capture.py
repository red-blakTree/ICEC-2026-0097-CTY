#!/usr/bin/env python3
"""给串口每行打上宿主机时间戳（宿主机运行，无需 pyserial）。

用法:
  python3 serial_capture.py --seconds 600 --out coldboot.log
  python3 serial_capture.py            # 一直读到 Ctrl-C

输出格式: 2026-11-10 12:35:47.123|原始行
这样以后 phases.py 能按行时间切分阶段；TTL 只接 TX/RX/GND，不供电。
"""
import argparse
import os
import select
import sys
import termios
import time

TS_FMT = "%Y-%m-%d %H:%M:%S"


def open_port(port, baud):
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[3] = 0
    speed = getattr(termios, "B%d" % baud)
    attrs[4] = speed
    attrs[5] = speed
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    termios.tcflush(fd, termios.TCIOFLUSH)
    return fd


def emit(stream, stamp, line):
    text = "%s.%03d|%s\n" % (stamp.strftime(TS_FMT), stamp.microsecond // 1000, line)
    stream.write(text)
    stream.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=float, default=0, help="0 = 一直读")
    ap.add_argument("--out", default=None, help="同时写入该文件")
    args = ap.parse_args()

    fd = open_port(args.port, args.baud)
    out = open(args.out, "w") if args.out else None
    end = time.time() + args.seconds if args.seconds > 0 else None
    buf = bytearray()

    try:
        while end is None or time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.2)
            if not r:
                continue
            try:
                chunk = os.read(fd, 4096)
            except BlockingIOError:
                continue
            if not chunk:
                continue
            now = time.time()
            buf.extend(chunk)
            while b"\n" in buf:
                raw, _, rest = buf.partition(b"\n")
                buf = bytearray(rest)
                line = raw.decode("utf-8", "replace").rstrip("\r")
                stamp = time.localtime(now)
                emit(sys.stdout, stamp, line)
                if out:
                    emit(out, stamp, line)
    except KeyboardInterrupt:
        pass
    finally:
        if buf:
            stamp = time.localtime(time.time())
            emit(sys.stdout, stamp, buf.decode("utf-8", "replace"))
            if out:
                emit(out, stamp, buf.decode("utf-8", "replace"))
        os.close(fd)
        if out:
            out.close()


if __name__ == "__main__":
    main()
