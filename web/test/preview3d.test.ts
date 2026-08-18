/**
 * 立体预览的几何。
 *
 * 这块没有基准数据可比 —— 它不参与打印，也就没有 Python 对照版。
 * 但薄板一旦有破口，在页面上就是「能看穿的画片」，而且只在某个角度出现，
 * 靠肉眼很难稳定复现。所以这里按封闭性来验：每条边必须被正反各用一次。
 */

import { describe, expect, it } from "vitest";
import { buildPanel, roundedRectPoly } from "../src/engine/preview3d";

const KEY = (x: number, y: number, z: number) =>
  `${x.toFixed(5)},${y.toFixed(5)},${z.toFixed(5)}`;

describe("roundedRectPoly", () => {
  it("stays inside the bounding box", () => {
    for (const [x0, y0, x1, y1, r] of [
      [0, 0, 100, 75, 5],
      [0.2, 0.2, 90.2, 120.2, 12],
      [0, 0, 60, 60, 0],
      [0, 0, 40, 40, 999], // 圆角大于半边，要被夹住而不是翻出去
    ]) {
      for (const [x, y] of roundedRectPoly(x0, y0, x1, y1, r)) {
        expect(x).toBeGreaterThanOrEqual(x0 - 1e-9);
        expect(x).toBeLessThanOrEqual(x1 + 1e-9);
        expect(y).toBeGreaterThanOrEqual(y0 - 1e-9);
        expect(y).toBeLessThanOrEqual(y1 + 1e-9);
      }
    }
  });

  it("keeps counter-clockwise winding", () => {
    const poly = roundedRectPoly(0, 0, 100, 75, 5);
    let area2 = 0;
    for (let i = 0; i < poly.length; i += 1) {
      const a = poly[i];
      const b = poly[(i + 1) % poly.length];
      area2 += a[0] * b[1] - b[0] * a[1];
    }
    expect(area2).toBeGreaterThan(0);
  });
});

describe("buildPanel", () => {
  const panel = buildPanel(0.2, 0.2, 135.2, 101.2, 18, 16.5, 5);

  it("is a closed surface", () => {
    const edges = new Map<string, number>();
    const { pos, count } = panel;
    for (let t = 0; t < count; t += 3) {
      for (let e = 0; e < 3; e += 1) {
        const a = (t + e) * 3;
        const b = (t + ((e + 1) % 3)) * 3;
        const ka = KEY(pos[a], pos[a + 1], pos[a + 2]);
        const kb = KEY(pos[b], pos[b + 1], pos[b + 2]);
        // 有向边计数：闭合网格里每条边的两个方向必须各出现一次
        edges.set(`${ka}|${kb}`, (edges.get(`${ka}|${kb}`) ?? 0) + 1);
      }
    }
    const unbalanced = [...edges].filter(([k, n]) => {
      const [a, b] = k.split("|");
      return n !== (edges.get(`${b}|${a}`) ?? 0);
    });
    expect(unbalanced).toEqual([]);
  });

  it("keeps every UV inside the texture", () => {
    for (const v of panel.uv) {
      expect(v).toBeGreaterThanOrEqual(-1e-9);
      expect(v).toBeLessThanOrEqual(1 + 1e-9);
    }
  });

  it("puts the texture's first row along the top edge", () => {
    // ImageData 第 0 行是图的顶边，模型里 +Y 朝上 —— v 必须翻过来，
    // 否则整张画片上下颠倒，而且颠倒得很自然，不盯着看根本发现不了。
    const { pos, uv, count } = panel;
    let topV = Number.POSITIVE_INFINITY;
    let bottomV = Number.NEGATIVE_INFINITY;
    for (let i = 0; i < count; i += 1) {
      if (pos[i * 3 + 1] > 101.0) topV = Math.min(topV, uv[i * 2 + 1]);
      if (pos[i * 3 + 1] < 0.3) bottomV = Math.max(bottomV, uv[i * 2 + 1]);
    }
    expect(topV).toBeCloseTo(0, 5);
    expect(bottomV).toBeCloseTo(1, 5);
  });

  it("faces the front face toward +Z", () => {
    const { pos, nrm, count } = panel;
    let front = 0;
    for (let i = 0; i < count; i += 1) {
      if (nrm[i * 3 + 2] > 0.5) {
        expect(pos[i * 3 + 2]).toBeCloseTo(18, 6);
        front += 1;
      }
    }
    expect(front).toBeGreaterThan(0);
  });
});
