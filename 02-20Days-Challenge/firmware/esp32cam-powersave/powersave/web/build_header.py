#!/usr/bin/env python3
"""把 web/index.html 打包成 sketch 里的 web_page.h（C 字符串常量）。

改完网页后跑一次：

    python3 web/build_header.py

生成的 web_page.h 与 web/index.html 一起提交，这样 arduino-cli 不跑脚本也能编译。
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "index.html"
DST = HERE.parent / "web_page.h"
DELIM = "WEBPAGE"


def main():
    html = SRC.read_text(encoding="utf-8")
    if f"){DELIM}\"" in html:
        raise SystemExit(f"index.html 里含结束定界符 {DELIM}，换个 DELIM 再生成")

    DST.write_text(
        "// 由 web/build_header.py 从 web/index.html 生成，不要手改\n"
        f"static const char kIndexHtml[] PROGMEM = R\"{DELIM}({html}){DELIM}\";\n",
        encoding="utf-8",
    )
    print(f"{SRC.name} ({len(html.encode('utf-8'))} B) -> {DST.name}")


if __name__ == "__main__":
    main()
