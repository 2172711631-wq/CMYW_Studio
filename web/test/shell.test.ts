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

  describe("Type-C 开孔", () => {
    const params = { ...SHELL_DEFAULTS, artW: 120, artH: 90 };
    const mesh = buildShellMesh(params);

    // 与 shell_master/shell_cadquery.py 的常量一致：名义 9.0×3.2 R1.6，
    // 加 FDM_TOL 0.2 与四周外扩 0.05，孔底抬到内腔底面之上 USB_LIFT_Z=1.55。
    const holeW = 9.0 + 0.2 + 2 * 0.05;
    const holeH = 3.2 + 0.2 + 2 * 0.05;
    const holeR = 1.6 + 0.05;
    const liftZ = 1.55;

    const cy = params.clearance + params.artH / 2;
    const cz = params.wall + liftZ + holeH / 2;

    /** 外壁 +X 面上、落在孔口包围盒内的顶点 —— 也就是洞口轮廓。 */
    const ring = (() => {
      const v = mesh.vertices;
      const faceX = params.clearance + params.artW + params.wall;
      const out: Array<[number, number]> = [];
      for (let i = 0; i < v.length; i += 3) {
        if (Math.abs(v[i] - faceX) > 1e-9) continue;
        const y = v[i + 1];
        const z = v[i + 2];
        if (Math.abs(y - cy) > holeW / 2 + 1e-6) continue;
        if (Math.abs(z - cz) > holeH / 2 + 1e-6) continue;
        out.push([y, z]);
      }
      return out;
    })();

    it("开在右外壁上，尺寸与抬高与母本一致", () => {
      expect(ring.length).toBeGreaterThan(0);
      const ys = ring.map(([y]) => y);
      const zs = ring.map(([, z]) => z);
      expect(Math.max(...ys) - Math.min(...ys)).toBeCloseTo(holeW, 6);
      expect(Math.max(...zs) - Math.min(...zs)).toBeCloseTo(holeH, 6);
      expect(Math.min(...zs)).toBeCloseTo(params.wall + liftZ, 6);
    });

    it("轮廓是 R1.65 圆角矩形，不是方口", () => {
      // 圆角矩形的有符号距离场：轮廓上的点应当处处为 0
      const sdf = (y: number, z: number) => {
        const dy = Math.abs(y - cy) - (holeW / 2 - holeR);
        const dz = Math.abs(z - cz) - (holeH / 2 - holeR);
        const outside = Math.hypot(Math.max(dy, 0), Math.max(dz, 0));
        return outside + Math.min(Math.max(dy, dz), 0) - holeR;
      };
      for (const [y, z] of ring) expect(Math.abs(sdf(y, z))).toBeLessThan(1e-6);

      // 方口会在包围盒四角各留一个顶点；圆角把它们让开约 0.41×R
      for (const cornerY of [cy - holeW / 2, cy + holeW / 2]) {
        for (const cornerZ of [cz - holeH / 2, cz + holeH / 2]) {
          const nearest = Math.min(
            ...ring.map(([y, z]) => Math.hypot(y - cornerY, z - cornerZ)),
          );
          expect(nearest).toBeGreaterThan(0.3);
        }
      }
    });

    it("是贯穿孔：内腔壁上有同一个洞口", () => {
      const v = mesh.vertices;
      const cavX = params.clearance + params.artW - params.wall * 0.5;
      let hits = 0;
      for (let i = 0; i < v.length; i += 3) {
        if (Math.abs(v[i] - cavX) > 1e-9) continue;
        if (Math.abs(v[i + 1] - cy) > holeW / 2 + 1e-6) continue;
        if (Math.abs(v[i + 2] - cz) > holeH / 2 + 1e-6) continue;
        hits += 1;
      }
      expect(hits).toBeGreaterThan(0);
    });
  });

  it("内腔过小时明确报错", () => {
    expect(() => buildShellMesh({ ...SHELL_DEFAULTS, artW: 8, artH: 8, wall: 8 })).toThrow();
  });

  it("深度不足时自动抬高到能容纳卡槽", () => {
    const m = buildShellMesh({ ...SHELL_DEFAULTS, artW: 120, artH: 90, depth: 5 });
    const b = bounds(m);
    expect(b.maxZ - b.minZ).toBeCloseTo(SHELL_DEFAULTS.wall + SHELL_DEFAULTS.artThickness + 4.0, 3);
  });
});
