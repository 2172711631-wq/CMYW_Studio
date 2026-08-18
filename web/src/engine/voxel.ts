/**
 * 层高图 → 可打印几何。
 * Layer-height fields → printable geometry.
 *
 * 两步都是为了减面：一个像素一个盒子在 240mm 画幅下是上百万三角面，
 * 切片软件会直接卡死。
 *
 *   1. 中值滤波把同层高像素连成片（不动分色结果，只平滑层高台阶）
 *   2. 贪心矩形合并把同高同起点的连续像素并成大方块
 *
 * 对应 Python 的 _mesh_merge_filter / merge_voxel_rectangles。
 */

import { LAYER_HEIGHT } from "./constants";

/**
 * scipy.ndimage 的 'reflect' 边界：(d c b a | a b c d | d c b a)
 * 即 -1 → 0，-2 → 1，n → n-1。注意这与 cv2 的 BORDER_REPLICATE 不同，
 * Python 侧装了 scipy 时走的正是这一支。
 */
function reflectIndex(i: number, n: number): number {
  if (n <= 1) return 0;
  let v = i;
  // 循环处理，兼容越界超过一个周期的情况
  while (v < 0 || v >= n) {
    if (v < 0) v = -v - 1;
    if (v >= n) v = 2 * n - v - 1;
  }
  return v;
}

/**
 * 3×3 中值滤波，零值保持为零（空洞仍是空洞）。
 * 对应 _mesh_merge_filter，与 scipy.ndimage.median_filter(size=3) 对齐。
 */
export function meshMergeFilter(
  layer: Int32Array,
  gridW: number,
  gridH: number,
  size = 3,
): Int32Array {
  let k = Math.trunc(size);
  if (k < 3 || layer.length === 0) return layer;
  if (k % 2 === 0) k += 1;

  const half = (k - 1) / 2;
  const out = new Int32Array(layer.length);
  const window = new Int32Array(k * k);
  const mid = (k * k - 1) >> 1;

  for (let y = 0; y < gridH; y += 1) {
    for (let x = 0; x < gridW; x += 1) {
      const idx = y * gridW + x;
      if (layer[idx] <= 0) {
        out[idx] = 0;
        continue;
      }
      let n = 0;
      for (let dy = -half; dy <= half; dy += 1) {
        const sy = reflectIndex(y + dy, gridH);
        for (let dx = -half; dx <= half; dx += 1) {
          const sx = reflectIndex(x + dx, gridW);
          window[n] = layer[sy * gridW + sx];
          n += 1;
        }
      }
      // 窗口很小，插入排序比通用排序快且无分配
      for (let i = 1; i < n; i += 1) {
        const v = window[i];
        let j = i - 1;
        while (j >= 0 && window[j] > v) {
          window[j + 1] = window[j];
          j -= 1;
        }
        window[j + 1] = v;
      }
      out[idx] = window[mid];
    }
  }
  return out;
}

/** 合并后的矩形：像素坐标 [x0,x1) × [y0,y1)，Z 用 mm。 */
export interface VoxelRect {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  z0: number;
  z1: number;
}

/**
 * 把层高相同、Z 起点相同的连续体素合并成大方块。
 * 对应 merge_voxel_rectangles。
 *
 * 先向右扩成一段，再把整段向下扩到不再均匀为止；每个结果矩形导出成
 * 一个 12 面的盒子。典型照片上能减面 10–50 倍。
 */
export function mergeVoxelRectangles(
  matrix: Int32Array,
  zStart: Int32Array,
  gridW: number,
  gridH: number,
  layerHeight = LAYER_HEIGHT,
): VoxelRect[] {
  const used = new Uint8Array(matrix.length);
  const rects: VoxelRect[] = [];

  for (let y = 0; y < gridH; y += 1) {
    let x = 0;
    while (x < gridW) {
      const base = y * gridW + x;
      if (used[base] === 1 || matrix[base] <= 0) {
        x += 1;
        continue;
      }

      const layers = matrix[base];
      const zs = zStart[base];

      // 向右扩
      let xEnd = x + 1;
      while (xEnd < gridW) {
        const i = y * gridW + xEnd;
        if (used[i] === 1 || matrix[i] !== layers || zStart[i] !== zs) break;
        xEnd += 1;
      }

      // 整段向下扩
      let yEnd = y + 1;
      outer: while (yEnd < gridH) {
        const row = yEnd * gridW;
        for (let i = x; i < xEnd; i += 1) {
          if (used[row + i] === 1 || matrix[row + i] !== layers || zStart[row + i] !== zs) {
            break outer;
          }
        }
        yEnd += 1;
      }

      for (let yy = y; yy < yEnd; yy += 1) {
        used.fill(1, yy * gridW + x, yy * gridW + xEnd);
      }

      rects.push({
        x0: x,
        x1: xEnd,
        y0: y,
        y1: yEnd,
        z0: zs * layerHeight,
        z1: (zs + layers) * layerHeight,
      });
      x = xEnd;
    }
  }
  return rects;
}

/** 矩形数 × 12 = 三角面数，用于给用户提示切片压力。 */
export function triangleCount(rects: VoxelRect[]): number {
  return rects.length * 12;
}
