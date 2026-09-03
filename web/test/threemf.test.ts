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

/**
 * 吧唧外壳复用外壳那条通道，但第二个部件必须是**普通件**而不是修改器。
 * 挂成 modifier_part 的话切片器会把后盖当成一块只改参数的虚体、根本不打出来，
 * 而且切片预览里前框照样在，很容易带着上机才发现。
 */
describe("build3mf（吧唧外壳）", () => {
  it("第二个部件是普通件，名字也跟着换", async () => {
    const med = meshMergeFilter(Int32Array.from(layersC), gridW, gridH, 3);
    const rects = mergeVoxelRectangles(med, Int32Array.from(zStartC), gridW, gridH, 0.08);
    const params = { ...SHELL_DEFAULTS, artW: 58, artH: 58 };
    const res = await build3mf({
      layers: [{ partId: 1, name: "1_Cyan", extruder: 1, rects }],
      gridH,
      pixelSize: 58 / gridW,
      artWidthMm: 58,
      artHeightMm: 58,
      shell: {
        body: buildShellMesh(params),
        modifier: buildTopSolidModifier(params),
        wall: 0,
        topThickness: 0,
        clearance: 0,
        secondPart: { name: "吧唧后盖", normal: true },
        objectName: "吧唧前框",
      },
      shellColorHex: "#000000",
      pictureName: "badge",
    });
    const cfg = text(readZip(res.data), "Metadata/model_settings.config");
    expect(cfg).toContain("吧唧前框");
    expect(cfg).toContain("吧唧后盖");
    expect(cfg).not.toContain("modifier_part");
    // 修改器专用的 100% 填充也不该跟到后盖上
    expect(cfg).not.toContain('key="sparse_infill_density"');
  });

  it("灯箱那条路没被改坏：第二个部件仍然是修改器", async () => {
    const cfg = text(readZip((await buildFixture(true)).data), "Metadata/model_settings.config");
    expect(cfg).toContain("modifier_part");
    expect(cfg).toContain("Lightbox_Shell_Box");
  });
});

/**
 * 立牌是四件一盘 —— 「一盘画一盘框」全靠这个：四件必须落在同一个对象、同一个盘上，
 * 而且都得是实体件。任何一件掉出去，用户拿到的就是缺零件的壳。
 */
describe("build3mf（立牌外壳：四件一盘）", () => {
  const shift = (m: { vertices: Float64Array; indices: Uint32Array }, dx: number) => {
    const v = Float64Array.from(m.vertices);
    for (let i = 0; i < v.length; i += 3) v[i] += dx;
    return { vertices: v, indices: m.indices };
  };

  const buildStandee = async () => {
    const med = meshMergeFilter(Int32Array.from(layersC), gridW, gridH, 3);
    const rects = mergeVoxelRectangles(med, Int32Array.from(zStartC), gridW, gridH, 0.08);
    const params = { ...SHELL_DEFAULTS, artW: 100, artH: 150 };
    const body = buildShellMesh(params);
    return build3mf({
      layers: [{ partId: 1, name: "1_Cyan", extruder: 1, rects }],
      gridH,
      pixelSize: 100 / gridW,
      artWidthMm: 100,
      artHeightMm: 150,
      shell: {
        body,
        modifier: shift(body, 40),
        wall: 0,
        topThickness: 0,
        clearance: 0,
        secondPart: { name: "灯板托盘", normal: true },
        objectName: "立牌前框",
        extraParts: [
          { name: "底座", mesh: shift(body, 80) },
          { name: "底盖", mesh: shift(body, 120) },
        ],
        plateName: "立牌外壳建议0.2mm层高打印",
      },
      shellColorHex: "#000000",
      pictureName: "standee",
    });
  };

  it("四件全在，且都是实体件", async () => {
    const cfg = text(readZip((await buildStandee()).data), "Metadata/model_settings.config");
    for (const n of ["立牌前框", "灯板托盘", "底座", "底盖"]) expect(cfg).toContain(n);
    expect(cfg.match(/subtype="normal_part"/g)?.length).toBeGreaterThanOrEqual(4);
    expect(cfg).not.toContain("modifier_part");
  });

  it("四件是四个独立对象，同在第二个盘 —— 一盘画一盘框", async () => {
    const zip = readZip((await buildStandee()).data);
    const cfg = text(zip, "Metadata/model_settings.config");
    // 盘还是两个：画片一盘、外壳一盘
    expect(cfg.match(/key="plater_id"/g)?.length).toBe(2);
    expect(cfg).toContain("立牌外壳建议0.2mm层高打印");
    // 但第二个盘上绑着四个对象实例 —— 合成一个对象的话，切片器里选不中单件、
    // 挪不动，尺寸还按整组算，一靠近屏蔽区就报碰撞
    const plate2 = cfg.slice(cfg.indexOf('key="plater_id" value="2"'));
    expect(plate2.match(/<model_instance>/g)?.length).toBe(4);
    // 四个对象各有各的 id 和 build item
    const model = text(zip, "3D/3dmodel.model");
    expect(model.match(/<item objectid=/g)?.length).toBe(5); // 画片 1 + 外壳 4
    const obj2 = text(zip, "3D/Objects/object_2.model");
    expect(obj2.match(/<object /g)?.length).toBe(4);
  });

  it("四件之间的相对摆位没丢 —— 各对象的 transform 不能都一样", async () => {
    const model = text(readZip((await buildStandee()).data), "3D/3dmodel.model");
    const xs = [...model.matchAll(/<item objectid="1\d"[^>]*?transform="([^"]+)"/g)]
      .map((m) => Number(m[1].trim().split(/\s+/)[9]));
    expect(xs.length).toBe(4);
    expect(new Set(xs).size).toBeGreaterThan(1);
  });

  it("包围盒是四件的并集，整组在盘上居中", async () => {
    const zip = readZip((await buildStandee()).data);
    const plate = JSON.parse(text(zip, "Metadata/plate_2.json")) as {
      bbox_all: [number, number, number, number];
    };
    const [x0, y0, x1, y1] = plate.bbox_all;
    // 只按前框算的话宽度会缩到 ~107；并集必须把挪到 +120 的底盖也框进去
    expect(x1 - x0).toBeGreaterThan(120);
    // 整组要放得下一个盘
    expect(x1 - x0).toBeLessThanOrEqual(256);
    expect(y1 - y0).toBeLessThanOrEqual(256);
    // 第二个盘摆在 x=440 那一列（沿用灯箱的摆位），整组该落在它的中心
    expect((x0 + x1) / 2).toBeCloseTo(440, 1);
    expect((y0 + y1) / 2).toBeCloseTo(128, 1);
  });
});
