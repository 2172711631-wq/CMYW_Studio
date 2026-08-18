/**
 * 外壳网格几何校验。
 * Shell mesh geometry checks — dimensions, watertightness, orientation.
 *
 * 手工构造的网格没有 CAD 内核兜底，水密性必须自己验：
 * 每条无向边恰好被两个三角形共用，且方向相反（一个 a→b，一个 b→a）。
 * 不满足就是有洞或有重面，切片时会出现莫名其妙的缺口。
 */

import { describe, expect, it } from "vitest";

import { SHELL_DEFAULTS, buildShellMesh, shellXYBounds, type Mesh } from "../src/engine/shell";

function bounds(mesh: Mesh) {
  const v = mesh.vertices;
  let minX = Infinity, minY = Infinity, minZ = Infinity;
  let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
  for (let i = 0; i < v.length; i += 3) {
    minX = Math.min(minX, v[i]); maxX = Math.max(maxX, v[i]);
    minY = Math.min(minY, v[i + 1]); maxY = Math.max(maxY, v[i + 1]);
    minZ = Math.min(minZ, v[i + 2]); maxZ = Math.max(maxZ, v[i + 2]);
  }
  return { minX, minY, minZ, maxX, maxY, maxZ };
}

/**
 * 按坐标（而非索引）归并顶点后统计边的使用情况。
 * 构建过程中同一位置会被多次 addVertex，必须按位置去重才能判断拓扑。
 */
function edgeReport(mesh: Mesh) {
  const key = (i: number) => {
    const q = (x: number) => Math.round(x * 1e6) / 1e6;
    return `${q(mesh.vertices[i * 3])},${q(mesh.vertices[i * 3 + 1])},${q(mesh.vertices[i * 3 + 2])}`;
  };
  const edges = new Map<string, number>();
  const idx = mesh.indices;
  for (let t = 0; t < idx.length; t += 3) {
    const p = [key(idx[t]), key(idx[t + 1]), key(idx[t + 2])];
    for (let e = 0; e < 3; e += 1) {
      const a = p[e];
      const b = p[(e + 1) % 3];
      if (a === b) continue; // 退化边（直角时圆弧收缩成重合点）
      const undirected = a < b ? `${a}|${b}` : `${b}|${a}`;
      const dir = a < b ? 1 : -1;
      edges.set(undirected, (edges.get(undirected) ?? 0) + dir);
    }
  }
  let unbalanced = 0;
  for (const v of edges.values()) if (v !== 0) unbalanced += 1;
  return { total: edges.size, unbalanced };
}

const CASES = [
  { name: "120×90 默认", artW: 120, artH: 90 },
  { name: "135×135 方形", artW: 135, artH: 135 },
  { name: "200×150 大幅", artW: 200, artH: 150 },
];

describe("buildShellMesh", () => {
  for (const c of CASES) {
    describe(c.name, () => {
      const params = { ...SHELL_DEFAULTS, artW: c.artW, artH: c.artH };
      const mesh = buildShellMesh(params);

      it("生成了非空网格", () => {
        expect(mesh.indices.length).toBeGreaterThan(0);
        expect(mesh.indices.length % 3).toBe(0);
      });

      it("外廓尺寸符合设计规则", () => {
        const b = bounds(mesh);
        // 与 shell_master/verify_shell.py 的判据一致
        expect(b.maxX - b.minX).toBeCloseTo(c.artW + 2 * params.wall, 3);
        expect(b.maxY - b.minY).toBeCloseTo(c.artH + params.wall + params.topThickness, 3);
        expect(b.maxZ - b.minZ).toBeCloseTo(params.depth, 3);
      });

      it("外底面贴 Z=0", () => {
        expect(bounds(mesh).minZ).toBeCloseTo(0, 6);
      });

      it("XY 包围盒与摆盘函数一致", () => {
        const b = bounds(mesh);
        const xy = shellXYBounds(c.artW, c.artH, params.wall, params.topThickness, params.clearance);
        expect(b.minX).toBeCloseTo(xy.minX, 3);
        expect(b.minY).toBeCloseTo(xy.minY, 3);
        expect(b.maxX).toBeCloseTo(xy.maxX, 3);
        expect(b.maxY).toBeCloseTo(xy.maxY, 3);
      });

      it("水密：每条边方向配平", () => {
        const r = edgeReport(mesh);
        expect(r.total).toBeGreaterThan(0);
        if (r.unbalanced !== 0) {
          throw new Error(`${r.unbalanced}/${r.total} 条边未配平——网格有洞或有重面`);
        }
      });

      it("顶壁厚度不超过 3mm 硬限", () => {
        expect(params.topThickness).toBeLessThanOrEqual(3.0);
      });
    });
  }

  it("内腔过小时明确报错", () => {
    expect(() => buildShellMesh({ ...SHELL_DEFAULTS, artW: 8, artH: 8, wall: 8 })).toThrow();
  });

  it("深度不足时自动抬高到能容纳卡槽", () => {
    const m = buildShellMesh({ ...SHELL_DEFAULTS, artW: 120, artH: 90, depth: 5 });
    const b = bounds(m);
    expect(b.maxZ - b.minZ).toBeCloseTo(SHELL_DEFAULTS.wall + SHELL_DEFAULTS.artThickness + 4.0, 3);
  });
});
