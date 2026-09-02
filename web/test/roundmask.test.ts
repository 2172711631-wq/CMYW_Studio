/**
 * 圆形画片（吧唧）用的遮罩校验。
 *
 * 圆形不是另写的一条裁形路径，而是复用画片的圆角遮罩：
 * 正方形 + 圆角半径顶到边长的一半时，四个圆心正好收敛到中心，出来就是一个正圆。
 * 这里就是钉住这个等价关系 —— 它一旦不成立，吧唧的画片会悄悄变成圆角方片。
 */

import { describe, expect, it } from "vitest";

import { applyKeepMask, roundedCornerKeepMask } from "../src/engine/corner";

const D = 58; // 主流吧唧规格
const G = 290; // 0.2mm/px 下的网格

describe("圆形遮罩", () => {
  const mask = roundedCornerKeepMask(G, G, D, D / 2);

  it("半径顶到一半时才会生成遮罩", () => {
    expect(mask).not.toBeNull();
  });

  it("留下的是圆，不是圆角方片", () => {
    const m = mask!;
    const at = (x: number, y: number) => m[y * G + x];

    // 中心留下，四角切掉
    expect(at(G >> 1, G >> 1)).toBe(1);
    for (const [x, y] of [
      [0, 0],
      [G - 1, 0],
      [0, G - 1],
      [G - 1, G - 1],
    ]) {
      expect(at(x, y)).toBe(0);
    }

    // 四条边的中点必须留着 —— 圆角方片这里也会留，但下面的面积判据它过不了
    expect(at(G >> 1, 0)).toBe(1);
    expect(at(G >> 1, G - 1)).toBe(1);
    expect(at(0, G >> 1)).toBe(1);
    expect(at(G - 1, G >> 1)).toBe(1);

    // 圆占正方形的 π/4 ≈ 0.785。圆角方片会明显高于这个数
    let kept = 0;
    for (let i = 0; i < m.length; i += 1) kept += m[i];
    expect(kept / m.length).toBeGreaterThan(0.77);
    expect(kept / m.length).toBeLessThan(0.80);
  });

  it("每一行留下的宽度都对得上圆的弦长", () => {
    const m = mask!;
    const r = G / 2;
    for (const row of [G >> 3, G >> 2, G >> 1, (G * 3) >> 2]) {
      let run = 0;
      for (let x = 0; x < G; x += 1) run += m[row * G + x];
      const dy = row + 0.5 - r;
      const chord = 2 * Math.sqrt(Math.max(0, r * r - dy * dy));
      // 遮罩带闭运算和软边界，允许两三个像素的出入
      expect(Math.abs(run - chord)).toBeLessThan(4);
    }
  });

  it("遮罩把四个通道一起清零", () => {
    const m = mask!;
    const mk = () => Int32Array.from({ length: G * G }, () => 4);
    const [w, c, mm, y] = [mk(), mk(), mk(), mk()];
    applyKeepMask(m, w, c, mm, y);
    const corner = 0;
    expect([w[corner], c[corner], mm[corner], y[corner]]).toEqual([0, 0, 0, 0]);
    const centre = (G >> 1) * G + (G >> 1);
    expect([w[centre], c[centre], mm[centre], y[centre]]).toEqual([4, 4, 4, 4]);
  });
});
