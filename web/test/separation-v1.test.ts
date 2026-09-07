/**
 * v1 分色的逐像素对拍。
 *
 * v1 现在是默认档，两边引擎各写了一份实现 —— 没有对拍就一定会分叉，
 * 而且分叉不会报错，只会让同一张图在桌面 App 和网站上出两张不一样的画片。
 *
 * 它是最简单的一条路，也正因为简单最容易被"顺手优化"改掉：抬浅层的门槛、
 * 白底扣减的位置、取整方式，任何一处改动都会在这里立刻炸出来。
 */

import { describe, expect, it } from "vitest";

import reference from "./fixtures/separation-v1-reference.json";
import { separateCMYW } from "../src/engine/separate";

const { grid_w: gridW, grid_h: gridH, rgb, W, Y, M, C } = reference;

describe("v1 与 Python 基准一致", () => {
  const result = separateCMYW(Uint8Array.from(rgb), gridW, gridH, {
    dither: reference.dither,
    profile: "v1",
  });

  it("这份基准钉的确实是 v1", () => {
    expect(reference.profile).toBe("v1");
  });

  it("白底层数全为固定值", () => {
    expect([...result.W].filter((v, i) => v !== W[i]).length).toBe(0);
  });

  for (const [name, key, expected] of [
    ["青 Cyan", "C", C],
    ["品红 Magenta", "M", M],
    ["黄 Yellow", "Y", Y],
  ] as const) {
    it(`${name} 通道逐像素一致`, () => {
      const actual = result[key];
      const bad: number[] = [];
      for (let i = 0; i < expected.length; i += 1) if (actual[i] !== expected[i]) bad.push(i);
      if (bad.length > 0) {
        const i = bad[0];
        const p = i * 3;
        throw new Error(
          `${name} 有 ${bad.length} 格对不上，第一处在 ${i}：`
          + `rgb=(${rgb[p]},${rgb[p + 1]},${rgb[p + 2]}) 期望 ${expected[i]} 实得 ${actual[i]}`,
        );
      }
      expect(bad.length).toBe(0);
    });
  }

  it("默认档就是 v1 —— 不传 profile 也要走同一条路", () => {
    const dflt = separateCMYW(Uint8Array.from(rgb), gridW, gridH, { dither: reference.dither });
    expect([...dflt.C].filter((v, i) => v !== C[i]).length).toBe(0);
    expect([...dflt.M].filter((v, i) => v !== M[i]).length).toBe(0);
    expect([...dflt.Y].filter((v, i) => v !== Y[i]).length).toBe(0);
  });
});
