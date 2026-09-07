"""全色域色卡：把每一种可打印的配方各打一格，用来建 ColorDB。

密度阶梯（make_wedge.py）量的是**四个常数**，前提是"模型是对的、只是常数不准"。
这张色卡不做这个假设 —— 它把 C/M/Y 各 0–6 层的 343 种组合**逐一打出来**，
测完就是一张 `配方 → 实测颜色` 的表。查表选配方时不再需要模型，也就没有模型误差。

为什么要留参照格：背光板不可能完全均匀，四角通常比中心暗。每行开头放一格
光秃白底，量的时候先用它把那一行的亮度校平，再算其余格子的透射率 ——
不然整张色卡会被背光的不均匀污染，而那正是我们要测的量级。

    py -3.11 tools/make_colorchart.py            # 默认 7mm 格
    py -3.11 tools/make_colorchart.py 6          # 想印小一点

打出来背光拍一张，接着跑 tools/measure_colorchart.py。
"""

from __future__ import annotations

import io
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import cv2
import numpy as np

import main as M

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calibration")
os.makedirs(OUT, exist_ok=True)

LEVELS = list(range(7))                    # 每色 0–6 层
WHITE = 4                                  # 底白固定，和画片一致
COLS, ROWS = 20, 19                        # 第 0 列是参照格，其余放配方
GAP_MM = 1.5

# 343 种配方，按「先黄后品红再青」排，同一行里颜色是渐变的，肉眼也好核对
RECIPES = [(c, m, y) for c, m, y in itertools.product(LEVELS, LEVELS, LEVELS)]


def build(cell_mm: float = 7.0) -> int:
    pitch = cell_mm + GAP_MM
    width_mm = COLS * pitch + GAP_MM
    height_mm = ROWS * pitch + GAP_MM

    gw = M.grid_w_for_print(width_mm, 300)
    px = width_mm / gw
    gh = int(round(height_mm / px))
    cell = max(1, int(round(cell_mm / px)))
    step = max(cell + 1, int(round(pitch / px)))

    def z() -> np.ndarray:
        return np.zeros((gh, gw), np.int32)

    w, c, m, y = z(), z(), z(), z()
    w[:] = WHITE                            # 整片底白，色卡本身也要连成一片

    def box(col: int, row: int):
        x0 = int(round(GAP_MM / px)) + col * step
        y0 = int(round(GAP_MM / px)) + row * step
        return slice(y0, min(y0 + cell, gh)), slice(x0, min(x0 + cell, gw))

    placed = []
    idx = 0
    for row in range(ROWS):
        # 第 0 列：光秃白底参照，用来在测量时校平背光的不均匀
        for col in range(1, COLS):
            if idx >= len(RECIPES):
                break
            cc, mm, yy = RECIPES[idx]
            sl = box(col, row)
            c[sl], m[sl], y[sl] = cc, mm, yy
            placed.append((col, row, cc, mm, yy))
            idx += 1

    sim = M.simulate_transmitted_rgb(w, y, m, c, brightness_ratio=1.0, stretch=False)
    prev = (np.clip(sim / np.exp(-M.DENSITY_W * WHITE), 0, 1) * 255).astype(np.uint8)
    prev = cv2.resize(prev, (gw * 2, gh * 2), interpolation=cv2.INTER_NEAREST)
    png = os.path.join(OUT, "全色域色卡_模拟预览.png")
    ok, buf = cv2.imencode(".png", cv2.cvtColor(prev, cv2.COLOR_RGB2BGR))
    if ok:
        open(png, "wb").write(buf.tobytes())   # 中文路径下 imwrite 会静默失败

    layers = {"C": c, "M": m, "Y": y, "W": w, "shape": (gh, gw, 3)}
    layers["stats"] = M.layer_stats(layers)
    mf = os.path.join(OUT, "全色域色卡.3mf")
    tris = M.save_as_bambu_3mf(mf, layers, gw, width_mm, shell_params=None,
                               target_height_mm=height_mm)

    # 版面写成 JSON，测量脚本按它去切格，不靠猜
    import json
    meta = {
        "cell_mm": cell_mm, "gap_mm": GAP_MM, "cols": COLS, "rows": ROWS,
        "width_mm": width_mm, "height_mm": height_mm, "white": WHITE,
        "ref_col": 0,
        "patches": [{"col": a, "row": b, "c": cc, "m": mm, "y": yy}
                    for a, b, cc, mm, yy in placed],
    }
    meta_path = os.path.join(OUT, "全色域色卡_版面.json")
    with open(meta_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)

    stack = (w + c + m + y)
    print(f"实物 {width_mm:.0f} × {height_mm:.0f} mm   格子 {cell*px:.1f} mm   三角面 {tris}")
    print(f"配方 {len(placed)} 格 + 参照 {ROWS} 格（每行第 1 格是光秃白底）")
    print(f"最厚 {int(stack.max())} 层 = {stack.max()*0.08:.2f} mm，平均 {stack.mean():.1f} 层")
    print()
    print(f"  {mf}")
    print(f"  {png}")
    print(f"  {meta_path}")
    print()
    print("打出来背光拍一张（锁曝光、别开 HDR、别开闪光），裁到只剩色卡，")
    print("然后跑：py -3.11 tools/measure_colorchart.py 照片.jpg")
    return 0


if __name__ == "__main__":
    raise SystemExit(build(float(sys.argv[1]) if len(sys.argv) > 1 else 7.0))
