#!/usr/bin/env python3
"""仓库级检查：Markdown 相对链接 + 暂存区大文件。

02-20Days-Challenge 的 measurement/verify.py 只覆盖该目录（且跳过 docs/figures），
本脚本覆盖全仓库，作为 `make check` 的入口。只用标准库，不读网络。

用法:
  python3 tools/check_repo.py
  python3 tools/check_repo.py --max-mb 25
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", ".arduino", "target", "__pycache__"}
LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def md_files():
    return [p for p in ROOT.rglob("*.md")
            if not SKIP_DIRS & set(p.relative_to(ROOT).parts)]


def check_links(files):
    """返回断链列表；http(s) / mailto / 纯锚点不检查。"""
    missing = []
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in LINK.finditer(text):
            target = m.group(1).strip().split("#")[0].strip().strip("<>")
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if not (p.parent / target).resolve().exists():
                missing.append(f"{p.relative_to(ROOT)} -> {target}")
    return missing


def staged_files():
    """本次即将提交的新增 / 修改 / 重命名文件（不含删除）。"""
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=AMR", "-z"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    return [rel for rel in proc.stdout.split("\0") if rel]


def check_staged_size(max_mb):
    """检查暂存区单文件大小；git 不可用时返回 None（不算失败）。"""
    files = staged_files()
    if files is None:
        return None
    oversize = []
    for rel in files:
        path = ROOT / rel
        if path.is_file():
            mb = path.stat().st_size / 1048576
            if mb > max_mb:
                oversize.append(f"{rel}（{mb:.1f} MB）")
    return oversize


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-mb", type=float, default=25.0,
                    help="暂存区单文件上限（MB），默认 25")
    args = ap.parse_args()

    files = md_files()
    missing = check_links(files)
    print(f"[{'PASS' if not missing else 'FAIL'}] markdown 相对链接（{len(files)} 个文件）")
    for item in missing:
        print(f"  断链: {item}")

    oversize = check_staged_size(args.max_mb)
    if oversize is None:
        print("[SKIP] 暂存区大文件（git 不可用）")
    else:
        print(f"[{'PASS' if not oversize else 'FAIL'}] 暂存区单文件 ≤ {args.max_mb:.0f} MB")
        for item in oversize:
            print(f"  过大: {item}，先压缩或外置（见 README 第 6 节）")

    if missing or oversize:
        return 1
    print("仓库检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
