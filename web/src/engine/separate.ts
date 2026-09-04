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
  UCR_ADD_BACK,
} from "./constants";

const f = Math.fround;

/** 线网的级数。级数越多色调越准，但图案周期 = 级数 × 行距，太长就看得见条纹。
 *  与 Python 侧 LINE_SCREEN_LEVELS 同值。 */
const LINE_SCREEN_LEVELS = 4;

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
  /**
   * 抖动幅度（层）。不传就用 LAYER_DITHER_AMT。
   *
   * 之所以做成连续量而不是开关：抖动对照片是必需的（打散层数之间的台阶），
   * 对平色插画是灾难（平色里撒麻点、细线被咬断），但真实素材大多在两者之间。
   * 给一个 0..LAYER_DITHER_AMT 的连续值，就能按画面本身的平坦程度线性地取。
   */
  ditherAmount?: number;
  /**
   * 浅色保留阈值。低于它的彩色度会被整格丢掉，默认 LAYER_KEEP_FLOOR。
   *
   * 照片里这条线是有用的：它挡住噪点被抬成一层。但线稿的淡线和抗锯齿边缘
   * 正好卡在这条线上，照默认值走会被整条抹掉 —— 平色画面本来也没有噪点要挡，
   * 所以画面越"平"，这个值就该越低。
   */
  keepFloor?: number;
  /**
   * 抬浅层时只看这一色**自己的彩色度**，不算中性底（kBack）。默认 false =
   * 老行为，Python 母本走的就是这一档。
   *
   * 为什么需要它：need = 自己的彩色度 + kBack，而 kBack 是给三色平摊的中性成分。
   * 门槛压在 need 上，就会出现"这一色的彩色度是 0，全靠 kBack 顶过门槛，于是被
   * 抬成整整一层"。一块饱和蓝里黄的彩色度正好是 0，keepFloor 降到 0.07 之后它
   * 被抬出一层黄 —— 黄吸蓝，画面当场发绿。中性灰的细线也一样，会平白多一层品红
   * 变成粉的。
   *
   * 把门槛改压在彩色度上，淡的彩色线照抬（它有自己的彩色度），
   * 纯靠中性底顶上来的配角色不抬。
   */
  liftChromaOnly?: boolean;
  /**
   * 抖动格子放大多少倍。1 = 每个网格一个抖动决定（默认，也就是原来的行为）。
   *
   * 抖动是拿相邻格子的层数高低差换视觉上的中间色，格子比喷嘴小的时候这笔交易
   * 不成立：0.1mm/px 下一个孤立抖动点只有喷嘴面积的十六分之一，印不出来，
   * 只会变成多余的三角形，或者被挤成 0.4mm 的一颗麻点。放大到喷嘴尺寸之后，
   * 每个抖动决定落到实物上正好是一个印得出来的点。
   */
  ditherBlock?: number;
  /**
   * 抖动图案。默认 "bayer"（4×4 网点，v2 基准钉的就是它）。
   *
   * "line" 是线网：阈值只沿 Y 变，同一行整行一个值，落到实物上是一条条**连续的
   * 挤出线**。网点在 0.4mm 这个尺度上是一颗颗孤立的点，切片器只能一个个去补 ——
   * 满屏缝隙填充、上千次回抽、换料次数暴涨，实测 44 万三角形还切得一塌糊涂。
   * 线网同一张图 1.9 万三角形，色调误差 0.230 → 0.094（网点 0.041）。
   */
  ditherScreen?: "bayer" | "line";
  /**
   * 分色档案。默认 v3。
   *
   * v2 先把白底吸收从每个通道扣掉、各自裁到 0，再在**层数**上做 UCR。两个后果：
   * 亮过 221/255 的通道一层墨都拿不到（浅粉、肉色、红晕整段变纯白），
   * 而三色单层密度不等又让纯灰凭空长出色度（54 级灰阶里 34 级三色不等）。
   *
   * v3 把 UCR 挪到**光密度**空间：先在 e 上取 min 当中性成分，剩下的才是色度，
   * 最后各自除以自己的密度。纯灰的色度精确是 0，浅色的色度也不再被裁切吃掉。
   *
   * v2 原样保留 —— 之前打过的片子要复现就选它。
   */
  profile?: "v2" | "v3";
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
  amount: number,
  keepMask: Uint8Array | null,
  keepFloor: number,
  neutral: Float32Array | null,
  ditherBlock: number,
  ditherScreen: "bayer" | "line",
): Int32Array {
  const n = need.length;
  const out = new Int32Array(n);
  const floor32 = f(keepFloor);
  const lifted = f(0.51);
  // 满幅抖动时抬层必须让开：幅度到一整个量化步长，0.67 层的需求会有 67% 的格子
  // 落到 1 层、33% 落到 0 层，平均正好是 0.67 —— 这是分数层唯一的表达方式。
  // 再抬一手就是把每格都按成 1 层，肉色从 0.67 变 1.00，深了一半。
  const fullDither = dither && amount >= 1;

  for (let i = 0; i < n; i += 1) {
    let x = need[i];

    if (dither) {
      const y = (i / gridW) | 0;
      let bayer: number;
      if (ditherScreen === "line") {
        // 线网：阈值只跟行走，同一行整行一个值 → 打出来是一条连续的线
        const row = ((y / ditherBlock) | 0) % LINE_SCREEN_LEVELS;
        bayer = f((row + 0.5) / LINE_SCREEN_LEVELS - 0.5);
      } else {
        // Bayer 矩阵按 4×4 平铺；ditherBlock > 1 时每格放大成 block×block
        const col = i - y * gridW;
        const by = ((y / ditherBlock) | 0) & 3;
        const bx = ((col / ditherBlock) | 0) & 3;
        bayer = BAYER4[by * 4 + bx];
      }
      x = f(x + f(bayer * amount));
    }

    // 仅在有彩色度处把浅色抬过取整门槛，避免中性灰被三色薄雾铺满
    // 拿去和门槛比的量：默认是 need 本身，开了 liftChromaOnly 就先把中性底扣掉
    const weight = neutral === null ? need[i] : f(need[i] - neutral[i]);
    const wantsLift =
      !fullDither && weight >= floor32 && x < 0.5 && (keepMask === null || keepMask[i] === 1);
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
  const ditherAmount = options.ditherAmount ?? LAYER_DITHER_AMT;
  const keepFloor = options.keepFloor ?? LAYER_KEEP_FLOOR;
  const liftChromaOnly = options.liftChromaOnly ?? false;
  const ditherBlock = Math.max(1, Math.round(options.ditherBlock ?? 1));
  const ditherScreen = options.ditherScreen ?? "bayer";
  const profile = options.profile ?? "v3";
  const whiteLayers = options.minWhiteLayers ?? MIN_WHITE_LAYERS;

  // 白底在每个通道贡献的固定密度。Python 侧此处是 float64 运算。
  const whiteCost = DENSITY_W * whiteLayers;
  const clipMin = f(RGB_CLIP_MIN);

  const needC = new Float32Array(count);
  const needM = new Float32Array(count);
  const needY = new Float32Array(count);
  const keepMask = new Uint8Array(count);
  // 不开时连数组都不分配 —— 默认行为一字未动。
  // v3 的中性底在三个通道上不等（各自除以自己的密度），所以要分三份。
  const neutralC = liftChromaOnly ? new Float32Array(count) : null;
  const neutralM = liftChromaOnly ? new Float32Array(count) : null;
  const neutralY = liftChromaOnly ? new Float32Array(count) : null;

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

    let lum = f(f(f(f(r + g) + b)) / 3);
    lum = lum < 0 ? 0 : lum > 1 ? 1 : lum;

    let cChr: number;
    let mChr: number;
    let yChr: number;
    let nC: number;
    let nM: number;
    let nY: number;

    if (profile === "v2") {
      // 扣掉白底吸收，除以单层密度 → 需求层数。青吸红、品红吸绿、黄吸蓝。
      let c = f(f(eR - whiteCost) / DENSITY_C);
      let m = f(f(eG - whiteCost) / DENSITY_M);
      let y = f(f(eB - whiteCost) / DENSITY_Y);
      c = c < 0 ? 0 : c;
      m = m < 0 ? 0 : m;
      y = y < 0 ? 0 : y;

      // 自适应 UCR：抽掉三色重叠出来的灰，再按该像素自身亮度回加一部分
      const k = Math.min(c, m, y);
      cChr = f(c - k);
      mChr = f(m - k);
      yChr = f(y - k);
      const kBack = f(f(k * f(1 - lum)) * 0.45);
      nC = kBack;
      nM = kBack;
      nY = kBack;
      needC[i] = f(cChr + kBack);
      needM[i] = f(mChr + kBack);
      needY[i] = f(yChr + kBack);
    } else {
      // v3：中性成分在**光密度**上取，不在层数上取
      const eK = Math.min(eR, eG, eB);
      cChr = f(f(eR - eK) / DENSITY_C);
      mChr = f(f(eG - eK) / DENSITY_M);
      yChr = f(f(eB - eK) / DENSITY_Y);

      // 中性成分扣掉白底自己的吸收；比白底还亮的部分印不出来，裁掉的只是它
      const kRaw = f(eK - whiteCost);
      const kPos = kRaw < 0 ? 0 : kRaw;
      const kBack = f(f(kPos * f(1 - lum)) * UCR_ADD_BACK);
      nC = f(kBack / DENSITY_C);
      nM = f(kBack / DENSITY_M);
      nY = f(kBack / DENSITY_Y);
      needC[i] = f(cChr + nC);
      needM[i] = f(mChr + nM);
      needY[i] = f(yChr + nY);
    }

    // 只有真正带彩色度的像素才允许抬浅层
    keepMask[i] = f(f(cChr + mChr) + yChr) >= f(keepFloor) ? 1 : 0;
    if (neutralC !== null) {
      neutralC[i] = nC;
      neutralM![i] = nM;
      neutralY![i] = nY;
    }
  }

  const W = new Int32Array(count);
  W.fill(whiteLayers);

  return {
    W,
    C: quantize(needC, MAX_LAYERS_C, gridW, dither, ditherAmount, keepMask, keepFloor, neutralC, ditherBlock, ditherScreen),
    M: quantize(needM, MAX_LAYERS_M, gridW, dither, ditherAmount, keepMask, keepFloor, neutralM, ditherBlock, ditherScreen),
    Y: quantize(needY, MAX_LAYERS_Y, gridW, dither, ditherAmount, keepMask, keepFloor, neutralY, ditherBlock, ditherScreen),
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
