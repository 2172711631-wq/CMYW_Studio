#!/usr/bin/env python3
"""重新生成浏览器引擎的比对基准 / Regenerate parity fixtures for the browser engine.

TypeScript 引擎必须与这份 Python 实现逐像素一致。改动分色或网格化逻辑后，
先跑这个脚本更新基准，再跑 `cd web && npx vitest run` 确认两边仍然对齐。

The TypeScript engine must match this Python implementation pixel-for-pixel.
After changing the separation or meshing logic, run this to refresh the
fixtures, then run `cd web && npx vitest run` to confirm both sides still agree.

用法 / Usage:
    py -3.11 tools/make_fixtures.py [来源图片 / source image]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from main import (  # noqa: E402
    MIN_WHITE_LAYERS,
    RGB_CLIP_MIN,
    _layers_from_rgb_v3,
    _mesh_merge_filter,
    apply_rounded_corner_mask,
    art_score,
    compute_z_stacks,
    dither_amount_for,
    flatness_of,
    generate_cmyw_layers,
    dither_block_for,
    keep_floor_for,
    lift_chroma_only_for,
    merge_voxel_rectangles,
    mesh_merge_filter_for,
    mm_per_px_for,
)

# 基准图要有全色域覆盖，否则测不到 UCR 与浅色保底的分支
DEFAULT_SOURCE = ROOT / "docs" / "img" / "color-chart.png"
OUT_DIR = ROOT / "web" / "test" / "fixtures"

# 小网格：基准文件保持在几十 KB，仍能覆盖所有代码路径
GRID_W = 64
GRID_H = 48

# 圆角基准用的画幅
CORNER_WIDTH_MM = 100.0
CORNER_RADIUS_MM = 5.0


def _imread(path: Path) -> np.ndarray:
    """Windows 中文路径下 cv2.imread 常失败，改用 fromfile + imdecode。"""
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"无法读取图片 / cannot read image: {path}")
    return img


def main(argv: list[str]) -> int:
    source = Path(argv[1]).expanduser() if len(argv) > 1 else DEFAULT_SOURCE
    if not source.is_file():
        print(f"找不到来源图片 / source image not found: {source}", file=sys.stderr)
        print("用法 / usage: py -3.11 tools/make_fixtures.py <image>", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    layers = generate_cmyw_layers(
        str(source),
        target_grid_w=GRID_W,
        target_grid_h=GRID_H,
        dither=True,
        color_profile="v2",
        # 基准钉的是**引擎默认值**，不是应用层的自动取值 —— 网页端那边
        # separateCMYW 的默认参数也没变，两边才对得上。
        auto_tune=False,
    )
    if not layers:
        print(f"分色失败 / separation failed: {source}", file=sys.stderr)
        return 3

    lw, ly, lm, lc = layers["W"], layers["Y"], layers["M"], layers["C"]

    # --- 分色基准 ---
    # 同时存下重采样后的 RGB，TS 侧直接吃它，把 resize 差异排除在比对之外
    img = cv2.resize(_imread(source), (GRID_W, GRID_H), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    separation = {
        "grid_w": GRID_W,
        "grid_h": GRID_H,
        "profile": "v2",
        "dither": True,
        "rgb": rgb.reshape(-1).tolist(),
        "W": lw.reshape(-1).tolist(),
        "Y": ly.reshape(-1).tolist(),
        "M": lm.reshape(-1).tolist(),
        "C": lc.reshape(-1).tolist(),
    }

    # --- 自动取值基准 ---
    # 上面那份钉的是引擎默认参数；这份钉的是两件默认路径根本走不到的事：
    #
    #   1. **选参数的公式**。它在 web/src/engine/autotune.ts 和 main.py 各有一份，
    #      分叉了不会报错，只会让同一张图在桌面 App 和网站上出两张不一样的画片。
    #      所以扫一遍整条曲线（含两端阈值），逐点对。
    #   2. **lift_chroma_only 那条分支**下引擎的输出。参数直接取插画档那一组，
    #      不跟着这张基准图的实际平坦度走 —— 基准图是色卡，本身并不"平"，
    #      跟着它走就永远测不到这条分支。
    curve = []
    for i in range(21):
        f = i / 20.0
        curve.append(
            {
                "flatness": f,
                "art_score": art_score(f),
                "dither_amount": dither_amount_for(f),
                "keep_floor": keep_floor_for(f),
                "lift_chroma_only": lift_chroma_only_for(f),
                "merge_filter": mesh_merge_filter_for(f),
                "mm_per_px": mm_per_px_for(f),
                "dither_block": dither_block_for(mm_per_px_for(f)),
            }
        )

    # 插画档，但**抖动还没归零**：0.8 那一档 dither_amount 正好是 0，
    # 抖动块那条路就一步也走不到，等于没测。0.6 同时满足门槛压低、免滤波、
    # 彩色度判据打开、抖动仍开着 —— 四条分支一次全覆盖。
    tuned_flat = 0.6
    # 抖动块固定取 0.1mm/px 那一档（block=4），基准才走得到 block > 1 那条路 ——
    # 基准网格本身是 64×48 铺 100mm，算出来 block 就是 1，跟着它走等于没测
    tuned = {
        "flatness": tuned_flat,
        "dither_amount": dither_amount_for(tuned_flat),
        "keep_floor": keep_floor_for(tuned_flat),
        "lift_chroma_only": lift_chroma_only_for(tuned_flat),
        "mm_per_px": 0.10,
        "dither_block": dither_block_for(0.10),
    }
    tuned_rgb = np.clip(rgb.astype(np.float32) / 255.0, RGB_CLIP_MIN, 1.0)
    tw, ty, tm, tc = _layers_from_rgb_v3(
        tuned_rgb,
        MIN_WHITE_LAYERS,
        dither=tuned["dither_amount"] > 0.0,
        dither_amount=tuned["dither_amount"],
        keep_floor=tuned["keep_floor"],
        lift_chroma_only=tuned["lift_chroma_only"],
        dither_block=tuned["dither_block"],
    )
    auto = {
        "grid_w": GRID_W,
        "grid_h": GRID_H,
        # 直接量基准网格本身（不经探针缩放），TS 侧吃同一个数组才对得上
        "flatness_of_grid": flatness_of(rgb),
        "curve": curve,
        "tuned": tuned,
        "profile": "v3",
        "W": tw.reshape(-1).tolist(),
        "Y": ty.reshape(-1).tolist(),
        "M": tm.reshape(-1).tolist(),
        "C": tc.reshape(-1).tolist(),
    }

    # --- 网格化基准 ---
    med_c = _mesh_merge_filter(lc, size=3)
    _, _, _, mc = apply_rounded_corner_mask(
        (lw, ly, lm, lc),
        physical_width_mm=CORNER_WIDTH_MM,
        corner_radius_mm=CORNER_RADIUS_MM,
    )
    _, _, _, zc = compute_z_stacks(lw, ly, lm)
    rects = merge_voxel_rectangles(med_c, zc, layer_height=0.08)

    mesh = {
        "grid_w": GRID_W,
        "grid_h": GRID_H,
        "layers_C": lc.reshape(-1).tolist(),
        "median_C": med_c.reshape(-1).tolist(),
        "z_start_C": zc.reshape(-1).tolist(),
        "corner_width_mm": CORNER_WIDTH_MM,
        "corner_radius_mm": CORNER_RADIUS_MM,
        "corner_masked_C": mc.reshape(-1).tolist(),
        "rects": [
            [int(a), int(b), int(c), int(d), round(float(e), 6), round(float(f), 6)]
            for a, b, c, d, e, f in rects
        ],
    }

    for name, payload in (
        ("separation-reference.json", separation),
        ("separation-auto-reference.json", auto),
        ("separation-auto-reference.json", auto),
        ("mesh-reference.json", mesh),
    ):
        path = OUT_DIR / name
        path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        print(f"  {path.relative_to(ROOT)}  ({path.stat().st_size / 1024:.0f} KB)")

    print(f"\n来源 / source: {source}")
    print(f"网格 / grid:   {GRID_W}×{GRID_H}")
    print(f"矩形 / rects:  {len(rects)}  (非零像素 {int((med_c > 0).sum())})")
    print("\n接着跑 / next: cd web && npx vitest run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
