/**
 * 透光模拟 —— 预览「点亮后」的样子。
 * Backlit simulation: what the print will look like with the light on.
 *
 * 把分色结果反过来走一遍光学模型：已知每个像素各色多少层，算出透射光谱。
 * 对应 Python 的 simulate_transmitted_rgb + preview_texture.enhance_lit_rgb。
 *
 * 这一步的价值在于它算的是**成品**而不是原图：原图好看不代表打出来好看，
 * 7 级量化、UCR、白底都会改变观感。让人在下载前就看到真实结果，
 * 比打废一版再回来调要好得多。
 */

import { DENSITY_C, DENSITY_M, DENSITY_W, DENSITY_Y } from "./constants";
import type { LayerSet } from "./separate";

/** 相邻通道的轻微串扰，经验值，不加会显得过于干净不像实物。 */
const CROSSTALK_RM = 0.04;
const CROSSTALK_GY = 0.02;
const CROSSTALK_BC = 0.03;

export interface SimulateOptions {
  /** 背光强度。1.6 接近常见 USB 灯板 */
  brightness?: number;
  /** 加散射与暗角，更接近肉眼观感；导出用图时可关 */
  enhance?: boolean;
}

/**
 * 层数 → 透射后的 RGB。
 * @returns RGBA 数据，可直接 putImageData
 */
export function simulateLit(layers: LayerSet, options: SimulateOptions = {}): ImageData {
  const { brightness = 1.6, enhance = true } = options;
  const { W, Y, M, C, gridW, gridH } = layers;
  const n = gridW * gridH;

  const rgb = new Float32Array(n * 3);
  for (let i = 0; i < n; i += 1) {
    const w = W[i], y = Y[i], m = M[i], c = C[i];
    const eR = DENSITY_C * c + DENSITY_W * w + CROSSTALK_RM * m;
    const eG = DENSITY_M * m + DENSITY_W * w + CROSSTALK_GY * y;
    const eB = DENSITY_Y * y + DENSITY_W * w + CROSSTALK_BC * c;
    rgb[i * 3] = Math.exp(-eR);
    rgb[i * 3 + 1] = Math.exp(-eG);
    rgb[i * 3 + 2] = Math.exp(-eB);
  }

  // 保留光学相对亮度，不做全图拉伸 —— 拉满会把画面拉成海报色块，
  // 看着讨喜但和实物对不上，反而误导。
  for (let i = 0; i < rgb.length; i += 1) {
    rgb[i] = Math.min(1, Math.max(0, rgb[i] * brightness));
  }

  if (enhance) applyGlow(rgb, gridW, gridH);

  const out = new ImageData(gridW, gridH);
  for (let i = 0; i < n; i += 1) {
    out.data[i * 4] = Math.round(rgb[i * 3] * 255);
    out.data[i * 4 + 1] = Math.round(rgb[i * 3 + 1] * 255);
    out.data[i * 4 + 2] = Math.round(rgb[i * 3 + 2] * 255);
    // 四层全 0 = 这一格没有任何材料，是被形状遮罩切掉的部分。
    // 白底默认铺满整片，所以画面内部不可能四层全 0，这个判据不会误伤。
    // 不置透明的话，圆形画片周围会渲染成一圈纯白，看着像方的。
    out.data[i * 4 + 3] =
      layers.W[i] === 0 && layers.C[i] === 0 && layers.M[i] === 0 && layers.Y[i] === 0
        ? 0
        : 255;
  }
  return out;
}

/**
 * 轻微散射 + 高光溢出 + 暗角。
 *
 * 实物是有厚度的塑料，光在里面会散开一点，边缘也比中心暗。
 * 幅度刻意压得很小 —— 加太多就变成滤镜，把脸吹爆。
 */
function applyGlow(rgb: Float32Array, w: number, h: number): void {
  const soft = boxBlur(rgb, w, h, Math.max(1, Math.round(Math.min(w, h) * 0.004)));
  for (let i = 0; i < rgb.length; i += 1) {
    rgb[i] = rgb[i] * 0.88 + soft[i] * 0.12;
  }

  // 只让高光溢出，暗部不动
  const bloomSrc = new Float32Array(rgb.length);
  for (let i = 0; i < rgb.length; i += 3) {
    const luma = Math.max(rgb[i], rgb[i + 1], rgb[i + 2]);
    const k = Math.min(1, Math.max(0, (luma - 0.72) / 0.28));
    bloomSrc[i] = rgb[i] * k;
    bloomSrc[i + 1] = rgb[i + 1] * k;
    bloomSrc[i + 2] = rgb[i + 2] * k;
  }
  const bloom = boxBlur(bloomSrc, w, h, Math.max(2, Math.round(Math.min(w, h) * 0.014)));

  const cx = (w - 1) / 2;
  const cy = (h - 1) / 2;
  const maxD = Math.hypot(cx, cy);
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      const i = (y * w + x) * 3;
      // 暗角：灯板边缘本来就比中心暗
      const vig = 1 - 0.14 * (Math.hypot(x - cx, y - cy) / maxD) ** 2.2;
      for (let ch = 0; ch < 3; ch += 1) {
        rgb[i + ch] = Math.min(1, (rgb[i + ch] + bloom[i + ch] * 0.35) * vig);
      }
    }
  }
}

/** 可分离盒式模糊，够快也够用，不值得为预览上高斯。 */
function boxBlur(src: Float32Array, w: number, h: number, radius: number): Float32Array {
  if (radius < 1) return src.slice();
  const tmp = new Float32Array(src.length);
  const out = new Float32Array(src.length);
  const span = radius * 2 + 1;

  for (let y = 0; y < h; y += 1) {
    for (let ch = 0; ch < 3; ch += 1) {
      let sum = 0;
      for (let x = -radius; x <= radius; x += 1) {
        sum += src[(y * w + Math.min(w - 1, Math.max(0, x))) * 3 + ch];
      }
      for (let x = 0; x < w; x += 1) {
        tmp[(y * w + x) * 3 + ch] = sum / span;
        const add = src[(y * w + Math.min(w - 1, x + radius + 1)) * 3 + ch];
        const sub = src[(y * w + Math.max(0, x - radius)) * 3 + ch];
        sum += add - sub;
      }
    }
  }

  for (let x = 0; x < w; x += 1) {
    for (let ch = 0; ch < 3; ch += 1) {
      let sum = 0;
      for (let y = -radius; y <= radius; y += 1) {
        sum += tmp[(Math.min(h - 1, Math.max(0, y)) * w + x) * 3 + ch];
      }
      for (let y = 0; y < h; y += 1) {
        out[(y * w + x) * 3 + ch] = sum / span;
        const add = tmp[(Math.min(h - 1, y + radius + 1) * w + x) * 3 + ch];
        const sub = tmp[(Math.max(0, y - radius) * w + x) * 3 + ch];
        sum += add - sub;
      }
    }
  }
  return out;
}
