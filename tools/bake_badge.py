"""把吧唧外壳烘成网页端能用的网格。

浏览器里跑不了 CadQuery，但吧唧外壳只有几个固定规格，没必要在 TS 里重写一遍
（重写就等于多一个母本，两边迟早对不上）。所以这里从 shell_master/badge_cadquery.py
这一个母本三角化，写成 JSON 放进 web/public/badge/，网页端要导出时按需 fetch。

放 public/ 而不是打进包里是有意的：只有真的要做吧唧的人才会下这几十 KB，
主包不受影响。

    py -3.11 tools/bake_badge.py            # 默认 58mm
    py -3.11 tools/bake_badge.py 32 44 58 75
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root

from shell_master import badge_cadquery as B  # noqa: E402
from shell_master import threemf_out as T  # noqa: E402

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "public", "badge"
)

# 三角化精度。0.1mm 弦差在 ⌀58 上大约 100 个面，肉眼和打印都够，
# 再细只是白白撑大文件。
TOL = 0.1
ANG = 0.3


def bake_one(diameter: float) -> str:
    B.BADGE_D = float(diameter)
    p = B.params()
    parts = {}
    for name, fn in (("front", B.build_front), ("back", B.build_back)):
        verts, tris = T.mesh_of(fn(), TOL, ANG)
        parts[name] = {
            # 展平成一维，省掉每个点两个中括号
            "vertices": [round(c, 4) for v in verts for c in v],
            "indices": [i for t in tris for i in t],
        }
    payload = {
        "diameter": B.BADGE_D,
        "depth": round(p["depth"], 3),
        "artDiameter": round(p["art_d"], 3),
        "windowDiameter": round(p["window_d"], 3),
        "lightCavity": B.LIGHT_T,
        "note": "由 shell_master/badge_cadquery.py 烘出；改参数后重跑 tools/bake_badge.py",
        "parts": parts,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{B.BADGE_D:.0f}.json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    return path


def main() -> None:
    sizes = [float(a) for a in sys.argv[1:]] or [58.0]
    for d in sizes:
        path = bake_one(d)
        size_kb = os.path.getsize(path) / 1024
        p = B.params()
        print(
            f"⌀{d:.0f} → {os.path.relpath(path)}  {size_kb:.1f} KB"
            f"（画片 ⌀{p['art_d']:.1f}，厚 {p['depth']:.1f}）"
        )


if __name__ == "__main__":
    main()
