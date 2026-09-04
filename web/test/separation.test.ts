/**
 * 分色引擎与 Python 版的逐像素一致性测试。
 * Pixel-exact parity between the TypeScript engine and the Python reference.
 *
 * 基准数据由 Python 侧生成（见 web/test/fixtures/README.md），内含重采样到
 * 打印网格后的 RGB 输入和四个通道的层数结果。喂同样的输入，就必须得到
 * 同样的输出——层数是整数，不存在「接近就行」。
 */

import { describe, expect, it } from "vitest";

import reference from "./fixtures/separation-reference.json";
import { maxStack, rintHalfToEven, separateCMYW } from "../src/engine/separate";

const { grid_w: gridW, grid_h: gridH, rgb, W, Y, M, C } = reference;

function countMismatches(actual: Int32Array, expected: number[]): number[] {
  const bad: number[] = [];
  for (let i = 0; i < expected.length; i += 1) {
    if (actual[i] !== expected[i]) bad.push(i);
  }
  return bad;
}

describe("rintHalfToEven", () => {
  it("匹配 NumPy 的银行家舍入 / matches NumPy half-to-even", () => {
    // 这些正是 Math.round 会答错的点
    expect(rintHalfToEven(0.5)).toBe(0);
    expect(rintHalfToEven(1.5)).toBe(2);
    expect(rintHalfToEven(2.5)).toBe(2);
    expect(rintHalfToEven(3.5)).toBe(4);
    expect(rintHalfToEven(-0.5)).toBe(0);
    expect(rintHalfToEven(-1.5)).toBe(-2);
    // 非边界值与常规舍入一致
    expect(rintHalfToEven(0.49)).toBe(0);
    expect(rintHalfToEven(0.51)).toBe(1);
    expect(rintHalfToEven(5.9)).toBe(6);
  });
});

describe("separateCMYW 与 Python 基准一致", () => {
  const result = separateCMYW(Uint8Array.from(rgb), gridW, gridH, {
    dither: reference.dither,
    profile: "v2",   // 这份基准钉的是 v2；v3 另有 separation-auto-reference
  });

  it("网格尺寸正确", () => {
    expect(result.gridW).toBe(gridW);
    expect(result.gridH).toBe(gridH);
    expect(result.C.length).toBe(gridW * gridH);
  });

  it("白底层数全为固定值", () => {
    expect(countMismatches(result.W, W)).toEqual([]);
  });

  for (const [name, actualKey, expected] of [
    ["青 Cyan", "C", C],
    ["品红 Magenta", "M", M],
    ["黄 Yellow", "Y", Y],
  ] as const) {
    it(`${name} 通道逐像素一致`, () => {
      const actual = result[actualKey];
      const bad = countMismatches(actual, expected);
      if (bad.length > 0) {
        const sample = bad.slice(0, 8).map((i) => {
          const p = i * 3;
          return `  [${i}] rgb=(${rgb[p]},${rgb[p + 1]},${rgb[p + 2]}) 期望=${expected[i]} 实得=${actual[i]}`;
        });
        throw new Error(
          `${bad.length}/${expected.length} 个像素不一致：\n${sample.join("\n")}`,
        );
      }
      expect(bad.length).toBe(0);
    });
  }

  it("总层数统计与基准一致", () => {
    const sum = (a: Int32Array) => a.reduce((t, v) => t + v, 0);
    expect(sum(result.C)).toBe(C.reduce((t: number, v: number) => t + v, 0));
    expect(sum(result.M)).toBe(M.reduce((t: number, v: number) => t + v, 0));
    expect(sum(result.Y)).toBe(Y.reduce((t: number, v: number) => t + v, 0));
  });

  it("最厚层数在合理范围", () => {
    const stack = maxStack(result);
    expect(stack).toBeGreaterThanOrEqual(4);
    expect(stack).toBeLessThanOrEqual(4 + 6 * 3);
  });
});

/**
 * 降低 keepFloor 是为了在插画上留住淡线，但门槛压在 need 上会被中性底顶穿。
 *
 * need = 这一色自己的彩色度 + kBack（三色平摊的中性成分）。一块饱和蓝里黄的
 * 彩色度正好是 0，全靠 kBack 顶过降下来的门槛，于是被抬成整整一层黄 —— 黄吸蓝，
 * 画面当场发绿。这就是"缩小到某个倍率预览就变色"的来源：取景缩小 → 白底占比变大
 * → 插画度上去 → 门槛降下来 → 蓝头发发绿。
 */
describe("抬浅层：只认自己的彩色度（v2 存档档案）", () => {
  const patch = (r: number, g: number, b: number) => {
    const rgb = new Uint8ClampedArray(4 * 3);
    for (let i = 0; i < 4; i += 1) { rgb[i * 3] = r; rgb[i * 3 + 1] = g; rgb[i * 3 + 2] = b; }
    return rgb;
  };
  const LOW = 0.32 * 0.224;   // 插画度 97% 时的门槛

  it("饱和蓝在低门槛下会被塞进一层黄（这就是发绿的原因）", () => {
    const bad = separateCMYW(patch(70, 115, 190), 2, 2, { dither: false, keepFloor: LOW, profile: "v2" });
    expect(bad.Y[0]).toBe(1);
  });

  it("只认彩色度之后，那层黄不再出现，青品原样保留", () => {
    const ok = separateCMYW(patch(70, 115, 190), 2, 2, {
      dither: false, keepFloor: LOW, liftChromaOnly: true, profile: "v2",
    });
    expect(ok.Y[0]).toBe(0);
    expect(ok.C[0]).toBeGreaterThan(0);
    expect(ok.M[0]).toBeGreaterThan(0);
  });

  // 已知没修干净的一块，钉在这儿免得以后当成新问题重查：
  // 三色墨的单层密度并不相等（c/m/y 是各自除以 DENSITY_C/M/Y 得来的），
  // 所以一块中性灰在层数这个单位下本来就不是三色等量 —— k = min(c,m,y) 扣完之后
  // 品红仍会剩一点。门槛降下来之后这点余量够得着，灰就会多一层品红、偏粉。
  // 这跟上面那层黄不是一回事：那层黄的彩色度是**精确的 0**，纯靠中性底顶上去，
  // 属于判据用错了量；这里的余量是真实存在的需求，只是 1 层的量化把它放大了。
  // 要治得动密度归一化，那是分色核心，不顺手改。
  it("中性灰仍会多一层品红 —— 这是墨密度不等，不是同一个毛病", () => {
    const opts = { dither: false, keepFloor: LOW, liftChromaOnly: true, profile: "v2" } as const;
    const grey = separateCMYW(patch(205, 205, 205), 2, 2, opts);
    expect([grey.C[0], grey.Y[0]]).toEqual([0, 0]);
    expect(grey.M[0]).toBe(1);
    // 默认门槛下够不着，所以只在插画档才看得见
    const dflt = separateCMYW(patch(205, 205, 205), 2, 2, { dither: false, profile: "v2" });
    expect([dflt.C[0], dflt.M[0], dflt.Y[0]]).toEqual([0, 0, 0]);
  });

  it("真正带彩色度的淡线照抬 —— 这条开关不能把淡线一起干掉", () => {
    const faint = patch(200, 226, 240);   // 很淡的青线
    const ok = separateCMYW(faint, 2, 2, {
      dither: false, keepFloor: LOW, liftChromaOnly: true, profile: "v2",
    });
    expect(ok.C[0]).toBeGreaterThan(0);
  });

  it("默认不开：Python 母本那条路一字未动", () => {
    const a = separateCMYW(patch(70, 115, 190), 2, 2, { dither: false, profile: "v2" });
    const b = separateCMYW(patch(70, 115, 190), 2, 2, { dither: false, liftChromaOnly: false, profile: "v2" });
    expect([a.C[0], a.M[0], a.Y[0]]).toEqual([b.C[0], b.M[0], b.Y[0]]);
  });
});

/**
 * v3：把 UCR 挪到光密度空间之后，浅色和中性色才对得上。
 *
 * v2 是先把白底吸收从每个通道扣掉、各自裁到 0，再在层数上取 min 当中性成分。
 * 两个后果都在实物上看得见：亮过 221/255 的通道一层墨都拿不到（浅粉、肉色、
 * 脸蛋红晕整段变纯白），而三色单层密度不等又让纯灰凭空长出色度（偏粉）。
 */
describe("v3 分色档案", () => {
  const px = (r: number, g: number, b: number) => {
    const a = new Uint8ClampedArray(4 * 3);
    for (let i = 0; i < 4; i += 1) { a[i * 3] = r; a[i * 3 + 1] = g; a[i * 3 + 2] = b; }
    return a;
  };
  const LOW = 0.32 * 0.224;
  const run = (c: Uint8ClampedArray, profile: "v2" | "v3") =>
    separateCMYW(c, 2, 2, { dither: false, keepFloor: LOW, liftChromaOnly: true, profile });

  it("浅粉在 v2 里整块消失，v3 留得住", () => {
    const pink = px(252, 230, 235);
    const v2 = run(pink, "v2");
    expect([v2.C[0], v2.M[0], v2.Y[0]]).toEqual([0, 0, 0]);   // 纯白，红晕没了
    const v3 = run(pink, "v3");
    expect(v3.C[0] + v3.M[0] + v3.Y[0]).toBeGreaterThan(0);
  });

  it("肉色在 v2 里只剩黄，v3 把品红补回来", () => {
    expect(run(px(252, 224, 205), "v2").M[0]).toBe(0);
    expect(run(px(252, 224, 205), "v3").M[0]).toBeGreaterThan(0);
  });

  it("中性灰不再凭空长出色度 —— v2 偏粉的根因", () => {
    for (const v of [120, 160, 205]) {
      const g = run(px(v, v, v), "v3");
      const set = new Set([g.C[0], g.M[0], g.Y[0]]);
      expect(set.size, `灰 ${v} 三色不等：C${g.C[0]} M${g.M[0]} Y${g.Y[0]}`).toBe(1);
    }
  });

  it("纯白和近白仍然一层墨都不上", () => {
    for (const c of [px(255, 255, 255), px(250, 250, 250)]) {
      const o = run(c, "v3");
      expect([o.C[0], o.M[0], o.Y[0]]).toEqual([0, 0, 0]);
    }
  });

  it("饱和色不受影响 —— 这次只该动浅色和中性色", () => {
    for (const c of [px(70, 115, 190), px(200, 60, 60)]) {
      const a = run(c, "v2");
      const b = run(c, "v3");
      expect(Math.abs(a.C[0] - b.C[0])).toBeLessThanOrEqual(1);
      expect(Math.abs(a.M[0] - b.M[0])).toBeLessThanOrEqual(1);
      expect(Math.abs(a.Y[0] - b.Y[0])).toBeLessThanOrEqual(1);
    }
  });
});
