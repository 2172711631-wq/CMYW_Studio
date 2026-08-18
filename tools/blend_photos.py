#!/usr/bin/env python3
"""把实拍照片融进站点夜色 / Blend product photos into the site's night palette.

问题：实拍照片各有各的房间背景（书桌、显示器、墙），直接放到深色页面上
像贴了几张卡片，很突兀。硬抠背景又会丢掉辉光和桌面反光 —— 那恰恰是这个
产品最好看的部分。

做法：发光面板保持锐利，背景重度模糊 + 降饱和 + 向站点靛蓝偏移，
最后按椭圆径向淡出到透明，让照片自然溶进页面。

用法 / Usage:
    py -3.11 tools/blend_photos.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "web" / "photos"          # 原始实拍照片
OUT_DIR_NOTE = "处理结果直接进 web/public/img，供页面引用"
OUT_DIR = ROOT / "web" / "public" / "img"

# 站点底色 #161E36，OpenCV 用 BGR
NIGHT_BGR = np.array([54, 30, 22], np.float32)

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


def largest_component(mask: np.ndarray) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if count <= 1:
        return mask
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return (labels == idx).astype(np.uint8) * 255


def panel_mask(bgr: np.ndarray) -> np.ndarray:
    """发光面板的实心掩码。灯箱是画面里唯一在发光的物体，靠亮度就能定位。"""
    h, w = bgr.shape[:2]
    lightness = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)[..., 0]

    mask = (lightness >= np.percentile(lightness, 86)).astype(np.uint8) * 255
    # 大核闭运算：把面板内部被暗部割裂的亮块连成一整块
    big = max(21, (min(h, w) // 18) | 1)
    mask = largest_component(
        cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((big, big), np.uint8), iterations=2)
    )

    # 补内部空洞：画片的暗部属于面板，不能被当成背景
    flood = mask.copy()
    cv2.floodFill(flood, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 255)
    mask = mask | cv2.bitwise_not(flood)

    # 平滑轮廓。不做凸包 —— 凸包会把面板和桌面反光并成一个楔形。
    small = max(9, (min(h, w) // 45) | 1)
    ellipse = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (small, small))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, ellipse, iterations=2)
    return largest_component(cv2.morphologyEx(mask, cv2.MORPH_OPEN, ellipse, iterations=1))


def blend_into_night(bgr: np.ndarray) -> np.ndarray:
    h, w = bgr.shape[:2]
    img = bgr.astype(np.float32)
    mask = panel_mask(bgr)

    ys, xs = np.where(mask > 0)
    cx, cy = float(xs.mean()), float(ys.mean())

    # 面板权重：本体为 1，向外柔和衰减
    sharp = np.clip(
        cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (0, 0), sigmaX=min(h, w) * 0.018) * 1.4,
        0.0,
        1.0,
    )[..., None]

    # 背景：重模糊 → 降饱和去掉房间杂色 → 压暗并向靛蓝偏移
    bg = cv2.GaussianBlur(img, (0, 0), sigmaX=min(h, w) * 0.05)
    hsv = cv2.cvtColor(np.clip(bg, 0, 255).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] *= 0.38
    bg = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)
    bg = bg * 0.34 + NIGHT_BGR * 0.66

    out = img * sharp + bg * (1.0 - sharp)

    # 椭圆径向淡出。矩形衰减会在四角拉出对角线，看起来像个相框。
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dist = np.sqrt(((xx - cx) / (w * 0.62)) ** 2 + ((yy - cy) / (h * 0.62)) ** 2)
    alpha = np.clip(np.maximum(1.0 - smoothstep(dist, 0.55, 1.0), sharp[..., 0]), 0.0, 1.0)

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

    print(f"\n输出目录 / output: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
