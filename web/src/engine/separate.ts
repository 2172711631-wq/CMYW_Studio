/**
 * RGB → CMYW 层数（v2 档案）。
 * RGB → CMYW layer counts, ported 1:1 from `_layers_from_rgb_v2` in main.py.
 *
 * 移植要点 / porting notes
 * ------------------------------------------------------------------
 * 这份实现刻意逐字对齐 Python 版的数值行为，而不是「差不多」：
 *
 *  1. Python 全程 float32（图像 astype(np.float32)/255 之后一路 float32），
 *     JS 数字是 float64。每一步都用 Math.fround 收敛回 float32，
 *     否则边界像素会在取整时倒向另一边。
 *
 *  2. NumPy 的 round 是**银行家舍入**（round-half-to-even，0.5→0、1.5→2），
 *     JS 的 Math.round 是 0.5→1。直接用 Math.round 会让大量像素差一层。
 *
 * 任何改动都必须让 web/test/separation.test.ts 继续通过——那个测试拿
 * Python 生成的基准数据逐像素比对。
 */

import {
  BAYER4,
  DENSITY_C,
  DENSITY_M,
  DENSITY_W,
  DENSITY_Y,
  GAMMA_EXPONENT,
  LAYER_DITHER_AMT,
  LAYER_KEEP_FLOOR,
  LINEAR_COEFFICIENT,
  MAX_LAYERS_C,
  MAX_LAYERS_M,
  MAX_LAYERS_Y,
  MIN_WHITE_LAYERS,
  RGB_CLIP_MIN,
} from "./constants";

const f = Math.fround;

export interface LayerSet {
  /** 白 / 黄 / 品红 / 青 的层数，行优先，长度 = gridW × gridH */
  W: Int32Array;
  Y: Int32Array;
  M: Int32Array;
  C: Int32Array;
  gridW: number;
  gridH: number;
}

export interface SeparateOptions {
  /** 有序抖动，默认开。关掉会出现明显等高线。 */
  dither?: boolean;
  /** 白底层数，默认 4。 */
  minWhiteLayers?: number;
}

/**
 * NumPy 的 np.round：舍入到最近整数，恰好 .5 时舍向偶数。
 * JS 的 Math.round 在 .5 时一律向上，两者在边界值上结果不同。
 */
export function rintHalfToEven(x: number): number {
  const fl = Math.floor(x);
  const diff = x - fl;
  if (diff > 0.5) return fl + 1;
  if (diff < 0.5) return fl;
  return fl % 2 === 0 ? fl : fl + 1;
}

/**
 * 浮点需求层数 → 整数层数。
 * 对应 Python 的 _quantize_layers。
 */
function quantize(
  need: Float32Array,
  maxLayers: number,
  gridW: number,
  dither: boolean,
  keepMask: Uint8Array | null,
): Int32Array {
  const n = need.length;
  const out = new Int32Array(n);
  const floor32 = f(LAYER_KEEP_FLOOR);
  const lifted = f(0.51);

  for (let i = 0; i < n; i += 1) {
    let x = need[i];

    if (dither) {
      // Bayer 矩阵按 4×4 平铺，索引与 numpy 的 np.tile 一致
      const y = (i / gridW) | 0;
      const col = i - y * gridW;
      const bayer = BAYER4[(y & 3) * 4 + (col & 3)];
      x = f(x + f(bayer * LAYER_DITHER_AMT));
    }

    // 仅在有彩色度处把浅色抬过取整门槛，避免中性灰被三色薄雾铺满
    const wantsLift = need[i] >= floor32 && x < 0.5 && (keepMask === null || keepMask[i] === 1);
    if (wantsLift) x = lifted;

    const r = rintHalfToEven(x);
    out[i] = r < 0 ? 0 : r > maxLayers ? maxLayers : r;
  }
  return out;
}

/**
 * 把已重采样到打印网格的 RGB 像素分解成四色层数。
 *
 * @param rgb   RGBRGB… 排列的 uint8，长度必须是 gridW × gridH × 3
 * @param gridW 打印网格宽（像素）
 * @param gridH 打印网格高（像素）
 */
export function separateCMYW(
  rgb: Uint8Array | Uint8ClampedArray,
  gridW: number,
  gridH: number,
  options: SeparateOptions = {},
): LayerSet {
  const count = gridW * gridH;
  if (rgb.length < count * 3) {
    throw new Error(`像素数据长度不足 / pixel buffer too short: ${rgb.length} < ${count * 3}`);
  }

  const dither = options.dither ?? true;
  const whiteLayers = options.minWhiteLayers ?? MIN_WHITE_LAYERS;

  // 白底在每个通道贡献的固定密度。Python 侧此处是 float64 运算。
  const whiteCost = DENSITY_W * whiteLayers;
  const clipMin = f(RGB_CLIP_MIN);

  const needC = new Float32Array(count);
  const needM = new Float32Array(count);
  const needY = new Float32Array(count);
  const keepMask = new Uint8Array(count);

  for (let i = 0; i < count; i += 1) {
    const p = i * 3;

    // uint8 → float32 归一化后钳住下限，ln(0) 会是无穷大
    let r = f(rgb[p] / 255);
    let g = f(rgb[p + 1] / 255);
    let b = f(rgb[p + 2] / 255);
    r = r < clipMin ? clipMin : r > 1 ? 1 : r;
    g = g < clipMin ? clipMin : g > 1 ? 1 : g;
    b = b < clipMin ? clipMin : b > 1 ? 1 : b;

    // 目标光密度 e = (−ln T)^γ · α
    const eR = f(f(Math.pow(f(-f(Math.log(r))), GAMMA_EXPONENT)) * LINEAR_COEFFICIENT);
    const eG = f(f(Math.pow(f(-f(Math.log(g))), GAMMA_EXPONENT)) * LINEAR_COEFFICIENT);
    const eB = f(f(Math.pow(f(-f(Math.log(b))), GAMMA_EXPONENT)) * LINEAR_COEFFICIENT);

    // 扣掉白底吸收，除以单层密度 → 需求层数。青吸红、品红吸绿、黄吸蓝。
    let c = f(f(eR - whiteCost) / DENSITY_C);
    let m = f(f(eG - whiteCost) / DENSITY_M);
    let y = f(f(eB - whiteCost) / DENSITY_Y);
    c = c < 0 ? 0 : c;
    m = m < 0 ? 0 : m;
    y = y < 0 ? 0 : y;

    // 自适应 UCR：抽掉三色重叠出来的灰，再按该像素自身亮度回加一部分
    const k = Math.min(c, m, y);
    const cChr = f(c - k);
    const mChr = f(m - k);
    const yChr = f(y - k);

    let lum = f(f(f(f(r + g) + b)) / 3);
    lum = lum < 0 ? 0 : lum > 1 ? 1 : lum;
    const kBack = f(f(k * f(1 - lum)) * 0.45);

    needC[i] = f(cChr + kBack);
    needM[i] = f(mChr + kBack);
    needY[i] = f(yChr + kBack);

    // 只有真正带彩色度的像素才允许抬浅层
    keepMask[i] = f(f(cChr + mChr) + yChr) >= f(LAYER_KEEP_FLOOR) ? 1 : 0;
  }

  const W = new Int32Array(count);
  W.fill(whiteLayers);

  return {
    W,
    C: quantize(needC, MAX_LAYERS_C, gridW, dither, keepMask),
    M: quantize(needM, MAX_LAYERS_M, gridW, dither, keepMask),
    Y: quantize(needY, MAX_LAYERS_Y, gridW, dither, keepMask),
    gridW,
    gridH,
  };
}

/** 各色层数叠起来的 Z 起点（层数，非 mm）。白在最底。 */
export function computeZStarts(layers: LayerSet): {
  zW: Int32Array;
  zY: Int32Array;
  zM: Int32Array;
  zC: Int32Array;
} {
  const n = layers.W.length;
  const zW = new Int32Array(n);
  const zY = new Int32Array(n);
  const zM = new Int32Array(n);
  const zC = new Int32Array(n);
  for (let i = 0; i < n; i += 1) {
    zY[i] = layers.W[i];
    zM[i] = layers.W[i] + layers.Y[i];
    zC[i] = layers.W[i] + layers.Y[i] + layers.M[i];
  }
  return { zW, zY, zM, zC };
}

/** 最厚处的总层数，外壳深度与卡槽要按它算。 */
export function maxStack(layers: LayerSet): number {
  let best = 0;
  for (let i = 0; i < layers.W.length; i += 1) {
    const t = layers.W[i] + layers.Y[i] + layers.M[i] + layers.C[i];
    if (t > best) best = t;
  }
  return best;
}
