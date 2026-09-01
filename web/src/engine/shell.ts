/**
 * 参数化灯箱外壳 —— 直接构造三角网格，不需要 CAD 内核。
 * Parametric lightbox shell, built directly as a mesh (no CAD kernel in the browser).
 *
 * Python 侧用 CadQuery 做布尔运算，但最终形状其实是个三区段棱柱，可以直接建：
 *
 *   z ∈ [0, wall]              外框实心 —— 底板
 *   z ∈ [wall, depth−slot]     外框 − 内腔 —— 侧壁
 *   z ∈ [depth−slot, depth]    外框 − 画片轮廓 —— 卡槽
 *                              （内腔与画片轮廓之差 = 托住画片的承台）
 *
 * 再加一个贯穿 +X 侧壁的 Type-C 通孔。
 *
 * 尺寸规则与 shell_master/shell_cadquery.py 的 _layout() 一致：
 *   内腔 = 画片内缩 wall/2（顶边 top/2）
 *   外框 = 画片外扩 wall（顶边 top_thickness）
 */

export interface ShellParams {
  /** 画片宽高 mm */
  artW: number;
  artH: number;
  /** 侧壁/底壁厚 */
  wall: number;
  /** 顶壁厚（触摸面），硬上限 3mm */
  topThickness: number;
  /** 外壳总深 Z */
  depth: number;
  /** 外框圆角，与画片一致 */
  corner: number;
  /** 画片放置间隙 */
  clearance: number;
  /** 卡槽 Z 向深度（画片厚度） */
  artThickness: number;
  /** 卡槽 XY 方向的打印公差 */
  fdmTol: number;
}

export const SHELL_DEFAULTS: Omit<ShellParams, "artW" | "artH"> = {
  wall: 3.0,
  topThickness: 2.0,
  depth: 18.0,
  corner: 5.0,
  clearance: 0.2,
  artThickness: 2.5,
  fdmTol: 0.2,
};

/** Type-C 开孔名义尺寸，含公差与外扩，与 CadQuery 母本一致。 */
const USB = {
  w: 9.0 + 0.2 + 2 * 0.05,
  h: 3.2 + 0.2 + 2 * 0.05,
  r: 1.6 + 0.05,
  liftZ: 1.55,
};

/** 每个圆角用多少段折线近似。12 段在 5mm 圆角上误差 < 0.02mm，肉眼与打印均不可见。 */
const ARC_SEGMENTS = 12;

export interface Mesh {
  /** xyz 连续排列 */
  vertices: Float64Array;
  /** 三角形顶点索引 */
  indices: Uint32Array;
}

type Pt = readonly [number, number];

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

function clampCorner(w: number, h: number, r: number): number {
  return Math.max(0, Math.min(r, w * 0.5 - 0.05, h * 0.5 - 0.05));
}

/**
 * 生成圆角矩形折线，逆时针，起点在 +X 边中点附近。
 *
 * 四个角各用固定段数，因此不同尺寸的两个多边形顶点数相同、顺序对应，
 * 可以直接在两者之间拉三角形带（用于环形面与侧壁）。
 */
function roundedRect(cx: number, cy: number, w: number, h: number, r: number): Pt[] {
  const rr = clampCorner(w, h, r);
  const x0 = cx - w / 2;
  const x1 = cx + w / 2;
  const y0 = cy - h / 2;
  const y1 = cy + h / 2;
  const pts: Pt[] = [];

  // 四个角的圆心与起始角度（逆时针：右下 → 右上 → 左上 → 左下）
  const corners: Array<[number, number, number]> = [
    [x1 - rr, y0 + rr, -Math.PI / 2],
    [x1 - rr, y1 - rr, 0],
    [x0 + rr, y1 - rr, Math.PI / 2],
    [x0 + rr, y0 + rr, Math.PI],
  ];

  if (rr <= 1e-9) {
    // 直角：仍然按每角 ARC_SEGMENTS 个重合点生成，保证顶点数一致
    for (const [ccx, ccy] of corners) {
      for (let i = 0; i <= ARC_SEGMENTS; i += 1) pts.push([ccx, ccy]);
    }
    return pts;
  }

  for (const [ccx, ccy, start] of corners) {
    for (let i = 0; i <= ARC_SEGMENTS; i += 1) {
      const a = start + (Math.PI / 2) * (i / ARC_SEGMENTS);
      pts.push([ccx + rr * Math.cos(a), ccy + rr * Math.sin(a)]);
    }
  }
  return pts;
}

/** 增量式网格构建器：只管往里塞三角形，最后一次性打包成 TypedArray。 */
class MeshBuilder {
  private verts: number[] = [];
  private tris: number[] = [];

  addVertex(x: number, y: number, z: number): number {
    const id = this.verts.length / 3;
    this.verts.push(x, y, z);
    return id;
  }

  addTriangle(a: number, b: number, c: number): void {
    this.tris.push(a, b, c);
  }

  /** 四边形 a-b-c-d（首尾相连）拆成两个三角形。 */
  addQuad(a: number, b: number, c: number, d: number): void {
    this.tris.push(a, b, c, a, c, d);
  }

  build(): Mesh {
    return {
      vertices: Float64Array.from(this.verts),
      indices: Uint32Array.from(this.tris),
    };
  }

  get triangleCount(): number {
    return this.tris.length / 3;
  }
}

/** 凸多边形用质心扇形三角化。圆角矩形一定是凸的。 */
function fanFill(mb: MeshBuilder, poly: Pt[], z: number, faceUp: boolean): void {
  let sx = 0;
  let sy = 0;
  for (const [x, y] of poly) {
    sx += x;
    sy += y;
  }
  const center = mb.addVertex(sx / poly.length, sy / poly.length, z);
  const ids = poly.map(([x, y]) => mb.addVertex(x, y, z));
  for (let i = 0; i < ids.length; i += 1) {
    const j = (i + 1) % ids.length;
    if (faceUp) mb.addTriangle(center, ids[i], ids[j]);
    else mb.addTriangle(center, ids[j], ids[i]);
  }
}

/** 两个同向、同顶点数的多边形之间的水平环面。 */
function ringFill(mb: MeshBuilder, outer: Pt[], inner: Pt[], z: number, faceUp: boolean): void {
  const o = outer.map(([x, y]) => mb.addVertex(x, y, z));
  const n = inner.map(([x, y]) => mb.addVertex(x, y, z));
  for (let i = 0; i < o.length; i += 1) {
    const j = (i + 1) % o.length;
    if (faceUp) mb.addQuad(o[i], o[j], n[j], n[i]);
    else mb.addQuad(o[i], n[i], n[j], o[j]);
  }
}

/**
 * 多边形垂直侧壁，可选跳过若干段（给开孔让位）。
 * @param outward true = 法线朝多边形外侧
 */
function sideWall(
  mb: MeshBuilder,
  poly: Pt[],
  zLow: number,
  zHigh: number,
  outward: boolean,
  skip?: (i: number) => boolean,
): void {
  const lo = poly.map(([x, y]) => mb.addVertex(x, y, zLow));
  const hi = poly.map(([x, y]) => mb.addVertex(x, y, zHigh));
  for (let i = 0; i < poly.length; i += 1) {
    if (skip?.(i)) continue;
    const j = (i + 1) % poly.length;
    if (outward) mb.addQuad(lo[i], lo[j], hi[j], hi[i]);
    else mb.addQuad(lo[i], hi[i], hi[j], lo[j]);
  }
}

/** 一段被开了洞的竖直墙面（位于 x = 常数的平面上）。 */
interface HoledFace {
  x: number;
  /** 这段墙面自身的 Y / Z 跨度 —— 外框面与内腔面并不相同，必须分别给 */
  yLo: number;
  yHi: number;
  zLo: number;
  zHi: number;
  /** 法线是否朝 +X */
  facePlusX: boolean;
}

/**
 * 在 +X 侧壁上开一个通孔，并补上孔壁。
 *
 * 洞口用任意闭合折线给出（Type-C 是圆角矩形），从外框右面贯穿到内腔右面。
 * 为了不破坏侧壁的三角形带，做法是把孔所在的那一整段侧壁替换成「带洞的墙面」，
 * 再补一圈孔壁把内外两个洞口连起来。
 *
 * 注意外框面与内腔面的 Y、Z 跨度不同（外框整高 0→depth，内腔只有 wall→slotZ），
 * 混用会留下未配平的边，也就是网格上的洞。
 *
 * hole 必须是 roundedRect 的输出（在 (y, z) 平面上、逆时针、四段等长圆弧），
 * 下面按段索引把洞口分给四个墙角，靠的就是这个排列。
 */
function punchSideHole(
  mb: MeshBuilder,
  outerFace: HoledFace,
  innerFace: HoledFace,
  hole: Pt[],
): void {
  const V = (x: number, y: number, z: number) => mb.addVertex(x, y, z);
  const n = hole.length;
  const arcLen = ARC_SEGMENTS + 1;

  /**
   * 墙角 c 负责的洞口折线从哪个顶点开始。
   *
   * roundedRect 的四段圆弧依次贴着 (yHi,zLo) → (yHi,zHi) → (yLo,zHi) → (yLo,zLo)，
   * 而墙角按 (yLo,zLo) → (yHi,zLo) → (yHi,zHi) → (yLo,zHi) 编号，故第 a 段对应墙角 (a+1)%4。
   * 每段链条 = 前一段圆弧的末点（直边起点）→ 本段圆弧末点，四条链首尾相接铺满洞口一周。
   */
  const chainStart = (c: number) => ((((c + 3) % 4) * arcLen - 1) + n) % n;

  /**
   * 把「带洞的矩形墙面」三角化。
   *
   * 关键约束：补丁的**外边界只能用四个角点**。若在外边界上插入额外顶点
   * （例如按 3×3 网格切），相邻的底面盖板与角部侧壁仍然只有一条长边，
   * 就会形成 T 型接点——非流形，切片器当破面处理。
   *
   * 因此每个墙角向它那一段洞口折线扇形铺开，再用一片过渡三角形跨过墙边，
   * 新增的边全在内部，外边界保持四条整边。洞口凸、且整体落在墙面内部，
   * 墙角对本段折线全可见，扇形不会自交。
   */
  const buildFace = (f: HoledFace) => {
    // (y,z) 按 (lo,lo)→(hi,lo)→(hi,hi)→(lo,hi) 绕序，在 x=常数 面上给出 +X 法线
    const cornerRing: Array<[number, number]> = [
      [f.yLo, f.zLo],
      [f.yHi, f.zLo],
      [f.yHi, f.zHi],
      [f.yLo, f.zHi],
    ];
    const o = cornerRing.map(([y, z]) => V(f.x, y, z));
    const h = hole.map(([y, z]) => V(f.x, y, z));
    const tri = (a: number, b: number, c: number) => {
      if (f.facePlusX) mb.addTriangle(a, b, c);
      else mb.addTriangle(a, c, b);
    };
    for (let c = 0; c < 4; c += 1) {
      const next = (c + 1) % 4;
      const end = chainStart(next);
      for (let k = chainStart(c); k !== end; k = (k + 1) % n) {
        tri(o[c], h[(k + 1) % n], h[k]);
      }
      tri(o[c], o[next], h[end]);
    }
  };

  buildFace(outerFace);
  buildFace(innerFace);

  // 孔壁：沿洞口一圈连接内外洞口，法线朝向孔内
  const xo = outerFace.x;
  const xi = innerFace.x;
  for (let k = 0; k < n; k += 1) {
    const [ay, az] = hole[k];
    const [by, bz] = hole[(k + 1) % n];
    mb.addQuad(V(xo, ay, az), V(xo, by, bz), V(xi, by, bz), V(xi, ay, az));
  }
}

/**
 * 构建完整外壳网格。
 *
 * 坐标系与 Python 一致：开口朝 +Z，外底面在 Z=0，画片原点在 (clearance, clearance)。
 */
export function buildShellMesh(params: ShellParams): Mesh {
  const p = { ...params };
  p.wall = clamp(p.wall, 1.0, 8.0);
  p.topThickness = clamp(p.topThickness, 0.8, 3.0);
  p.clearance = clamp(p.clearance, 0.0, 0.5);
  p.fdmTol = clamp(p.fdmTol, 0.0, 0.6);
  p.artThickness = clamp(p.artThickness, 1.0, 6.0);
  p.depth = Math.max(p.wall + p.artThickness + 4.0, p.depth);

  const insetSide = p.wall * 0.5;
  const insetTop = p.topThickness * 0.5;

  const artX0 = p.clearance;
  const artY0 = p.clearance;
  const artX1 = p.clearance + p.artW;
  const artY1 = p.clearance + p.artH;

  const cavX0 = artX0 + insetSide;
  const cavY0 = artY0 + insetSide;
  const cavX1 = artX1 - insetSide;
  const cavY1 = artY1 - insetTop;

  const outX0 = artX0 - p.wall;
  const outY0 = artY0 - p.wall;
  const outX1 = artX1 + p.wall;
  const outY1 = artY1 + p.topThickness;

  const cavW = cavX1 - cavX0;
  const cavH = cavY1 - cavY0;
  if (cavW < 5 || cavH < 5) {
    throw new Error("内缩后内腔过小：减小壁厚或增大画片 / cavity too small after inset");
  }

  const slotZ = p.depth - p.artThickness;

  const outer = roundedRect((outX0 + outX1) / 2, (outY0 + outY1) / 2, outX1 - outX0, outY1 - outY0, p.corner);
  const cavity = roundedRect((cavX0 + cavX1) / 2, (cavY0 + cavY1) / 2, cavW, cavH, p.corner);
  const slot = roundedRect(
    (artX0 + artX1) / 2,
    (artY0 + artY1) / 2,
    p.artW + p.fdmTol,
    p.artH + p.fdmTol,
    p.corner,
  );

  const mb = new MeshBuilder();

  // Type-C 孔：位于 +X 侧壁的直边段上，Y 居中
  const usbCy = (artY0 + artY1) / 2;
  let usbCz = p.wall + USB.liftZ + USB.h * 0.5;
  const maxCz = p.depth - p.artThickness - USB.h * 0.5 - 0.5;
  const minCz = p.wall + USB.h * 0.5 + 0.2;
  usbCz = clamp(usbCz, minCz, maxCz);
  const usbZLo = usbCz - USB.h / 2;
  const usbZHi = usbCz + USB.h / 2;
  // 洞口是圆角矩形（R1.65，上下边几乎贴成半圆），与 Type-C 插头轮廓、以及
  // CadQuery 母本 cut_type_c_hole() 的 fillet 一致。切成直角方口插头虽然塞得进，
  // 但四角会各露一块空隙，插头也不再被孔壁扶正——外观和手感都是坏的。
  const usbHole = roundedRect(usbCy, usbCz, USB.w, USB.h, USB.r);

  // 孔所在的 Z 区间完全落在侧壁段（wall → slotZ）内，因此只需在这一段开洞
  const holeInWallZone = usbZLo > p.wall + 1e-6 && usbZHi < slotZ - 1e-6;

  // --- 底板 ---
  fanFill(mb, outer, 0, false); // 外底面朝下
  fanFill(mb, cavity, p.wall, true); // 内腔底面朝上

  // --- 外侧壁：0 → depth ---
  // +X 直边所在的段需要为 Type-C 孔让位，单独处理
  const rightEdgeIndex = ARC_SEGMENTS; // 右下角弧结束 → 右上角弧开始之间的直边
  sideWall(mb, outer, 0, p.depth, true, (i) => holeInWallZone && i === rightEdgeIndex);
  sideWall(mb, cavity, p.wall, slotZ, false, (i) => holeInWallZone && i === rightEdgeIndex);

  if (holeInWallZone) {
    const oA = outer[rightEdgeIndex];
    const oB = outer[(rightEdgeIndex + 1) % outer.length];
    const cA = cavity[rightEdgeIndex];
    const cB = cavity[(rightEdgeIndex + 1) % cavity.length];
    // 被跳过的两段侧壁，各自补成「带洞的墙」，再用孔壁连起来
    punchSideHole(
      mb,
      {
        x: oA[0],
        yLo: Math.min(oA[1], oB[1]),
        yHi: Math.max(oA[1], oB[1]),
        zLo: 0,
        zHi: p.depth,
        facePlusX: true,
      },
      {
        x: cA[0],
        yLo: Math.min(cA[1], cB[1]),
        yHi: Math.max(cA[1], cB[1]),
        zLo: p.wall,
        zHi: slotZ,
        facePlusX: false,
      },
      usbHole,
    );
  }

  // --- 承托台：内腔轮廓 → 卡槽轮廓，位于 slotZ ---
  ringFill(mb, slot, cavity, slotZ, true);

  // --- 卡槽内壁：slotZ → depth ---
  sideWall(mb, slot, slotZ, p.depth, false);

  // --- 顶面：外框 − 卡槽 ---
  ringFill(mb, outer, slot, p.depth, true);

  return mb.build();
}

/** 外壳 XY 包围盒，用于摆盘。与 Python 的 compute_xy_bounds 一致。 */
export function shellXYBounds(
  artW: number,
  artH: number,
  wall: number,
  topThickness: number,
  clearance: number,
): { minX: number; minY: number; maxX: number; maxY: number } {
  return {
    minX: clearance - wall,
    minY: clearance - wall,
    maxX: clearance + artW + wall,
    maxY: clearance + artH + topThickness,
  };
}

/**
 * 顶壁实心 modifier：盖住顶壁触摸区的一块薄盒，让 Bambu 以 100% 填充打印它。
 * 对应 Python 的 top_solid_modifier_to_3mf_xml。
 */
export function buildTopSolidModifier(params: ShellParams): Mesh {
  const p = params;
  const artY1 = p.clearance + p.artH;
  const outX0 = p.clearance - p.wall;
  const outX1 = p.clearance + p.artW + p.wall;
  const outY1 = artY1 + p.topThickness;
  const y0 = artY1 - p.topThickness * 0.5;

  const mb = new MeshBuilder();
  const z0 = 0;
  const z1 = p.depth;
  const corners: Array<[number, number]> = [
    [outX0, y0],
    [outX1, y0],
    [outX1, outY1],
    [outX0, outY1],
  ];
  const lo = corners.map(([x, y]) => mb.addVertex(x, y, z0));
  const hi = corners.map(([x, y]) => mb.addVertex(x, y, z1));
  mb.addQuad(lo[0], lo[3], lo[2], lo[1]);
  mb.addQuad(hi[0], hi[1], hi[2], hi[3]);
  for (let i = 0; i < 4; i += 1) {
    const j = (i + 1) % 4;
    mb.addQuad(lo[i], lo[j], hi[j], hi[i]);
  }
  return mb.build();
}
