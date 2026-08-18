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
): LayerSet {
  const layers = separateCMYW(rgb, gridW, gridH, { dither: true });
  const mask = roundedCornerKeepMask(gridW, gridH, widthMm, cornerRadiusMm);
  if (mask) applyKeepMask(mask, layers.W, layers.Y, layers.M, layers.C);
  return layers;
}

self.onmessage = async (event: MessageEvent<WorkerRequest>) => {
  const req = event.data;
  try {
    if (req.type === "preview") {
      report(req.id, 15, "分色中");
      const layers = separateWithCorner(
        req.rgb, req.gridW, req.gridH, req.widthMm, req.cornerRadiusMm,
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
    const cornerRadius = shell ? shell.corner : 0;
    const layers = separateWithCorner(req.rgb, gridW, gridH, widthMm, cornerRadius);

    report(req.id, 30, "平滑层高");
    const filtered = {
      W: meshMergeFilter(layers.W, gridW, gridH, MESH_MERGE_FILTER),
      Y: meshMergeFilter(layers.Y, gridW, gridH, MESH_MERGE_FILTER),
      M: meshMergeFilter(layers.M, gridW, gridH, MESH_MERGE_FILTER),
      C: meshMergeFilter(layers.C, gridW, gridH, MESH_MERGE_FILTER),
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

    report(req.id, 72, shell ? "生成外壳" : "组装 3MF");
    let shellInput = null;
    if (shell) {
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
