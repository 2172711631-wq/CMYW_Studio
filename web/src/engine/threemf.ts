/**
 * Bambu Studio 工程 3MF 组装。
 * Bambu Studio project 3MF assembly — ported from bambu_export.py.
 *
 * 产出的不是裸模型，而是一个可以直接切片的工程：
 *   · 两个盘：画片 0.08mm，外壳 0.2mm
 *   · AMS 槽位预分配：1–4 = 青/品红/黄/白，5 = 外壳色
 *   · 擦料塔固定在盘内靠后角（默认位置会飘出 256mm 盘外）
 *   · 顶壁实心 modifier，让触摸面打得密实
 *   · 顾客原图作为包缩略图
 */

import { DEFAULT_SHELL_HEX, FILAMENT_HEX, LAYER_HEIGHT } from "./constants";
import type { Mesh } from "./shell";
import type { VoxelRect } from "./voxel";
import { createZip, type ZipEntry } from "./zip";

const X1C_BED = 256.0;
const BED_CENTER = X1C_BED / 2;
const BED_MARGIN = 12.0;

const PICTURE_OBJECT_ID = 2;
const SHELL_OBJECT_ID = 10;
// 外壳部件 ID 必须避开画片的 1–4。用 1/2 时 Bambu Studio 会把画片网格
// 误挂到外壳上，表现为「外壳变成一张薄画片」。
const SHELL_BODY_PART_ID = 101;
const SHELL_MODIFIER_PART_ID = 102;
const PICTURE_IDENTIFY_ID = 1001;
const SHELL_IDENTIFY_ID = 1002;
const PLATE2_TARGET_CENTER_X = 440.0;

const PLATE1_NAME = "四色画片建议使用0.08mm层高打印";
const PLATE2_NAME = "灯箱建议0.2mm层高打印";
const SHELL_TOP_MODIFIER_NAME = "顶壁实心";

const MODEL_NS =
  'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" ' +
  'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" ' +
  'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" ' +
  'requiredextensions="p"';

/** 立方体 8 顶点的 12 个三角形，绕序与 Python 的 BOX_TRIANGLES 一致。 */
const BOX_TRIANGLES: ReadonlyArray<readonly [number, number, number]> = [
  [0, 1, 2], [0, 2, 3], [4, 6, 5], [4, 7, 6],
  [0, 4, 5], [0, 5, 1], [1, 5, 6], [1, 6, 2],
  [2, 6, 7], [2, 7, 3], [3, 7, 4], [3, 4, 0],
];

function escapeXml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

const UUID_NAMESPACE_URL = "6ba7b811-9dad-11d1-80b4-00c04fd430c8";

function uuidToBytes(uuid: string): Uint8Array {
  const hex = uuid.replace(/-/g, "");
  const out = new Uint8Array(16);
  for (let i = 0; i < 16; i += 1) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

/** UUID v5（SHA-1），与 Python 的 uuid.uuid5(NAMESPACE_URL, …) 结果一致。 */
async function uuid5(name: string): Promise<string> {
  const ns = uuidToBytes(UUID_NAMESPACE_URL);
  const nameBytes = new TextEncoder().encode(name);
  const buf = new Uint8Array(ns.length + nameBytes.length);
  buf.set(ns, 0);
  buf.set(nameBytes, ns.length);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-1", buf));
  const b = digest.slice(0, 16);
  b[6] = (b[6] & 0x0f) | 0x50; // 版本 5
  b[8] = (b[8] & 0x3f) | 0x80; // 变体
  const hex = Array.from(b, (v) => v.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

const seedUuid = (seed: string) => uuid5(`fdm-picture-generator:${seed}`);

export interface ColorPlateInput {
  partId: number;
  name: string;
  extruder: number;
  rects: VoxelRect[];
}

export interface Build3mfOptions {
  /** 四个颜色件，按 C/M/Y/W 顺序 */
  layers: ColorPlateInput[];
  gridH: number;
  /** 每个网格像素的实际边长 mm */
  pixelSize: number;
  /** 画片实际宽高 mm */
  artWidthMm: number;
  artHeightMm: number;
  /** 外壳网格与顶壁 modifier；不要外壳时传 null */
  shell: { body: Mesh; modifier: Mesh; wall: number; topThickness: number; clearance: number } | null;
  shellColorHex?: string;
  pictureName?: string;
  /** 包内缩略图（PNG 字节），资源管理器与 Bambu 会显示 */
  thumbnailPng?: Uint8Array | null;
}

/** 摆盘偏移：把模型挪进热床，避免外壳出现负坐标。 */
function computeBedOffset(
  artW: number,
  artH: number,
  wall: number,
  topThickness: number,
  clearance: number,
): { offsetX: number; offsetY: number } {
  const minX = clearance - wall;
  const minY = clearance - wall;
  const shellW = clearance + artW + wall - minX;
  const shellH = clearance + artH + topThickness - minY;
  const minOffset = BED_MARGIN + wall;
  return {
    offsetX: Math.max(minOffset, BED_CENTER - shellW / 2 - minX),
    offsetY: Math.max(minOffset, BED_CENTER - shellH / 2 - minY),
  };
}

interface XmlMesh {
  vertices: string;
  triangles: string;
  faceCount: number;
  bbox: [number, number, number, number] | null;
}

/** 合并矩形 → 立方体网格的 3MF XML。 */
function rectsToXml(
  rects: VoxelRect[],
  gridH: number,
  pixelSize: number,
  offsetX: number,
  offsetY: number,
): XmlMesh {
  if (rects.length === 0) {
    return { vertices: "", triangles: "", faceCount: 0, bbox: null };
  }

  const verts: string[] = [];
  const tris: string[] = [];
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

  for (let i = 0; i < rects.length; i += 1) {
    const r = rects[i];
    const x0 = r.x0 * pixelSize + offsetX;
    const x1 = r.x1 * pixelSize + offsetX;
    // 图像行序与实体 Y 轴相反，这里翻过来
    const y0 = (gridH - r.y1) * pixelSize + offsetY;
    const y1 = (gridH - r.y0) * pixelSize + offsetY;
    const { z0, z1 } = r;

    minX = Math.min(minX, x0); maxX = Math.max(maxX, x1);
    minY = Math.min(minY, y0); maxY = Math.max(maxY, y1);

    const corners: Array<[number, number, number]> = [
      [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
      [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1],
    ];
    for (const [x, y, z] of corners) {
      verts.push(`<vertex x="${x.toFixed(3)}" y="${y.toFixed(3)}" z="${z.toFixed(3)}"/>`);
    }
    const base = i * 8;
    for (const [a, b, c] of BOX_TRIANGLES) {
      tris.push(`<triangle v1="${base + a}" v2="${base + b}" v3="${base + c}"/>`);
    }
  }

  return {
    vertices: verts.join(""),
    triangles: tris.join(""),
    faceCount: rects.length * BOX_TRIANGLES.length,
    bbox: [minX, minY, maxX, maxY],
  };
}

/** 任意三角网格 → 3MF XML，可整体平移。 */
function meshToXml(mesh: Mesh, dx = 0, dy = 0, dz = 0): XmlMesh {
  const v = mesh.vertices;
  if (v.length === 0) return { vertices: "", triangles: "", faceCount: 0, bbox: null };

  const verts: string[] = [];
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (let i = 0; i < v.length; i += 3) {
    const x = v[i] + dx;
    const y = v[i + 1] + dy;
    const z = v[i + 2] + dz;
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    verts.push(`<vertex x="${x.toFixed(3)}" y="${y.toFixed(3)}" z="${z.toFixed(3)}"/>`);
  }
  const tris: string[] = [];
  for (let i = 0; i < mesh.indices.length; i += 3) {
    tris.push(
      `<triangle v1="${mesh.indices[i]}" v2="${mesh.indices[i + 1]}" v3="${mesh.indices[i + 2]}"/>`,
    );
  }
  return {
    vertices: verts.join(""),
    triangles: tris.join(""),
    faceCount: mesh.indices.length / 3,
    bbox: [minX, minY, maxX, maxY],
  };
}

function meshBoundsZ(mesh: Mesh): { min: number; max: number } {
  let min = Infinity;
  let max = -Infinity;
  for (let i = 2; i < mesh.vertices.length; i += 3) {
    min = Math.min(min, mesh.vertices[i]);
    max = Math.max(max, mesh.vertices[i]);
  }
  return { min, max };
}

function meshCenterXY(mesh: Mesh): { cx: number; cy: number } {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (let i = 0; i < mesh.vertices.length; i += 3) {
    minX = Math.min(minX, mesh.vertices[i]); maxX = Math.max(maxX, mesh.vertices[i]);
    minY = Math.min(minY, mesh.vertices[i + 1]); maxY = Math.max(maxY, mesh.vertices[i + 1]);
  }
  return { cx: (minX + maxX) / 2, cy: (minY + maxY) / 2 };
}

const CONTENT_TYPES = `<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
  <Default Extension="config" ContentType="text/xml"/>
  <Default Extension="json" ContentType="application/json"/>
  <Default Extension="png" ContentType="image/png"/>
</Types>`;

const SLICE_INFO = `<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
    <header_item key="X-BBL-Client-Version" value="01.10.01.50"/>
  </header>
</config>
`;

function packageRels(withThumb: boolean): string {
  const thumb = withThumb
    ? '\n  <Relationship Target="/Metadata/thumbnail.png" Id="rel-thumb" ' +
      'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>'
    : "";
  return `<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0"
    Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>${thumb}
</Relationships>`;
}

function objectFileModel(objectsXml: string): string {
  return `<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" ${MODEL_NS}>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <resources>
${objectsXml}
 </resources>
</model>
`;
}

async function meshObjectXml(id: number, name: string, m: XmlMesh): Promise<string> {
  const u = await seedUuid(`object-mesh:${id}:${name}`);
  return (
    `  <object id="${id}" p:UUID="${u}" type="model" name="${escapeXml(name)}">\n` +
    `   <mesh><vertices>${m.vertices}</vertices><triangles>${m.triangles}</triangles></mesh>\n` +
    `  </object>`
  );
}

function projectSettings(shellHex: string, withShell: boolean): string {
  const slots = withShell ? 5 : 4;
  const colours: string[] = [FILAMENT_HEX.C, FILAMENT_HEX.M, FILAMENT_HEX.Y, FILAMENT_HEX.W];
  if (withShell) colours.push(shellHex.toUpperCase());
  const profile = "Bambu PLA Basic @BBL X1C";
  const rep = <T,>(v: T) => Array.from({ length: slots }, () => v);
  return JSON.stringify(
    {
      from: "cmyw_studio_web",
      name: "CMYW Studio",
      version: "1.0.0",
      printer_model: "Bambu Lab X1 Carbon",
      printer_variant: "0.4",
      printer_settings_id: "Bambu Lab X1 Carbon 0.4 nozzle",
      print_settings_id: "0.08mm Extra Fine @BBL X1C",
      default_print_profile: "0.08mm Extra Fine @BBL X1C",
      default_filament_profile: [profile],
      printable_area: ["0x0", "256x256", "0x256", "256x256", "256x256", "0x256", "256x0", "0x0"],
      bed_shape: ["0x0", "256x256", "0x256", "256x256", "256x256", "0x256", "256x0", "0x0"],
      bed_type: "textured_plate",
      nozzle_diameter: ["0.4"],
      layer_height: "0.08",
      initial_layer_height: "0.2",
      filament_type: rep("PLA"),
      filament_colour: colours,
      filament_vendor: rep("Bambu Lab"),
      filament_ids: rep("GFA00"),
      filament_settings_id: rep(profile),
      filament_diameter: rep("1.75"),
      filament_density: rep("1.24"),
      sparse_infill_density: "100%",
      enable_support: "0",
      // 四色换料必须有擦料塔；默认 Y≈220 会飘出 256 盘边
      enable_prime_tower: "1",
      prime_tower_width: "35",
      prime_tower_brim_width: "3",
      wipe_tower_rotation_angle: "0",
      wipe_tower_x: withShell ? ["15", "15"] : ["15"],
      wipe_tower_y: withShell ? ["200", "200"] : ["200"],
      single_extruder_multi_material: "1",
      filament_map_mode: "Auto For Flush",
      filament_map: rep("1"),
      flush_into_objects: "0",
      flush_into_infill: "0",
      flush_into_support: "0",
    },
    null,
    2,
  );
}

function plateJson(
  bbox: [number, number, number, number],
  identifyId: number,
  name: string,
  layerHeight: number,
): string {
  const area = Math.max(0, bbox[2] - bbox[0]) * Math.max(0, bbox[3] - bbox[1]);
  return JSON.stringify({
    bbox_all: bbox,
    bbox_objects: [{ area, bbox, id: identifyId, layer_height: layerHeight, name }],
    bed_type: "textured_plate",
    filament_colors: [],
    filament_ids: [],
    first_extruder: 0,
    is_seq_print: false,
    nozzle_diameter: 0.4,
    version: 2,
  });
}

const meshStat = (faces: number) =>
  `<mesh_stat face_count="${faces}" edges_fixed="0" degenerate_facets="0" ` +
  `facets_removed="0" facets_reversed="0" backwards_edges="0"/>`;

const IDENTITY = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1";
const transform = (tx: number, ty: number, tz = 0) =>
  `1 0 0 0 1 0 0 0 1 ${tx.toFixed(6)} ${ty.toFixed(6)} ${tz.toFixed(6)}`;

export interface Build3mfResult {
  data: Uint8Array;
  triangles: number;
  bytes: number;
}

/** 组装完整的 Bambu 工程 3MF。 */
export async function build3mf(options: Build3mfOptions): Promise<Build3mfResult> {
  const {
    layers, gridH, pixelSize, artWidthMm, artHeightMm, shell,
    shellColorHex = DEFAULT_SHELL_HEX,
    pictureName = "CMYW Studio",
    thumbnailPng = null,
  } = options;

  const wall = shell?.wall ?? 3;
  const topThickness = shell?.topThickness ?? 2;
  const clearance = shell?.clearance ?? 0.2;
  const { offsetX, offsetY } = computeBedOffset(artWidthMm, artHeightMm, wall, topThickness, clearance);

  // ---- 画片四色件 ----
  const colorMeshes = layers
    .map((l) => ({ input: l, xml: rectsToXml(l.rects, gridH, pixelSize, offsetX, offsetY) }))
    .filter((e) => e.xml.vertices.length > 0);

  if (colorMeshes.length === 0) throw new Error("没有可导出的四色网格 / no colour geometry to export");

  let pictureBbox: [number, number, number, number] | null = null;
  for (const e of colorMeshes) {
    if (!e.xml.bbox) continue;
    pictureBbox = pictureBbox
      ? [
          Math.min(pictureBbox[0], e.xml.bbox[0]), Math.min(pictureBbox[1], e.xml.bbox[1]),
          Math.max(pictureBbox[2], e.xml.bbox[2]), Math.max(pictureBbox[3], e.xml.bbox[3]),
        ]
      : e.xml.bbox;
  }

  // ---- 外壳：网格中心归零，Z 靠 transform 抬到贴盘 ----
  let shellBody: XmlMesh | null = null;
  let shellMod: XmlMesh | null = null;
  let plate2 = { tx: PLATE2_TARGET_CENTER_X, ty: BED_CENTER, tz: 0 };

  if (shell) {
    const { cx, cy } = meshCenterXY(shell.body);
    const z = meshBoundsZ(shell.body);
    const zc = (z.min + z.max) / 2;
    shellBody = meshToXml(shell.body, -cx, -cy, -zc);
    shellMod = meshToXml(shell.modifier, -cx, -cy, -zc);
    plate2 = { tx: PLATE2_TARGET_CENTER_X, ty: BED_CENTER, tz: (z.max - z.min) / 2 };
  }

  const hasShell = shellBody !== null && shellBody.vertices.length > 0;

  // ---- 3D/3dmodel.model ----
  const componentLines = await Promise.all(
    colorMeshes.map(async (e) => {
      const u = await seedUuid(`component:${e.input.partId}`);
      return (
        `    <component p:path="/3D/Objects/object_1.model" objectid="${e.input.partId}" ` +
        `p:UUID="${u}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>`
      );
    }),
  );

  const resources: string[] = [
    `  <object id="${PICTURE_OBJECT_ID}" p:UUID="${await seedUuid("picture-assembly")}" type="model">\n` +
      `   <components>\n${componentLines.join("\n")}\n   </components>\n  </object>`,
  ];
  const buildItems: string[] = [
    `  <item objectid="${PICTURE_OBJECT_ID}" p:UUID="${await seedUuid("build-picture")}" ` +
      `transform="${transform(0, 0)}" printable="1"/>`,
  ];

  if (hasShell) {
    const compBody = await seedUuid("shell-comp-body");
    const compMod = await seedUuid("shell-comp-mod");
    resources.push(
      `  <object id="${SHELL_OBJECT_ID}" p:UUID="${await seedUuid("shell-object")}" type="model" ` +
        `name="${escapeXml("Lightbox_Shell_Box")}">\n   <components>\n` +
        `    <component p:path="/3D/Objects/object_2.model" objectid="${SHELL_BODY_PART_ID}" ` +
        `p:UUID="${compBody}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>\n` +
        `    <component p:path="/3D/Objects/object_2.model" objectid="${SHELL_MODIFIER_PART_ID}" ` +
        `p:UUID="${compMod}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>\n   </components>\n  </object>`,
    );
    buildItems.push(
      `  <item objectid="${SHELL_OBJECT_ID}" p:UUID="${await seedUuid("build-shell")}" ` +
        `transform="${transform(plate2.tx, plate2.ty, plate2.tz)}" printable="1"/>`,
    );
  }

  const mainModel = `<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" ${MODEL_NS}>
 <metadata name="Application">BambuStudio-01.10.01.50</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <resources>
${resources.join("\n")}
 </resources>
 <build p:UUID="${await seedUuid("build-root")}">
${buildItems.join("\n")}
 </build>
</model>
`;

  const relsLines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
    ' <Relationship Target="/3D/Objects/object_1.model" Id="rel-1" ' +
      'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>',
  ];
  if (hasShell) {
    relsLines.push(
      ' <Relationship Target="/3D/Objects/object_2.model" Id="rel-2" ' +
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>',
    );
  }
  relsLines.push("</Relationships>");

  // ---- 部件模型文件 ----
  const object1 = objectFileModel(
    (
      await Promise.all(colorMeshes.map((e) => meshObjectXml(e.input.partId, e.input.name, e.xml)))
    ).join("\n"),
  );

  // ---- model_settings.config ----
  const totalPictureFaces = colorMeshes.reduce((t, e) => t + e.xml.faceCount, 0);
  const ms: string[] = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>"];
  ms.push(`  <object id="${PICTURE_OBJECT_ID}">`);
  ms.push(`    <metadata key="name" value="${escapeXml(pictureName)}"/>`);
  ms.push('    <metadata key="extruder" value="1"/>');
  ms.push(`    <metadata face_count="${totalPictureFaces}"/>`);
  for (const e of colorMeshes) {
    ms.push(`    <part id="${e.input.partId}" subtype="normal_part">`);
    ms.push(`      <metadata key="name" value="${escapeXml(e.input.name)}"/>`);
    ms.push(`      <metadata key="matrix" value="${IDENTITY}"/>`);
    ms.push(`      <metadata key="source_offset_x" value="${offsetX.toFixed(6)}"/>`);
    ms.push(`      <metadata key="source_offset_y" value="${offsetY.toFixed(6)}"/>`);
    ms.push(`      <metadata key="extruder" value="${e.input.extruder}"/>`);
    ms.push(`      ${meshStat(e.xml.faceCount)}`);
    ms.push("    </part>");
  }
  ms.push("  </object>");

  if (hasShell && shellBody && shellMod) {
    ms.push(`  <object id="${SHELL_OBJECT_ID}">`);
    ms.push('    <metadata key="name" value="Lightbox_Shell_Box"/>');
    ms.push('    <metadata key="extruder" value="5"/>');
    ms.push(`    <metadata face_count="${shellBody.faceCount + shellMod.faceCount}"/>`);
    ms.push(`    <part id="${SHELL_BODY_PART_ID}" subtype="normal_part">`);
    ms.push('      <metadata key="name" value="Lightbox_Shell_Box"/>');
    ms.push(`      <metadata key="matrix" value="${IDENTITY}"/>`);
    ms.push('      <metadata key="source_offset_x" value="0"/>');
    ms.push('      <metadata key="source_offset_y" value="0"/>');
    ms.push('      <metadata key="source_offset_z" value="0"/>');
    ms.push('      <metadata key="extruder" value="5"/>');
    ms.push(`      ${meshStat(shellBody.faceCount)}`);
    ms.push("    </part>");
    ms.push(`    <part id="${SHELL_MODIFIER_PART_ID}" subtype="modifier_part">`);
    ms.push(`      <metadata key="name" value="${escapeXml(SHELL_TOP_MODIFIER_NAME)}"/>`);
    ms.push(`      <metadata key="matrix" value="${IDENTITY}"/>`);
    ms.push('      <metadata key="source_offset_x" value="0"/>');
    ms.push('      <metadata key="source_offset_y" value="0"/>');
    ms.push('      <metadata key="source_offset_z" value="0"/>');
    ms.push('      <metadata key="sparse_infill_density" value="100%"/>');
    ms.push(`      ${meshStat(shellMod.faceCount)}`);
    ms.push("    </part>");
    ms.push("  </object>");
  }

  const plateBlock = (
    id: number, name: string, printSettings: string, objectId: number, identifyId: number,
  ) => [
    "  <plate>",
    `    <metadata key="plater_id" value="${id}"/>`,
    `    <metadata key="plater_name" value="${escapeXml(name)}"/>`,
    '    <metadata key="locked" value="true"/>',
    '    <metadata key="filament_map_mode" value="Auto For Flush"/>',
    `    <metadata key="print_settings_id" value="${printSettings}"/>`,
    '    <metadata key="printer_settings_id" value="Bambu Lab X1 Carbon 0.4 nozzle"/>',
    '    <metadata key="nozzle_diameters" value="0.4"/>',
    "    <model_instance>",
    `      <metadata key="object_id" value="${objectId}"/>`,
    '      <metadata key="instance_id" value="0"/>',
    `      <metadata key="identify_id" value="${identifyId}"/>`,
    "    </model_instance>",
    "  </plate>",
  ];

  ms.push(...plateBlock(1, PLATE1_NAME, "0.08mm Extra Fine @BBL X1C", PICTURE_OBJECT_ID, PICTURE_IDENTIFY_ID));
  if (hasShell) {
    ms.push(...plateBlock(2, PLATE2_NAME, "0.2mm Standard @BBL X1C", SHELL_OBJECT_ID, SHELL_IDENTIFY_ID));
  }

  ms.push("  <assemble>");
  ms.push(
    `   <assemble_item object_id="${PICTURE_OBJECT_ID}" instance_id="0" ` +
      `transform="${transform(0, 0)}" offset="0 0 0" />`,
  );
  if (hasShell) {
    ms.push(
      `   <assemble_item object_id="${SHELL_OBJECT_ID}" instance_id="0" ` +
        `transform="${transform(plate2.tx, plate2.ty, plate2.tz)}" offset="0 0 0" />`,
    );
  }
  ms.push("  </assemble>");
  ms.push("</config>");

  // ---- 打包 ----
  const enc = new TextEncoder();
  const files: ZipEntry[] = [
    { name: "[Content_Types].xml", data: enc.encode(CONTENT_TYPES) },
    { name: "_rels/.rels", data: enc.encode(packageRels(!!thumbnailPng)) },
    { name: "3D/3dmodel.model", data: enc.encode(mainModel) },
    { name: "3D/_rels/3dmodel.model.rels", data: enc.encode(relsLines.join("\n")) },
    { name: "3D/Objects/object_1.model", data: enc.encode(object1) },
  ];

  if (hasShell && shellBody && shellMod) {
    const shellObjects = [
      await meshObjectXml(SHELL_BODY_PART_ID, "Lightbox_Shell_Box", shellBody),
      await meshObjectXml(SHELL_MODIFIER_PART_ID, SHELL_TOP_MODIFIER_NAME, shellMod),
    ].join("\n");
    files.push({ name: "3D/Objects/object_2.model", data: enc.encode(objectFileModel(shellObjects)) });
  }

  if (thumbnailPng) {
    files.push({ name: "Metadata/thumbnail.png", data: thumbnailPng, store: true });
    files.push({ name: "Metadata/plate_1.png", data: thumbnailPng, store: true });
  }

  files.push(
    { name: "Metadata/project_settings.config", data: enc.encode(projectSettings(shellColorHex, hasShell)) },
    { name: "Metadata/model_settings.config", data: enc.encode(ms.join("\n")) },
    { name: "Metadata/slice_info.config", data: enc.encode(SLICE_INFO) },
    {
      name: "Metadata/filament_sequence.json",
      data: enc.encode(
        JSON.stringify({
          plate_1: { nozzle_sequence: [], optimal_assignment: [], sequence: [] },
          ...(hasShell
            ? { plate_2: { nozzle_sequence: [], optimal_assignment: [], sequence: [] } }
            : {}),
        }),
      ),
    },
  );

  if (pictureBbox) {
    files.push({
      name: "Metadata/plate_1.json",
      data: enc.encode(plateJson(pictureBbox, PICTURE_IDENTIFY_ID, pictureName, LAYER_HEIGHT)),
    });
  }
  if (hasShell && shellBody?.bbox) {
    const b = shellBody.bbox;
    const shifted: [number, number, number, number] = [
      b[0] + plate2.tx, b[1] + plate2.ty, b[2] + plate2.tx, b[3] + plate2.ty,
    ];
    files.push({
      name: "Metadata/plate_2.json",
      data: enc.encode(plateJson(shifted, SHELL_IDENTIFY_ID, "Lightbox_Shell_Box", 0.2)),
    });
  }

  const data = await createZip(files);
  const triangles =
    totalPictureFaces + (shellBody?.faceCount ?? 0) + (shellMod?.faceCount ?? 0);
  return { data, triangles, bytes: data.length };
}
