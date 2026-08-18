/**
 * 制作台交互。
 * Studio page: pick a photo, see it lit, download a printable 3MF.
 *
 * 主线程只做三件事：把图重采样到打印网格、把参数丢给 Worker、把结果画出来。
 * 所有重活都在 worker 里，界面任何时候都不会卡。
 */

import "./site";
import { DEFAULT_MM_PER_PX, GRID_MAX, GRID_MIN } from "../engine/constants";
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

/** 按最长边和 mm/px 密度算打印网格，并夹在安全范围内。 */
function gridFor(bitmap: ImageBitmap, longestMm: number) {
  const ar = bitmap.width / bitmap.height;
  const widthMm = ar >= 1 ? longestMm : longestMm * ar;
  const heightMm = ar >= 1 ? longestMm / ar : longestMm;
  const clamp = (v: number) => Math.max(GRID_MIN, Math.min(GRID_MAX, Math.round(v)));
  return {
    widthMm,
    heightMm,
    gridW: clamp(widthMm / DEFAULT_MM_PER_PX),
    gridH: clamp(heightMm / DEFAULT_MM_PER_PX),
  };
}

/** 把图重采样到打印网格，取出像素。Canvas 的缩放已经是面积平均，够用。 */
function resample(bitmap: ImageBitmap, gridW: number, gridH: number): Uint8ClampedArray {
  const canvas = document.createElement("canvas");
  canvas.width = gridW;
  canvas.height = gridH;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) throw new Error(t("浏览器不支持 Canvas", "Canvas is unavailable"));
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(bitmap, 0, 0, gridW, gridH);
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

  const longest = Number(els.size.value);
  const { widthMm, heightMm, gridW, gridH } = gridFor(source.bitmap, longest);
  const rgb = resample(source.bitmap, gridW, gridH);

  els.stSize.textContent = `${widthMm.toFixed(0)} × ${heightMm.toFixed(0)} mm`;
  els.stGrid.textContent = `${gridW} × ${gridH} px`;

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
    cornerRadiusMm: els.withShell.checked ? Number(els.corner.value) : 0,
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

  const longest = Number(els.size.value);
  const { widthMm, heightMm, gridW, gridH } = gridFor(source.bitmap, longest);
  const rgb = resample(source.bitmap, gridW, gridH);

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
  els.shellFields.style.display = els.withShell.checked ? "" : "none";
  requestPreview();
});

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
