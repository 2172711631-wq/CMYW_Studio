"""3MF 导出：给切片器的摆盘文件。

抽出来放这儿是因为每个产品线（画框、吧唧、以后的立牌色纸）都要摆盘，
而这两件事一旦各写一份就会各错一份：

  · **顶点要焊。** OCC 是按面分别三角化的，相邻两面在公共棱上各生成一份顶点，
    坐标一样、索引不同。STL 是三角形汤没有索引，切片器读进去自己会焊，所以看不出来；
    3MF 带索引，不焊就是几百条"开放边"，Bambu Studio 会报破面。
  · **坐标就是床坐标。** 零件还以模型原点为中心的话，一半会落在床外，直接报超出范围。
"""

from __future__ import annotations

import zipfile

import cadquery as cq

# X1C 热床
BED = 256.0

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" '
    'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="model" '
    'ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
    '<Default Extension="config" ContentType="application/vnd.bambulab.config"/>'
    "</Types>"
)

_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rel0" Target="/3D/3dmodel.model" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'
)


def mesh_of(shape: cq.Workplane, tol: float = 0.05, ang: float = 0.2):
    """三角化，并按坐标（1e-6）把重合顶点焊到一起，顺手丢掉塌掉的退化三角形。"""
    raw_v, raw_t = shape.val().tessellate(tol, ang)
    index: dict[tuple[int, int, int], int] = {}
    verts: list[tuple[float, float, float]] = []
    remap: list[int] = []
    for v in raw_v:
        key = (round(v.x * 1e6), round(v.y * 1e6), round(v.z * 1e6))
        i = index.get(key)
        if i is None:
            i = len(verts)
            index[key] = i
            verts.append((v.x, v.y, v.z))
        remap.append(i)
    tris = []
    for a, b, c in raw_t:
        ta, tb, tc = remap[a], remap[b], remap[c]
        if ta != tb and tb != tc and ta != tc:
            tris.append((ta, tb, tc))
    return verts, tris


def place(shape: cq.Workplane, x: float, y: float, rot: float = 0.0) -> cq.Workplane:
    """把零件按 XY 包围盒中心摆到 (x, y)，可先绕 Z 转 rot 度。"""
    if abs(rot) > 1e-9:
        shape = shape.rotate((0, 0, 0), (0, 0, 1), rot)
    bb = shape.val().BoundingBox()
    return shape.translate(
        (x - (bb.xmin + bb.xmax) / 2.0, y - (bb.ymin + bb.ymax) / 2.0, 0.0)
    )


def pack_plates(
    parts: list[tuple[str, cq.Workplane]],
    *,
    bed: float = 247.0,   # 256 的热床，四边各留 4.5 留给裙边和边缘吸附
    gap: float = 3.0,     # 件与件之间；再小切片器会把它们当一坨算裙边
) -> list[list[tuple[str, cq.Workplane]]]:
    """货架式排盘：能挤进一盘就一盘，挤不下才开第二盘。

    以前是按颜色写死分两盘的，但那不是零件的属性 —— 一套小尺寸的壳四件本来就
    放得下一盘，硬拆成两盘等于让人多换一次料、多等一次开机。所以改成实际去排，
    排得下就是一盘。

    高的先放，一行一行往上摞（shelf packing）。够用了：这些零件都是矩形薄片，
    而且一盘上也就三五件，没必要上真正的装箱算法。
    """
    sized = []
    for name, shape in parts:
        bb = shape.val().BoundingBox()
        sized.append((bb.xlen, bb.ylen, name, shape))
    sized.sort(key=lambda t: -t[1])

    plates: list[list[tuple[str, cq.Workplane]]] = []
    cur: list[tuple[str, cq.Workplane]] = []
    x = y = row_h = 0.0
    for w, h, name, shape in sized:
        if x > 0 and x + w > bed:          # 这一行放不下了，换行
            y += row_h + gap
            x = 0.0
            row_h = 0.0
        if y + h > bed and cur:            # 这一盘也放不下了，换盘
            plates.append(cur)
            cur = []
            x = y = row_h = 0.0
        cur.append((name, place(shape, x + w / 2.0 - bed / 2.0, bed / 2.0 - (y + h / 2.0))))
        x += w + gap
        row_h = max(row_h, h)
    if cur:
        plates.append(cur)
    return plates


def write_3mf(
    path: str, parts: list[tuple[str, cq.Workplane]], *, tol: float = 0.05, ang: float = 0.2
) -> str:
    """单盘 3MF：每个零件一个 object、一个 build item，切片器里各自可动。"""
    objs, items = [], []
    for i, (name, shape) in enumerate(parts, start=1):
        verts, tris = mesh_of(shape, tol, ang)
        verts = [(x + BED / 2.0, y + BED / 2.0, z) for x, y, z in verts]
        vx = "".join(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in verts)
        tx = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris)
        objs.append(
            f'<object id="{i}" name="{name}" type="model">'
            f"<mesh><vertices>{vx}</vertices><triangles>{tx}</triangles></mesh></object>"
        )
        items.append(f'<item objectid="{i}"/>')
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        f'<resources>{"".join(objs)}</resources>'
        f'<build>{"".join(items)}</build></model>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("3D/3dmodel.model", model)
    return path


def write_bambu_3mf(
    path: str,
    plates: list[tuple[str, list[tuple[str, cq.Workplane]]]],
    *,
    tol: float = 0.05,
    ang: float = 0.2,
) -> str:
    """多盘 Bambu 项目：一个文件，里面若干个盘。

    盘是靠 Metadata/model_settings.config 里的 <plate> 块把 model_instance 绑到
    plater_id 上的；3dmodel.model 里再把第二盘整体挪到 x=440 那一列
    （沿用 bambu_export.py 里已经验证过的摆位）。
    """
    nl = chr(10)
    plate_centers = [(BED / 2.0, BED / 2.0), (440.0, BED / 2.0)]
    objs: list[str] = []
    items: list[str] = []
    cfg: list[str] = []
    plate_blocks: list[str] = []
    oid = 0
    for pi, (plate_name, parts) in enumerate(plates):
        cx, cy = plate_centers[min(pi, len(plate_centers) - 1)]
        inst: list[str] = []
        for name, shape in parts:
            oid += 1
            verts, tris = mesh_of(shape, tol, ang)
            xs = [v[0] for v in verts]
            ys = [v[1] for v in verts]
            ox = (min(xs) + max(xs)) / 2.0
            oy = (min(ys) + max(ys)) / 2.0
            vx = "".join(
                f'<vertex x="{x - ox:.4f}" y="{y - oy:.4f}" z="{z:.4f}"/>'
                for x, y, z in verts
            )
            tx = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris)
            objs.append(
                f'<object id="{oid}" name="{name}" type="model">'
                f"<mesh><vertices>{vx}</vertices><triangles>{tx}</triangles></mesh></object>"
            )
            items.append(
                f'<item objectid="{oid}" transform="1 0 0 0 1 0 0 0 1 '
                f'{cx + ox:.4f} {cy + oy:.4f} 0"/>'
            )
            cfg.extend(
                [
                    f'  <object id="{oid}">',
                    f'    <metadata key="name" value="{name}"/>',
                    '    <metadata key="extruder" value="1"/>',
                    f'    <part id="{oid}" subtype="normal_part">',
                    f'      <metadata key="name" value="{name}"/>',
                    '      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>',
                    "    </part>",
                    "  </object>",
                ]
            )
            inst.extend(
                [
                    "    <model_instance>",
                    f'      <metadata key="object_id" value="{oid}"/>',
                    '      <metadata key="instance_id" value="0"/>',
                    "    </model_instance>",
                ]
            )
        plate_blocks.extend(
            [
                "  <plate>",
                f'    <metadata key="plater_id" value="{pi + 1}"/>',
                f'    <metadata key="plater_name" value="{plate_name}"/>',
                *inst,
                "  </plate>",
            ]
        )

    model = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        f'<resources>{"".join(objs)}</resources>'
        f'<build>{"".join(items)}</build></model>'
    )
    settings = nl.join(
        ['<?xml version="1.0" encoding="UTF-8"?>', "<config>", *cfg, *plate_blocks, "</config>", ""]
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/model_settings.config", settings)
    return path
