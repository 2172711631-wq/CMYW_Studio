/**
 * 光学与打印常数 —— 与 Python 版 main.py 顶部严格一致。
 * Optical and printing constants — kept in exact sync with main.py.
 *
 * 改这里的任何一个值都会改变成品观感，且没有回退提示。
 * 修改前请先读 docs/how-it-works.md 里的标定流程。
 */

/** 打印层高 mm。整个颜色模型都以此为单位，改了必须重新标定所有密度。 */
export const LAYER_HEIGHT = 0.08;

/** 白色底层数，固定。负责把背光打匀。 */
export const MIN_WHITE_LAYERS = 4;

/** 每层 0.08mm 贡献的光密度，拓竹 PLA Basic 上的工作值（非仪器实测）。 */
export const DENSITY_W = 0.11;
export const DENSITY_C = 0.58;
export const DENSITY_M = 0.5;
export const DENSITY_Y = 0.68;

/** 各色最大层数。超过这个厚度收益递减且换料成本剧增。 */
export const MAX_LAYERS_C = 6;
export const MAX_LAYERS_M = 6;
export const MAX_LAYERS_Y = 6;

/** 影调曲线：不是物理，是按成品观感定的经验值。 */
export const GAMMA_EXPONENT = 0.72;
export const LINEAR_COEFFICIENT = 1.78;

/** ln(0) 是无穷大，纯黑像素会要求无限厚度，先钳住。 */
export const RGB_CLIP_MIN = 0.004;

/** 有序抖动幅度（层）。分色后只需轻抖动，过大浅灰会被铺满。 */
export const LAYER_DITHER_AMT = 0.22;

/** 低于此需求层数的浅色被舍弃；仅在有彩色度处才抬起。 */
export const LAYER_KEEP_FLOOR = 0.32;

/** 网格化前的中值滤波尺寸，把同层高像素连成片以提升矩形合并率。 */
export const MESH_MERGE_FILTER = 3;

/** 默认网格密度 mm/像素。 */
export const DEFAULT_MM_PER_PX = 0.2;

/** 网格宽高的硬边界，防止手滑打出几千万面。 */
export const GRID_MIN = 80;
export const GRID_MAX = 1600;

/** 拓竹 PLA Basic 官方色（CMYW 透光套装）。 */
export const FILAMENT_HEX = {
  C: "#0086D6",
  M: "#EC008C",
  Y: "#F4EE2A",
  W: "#FFFFFF",
} as const;

export const DEFAULT_SHELL_HEX = "#000000";

/**
 * 4×4 Bayer 有序抖动矩阵，已归一到 [-0.5, 0.5)。
 * 与 Python 的 _BAYER4 = matrix/16 - 0.5 完全一致。
 */
export const BAYER4: Float32Array = (() => {
  const raw = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
  const out = new Float32Array(16);
  for (let i = 0; i < 16; i += 1) out[i] = Math.fround(raw[i] / 16 - 0.5);
  return out;
})();

/** v3：抽掉的中性成分往回加多少。
 *
 * 印刷里 UCR 抽掉的灰由黑墨补回去，我们没有黑墨 —— 补不回来的那部分就是凭空
 * 丢掉的暗部。所以物理上唯一站得住的值是 1.0：抽多少，原样加回多少。
 *
 * 1.0 试过了，实物偏深，退回 0.75 —— 数字上 1.0 更好，但那是在灯足够亮的前提下。
 * 之前设 0.75 是为了"墨量与 v2 持平"，而 v2 的暗部本来就是虚的。那 25% 扣的
 * 全是暗部：灰阶明暗跨度 0.566 → 0.607，最暗处透射 0.078 → 0.037，
 * 调色板色差 22.3 → 19.7，代价只是墨量多 6%。与 Python 侧 UCR_ADD_BACK 同值。 */
export const UCR_ADD_BACK = 0.75;
