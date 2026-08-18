#!/usr/bin/env python3
"""生成「朴素分色 vs 自适应 UCR」对比图 / Render the naive-vs-UCR comparison.

这个项目最难讲清楚的一点是：**彩色透光画不是新东西，2020 年就有人做**，
但大多数人试过一次就放弃了，因为直接把 RGB 拆成 CMY 打出来是发灰、蒙一层雾的。

自适应 UCR + 有序抖动就是冲着这件事去的。可这种话自己说没有意义 ——
所以这里用同一张源图、同一套光学模型跑两遍，只换分色算法，把结果并排放出来。
两边唯一的差别就是 `_layers_from_rgb_v1` 和 `_layers_from_rgb_v2`，
其余每一步（缩放、光密度、模拟透光、亮度）完全一致，比较才站得住。

    左 = v1：RGB 直接映射到 CMY，不抖动 —— 现成工具的普遍做法
    右 = v2：抽灰再按亮度回加（UCR）+ Bayer 4×4 有序抖动

用法 / Usage:
    py -3.11 tools/make_comparison.py docs/img/color-chart.png
    py -3.11 tools/make_comparison.py 某张照片.jpg --name photo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import (  # noqa: E402
    generate_cmyw_layers,
    resize_layers,
    simulate_transmitted_rgb,
)

OUT_DIR = ROOT / "docs" / "img"
GRID_W = 420          # 对比用的打印网格宽度，够看清抖动纹理又不至于文件太大
UPSCALE_TO = 840      # 放大后输出，让层级差异在 README 里看得见
WEBP_QUALITY = 92


def render(path: Path, profile: str, dither: bool) -> np.ndarray:
    layers = generate_cmyw_layers(
        str(path), target_grid_w=GRID_W, dither=dither, color_profile=profile,
    )
    if not layers:
        raise SystemExit(f"读不出 / cannot read: {path}")
    r = resize_layers(layers, GRID_W)
    # stretch=False：保留光学相对亮度。拉满会把两边都拉成海报色，
    # 正好把要比较的那点差异抹掉。
    sim = simulate_transmitted_rgb(r.w, r.y, r.m, r.c, brightness_ratio=1.6, stretch=False)
    bgr = cv2.cvtColor((sim * 255.0).astype(np.uint8), cv2.COLOR_RGB2BGR)
    h, w = bgr.shape[:2]
    scale = UPSCALE_TO / max(h, w)
    if scale > 1:
        # 最近邻：这里要看的就是层级和抖动点，插值会把它们糊掉
        bgr = cv2.resize(bgr, (round(w * scale), round(h * scale)),
                         interpolation=cv2.INTER_NEAREST)
    return bgr


def shadow_detail(naive: np.ndarray, ours: np.ndarray) -> tuple[float, float]:
    """暗部还剩多少信息。

    一开始我拿全图饱和度均值当指标，量出来两边只差 2%，差点得出「没区别」的结论。
    错在取样范围：三色叠灰只发生在**中性色和暗部**，那点面积在全图均值里被稀释没了。
    改成只取朴素版判定为暗的那批像素 —— 两边取同一批，才可比。
    """
    la = naive.max(axis=2).astype(np.float32)
    lb = ours.max(axis=2).astype(np.float32)
    dark = la < np.percentile(la, 35)
    return float(la[dark].mean()), float(lb[dark].mean())


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="生成朴素分色 vs 自适应 UCR 的对比图")
    ap.add_argument("image", help="源图路径")
    ap.add_argument("--name", default="compare", help="输出文件名前缀")
    args = ap.parse_args(argv[1:])

    src = Path(args.image)
    if not src.is_absolute():
        src = ROOT / src
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    naive = render(src, "v1", dither=False)
    ours = render(src, "v2", dither=True)

    for tag, img in (("naive", naive), ("ucr", ours)):
        dst = OUT_DIR / f"{args.name}-{tag}.webp"
        ok, buf = cv2.imencode(".webp", img, [int(cv2.IMWRITE_WEBP_QUALITY), WEBP_QUALITY])
        if not ok:
            raise SystemExit(f"编码失败 / encode failed: {dst}")
        buf.tofile(str(dst))
        print(f"  {dst.relative_to(ROOT)}  {img.shape[1]}×{img.shape[0]}  "
              f"{dst.stat().st_size / 1024:.0f}KB")

    a, b = shadow_detail(naive, ours)
    print()
    print(f"  暗部平均亮度  朴素 {a:.1f}  →  UCR+抖动 {b:.1f}")
    print("  朴素版把中性暗部压成一片死黑（三色全叠）；UCR 抽掉共有的灰、只按亮度补回一部分，")
    print("  所以暗部留得住细节，顺带还省掉大量本来要叠三次的耗材。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
