/**
 * 制作台交互。
 * Studio page: pick a photo, see it lit, download a printable 3MF.
 *
 * 主线程只做三件事：把图重采样到打印网格、把参数丢给 Worker、把结果画出来。
 * 所有重活都在 worker 里，界面任何时候都不会卡。
 */

import "./site";
import {
  DEFAULT_MM_PER_PX,
  GRID_MAX,
  GRID_MIN,
  LAYER_DITHER_AMT,
  LAYER_KEEP_FLOOR,
  MESH_MERGE_FILTER,
} from "../engine/constants";
import { Preview3D, type Preview3DShell } from "../engine/preview3d";
import type { WorkerRequest, WorkerResponse } from "../worker/engine.worker";

/** 拓竹 PLA 常用色，作为外壳可选项。 */
const SHELL_COLOURS: ReadonlyArray<{ hex: string; zh: string; en: string }> = [
  { hex: "#FFFFFF", zh: "象牙白", en: "Ivory White" },
  { hex: "#000000", zh: "曜石黑", en: "Obsidian Black" },
  { hex: "#E8AFCF", zh: "哑光樱花粉", en: "Matte Sakura Pink" },
  { hex: "#F4EE2A", zh: "柠檬黄", en: "Lemon Yellow" },
  { hex: "#C12E1F", zh: "火焰红", en: "Flame Red" },
  { hex: "#0A2989", zh: "群青蓝", en: "Ultramarine Blue" },
  { hex: "#00AE42", zh: "竹叶绿", en: "Bamboo Green" },
  { hex: "#9B9EA0", zh: "哑光岩石灰", en: "Matte Stone Gray" },
];

const $ = <T extends HTMLElement>(id: string): T => {
  const el = document.getElementById(id);
  if (!el) throw new Error(`缺少元素 / missing element: #${id}`);
  return el as T;
};

const els = {
  drop: $<HTMLLabelElement>("drop"),
  file: $<HTMLInputElement>("file"),
  size: $<HTMLInputElement>("size"),
  sizeOut: $<HTMLOutputElement>("sizeOut"),
  withShell: $<HTMLInputElement>("withShell"),
  shellFields: $<HTMLDivElement>("shellFields"),
  shapeSwitch: $<HTMLDivElement>("shapeSwitch"),
  badgeSize: $<HTMLSelectElement>("badgeSize"),
  standeeSize: $<HTMLSelectElement>("standeeSize"),
  cropField: $<HTMLDivElement>("cropField"),
  cropBox: $<HTMLDivElement>("cropBox"),
  cropCanvas: $<HTMLCanvasElement>("cropCanvas"),
  cropHole: $<HTMLDivElement>("cropHole"),
  cropZoom: $<HTMLInputElement>("cropZoom"),
  cropReset: $<HTMLButtonElement>("cropReset"),
  cropZoomOut: $<HTMLOutputElement>("cropZoomOut"),
  cropAngle: $<HTMLInputElement>("cropAngle"),
  cropAngleOut: $<HTMLOutputElement>("cropAngleOut"),
  density: $<HTMLSelectElement>("density"),
  styleOut: $<HTMLOutputElement>("styleOut"),
  densityOut: $<HTMLOutputElement>("densityOut"),
  swatches: $<HTMLDivElement>("swatches"),
  corner: $<HTMLInputElement>("corner"),
  cornerOut: $<HTMLOutputElement>("cornerOut"),
  exportBtn: $<HTMLButtonElement>("export"),
  progress: $<HTMLDivElement>("progress"),
  progressFill: $<HTMLElement>("progressFill"),
  progressText: $<HTMLParagraphElement>("progressText"),
  error: $<HTMLParagraphElement>("error"),
  stage: $<HTMLDivElement>("stage"),
  empty: $<HTMLParagraphElement>("empty"),
  preview: $<HTMLCanvasElement>("preview"),
  view3d: $<HTMLCanvasElement>("view3d"),
  viewSwitch: $<HTMLDivElement>("viewSwitch"),
  viewHint: $<HTMLParagraphElement>("viewHint"),
  stats: $<HTMLElement>("stats"),
  stSize: $<HTMLElement>("stSize"),
  stThick: $<HTMLElement>("stThick"),
  stGrid: $<HTMLElement>("stGrid"),
  stInk: $<HTMLElement>("stInk"),
  done: $<HTMLDivElement>("done"),
  doneMeta: $<HTMLElement>("doneMeta"),
  download: $<HTMLAnchorElement>("download"),
};

const isZh = () => document.documentElement.lang === "zh-CN";
const t = (zh: string, en: string) => (isZh() ? zh : en);

interface Source {
  bitmap: ImageBitmap;
  name: string;
}

let source: Source | null = null;
let shellHex = SHELL_COLOURS[0].hex;
let shape: "rect" | "round" | "standee" = "rect";
/** 上一次量出来的平坦度 0..1，供精细度的"自动"档复用 */
let lastFlatness = 0;

/* ---------------- 取景裁剪 ---------------- */

/** 取景框：原图像素坐标里的一个正方形。zoom = 1 时正好铺满（cover）。 */
const crop = { cx: 0, cy: 0, w: 0, angle: 0 };

/** 取景框的宽高比。方形模式不裁；圆形是 1；立牌按选中的规格。 */
function cropAspect(): number {
  if (shape === "round") return 1;
  if (shape === "standee") {
    const [w, h] = els.standeeSize.value.split("x").map(Number);
    return w / h;
  }
  return 1;
}

/** 取景框高度由宽高比推出 —— 只存宽，避免两个数打架 */
function cropH(): number {
  return crop.w / cropAspect();
}

/** zoom=1 对应的框宽：在原图里放得下的最大同比例框（cover）。再小就要留白了 */
function coverW(): number {
  if (!source) return 0;
  const a = cropAspect();
  return Math.min(source.bitmap.width, source.bitmap.height * a);
}

/** 缩到最小时整张图都进框 */
function minZoom(): number {
  if (!source) return 1;
  const a = cropAspect();
  const fit = Math.max(source.bitmap.width, source.bitmap.height * a);
  return coverW() / fit;
}

function clampCrop(): void {
  if (!source) return;
  const { width: w, height: h } = source.bitmap;
  // 只兜一条底线：取景框和原图至少还有一点重叠，不至于拖到全白、找不回来。
  // 除此之外随便挪 —— 想把人物顶到边上、只留半张脸，都由着你。
  // （旋转之后这个判据不再精确，但作为"别弄丢"的护栏够用了。）
  crop.cx = Math.min(Math.max(crop.cx, -crop.w * 0.85), w + crop.w * 0.85);
  crop.cy = Math.min(Math.max(crop.cy, -cropH() * 0.85), h + cropH() * 0.85);
}

/** 把取景框映射到一块 W×H 的画布上。
 *
 * 预览和重采样都调这一个函数，所以框里看到什么就印出什么 —— 包括旋转。
 * 顺序不能换：先把画布中心挪到原点，再转、再缩放，最后把取景中心拉过来。
 */
function paintFramed(
  ctx: CanvasRenderingContext2D,
  bitmap: ImageBitmap,
  w: number,
  h: number,
): void {
  ctx.save();
  ctx.fillStyle = "#ffffff";      // 框外补白：白色在成品上是最亮的底，不是洞
  ctx.fillRect(0, 0, w, h);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.translate(w / 2, h / 2);
  ctx.rotate(crop.angle);
  const k = w / crop.w;
  ctx.scale(k, k);
  ctx.translate(-crop.cx, -crop.cy);
  ctx.drawImage(bitmap, 0, 0);
  ctx.restore();
}

function resetCrop(): void {
  if (!source) return;
  crop.w = coverW();
  crop.cx = source.bitmap.width / 2;
  crop.cy = source.bitmap.height / 2;
  crop.angle = 0;
  els.cropAngle.value = "0";
  // 下限压到"整图进框"之下再留一截 —— 想做成小图浮在一圈白底上也做得到
  els.cropZoom.min = String(Math.max(5, Math.min(15, Math.floor(minZoom() * 100) - 10)));
  els.cropZoom.value = "100";
  clampCrop();
  drawCrop();
}

/** 预览用的画布和真正重采样走同一个矩形，所见即所得。 */
function drawCrop(): void {
  if (!source) return;
  els.cropZoomOut.textContent = `${Math.round((coverW() / crop.w) * 100)}%`;
  els.cropAngleOut.textContent = `${Math.round((crop.angle * 180) / Math.PI)}°`;
  // 画布的像素比例必须跟取景框一致。以前取景框只有正方形，画布跟着写死成方的；
  // 立牌是 2:3 之后 CSS 把方画布拉成 2:3，预览就被竖着抻长了（框里的画片是对的，
  // 因为重采样走的是 paintFramed 到目标网格，不经过这块画布）。
  const box = els.cropBox.clientWidth || 280;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  els.cropCanvas.width = Math.round(box * dpr);
  els.cropCanvas.height = Math.round((box / cropAspect()) * dpr);
  const ctx = els.cropCanvas.getContext("2d");
  if (!ctx) return;
  paintFramed(ctx, source.bitmap, els.cropCanvas.width, els.cropCanvas.height);
}

function initCrop(): void {
  els.cropZoom.addEventListener("input", () => {
    if (!source) return;
    crop.w = coverW() / (Number(els.cropZoom.value) / 100);
    clampCrop();
    drawCrop();
  });
  els.cropZoom.addEventListener("change", requestPreview);
  els.cropAngle.addEventListener("input", () => {
    crop.angle = (Number(els.cropAngle.value) * Math.PI) / 180;
    clampCrop();
    drawCrop();
  });
  els.cropAngle.addEventListener("change", requestPreview);
  els.cropReset.addEventListener("click", () => {
    resetCrop();
    requestPreview();
  });

  els.cropBox.addEventListener("wheel", (e) => {
    if (!source) return;
    e.preventDefault();
    const step = e.deltaY > 0 ? -6 : 6;
    const next = Math.min(300, Math.max(Number(els.cropZoom.min), Number(els.cropZoom.value) + step));
    els.cropZoom.value = String(next);
    els.cropZoom.dispatchEvent(new Event("input"));
    scheduleCropPreview();
  }, { passive: false });

  let dragging = false;
  let lastX = 0;
  let lastY = 0;
  els.cropBox.addEventListener("pointerdown", (e) => {
    if (!source) return;
    dragging = true;
    lastX = e.clientX;
    lastY = e.clientY;
    els.cropBox.setPointerCapture(e.pointerId);
  });
  els.cropBox.addEventListener("pointermove", (e) => {
    if (!dragging || !source) return;
    // 画布上挪 1px = 原图里挪 side/画布边长 px；转过角度之后方向也要跟着转回去，
    // 否则旋转 90° 时"往右拖"会变成"往下走"，手感立刻就不对了
    const k = crop.w / (els.cropBox.clientWidth || 280);
    const dx = (e.clientX - lastX) * k;
    const dy = (e.clientY - lastY) * k;
    const ca = Math.cos(-crop.angle);
    const sa = Math.sin(-crop.angle);
    crop.cx -= dx * ca - dy * sa;
    crop.cy -= dx * sa + dy * ca;
    lastX = e.clientX;
    lastY = e.clientY;
    clampCrop();
    drawCrop();
  });
  for (const evt of ["pointerup", "pointercancel"] as const) {
    els.cropBox.addEventListener(evt, () => {
      if (!dragging) return;
      dragging = false;
      scheduleCropPreview();
    });
  }
}

/** 拖完/滚完再重算，拖动过程中每帧重算会把设备烤热 */
let cropTimer = 0;
function scheduleCropPreview(): void {
  window.clearTimeout(cropTimer);
  cropTimer = window.setTimeout(requestPreview, 260);
}

/** 量这张图有多"平"：相邻像素几乎没有差别的比例。
 *
 * 平色插画大片同色 → 高；照片就算降采样过，也仍然到处是细微渐变 → 低。
 * 拿它在"照片"和"插画"之间连续取值，比让人自己判断可靠，也比二选一细腻 ——
 * 真实素材（带纹理的厚涂、有噪点的扫描线稿）大多落在中间。
 */
function flatnessOf(rgb: Uint8ClampedArray, w: number, h: number): number {
  let flat = 0;
  let n = 0;
  for (let y = 0; y < h - 1; y += 1) {
    for (let x = 0; x < w - 1; x += 1) {
      const i = (y * w + x) * 3;
      const r = i + 3;                 // 右邻
      const d = ((y + 1) * w + x) * 3; // 下邻
      const g = Math.max(
        Math.abs(rgb[i] - rgb[r]), Math.abs(rgb[i + 1] - rgb[r + 1]), Math.abs(rgb[i + 2] - rgb[r + 2]),
        Math.abs(rgb[i] - rgb[d]), Math.abs(rgb[i + 1] - rgb[d + 1]), Math.abs(rgb[i + 2] - rgb[d + 2]),
      );
      if (g <= 2) flat += 1;
      n += 1;
    }
  }
  return n ? flat / n : 0;
}

/** 平坦度 → 0（照片）..1（插画）。两端的阈值是按降采样后的实测量级定的。 */
function artScore(flat: number): number {
  return Math.min(1, Math.max(0, (flat - 0.35) / 0.4));
}

/** 抖动幅度：按平坦度在照片档和插画档之间连续取值 */
function ditherAmountFor(flat: number): number {
  return LAYER_DITHER_AMT * (1 - artScore(flat));
}

/** 浅色保留阈值：越"平"压得越低。
 *
 * 这条线在照片里挡的是噪点，在线稿里挡掉的却是淡线和抗锯齿边 —— 而平色画面
 * 本来就没有噪点要挡，所以按插画度线性往下压，最低压到默认值的两成。 */
function keepFloorFor(flat: number): number {
  return LAYER_KEEP_FLOOR * (1 - 0.8 * artScore(flat));
}

/** 门槛一降就必须同时打开它，否则降下来的门槛会被中性底顶穿。
 *
 * need = 这一色自己的彩色度 + kBack（三色平摊的中性成分）。门槛压在 need 上时，
 * 彩色度为 0 的通道也能靠 kBack 顶过去，被抬成整整一层：饱和蓝里多一层黄就发绿，
 * 中性灰细线里多一层品红就发粉。而这两种情况**只在门槛降下来之后才够得着**，
 * 所以这两件事是同一个开关的两半，不该分开。 */
function liftChromaOnlyFor(flat: number): boolean {
  return keepFloorFor(flat) < LAYER_KEEP_FLOOR;
}

/** 网格化前的中值滤波：线稿要关掉，否则 1–2 像素宽的笔画会被抹平。
 *  代价是矩形变多、三角形涨 —— 面板上的"三角面"读数就是这个成本。 */
function mergeFilterFor(flat: number): number {
  return artScore(flat) > 0.5 ? 1 : MESH_MERGE_FILTER;
}

/** 网格密度 mm/px。
 *
 * 这是"细节"的真正来源：画面占多少个格子。取景缩小之后主体占的格子变少，
 * 糊掉的就是这个。密度调高能把格子补回来。
 *
 * 再往细走的收益有上限 —— 喷嘴 0.4mm，XY 方向比它小的特征本来就印不出来；
 * 0.1mm/px 已经比喷嘴细一倍，继续加只会让三角形和文件涨，画面不会更清楚。
 */
function mmPerPx(): number {
  if (els.density.value !== "auto") {
    const v = Number(els.density.value);
    return Number.isFinite(v) && v > 0 ? v : DEFAULT_MM_PER_PX;
  }
  // 自动：插画靠细线吃饭，格子给密一点；照片是连续调，标准密度就够，
  // 再密只是把三角形和文件撑大。
  const k = artScore(lastFlatness);
  return k > 0.6 ? 0.1 : k > 0.3 ? 0.15 : DEFAULT_MM_PER_PX;
}

/** 立牌选中的画幅。壳子按同一个数去 /standee/ 取烘好的网格，尺寸不会各走各的。 */
function standeeMm(): { w: number; h: number } {
  const [w, h] = els.standeeSize.value.split("x").map(Number);
  return { w, h };
}

/** 当前画幅 mm。三种模式各有各的来源。 */
function artSizeMm(): { w: number; h: number } {
  if (shape === "round") {
    const d = Number(els.badgeSize.value);
    return { w: d, h: d };
  }
  if (shape === "standee") {
    const [w, h] = els.standeeSize.value.split("x").map(Number);
    return { w, h };
  }
  const longest = Number(els.size.value);
  return { w: longest, h: longest }; // 方形模式下真实比例由照片决定，见 gridFor
}

/** 遮罩半径用的"尺寸"：圆形是直径，其余取长边 */
function sizeMm(): number {
  const { w, h } = artSizeMm();
  return Math.max(w, h);
}

/** 形状遮罩半径：圆形 = 直径的一半；方形 = 外壳圆角（没外壳就是 0） */
function maskRadiusMm(longestMm: number): number {
  if (shape === "round") return longestMm / 2;
  if (shape === "standee") return els.withShell.checked ? Number(els.corner.value) : 0;
  return els.withShell.checked ? Number(els.corner.value) : 0;
}
let reqId = 0;
let previewToken = 0;
let downloadUrl: string | null = null;

/** 发出预览请求时记下当时的尺寸与外壳参数，结果回来时要用。 */
let pending: { widthMm: number; heightMm: number; shell: Preview3DShell | null } | null = null;
/** 最近一次算好的场景，用来在两种预览之间瞬间切换，不必重算。 */
let scene: { image: ImageData; thicknessMm: number } | null = null;

let view: "flat" | "solid" = "flat";
let viewer: Preview3D | null = null;
/** 3D 场景是否落后于最新的解算结果。切回平面时不重建，省掉白做的功。 */
let viewerStale = true;

const worker = new Worker(new URL("../worker/engine.worker.ts", import.meta.url), {
  type: "module",
});

/* ---------------- 网格计算 ---------------- */

/** 按最长边和 mm/px 密度算打印网格，并夹在安全范围内。
 *
 * 圆形（吧唧）走的是"正方形画片 + 圆角半径 = 边长的一半"——圆角遮罩那套代码
 * 在半径顶到一半时四个圆心正好重合到中心，出来就是一个正圆。不用另写裁形逻辑，
 * 也就不会和 Python 那边的对拍分叉。 */
function gridFor(bitmap: ImageBitmap, longestMm: number, fixed: { w: number; h: number } | null) {
  const ar = fixed ? fixed.w / fixed.h : bitmap.width / bitmap.height;
  const widthMm = fixed ? fixed.w : ar >= 1 ? longestMm : longestMm * ar;
  const heightMm = fixed ? fixed.h : ar >= 1 ? longestMm / ar : longestMm;
  const clamp = (v: number) => Math.max(GRID_MIN, Math.min(GRID_MAX, Math.round(v)));
  const mm = mmPerPx();
  return {
    widthMm,
    heightMm,
    gridW: clamp(widthMm / mm),
    gridH: clamp(heightMm / mm),
  };
}

/** 把图重采样到打印网格，取出像素。Canvas 的缩放已经是面积平均，够用。
 *
 * crop 给的是**原图像素坐标**里的取景框，和裁剪控件预览用的是同一个矩形，
 * 所以框里看到什么就印出什么。框可以比原图大（缩到最小时），
 * 超出的部分留白 —— 白色在成品上就是最亮的底，不是洞。 */
function resample(
  bitmap: ImageBitmap,
  gridW: number,
  gridH: number,
  framed = false,
): Uint8ClampedArray {
  const canvas = document.createElement("canvas");
  canvas.width = gridW;
  canvas.height = gridH;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) throw new Error(t("浏览器不支持 Canvas", "Canvas is unavailable"));
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  if (framed) {
    paintFramed(ctx, bitmap, gridW, gridH);
  } else {
    ctx.drawImage(bitmap, 0, 0, gridW, gridH);
  }
  const rgba = ctx.getImageData(0, 0, gridW, gridH).data;

  // 引擎吃紧凑的 RGB，去掉 alpha 通道
  const rgb = new Uint8ClampedArray(gridW * gridH * 3);
  for (let i = 0, j = 0; i < rgba.length; i += 4, j += 3) {
    rgb[j] = rgba[i];
    rgb[j + 1] = rgba[i + 1];
    rgb[j + 2] = rgba[i + 2];
  }
  return rgb;
}

/* ---------------- 界面状态 ---------------- */

function showError(message: string | null): void {
  els.error.hidden = message === null;
  if (message) els.error.textContent = message;
}

function setProgress(percent: number, stage: string): void {
  els.progress.hidden = false;
  els.progressFill.style.width = `${percent}%`;
  els.progressText.textContent = `${percent}% · ${stage}`;
}

function clearOutput(): void {
  els.done.hidden = true;
  if (downloadUrl) {
    URL.revokeObjectURL(downloadUrl);
    downloadUrl = null;
  }
}

/* ---------------- 预览 ---------------- */

/** 当前界面上的外壳设置。导出与立体预览共用同一组数字，不会各说各话。 */
function shellSettings(): Preview3DShell | null {
  // 圆形是吧唧、立牌是两件式灯座，都不该套灯箱外壳。
  // 吧唧的壳由烘好的数据打进 3MF；立牌的壳走 CAD 母本单独出，
  // 因为壳只打一次、画片要打很多次，没必要每次导出都带一份。
  if (shape !== "rect") return null;
  if (!els.withShell.checked) return null;
  return {
    wall: 3,
    depth: 18,
    corner: Number(els.corner.value),
    clearance: 0.2,
    colorHex: shellHex,
  };
}

function requestPreview(): void {
  if (!source) return;
  clearOutput();
  showError(null);

  // 先用一块固定的小网格量平坦度：密度要按它来定，而它自己不能再依赖密度，
  // 否则就成了循环。192×192 够判风格，代价可以忽略。
  lastFlatness = flatnessOf(
    resample(source.bitmap, 192, 192, shape !== "rect"), 192, 192,
  );
  const longest = sizeMm();
  const { widthMm, heightMm, gridW, gridH } = gridFor(source.bitmap, longest, shape === "rect" ? null : artSizeMm());
  const rgb = resample(source.bitmap, gridW, gridH, shape !== "rect");

  els.stSize.textContent = `${widthMm.toFixed(0)} × ${heightMm.toFixed(0)} mm`;
  const asked = Math.round(Math.max(widthMm, heightMm) / mmPerPx());
  const capped = asked > GRID_MAX;
  els.stGrid.textContent = capped
    ? `${gridW} × ${gridH} px（已封顶）`
    : `${gridW} × ${gridH} px`;
  const pct = Math.round(artScore(lastFlatness) * 100);
  els.styleOut.textContent = t(
    `自动 · 插画度 ${pct}%${mergeFilterFor(lastFlatness) < 3 ? " · 免滤波" : ""}`,
    `auto · ${pct}% flat${mergeFilterFor(lastFlatness) < 3 ? " · no median" : ""}`,
  );
  els.densityOut.textContent = capped
    ? t(`${mmPerPx().toFixed(2)} mm/px · 受网格上限限制`, `${mmPerPx().toFixed(2)} mm/px · capped`)
    : `${mmPerPx().toFixed(2)} mm/px`;

  const id = ++reqId;
  previewToken = id;
  pending = { widthMm, heightMm, shell: shellSettings() };
  const msg: WorkerRequest = {
    type: "preview",
    id,
    rgb,
    gridW,
    gridH,
    widthMm,
    cornerRadiusMm: maskRadiusMm(longest),
    ditherAmount: ditherAmountFor(lastFlatness),
    keepFloor: keepFloorFor(lastFlatness),
    liftChromaOnly: liftChromaOnlyFor(lastFlatness),
    mergeFilter: mergeFilterFor(lastFlatness),
  };
  worker.postMessage(msg, [rgb.buffer]);
}

function drawPreview(image: ImageData): void {
  els.preview.width = image.width;
  els.preview.height = image.height;
  const ctx = els.preview.getContext("2d");
  if (!ctx) return;
  ctx.putImageData(image, 0, 0);
  els.empty.hidden = true;
  els.stats.hidden = false;
  if (Preview3D.isSupported()) els.viewSwitch.hidden = false;
}

/* ---------------- 立体预览 ---------------- */

/**
 * 把最近一次的解算结果推给 3D 视图。
 *
 * 贴图就是平面预览那张 ImageData，原分辨率直接上 GPU —— 两种看法用的是
 * 同一份数据，不存在「3D 那边糊一点」的情况。
 */
function syncViewer(): void {
  if (!viewer || !scene || !pending || !viewerStale) return;
  viewerStale = false;
  viewer.setScene({
    image: scene.image,
    artW: pending.widthMm,
    artH: pending.heightMm,
    artThicknessMm: scene.thicknessMm,
    shell: pending.shell,
  });
}

function setView(next: "flat" | "solid"): void {
  view = next;
  const solid = next === "solid";

  for (const b of els.viewSwitch.querySelectorAll<HTMLButtonElement>("button")) {
    b.setAttribute("aria-pressed", String(b.dataset.view === next));
  }

  if (solid && !viewer) {
    // WebGL 上下文到这一刻才创建：只看平面预览的人一分钱开销都不用付
    try {
      viewer = new Preview3D(els.view3d);
    } catch (err) {
      showError(t(
        `立体预览打不开：${err instanceof Error ? err.message : String(err)}`,
        `The 3D view could not start: ${err instanceof Error ? err.message : String(err)}`,
      ));
      els.viewSwitch.hidden = true;
      view = "flat";
      return;
    }
    syncViewer();
  }

  els.preview.hidden = solid || !scene;
  els.view3d.hidden = !solid;
  els.viewHint.hidden = !solid;
  if (solid) viewer?.invalidate();
}

/* ---------------- 导出 ---------------- */

function startExport(): void {
  if (!source) return;
  clearOutput();
  showError(null);
  els.exportBtn.disabled = true;
  setProgress(2, t("准备中", "Preparing"));

  // 先用一块固定的小网格量平坦度：密度要按它来定，而它自己不能再依赖密度，
  // 否则就成了循环。192×192 够判风格，代价可以忽略。
  lastFlatness = flatnessOf(
    resample(source.bitmap, 192, 192, shape !== "rect"), 192, 192,
  );
  const longest = sizeMm();
  const { widthMm, heightMm, gridW, gridH } = gridFor(source.bitmap, longest, shape === "rect" ? null : artSizeMm());
  const rgb = resample(source.bitmap, gridW, gridH, shape !== "rect");

  const msg: WorkerRequest = {
    type: "export",
    id: ++reqId,
    rgb,
    gridW,
    gridH,
    widthMm,
    heightMm,
    pictureName: source.name.replace(/\.[^.]+$/, "") || "CMYW Studio",
    shell: shellSettings(),
    cornerRadiusMm: maskRadiusMm(longest),
    badge: shape === "round" && els.withShell.checked ? { diameter: sizeMm() } : null,
    standee: shape === "standee" && els.withShell.checked ? standeeMm() : null,
    ditherAmount: ditherAmountFor(lastFlatness),
    keepFloor: keepFloorFor(lastFlatness),
    liftChromaOnly: liftChromaOnlyFor(lastFlatness),
    mergeFilter: mergeFilterFor(lastFlatness),
  };
  worker.postMessage(msg, [rgb.buffer]);
}

worker.onmessage = (event: MessageEvent<WorkerResponse>) => {
  const msg = event.data;

  if (msg.type === "progress") {
    if (msg.id === reqId) setProgress(msg.percent, msg.stage);
    return;
  }

  if (msg.type === "preview") {
    // 拖动滑块会连发请求，只认最后一次的结果
    if (msg.id !== previewToken) return;
    scene = { image: msg.image, thicknessMm: msg.thicknessMm };
    viewerStale = true;
    drawPreview(msg.image);
    if (view === "solid") syncViewer();
    els.preview.hidden = view === "solid";
    els.stThick.textContent = `${msg.thicknessMm.toFixed(2)} mm · ${msg.stack} ${t("层", "layers")}`;
    els.stInk.textContent =
      `C ${msg.coverage.c.toFixed(0)}% · M ${msg.coverage.m.toFixed(0)}% · Y ${msg.coverage.y.toFixed(0)}%`;
    els.exportBtn.disabled = false;
    els.progress.hidden = true;
    return;
  }

  if (msg.type === "export") {
    if (msg.id !== reqId) return;
    els.progress.hidden = true;
    els.exportBtn.disabled = false;

    const blob = new Blob([msg.data as BlobPart], { type: "application/octet-stream" });
    downloadUrl = URL.createObjectURL(blob);
    els.download.href = downloadUrl;
    els.download.download = `${source?.name.replace(/\.[^.]+$/, "") || "lightbox"}.3mf`;
    els.doneMeta.textContent =
      `${(msg.bytes / 1024 / 1024).toFixed(1)} MB · ${msg.triangles.toLocaleString()} ${t("三角面", "triangles")}`;
    els.done.hidden = false;
    els.done.scrollIntoView({ behavior: "smooth", block: "nearest" });
    return;
  }

  if (msg.type === "error") {
    els.progress.hidden = true;
    els.exportBtn.disabled = false;
    showError(t(`出错了：${msg.message}`, `Something went wrong: ${msg.message}`));
  }
};

worker.onerror = (e) => {
  els.progress.hidden = true;
  els.exportBtn.disabled = false;
  showError(t(`解算线程崩溃：${e.message}`, `The engine worker crashed: ${e.message}`));
};

/* ---------------- 载入图片 ---------------- */

async function loadFile(file: File): Promise<void> {
  showError(null);
  if (!file.type.startsWith("image/")) {
    showError(t("请选择图片文件", "Please choose an image file"));
    return;
  }
  if (file.size > 40 * 1024 * 1024) {
    showError(t("图片过大（上限 40MB）", "That image is too large (40MB max)"));
    return;
  }
  try {
    const bitmap = await createImageBitmap(file);
    source = { bitmap, name: file.name };
    resetCrop();          // 换图必须复位，不然新图会沿用上一张的取景框
    syncShapeFields();    // 有图之后取景控件才该出现
    requestPreview();
  } catch {
    showError(t("这张图读不出来，换一张试试", "That image could not be decoded — try another"));
  }
}

/* ---------------- 事件绑定 ---------------- */

els.file.addEventListener("change", () => {
  const f = els.file.files?.[0];
  if (f) void loadFile(f);
});

for (const evt of ["dragenter", "dragover"] as const) {
  els.drop.addEventListener(evt, (e) => {
    e.preventDefault();
    els.drop.dataset.over = "true";
  });
}
for (const evt of ["dragleave", "drop"] as const) {
  els.drop.addEventListener(evt, (e) => {
    e.preventDefault();
    delete els.drop.dataset.over;
  });
}
els.drop.addEventListener("drop", (e) => {
  const f = (e as DragEvent).dataTransfer?.files?.[0];
  if (f) void loadFile(f);
});

// 滑块拖动时先更新读数，松手才重算 —— 每一帧都重算会把设备烤热
const syncSize = () => {
  els.sizeOut.textContent = `${els.size.value} mm`;
};
els.size.addEventListener("input", syncSize);
els.size.addEventListener("change", requestPreview);

const syncCorner = () => {
  els.cornerOut.textContent = `${els.corner.value} mm`;
};
els.corner.addEventListener("input", syncCorner);
els.corner.addEventListener("change", requestPreview);

els.withShell.addEventListener("change", () => {
  syncShapeFields();
  requestPreview();
});

/** 外壳设置块的显隐：圆形没有灯箱那套壁厚/深度/圆角，方形跟着勾选走。 */
function syncShapeFields(): void {
  const round = shape === "round";
  const standee = shape === "standee";
  const framed = round || standee;   // 这两种画幅固定，才需要自己取景
  els.cropField.hidden = !framed || !source;
  els.cropHole.dataset.shape = round ? "round" : "rect";
  els.cropBox.style.aspectRatio = String(cropAspect());
  if (framed && source) drawCrop();
  els.size.hidden = framed;
  els.badgeSize.hidden = !round;
  els.standeeSize.hidden = !standee;
  // 立牌的外壳来自 CAD 母本，网站这边没有可打包的壳，别给一个按了没用的勾
  els.withShell.closest<HTMLElement>(".field")!.hidden = false;
  els.shellFields.style.display = framed || !els.withShell.checked ? "none" : "";
  document.querySelectorAll<HTMLElement>(".lbl-rect").forEach((e) => (e.hidden = framed));
  document.querySelectorAll<HTMLElement>(".lbl-round").forEach((e) => (e.hidden = !round));
}

// 形状：方形（跟照片比例）/ 圆形（吧唧）。
// 注意这几行必须留在顶层 —— 之前误塞进 withShell 的 change 回调里，
// 结果是不勾一次外壳，形状按钮根本没绑上事件，勾一次还会重复绑一遍。
els.badgeSize.addEventListener("change", () => {
  if (source) resetCrop();
  requestPreview();
});
els.standeeSize.addEventListener("change", () => {
  if (source) resetCrop();
  syncShapeFields();
  requestPreview();
});
els.density.addEventListener("change", requestPreview);
initCrop();
els.shapeSwitch.querySelectorAll<HTMLButtonElement>("[data-shape]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const next = (btn.dataset.shape ?? "rect") as typeof shape;
    if (next === shape) return;
    shape = next;
    if (source) resetCrop();
    els.shapeSwitch.querySelectorAll<HTMLButtonElement>("[data-shape]").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.shape === shape));
    });
    syncShapeFields();
    requestPreview();
  });
});
syncShapeFields();

els.exportBtn.addEventListener("click", startExport);

// 色卡
for (const c of SHELL_COLOURS) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "swatch";
  b.style.background = c.hex;
  b.setAttribute("role", "radio");
  b.setAttribute("aria-checked", String(c.hex === shellHex));
  b.title = isZh() ? c.zh : c.en;
  b.addEventListener("click", () => {
    shellHex = c.hex;
    els.swatches.querySelectorAll<HTMLButtonElement>(".swatch").forEach((el) => {
      el.setAttribute("aria-checked", String(el.style.background === b.style.background));
    });
    // 换颜色不影响分色，也不影响几何 —— 只改一个 uniform，不要重算
    if (pending?.shell) pending.shell.colorHex = c.hex;
    viewer?.setShellColor(c.hex);
    clearOutput();
  });
  els.swatches.append(b);
}

for (const b of els.viewSwitch.querySelectorAll<HTMLButtonElement>("button")) {
  b.addEventListener("click", () => setView(b.dataset.view === "solid" ? "solid" : "flat"));
}

syncSize();
syncCorner();
