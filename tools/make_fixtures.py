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
    _mesh_merge_filter,
    apply_rounded_corner_mask,
    compute_z_stacks,
    generate_cmyw_layers,
    merge_voxel_rectangles,
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
