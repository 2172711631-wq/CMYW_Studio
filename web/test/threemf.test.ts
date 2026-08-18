/**
 * 3MF 包结构校验。
 * Structural validation of the generated Bambu project 3MF.
 *
 * 用 Node 自带的 zlib 把包解开，逐项检查 Bambu Studio 打开时依赖的东西：
 * 必需文件、双盘、AMS 槽位、层高、部件 ID。ZIP 本身写坏或少一个 config，
 * 表现都是「切片软件打不开」，而那时已经没法从产物反推原因了。
 */

import { inflateRawSync } from "node:zlib";
import { describe, expect, it } from "vitest";

import reference from "./fixtures/mesh-reference.json";
import { build3mf } from "../src/engine/threemf";
import { meshMergeFilter, mergeVoxelRectangles } from "../src/engine/voxel";
import { SHELL_DEFAULTS, buildShellMesh, buildTopSolidModifier } from "../src/engine/shell";

const { grid_w: gridW, grid_h: gridH, layers_C: layersC, z_start_C: zStartC } = reference;

/** 极简 ZIP 读取器：够用来验证我们自己写出来的包。 */
function readZip(buf: Uint8Array): Map<string, Uint8Array> {
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const out = new Map<string, Uint8Array>();

  // 从尾部找中央目录结束记录
  let eocd = -1;
  for (let i = buf.length - 22; i >= 0; i -= 1) {
    if (view.getUint32(i, true) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new Error("找不到 ZIP 中央目录结束记录 / no EOCD");

  const count = view.getUint16(eocd + 10, true);
  let p = view.getUint32(eocd + 16, true);

  for (let i = 0; i < count; i += 1) {
    if (view.getUint32(p, true) !== 0x02014b50) throw new Error("中央目录项签名错误");
    const method = view.getUint16(p + 10, true);
    const compSize = view.getUint32(p + 20, true);
    const nameLen = view.getUint16(p + 28, true);
    const extraLen = view.getUint16(p + 30, true);
    const commentLen = view.getUint16(p + 32, true);
    const localOffset = view.getUint32(p + 42, true);
    const name = new TextDecoder().decode(buf.subarray(p + 46, p + 46 + nameLen));

    // 跳到本地头，取出数据
    const lNameLen = view.getUint16(localOffset + 26, true);
    const lExtraLen = view.getUint16(localOffset + 28, true);
    const dataStart = localOffset + 30 + lNameLen + lExtraLen;
    const raw = buf.subarray(dataStart, dataStart + compSize);
    out.set(name, method === 8 ? new Uint8Array(inflateRawSync(raw)) : raw);

    p += 46 + nameLen + extraLen + commentLen;
  }
  return out;
}

const text = (files: Map<string, Uint8Array>, name: string) => {
  const d = files.get(name);
  if (!d) throw new Error(`包内缺少 ${name}`);
  return new TextDecoder().decode(d);
};

async function buildFixture(withShell: boolean) {
  const med = meshMergeFilter(Int32Array.from(layersC), gridW, gridH, 3);
  const rects = mergeVoxelRectangles(med, Int32Array.from(zStartC), gridW, gridH, 0.08);
  const artW = 100;
  const pixelSize = artW / gridW;
  const artH = pixelSize * gridH;
  const params = { ...SHELL_DEFAULTS, artW, artH };

  return build3mf({
    // 用同一份几何填四个颜色件，结构校验不关心颜色差异
    layers: [
      { partId: 1, name: "1_Cyan", extruder: 1, rects },
      { partId: 2, name: "2_Magenta", extruder: 2, rects },
      { partId: 3, name: "3_Yellow", extruder: 3, rects },
      { partId: 4, name: "4_White", extruder: 4, rects },
    ],
    gridH,
    pixelSize,
    artWidthMm: artW,
    artHeightMm: artH,
    shell: withShell
      ? {
          body: buildShellMesh(params),
          modifier: buildTopSolidModifier(params),
          wall: params.wall,
          topThickness: params.topThickness,
          clearance: params.clearance,
        }
      : null,
    shellColorHex: "#000000",
    pictureName: "测试画片",
  });
}

describe("build3mf（含外壳）", () => {
  it("产出可解析的 ZIP，且必需文件齐全", async () => {
    const result = await buildFixture(true);
    expect(result.bytes).toBeGreaterThan(1000);

    const files = readZip(result.data);
    for (const required of [
      "[Content_Types].xml",
      "_rels/.rels",
      "3D/3dmodel.model",
      "3D/_rels/3dmodel.model.rels",
      "3D/Objects/object_1.model",
      "3D/Objects/object_2.model",
      "Metadata/project_settings.config",
      "Metadata/model_settings.config",
      "Metadata/slice_info.config",
      "Metadata/plate_1.json",
      "Metadata/plate_2.json",
    ]) {
      expect(files.has(required), `缺少 ${required}`).toBe(true);
    }
  });

  it("两个盘、两个 build item", async () => {
    const files = readZip((await buildFixture(true)).data);
    const model = text(files, "3D/3dmodel.model");
    expect((model.match(/<item /g) ?? []).length).toBe(2);
    const cfg = text(files, "Metadata/model_settings.config");
    expect((cfg.match(/<plate>/g) ?? []).length).toBe(2);
  });

  it("AMS 槽位 1–5 分配正确，层高 0.08", async () => {
    const files = readZip((await buildFixture(true)).data);
    const cfg = text(files, "Metadata/model_settings.config");
    const extruders = [...cfg.matchAll(/key="extruder" value="(\d+)"/g)].map((m) => m[1]);
    expect(new Set(extruders)).toEqual(new Set(["1", "2", "3", "4", "5"]));

    const settings = JSON.parse(text(files, "Metadata/project_settings.config"));
    expect(settings.layer_height).toBe("0.08");
    expect(settings.filament_colour).toEqual(["#0086D6", "#EC008C", "#F4EE2A", "#FFFFFF", "#000000"]);
    expect(settings.sparse_infill_density).toBe("100%");
    expect(settings.enable_prime_tower).toBe("1");
  });

  it("外壳部件 ID 避开画片的 1–4", async () => {
    const files = readZip((await buildFixture(true)).data);
    const obj2 = text(files, "3D/Objects/object_2.model");
    const ids = [...obj2.matchAll(/<object id="(\d+)"/g)].map((m) => Number(m[1]));
    expect(ids).toEqual([101, 102]);
    for (const id of ids) expect(id).toBeGreaterThan(4);
  });

  it("顶壁 modifier 标记为 100% 填充", async () => {
    const files = readZip((await buildFixture(true)).data);
    const cfg = text(files, "Metadata/model_settings.config");
    expect(cfg).toContain('subtype="modifier_part"');
    expect(cfg).toContain('key="sparse_infill_density" value="100%"');
  });

  it("画片盘的包围盒落在 256mm 热床内", async () => {
    const files = readZip((await buildFixture(true)).data);
    const plate = JSON.parse(text(files, "Metadata/plate_1.json"));
    const [x0, y0, x1, y1] = plate.bbox_all;
    expect(x0).toBeGreaterThanOrEqual(0);
    expect(y0).toBeGreaterThanOrEqual(0);
    expect(x1).toBeLessThanOrEqual(256);
    expect(y1).toBeLessThanOrEqual(256);
  });
});

describe("build3mf（仅画片）", () => {
  it("不含外壳时只有一个盘，四个槽位", async () => {
    const files = readZip((await buildFixture(false)).data);
    expect(files.has("3D/Objects/object_2.model")).toBe(false);
    expect(files.has("Metadata/plate_2.json")).toBe(false);
    const model = text(files, "3D/3dmodel.model");
    expect((model.match(/<item /g) ?? []).length).toBe(1);
    const settings = JSON.parse(text(files, "Metadata/project_settings.config"));
    expect(settings.filament_colour).toHaveLength(4);
  });
});
