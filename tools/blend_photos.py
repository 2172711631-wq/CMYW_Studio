#!/usr/bin/env python3
"""把实拍照片融进站点夜色 / Blend product photos into the site's night palette.

问题：实拍照片各有各的房间背景（书桌、显示器、墙），直接放到深色页面上
像贴了几张卡片，很突兀。

第一版试过按「发光面板」分割，清晰保留面板、模糊其余部分。这条路走不通：
分割一旦不准就会留下硬边 —— 桌面被切出斜边、面板贴到画幅边缘导致淡出
没走完就被截断，反而比不处理更难看。掩码越努力，失败时越显眼。

现在的做法完全不依赖分割：以画面中心为原点，向外**连续**地
  · 加深模糊
  · 偏向站点底色
  · 降低不透明度
三者由同一条平滑曲线驱动，结构上就不可能出现硬边。画幅四周还会补一圈
底色留白，保证淡出一定能在画布内完成。

用法 / Usage:
    py -3.11 tools/blend_photos.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "web" / "photos"
OUT_DIR = ROOT / "web" / "public" / "img"

# 站点底色 #161E36。OpenCV 用 BGR 排列。
NIGHT_BGR = np.array([54, 30, 22], np.float32)

# 画幅四周补多少留白（相对短边），给淡出留出空间
PAD_RATIO = 0.16

JOBS = [
    ("real-monalisa", "monalisa"),
    ("real-enel", "lit"),
    ("real-handheld", "handheld"),
    ("real-spongebob", "spongebob"),
]


def imread(path: Path) -> np.ndarray:
    """Windows 中文路径下 cv2.imread 常失败，改用 fromfile + imdecode。"""
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"无法读取 / cannot read: {path}")
    return img


def smoothstep(x: np.ndarray, a: float, b: float) -> np.ndarray:
    t = np.clip((x - a) / max(1e-6, b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def subject_center(bgr: np.ndarray) -> tuple[float, float]:
    """发光面板的重心。灯箱是画面里唯一在发光的物体，用亮度定位即可。

    这里只用它决定「哪里最清晰」，不用来抠图 —— 即使偏了几十像素，
    结果也只是景深中心稍微偏一点，不会产生硬边。
    """
    h, w = bgr.shape[:2]
    lightness = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)[..., 0]
    mask = (lightness >= np.percentile(lightness, 88)).astype(np.uint8)
    if mask.sum() < 50:
        return w / 2.0, h / 2.0
    ys, xs = np.nonzero(mask)
    return float(xs.mean()), float(ys.mean())


def blend_into_night(bgr: np.ndarray) -> np.ndarray:
    h0, w0 = bgr.shape[:2]
    cx0, cy0 = subject_center(bgr)

    # 四周补底色留白，确保淡出在画布内走完（否则贴边的照片会被硬生生截断）
    pad = int(min(h0, w0) * PAD_RATIO)
    canvas = np.empty((h0 + pad * 2, w0 + pad * 2, 3), np.float32)
    canvas[:] = NIGHT_BGR
    canvas[pad : pad + h0, pad : pad + w0] = bgr.astype(np.float32)
    h, w = canvas.shape[:2]
    cx, cy = cx0 + pad, cy0 + pad

    # 归一化椭圆距离：0 = 主体中心，1 ≈ 画布边缘
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dist = np.sqrt(((xx - cx) / (w * 0.55)) ** 2 + ((yy - cy) / (h * 0.55)) ** 2)

    # 一条曲线驱动全部三件事，因此不会出现互相错位的边界
    t = smoothstep(dist, 0.34, 0.92)[..., None]

    # 1) 景深：中心锐利，向外连续过渡到重模糊
    blurred = cv2.GaussianBlur(canvas, (0, 0), sigmaX=min(h, w) * 0.055)
    hsv = cv2.cvtColor(np.clip(blurred, 0, 255).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] *= 0.40  # 降饱和，去掉房间的杂色
    blurred = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)

    out = canvas * (1.0 - t) + blurred * t

    # 2) 调色：向站点底色偏移，边缘处几乎完全等于底色 —— 这样即使
    #    alpha 还没到 0，颜色也已经和页面一致，不会看出色块
    out = out * (1.0 - t * 0.92) + NIGHT_BGR * (t * 0.92)

    # 3) 淡出：比调色稍晚开始，让颜色先对齐再消失
    alpha = 1.0 - smoothstep(dist, 0.58, 1.02)

    return np.dstack([np.clip(out, 0, 255).astype(np.uint8), (alpha * 255).astype(np.uint8)])


def main() -> int:
    if not SRC_DIR.is_dir():
        print(f"找不到源图目录 / source dir missing: {SRC_DIR}", file=sys.stderr)
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for src, dst in JOBS:
        path = SRC_DIR / f"{src}.jpg"
        if not path.is_file():
            print(f"  跳过 / skip {src} (不存在)")
            continue
        blended = blend_into_night(imread(path))
        h, w = blended.shape[:2]
        ok, buf = cv2.imencode(".webp", blended, [int(cv2.IMWRITE_WEBP_QUALITY), 88])
        if not ok:
            print(f"  编码失败 / encode failed: {dst}", file=sys.stderr)
            continue
        out = OUT_DIR / f"{dst}.webp"
        buf.tofile(str(out))
        print(f"  {dst:10} {w}×{h}  比例 {w / h:.2f}  {out.stat().st_size / 1024:.0f} KB")

    print(f"\n输出 / output: {OUT_DIR}")
    print("页面上的 --ar 需要跟着更新（补白后比例会变）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
