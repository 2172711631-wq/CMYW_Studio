/**
 * 烘焙出来的立牌外壳数据是不是跟 CAD 母本同一辈。
 *
 * 网页端不跑 CadQuery，外壳是从 shell_master/ringframe_cadquery.py 烘成
 * web/public/standee/*.json 的**静态文件**。改了母本不重跑 tools/bake_standee.py，
 * 网站就照旧发旧模型 —— 而页脚那个构建代号只跟着代码走，JS 一变它就变，
 * 看起来像是更新了。
 *
 * 这个坑踩过一次：母本 09-08 改完（画片加大、压边加宽、Type-C 改高度、背板加厚），
 * 网站发的还是 09-04 烘的壳，照着它打了一整版才发现。发现的时候东西已经打出来了。
 *
 * 所以烘焙时把母本的源码指纹写进 JSON，这里比对。对不上就红在 CI 里，
 * 不用再靠人记得重跑。修法只有一条：`py -3.11 tools/bake_standee.py`。
 */

import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = join(import.meta.dirname, "..", "..");
const CAD = join(ROOT, "shell_master", "ringframe_cadquery.py");
const BAKED = join(ROOT, "web", "public", "standee");

function cadSha(): string {
  return createHash("sha256").update(readFileSync(CAD)).digest("hex").slice(0, 12);
}

describe("立牌烘焙数据与 CAD 母本同辈", () => {
  const files = readdirSync(BAKED).filter((f) => f.endsWith(".json"));

  it("有烘焙数据可比", () => {
    expect(files.length).toBeGreaterThan(0);
  });

  for (const f of files) {
    it(`${f} 是用当前母本烘的`, () => {
      const data = JSON.parse(readFileSync(join(BAKED, f), "utf8"));
      expect(
        data.cadSha,
        `${f} 没有母本指纹 —— 重跑 py -3.11 tools/bake_standee.py`,
      ).toBeTruthy();
      expect(
        data.cadSha,
        `${f} 是旧母本烘的，网站会发旧模型。重跑：py -3.11 tools/bake_standee.py`,
      ).toBe(cadSha());
    });
  }

  it("尺寸字段齐全 —— 网站按这些出画片，缺一个就出错图", () => {
    for (const f of files) {
      const d = JSON.parse(readFileSync(join(BAKED, f), "utf8"));
      for (const k of ["artPrintW", "artPrintH", "windowW", "windowH", "depth", "order", "bias"]) {
        expect(d[k], `${f} 缺 ${k}`).toBeDefined();
      }
      // 画片必须比取景窗大，否则压边压不住它 —— 实物上就是"卡不住、会掉"
      expect(d.artPrintW, `${f} 画片比窗还窄`).toBeGreaterThan(d.windowW);
      expect(d.artPrintH, `${f} 画片比窗还矮`).toBeGreaterThan(d.windowH);
    }
  });
});
