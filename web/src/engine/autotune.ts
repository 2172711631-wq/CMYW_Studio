/**
 * 按画风自动取值 —— 分色引擎的「策略层」。
 *
 * 引擎本身（separate.ts）的默认参数一个都不动，parity fixture 钉的就是它们。
 * 这里是应用层怎么**选**参数：量一下这张图有多"平"，在照片和插画之间连续取值。
 *
 * 抽成独立模块而不是留在 studio.ts 里，是因为它必须能被测到 ——
 * Python 侧 main.py 有一份一模一样的实现，两边一旦分叉，同一张图桌面 App
 * 和网站就会出两张不一样的画片，而这种分叉不会报错，只会让人某天发现颜色不对。
 */

import {
  DEFAULT_MM_PER_PX,
  LAYER_DITHER_AMT,
  LAYER_KEEP_FLOOR,
  MESH_MERGE_FILTER,
} from "./constants";

/** 量这张图有多"平"：相邻像素几乎没有差别的比例。
 *
 * 平色插画大片同色 → 高；照片就算降采样过，也仍然到处是细微渐变 → 低。
 * 拿它在"照片"和"插画"之间连续取值，比让人自己判断可靠，也比二选一细腻 ——
 * 真实素材（带纹理的厚涂、有噪点的扫描线稿）大多落在中间。
 */
export function flatnessOf(rgb: Uint8ClampedArray, w: number, h: number): number {
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
export function artScore(flat: number): number {
  return Math.min(1, Math.max(0, (flat - 0.35) / 0.4));
}

/** 抖动幅度：按平坦度在照片档和插画档之间连续取值。
 *
 * 实测过一件要紧的事：**抖动幅度不到一整个量化步长，等于完全没开**。
 * 0.22 / 0.5 / 0.7 三档量出来的色调误差都是 0.230，和关掉一模一样 ——
 * 因为抖动只有跨过一整步才可能改变取整的结果。
 *
 * 所以这里只有两个真实档位：这个（≈ 关）和满幅。满幅确实把色调误差压到 0.041，
 * 但相邻格子有 7% 的层数不同，落到实物上就是满脸 0.4mm 的网点，实测不能接受。
 * 真正的出路是让量化台阶变细，不是在粗台阶上抖。 */
export function ditherAmountFor(flat: number): number {
  return LAYER_DITHER_AMT * (1 - artScore(flat));
}

/** 浅色保留阈值：越"平"压得越低，最低压到默认值的两成。
 *
 * 这条线在照片里挡的是噪点，在线稿里挡掉的却是淡线和抗锯齿边 —— 而平色画面
 * 本来就没有噪点要挡。 */
export function keepFloorFor(flat: number): number {
  return LAYER_KEEP_FLOOR * (1 - 0.8 * artScore(flat));
}

/** 门槛一降就必须同时打开它，否则降下来的门槛会被中性底顶穿。
 *
 * need = 这一色自己的彩色度 + kBack（三色平摊的中性成分）。门槛压在 need 上时，
 * 彩色度为 0 的通道也能靠 kBack 顶过去，被抬成整整一层：饱和蓝里多一层黄就发绿，
 * 中性灰细线里多一层品红就发粉。而这两种情况**只在门槛降下来之后才够得着**，
 * 所以这两件事是同一个开关的两半，不该分开。 */
export function liftChromaOnlyFor(flat: number): boolean {
  return keepFloorFor(flat) < LAYER_KEEP_FLOOR;
}

/** 网格化前的中值滤波：线稿要关掉，否则 1–2 像素宽的笔画会被抹平。
 *  代价是矩形变多、三角形涨 —— 面板上的"三角面"读数就是这个成本。 */
export function mergeFilterFor(flat: number): number {
  return artScore(flat) > 0.5 ? 1 : MESH_MERGE_FILTER;
}

/** 喷嘴直径。XY 方向上比它细的东西印不出来 —— 要么消失，要么被挤成它这么粗。 */
export const NOZZLE_MM = 0.4;

/** 抖动格子要多大：按喷嘴来，不是按网格来。
 *
 * 抖动是拿相邻格子的层数高低差去换视觉上的中间色。格子比喷嘴小的时候这笔交易
 * 根本不成立 —— 0.1mm/px 下一个孤立的抖动点只有喷嘴面积的十六分之一，
 * 印不出来，只会变成一堆多余的三角形，或者被挤成 0.4mm 的一颗麻点。
 *
 * 实测 0.1mm/px、插画度 52% 时，亚喷嘴的等值连通块从 1705 个降到 24 个。 */
export function ditherBlockFor(mmPerPx: number): number {
  if (!(mmPerPx > 0)) return 1;
  return Math.max(1, Math.round(NOZZLE_MM / mmPerPx));
}

/** 用网点，按喷嘴尺寸放大。
 *
 * 中间试过线网（每行一条连续挤出线），几何量确实只有网点的四分之一，
 * 但**图案周期 = 级数 × 行距 = 1.6mm**，横在 97mm 宽的画上就是六十道杠，
 * 脸上一眼就看得见。线网适合行距能压到看不见的场合，这儿压不下去 ——
 * 再细就掉到喷嘴以下了。
 *
 * 换线网本来是为了救「切不动」，而切不动的真正原因是导出没收到抖动块参数，
 * 跑成了格子尺度的网点（750 万三角形）。那个修好之后，按喷嘴放大的网点是
 * 66 万三角形，切得动，色调误差也更小（0.041 对线网的 0.094）。 */
export function ditherScreenFor(flat: number): "bayer" | "line" {
  void flat;
  return "bayer";
}

/** 网格密度 mm/px：插画靠细线吃饭，格子给密一点。
 *
 * 照片是连续调，标准密度就够，再密只是把三角形和文件撑大。
 * 喷嘴 0.4mm 是物理下限，0.1 已经比它细一倍，继续加不增加细节。 */
export function mmPerPxFor(flat: number): number {
  const k = artScore(flat);
  return k > 0.6 ? 0.1 : k > 0.3 ? 0.15 : DEFAULT_MM_PER_PX;
}
