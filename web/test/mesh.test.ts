/**
 * 网格化环节与 Python 基准的一致性测试。
 * Parity for the meshing stage: median filter, corner mask, rectangle merge.
 */

import { describe, expect, it } from "vitest";

import reference from "./fixtures/mesh-reference.json";
import { meshMergeFilter, mergeVoxelRectangles } from "../src/engine/voxel";
import { applyKeepMask, roundedCornerKeepMask } from "../src/engine/corner";

const {
  grid_w: gridW,
  grid_h: gridH,
  layers_C: layersC,
  median_C: medianC,
  z_start_C: zStartC,
  corner_width_mm: cornerWidthMm,
  corner_radius_mm: cornerRadiusMm,
  corner_masked_C: cornerMaskedC,
  rects,
} = reference;

function firstMismatch(actual: Int32Array, expected: number[]): string | null {
  for (let i = 0; i < expected.length; i += 1) {
    if (actual[i] !== expected[i]) {
      const y = Math.floor(i / gridW);
      const x = i - y * gridW;
      return `索引 ${i} (x=${x}, y=${y}) 期望 ${expected[i]}，实得 ${actual[i]}`;
    }
  }
  return null;
}

describe("meshMergeFilter 对齐 scipy.ndimage.median_filter", () => {
  it("3×3 中值结果逐像素一致（含 reflect 边界）", () => {
    const out = meshMergeFilter(Int32Array.from(layersC), gridW, gridH, 3);
    expect(firstMismatch(out, medianC)).toBeNull();
  });

  it("零值保持为零", () => {
    const out = meshMergeFilter(Int32Array.from(layersC), gridW, gridH, 3);
    for (let i = 0; i < layersC.length; i += 1) {
      if (layersC[i] <= 0) expect(out[i]).toBe(0);
    }
  });
});

describe("roundedCornerKeepMask 对齐 apply_rounded_corner_mask", () => {
  it("圆角切除结果逐像素一致", () => {
    const layer = Int32Array.from(layersC);
    const mask = roundedCornerKeepMask(gridW, gridH, cornerWidthMm, cornerRadiusMm);
    expect(mask).not.toBeNull();
    applyKeepMask(mask, layer);
    expect(firstMismatch(layer, cornerMaskedC)).toBeNull();
  });

  it("直角时返回 null，不做任何切除", () => {
    expect(roundedCornerKeepMask(gridW, gridH, cornerWidthMm, 0)).toBeNull();
  });
});

describe("mergeVoxelRectangles 对齐 merge_voxel_rectangles", () => {
  const out = mergeVoxelRectangles(
    meshMergeFilter(Int32Array.from(layersC), gridW, gridH, 3),
    Int32Array.from(zStartC),
    gridW,
    gridH,
    0.08,
  );

  it("矩形数量一致", () => {
    expect(out.length).toBe(rects.length);
  });

  it("每个矩形的坐标与 Z 范围一致", () => {
    for (let i = 0; i < rects.length; i += 1) {
      const [x0, x1, y0, y1, z0, z1] = rects[i];
      const r = out[i];
      const same =
        r.x0 === x0 && r.x1 === x1 && r.y0 === y0 && r.y1 === y1 &&
        Math.abs(r.z0 - z0) < 1e-6 && Math.abs(r.z1 - z1) < 1e-6;
      if (!same) {
        throw new Error(
          `矩形 ${i} 不一致：期望 [${x0},${x1},${y0},${y1},${z0},${z1}]，` +
            `实得 [${r.x0},${r.x1},${r.y0},${r.y1},${r.z0},${r.z1}]`,
        );
      }
    }
  });

  it("覆盖的像素数等于非零像素数（不重不漏）", () => {
    const med = meshMergeFilter(Int32Array.from(layersC), gridW, gridH, 3);
    let nonZero = 0;
    for (let i = 0; i < med.length; i += 1) if (med[i] > 0) nonZero += 1;
    const covered = out.reduce((t, r) => t + (r.x1 - r.x0) * (r.y1 - r.y0), 0);
    expect(covered).toBe(nonZero);
  });
});
