"""
FDM 灯箱外壳 — 参数化实体建模母本（CadQuery）

尺寸逻辑（相对画片）：
  - 内缩 = wall/2（壁厚 3→内缩 1.5；壁厚 2→内缩 1）
  - 外扩 = wall
  - 内腔 = 画片 - 2×内缩 → 承托台宽 = 内缩，卡槽切画片+公差后托住画片
  - 外框 = 画片 + 2×外扩
  - 顶壁触摸区用 top_thickness（同样：内缩 top/2，外扩 top）
  - 画片圆角与外框同为 corner

建模顺序：
  1) 全局变量
  2) 基础主壳体
  3) 画片卡槽（FDM 公差）
  4) Type-C 开孔（内腔底面之上抬高 1.55mm = 底板厚 + USB_LIFT_Z；无 PCB 承托板）
  5) 导出

坐标系：开口 +Z，外底 Z=0，内腔底 Z=wall；+X 右侧 Type-C；+Y 顶部薄壁。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cadquery as cq
import numpy as np
import trimesh

# =============================================================================
# 1) 全局变量
# =============================================================================

ART_W = 120.0
ART_H = 90.0
ART_THICKNESS = 2.5  # 画片厚度 = 卡槽 Z 向深度

WALL = 3.0  # 底 / 左 / 右 壁厚；内缩 = WALL/2，外扩 = WALL
TOP_THICKNESS = 2.0  # 顶壁（触摸），硬限 ≤3；内缩 = TOP/2，外扩 = TOP
DEPTH = 18.0
CORNER = 5.0  # 外框圆角；内腔与卡槽、画片圆角与此一致
CLEARANCE = 0.2  # 画片放置原点偏移（与导出错位对齐）
FDM_TOL = 0.2  # 卡槽 / Type-C 打印公差

SLOT_OUTWARD = 5.0

# Type-C：名义尺寸 + 公差 + 外扩；孔底 = 底板厚(wall) + USB_LIFT_Z（相对内腔底抬高）
USB_NOMINAL_W = 9.0
USB_NOMINAL_H = 3.2
USB_NOMINAL_R = 1.6
USB_LIFT_Z = 1.55  # 相对内腔底面抬高（不含底板厚度）；原 2.0，略降方便对准
USB_EXTRA_OUT = 0.05  # 孔轮廓四周再外扩，方便插入

_ROOT = Path(__file__).resolve().parent
_PARAMS_PATH = _ROOT / "params.json"

assert TOP_THICKNESS <= 3.0, "top_thickness 绝对不能超过 3mm"


def _clamp(v: float, lo: float, hi: float) -> float:
    return float(min(hi, max(lo, v)))


def _clamp_corner(width: float, height: float, radius: float) -> float:
    return max(0.0, min(radius, width * 0.5 - 0.05, height * 0.5 - 0.05))


def _active_params(**overrides: float) -> dict[str, float]:
    p = {
        "art_w": ART_W,
        "art_h": ART_H,
        "art_thickness": ART_THICKNESS,
        "wall": WALL,
        "top_thickness": TOP_THICKNESS,
        "depth": DEPTH,
        "corner": CORNER,
        "clearance": CLEARANCE,
        "fdm_tol": FDM_TOL,
        # 四周各外扩 USB_EXTRA_OUT → 宽高各 +2×，圆角同步 +USB_EXTRA_OUT
        "usb_w": USB_NOMINAL_W + FDM_TOL + 2.0 * USB_EXTRA_OUT,
        "usb_h": USB_NOMINAL_H + FDM_TOL + 2.0 * USB_EXTRA_OUT,
        "usb_r": USB_NOMINAL_R + USB_EXTRA_OUT,
        "usb_lift_z": USB_LIFT_Z,
    }
    for k, v in overrides.items():
        if v is not None and k in p:
            p[k] = float(v)

    p["art_w"] = max(10.0, p["art_w"])
    p["art_h"] = max(10.0, p["art_h"])
    p["wall"] = _clamp(p["wall"], 1.0, 8.0)
    p["top_thickness"] = _clamp(p["top_thickness"], 0.8, 3.0)
    p["depth"] = max(p["wall"] + p["art_thickness"] + 4.0, p["depth"])
    p["clearance"] = _clamp(p["clearance"], 0.0, 0.5)
    p["fdm_tol"] = _clamp(p["fdm_tol"], 0.0, 0.6)
    p["art_thickness"] = _clamp(p["art_thickness"], 1.0, 6.0)
    p["usb_w"] = max(1.0, p["usb_w"])
    p["usb_h"] = max(1.0, p["usb_h"])
    p["usb_r"] = _clamp_corner(p["usb_w"], p["usb_h"], p["usb_r"])
    p["usb_lift_z"] = _clamp(p["usb_lift_z"], 0.0, p["depth"] * 0.5)

    # 派生：内缩 = 壁厚/2，外扩 = 壁厚
    p["inset_side"] = p["wall"] * 0.5
    p["inset_top"] = p["top_thickness"] * 0.5
    return p


def _layout(p: dict[str, float]) -> dict[str, float]:
    """由画片尺寸推内外轮廓（同中心）。"""
    clr = p["clearance"]
    aw, ah = p["art_w"], p["art_h"]
    wall, top_t = p["wall"], p["top_thickness"]
    inset_s, inset_t = p["inset_side"], p["inset_top"]

    # 画片占用区
    art_x0, art_y0 = clr, clr
    art_x1, art_y1 = clr + aw, clr + ah

    # 内腔：相对画片内缩 wall/2（顶边用 top/2）→ 承托台宽 = 内缩量
    cav_x0 = art_x0 + inset_s
    cav_y0 = art_y0 + inset_s
    cav_x1 = art_x1 - inset_s
    cav_y1 = art_y1 - inset_t

    # 外框：相对画片外扩 wall（顶边外扩 top_thickness）
    out_x0 = art_x0 - wall
    out_y0 = art_y0 - wall
    out_x1 = art_x1 + wall
    out_y1 = art_y1 + top_t

    return {
        "art_x0": art_x0,
        "art_y0": art_y0,
        "art_x1": art_x1,
        "art_y1": art_y1,
        "cav_x0": cav_x0,
        "cav_y0": cav_y0,
        "cav_x1": cav_x1,
        "cav_y1": cav_y1,
        "cav_w": cav_x1 - cav_x0,
        "cav_h": cav_y1 - cav_y0,
        "out_x0": out_x0,
        "out_y0": out_y0,
        "out_x1": out_x1,
        "out_y1": out_y1,
        "out_w": out_x1 - out_x0,
        "out_h": out_y1 - out_y0,
        "cx": 0.5 * (art_x0 + art_x1),
        "cy": 0.5 * (art_y0 + art_y1),
    }


def _rounded_box(
    *,
    cx: float,
    cy: float,
    width: float,
    height: float,
    radius: float,
    z0: float,
    zh: float,
) -> cq.Workplane:
    solid = (
        cq.Workplane("XY")
        .workplane(offset=z0)
        .center(cx, cy)
        .rect(width, height)
        .extrude(zh)
    )
    r = _clamp_corner(width, height, radius)
    if r > 1e-4 and zh > 1e-6:
        solid = solid.edges("|Z").fillet(r)
    return solid


# =============================================================================
# 2) 基础主壳体
# =============================================================================

def build_base_shell(p: dict[str, float]) -> cq.Workplane:
    """
    外实体 − 内腔：
    - 内腔 = 画片内缩（侧 wall/2，顶 top/2）→ 留下承托台
    - 外框 = 画片外扩（侧 wall，顶 top_thickness）
    - 内外圆角均用 corner（与画片圆角一致）
    """
    lay = _layout(p)
    depth, corner, wall = p["depth"], p["corner"], p["wall"]

    # 若内缩过大导致腔体无效，钳制
    if lay["cav_w"] < 5.0 or lay["cav_h"] < 5.0:
        raise ValueError("内缩后内腔过小：减小壁厚或增大画片")

    # 外框中心（顶/底壁厚不同时 ≠ 画片中心）
    out_cx = 0.5 * (lay["out_x0"] + lay["out_x1"])
    out_cy = 0.5 * (lay["out_y0"] + lay["out_y1"])
    cav_cx = 0.5 * (lay["cav_x0"] + lay["cav_x1"])
    cav_cy = 0.5 * (lay["cav_y0"] + lay["cav_y1"])

    body = _rounded_box(
        cx=out_cx,
        cy=out_cy,
        width=lay["out_w"],
        height=lay["out_h"],
        radius=corner,
        z0=0.0,
        zh=depth,
    )

    # 内腔从底板顶面挖穿开口；圆角 = corner（与外框/画一致）
    cavity = _rounded_box(
        cx=cav_cx,
        cy=cav_cy,
        width=lay["cav_w"],
        height=lay["cav_h"],
        radius=corner,
        z0=wall,
        zh=depth - wall + 1.0,
    )
    return body.cut(cavity)


# =============================================================================
# 3) 画片卡槽（画片 + FDM 公差，圆角同外框）
# =============================================================================

def cut_art_slot(shell: cq.Workplane, p: dict[str, float]) -> cq.Workplane:
    """
    卡槽 XY = 画片 + fdm_tol；Z 深 = art_thickness。
    与画片同中心、同圆角 → 切完留下内缩形成的承托台托住画片。
    """
    lay = _layout(p)
    tol, corner = p["fdm_tol"], p["corner"]
    depth, slot_z = p["depth"], p["art_thickness"]

    cut_w = p["art_w"] + tol
    cut_h = p["art_h"] + tol
    z0 = depth - slot_z

    cutter = _rounded_box(
        cx=lay["cx"],
        cy=lay["cy"],
        width=cut_w,
        height=cut_h,
        radius=corner,
        z0=z0,
        zh=slot_z + SLOT_OUTWARD,
    )
    return shell.cut(cutter)


# =============================================================================
# 4) Type-C 开孔（无承托板；内腔底 + USB_LIFT_Z）
# =============================================================================

def cut_type_c_hole(shell: cq.Workplane, p: dict[str, float]) -> cq.Workplane:
    """
    右侧壁 Type-C 通孔（无承托板）。

    坐标说明（与导出一致）：
      - 孔开在右外壁 face：X = out_x1（画片右缘 + wall）
      - Y 居中：画片中心 cy
      - Z：孔底 = 底板厚(wall) + usb_lift_z（默认内腔底之上 1.55mm）
        孔中心 Z = wall + usb_lift_z + usb_h/2
      - 孔轮廓已含 FDM_TOL + 四周 USB_EXTRA_OUT（默认 0.05）
    """
    lay = _layout(p)
    wall = p["wall"]
    usb_w, usb_h, usb_r = p["usb_w"], p["usb_h"], p["usb_r"]
    lift = p["usb_lift_z"]

    outer_x1 = lay["out_x1"]
    face_cy = lay["cy"]
    # 孔底 = 底板顶面(wall) + 相对内腔底的抬高
    z0 = wall + lift
    face_cz = z0 + usb_h * 0.5
    max_cz = p["depth"] - p["art_thickness"] - usb_h * 0.5 - 0.5
    min_cz = wall + usb_h * 0.5 + 0.2
    face_cz = _clamp(face_cz, min_cz, max_cz)
    z0 = face_cz - usb_h * 0.5
    z1 = face_cz + usb_h * 0.5

    # 用实心切刀从腔外 X 贯穿到腔内，避免 WP 挤出方向偶发失败
    x0 = lay["cav_x1"] - 1.0
    x1 = outer_x1 + 1.0

    cut_w = usb_w
    cut_h = usb_h
    usb_cutter = (
        cq.Workplane("YZ")
        .workplane(offset=x1)
        .center(face_cy, face_cz)
        .rect(cut_w, cut_h)
        .extrude(-(x1 - x0))
    )
    r = _clamp_corner(cut_w, cut_h, usb_r)
    if r > 1e-4:
        try:
            usb_cutter = usb_cutter.edges("|X").fillet(r)
        except Exception:
            pass

    p["_usb_x_face"] = outer_x1
    p["_usb_y"] = face_cy
    p["_usb_z_bottom"] = z0
    p["_usb_z_center"] = face_cz
    p["_usb_z_top"] = z1

    return shell.cut(usb_cutter)


# =============================================================================
# 组合 / 导出
# =============================================================================

def build_shell_solid(**overrides: float) -> cq.Workplane:
    p = _active_params(**overrides)
    shell = build_base_shell(p)
    shell = cut_art_slot(shell, p)
    shell = cut_type_c_hole(shell, p)
    # 把孔位写回便于调试打印（不参与建模）
    return shell


def describe_usb_pose(**overrides: float) -> dict[str, float]:
    """返回当前参数下 Type-C 孔的关键坐标（mm）。"""
    p = _active_params(**overrides)
    lay = _layout(p)
    wall = p["wall"]
    z_bottom = wall + p["usb_lift_z"]
    z_center = z_bottom + p["usb_h"] * 0.5
    return {
        "x_outer_face": float(lay["out_x1"]),
        "y_center": float(lay["cy"]),
        "z_bottom": float(z_bottom),
        "z_center": float(z_center),
        "z_top": float(z_bottom + p["usb_h"]),
        "width_y": float(p["usb_w"]),
        "height_z": float(p["usb_h"]),
        "bottom_thickness": float(wall),
        "lift_from_inner_floor": float(p["usb_lift_z"]),
    }


def solid_to_trimesh(solid: cq.Workplane, *, tolerance: float = 0.18) -> trimesh.Trimesh:
    shape = solid.val()
    verts, faces = shape.tessellate(tolerance, 0.5)
    vertices = np.asarray([[v.x, v.y, v.z] for v in verts], dtype=np.float64)
    triangles = np.asarray(faces, dtype=np.int64)
    mesh = trimesh.Trimesh(vertices=vertices, faces=triangles, process=True)
    if mesh.is_empty:
        raise ValueError("外壳网格为空")
    return mesh


def build_shell_trimesh(**overrides: float) -> trimesh.Trimesh:
    return solid_to_trimesh(build_shell_solid(**overrides))


def build_shell_from_product_params(
    *,
    art_w: float,
    art_h: float,
    wall_thickness: float,
    corner_radius: float,
    shell_depth: float,
    fit_clearance: float = 0.2,
    top_thickness: float | None = None,
    art_thickness: float | None = None,
    fdm_tol: float | None = None,
) -> trimesh.Trimesh:
    kw: dict[str, float] = {
        "art_w": art_w,
        "art_h": art_h,
        "wall": wall_thickness,
        "corner": corner_radius,
        "depth": shell_depth,
        "clearance": fit_clearance,
    }
    if top_thickness is not None:
        kw["top_thickness"] = top_thickness
    if art_thickness is not None:
        kw["art_thickness"] = art_thickness
    if fdm_tol is not None:
        kw["fdm_tol"] = fdm_tol
    return build_shell_trimesh(**kw)


def export_shell_stl(path: str | Path, **overrides: float) -> trimesh.Trimesh:
    mesh = build_shell_trimesh(**overrides)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(path)
    return mesh


def compute_xy_bounds(
    art_w: float,
    art_h: float,
    wall_thickness: float,
    clearance: float = 0.0,
    top_thickness: float | None = None,
) -> tuple[float, float, float, float]:
    p = _active_params(
        art_w=art_w,
        art_h=art_h,
        wall=wall_thickness,
        clearance=clearance,
        top_thickness=top_thickness if top_thickness is not None else TOP_THICKNESS,
    )
    lay = _layout(p)
    return (
        float(lay["out_x0"]),
        float(lay["out_y0"]),
        float(lay["out_x1"]),
        float(lay["out_y1"]),
    )


def clamp_params(**kwargs: float) -> dict[str, float]:
    rename = {
        "slot_depth": "art_thickness",
        "slot_ledge": "fdm_tol",
    }
    mapped = {rename.get(k, k): v for k, v in kwargs.items()}
    return _active_params(**mapped)


def load_param_sheet() -> dict[str, Any]:
    if not _PARAMS_PATH.is_file():
        return {"parameters": {}, "constants": {}}
    return json.loads(_PARAMS_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    out = _ROOT / "preview_shell.stl"
    mesh = export_shell_stl(out)
    p = _active_params()
    lay = _layout(p)
    print(f"exported {out}")
    print(f"watertight={mesh.is_watertight} faces={len(mesh.faces)}")
    print(f"bounds={mesh.bounds.tolist()}")
    print(
        f"wall={p['wall']} inset={p['inset_side']} "
        f"cavity={lay['cav_w']:.1f}x{lay['cav_h']:.1f} "
        f"outer={lay['out_w']:.1f}x{lay['out_h']:.1f}"
    )
    pose = describe_usb_pose()
    print(
        f"USB z_bottom={pose['z_bottom']:.1f} "
        f"(wall {pose['bottom_thickness']:.1f} + lift {pose['lift_from_inner_floor']:.1f})"
    )
