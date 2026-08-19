# -*- coding: utf-8 -*-
"""量印好的密度阶梯片：一张背光照片 → 四个耗材的每层光学密度。

用法：
  1. 把「密度阶梯标定片.3mf」打出来，装进灯箱，正对拍一张（别开闪光、别用 HDR、
     手机锁定曝光；能拍 RAW 更好）。
  2. 裁到只剩画片本身（四条边贴着画片外缘），存成 wedge_photo.jpg。
  3. py -3.11 白底实验/measure_wedge.py 白底实验/wedge_photo.jpg

输出：拟合出的 DENSITY_W / C / M / Y，和现在 main.py 里的常数对比。
"""
import os, sys, io
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, cv2
import main as M
from make_wedge import TOP, BOT

GW, WMM, HMM = 300, 120.0, 160.0           # 与 make_wedge 的默认一致
COLS = ROWS = 4
GAP = 4


def cell_boxes(h, w):
    """按 make_wedge 的几何，把照片按比例切成 16 格（取中心 60% 采样）。"""
    px = WMM / GW
    gh = int(round(HMM / px))
    cell = (GW - GAP * (COLS + 1)) // COLS
    rowh = (gh - GAP * (ROWS + 1)) // ROWS
    out = []
    for idx in range(16):
        r, i = divmod(idx, COLS)
        x0 = (GAP + i * (cell + GAP)) / GW
        y0 = (GAP + r * (rowh + GAP)) / gh
        x1, y1 = x0 + cell / GW, y0 + rowh / gh
        # 往里收 20%，避开边缘漏光和圆角
        dx, dy = (x1 - x0) * 0.2, (y1 - y0) * 0.2
        out.append((int((y0 + dy) * h), int((y1 - dy) * h),
                    int((x0 + dx) * w), int((x1 - dx) * w)))
    return out


def fit(xs, ys):
    """ys = A·exp(-D·xs) → 对 ln 做最小二乘，返回每层密度 D。"""
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    ok = ys > 1e-4
    if ok.sum() < 2:
        return float('nan')
    A = np.stack([xs[ok], np.ones(ok.sum())], 1)
    slope, _ = np.linalg.lstsq(A, np.log(ys[ok]), rcond=None)[0]
    return -float(slope)


def main(path):
    buf = np.frombuffer(open(path, 'rb').read(), np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"读不出图片：{path}")
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    # sRGB → 线性光，否则拟合出来的密度会被 gamma 带偏
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    h, w = lin.shape[:2]
    boxes = cell_boxes(h, w)
    vals = [lin[y0:y1, x0:x1].reshape(-1, 3).mean(0) for y0, y1, x0, x1 in boxes]

    print(f"照片 {w}×{h}\n")
    print("第 1–2 行 纯白阶梯      白层   R      G      B")
    for n, v in zip(TOP, vals[:8]):
        print(f"                        {n:>3}  {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}")
    print("\n第 3–4 行 CMY 阶梯     CMY层   R      G      B")
    for k, v in zip(BOT, vals[8:]):
        print(f"                        {k:>3}  {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}")

    # 白：三通道一起拟（白是中性的，三条曲线斜率应当一致）
    wl = np.array(TOP, float)
    dw = [fit(wl, [v[ch] for v in vals[:8]]) for ch in range(3)]
    # CMY：C 吃红、M 吃绿、Y 吃蓝；白底恒为 4 层，作为常数被截距吸收
    kk = np.array(BOT[:7], float)
    dc = fit(kk, [v[0] for v in vals[8:15]])
    dm = fit(kk, [v[1] for v in vals[8:15]])
    dy = fit(kk, [v[2] for v in vals[8:15]])

    # CMY 阶梯三色同时加层，所以斜率里混进了 main.py 的串扰项
    # (e_r += 0.04·l_m, e_g += 0.02·l_y, e_b += 0.03·l_c) —— 扣掉才是本色密度
    dc_p, dm_p, dy_p = dc - 0.04, dm - 0.02, dy - 0.03

    print("\n拟合结果（每层光学密度）")
    print(f"  DENSITY_W  实测 {np.mean(dw):.3f}  (R{dw[0]:.3f}/G{dw[1]:.3f}/B{dw[2]:.3f})"
          f"   现值 {M.DENSITY_W:.3f}")
    print(f"  DENSITY_C  实测 {dc_p:.3f}（原始斜率 {dc:.3f} 扣 0.04 串扰）   现值 {M.DENSITY_C:.3f}")
    print(f"  DENSITY_M  实测 {dm_p:.3f}（原始斜率 {dm:.3f} 扣 0.02 串扰）   现值 {M.DENSITY_M:.3f}")
    print(f"  DENSITY_Y  实测 {dy_p:.3f}（原始斜率 {dy:.3f} 扣 0.03 串扰）   现值 {M.DENSITY_Y:.3f}")

    dw_m, d3 = float(np.mean(dw)), (dc_p + dm_p + dy_p) / 3
    print(f"\n白的层效率 / CMY 三联的层效率 = {dw_m/(d3/3):.2f}")
    if dw_m / (d3 / 3) >= 1.0:
        print("  ≥1 → 白色做中性密度比 CMY 三联更省层，「白当 K」值得做。")
    else:
        print("  <1 → 白色做中性密度更费层，「白当 K」不成立（当前模型给的是 0.56）。")
    print("\n注意：白色同时是扩散层，这里只量了吸收。若纯白 20/24 格明显发糊，")
    print("      说明散射已经吃掉锐度，那是比密度更早触发的上限。")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "wedge_photo.jpg"))
