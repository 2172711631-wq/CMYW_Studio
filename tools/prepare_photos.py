#!/usr/bin/env python3
"""把实拍原图处理成网页用图 / Prepare product photos for the web.

手机原图是 3000×4000、单张 5MB 以上，直接放上网页太重。这个脚本把
`web/photos/` 里的图缩到合理尺寸并转成 WebP，输出到 `web/public/img/`。

默认**不做任何调色**——如果照片已经修过，原样保留就好。

`--blend` 用于**没修过的**照片：发光面板保持锐利，背景向外连续模糊、
偏向站点底色、淡出到透明，让照片自然溶进深色页面。之所以是纯径向而不是
按面板分割，是因为分割一旦不准就会留下硬边，比不处理更难看。

用法 / Usage:
    py -3.11 tools/prepare_photos.py            # 只缩放转格式（图已修过）
    py -3.11 tools/prepare_photos.py --blend    # 顺便融进页面底色（图没修过）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "web" / "photos"
OUT_DIR = ROOT / "web" / "public" / "img"

# 站点底色 #161E36。OpenCV 用 BGR 排列。
NIGHT_BGR = np.array([54, 30, 22], np.float32)

# 长边上限。再大网页上看不出差别，只是白白多下几百 KB。
MAX_EDGE = 1600
WEBP_QUALITY = 86

# 融合模式下四周补多少留白（相对短边），给淡出留出空间
PAD_RATIO = 0.16

SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


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
    """发光面板的重心。只用来决定景深中心，偏一点也不会产生硬边。"""
    h, w = bgr.shape[:2]
    lightness = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)[..., 0]
    mask = (lightness >= np.percentile(lightness, 88)).astype(np.uint8)
    if mask.sum() < 50:
        return w / 2.0, h / 2.0
    ys, xs = np.nonzero(mask)
    return float(xs.mean()), float(ys.mean())


def blend_into_night(bgr: np.ndarray) -> np.ndarray:
    """未修图的照片：连续模糊 + 向底色偏移 + 径向淡出，融进页面。"""
    h0, w0 = bgr.shape[:2]
    cx0, cy0 = subject_center(bgr)

    # 主体先补白到画布正中。若主体偏向某侧，离得近的那两条边还没衰减到 0
    # 就会被画幅截断，页面上会看到一条笔直的亮边。
    pad_left = int(max(0.0, w0 - 2 * cx0))
    pad_right = int(max(0.0, 2 * cx0 - w0))
    pad_top = int(max(0.0, h0 - 2 * cy0))
    pad_bottom = int(max(0.0, 2 * cy0 - h0))

    margin = int(min(h0, w0) * PAD_RATIO)
    pad_left += margin
    pad_right += margin
    pad_top += margin
    pad_bottom += margin

    h = h0 + pad_top + pad_bottom
    w = w0 + pad_left + pad_right
    canvas = np.empty((h, w, 3), np.float32)
    canvas[:] = NIGHT_BGR
    canvas[pad_top : pad_top + h0, pad_left : pad_left + w0] = bgr.astype(np.float32)
    cx, cy = w / 2.0, h / 2.0

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dist = np.sqrt(((xx - cx) / (w / 2.0)) ** 2 + ((yy - cy) / (h / 2.0)) ** 2)
    t = smoothstep(dist, 0.34, 0.92)[..., None]

    blurred = cv2.GaussianBlur(canvas, (0, 0), sigmaX=min(h, w) * 0.055)
    hsv = cv2.cvtColor(np.clip(blurred, 0, 255).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] *= 0.40
    blurred = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)

    out = canvas * (1.0 - t) + blurred * t
    # 颜色比不透明度更早到达底色，边缘就不会露出色块
    out = out * (1.0 - t * 0.92) + NIGHT_BGR * (t * 0.92)
    alpha = 1.0 - smoothstep(dist, 0.58, 1.02)

    return np.dstack([np.clip(out, 0, 255).astype(np.uint8), (alpha * 255).astype(np.uint8)])


def fit(img: np.ndarray, max_edge: int) -> np.ndarray:
    h, w = img.shape[:2]
    scale = min(1.0, max_edge / max(h, w))
    if scale >= 1.0:
        return img
    return cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="把实拍原图处理成网页用图")
    ap.add_argument("--blend", action="store_true",
                    help="融进站点底色（用于没修过的照片）/ blend into the site background")
    ap.add_argument("--max-edge", type=int, default=MAX_EDGE, help=f"长边上限，默认 {MAX_EDGE}")
    args = ap.parse_args(argv[1:])

    if not SRC_DIR.is_dir():
        print(f"找不到源图目录 / source dir missing: {SRC_DIR}", file=sys.stderr)
        return 2

    photos = sorted(p for p in SRC_DIR.iterdir() if p.suffix.lower() in SUFFIXES)
    if not photos:
        print(f"{SRC_DIR} 里没有图片 / no images found", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"模式 / mode: {'融合底色 blend' if args.blend else '仅缩放 resize only'}\n")

    ratios: list[tuple[str, float]] = []
    for i, path in enumerate(photos, 1):
        img = imread(path)
        before = path.stat().st_size
        if args.blend:
            img = blend_into_night(img)
        img = fit(img, args.max_edge)
        h, w = img.shape[:2]

        dst = OUT_DIR / f"shot{i}.webp"
        ok, buf = cv2.imencode(".webp", img, [int(cv2.IMWRITE_WEBP_QUALITY), WEBP_QUALITY])
        if not ok:
            print(f"  编码失败 / encode failed: {path.name}", file=sys.stderr)
            continue
        buf.tofile(str(dst))
        ratios.append((dst.name, w / h))
        print(f"  {dst.name:12} {w}×{h}  比例 {w / h:.2f}  "
              f"{before / 1024 / 1024:.1f}MB → {dst.stat().st_size / 1024:.0f}KB   ({path.name})")

    print("\n页面上每个 figure 的 --ar 要和这里的比例一致，否则等高布局会算错占位：")
    for name, ar in ratios:
        print(f"  {name}  --ar: {ar:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
