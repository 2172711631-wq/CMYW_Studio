/**
 * 解算工作线程。
 * Engine worker — keeps the whole pipeline off the main thread.
 *
 * 240mm 画幅是 1200×900 的网格、四个通道，主线程跑会直接卡死界面几秒钟。
 * 放进 Worker 后页面始终可交互，还能实时回报进度。
 */

import { GRID_MAX, GRID_MIN, LAYER_HEIGHT, MESH_MERGE_FILTER } from "../engine/constants";
import { applyKeepMask, roundedCornerKeepMask } from "../engine/corner";
import { computeZStarts, maxStack, separateCMYW, type LayerSet } from "../engine/separate";
import { SHELL_DEFAULTS, buildShellMesh, buildTopSolidModifier } from "../engine/shell";
import { simulateLit } from "../engine/simulate";
import { build3mf } from "../engine/threemf";
import { meshMergeFilter, mergeVoxelRectangles } from "../engine/voxel";

export interface ShellRequest {
  wall: number;
  depth: number;
  corner: number;
  clearance: number;
  colorHex: string;
}

export type WorkerRequest =
  | {
      type: "preview";
      id: number;
      rgb: Uint8ClampedArray;
      gridW: number;
      gridH: number;
      cornerRadiusMm: number;
      /** 抖动幅度（层）。0 = 不抖，不传就用引擎默认 */
      ditherAmount?: number;
      /** 浅色保留阈值。线稿要调低，否则淡线和抗锯齿边会被整条丢掉 */
      keepFloor?: number;
      liftChromaOnly?: boolean;
      ditherBlock?: number;
      ditherScreen?: "bayer" | "line";
      /** 网格化前的中值滤波尺寸。3 = 默认，1 = 关掉（线稿要关，否则细线被吃） */
      mergeFilter?: number;
      widthMm: number;
    }
  | {
      type: "export";
      id: number;
      rgb: Uint8ClampedArray;
      gridW: number;
      gridH: number;
      widthMm: number;
      heightMm: number;
      shell: ShellRequest | null;
      /** 形状遮罩半径 mm。圆形画片传边长的一半；不传则沿用外壳圆角 */
      cornerRadiusMm?: number;
      /** 抖动幅度（层）。0 = 不抖，不传就用引擎默认 */
      ditherAmount?: number;
      /** 浅色保留阈值。线稿要调低，否则淡线和抗锯齿边会被整条丢掉 */
      keepFloor?: number;
      liftChromaOnly?: boolean;
      ditherBlock?: number;
      ditherScreen?: "bayer" | "line";
      /** 网格化前的中值滤波尺寸。3 = 默认，1 = 关掉（线稿要关，否则细线被吃） */
      mergeFilter?: number;
      /** 圆形时要不要连吧唧外壳一起打包 */
      badge?: { diameter: number } | null;
      standee?: { w: number; h: number } | null;
      pictureName: string;
    };

export type WorkerResponse =
  | { type: "progress"; id: number; percent: number; stage: string }
  | {
      type: "preview";
      id: number;
      image: ImageData;
      stack: number;
      thicknessMm: number;
      coverage: { c: number; m: number; y: number };
    }
  | { type: "export"; id: number; data: Uint8Array; triangles: number; bytes: number }
  | { type: "error"; id: number; message: string };

const post = (msg: WorkerResponse, transfer: Transferable[] = []) =>
  (self as unknown as Worker).postMessage(msg, transfer);

const report = (id: number, percent: number, stage: string) =>
  post({ type: "progress", id, percent, stage });

/** 非零占比，用来告诉用户这张图用了多少彩色墨。 */
function coverage(layer: Int32Array): number {
  let n = 0;
  for (let i = 0; i < layer.length; i += 1) if (layer[i] > 0) n += 1;
  return (n / layer.length) * 100;
}

function separateWithCorner(
  rgb: Uint8ClampedArray,
  gridW: number,
  gridH: number,
  widthMm: number,
  cornerRadiusMm: number,
  ditherAmount?: number,
  keepFloor?: number,
  liftChromaOnly?: boolean,
  ditherBlock?: number,
  ditherScreen?: "bayer" | "line",
): LayerSet {
  // 抖动是给照片的：连续调靠它把层数之间的台阶打散。
  // 插画/线稿是大片平色 + 细线，抖动反而在平色里撒麻点、把细线咬断，关掉更干净。
  const layers = separateCMYW(rgb, gridW, gridH, {
    dither: (ditherAmount ?? 1) > 0,
    ditherAmount,
    keepFloor,
    liftChromaOnly,
    ditherBlock,
    ditherScreen,
  });
  const mask = roundedCornerKeepMask(gridW, gridH, widthMm, cornerRadiusMm);
  if (mask) applyKeepMask(mask, layers.W, layers.Y, layers.M, layers.C);
  return layers;
}

/* ---------------- 吧唧外壳 ---------------- */

interface BakedBadge {
  front: { vertices: Float64Array; indices: Uint32Array };
  back: { vertices: Float64Array; indices: Uint32Array };
}

const badgeCache = new Map<number, BakedBadge>();

async function loadBadge(diameter: number): Promise<BakedBadge> {
  const hit = badgeCache.get(diameter);
  if (hit) return hit;
  const res = await fetch(`/badge/${diameter.toFixed(0)}.json`);
  if (!res.ok) {
    throw new Error(`没有 ⌀${diameter} 的吧唧外壳数据 / no baked badge shell for ⌀${diameter}`);
  }
  const raw = (await res.json()) as {
    parts: Record<string, { vertices: number[]; indices: number[] }>;
  };
  const conv = (k: string) => ({
    vertices: Float64Array.from(raw.parts[k].vertices),
    indices: Uint32Array.from(raw.parts[k].indices),
  });
  const baked = { front: conv("front"), back: conv("back") };
  badgeCache.set(diameter, baked);
  return baked;
}

/* ---------------- 立牌外壳 ---------------- */

interface BakedStandee {
  order: string[];
  bias: { x: number; y: number };
  parts: Record<string, { label: string; vertices: Float64Array; indices: Uint32Array }>;
}

const standeeCache = new Map<string, BakedStandee>();

/** 四件的坐标在烘焙时就排好盘了，这里原样取出来 —— 排盘算法只有 Python 那一份。 */
async function loadStandee(w: number, h: number): Promise<BakedStandee> {
  const key = `${w.toFixed(0)}x${h.toFixed(0)}`;
  const hit = standeeCache.get(key);
  if (hit) return hit;
  const res = await fetch(`/standee/${key}.json`);
  if (!res.ok) {
    throw new Error(`没有 ${key} 的立牌外壳数据 / no baked standee shell for ${key}`);
  }
  const raw = (await res.json()) as {
    order: string[];
    bias?: [number, number];
    parts: Record<string, { label: string; vertices: number[]; indices: number[] }>;
  };
  const parts: BakedStandee["parts"] = {};
  for (const [k, v] of Object.entries(raw.parts)) {
    parts[k] = {
      label: v.label,
      vertices: Float64Array.from(v.vertices),
      indices: Uint32Array.from(v.indices),
    };
  }
  const baked = {
    order: raw.order,
    bias: { x: raw.bias?.[0] ?? 0, y: raw.bias?.[1] ?? 0 },
    parts,
  };
  standeeCache.set(key, baked);
  return baked;
}

function shiftMeshX<T extends { vertices: Float64Array; indices: Uint32Array }>(
  mesh: T,
  dx: number,
): T {
  const v = Float64Array.from(mesh.vertices);
  for (let i = 0; i < v.length; i += 3) v[i] += dx;
  return { ...mesh, vertices: v };
}

self.onmessage = async (event: MessageEvent<WorkerRequest>) => {
  const req = event.data;
  try {
    if (req.type === "preview") {
      report(req.id, 15, "分色中");
      const layers = separateWithCorner(
        req.rgb, req.gridW, req.gridH, req.widthMm, req.cornerRadiusMm,
        req.ditherAmount, req.keepFloor, req.liftChromaOnly, req.ditherBlock, req.ditherScreen,
      );

      report(req.id, 65, "模拟透光");
      const image = simulateLit(layers);
      const stack = maxStack(layers);

      post(
        {
          type: "preview",
          id: req.id,
          image,
          stack,
          thicknessMm: stack * LAYER_HEIGHT,
          coverage: {
            c: coverage(layers.C),
            m: coverage(layers.M),
            y: coverage(layers.Y),
          },
        },
        [image.data.buffer],
      );
      return;
    }

    // ---- 导出 3MF ----
    const { gridW, gridH, widthMm, heightMm, shell } = req;
    if (gridW < GRID_MIN || gridW > GRID_MAX || gridH < GRID_MIN || gridH > GRID_MAX) {
      throw new Error(`网格超出范围 / grid out of range: ${gridW}×${gridH}`);
    }

    report(req.id, 8, "分色中");
    // 形状遮罩半径：圆形画片就是"正方形 + 半径 = 边长/2"，
    // 复用圆角遮罩那套（已经有 Python 对拍），不需要另写一条裁形路径。
    const cornerRadius = req.cornerRadiusMm ?? (shell ? shell.corner : 0);
    const layers = separateWithCorner(
      req.rgb, gridW, gridH, widthMm, cornerRadius, req.ditherAmount, req.keepFloor,
    );

    report(req.id, 30, "平滑层高");
    // 中值滤波是为了把同层高的像素连成片、少出几个矩形，代价是吃掉 1–2 像素宽的东西。
    // 照片无所谓（本来就没有一像素宽的结构），线稿则正好靠这些细节吃饭，所以要能关。
    const mf = req.mergeFilter ?? MESH_MERGE_FILTER;
    const filtered = {
      W: meshMergeFilter(layers.W, gridW, gridH, mf),
      Y: meshMergeFilter(layers.Y, gridW, gridH, mf),
      M: meshMergeFilter(layers.M, gridW, gridH, mf),
      C: meshMergeFilter(layers.C, gridW, gridH, mf),
    };
    const z = computeZStarts({ ...filtered, gridW, gridH });

    report(req.id, 48, "合并体素");
    const pixelSize = widthMm / gridW;
    const plates = [
      { partId: 1, name: "1_Cyan", extruder: 1, layer: filtered.C, zs: z.zC },
      { partId: 2, name: "2_Magenta", extruder: 2, layer: filtered.M, zs: z.zM },
      { partId: 3, name: "3_Yellow", extruder: 3, layer: filtered.Y, zs: z.zY },
      { partId: 4, name: "4_White", extruder: 4, layer: filtered.W, zs: z.zW },
    ].map((p) => ({
      partId: p.partId,
      name: p.name,
      extruder: p.extruder,
      rects: mergeVoxelRectangles(p.layer, p.zs, gridW, gridH, LAYER_HEIGHT),
    }));

    report(req.id, 72, shell || req.badge || req.standee ? "生成外壳" : "组装 3MF");
    let shellInput = null;
    if (req.standee) {
      // 立牌是四件一盘。前框走 body，灯板托盘占掉 modifier 那个位置（实体，不是修改器），
      // 底座和底盖挂在 extraParts 上 —— 四件同属一个对象、同在第二个盘，
      // 于是导出来就是「一盘画一盘框」，和小夜灯那个 3MF 一个形状。
      const baked = await loadStandee(req.standee.w, req.standee.h);
      const pick = (k: string) => baked.parts[k];
      shellInput = {
        body: pick("frame"),
        modifier: pick("module"),
        wall: 0,
        topThickness: 0,
        clearance: 0,
        secondPart: { name: pick("module").label, normal: true },
        objectName: pick("frame").label,
        extraParts: baked.order
          .filter((k) => k !== "frame" && k !== "module")
          .map((k) => ({ name: pick(k).label, mesh: pick(k) })),
        plateName: "立牌外壳建议0.2mm层高打印",
        plateBias: baked.bias,
      };
    } else if (req.badge) {
      // 吧唧外壳跑不了 CadQuery，是 tools/bake_badge.py 从同一个母本烘出来的，
      // 放在 public/badge/ 按需取 —— 不进主包，只有真做吧唧的人才下这几十 KB。
      const baked = await loadBadge(req.badge.diameter);
      shellInput = {
        body: baked.front,
        // 后盖往边上挪一格，不然两件会叠在一起
        modifier: shiftMeshX(baked.back, req.badge.diameter + 8),
        wall: 0,
        topThickness: 0,
        clearance: 0,
        secondPart: { name: "吧唧后盖", normal: true },
        objectName: "吧唧前框",
      };
    } else if (shell) {
      const params = {
        ...SHELL_DEFAULTS,
        artW: widthMm,
        artH: heightMm,
        wall: shell.wall,
        depth: shell.depth,
        corner: shell.corner,
        clearance: shell.clearance,
      };
      shellInput = {
        body: buildShellMesh(params),
        modifier: buildTopSolidModifier(params),
        wall: params.wall,
        topThickness: params.topThickness,
        clearance: params.clearance,
      };
    }

    report(req.id, 86, "打包 3MF");
    const result = await build3mf({
      layers: plates,
      gridH,
      pixelSize,
      artWidthMm: widthMm,
      artHeightMm: heightMm,
      shell: shellInput,
      shellColorHex: shell?.colorHex,
      pictureName: req.pictureName,
    });

    report(req.id, 100, "完成");
    post(
      { type: "export", id: req.id, data: result.data, triangles: result.triangles, bytes: result.bytes },
      [result.data.buffer],
    );
  } catch (err) {
    post({
      type: "error",
      id: req.id,
      message: err instanceof Error ? err.message : String(err),
    });
  }
};
