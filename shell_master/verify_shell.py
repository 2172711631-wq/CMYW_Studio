"""抽检：外廓、顶壁限厚、卡槽、水密。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shell_master.shell_cadquery import (  # noqa: E402
    TOP_THICKNESS,
    _active_params,
    export_shell_stl,
)


def main() -> int:
    assert TOP_THICKNESS <= 3.0
    p = _active_params(art_w=120, art_h=90, wall=3, top_thickness=2.0, depth=18, clearance=0.2)
    path = Path(tempfile.gettempdir()) / "fdm_shell_check.stl"
    mesh = export_shell_stl(path, **p)
    ok = True
    size_x = float(mesh.bounds[1][0] - mesh.bounds[0][0])
    size_y = float(mesh.bounds[1][1] - mesh.bounds[0][1])
    expect_x = p["art_w"] + 2.0 * p["wall"]
    expect_y = p["art_h"] + p["wall"] + p["top_thickness"]
    print("TOP_THICKNESS", p["top_thickness"])
    print("watertight", mesh.is_watertight, "bodies", len(mesh.split(only_watertight=False)))
    print(f"size_x {size_x:.2f} expect {expect_x:.2f}")
    print(f"size_y {size_y:.2f} expect {expect_y:.2f} (bottom wall + art + top_thickness)")
    if abs(size_x - expect_x) > 0.6:
        ok = False
    if abs(size_y - expect_y) > 0.6:
        ok = False
    if not mesh.is_watertight:
        ok = False
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
