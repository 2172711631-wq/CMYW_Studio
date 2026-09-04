/**
 * 自动取值的跨语言一致性。
 *
 * 引擎的默认参数由 separation.test.ts 钉着；这里钉的是默认路径根本走不到的两件事：
 *
 *  1. **选参数的公式。** 它在 web/src/engine/autotune.ts 和 main.py 各有一份。
 *     分叉了不会报错，只会让同一张图在桌面 App 和网站上出两张不一样的画片 ——
 *     等有人发现颜色不对时，已经打废好几版了。
 *  2. **liftChromaOnly 那条分支下引擎的输出。** 它只在门槛降下来之后才生效，
 *     默认参数永远走不到；而它恰好是最容易跑偏的地方（饱和色里多一层无关的墨）。
 *
 * 基准由 py -3.11 tools/make_fixtures.py 生成。
 */

import { describe, expect, it } from "vitest";

import auto from "./fixtures/separation-auto-reference.json";
import reference from "./fixtures/separation-reference.json";
import {
  artScore, ditherAmountFor, flatnessOf, keepFloorFor,
  liftChromaOnlyFor, mergeFilterFor, mmPerPxFor,
} from "../src/engine/autotune";
import { separateCMYW } from "../src/engine/separate";

const rgb = Uint8ClampedArray.from(reference.rgb);

describe("自动取值：与 Python 侧同一套判据", () => {
  it("平坦度：同一个数组量出同一个数", () => {
    expect(flatnessOf(rgb, auto.grid_w, auto.grid_h)).toBeCloseTo(auto.flatness_of_grid, 12);
  });

  it("整条曲线逐点对得上，包括两端阈值", () => {
    for (const row of auto.curve) {
      const f = row.flatness;
      expect(artScore(f), `art_score @ ${f}`).toBeCloseTo(row.art_score, 12);
      expect(ditherAmountFor(f), `dither @ ${f}`).toBeCloseTo(row.dither_amount, 12);
      expect(keepFloorFor(f), `keep_floor @ ${f}`).toBeCloseTo(row.keep_floor, 12);
      expect(liftChromaOnlyFor(f), `lift @ ${f}`).toBe(row.lift_chroma_only);
      expect(mergeFilterFor(f), `filter @ ${f}`).toBe(row.merge_filter);
      expect(mmPerPxFor(f), `mm/px @ ${f}`).toBeCloseTo(row.mm_per_px, 12);
    }
  });

  it("曲线确实覆盖了照片档和插画档两头", () => {
    const lifts = auto.curve.map((r) => r.lift_chroma_only);
    expect(lifts).toContain(true);
    expect(lifts).toContain(false);
    const filters = new Set(auto.curve.map((r) => r.merge_filter));
    expect(filters.size).toBeGreaterThan(1);
  });

  it("插画档参数下，引擎逐像素一致", () => {
    const t = auto.tuned;
    const layers = separateCMYW(rgb, auto.grid_w, auto.grid_h, {
      dither: t.dither_amount > 0,
      ditherAmount: t.dither_amount,
      keepFloor: t.keep_floor,
      liftChromaOnly: t.lift_chroma_only,
    });
    expect(t.lift_chroma_only, "基准没走到 liftChromaOnly，这个用例等于没测").toBe(true);
    for (const key of ["W", "Y", "M", "C"] as const) {
      const got = layers[key];
      const want = auto[key];
      let diff = 0;
      let first = -1;
      for (let i = 0; i < want.length; i += 1) {
        if (got[i] !== want[i]) {
          diff += 1;
          if (first < 0) first = i;
        }
      }
      expect(
        diff,
        diff ? `${key} 有 ${diff} 个格子对不上，第一个在 ${first}：TS ${got[first]} vs PY ${want[first]}` : "",
      ).toBe(0);
    }
  });
});
