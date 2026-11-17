#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用纯 PIL 生成 README 用的 5 张中文证据图。

运行（宿主机有 PIL 12.3 和中文字体）：
  distrobox-host-exec python3 /home/binarytree/.fedora/ICEC-2026-0097-CTY/02-20Days-Challenge/measurement/make_figures.py

只读取 evidence/ 下的原始证据，只写 docs/figures/*.png。
fig1 的两张表盘照片只做旋转/裁剪/等比缩放，不改动读数像素。
"""

from pathlib import Path
import math

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
EVID = ROOT / "evidence"
OUT = ROOT / "docs" / "figures"

FONT_CN = "/home/binarytree/.local/share/fonts/minecraft/msyh.ttc"
FONT_CN_B = "/home/binarytree/.local/share/fonts/minecraft/msyhbd.ttc"
FONT_MONO = "/usr/share/fonts/MapleMono/MapleMono-NF-CN-Regular.ttf"
FONT_MONO_B = "/usr/share/fonts/MapleMono/MapleMono-NF-CN-Bold.ttf"

NAVY = (31, 58, 95)
GREEN = (46, 125, 50)
GREEN_DARK = (27, 94, 32)
GREEN_LIGHT = (200, 230, 201)
RED = (198, 40, 40)
BLUE = (21, 101, 192)
GRAY = (102, 102, 102)
GRAY_LIGHT = (158, 164, 170)
GRID = (228, 232, 237)
INK = (33, 38, 45)
WHITE = (255, 255, 255)

W, H = 1600, 900

_font_cache = {}


def F(kind, size):
    """按用途取字体；kind: cn / cn_b / mono / mono_b。"""
    path = {
        "cn": FONT_CN,
        "cn_b": FONT_CN_B,
        "mono": FONT_MONO,
        "mono_b": FONT_MONO_B,
    }[kind]
    key = (path, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(path, size, index=0)
    return _font_cache[key]


def text(d, xy, s, font, fill, anchor="la", stroke=0, stroke_fill=WHITE):
    d.text(xy, s, font=font, fill=fill, anchor=anchor,
           stroke_width=stroke, stroke_fill=stroke_fill)


def length(d, s, font):
    return d.textlength(s, font=font)


def fit_size(d, s, kind, max_width, start, minimum=16):
    size = start
    while size > minimum:
        if length(d, s, F(kind, size)) <= max_width:
            return size
        size -= 1
    return minimum


def header(d, title, subtitle, index, w=W):
    size = fit_size(d, title, "cn_b", w - 240, 44, 26)
    text(d, (80, 46), title, F("cn_b", size), NAVY)
    text(d, (w - 80, 52), f"图 {index} / 5", F("cn", 20), GRAY_LIGHT, "ra")
    ssize = fit_size(d, subtitle, "cn", w - 200, 22, 15)
    text(d, (80, 108), subtitle, F("cn", ssize), GRAY)
    d.line([(80, 156), (w - 80, 156)], fill=(226, 231, 237), width=2)


def footer(d, w=W, h=H):
    text(d, (w - 80, h - 26), "数据与出处见 02-20Days-Challenge/README.md",
         F("cn", 18), GRAY_LIGHT, "ra")


def fit_image(im, max_w, max_h):
    ratio = min(max_w / im.width, max_h / im.height)
    return im.resize((max(1, round(im.width * ratio)), max(1, round(im.height * ratio))),
                     Image.Resampling.LANCZOS)


def arrow(d, x1, y1, x2, y2, color, width=8, head=22):
    d.line([(x1, y1), (x2, y2)], fill=color, width=width)
    angle = math.atan2(y2 - y1, x2 - x1)
    p1 = (x2, y2)
    p2 = (x2 - head * math.cos(angle - 0.45), y2 - head * math.sin(angle - 0.45))
    p3 = (x2 - head * math.cos(angle + 0.45), y2 - head * math.sin(angle + 0.45))
    d.polygon([p1, p2, p3], fill=color)


# ---------------------------------------------------------------- fig 1

def fig1():
    base_src = Image.open(EVID / "baseline-viewer-meter-2026-11-10" / "frame_meter_zoom.jpg").convert("RGB")
    # 原图整体旋转了 90°（顺时针），先转正，再只裁表盘区域。
    base_disp = base_src.transpose(Image.Transpose.ROTATE_90).crop((195, 675, 1265, 1130))
    ps_src = Image.open(EVID / "powersave-meter-2026-11-10" / "frame_meter_zoom.jpg").convert("RGB")

    img = Image.new("RGB", (W, 1000), WHITE)
    d = ImageDraw.Draw(img)
    header(d, "同一块 USB 表、同一块板：基线常开 vs 省电版深睡",
           "表盘实拍对比 · 5 V 输入侧 · 2026-11-10 现场 · 左：0.09 A / 5.04 V / 0.45 W · 右：0.00 A / 4.90 V / 0.00 W", 1)
    footer(d, h=1000)

    # 两块照片卡片
    cards = [
        (70, 240, 720, 350, RED, "基线常开", "WiFi 常开 · 每小时一张"),
        (810, 240, 720, 350, GREEN, "省电版深睡", "15 min 窗口后进入深睡"),
    ]
    photos = [base_disp, ps_src]
    labels = [("0.09 A", "5.04 V · 0.45 W", "累计 64 mWh · 表计时 0:08",
               "2026-11-10 21:02 · 基线 WiFi 常开", RED),
              ("0.00 A", "4.90 V · 0.00 W", "表累计不显示（##### mWh）",
               "2026-11-10 · 30 s 深睡档", GREEN)]
    for (x, y, w, h, color, title, sub), photo, lab in zip(cards, photos, labels):
        d.rounded_rectangle([x + 4, y + 6, x + w + 4, y + h + 6], radius=16, fill=(238, 241, 244))
        d.rounded_rectangle([x, y, x + w, y + h], radius=16, fill=WHITE, outline=(223, 228, 233), width=2)
        d.rounded_rectangle([x + 3, y + 16, x + 13, y + h - 16], radius=5, fill=color)
        text(d, (x + 34, y - 70), title, F("cn_b", 30), color)
        text(d, (x + 34, y - 30), sub, F("cn", 17), GRAY)

        inner_w, inner_h = w - 62, h - 36
        pic = fit_image(photo, inner_w, inner_h)
        px = x + 30 + (inner_w - pic.width) // 2
        py = y + 18 + (inner_h - pic.height) // 2
        img.paste(pic, (px, py))

        cx = x + w // 2
        top = y + h + 14
        text(d, (cx, top), lab[0], F("mono_b", 62), lab[4], "ma")
        text(d, (cx, top + 78), lab[1], F("mono", 27), NAVY, "ma")
        text(d, (cx, top + 118), lab[2], F("cn", 21), GRAY, "ma")
        text(d, (cx, top + 150), lab[3], F("cn", 19), GRAY_LIGHT, "ma")

    text(d, (80, 838), "对比照仅做旋转、裁剪与等比缩放，未改动表盘读数像素。",
         F("cn", 18), GRAY)
    text(d, (80, 866),
         "深睡档 0.00 A 是 0.01 A 表分辨率的读数，含义为平均电流 < 10 mA；该档能量累计不进位（##### mWh）。",
         F("cn", 18), GRAY)
    return img


# ---------------------------------------------------------------- fig 2

def fig2():
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    header(d, "24h 表累计 16.384 Wh ≈ 136 mA 平均（2026-11-10 20:54 → 11-11 20:54）",
           "表累计读数（5 V 输入侧）· 5 个实测点连成分段折线，4 段区间电流由相邻累计量反推 · 阴影为 08:20–12:08 断网段", 2)
    footer(d)

    left, right = 170, 1105
    top, bottom = 278, 735
    ymax = 18000

    def px(hours):
        return left + hours / 24.0 * (right - left)

    def py(mwh):
        return bottom - mwh / ymax * (bottom - top)

    # 断网段阴影（08:20 = 8.33 h，12:08 = 15.13 h）
    x1, x2 = px(8.333), px(15.133)
    d.rectangle([x1, top, x2, bottom], fill=(253, 237, 237))
    text(d, ((x1 + x2) / 2, top + 12), "WiFi 断网段", F("cn_b", 20), RED, "ma")
    text(d, ((x1 + x2) / 2, top + 40), "08:20 – 12:08", F("mono", 17), RED, "ma")
    text(d, ((x1 + x2) / 2, top + 64), "表读 0.18 A", F("cn", 16), (170, 90, 90), "ma")

    # 网格与坐标轴
    for v in range(0, 18001, 3000):
        y = py(v)
        d.line([(left, y), (right, y)], fill=GRID if v else (170, 176, 184), width=1)
        text(d, (left - 14, y), f"{v // 1000}k" if v else "0", F("mono", 18), GRAY, "rm")
    text(d, (left - 14, top - 18), "累计 mWh", F("cn", 17), GRAY, "rm")
    for v in range(0, 25, 4):
        x = px(v)
        d.line([(x, bottom), (x, bottom + 6)], fill=(170, 176, 184), width=1)
        text(d, (x, bottom + 16), f"{v}h", F("mono", 18), GRAY, "ma")
    text(d, ((left + right) / 2, bottom + 52), "自 2026-11-10 20:54 起算（墙钟 24 h）",
         F("cn", 17), GRAY, "ma")

    # 分段累计曲线：4 段折线，斜率即区间平均电流
    pts = [(0.0, 0), (0.133, 64), (15.167, 8508), (15.233, 8567), (24.0, 16384)]
    poly = [(px(h), py(v)) for h, v in pts]
    d.polygon([(px(0), bottom)] + poly + [(px(24), bottom)], fill=(235, 243, 251))
    d.line(poly, fill=BLUE, width=5, joint="curve")

    # 区间电流标注
    def seg_y(h, v0, v1, h0, h1):
        return py(v0 + (v1 - v0) * (h - h0) / (h1 - h0))

    text(d, (px(7.7), seg_y(7.7, 64, 8508, 0.133, 15.167) - 26), "区间均 112 mA",
         F("mono_b", 19), BLUE, "mm", stroke=3)
    text(d, (px(19.2), seg_y(19.2, 8567, 16384, 15.233, 24.0) - 38), "区间均 177 mA",
         F("mono_b", 19), BLUE, "mm", stroke=3)

    # 锚点
    for h, v in pts:
        x, y = px(h), py(v)
        d.ellipse([x - 7, y - 7, x + 7, y + 7], fill=WHITE, outline=BLUE, width=4)

    text(d, (px(0) + 14, py(0) - 12), "起读 0", F("mono", 17), BLUE)
    text(d, (px(0.133) + 12, py(64) - 46), "64 mWh · 21:02", F("mono", 17), BLUE)
    text(d, (px(15.167) - 16, py(8508) - 46), "8508 mWh · 12:04",
         F("mono", 17), BLUE, "ra", stroke=3)
    d.line([(px(15.167) - 8, py(8508) - 10), (px(15.167) - 12, py(8508) - 32)],
           fill=(120, 160, 210), width=1)
    text(d, (px(15.233) + 18, py(8567) + 30), "8567 mWh · 12:08",
         F("mono", 17), BLUE, "la", stroke=3)
    d.line([(px(15.233) + 8, py(8567) + 8), (px(15.233) + 14, py(8567) + 24)],
           fill=(120, 160, 210), width=1)
    text(d, (px(24) - 14, py(16384) - 40), "16384 mWh · 24 h",
         F("mono_b", 18), BLUE, "ra", stroke=3)

    # 右侧区间表
    cx = 1140
    text(d, (cx, 296), "区间平均电流", F("cn_b", 22), NAVY)
    text(d, (cx, 326), "由相邻累计量反推（5.04 V）", F("cn", 16), GRAY)
    rows = [("0 → 0.13 h", "95 mA", "0 → 64 mWh"),
            ("0.13 → 15.17 h", "112 mA", "64 → 8508 mWh"),
            ("15.17 → 15.23 h", "176 mA", "8508 → 8567 mWh"),
            ("15.23 → 24 h", "177 mA", "8567 → 16384 mWh")]
    for i, (span, cur, en) in enumerate(rows):
        y = 360 + i * 72
        d.rounded_rectangle([cx, y, cx + 390, y + 60], radius=8, fill=(247, 249, 252))
        d.rounded_rectangle([cx + 12, y + 14, cx + 16, y + 46], radius=2, fill=BLUE)
        text(d, (cx + 28, y + 9), span, F("mono", 17), GRAY)
        text(d, (cx + 28, y + 30), cur, F("mono_b", 24), BLUE)
        text(d, (cx + 378, y + 34), en, F("mono", 14), GRAY, "ra")
    text(d, (cx, 662), "136 mA = 16384 mWh ÷ 24 h ÷ 5.04 V", F("mono", 14), GRAY)
    text(d, (cx, 686), "断网段按表读 0.18 A；重连后仍间歇回到 0.18 A 档。", F("cn", 15), GRAY)
    return img


# ---------------------------------------------------------------- fig 3

def fig3():
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    header(d, "24h 占空比：基线 WiFi 常开 100%，省电版深睡 98.92%",
           "省电版 24 h = 15 min 窗口 + 24 次唤醒（1.4 s/次）+ 深睡 · 5 V 输入侧实测/推算", 3)
    footer(d)

    x0, x1 = 300, 1280
    total = x1 - x0

    # 基线
    text(d, (80, 330), "基线", F("cn_b", 30), RED)
    text(d, (80, 370), "WiFi 常开", F("cn", 20), GRAY)
    text(d, (80, 398), "无休眠", F("cn", 18), GRAY_LIGHT)
    d.rectangle([x0, 330, x1, 422], fill=RED)
    text(d, ((x0 + x1) / 2, 376), "90 mA", F("mono_b", 36), WHITE, "mm")
    text(d, (x1 - 22, 376), "100%", F("mono_b", 26), WHITE, "rm")
    text(d, ((x0 + x1) / 2, 446), "占空比 100%：WiFi 常开，无窗口、无深睡",
         F("cn", 17), GRAY, "ma")

    # 省电版
    text(d, (80, 540), "省电版", F("cn_b", 30), GREEN)
    text(d, (80, 580), "窗口 / 唤醒", F("cn", 20), GRAY)
    text(d, (80, 608), "/ 深睡", F("cn", 20), GRAY)

    win = total * 0.0104
    wake = total * 0.00039
    deep = total - win - wake
    d.rectangle([x0, 540, x0 + win, 632], fill=GREEN_DARK)
    d.rectangle([x0 + win, 540, x0 + win + max(wake, 2), 632], fill=BLUE)
    d.rectangle([x0 + win + max(wake, 2), 540, x1, 632], fill=GREEN_LIGHT)
    text(d, (x0 + win + max(wake, 2) + deep / 2, 586),
         "深睡 6 mA · 98.92%（85 466 s / 24 h）", F("cn_b", 23), GREEN_DARK, "mm")
    text(d, (x1 - 18, 586), "98.92%", F("mono_b", 20), GREEN_DARK, "rm")

    # 小段引线标注
    text(d, (x0 + 10, 466), "窗口 95 mA · 1.04%（900 s / 24 h）", F("cn", 20), GREEN_DARK)
    d.line([(x0 + 26, 494), (x0 + 26, 516), (x0 + win / 2, 540)],
           fill=GREEN_DARK, width=2)
    d.ellipse([x0 + win / 2 - 4, 536, x0 + win / 2 + 4, 544], fill=GREEN_DARK)

    text(d, (x0 + 34, 674), "唤醒 145 mA · 0.039%（24 × 1.4 s ≈ 33.6 s）", F("cn", 20), BLUE)
    d.line([(x0 + 26, 674), (x0 + 26, 652), (x0 + win + 2, 632)],
           fill=BLUE, width=2)
    d.ellipse([x0 + win + wake - 2, 628, x0 + win + wake + 6, 636], fill=BLUE)

    text(d, (x0 - 10, 716), "0%", F("mono", 18), GRAY, "ra")
    text(d, (x1 + 10, 716), "100%", F("mono", 18), GRAY, "la")

    text(d, (x0, 796),
         "省电版：窗口 1.04% + 唤醒 0.039% = 1.08%，其余 98.92% 在深睡；窗口 + 唤醒电量 25.1 mAh，占 24 h 167.5 mAh 的 15%。",
         F("cn", 18), GRAY)


    # 右侧 24h 平均
    bx = 1300
    d.rounded_rectangle([bx, 330, 1530, 632], radius=14, fill=(241, 248, 233),
                        outline=(200, 230, 201), width=2)
    text(d, (bx + 20, 356), "24 h 平均", F("cn_b", 20), GRAY)
    text(d, (bx + 18, 386), "6.98", F("mono_b", 52), GREEN)
    text(d, (bx + 152, 418), "mA", F("mono_b", 22), GREEN, "ls")
    text(d, (bx + 20, 470), "基线 90 mA", F("cn", 18), GRAY)
    text(d, (bx + 20, 500), "12.9×", F("mono_b", 30), GREEN)
    text(d, (bx + 20, 540), "（深睡按手册", F("cn", 14), GRAY)
    text(d, (bx + 20, 560), "6 mA 口径）", F("cn", 14), GRAY)
    d.line([(bx + 20, 590), (bx + 210, 590)], fill=(200, 220, 195), width=1)
    text(d, (bx + 20, 602), "24 h 电量 167.5 mAh", F("mono", 14), GRAY)
    return img


# ---------------------------------------------------------------- fig 4

def fig4():
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    header(d, "24h 电量预算：2160 mAh → 167.5 mAh（12.9×）",
           "按 24 h 平均电流折算（5 V 输入侧）· 省电版 = 窗口 23.75 + 唤醒 1.36 + 深睡 142.4 mAh", 4)
    footer(d)

    left, right = 170, 980
    top, bottom = 300, 760
    ymax = 2400

    def py(v):
        return bottom - v / ymax * (bottom - top)

    for v in range(0, 2401, 600):
        y = py(v)
        d.line([(left, y), (right, y)], fill=GRID if v else (170, 176, 184), width=1)
        text(d, (left - 14, y), f"{v}", F("mono", 18), GRAY, "rm")
    text(d, (left - 14, top - 22), "24 h 电量 / mAh", F("cn", 17), GRAY, "rm")

    # 基线柱
    bx = 250
    text(d, (bx + 95, py(2160) - 40), "2160 mAh", F("mono_b", 30), RED, "ma")
    d.rectangle([bx, py(2160), bx + 190, bottom], fill=RED)
    text(d, (bx + 95, 780), "90 mA × 24 h", F("mono", 17), GRAY, "ma")

    # 省电版柱（三段，深睡在下）
    px0 = 610
    wake_h = max(py(142.4 + 23.75) - py(167.5), 2)
    d.rectangle([px0, py(142.4), px0 + 190, bottom], fill=GREEN_LIGHT)
    d.rectangle([px0, py(166.15), px0 + 190, py(142.4)], fill=GREEN)
    d.rectangle([px0, py(167.5), px0 + 190, py(167.5) + wake_h], fill=BLUE)
    text(d, (px0 + 95, py(167.5) - 38), "167.5 mAh", F("mono_b", 30), GREEN, "ma")
    text(d, (px0 + 95, 780), "6.98 mA × 24 h", F("mono", 17), GRAY, "ma")

    # 中间箭头
    arrow(d, 455, 604, 595, 604, GREEN, width=9, head=24)
    text(d, (525, 478), "12.9×", F("mono_b", 54), GREEN, "mm")
    text(d, (525, 534), "基线 ÷ 省电版", F("cn", 15), GRAY, "mm")

    # 右侧放大插图
    ix0, iy0, ix1, iy1 = 1010, 300, 1530, 760
    d.rounded_rectangle([ix0, iy0, ix1, iy1], radius=14, fill=(250, 251, 252),
                        outline=(223, 228, 233), width=2)
    text(d, (ix0 + 24, iy0 + 20), "省电版 167.5 mAh 分解（放大）", F("cn_b", 20), NAVY)
    text(d, (ix0 + 24, iy0 + 50), "同一 24 h 口径，横向按比例展开", F("cn", 14), GRAY)

    bar_x0, bar_x1 = ix0 + 40, ix1 - 60
    bar_w = bar_x1 - bar_x0
    seg_deep = bar_w * 142.44 / 167.51
    seg_win = bar_w * 23.75 / 167.51
    seg_wake = bar_w * 1.36 / 167.51
    by = iy0 + 170
    d.rectangle([bar_x0, by, bar_x0 + seg_deep, by + 74], fill=GREEN_LIGHT)
    d.rectangle([bar_x0 + seg_deep, by, bar_x0 + seg_deep + seg_win, by + 74], fill=GREEN)
    d.rectangle([bar_x0 + seg_deep + seg_win, by, bar_x0 + seg_deep + seg_win + max(seg_wake, 4), by + 74], fill=BLUE)
    text(d, (bar_x0, by - 36), "合计 167.5 mAh", F("mono_b", 22), GREEN)
    text(d, (bar_x0 + seg_deep / 2, by + 37), "深睡 142.4 mAh", F("cn_b", 20), GREEN_DARK, "mm")

    rows = [("深睡 6 mA", "142.4 mAh", GREEN_LIGHT, GREEN_DARK),
            ("窗口 95 mA", "23.75 mAh", GREEN, WHITE),
            ("唤醒 145 mA", "1.36 mAh", BLUE, WHITE)]
    for i, (name, val, sw, fg) in enumerate(rows):
        y = iy0 + 300 + i * 36
        d.rectangle([bar_x0, y, bar_x0 + 18, y + 18], fill=sw)
        text(d, (bar_x0 + 30, y - 1), name, F("cn", 17), GRAY)
        text(d, (bar_x1, y - 1), val, F("mono_b", 18), fg if fg != WHITE else INK, "ra")
    d.line([(bar_x0, iy0 + 408), (bar_x1, iy0 + 408)], fill=(213, 220, 226), width=1)
    text(d, (bar_x0, iy0 + 420), "合计", F("cn_b", 17), NAVY)
    text(d, (bar_x1, iy0 + 420), "167.5 mAh", F("mono_b", 19), GREEN, "ra")

    text(d, (80, 812),
         "省电版三段：窗口 0.25 h × 95 mA = 23.75；唤醒 24 × 1.4 s × 145 mA ≈ 1.36；深睡 23.74 h × 6 mA = 142.4 mAh。",
         F("cn", 17), GRAY)
    text(d, (80, 840), "12.9× = 2160 ÷ 167.5，是计算值；基线按健康空闲 90 mA 折算。",
         F("cn", 17), GRAY)
    return img


# ---------------------------------------------------------------- fig 5

def fig5():
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    header(d, "分组电流对比：冷启动 / 拍照写卡 / 常开空闲 / 深睡 / 24h 平均",
           "5 V 输入侧 · 对数刻度 1–200 mA · 范围条=实测区间，点值画成条形 · 红=基线，绿=省电版", 5)
    footer(d)

    # 图例
    lx = 1050
    d.rounded_rectangle([lx, 186, lx + 18, 204], radius=3, fill=RED)
    text(d, (lx + 26, 184), "基线（WiFi 常开）", F("cn", 18), GRAY)
    d.rounded_rectangle([lx + 210, 186, lx + 228, 204], radius=3, fill=GREEN)
    text(d, (lx + 236, 184), "省电版", F("cn", 18), GRAY)

    left, right = 300, 1300
    top, bottom = 252, 722
    decades = (right - left) / math.log10(200)

    def px(v):
        return left + math.log10(max(v, 1)) * decades

    for v in (1, 10, 100):
        x = px(v)
        d.line([(x, top), (x, bottom)], fill=GRID, width=1)
        d.line([(x, bottom), (x, bottom + 6)], fill=(170, 176, 184), width=1)
        text(d, (x, bottom + 16), str(v), F("mono", 19), GRAY, "ma")
    d.line([(left, bottom), (right, bottom)], fill=(170, 176, 184), width=2)
    text(d, (left - 18, top), "mA", F("mono", 17), GRAY, "ra")
    text(d, ((left + right) / 2, bottom + 54), "电流（mA，5 V 输入侧，对数刻度）",
         F("cn", 17), GRAY, "ma")

    groups = [
        ("P1", "冷启动", "range", (90, 150), "range", (90, 150)),
        ("P3", "拍照 + 写卡", "range", (100, 130), "range", (130, 160)),
        ("P6", "常开空闲", "point", 90, "point", 95),
        ("P4", "深睡", "none", None, "bound", (6, 10)),
        ("24h", "平均", "point", 90, "bound", (6.98, 10.94)),
    ]

    for i, (code, name, bkind, bval, pkind, pval) in enumerate(groups):
        cy = top + 47 + i * 94
        text(d, (288, cy - 26), code, F("mono_b", 26), NAVY, "ra")
        text(d, (288, cy + 2), name, F("cn", 20), GRAY, "ra")

        # 基线
        yb = cy - 14
        if bkind == "range":
            lo, hi = bval
            d.rounded_rectangle([px(lo), yb - 11, px(hi), yb + 11], radius=6, fill=RED)
            text(d, (px(hi) + 10, yb), f"{lo}–{hi} mA", F("mono", 17), RED, "lm")
        elif bkind == "point":
            d.rounded_rectangle([left, yb - 11, px(bval), yb + 11], radius=6, fill=RED)
            text(d, (px(bval) + 10, yb), f"{bval} mA", F("mono", 17), RED, "lm")
        else:
            text(d, (left + 6, yb), "不适用（基线不休眠）", F("cn", 18), GRAY_LIGHT, "lm")

        # 省电版
        yp = cy + 14
        if pkind == "range":
            lo, hi = pval
            d.rounded_rectangle([px(lo), yp - 11, px(hi), yp + 11], radius=6, fill=GREEN)
            text(d, (px(hi) + 10, yp), f"{lo}–{hi} mA", F("mono", 17), GREEN, "lm")
        elif pkind == "point":
            d.rounded_rectangle([left, yp - 11, px(pval), yp + 11], radius=6, fill=GREEN)
            text(d, (px(pval) + 10, yp), f"{pval} mA", F("mono", 17), GREEN, "lm")
        else:
            lo, hi = pval
            d.rounded_rectangle([px(lo), yp - 11, px(hi), yp + 11], radius=6, fill=GREEN_LIGHT)
            d.ellipse([px(lo) - 6, yp - 6, px(lo) + 6, yp + 6], fill=GREEN)
            if code == "P4":
                text(d, (px(hi) + 10, yp), "6 手册 / ≤10 表上界", F("cn", 16), GREEN, "lm")
            else:
                text(d, (px(hi) + 10, yp), "6.98 手册 / 10.94 表上界", F("cn", 16), GREEN, "lm")

    text(d, (80, 800),
         "P3 基线只有 1 s 表读 100–130 mA（不是 60–90 ms 平均）；省电版连拍 130–160 mA，两者不互换。P4 基线不适用（WiFi 常开、不休眠）。",
         F("cn", 16), GRAY)
    text(d, (80, 824),
         "P4 省电版 6 mA 为官方手册 Deep-Sleep 点值，≤10 mA 为 0.01 A 表分辨率上界；24h 平均 6.98 mA（手册口径）/ 10.94 mA（表上界）。",
         F("cn", 16), GRAY)
    text(d, (80, 848),
         "24h 平均基线取健康空闲 90 mA；本轮含 12.6 h 断网的 24 h 表测为 136 mA（见 fig2），不混用两个口径。",
         F("cn", 16), GRAY)
    return img


# ---------------------------------------------------------------- main

FIGS = [
    ("fig1-meter-compare.png", fig1),
    ("fig2-24h-energy.png", fig2),
    ("fig3-duty-cycle.png", fig3),
    ("fig4-energy-budget.png", fig4),
    ("fig5-stage-current.png", fig5),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, _ in FIGS:
        p = OUT / name
        if p.exists():
            p.unlink()
    for name, fn in FIGS:
        img = fn()
        path = OUT / name
        img.save(path, "PNG", optimize=True)
        print(f"{name}: {img.width}x{img.height}, {path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
