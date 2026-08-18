#!/usr/bin/env python3
"""生成站点图标与分享卡 / Generate the favicon artwork and the link-preview card.

两样都是「不做就会被人看见」的东西：
  * 没有图标，浏览器标签上是一张白纸，而且每次访问都多一条 /favicon.ico 404
  * og:image 只要给不出一张 1.91:1 的图，分享到任何地方都是一条秃链接

分享卡不放文字：中文字要嵌字体才画得好看，与其画一行歪的，不如直接让三件
实物说话 —— 反正卡片旁边就是标题和描述。

用法 / Usage:
    py -3.11 tools/make_brand_assets.py
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "web" / "public" / "img"
PUBLIC = ROOT / "web" / "public"

# 站点底色 #161E36 与暖光 #FFB16B，OpenCV 用 BGR
NIGHT = (54, 30, 22)
GLOW = (107, 177, 255)

# 分享卡上用哪三张，以及顺序。挑的是冷 / 暖 / 中间调各一张，
# 让人一眼看出这不是只能打暖色调的东西。
COVER_SHOTS = ("shot8.webp", "shot7.webp", "shot5.webp")
COVER_W, COVER_H = 1200, 630


def imread(path: Path) -> np.ndarray:
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"读不出 / cannot read: {path}")
    return img


def rounded_mask(h: int, w: int, radius: int) -> np.ndarray:
    """圆角矩形的抗锯齿遮罩，0..1。用 4 倍超采样，边缘才不会有台阶。"""
    ss = 4
    m = np.zeros((h * ss, w * ss), np.uint8)
    cv2.rectangle(m, (0, 0), (w * ss - 1, h * ss - 1), 255, -1, cv2.LINE_AA)
    r = radius * ss
    if r > 0:
        m[:] = 0
        cv2.rectangle(m, (r, 0), (w * ss - 1 - r, h * ss - 1), 255, -1)
        cv2.rectangle(m, (0, r), (w * ss - 1, h * ss - 1 - r), 255, -1)
        for cx, cy in ((r, r), (w * ss - 1 - r, r), (r, h * ss - 1 - r), (w * ss - 1 - r, h * ss - 1 - r)):
            cv2.circle(m, (cx, cy), r, 255, -1)
    return cv2.resize(m, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0


def make_cover() -> None:
    canvas = np.zeros((COVER_H, COVER_W, 3), np.float32)
    canvas[:] = NIGHT

    # 背景先铺一层暖光晕，卡片才不像贴在纯色板上
    yy, xx = np.mgrid[0:COVER_H, 0:COVER_W].astype(np.float32)
    d = np.sqrt(((xx - COVER_W / 2) / (COVER_W * 0.62)) ** 2 + ((yy - COVER_H * 0.55) / (COVER_H * 0.9)) ** 2)
    halo = np.clip(1.0 - d, 0.0, 1.0)[..., None] ** 2
    canvas = canvas * (1 - halo * 0.5) + np.float32(GLOW) * halo * 0.5

    tile_h = 452
    gap = 44
    tiles = []
    for name in COVER_SHOTS:
        img = imread(IMG_DIR / name).astype(np.float32)
        h, w = img.shape[:2]
        tw = max(1, round(w * tile_h / h))
        tiles.append(cv2.resize(img, (tw, tile_h), interpolation=cv2.INTER_AREA))

    total = sum(t.shape[1] for t in tiles) + gap * (len(tiles) - 1)
    x = (COVER_W - total) // 2
    y = (COVER_H - tile_h) // 2

    for tile in tiles:
        th, tw = tile.shape[:2]
        mask = rounded_mask(th, tw, 14)[..., None]

        # 每张底下垫一层它自己的辉光：灯箱本来就会把桌面照亮
        glow = cv2.GaussianBlur(tile * mask, (0, 0), sigmaX=46)
        pad = 60
        gy0, gy1 = max(0, y - pad), min(COVER_H, y + th + pad)
        gx0, gx1 = max(0, x - pad), min(COVER_W, x + tw + pad)
        patch = np.zeros((gy1 - gy0, gx1 - gx0, 3), np.float32)
        patch[y - gy0 : y - gy0 + th, x - gx0 : x - gx0 + tw] = glow
        patch = cv2.GaussianBlur(patch, (0, 0), sigmaX=40)
        canvas[gy0:gy1, gx0:gx1] = np.clip(canvas[gy0:gy1, gx0:gx1] + patch * 0.42, 0, 255)

        region = canvas[y : y + th, x : x + tw]
        canvas[y : y + th, x : x + tw] = region * (1 - mask) + tile * mask
        x += tw + gap

    # 四周压暗一点，视线收回中间
    d2 = np.sqrt(((xx - COVER_W / 2) / (COVER_W / 2)) ** 2 + ((yy - COVER_H / 2) / (COVER_H / 2)) ** 2)
    vig = np.clip(1.0 - 0.30 * np.clip(d2, 0, 1.5) ** 2, 0.55, 1.0)[..., None]
    out = np.clip(canvas * vig, 0, 255).astype(np.uint8)

    dst = IMG_DIR / "og-cover.jpg"
    ok, buf = cv2.imencode(".jpg", out, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok:
        raise SystemExit("分享卡编码失败 / cover encode failed")
    buf.tofile(str(dst))
    print(f"  {dst.relative_to(ROOT)}  {COVER_W}×{COVER_H}  {dst.stat().st_size / 1024:.0f}KB")


def make_touch_icon(size: int = 180) -> None:
    """iOS 加到主屏幕用的图标。SVG 它不认，必须给一张 PNG。"""
    canvas = np.zeros((size, size, 3), np.float32)
    canvas[:] = NIGHT

    pad = round(size * 0.16)
    inner = size - pad * 2
    yy, xx = np.mgrid[0:inner, 0:inner].astype(np.float32)
    d = np.sqrt(((xx - inner / 2) / (inner * 0.62)) ** 2 + ((yy - inner * 0.46) / (inner * 0.62)) ** 2)
    t = np.clip(d, 0.0, 1.0)[..., None]
    # 中心近白，向外过渡到暖橙 —— 就是一块点亮的画片
    panel = np.float32([200, 233, 255]) * (1 - t) + np.float32([46, 118, 217]) * t

    mask = rounded_mask(inner, inner, round(inner * 0.2))[..., None]
    region = canvas[pad : pad + inner, pad : pad + inner]
    canvas[pad : pad + inner, pad : pad + inner] = region * (1 - mask) + panel * mask

    dst = PUBLIC / "apple-touch-icon.png"
    ok, buf = cv2.imencode(".png", np.clip(canvas, 0, 255).astype(np.uint8))
    if not ok:
        raise SystemExit("图标编码失败 / icon encode failed")
    buf.tofile(str(dst))
    print(f"  {dst.relative_to(ROOT)}  {size}×{size}  {dst.stat().st_size / 1024:.0f}KB")


if __name__ == "__main__":
    make_cover()
    make_touch_icon()
