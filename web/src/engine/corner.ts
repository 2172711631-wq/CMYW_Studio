/**
 * 画片圆角遮罩 —— 让画片四角与灯箱外壳的圆角贴合。
 * Rounded-corner mask so the picture matches the shell's corner radius.
 *
 * 对应 Python 的 apply_rounded_corner_mask。三道保险都是踩过坑留下的：
 *
 *   1. 判据是「整个像素方块是否落在圆角矩形外」，不是只看中心点。
 *      只看中心会在圆弧上留下锯齿缺口。
 *   2. 形态学闭运算补掉圆弧上的单像素豁口。
 *   3. 外侧再留一道软边界，防止闭运算把圆角糊出外壳轮廓。
 */

/** 3×3 膨胀。越界按 0（最小值）处理，与 cv2 形态学默认边界行为一致。 */
function dilate3(src: Uint8Array, w: number, h: number): Uint8Array {
  const out = new Uint8Array(src.length);
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      let v = 0;
      for (let dy = -1; dy <= 1 && v === 0; dy += 1) {
        const sy = y + dy;
        if (sy < 0 || sy >= h) continue;
        for (let dx = -1; dx <= 1; dx += 1) {
          const sx = x + dx;
          if (sx < 0 || sx >= w) continue;
          if (src[sy * w + sx] !== 0) {
            v = 1;
            break;
          }
        }
      }
      out[y * w + x] = v;
    }
  }
  return out;
}

/** 3×3 腐蚀。越界按最大值处理（不因贴边而被削掉），同样对齐 cv2 默认行为。 */
function erode3(src: Uint8Array, w: number, h: number): Uint8Array {
  const out = new Uint8Array(src.length);
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      let v = 1;
      for (let dy = -1; dy <= 1 && v === 1; dy += 1) {
        const sy = y + dy;
        if (sy < 0 || sy >= h) continue;
        for (let dx = -1; dx <= 1; dx += 1) {
          const sx = x + dx;
          if (sx < 0 || sx >= w) continue;
          if (src[sy * w + sx] === 0) {
            v = 0;
            break;
          }
        }
      }
      out[y * w + x] = v;
    }
  }
  return out;
}

/**
 * 算出「保留」掩码：1 = 该像素留下，0 = 落在圆角外要切掉。
 *
 * @param physicalWidthMm 画片实际宽度 mm（高度按网格比例推出）
 * @param cornerRadiusMm  圆角半径 mm，≤0 表示直角
 */
export function roundedCornerKeepMask(
  gridW: number,
  gridH: number,
  physicalWidthMm: number,
  cornerRadiusMm: number,
): Uint8Array | null {
  if (cornerRadiusMm <= 1e-6 || gridW < 2 || gridH < 2) return null;

  const pixel = physicalWidthMm / gridW;
  const w = physicalWidthMm;
  const h = (physicalWidthMm * gridH) / gridW;
  const r = Math.min(cornerRadiusMm, w * 0.5 - pixel * 0.25, h * 0.5 - pixel * 0.25);
  if (r <= 1e-6) return null;

  const half = pixel * 0.5;
  const r2 = r * r;
  const rSoft = r + 0.35 * pixel;
  const rSoft2 = rSoft * rSoft;

  const keep = new Uint8Array(gridW * gridH);
  const softOut = new Uint8Array(gridW * gridH);

  // 四个圆心，与 Python 的四次 _corner_cut 一一对应
  const corners: Array<[number, number, (x: number, y: number) => boolean]> = [
    [r, r, (x, y) => x < r && y < r],
    [w - r, r, (x, y) => x > w - r && y < r],
    [w - r, h - r, (x, y) => x > w - r && y > h - r],
    [r, h - r, (x, y) => x < r && y > h - r],
  ];

  for (let gy = 0; gy < gridH; gy += 1) {
    // 注意 Y 轴翻转：图像行 0 在顶部，实体坐标 Y 向上
    const yy = (gridH - gy - 0.5) * pixel;
    for (let gx = 0; gx < gridW; gx += 1) {
      const xx = (gx + 0.5) * pixel;
      const idx = gy * gridW + gx;

      let outside = false;
      let soft = false;
      for (const [cx, cy, inQuad] of corners) {
        if (!inQuad(xx, yy)) continue;
        // 像素方块上离圆心最近的点：方块完全在圆外才切
        const nx = Math.min(Math.max(cx, xx - half), xx + half);
        const ny = Math.min(Math.max(cy, yy - half), yy + half);
        const d2 = (nx - cx) * (nx - cx) + (ny - cy) * (ny - cy);
        if (d2 > r2) outside = true;
        // 软边界按中心点算，容许圆角外约 0.35 像素
        const c2 = (xx - cx) * (xx - cx) + (yy - cy) * (yy - cy);
        if (c2 > rSoft2) soft = true;
      }
      keep[idx] = outside ? 0 : 1;
      softOut[idx] = soft ? 1 : 0;
    }
  }

  // 闭运算（先膨胀后腐蚀）补掉圆弧上的单像素豁口
  const closed = erode3(dilate3(keep, gridW, gridH), gridW, gridH);

  const result = new Uint8Array(gridW * gridH);
  for (let i = 0; i < result.length; i += 1) {
    result[i] = closed[i] !== 0 && softOut[i] === 0 ? 1 : 0;
  }
  return result;
}

/** 按保留掩码就地清零若干层高图。 */
export function applyKeepMask(mask: Uint8Array | null, ...layers: Int32Array[]): void {
  if (!mask) return;
  for (const layer of layers) {
    for (let i = 0; i < layer.length; i += 1) {
      if (mask[i] === 0) layer[i] = 0;
    }
  }
}
