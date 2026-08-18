"""圆角灯箱外壳：对接 CadQuery 参数母本（表达式见 shell_master/）。"""

from __future__ import annotations

import numpy as np
import open3d as o3d
import trimesh

from shell_master.shell_cadquery import (
    TOP_THICKNESS,
    build_shell_from_product_params,
    compute_xy_bounds,
    export_shell_stl,
)

# 兼容旧常量名（校验脚本 / 外部引用）
SLOT_LEDGE_MM = 1.2
SLOT_DEPTH_MM = 2.5
SLOT_OUTWARD_MM = 5.0


def _trimesh_to_open3d(
    mesh: trimesh.Trimesh, color: tuple[float, float, float]
) -> o3d.geometry.TriangleMesh:
    if hasattr(mesh, "remove_duplicate_faces"):
        mesh.remove_duplicate_faces()
        mesh.remove_degenerate_faces()
    else:
        mesh.update_faces(mesh.unique_faces())
        mesh.update_faces(mesh.nondegenerate_faces())
        mesh.remove_unreferenced_vertices()
    o3d_mesh = o3d.geometry.TriangleMesh(
        o3d.utility.Vector3dVector(np.asarray(mesh.vertices, dtype=np.float64)),
        o3d.utility.Vector3iVector(np.asarray(mesh.faces, dtype=np.int32)),
    )
    o3d_mesh.remove_degenerate_triangles()
    o3d_mesh.remove_duplicated_triangles()
    o3d_mesh.remove_unreferenced_vertices()
    o3d_mesh.compute_vertex_normals()
    o3d_mesh.paint_uniform_color(list(color))
    return o3d_mesh


def build_hollow_shell_trimesh(
    inner_w: float,
    inner_h: float,
    wall_thickness: float,
    corner_radius: float,
    *,
    z_back: float = 0.0,
    z_front: float = 18.0,
    floor_thickness: float | None = None,
    clearance: float = 0.0,
    art_w: float | None = None,
    art_h: float | None = None,
) -> trimesh.Trimesh:
    """圆角灯箱：CadQuery 母本生成（含正面画片卡槽）。"""
    del inner_w, inner_h, floor_thickness
    if art_w is None or art_h is None:
        raise ValueError("build_hollow_shell_trimesh 需要 art_w / art_h")
    if abs(z_back) > 1e-9:
        raise ValueError("母本坐标系要求 z_back=0")
    mesh = build_shell_from_product_params(
        art_w=float(art_w),
        art_h=float(art_h),
        wall_thickness=float(wall_thickness),
        corner_radius=float(corner_radius),
        shell_depth=float(z_front),
        fit_clearance=max(0.0, float(clearance)),
    )
    return mesh


def build_hollow_shell_mesh(
    inner_w: float,
    inner_h: float,
    wall_thickness: float,
    corner_radius: float,
    *,
    z_back: float = 0.0,
    z_front: float = 18.0,
    color: tuple[float, float, float] = (0.25, 0.25, 0.28),
    floor_thickness: float | None = None,
    clearance: float = 0.0,
    art_w: float | None = None,
    art_h: float | None = None,
) -> o3d.geometry.TriangleMesh:
    """圆角灯箱 Open3D 网格（含正面画片卡槽）。"""
    shell = build_hollow_shell_trimesh(
        inner_w,
        inner_h,
        wall_thickness,
        corner_radius,
        z_back=z_back,
        z_front=z_front,
        floor_thickness=floor_thickness,
        clearance=clearance,
        art_w=art_w,
        art_h=art_h,
    )
    return _trimesh_to_open3d(shell, color)


def export_hollow_shell_stl(
    output_path: str,
    art_w: float,
    art_h: float,
    *,
    wall_thickness: float,
    corner_radius: float,
    shell_depth: float,
    fit_clearance: float = 0.0,
) -> trimesh.Trimesh:
    """导出单一个体外壳 STL（含正面卡槽）。"""
    return export_shell_stl(
        output_path,
        art_w=art_w,
        art_h=art_h,
        wall=wall_thickness,
        corner=corner_radius,
        depth=shell_depth,
        clearance=max(0.0, fit_clearance),
    )


def compute_shell_xy_bounds(
    art_w: float,
    art_h: float,
    wall_thickness: float,
    corner_radius: float,
    clearance: float = 0.0,
) -> tuple[float, float, float, float]:
    """外壳 XY 包围盒（min_x, min_y, max_x, max_y）。"""
    del corner_radius
    return compute_xy_bounds(art_w, art_h, wall_thickness, clearance)


def compute_art_bounds(
    physical_width_mm: float,
    grid_w: int,
    grid_h: int,
    max_layer_stack: int,
    *,
    layer_height: float,
) -> dict[str, float]:
    return {
        "max_x": physical_width_mm,
        "max_y": physical_width_mm * grid_h / grid_w,
        "max_z": max_layer_stack * layer_height,
    }


def build_lightbox_shell(
    physical_width_mm: float,
    grid_w: int,
    grid_h: int,
    max_layer_stack: int,
    *,
    layer_height: float,
    fit_clearance: float,
    wall_thickness: float,
    corner_radius: float,
    shell_depth: float,
    shell_color: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> o3d.geometry.TriangleMesh:
    bounds = compute_art_bounds(
        physical_width_mm,
        grid_w,
        grid_h,
        max_layer_stack,
        layer_height=layer_height,
    )
    clearance = max(0.0, fit_clearance)
    art_w = bounds["max_x"]
    art_h = bounds["max_y"]

    return build_hollow_shell_mesh(
        0.0,
        0.0,
        wall_thickness,
        corner_radius,
        z_back=0.0,
        z_front=shell_depth,
        color=shell_color,
        floor_thickness=wall_thickness,
        clearance=clearance,
        art_w=art_w,
        art_h=art_h,
    )


def _mesh_arrays_to_3mf_xml(
    vertices: np.ndarray,
    triangles: np.ndarray,
    *,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> tuple[str, str]:
    verts = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(triangles, dtype=np.int32)
    if offset_x or offset_y:
        verts = verts.copy()
        verts[:, 0] += offset_x
        verts[:, 1] += offset_y
    vertex_xml = "".join(
        f'<vertex x="{x:.3f}" y="{y:.3f}" z="{z:.3f}"/>' for x, y, z in verts
    )
    triangle_xml = "".join(
        f'<triangle v1="{i0}" v2="{i1}" v3="{i2}"/>' for i0, i1, i2 in faces
    )
    return vertex_xml, triangle_xml


def shell_mesh_to_3mf_xml(
    physical_width_mm: float,
    grid_w: int,
    grid_h: int,
    max_layer_stack: int,
    *,
    layer_height: float,
    fit_clearance: float,
    wall_thickness: float,
    corner_radius: float,
    shell_depth: float,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> tuple[str, str]:
    shell = build_lightbox_shell(
        physical_width_mm,
        grid_w,
        grid_h,
        max_layer_stack,
        layer_height=layer_height,
        fit_clearance=fit_clearance,
        wall_thickness=wall_thickness,
        corner_radius=corner_radius,
        shell_depth=shell_depth,
    )
    return _mesh_arrays_to_3mf_xml(
        np.asarray(shell.vertices, dtype=np.float64),
        np.asarray(shell.triangles, dtype=np.int32),
        offset_x=offset_x,
        offset_y=offset_y,
    )


def top_solid_modifier_to_3mf_xml(
    physical_width_mm: float,
    grid_w: int,
    grid_h: int,
    max_layer_stack: int,
    *,
    layer_height: float,
    fit_clearance: float,
    wall_thickness: float,
    corner_radius: float,
    shell_depth: float,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    top_thickness: float | None = None,
) -> tuple[str, str]:
    """
    顶壁实心填充修改器长方体（Bambu modifier_part）。
    宽 ≈ 画片宽 − 2×圆角，贴在 +Y 顶墙上。
    """
    bounds = compute_art_bounds(
        physical_width_mm,
        grid_w,
        grid_h,
        max_layer_stack,
        layer_height=layer_height,
    )
    clearance = max(0.0, float(fit_clearance))
    art_w = float(bounds["max_x"])
    art_h = float(bounds["max_y"])
    wall = float(wall_thickness)
    corner = max(0.0, float(corner_radius))
    depth = float(shell_depth)
    top_t = float(TOP_THICKNESS if top_thickness is None else top_thickness)

    out_x0 = clearance - wall
    out_x1 = clearance + art_w + wall
    out_y1 = clearance + art_h + top_t
    inset_top = top_t * 0.5
    cav_y1 = clearance + art_h - inset_top
    top_wall_span = max(0.5, out_y1 - cav_y1)

    box_w = max(8.0, art_w - 2.0 * corner)
    cx = 0.5 * (out_x0 + out_x1)
    x0 = cx - 0.5 * box_w
    x1 = cx + 0.5 * box_w
    # 盖住顶壁：略出外缘 + 向内伸一截，保证与顶墙实体重叠
    y1 = out_y1 + 1.0
    y0 = out_y1 - max(12.0, top_wall_span + 8.0)
    z0 = 0.0
    z1 = depth

    vertices = np.array(
        [
            [x0, y0, z0],
            [x1, y0, z0],
            [x1, y1, z0],
            [x0, y1, z0],
            [x0, y0, z1],
            [x1, y0, z1],
            [x1, y1, z1],
            [x0, y1, z1],
        ],
        dtype=np.float64,
    )
    triangles = np.array(
        [
            [0, 1, 2],
            [0, 2, 3],
            [4, 6, 5],
            [4, 7, 6],
            [0, 4, 5],
            [0, 5, 1],
            [2, 6, 7],
            [2, 7, 3],
            [0, 3, 7],
            [0, 7, 4],
            [1, 5, 6],
            [1, 6, 2],
        ],
        dtype=np.int32,
    )
    return _mesh_arrays_to_3mf_xml(
        vertices, triangles, offset_x=offset_x, offset_y=offset_y
    )
