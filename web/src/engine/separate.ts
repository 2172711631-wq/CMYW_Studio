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
  FILL_INK_FLOOR,
  LIFT_MIN_CHROMA,
  LINE_BLUR_MM,
  LINE_CONTRAST,
  LINE_DARK,
  LINE_INK_FLOOR,
  LINEAR_COEFFICIENT,
  MAX_LAYERS_C,
  MAX_LAYERS_M,
  MAX_LAYERS_Y,
  MIN_WHITE_LAYERS,
  RGB_CLIP_MIN,
  UCR_ADD_BACK,
} from "./constants";

const f = Math.fround;

/** 逐像素挑白层数：哪个白让渲染结果最接近目标，就用哪个。
 *
 * 白对三个通道的贡献相等，调的是中性档位不是色相；色相仍由 CMY 的取整决定。
 * 挑的时候用不带抖动/抬层的朴素取整 —— 白只影响中性档位，这个近似不会挑错。
 * 与 Python 的 _choose_white 是同一套判据、同一个运算顺序。 */
function pickWhite(
  eR: number, eG: number, eB: number, lum: number, minW: number, maxW: number,
): number {
  if (maxW <= minW) return minW;
  const eK = Math.min(eR, eG, eB);
  const tR = Math.exp(-eR), tG = Math.exp(-eG), tB = Math.exp(-eB);
  let bestW = minW;
  let bestErr = Infinity;
  for (let w = minW; w <= maxW; w += 1) {
    const wc = f(DENSITY_W * w);
    const kb = f(f(Math.max(0, f(eK - wc)) * f(1 - lum)) * UCR_ADD_BACK);
    const c = Math.min(MAX_LAYERS_C, Math.max(0, Math.round(f(f(eR - eK) / DENSITY_C + f(kb / DENSITY_C)))));
    const m = Math.min(MAX_LAYERS_M, Math.max(0, Math.round(f(f(eG - eK) / DENSITY_M + f(kb / DENSITY_M)))));
    const y = Math.min(MAX_LAYERS_Y, Math.max(0, Math.round(f(f(eB - eK) / DENSITY_Y + f(kb / DENSITY_Y)))));
    const dR = Math.exp(-(c * DENSITY_C + wc)) - tR;
    const dG = Math.exp(-(m * DENSITY_M + wc)) - tG;
    const dB = Math.exp(-(y * DENSITY_Y + wc)) - tB;
    const err = dR * dR + dG * dG + dB * dB;
    if (err < bestErr) { bestErr = err; bestW = w; }
  }
  return bestW;
}

/** 线网的级数。级数越多色调越准，但图案周期 = 级数 × 行距，太长就看得见条纹。
 *  与 Python 侧 LINE_SCREEN_LEVELS 同值。 */
const LINE_SCREEN_LEVELS = 4;

/** 把面积小于 minArea 的连通团整块清零（8 邻接，只看有没有墨）。
 *
 * 连通域的划分与用什么算法无关，所以这里的洪水填充和 Python 侧的
 * cv2.connectedComponents 会得到同一个划分，结果逐格一致。 */
function dropSmallBlobs(layer: Int32Array, gridW: number, gridH: number, minArea: number): void {
  if (minArea <= 1) return;
  const n = layer.length;
  const seen = new Uint8Array(n);
  const stack = new Int32Array(n);
  const blob = new Int32Array(n);
  for (let start = 0; start < n; start += 1) {
    if (seen[start] || layer[start] === 0) continue;
    let sp = 0;
    let bp = 0;
    stack[sp++] = start;
    seen[start] = 1;
    while (sp > 0) {
      const cur = stack[--sp];
      blob[bp++] = cur;
      const y = (cur / gridW) | 0;
      const x = cur - y * gridW;
      for (let dy = -1; dy <= 1; dy += 1) {
        const ny = y + dy;
        if (ny < 0 || ny >= gridH) continue;
        for (let dx = -1; dx <= 1; dx += 1) {
          const nx = x + dx;
          if (nx < 0 || nx >= gridW) continue;
          const j = ny * gridW + nx;
          if (seen[j] || layer[j] === 0) continue;
          seen[j] = 1;
          stack[sp++] = j;
        }
      }
    }
    if (bp < minArea) for (let k = 0; k < bp; k += 1) layer[blob[k]] = 0;
  }
}

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
  profile?: "v1" | "v2" | "v3";
  /**
   * 白层最多铺几层。不给就等于 minWhiteLayers（白钉死，也就是老行为）。
   *
   * 白对三个通道的贡献相等，所以它调的是**中性档位**、不是色相；而它的刻度比
   * 彩色墨细 4.5 倍。色相仍由 CMY 的取整决定，白只负责把三通道共同的那部分残差
   * 抹平 —— 中性灰因此不再需要靠三支粗墨去凑，也就不会凑出色偏。
   */
  whiteMax?: number;
  /**
   * 比这还小的一团彩色墨就清掉，单位是格。0 = 不清（老行为）。
   *
   * 0.1mm/px 下一两格的杂点只有 0.1–0.2mm，比 0.4 的喷嘴还小，印不出来 ——
   * 切片器只能拿缝隙填充去糊，结果就是边缘一圈杂色。这些点是抗锯齿边缘取整
   * 取出来的，画里本来没有。
   *
   * 按**面积**清而不是按宽度：细线只有一格宽也比喷嘴细，但它连成一长条，
   * 面积远大于阈值 —— 团被清掉、线留得住。中值滤波做不到这一点，它会把
   * 1–2 格宽的笔画一起抹平。
   */
  minInkArea?: number;
  /** 打印格的物理尺寸（mm）。线条判据要按毫米定，换精细度才不跑偏。 */
  mmPerPx?: number;
  /**
   * 叠色浓度：整体乘在目标光密度上。1 = 原样。
   *
   * 做成参数而不是定死一个数，是因为"够不够浓"只能拿实物跟原图比 —— 所有能算的
   * 指标都是拿模型跟模型自己比，换个参照系结论就反过来。定下来之后写死。
   */
  inkScale?: number;
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

/** 半径 r 的方框模糊，边缘按最近像素延拓。先横后竖。
 *
 * 刻意不用高斯：Python 那边要逐像素对上，方框模糊两边写出来一定一样，
 * 高斯核的系数会因为实现不同差最后一位 —— 而这个输出要拿去和门槛比大小，
 * 差一位就可能把一整条线判成不是线。
 *
 * **累加顺序是约定的一部分**：偏移从 −r 走到 +r，每加一次都落回 float32。
 * 与 Python 的 _box_blur 同序、同精度。 */
function boxBlurF32(src: Float32Array, w: number, h: number, r: number): Float32Array {
  if (r < 1) return src;
  const k = f(2 * r + 1);
  const tmp = new Float32Array(src.length);
  const out = new Float32Array(src.length);
  for (let y = 0; y < h; y += 1) {
    const row = y * w;
    for (let x = 0; x < w; x += 1) {
      let acc = 0;
      for (let d = -r; d <= r; d += 1) {
        const xx = x + d < 0 ? 0 : x + d > w - 1 ? w - 1 : x + d;
        acc = f(acc + src[row + xx]);
      }
      tmp[row + x] = f(acc / k);
    }
  }
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      let acc = 0;
      for (let d = -r; d <= r; d += 1) {
        const yy = y + d < 0 ? 0 : y + d > h - 1 ? h - 1 : y + d;
        acc = f(acc + tmp[yy * w + x]);
      }
      out[y * w + x] = f(acc / k);
    }
  }
  return out;
}

/**
 * v1：最早那版，图上是什么色就照着分什么色。
 *
 * 每个通道各算各的光密度，扣掉白底自己吸掉的那份，除以该色单层的密度，
 * 四舍五入。没有 UCR，没有抬浅层，没有清杂点 —— 一条直路。
 *
 * 它的短处是真的：白底吸收 0.44，任何通道亮过 221/255 就一层墨都拿不到，
 * 浅肉色、淡粉会整片变白。v2 和 v3 就是为了修这个才长出来的，但修的过程中
 * 把别的地方弄坏了 —— 同一张插画上 v3 会把深蓝头发推成青绿、把浅肉色抬成橘，
 * 平均色差反而从 7.10 涨到 8.15，最差 5% 从 25.5 涨到 38.5。
 * **少了颜色，比多出一个错的颜色好看**，所以默认退回这里。
 *
 * 与 Python 侧 _layers_from_rgb_v1 逐像素一致。
 */
function separateV1(
  rgb: Uint8Array | Uint8ClampedArray,
  gridW: number,
  gridH: number,
  whiteLayers: number,
  inkScale: number,
  dither: boolean,
  ditherAmount: number,
  mmPerPx: number,
): LayerSet {
  const count = gridW * gridH;
  const clipMin = f(RGB_CLIP_MIN);
  const whiteCost = f(DENSITY_W * whiteLayers);
  const W = new Int32Array(count);
  W.fill(whiteLayers);
  const needC = new Float32Array(count);
  const needM = new Float32Array(count);
  const needY = new Float32Array(count);
  const luma = new Float32Array(count);

  for (let i = 0; i < count; i += 1) {
    const p = i * 3;
    let r = f(rgb[p] / 255);
    let g = f(rgb[p + 1] / 255);
    let b = f(rgb[p + 2] / 255);
    r = r < clipMin ? clipMin : r > 1 ? 1 : r;
    g = g < clipMin ? clipMin : g > 1 ? 1 : g;
    b = b < clipMin ? clipMin : b > 1 ? 1 : b;
    const eR = f(f(f(Math.pow(f(-f(Math.log(r))), GAMMA_EXPONENT)) * LINEAR_COEFFICIENT) * inkScale);
    const eG = f(f(f(Math.pow(f(-f(Math.log(g))), GAMMA_EXPONENT)) * LINEAR_COEFFICIENT) * inkScale);
    const eB = f(f(f(Math.pow(f(-f(Math.log(b))), GAMMA_EXPONENT)) * LINEAR_COEFFICIENT) * inkScale);
    needC[i] = f(f(eR - whiteCost) / DENSITY_C);
    needM[i] = f(f(eG - whiteCost) / DENSITY_M);
    needY[i] = f(f(eB - whiteCost) / DENSITY_Y);
    luma[i] = f(f(f(r + g) + b) / 3);
  }

  // 线条优先的限墨。**必须在取整之前做**：先缩再取整只取整一次，
  // 反过来是缩完再取整、取了两遍，误差翻倍。
  const blurR = Math.max(1, Math.round(LINE_BLUR_MM / (mmPerPx > 0 ? mmPerPx : 0.1)));
  const around = boxBlurF32(luma, gridW, gridH, blurR);
  for (let i = 0; i < count; i += 1) {
    const isLine = f(around[i] - luma[i]) > f(LINE_CONTRAST) && luma[i] < f(LINE_DARK);
    const dens = f(f(f(needC[i] * DENSITY_C) + f(needM[i] * DENSITY_M)) + f(needY[i] * DENSITY_Y));
    const budget = Math.max(f(-Math.log(isLine ? LINE_INK_FLOOR : FILL_INK_FLOOR) - whiteCost), 0);
    if (dens > budget) {
      const k = f(budget / Math.max(dens, 1e-9));
      needC[i] = f(needC[i] * k);
      needM[i] = f(needM[i] * k);
      needY[i] = f(needY[i] * k);
    }
  }

  // v1 也抬浅层（Python 侧 _quantize_layers 的默认行为就是抬），门槛用模块常数。
  // keepMask 传 null = 不额外设关卡，neutral 传 null = 门槛就看需求本身。
  // 这两处必须跟 Python 一模一样，否则桌面端和网页端会出两张不同的画片。
  const q = (need: Float32Array, max: number) =>
    quantize(need, max, gridW, dither, ditherAmount, null, LAYER_KEEP_FLOOR, null, 1, "bayer");
  return {
    W,
    C: q(needC, MAX_LAYERS_C),
    M: q(needM, MAX_LAYERS_M),
    Y: q(needY, MAX_LAYERS_Y),
    gridW,
    gridH,
  };
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
  const liftChromaOnly = options.liftChromaOnly ?? false;
  const ditherBlock = Math.max(1, Math.round(options.ditherBlock ?? 1));
  const ditherScreen = options.ditherScreen ?? "bayer";
  const profile = options.profile ?? "v1";
  const whiteLayers = options.minWhiteLayers ?? MIN_WHITE_LAYERS;
  const whiteMax = Math.max(whiteLayers, options.whiteMax ?? whiteLayers);
  const minInkArea = Math.max(0, Math.round(options.minInkArea ?? 0));
  const inkScale = options.inkScale ?? 1;
  // 门槛要跟着浓度一起放大。
  // 
  //     keep_floor 判的是"这个像素**本来**有没有颜色"，是对原图的判断；
  //     而拿去比的色度已经被 ink_scale 乘过了。门槛不跟着乘，等于一调浓度
  //     就把门槛偷偷降了同样的倍数 —— 2.7 倍下，只差 4/255 的"白"（JPEG 振铃、
  //     抗锯齿溢出、本来就不是纯白的底）就被判成有颜色，1.0 倍下要差 14/255。
  //     而且抬浅层是直接抬成整整一层，所以冒出来的不是一点点墨，是实打实的黄点。
  //     乘上去之后，浓度只管印多厚，不再插手"这儿到底有没有颜色"。
  const keepFloor = f(f(options.keepFloor ?? LAYER_KEEP_FLOOR) * inkScale);

  // 白底在每个通道贡献的密度。白层可变时它是逐像素的，见 pickWhite。
  const whiteCostFixed = DENSITY_W * whiteLayers;
  const clipMin = f(RGB_CLIP_MIN);

  if (profile === "v1") {
    return separateV1(rgb, gridW, gridH, whiteLayers, inkScale, dither, ditherAmount,
      options.mmPerPx ?? 0.1);
  }

  const needC = new Float32Array(count);
  const needM = new Float32Array(count);
  const needY = new Float32Array(count);
  const W = new Int32Array(count);
  W.fill(whiteLayers);
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
    const eR = f(f(f(Math.pow(f(-f(Math.log(r))), GAMMA_EXPONENT)) * LINEAR_COEFFICIENT) * inkScale);
    const eG = f(f(f(Math.pow(f(-f(Math.log(g))), GAMMA_EXPONENT)) * LINEAR_COEFFICIENT) * inkScale);
    const eB = f(f(f(Math.pow(f(-f(Math.log(b))), GAMMA_EXPONENT)) * LINEAR_COEFFICIENT) * inkScale);

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
      // v2 的白是钉死的，不参与逐像素挑选。
      const whiteCost = whiteCostFixed;
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
      // v3：中性成分在**光密度**上取，不在层数上取。
      // 白层也在这儿逐像素定 —— 它是最细的那把尺，专管中性档位。
      const wLayers = pickWhite(eR, eG, eB, lum, whiteLayers, whiteMax);
      W[i] = wLayers;
      const whiteCost = f(DENSITY_W * wLayers);
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

    // 只有真正带彩色度的像素才允许抬浅层。第二关看**原图**的色度，
    // 不看换算出来的层数 —— 见 LIFT_MIN_CHROMA。
    // v2 是存档档案，一字不动 —— 这一关只加在 v3 上。
    const srcChroma = profile === "v2" ? 1 : f(Math.max(r, g, b) - Math.min(r, g, b));
    keepMask[i] =
      f(f(cChr + mChr) + yChr) >= f(keepFloor) && srcChroma >= f(LIFT_MIN_CHROMA) ? 1 : 0;
    if (neutralC !== null) {
      neutralC[i] = nC;
      neutralM![i] = nM;
      neutralY![i] = nY;
    }
  }

  const outC = quantize(needC, MAX_LAYERS_C, gridW, dither, ditherAmount, keepMask, keepFloor, neutralC, ditherBlock, ditherScreen);
  const outM = quantize(needM, MAX_LAYERS_M, gridW, dither, ditherAmount, keepMask, keepFloor, neutralM, ditherBlock, ditherScreen);
  const outY = quantize(needY, MAX_LAYERS_Y, gridW, dither, ditherAmount, keepMask, keepFloor, neutralY, ditherBlock, ditherScreen);

  // 清掉比喷嘴还小的彩色杂点。白不清 —— 它是底，清出洞来就漏光了。
  if (minInkArea > 1 && profile !== "v2") {
    dropSmallBlobs(outC, gridW, gridH, minInkArea);
    dropSmallBlobs(outM, gridW, gridH, minInkArea);
    dropSmallBlobs(outY, gridW, gridH, minInkArea);
  }

  return {
    W,
    C: outC,
    M: outM,
    Y: outY,
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
