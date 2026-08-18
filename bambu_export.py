"""Bambu Studio 兼容 3MF 导出：分盘 + 预填颜色。"""

from __future__ import annotations

import json
import re
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from shell import compute_shell_xy_bounds

# 拓竹 PLA Basic 官方色（CMYK 透光画套装）
BAMBU_PLA_CYAN = "#0086D6"
BAMBU_PLA_MAGENTA = "#EC008C"
BAMBU_PLA_YELLOW = "#F4EE2A"
BAMBU_PLA_JADE_WHITE = "#FFFFFF"
BAMBU_PLA_BLACK = "#000000"

DEFAULT_SHELL_COLOR = BAMBU_PLA_BLACK
X1C_BED_SIZE_MM = 256.0
X1C_BED_CENTER = X1C_BED_SIZE_MM / 2.0
BED_MARGIN_MM = 12.0

PICTURE_OBJECT_ID = 2
SHELL_OBJECT_ID = 10
# 外壳部件 ID 必须避开画片 1–4（青品红黄白）。
# 曾用 1/2 时 Bambu Studio 会把 object_1 的画片网格误挂到外壳上，
# 表现为「外壳变成 160×160×1.28 画片」、盘外孤立对象。
SHELL_BODY_PART_ID = 101
SHELL_MODIFIER_PART_ID = 102
SHELL_OBJECTS_REL_PATH = "/3D/Objects/object_2.model"
PICTURE_IDENTIFY_ID = 1001
SHELL_IDENTIFY_ID = 1002
# Bambu 多盘并排时，第 2 盘在世界坐标 X 方向偏移一整张热床宽度
PLATE2_OFFSET_X = 256.0
# 第 2 盘灯箱世界坐标中心 X（与 Bambu Studio 世界坐标一致）
PLATE2_TARGET_CENTER_X = 440.0

PLATE1_NAME = "四色画片建议使用0.08mm层高打印"
PLATE2_NAME = "灯箱建议0.2mm层高打印"
SHELL_TOP_MODIFIER_NAME = "顶壁实心"
# Bambu Studio 的 Z 是物体包围盒中心高度：深度 18 → Z=9 时底面贴盘。
# 导出时 transform.tz = shell_height/2，与 Studio 面板一致。

FILAMENT_SLOTS = (
    {"name": "Cyan", "display": "拓竹青", "hex": BAMBU_PLA_CYAN, "extruder": 1},
    {"name": "Magenta", "display": "拓竹品红", "hex": BAMBU_PLA_MAGENTA, "extruder": 2},
    {"name": "Yellow", "display": "拓竹黄", "hex": BAMBU_PLA_YELLOW, "extruder": 3},
    {"name": "White", "display": "拓竹白", "hex": BAMBU_PLA_JADE_WHITE, "extruder": 4},
    {"name": "Shell", "display": "灯箱外壳", "hex": DEFAULT_SHELL_COLOR, "extruder": 5},
)

BAMBU_MODEL_NS = (
    'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
    'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
    'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" '
    'requiredextensions="p"'
)


def normalize_hex_color(value: str, *, fallback: str = DEFAULT_SHELL_COLOR) -> str:
    text = (value or "").strip()
    if not text:
        return fallback
    if not text.startswith("#"):
        text = f"#{text}"
    body = text[1:]
    if len(body) == 3 and all(ch in "0123456789abcdefABCDEF" for ch in body):
        body = "".join(ch * 2 for ch in body)
    if len(body) != 6 or not all(ch in "0123456789abcdefABCDEF" for ch in body):
        return fallback
    return f"#{body.upper()}"


def hex_to_rgb01(hex_color: str) -> tuple[float, float, float]:
    color = normalize_hex_color(hex_color)
    r = int(color[1:3], 16) / 255.0
    g = int(color[3:5], 16) / 255.0
    b = int(color[5:7], 16) / 255.0
    return r, g, b


def compute_bed_offset(
    art_width_mm: float,
    art_height_mm: float,
    wall_thickness: float,
    *,
    fit_clearance: float = 0.0,
    corner_radius: float = 0.0,
) -> tuple[float, float]:
    """把模型移到 X1C 热床内，避免外壳负坐标越界。"""
    shell_bounds = compute_shell_xy_bounds(
        art_width_mm,
        art_height_mm,
        wall_thickness,
        corner_radius,
        clearance=fit_clearance,
    )
    shell_w = shell_bounds[2] - shell_bounds[0]
    shell_h = shell_bounds[3] - shell_bounds[1]
    min_offset = BED_MARGIN_MM + wall_thickness
    offset_x = max(min_offset, X1C_BED_CENTER - shell_w / 2.0 - shell_bounds[0])
    offset_y = max(min_offset, X1C_BED_CENTER - shell_h / 2.0 - shell_bounds[1])
    return offset_x, offset_y


def _shift_bbox(
    bbox: tuple[float, float, float, float],
    dx: float,
    dy: float,
) -> tuple[float, float, float, float]:
    if bbox == (0.0, 0.0, 0.0, 0.0):
        return bbox
    return (bbox[0] + dx, bbox[1] + dy, bbox[2] + dx, bbox[3] + dy)


def _bambu_uuid(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"fdm-picture-generator:{seed}"))


def _face_count(triangles_xml: str) -> int:
    return triangles_xml.count("<triangle")


def _bbox_from_vertices_xml(vertices_xml: str) -> tuple[float, float, float, float]:
    xs = [float(x) for x in re.findall(r'x="([-\d.]+)"', vertices_xml)]
    ys = [float(y) for y in re.findall(r'y="([-\d.]+)"', vertices_xml)]
    if not xs or not ys:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def _shift_vertices_xml(vertices_xml: str, dx: float, dy: float, dz: float = 0.0) -> str:
    def _repl(match: re.Match[str]) -> str:
        x = float(match.group(1)) + dx
        y = float(match.group(2)) + dy
        z = float(match.group(3)) + dz
        return f'<vertex x="{x:.3f}" y="{y:.3f}" z="{z:.3f}"/>'

    return re.sub(
        r'<vertex x="([-\d.]+)" y="([-\d.]+)" z="([-\d.]+)"/>',
        _repl,
        vertices_xml,
    )


def _bbox_center_xyz(vertices_xml: str) -> tuple[float, float, float]:
    xs = [float(x) for x in re.findall(r'x="([-\d.]+)"', vertices_xml)]
    ys = [float(y) for y in re.findall(r'y="([-\d.]+)"', vertices_xml)]
    zs = [float(z) for z in re.findall(r'z="([-\d.]+)"', vertices_xml)]
    if not xs or not ys or not zs:
        return (0.0, 0.0, 0.0)
    return (
        0.5 * (min(xs) + max(xs)),
        0.5 * (min(ys) + max(ys)),
        0.5 * (min(zs) + max(zs)),
    )


def _vertex_z_extent(vertices_xml: str) -> tuple[float, float]:
    zs = [float(z) for z in re.findall(r'z="([-\d.]+)"', vertices_xml or "")]
    if not zs:
        return (0.0, 0.0)
    return (min(zs), max(zs))


def _shell_height_mm(shell: ShellPart | None) -> float:
    if shell is None or not shell.vertices_xml:
        return 0.0
    z0, z1 = _vertex_z_extent(shell.vertices_xml)
    return max(0.0, z1 - z0)


def _to_shared_shell_origin(shell: ShellPart) -> ShellPart:
    """
    壳体与修改器对齐到同一包围盒中心（含 Z）。
    Studio 面板 Z 与 X/Y 一样是 transform 平移：中心网格 + tz=高度/2 → 底面贴盘（18→Z=9）。
    """
    cx, cy, cz = _bbox_center_xyz(shell.vertices_xml)
    return ShellPart(
        name=shell.name,
        extruder=shell.extruder,
        vertices_xml=_shift_vertices_xml(shell.vertices_xml, -cx, -cy, -cz),
        triangles_xml=shell.triangles_xml,
        modifier_vertices_xml=(
            _shift_vertices_xml(shell.modifier_vertices_xml, -cx, -cy, -cz)
            if shell.modifier_vertices_xml
            else ""
        ),
        modifier_triangles_xml=shell.modifier_triangles_xml,
        modifier_name=shell.modifier_name,
    )


def _bbox_area(bbox: tuple[float, float, float, float]) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _build_plate_json(
    *,
    bbox: tuple[float, float, float, float],
    identify_id: int,
    name: str,
    layer_height: float,
) -> str:
    payload = {
        "bbox_all": list(bbox),
        "bbox_objects": [
            {
                "area": _bbox_area(bbox),
                "bbox": list(bbox),
                "id": identify_id,
                "layer_height": layer_height,
                "name": name,
            }
        ],
        "bed_type": "textured_plate",
        "filament_colors": [],
        "filament_ids": [],
        "first_extruder": 0,
        "is_seq_print": False,
        "nozzle_diameter": 0.4,
        "version": 2,
    }
    return json.dumps(payload, ensure_ascii=False)


SLICE_INFO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
    <header_item key="X-BBL-Client-Version" value="01.10.01.50"/>
  </header>
</config>
"""


def compute_plate2_build_transform(
    shell: ShellPart | None,
) -> tuple[float, float, float]:
    """
    第 2 盘外壳世界坐标（与 Studio 移动面板一致）。
    XY：盘面目标中心；Z：高度/2（深度 18 → Z=9 底面贴盘）。
    """
    if shell is None or not shell.vertices_xml:
        return PLATE2_TARGET_CENTER_X, X1C_BED_CENTER, 0.0
    bbox = _bbox_from_vertices_xml(shell.vertices_xml)
    if bbox == (0.0, 0.0, 0.0, 0.0):
        return PLATE2_TARGET_CENTER_X, X1C_BED_CENTER, 0.0
    cx = (bbox[0] + bbox[2]) / 2.0
    cy = (bbox[1] + bbox[3]) / 2.0
    tx = PLATE2_TARGET_CENTER_X - cx
    ty = X1C_BED_CENTER - cy
    tz = 0.5 * _shell_height_mm(shell)
    return tx, ty, tz


def _identity_matrix() -> str:
    return "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"


def _build_transform(tx: float, ty: float, tz: float = 0.0) -> str:
    return f"1 0 0 0 1 0 0 0 1 {tx:.6f} {ty:.6f} {tz:.6f}"


CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
  <Default Extension="config" ContentType="text/xml"/>
  <Default Extension="json" ContentType="application/json"/>
  <Default Extension="png" ContentType="image/png"/>
</Types>"""

PACKAGE_RELS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0"
    Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>"""

PACKAGE_RELS_WITH_THUMB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0"
    Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
  <Relationship Target="/Metadata/thumbnail.png" Id="rel-thumb"
    Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>
</Relationships>"""


def make_package_thumbnail_png(image_path: str | Path, *, max_edge: int = 512) -> bytes | None:
    """把顾客图压成 3MF 包内缩略图（资源管理器 / Bambu 可显示为图标）。"""
    try:
        import cv2
        import numpy as np
    except Exception:
        return None

    path = Path(image_path)
    if not path.is_file():
        return None
    # Windows 中文路径：cv2.imread 常失败，改用 fromfile + imdecode
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    except Exception:
        img = None
    if img is None:
        img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.ndim == 2:
        bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] == 4:
        bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    else:
        bgr = img
    h, w = bgr.shape[:2]
    edge = max(h, w)
    if edge > max_edge:
        scale = max_edge / float(edge)
        bgr = cv2.resize(
            bgr,
            (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    # 白底画板，便于资源管理器预览
    ph, pw = bgr.shape[:2]
    side = max(ph, pw)
    canvas = np.full((side, side, 3), 245, dtype=np.uint8)
    y0 = (side - ph) // 2
    x0 = (side - pw) // 2
    canvas[y0 : y0 + ph, x0 : x0 + pw] = bgr
    ok, buf = cv2.imencode(".png", canvas, [int(cv2.IMWRITE_PNG_COMPRESSION), 3])
    if not ok:
        return None
    return bytes(buf)


@dataclass(frozen=True)
class MeshPart:
    """四色图层网格（assembly 内的一个 part）。"""

    part_id: int
    name: str
    extruder: int
    vertices_xml: str
    triangles_xml: str


@dataclass(frozen=True)
class ShellPart:
    """灯箱外壳网格；可选顶壁 modifier_part（100% 填充）。"""

    name: str
    extruder: int
    vertices_xml: str
    triangles_xml: str
    modifier_vertices_xml: str = ""
    modifier_triangles_xml: str = ""
    modifier_name: str = SHELL_TOP_MODIFIER_NAME

    @property
    def has_modifier(self) -> bool:
        return bool(self.modifier_vertices_xml and self.modifier_triangles_xml)


def _object_file_model(objects_xml: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<model unit="millimeter" xml:lang="en-US" {BAMBU_MODEL_NS}>\n'
        ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
        " <resources>\n"
        f"{objects_xml}\n"
        " </resources>\n"
        "</model>\n"
    )


def _mesh_object_xml(object_id: int, name: str, vertices_xml: str, triangles_xml: str) -> str:
    obj_uuid = _bambu_uuid(f"object-mesh:{object_id}:{name}")
    return (
        f'  <object id="{object_id}" p:UUID="{obj_uuid}" type="model" name="{escape(name)}">\n'
        f"   <mesh><vertices>{vertices_xml}</vertices>"
        f"<triangles>{triangles_xml}</triangles></mesh>\n"
        "  </object>"
    )


def _build_main_model(
    color_layers: list[MeshPart],
    shell: ShellPart | None,
    offset_x: float,
    offset_y: float,
    *,
    plate2_tx: float = PLATE2_OFFSET_X,
    plate2_ty: float = 0.0,
    plate2_tz: float = 0.0,
) -> tuple[str, str]:
    picture_uuid = _bambu_uuid("picture-assembly")
    component_lines = []
    for layer in color_layers:
        comp_uuid = _bambu_uuid(f"component:{layer.part_id}")
        component_lines.append(
            '    <component p:path="/3D/Objects/object_1.model" '
            f'objectid="{layer.part_id}" p:UUID="{comp_uuid}" '
            'transform="1 0 0 0 1 0 0 0 1 0 0 0"/>'
        )

    picture_object = (
        f'  <object id="{PICTURE_OBJECT_ID}" p:UUID="{picture_uuid}" type="model">\n'
        "   <components>\n"
        + "\n".join(component_lines)
        + "\n   </components>\n"
        "  </object>"
    )

    resources = [picture_object]
    build_items = [
        f'  <item objectid="{PICTURE_OBJECT_ID}" p:UUID="{_bambu_uuid("build-picture")}" '
        f'transform="{_build_transform(0, 0)}" printable="1"/>'
    ]

    if shell and shell.vertices_xml:
        shell_uuid = _bambu_uuid("shell-object")
        if shell.has_modifier:
            shell_comp_lines = [
                f'    <component p:path="{SHELL_OBJECTS_REL_PATH}" '
                f'objectid="{SHELL_BODY_PART_ID}" p:UUID="{_bambu_uuid("shell-comp-body")}" '
                'transform="1 0 0 0 1 0 0 0 1 0 0 0"/>',
                f'    <component p:path="{SHELL_OBJECTS_REL_PATH}" '
                f'objectid="{SHELL_MODIFIER_PART_ID}" p:UUID="{_bambu_uuid("shell-comp-mod")}" '
                'transform="1 0 0 0 1 0 0 0 1 0 0 0"/>',
            ]
            resources.append(
                f'  <object id="{SHELL_OBJECT_ID}" p:UUID="{shell_uuid}" type="model" '
                f'name="{escape(shell.name)}">\n'
                "   <components>\n"
                + "\n".join(shell_comp_lines)
                + "\n   </components>\n"
                "  </object>"
            )
        else:
            resources.append(
                f'  <object id="{SHELL_OBJECT_ID}" p:UUID="{shell_uuid}" type="model" '
                f'name="{escape(shell.name)}">\n'
                f"   <mesh><vertices>{shell.vertices_xml}</vertices>"
                f"<triangles>{shell.triangles_xml}</triangles></mesh>\n"
                "  </object>"
            )
        build_items.append(
            f'  <item objectid="{SHELL_OBJECT_ID}" p:UUID="{_bambu_uuid("build-shell")}" '
            f'transform="{_build_transform(plate2_tx, plate2_ty, plate2_tz)}" printable="1"/>'
        )

    model_rels_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
        ' <Relationship Target="/3D/Objects/object_1.model" Id="rel-1" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>',
    ]
    if shell and shell.vertices_xml and shell.has_modifier:
        model_rels_lines.append(
            ' <Relationship Target="/3D/Objects/object_2.model" Id="rel-2" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        )
    model_rels_lines.append("</Relationships>")
    model_rels = "\n".join(model_rels_lines)

    main_model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<model unit="millimeter" xml:lang="en-US" {BAMBU_MODEL_NS}>\n'
        ' <metadata name="Application">BambuStudio-01.10.01.50</metadata>\n'
        ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
        " <resources>\n"
        + "\n".join(resources)
        + "\n </resources>\n"
        f' <build p:UUID="{_bambu_uuid("build-root")}">\n'
        + "\n".join(build_items)
        + "\n </build>\n"
        "</model>\n"
    )
    return main_model, model_rels


def _build_project_settings(shell_color_hex: str, *, with_shell: bool) -> str:
    slot_count = 5 if with_shell else 4
    colours = [slot["hex"] for slot in FILAMENT_SLOTS[:4]]
    if with_shell:
        colours.append(normalize_hex_color(shell_color_hex))

    profile = "Bambu PLA Basic @BBL X1C"
    settings = {
        "from": "fdm_picture_generator",
        "name": "FDM图片画",
        "version": "1.0.0",
        "printer_model": "Bambu Lab X1 Carbon",
        "printer_variant": "0.4",
        "printer_settings_id": "Bambu Lab X1 Carbon 0.4 nozzle",
        "print_settings_id": "0.08mm Extra Fine @BBL X1C",
        "default_print_profile": "0.08mm Extra Fine @BBL X1C",
        "default_filament_profile": [profile],
        "printable_area": ["0x0", "256x256", "0x256", "256x256", "256x256", "0x256", "256x0", "0x0"],
        "bed_shape": ["0x0", "256x256", "0x256", "256x256", "256x256", "0x256", "256x0", "0x0"],
        "bed_type": "textured_plate",
        "nozzle_diameter": ["0.4"],
        "layer_height": "0.08",
        "initial_layer_height": "0.2",
        "filament_type": ["PLA"] * slot_count,
        "filament_colour": colours,
        "filament_vendor": ["Bambu Lab"] * slot_count,
        "filament_ids": ["GFA00"] * slot_count,
        "filament_settings_id": [profile] * slot_count,
        "filament_diameter": ["1.75"] * slot_count,
        "filament_density": ["1.24"] * slot_count,
        "sparse_infill_density": "100%",
        "enable_support": "0",
        # 四色换料需要擦料塔；默认 Y≈220 易超出 256 盘边，固定到盘内靠后角
        "enable_prime_tower": "1",
        "prime_tower_width": "35",
        "prime_tower_brim_width": "3",
        "wipe_tower_rotation_angle": "0",
        # 每盘一组；左前角为原点，取值偏后侧并留边距，避免悬出盘外
        "wipe_tower_x": ["15", "15"] if with_shell else ["15"],
        "wipe_tower_y": ["200", "200"] if with_shell else ["200"],
        "single_extruder_multi_material": "1",
        "filament_map_mode": "Auto For Flush",
        "filament_map": ["1"] * slot_count,
        "flush_into_objects": "0",
        "flush_into_infill": "0",
        "flush_into_support": "0",
    }
    return json.dumps(settings, ensure_ascii=False, indent=2)


def _mesh_stat_xml(triangles_xml: str) -> str:
    faces = _face_count(triangles_xml)
    return (
        f'<mesh_stat face_count="{faces}" edges_fixed="0" degenerate_facets="0" '
        'facets_removed="0" facets_reversed="0" backwards_edges="0"/>'
    )


def _build_model_settings(
    color_layers: list[MeshPart],
    shell: ShellPart | None,
    *,
    picture_name: str,
    offset_x: float,
    offset_y: float,
    plate2_tx: float = PLATE2_OFFSET_X,
    plate2_ty: float = 0.0,
    plate2_tz: float = 0.0,
) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>"]

    total_faces = sum(_face_count(layer.triangles_xml) for layer in color_layers)
    lines.append(f'  <object id="{PICTURE_OBJECT_ID}">')
    lines.append(f'    <metadata key="name" value="{escape(picture_name)}"/>')
    lines.append('    <metadata key="extruder" value="1"/>')
    lines.append(f'    <metadata face_count="{total_faces}"/>')
    for layer in color_layers:
        lines.append(f'    <part id="{layer.part_id}" subtype="normal_part">')
        lines.append(f'      <metadata key="name" value="{escape(layer.name)}"/>')
        lines.append(f'      <metadata key="matrix" value="{_identity_matrix()}"/>')
        lines.append(f'      <metadata key="source_offset_x" value="{offset_x:.6f}"/>')
        lines.append(f'      <metadata key="source_offset_y" value="{offset_y:.6f}"/>')
        lines.append(f'      <metadata key="extruder" value="{layer.extruder}"/>')
        lines.append(f"      {_mesh_stat_xml(layer.triangles_xml)}")
        lines.append("    </part>")
    lines.append("  </object>")

    has_shell = shell is not None and bool(shell.vertices_xml)
    if has_shell and shell is not None:
        shell_faces = _face_count(shell.triangles_xml)
        mod_faces = (
            _face_count(shell.modifier_triangles_xml) if shell.has_modifier else 0
        )
        lines.append(f'  <object id="{SHELL_OBJECT_ID}">')
        lines.append(f'    <metadata key="name" value="{escape(shell.name)}"/>')
        lines.append(f'    <metadata key="extruder" value="{shell.extruder}"/>')
        lines.append(f'    <metadata face_count="{shell_faces + mod_faces}"/>')
        lines.append(f'    <part id="{SHELL_BODY_PART_ID}" subtype="normal_part">')
        lines.append(f'      <metadata key="name" value="{escape(shell.name)}"/>')
        lines.append(f'      <metadata key="matrix" value="{_identity_matrix()}"/>')
        lines.append('      <metadata key="source_offset_x" value="0"/>')
        lines.append('      <metadata key="source_offset_y" value="0"/>')
        lines.append('      <metadata key="source_offset_z" value="0"/>')
        lines.append(f'      <metadata key="extruder" value="{shell.extruder}"/>')
        lines.append(f"      {_mesh_stat_xml(shell.triangles_xml)}")
        lines.append("    </part>")
        if shell.has_modifier:
            lines.append(
                f'    <part id="{SHELL_MODIFIER_PART_ID}" subtype="modifier_part">'
            )
            lines.append(
                f'      <metadata key="name" value="{escape(shell.modifier_name)}"/>'
            )
            lines.append(f'      <metadata key="matrix" value="{_identity_matrix()}"/>')
            lines.append('      <metadata key="source_offset_x" value="0"/>')
            lines.append('      <metadata key="source_offset_y" value="0"/>')
            lines.append('      <metadata key="source_offset_z" value="0"/>')
            lines.append('      <metadata key="sparse_infill_density" value="100%"/>')
            lines.append(f"      {_mesh_stat_xml(shell.modifier_triangles_xml)}")
            lines.append("    </part>")
        lines.append("  </object>")

    lines.extend(
        [
            "  <plate>",
            '    <metadata key="plater_id" value="1"/>',
            f'    <metadata key="plater_name" value="{escape(PLATE1_NAME)}"/>',
            '    <metadata key="locked" value="true"/>',
            '    <metadata key="filament_map_mode" value="Auto For Flush"/>',
            '    <metadata key="print_settings_id" value="0.08mm Extra Fine @BBL X1C"/>',
            '    <metadata key="printer_settings_id" value="Bambu Lab X1 Carbon 0.4 nozzle"/>',
            '    <metadata key="nozzle_diameters" value="0.4"/>',
            "    <model_instance>",
            f'      <metadata key="object_id" value="{PICTURE_OBJECT_ID}"/>',
            '      <metadata key="instance_id" value="0"/>',
            f'      <metadata key="identify_id" value="{PICTURE_IDENTIFY_ID}"/>',
            "    </model_instance>",
            "  </plate>",
        ]
    )

    if has_shell:
        lines.extend(
            [
                "  <plate>",
                '    <metadata key="plater_id" value="2"/>',
                f'    <metadata key="plater_name" value="{escape(PLATE2_NAME)}"/>',
                '    <metadata key="locked" value="true"/>',
                '    <metadata key="filament_map_mode" value="Auto For Flush"/>',
                '    <metadata key="print_settings_id" value="0.2mm Standard @BBL X1C"/>',
                '    <metadata key="printer_settings_id" value="Bambu Lab X1 Carbon 0.4 nozzle"/>',
                '    <metadata key="nozzle_diameters" value="0.4"/>',
                "    <model_instance>",
                f'      <metadata key="object_id" value="{SHELL_OBJECT_ID}"/>',
                '      <metadata key="instance_id" value="0"/>',
                f'      <metadata key="identify_id" value="{SHELL_IDENTIFY_ID}"/>',
                "    </model_instance>",
                "  </plate>",
            ]
        )

    lines.append("  <assemble>")
    lines.append(
        f'   <assemble_item object_id="{PICTURE_OBJECT_ID}" instance_id="0" '
        f'transform="{_build_transform(0, 0)}" offset="0 0 0" />'
    )
    if has_shell:
        lines.append(
            f'   <assemble_item object_id="{SHELL_OBJECT_ID}" instance_id="0" '
            f'transform="{_build_transform(plate2_tx, plate2_ty, plate2_tz)}" offset="0 0 0" />'
        )
    lines.append("  </assemble>")
    lines.append("</config>")
    return "\n".join(lines)


def save_bambu_project_3mf(
    output_path: str,
    color_layers: list[MeshPart],
    shell: ShellPart | None = None,
    *,
    picture_name: str = "FDM图片画",
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    shell_color_hex: str = DEFAULT_SHELL_COLOR,
    thumbnail_png: bytes | None = None,
) -> None:
    active_layers = [layer for layer in color_layers if layer.vertices_xml]
    if not active_layers:
        raise ValueError("没有可导出的四色网格")

    has_shell = shell is not None and bool(shell.vertices_xml)
    # 网格中心归零 + transform.Z=高度/2（与 Studio 面板图二一致：18→Z=9）
    if has_shell and shell is not None:
        shell = _to_shared_shell_origin(shell)
    plate2_tx, plate2_ty, plate2_tz = compute_plate2_build_transform(
        shell if has_shell else None
    )
    main_model, model_rels = _build_main_model(
        active_layers,
        shell,
        offset_x,
        offset_y,
        plate2_tx=plate2_tx,
        plate2_ty=plate2_ty,
        plate2_tz=plate2_tz,
    )

    color_objects = "\n".join(
        _mesh_object_xml(layer.part_id, layer.name, layer.vertices_xml, layer.triangles_xml)
        for layer in active_layers
    )
    object_1_model = _object_file_model(color_objects)

    picture_bbox = (0.0, 0.0, 0.0, 0.0)
    for layer in active_layers:
        layer_bbox = _bbox_from_vertices_xml(layer.vertices_xml)
        if layer_bbox == (0.0, 0.0, 0.0, 0.0):
            continue
        if picture_bbox == (0.0, 0.0, 0.0, 0.0):
            picture_bbox = layer_bbox
        else:
            picture_bbox = (
                min(picture_bbox[0], layer_bbox[0]),
                min(picture_bbox[1], layer_bbox[1]),
                max(picture_bbox[2], layer_bbox[2]),
                max(picture_bbox[3], layer_bbox[3]),
            )

    shell_bbox = (
        _bbox_from_vertices_xml(shell.vertices_xml)
        if has_shell and shell is not None
        else (0.0, 0.0, 0.0, 0.0)
    )

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        archive.writestr(
            "_rels/.rels",
            PACKAGE_RELS_WITH_THUMB_XML if thumbnail_png else PACKAGE_RELS_XML,
        )
        archive.writestr("3D/3dmodel.model", main_model)
        archive.writestr("3D/_rels/3dmodel.model.rels", model_rels)
        archive.writestr("3D/Objects/object_1.model", object_1_model)
        if has_shell and shell is not None and shell.has_modifier:
            shell_objects = "\n".join(
                [
                    _mesh_object_xml(
                        SHELL_BODY_PART_ID,
                        shell.name,
                        shell.vertices_xml,
                        shell.triangles_xml,
                    ),
                    _mesh_object_xml(
                        SHELL_MODIFIER_PART_ID,
                        shell.modifier_name,
                        shell.modifier_vertices_xml,
                        shell.modifier_triangles_xml,
                    ),
                ]
            )
            archive.writestr(
                "3D/Objects/object_2.model",
                _object_file_model(shell_objects),
            )
        if thumbnail_png:
            # Windows 资源管理器图标 + Bambu 盘预览
            archive.writestr("Metadata/thumbnail.png", thumbnail_png)
            archive.writestr("Metadata/plate_1.png", thumbnail_png)
        archive.writestr(
            "Metadata/project_settings.config",
            _build_project_settings(shell_color_hex, with_shell=has_shell),
        )
        archive.writestr(
            "Metadata/model_settings.config",
            _build_model_settings(
                active_layers,
                shell,
                picture_name=picture_name,
                offset_x=offset_x,
                offset_y=offset_y,
                plate2_tx=plate2_tx,
                plate2_ty=plate2_ty,
                plate2_tz=plate2_tz,
            ),
        )
        archive.writestr("Metadata/slice_info.config", SLICE_INFO_XML)
        archive.writestr(
            "Metadata/filament_sequence.json",
            json.dumps(
                {
                    "plate_1": {
                        "nozzle_sequence": [],
                        "optimal_assignment": [],
                        "sequence": [],
                    },
                    **(
                        {
                            "plate_2": {
                                "nozzle_sequence": [],
                                "optimal_assignment": [],
                                "sequence": [],
                            }
                        }
                        if has_shell
                        else {}
                    ),
                },
                ensure_ascii=False,
            ),
        )
        if picture_bbox != (0.0, 0.0, 0.0, 0.0):
            archive.writestr(
                "Metadata/plate_1.json",
                _build_plate_json(
                    bbox=picture_bbox,
                    identify_id=PICTURE_IDENTIFY_ID,
                    name=picture_name,
                    layer_height=0.08,
                ),
            )
        if has_shell and shell_bbox != (0.0, 0.0, 0.0, 0.0):
            plate2_bbox = _shift_bbox(shell_bbox, plate2_tx, plate2_ty)
            archive.writestr(
                "Metadata/plate_2.json",
                _build_plate_json(
                    bbox=plate2_bbox,
                    identify_id=SHELL_IDENTIFY_ID,
                    name=shell.name if shell else "Lightbox_Shell",
                    layer_height=0.2,
                ),
            )
