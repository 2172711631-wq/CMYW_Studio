"""把立牌外壳烘成网页端能用的网格。

和 tools/bake_badge.py 同一个道理：浏览器里跑不了 CadQuery，但外壳只有几个固定
规格，在 TS 里重写一遍就等于多一个母本、两边迟早对不上。所以从
shell_master/ringframe_cadquery.py 这一个母本三角化，写成 JSON 放进
web/public/standee/，网页端导出时按需 fetch。

和吧唧不同的一点：立牌是四件，**排盘也在这儿做完**。烘出来的坐标已经是四件在
盘上的相对摆位，网页端只负责把整组挪到盘中央 —— 排盘算法就只有 Python 这一份。

    py -3.11 tools/bake_standee.py                 # 全部规格
    py -3.11 tools/bake_standee.py 100x150
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root

from shell_master import ringframe_cadquery as R  # noqa: E402
from shell_master import threemf_out as T  # noqa: E402

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "public", "standee"
)

# 网站上给出的规格。上限不是随便定的：四件要排进一个盘，
# 底座那一行的宽度 ≈ 2×画宽 + 32，247 是热床能用的净宽，反推画宽 ≤ 106；
# 前框加底座那一列的高度 ≈ 画高 + 95，反推画高 ≤ 150。所以 100×150 就是顶。
SIZES = [(60.0, 90.0), (80.0, 120.0), (100.0, 150.0)]

# 三角化精度。外壳全是平面和小圆角，0.08mm 弦差已经看不出棱了。
TOL = 0.08
ANG = 0.3

PART_LABELS = {
    "frame": "立牌前框",
    "module": "灯板托盘",
    "base": "底座",
    "cover": "底盖",
}


def bake_one(art_w: float, art_h: float) -> tuple[str, int]:
    R.ART_W, R.ART_H = art_w, art_h
    R.WALL = 3.5  # 立牌用窄边框，和 --preset standee 同一个数
    shapes = [(name, R.PARTS[name]()) for name in ("frame", "module", "base", "cover")]
    packed = T.pack_plates(shapes)

    parts = {}
    for name, shape in packed[0]:
        verts, tris = T.mesh_of(shape, TOL, ANG)
        parts[name] = {
            "label": PART_LABELS[name],
            # 展平成一维，省掉每个点两个中括号
            "vertices": [round(c, 4) for v in verts for c in v],
            "indices": [i for t in tris for i in t],
        }

    p = R.params()
    payload = {
        "artWidth": art_w,
        "artHeight": art_h,
        "frameW": round(p["frame_w"], 2),
        "frameH": round(p["frame_h"], 2),
        "depth": round(p["depth"], 2),
        "windowW": round(p["window_w"], 2),
        "windowH": round(p["window_h"], 2),
        "order": [name for name, _ in packed[0]],
        "note": "由 shell_master/ringframe_cadquery.py 烘出；改参数后重跑 tools/bake_standee.py",
        "parts": parts,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{art_w:.0f}x{art_h:.0f}.json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    return path, len(packed)


def main() -> None:
    if sys.argv[1:]:
        sizes = [tuple(float(v) for v in a.lower().split("x")) for a in sys.argv[1:]]
    else:
        sizes = SIZES
    for w, h in sizes:
        path, n_plates = bake_one(w, h)
        size_kb = os.path.getsize(path) / 1024
        # 排到第二盘就说明这个规格进不了"一盘画一盘框"，得当场看见，别等切片器报错
        warn = "" if n_plates == 1 else f"  ⚠ 四件排了 {n_plates} 盘，只烘了第 1 盘"
        print(f"{w:.0f}×{h:.0f} → {os.path.relpath(path)}  {size_kb:.1f} KB{warn}")


if __name__ == "__main__":
    main()
