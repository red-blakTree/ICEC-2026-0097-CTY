#!/usr/bin/env python3
"""把 web/index.html 压成 gzip 后打包成 sketch 里的 web_page.h（C 数组常量）。

改完网页后跑一次：

    python3 web/build_header.py

生成内容一起提交，这样 arduino-cli 不跑脚本也能编译。
用 gzip 是因为页面 10 KB 左右，2.4 GHz 弱链路上大响应经常传不完；压到 ~3.9 KB
明显更容易一次发完，浏览器会自动解压。
"""
import gzip
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "index.html"
DST = HERE.parent / "web_page.h"


def main():
    html = SRC.read_text(encoding="utf-8")
    raw = html.encode("utf-8")
    gz = gzip.compress(raw, 9, mtime=0)

    lines = ["// 由 web/build_header.py 从 web/index.html 生成，不要手改",
             f"// 原始 {len(raw)} B，gzip {len(gz)} B",
             "static const uint8_t kIndexHtmlGz[] PROGMEM = {"]
    for i in range(0, len(gz), 16):
        lines.append("  " + ",".join(str(b) for b in gz[i:i + 16]) + ",")
    lines.append("};")
    DST.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{SRC.name} ({len(raw)} B) -> {len(gz)} B gzip -> {DST.name}")


if __name__ == "__main__":
    main()
