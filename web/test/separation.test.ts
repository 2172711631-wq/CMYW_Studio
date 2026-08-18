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
