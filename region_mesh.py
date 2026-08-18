"""色块连通域网格：强融合抖动 → 丝滑去像素 → 强制圆角 → 挤出。

目标：
1. 抖动保留浅色；网格阶段把散点收成大色块（邻接小块合并，极小点清理）
2. 大面积边缘轻光顺，整体呈照片般曲线，弱化像素感
3. 画片四角：完整直角生成后精确裁圆角（体素兜底 + 多边形求交）
4. OpenCV 轮廓路径，避免海量矩形 unary_union 卡死
"""

from __future__ import annotations

import os
from collections.abc import Iterable

import cv2
import numpy as np

LAYER_HEIGHT_DEFAULT = 0.08
# 过小色块直接丢掉（后续由邻域吸收），减轻浮空与像素点
MIN_REGION_AREA = int(os.environ.get("FDM_REGION_MIN_AREA", "4") or "4")
# 边缘去像素（像素倍数）；略大 → 大色块更丝滑
SMOOTH_PX = float(os.environ.get("FDM_REGION_SMOOTH_PX", "0.95") or "0.95")
SIMPLIFY_PX = float(os.environ.get("FDM_REGION_SIMPLIFY_PX", "0.22") or "0.22")
SMOOTH_REF_MPP = float(os.environ.get("FDM_REGION_SMOOTH_REF_MPP", "0.28") or "0.28")
SMOOTH_ADAPT_POWER = float(os.environ.get("FDM_REGION_SMOOTH_POWER", "0.55") or "0.55")
MAX_AREA_DRIFT = float(os.environ.get("FDM_REGION_MAX_AREA_DRIFT", "0.06") or "0.06")
# 闭运算核：只粘合紧邻抖动点；过大+众数抹平会把整张图收成实心板
COALESCE_CLOSE = int(os.environ.get("FDM_REGION_COALESCE", "3") or "3")
COALESCE_ITERS = int(os.environ.get("FDM_REGION_COALESCE_ITERS", "1") or "1")
# 小于此面积的岛：先尝试被邻域吸收，否则清除
ABSORB_AREA = int(os.environ.get("FDM_REGION_ABSORB_AREA", "10") or "10")
# 超过此面积禁止众数抹平，保留逐像素层高
COALESCE_MODE_MAX_AREA = int(os.environ.get("FDM_REGION_MODE_MAX_AREA", "120") or "120")


def _adaptive_edge_px(base_px: float, pixel_size: float) -> float:
    """像素越密，按像素计的圆滑量略降，但保持足够丝滑。"""
    base = max(0.0, float(base_px))
    if base <= 1e-12:
        return 0.0
    ref = max(1e-6, float(SMOOTH_REF_MPP))
    power = max(0.0, min(1.5, float(SMOOTH_ADAPT_POWER)))
    ratio = float(pixel_size) / ref
    # 更密时也不要掉太狠，否则又变回像素台阶
    factor = max(0.55, min(1.25, ratio**power))
    return base * factor


def _keep_mask_rounded_rect(
    grid_h: int,
    grid_w: int,
    *,
    width_mm: float,
    height_mm: float,
    radius_mm: float,
) -> np.ndarray:
    """圆角矩形内为 True；用于融合后挖四角，保证盘面一定有圆角。"""
    pixel = float(width_mm) / max(1, float(grid_w))
    w = float(width_mm)
    h = float(height_mm)
    r = min(float(radius_mm), w * 0.5 - pixel * 0.2, h * 0.5 - pixel * 0.2)
    if r <= 1e-6:
        return np.ones((grid_h, grid_w), dtype=bool)
    xs = (np.arange(grid_w, dtype=np.float64) + 0.5) * pixel
    ys = (grid_h - np.arange(grid_h, dtype=np.float64) - 0.5) * pixel
    xx, yy = np.meshgrid(xs, ys)
    outside = (
        ((xx < r) & (yy < r) & ((xx - r) ** 2 + (yy - r) ** 2 > r * r))
        | ((xx > w - r) & (yy < r) & ((xx - (w - r)) ** 2 + (yy - r) ** 2 > r * r))
        | ((xx > w - r) & (yy > h - r) & ((xx - (w - r)) ** 2 + (yy - (h - r)) ** 2 > r * r))
        | ((xx < r) & (yy > h - r) & ((xx - r) ** 2 + (yy - (h - r)) ** 2 > r * r))
    )
    return ~outside


def _merge_mask_rects(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """把 True 掩膜合并成矩形。"""
    h, w = mask.shape
    used = np.zeros((h, w), dtype=bool)
    rects: list[tuple[int, int, int, int]] = []
    for y in range(h):
        x = 0
        while x < w:
            if used[y, x] or not mask[y, x]:
                x += 1
                continue
            x_end = x + 1
            while x_end < w and mask[y, x_end] and not used[y, x_end]:
                x_end += 1
            y_end = y + 1
            while y_end < h and np.all(mask[y_end, x:x_end]) and not np.any(used[y_end, x:x_end]):
                y_end += 1
            used[y:y_end, x:x_end] = True
            rects.append((x, x_end, y, y_end))
            x = x_end
    return rects


def _rects_to_prism_arrays(
    rects: list[tuple[int, int, int, int]],
    *,
    pixel_size: float,
    grid_h: int,
    offset_x: float,
    offset_y: float,
    z0: float,
    z1: float,
) -> tuple[np.ndarray, np.ndarray]:
    """体素回退：每个矩形一个封闭盒子（不互叠）。"""
    if not rects:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32)
    all_v: list[np.ndarray] = []
    all_f: list[np.ndarray] = []
    v_off = 0
    box_faces = np.array(
        [
            [0, 1, 2],
            [0, 2, 3],
            [4, 6, 5],
            [4, 7, 6],
            [0, 4, 5],
            [0, 5, 1],
            [1, 5, 6],
            [1, 6, 2],
            [2, 6, 7],
            [2, 7, 3],
            [3, 7, 4],
            [3, 4, 0],
        ],
        dtype=np.int32,
    )
    for x0i, x1i, y0i, y1i in rects:
        x0 = x0i * pixel_size + offset_x
        x1 = x1i * pixel_size + offset_x
        yw0 = (grid_h - y1i) * pixel_size + offset_y
        yw1 = (grid_h - y0i) * pixel_size + offset_y
        verts = np.array(
            [
                [x0, yw0, z0],
                [x1, yw0, z0],
                [x1, yw1, z0],
                [x0, yw1, z0],
                [x0, yw0, z1],
                [x1, yw0, z1],
                [x1, yw1, z1],
                [x0, yw1, z1],
            ],
            dtype=np.float64,
        )
        all_v.append(verts)
        all_f.append(box_faces + v_off)
        v_off += 8
    return np.vstack(all_v), np.vstack(all_f)


def _iter_polygons(geom) -> Iterable:
    if geom is None or geom.is_empty:
        return
    gtype = geom.geom_type
    if gtype == "Polygon":
        yield geom
    elif gtype == "MultiPolygon":
        for g in geom.geoms:
            if not g.is_empty:
                yield g
    elif gtype == "GeometryCollection":
        for g in geom.geoms:
            yield from _iter_polygons(g)


def _restore_area_centroid(ref, geom):
    """圆滑后对齐质心并回补面积（只在裁圆角之前调用，禁止裁角后再 restore）。

    变大：只平移不缩小，保住色块尺度；变小：有限放大回补。
    """
    from shapely import affinity

    if ref is None or geom is None or ref.is_empty or geom.is_empty:
        return ref
    a0 = float(ref.area)
    a1 = float(geom.area)
    if a0 <= 1e-12 or a1 <= 1e-12:
        return ref
    if a1 < a0 * 0.55 or a1 > a0 * 1.45:
        return ref

    c0 = ref.centroid
    c1 = geom.centroid
    moved = affinity.translate(geom, xoff=float(c0.x - c1.x), yoff=float(c0.y - c1.y))
    a_m = float(moved.area)
    if a_m <= 1e-12:
        return ref

    drift = max(0.0, float(MAX_AREA_DRIFT))
    # 面积未明显缩小：只平移
    if a_m >= a0 * (1.0 - drift):
        return moved

    # 面积变小：轻微放大回补，但限制倍率
    scale = (a0 / a_m) ** 0.5
    if scale > 1.12:
        return ref
    restored = affinity.scale(moved, xfact=scale, yfact=scale, origin=(float(c0.x), float(c0.y)))
    try:
        restored = restored.buffer(0)
    except Exception:
        return moved
    if restored.is_empty:
        return moved
    return restored


def _rounded_rect_polygon(
    width_mm: float,
    height_mm: float,
    radius_mm: float,
    *,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    resolution: int = 40,
):
    """精确圆角矩形（用于裁出完整圆弧，避免像素台阶缺口）。"""
    from shapely.geometry import Point, box
    from shapely.ops import unary_union

    w = float(width_mm)
    h = float(height_mm)
    ox = float(offset_x)
    oy = float(offset_y)
    r = min(max(0.0, float(radius_mm)), w * 0.5, h * 0.5)
    if r <= 1e-9:
        return box(ox, oy, ox + w, oy + h)
    core = unary_union(
        [
            box(ox + r, oy, ox + w - r, oy + h),
            box(ox, oy + r, ox + w, oy + h - r),
        ]
    )
    corners = [
        Point(ox + r, oy + r).buffer(r, resolution=resolution),
        Point(ox + w - r, oy + r).buffer(r, resolution=resolution),
        Point(ox + w - r, oy + h - r).buffer(r, resolution=resolution),
        Point(ox + r, oy + h - r).buffer(r, resolution=resolution),
    ]
    return unary_union([core, *corners])


def _contour_pts_to_world(
    cnt: np.ndarray,
    *,
    pixel_size: float,
    grid_h: int,
    offset_x: float,
    offset_y: float,
    pad_offset: float = 0.0,
) -> np.ndarray:
    pts = cnt.reshape(-1, 2).astype(np.float64) - float(pad_offset)
    xs = pts[:, 0] * pixel_size + offset_x
    ys = (grid_h - pts[:, 1]) * pixel_size + offset_y
    return np.column_stack([xs, ys])


def _mask_to_shapely_fast(
    mask: np.ndarray,
    *,
    pixel_size: float,
    grid_h: int,
    offset_x: float,
    offset_y: float,
):
    """用 OpenCV 轮廓提取直角掩膜多边形（避免成千上万矩形 unary_union 卡死）。

    外围垫 1px 再取轮廓，使满幅掩膜覆盖完整 [0,W]×[0,H] mm，
    否则圆角裁切框碰不到真正的四角。
    """
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    if not np.any(mask):
        return None
    u8 = np.ascontiguousarray(mask.astype(np.uint8) * 255)
    padded = cv2.copyMakeBorder(u8, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    contours, hierarchy = cv2.findContours(
        padded, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours or hierarchy is None:
        return None
    hier = hierarchy[0]
    polys = []
    min_area_px = 0.5
    for i, cnt in enumerate(contours):
        if hier[i][3] != -1:
            continue
        if cv2.contourArea(cnt) < min_area_px:
            continue
        ext = _contour_pts_to_world(
            cnt,
            pixel_size=pixel_size,
            grid_h=grid_h,
            offset_x=offset_x,
            offset_y=offset_y,
            pad_offset=1.0,
        )
        if len(ext) < 3:
            continue
        holes = []
        child = hier[i][2]
        while child != -1:
            hcnt = contours[child]
            if cv2.contourArea(hcnt) >= min_area_px:
                hp = _contour_pts_to_world(
                    hcnt,
                    pixel_size=pixel_size,
                    grid_h=grid_h,
                    offset_x=offset_x,
                    offset_y=offset_y,
                    pad_offset=1.0,
                )
                if len(hp) >= 3:
                    holes.append(hp)
            child = hier[child][0]
        try:
            poly = Polygon(ext, holes if holes else None)
            if not poly.is_valid:
                poly = poly.buffer(0)
            for p in _iter_polygons(poly):
                if float(p.area) > 1e-12:
                    polys.append(p)
        except Exception:
            continue
    if not polys:
        return None
    if len(polys) == 1:
        return polys[0]
    try:
        return unary_union(polys)
    except Exception:
        return polys[0]




def _hard_clip_to_poly(geom, clip_poly):
    """强制裁进圆角框；失败或空则返回 None（绝不可保留未裁直角）。"""
    if geom is None or getattr(geom, "is_empty", True):
        return None
    if clip_poly is None or getattr(clip_poly, "is_empty", True):
        return geom
    try:
        clipped = geom.intersection(clip_poly)
    except Exception:
        try:
            clipped = geom.buffer(0).intersection(clip_poly.buffer(0))
        except Exception:
            return None
    if clipped is None or clipped.is_empty:
        return None
    try:
        if float(clipped.area) <= 1e-12:
            return None
    except Exception:
        return None
    return clipped


def _mask_to_union_polygons(
    mask: np.ndarray,
    *,
    pixel_size: float,
    grid_h: int,
    offset_x: float,
    offset_y: float,
    smooth_px: float,
    simplify_px: float,
    clip_poly=None,
):
    """直角轮廓 → 边缘去像素 → 强制圆角裁切（失败则丢弃，避免色块冒出圆角外）。"""
    union = _mask_to_shapely_fast(
        mask,
        pixel_size=pixel_size,
        grid_h=grid_h,
        offset_x=offset_x,
        offset_y=offset_y,
    )
    if union is None or getattr(union, "is_empty", True):
        return []

    try:
        union = union.buffer(0)
    except Exception:
        pass

    pre_simp = max(float(pixel_size) * 0.08, 1e-4)
    try:
        slim = union.simplify(pre_simp, preserve_topology=True)
        if not slim.is_empty:
            union = slim
    except Exception:
        pass

    ref = union
    area_px = float(ref.area) / max(pixel_size * pixel_size, 1e-12)
    # 大色块多光顺；小碎块少外扩，避免顶出圆角后再裁失败
    area_boost = 1.0
    if area_px >= 280:
        area_boost = 1.25
    elif area_px >= 80:
        area_boost = 1.1
    elif area_px < 40:
        area_boost = 0.35

    sm = max(0.0, float(smooth_px)) * float(pixel_size) * area_boost
    if sm > 1e-9 and float(ref.area) > 0:
        try:
            smoothed = ref.buffer(sm, join_style=1, resolution=10)
            smoothed = smoothed.buffer(-sm, join_style=1, resolution=10)
            smoothed = smoothed.buffer(0)
            union = _restore_area_centroid(ref, smoothed)
        except Exception:
            union = ref

    simp = max(0.0, float(simplify_px)) * float(pixel_size)
    if simp > 1e-9:
        try:
            simplified = union.simplify(simp, preserve_topology=True)
            union = _restore_area_centroid(ref, simplified)
        except Exception:
            pass

    # 光顺可能外扩：必须强制裁回圆角；裁空则整块丢弃（不能保留直角冒头）
    if clip_poly is not None and not getattr(clip_poly, "is_empty", True):
        clipped = _hard_clip_to_poly(union, clip_poly)
        if clipped is None:
            return []
        union = clipped

    min_area = (pixel_size * pixel_size) * 0.25
    out = []
    for poly in _iter_polygons(union):
        if float(poly.area) < min_area:
            continue
        if not poly.is_valid:
            try:
                poly = poly.buffer(0)
            except Exception:
                continue
        if poly.is_empty or float(poly.area) < min_area:
            continue
        # 再保险：每个子面也强制在圆角内
        if clip_poly is not None:
            poly2 = _hard_clip_to_poly(poly, clip_poly)
            if poly2 is None:
                continue
            for p in _iter_polygons(poly2):
                if float(p.area) >= min_area:
                    out.append(p)
        else:
            out.append(poly)
    return out


def _cut_mesh_arrays_with_polygon(
    verts: np.ndarray,
    faces: np.ndarray,
    clip_poly,
    *,
    z0: float,
    z1: float,
) -> tuple[np.ndarray, np.ndarray]:
    """直角网格生成后强制圆角裁切；失败则丢弃（不可退回未裁直角）。"""
    import trimesh

    empty = (np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32))
    if clip_poly is None or getattr(clip_poly, "is_empty", True):
        return verts, faces
    if len(verts) == 0 or len(faces) == 0:
        return empty
    height = float(z1) - float(z0)
    if height <= 1e-9:
        return empty
    try:
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        cutter = trimesh.creation.extrude_polygon(clip_poly, height=height + 0.04)
        cutter.apply_translation([0.0, 0.0, float(z0) - 0.02])
        try:
            out = mesh.intersection(cutter, engine="manifold")
        except Exception:
            out = mesh.intersection(cutter)
        if out is None or len(getattr(out, "faces", [])) == 0:
            return empty
        if isinstance(out, list):
            out = trimesh.util.concatenate(
                [m for m in out if m is not None and len(m.faces)]
            )
        v = np.asarray(out.vertices, dtype=np.float64)
        f = np.asarray(out.faces, dtype=np.int32)
        if len(v) == 0 or len(f) == 0:
            return empty
        return v, f
    except Exception:
        return empty


def _try_make_watertight(mesh):
    """尽量修补挤出网格；失败则原样返回。"""
    if mesh is None or len(getattr(mesh, "faces", [])) == 0:
        return mesh
    if bool(getattr(mesh, "is_watertight", False)):
        return mesh
    try:
        mesh.fill_holes()
    except Exception:
        pass
    try:
        mesh.process(validate=True)
    except Exception:
        try:
            mesh.remove_duplicate_faces()
            mesh.remove_unreferenced_vertices()
        except Exception:
            pass
    return mesh


def _extrude_polygons(
    polygons,
    z0: float,
    z1: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Shapely 多边形挤出为三角网格（保留洞，不填实外环）。"""
    import trimesh

    height = float(z1) - float(z0)
    if height <= 1e-9 or not polygons:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32)

    meshes = []
    for poly in polygons:
        try:
            fixed = poly.buffer(0)
        except Exception:
            fixed = poly
        parts = list(_iter_polygons(fixed)) or (
            [poly] if getattr(poly, "geom_type", "") == "Polygon" else []
        )
        for part in parts:
            if part.is_empty or float(part.area) <= 0:
                continue
            try:
                mesh = trimesh.creation.extrude_polygon(part, height=height)
            except Exception:
                continue
            if mesh is None or len(mesh.faces) == 0:
                continue
            mesh = _try_make_watertight(mesh)
            if mesh is None or len(mesh.faces) == 0:
                continue
            mesh.apply_translation([0.0, 0.0, float(z0)])
            meshes.append(mesh)

    if not meshes:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32)

    combined = trimesh.util.concatenate(meshes)
    try:
        combined.remove_duplicate_faces()
        combined.update_faces(combined.nondegenerate_faces())
        combined.remove_unreferenced_vertices()
    except Exception:
        pass
    v = np.asarray(combined.vertices, dtype=np.float64)
    f = np.asarray(combined.faces, dtype=np.int32)
    return v, f


def _rects_to_clipped_extrude(
    rects: list[tuple[int, int, int, int]],
    *,
    pixel_size: float,
    grid_h: int,
    offset_x: float,
    offset_y: float,
    z0: float,
    z1: float,
    clip_poly=None,
) -> tuple[np.ndarray, np.ndarray]:
    """体素矩形 → 2D 并集 →（可选）圆角求交 → 挤出。比 3D 布尔更稳。"""
    from shapely.geometry import box
    from shapely.ops import unary_union

    if not rects:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32)
    polys = []
    for x0i, x1i, y0i, y1i in rects:
        x0 = x0i * pixel_size + offset_x
        x1 = x1i * pixel_size + offset_x
        yw0 = (grid_h - y1i) * pixel_size + offset_y
        yw1 = (grid_h - y0i) * pixel_size + offset_y
        if x1 <= x0 or yw1 <= yw0:
            continue
        polys.append(box(float(x0), float(yw0), float(x1), float(yw1)))
    if not polys:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32)
    try:
        union = polys[0] if len(polys) == 1 else unary_union(polys)
        union = union.buffer(0)
    except Exception:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32)
    if clip_poly is not None and not getattr(clip_poly, "is_empty", True):
        clipped = _hard_clip_to_poly(union, clip_poly)
        if clipped is None:
            return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32)
        union = clipped
    return _extrude_polygons(list(_iter_polygons(union)), z0, z1)


def _coalesce_height_fields(
    matrix: np.ndarray,
    z_start: np.ndarray,
    *,
    close_k: int = 3,
    close_iters: int = 1,
    absorb_area: int = 10,
) -> tuple[np.ndarray, np.ndarray]:
    """抖动散点轻度融合，严禁把整幅画面抹成实心板。

    - 小核闭运算：只粘合紧邻细点
    - 小连通域：众数层高（去一像素柱 / 浮空）
    - 大连通域：保留逐像素层高，只填闭运算新增的缝
    - 极小岛：邻域吸收，否则清除
    """
    mat = np.asarray(matrix, dtype=np.int32)
    zs = np.asarray(z_start, dtype=np.int32)
    if not np.any(mat > 0):
        return mat.copy(), zs.copy()

    mat_work = mat.copy()

    occ = (mat_work > 0).astype(np.uint8)
    k = max(0, int(close_k))
    iters = max(0, int(close_iters))
    if k <= 0 or iters <= 0:
        closed = occ.copy()
        k = 0
        iters = 0
    else:
        if k % 2 == 0:
            k += 1
        kernel = np.ones((k, k), np.uint8)
        closed = cv2.morphologyEx(occ, cv2.MORPH_CLOSE, kernel, iterations=iters)

    # 向闭运算新增空隙传播邻域层高（不改已有像素）
    filled_m = np.clip(mat_work, 0, 255).astype(np.uint8)
    filled_z = np.clip(zs, 0, 255).astype(np.uint8)
    steps = max(1, (k // 2 + iters) if k else 1)
    for _ in range(steps):
        need = (closed > 0) & (filled_m == 0)
        if not np.any(need):
            break
        dil_m = cv2.dilate(filled_m, np.ones((3, 3), np.uint8))
        dil_z = cv2.dilate(filled_z, np.ones((3, 3), np.uint8))
        take = need & (dil_m > 0)
        filled_m[take] = dil_m[take]
        filled_z[take] = dil_z[take]
    filled_m[closed == 0] = 0
    filled_z[closed == 0] = 0

    n_label, labels, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    out_m = np.zeros_like(mat_work)
    out_z = np.zeros_like(zs)
    tiny_mask = np.zeros_like(closed, dtype=bool)
    abs_lim = max(1, int(absorb_area))
    mode_max = max(abs_lim + 1, int(COALESCE_MODE_MAX_AREA))

    for lab in range(1, n_label):
        comp = labels == lab
        area = int(stats[lab, cv2.CC_STAT_AREA])
        src = comp & (filled_m > 0)
        if not np.any(src):
            continue
        if area < abs_lim:
            tiny_mask |= comp
            continue
        if area <= mode_max:
            # 小色块：众数抹平，减少碎柱
            vals, counts = np.unique(filled_m[src], return_counts=True)
            layer_mode = int(vals[int(np.argmax(counts))])
            zvals, zcounts = np.unique(filled_z[src], return_counts=True)
            z_mode = int(zvals[int(np.argmax(zcounts))])
            if layer_mode <= 0:
                continue
            out_m[comp] = layer_mode
            out_z[comp] = z_mode
        else:
            # 大色块：保留逐像素高度（否则整张图变成一层实心板）
            out_m[comp] = filled_m[comp].astype(np.int32)
            out_z[comp] = filled_z[comp].astype(np.int32)

    if np.any(tiny_mask):
        dil_m = cv2.dilate(np.clip(out_m, 0, 255).astype(np.uint8), np.ones((5, 5), np.uint8))
        dil_z = cv2.dilate(np.clip(out_z, 0, 255).astype(np.uint8), np.ones((5, 5), np.uint8))
        take = tiny_mask & (dil_m > 0)
        out_m[take] = dil_m[take].astype(np.int32)
        out_z[take] = dil_z[take].astype(np.int32)
        out_m[tiny_mask & (out_m <= 0)] = 0
        out_z[tiny_mask & (out_m <= 0)] = 0

    return out_m.astype(np.int32), out_z.astype(np.int32)


def _unique_keys(matrix: np.ndarray, z_start: np.ndarray) -> Iterable[tuple[int, int]]:
    mask = matrix > 0
    if not np.any(mask):
        return []
    layers = matrix[mask].astype(np.int32)
    zs = z_start[mask].astype(np.int32)
    stacked = np.column_stack([layers, zs])
    return [tuple(map(int, row)) for row in np.unique(stacked, axis=0)]


def build_region_mesh_arrays(
    matrix: np.ndarray,
    z_start_matrix: np.ndarray,
    *,
    pixel_size: float,
    grid_h: int,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    layer_height: float = LAYER_HEIGHT_DEFAULT,
    smooth_iters: int | None = None,
    art_width_mm: float | None = None,
    art_height_mm: float | None = None,
    corner_radius_mm: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """融合 →（可选）挖圆角体素 → 轮廓光顺 → 精确圆角求交 → 挤出。"""
    del smooth_iters
    smooth_px = _adaptive_edge_px(SMOOTH_PX, pixel_size)
    simplify_px = _adaptive_edge_px(SIMPLIFY_PX, pixel_size)

    matrix, z_start_matrix = _coalesce_height_fields(
        matrix,
        z_start_matrix,
        close_k=COALESCE_CLOSE,
        close_iters=COALESCE_ITERS,
        absorb_area=ABSORB_AREA,
    )

    clip_poly = None
    art_w = float(art_width_mm) if art_width_mm else 0.0
    art_h = float(art_height_mm) if art_height_mm else 0.0
    # 画片默认至少 5mm 圆角（None）；显式传 0 才直角。与 main.resolve_corner_radius 一致。
    corner = float(corner_radius_mm) if corner_radius_mm is not None else 5.0
    if corner < 0:
        corner = 0.0
    if art_w > 1e-6 and art_h > 1e-6 and corner > 1e-6:
        keep = _keep_mask_rounded_rect(
            int(matrix.shape[0]),
            int(matrix.shape[1]),
            width_mm=art_w,
            height_mm=art_h,
            radius_mm=corner,
        )
        matrix = np.asarray(matrix, dtype=np.int32).copy()
        z_start_matrix = np.asarray(z_start_matrix, dtype=np.int32).copy()
        matrix[~keep] = 0
        z_start_matrix[~keep] = 0
        try:
            clip_poly = _rounded_rect_polygon(
                art_w,
                art_h,
                corner,
                offset_x=offset_x,
                offset_y=offset_y,
                resolution=48,
            )
        except Exception:
            clip_poly = None

    all_v: list[np.ndarray] = []
    all_f: list[np.ndarray] = []
    v_off = 0
    for layers, zs in _unique_keys(matrix, z_start_matrix):
        mask = (matrix == layers) & (z_start_matrix == zs)
        n_label, labels, stats, _ = cv2.connectedComponentsWithStats(
            mask.astype(np.uint8), connectivity=8
        )
        clean = np.zeros_like(mask, dtype=bool)
        for lab in range(1, n_label):
            area = int(stats[lab, cv2.CC_STAT_AREA])
            if area >= MIN_REGION_AREA:
                clean |= labels == lab
        if not np.any(clean):
            continue
        z0 = zs * layer_height
        z1 = (zs + layers) * layer_height

        verts = faces = None
        try:
            polys = _mask_to_union_polygons(
                clean,
                pixel_size=pixel_size,
                grid_h=grid_h,
                offset_x=offset_x,
                offset_y=offset_y,
                smooth_px=smooth_px,
                simplify_px=simplify_px,
                clip_poly=clip_poly,
            )
            verts, faces = _extrude_polygons(polys, z0, z1)
        except Exception:
            verts, faces = np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32)

        if verts is None or len(verts) == 0 or faces is None or len(faces) == 0:
            rects = _merge_mask_rects(clean)
            verts, faces = _rects_to_clipped_extrude(
                rects,
                pixel_size=pixel_size,
                grid_h=grid_h,
                offset_x=offset_x,
                offset_y=offset_y,
                z0=z0,
                z1=z1,
                clip_poly=clip_poly,
            )
            # 有圆角时禁止回退到未裁直角棱柱（否则 C/M/Y 会冒出圆角外）
            if (verts is None or len(verts) == 0) and rects and clip_poly is None:
                verts, faces = _rects_to_prism_arrays(
                    rects,
                    pixel_size=pixel_size,
                    grid_h=grid_h,
                    offset_x=offset_x,
                    offset_y=offset_y,
                    z0=z0,
                    z1=z1,
                )
            elif (verts is None or len(verts) == 0) and rects and clip_poly is not None:
                verts, faces = _rects_to_prism_arrays(
                    rects,
                    pixel_size=pixel_size,
                    grid_h=grid_h,
                    offset_x=offset_x,
                    offset_y=offset_y,
                    z0=z0,
                    z1=z1,
                )
                verts, faces = _cut_mesh_arrays_with_polygon(
                    verts, faces, clip_poly, z0=z0, z1=z1
                )

        if len(verts) and len(faces):
            all_v.append(verts)
            all_f.append(faces + v_off)
            v_off += len(verts)

    if not all_v:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32)
    return np.vstack(all_v), np.vstack(all_f)


def arrays_to_3mf_xml(vertices: np.ndarray, faces: np.ndarray) -> tuple[str, str, int]:
    if len(vertices) == 0 or len(faces) == 0:
        return "", "", 0
    vertex_xml = "".join(
        f'<vertex x="{a:.4f}" y="{b:.4f}" z="{c:.4f}"/>' for a, b, c in vertices
    )
    triangle_xml = "".join(
        f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces.astype(np.int32)
    )
    return vertex_xml, triangle_xml, int(len(faces))


def build_region_mesh_xml(
    matrix: np.ndarray,
    z_start_matrix: np.ndarray,
    pixel_size: float,
    *,
    layer_height: float = LAYER_HEIGHT_DEFAULT,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    smooth_iters: int | None = None,
    art_width_mm: float | None = None,
    art_height_mm: float | None = None,
    corner_radius_mm: float = 0.0,
) -> tuple[str, str, int]:
    h, _w = matrix.shape
    verts, faces = build_region_mesh_arrays(
        matrix,
        z_start_matrix,
        pixel_size=pixel_size,
        grid_h=h,
        offset_x=offset_x,
        offset_y=offset_y,
        layer_height=layer_height,
        smooth_iters=smooth_iters,
        art_width_mm=art_width_mm,
        art_height_mm=art_height_mm,
        corner_radius_mm=corner_radius_mm,
    )
    return arrays_to_3mf_xml(verts, faces)
