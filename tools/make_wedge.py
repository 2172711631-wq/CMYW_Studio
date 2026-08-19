# -*- coding: utf-8 -*-
"""密度阶梯标定片：直接量 DENSITY_W 与 CMY 三联的中性密度。

第 1–2 行 = 纯白色 N 层（N = 4,6,8,10,12,16,20,24）
第 3–4 行 = 白 4 层 + C/M/Y 各 k 层（k = 0..6，末格重复 0 做重复性参照）

打出来背光拍一张，量每格亮度 → 取 ln，斜率就是每层的光学密度。
这一个数决定「白色能不能当 K 通道」。
"""
import os, sys, io
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, cv2
import main as M

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calibration")
os.makedirs(OUT, exist_ok=True)
TOP = [4, 6, 8, 10, 12, 16, 20, 24]        # 纯白层数
BOT = [0, 1, 2, 3, 4, 5, 6, 0]             # 白4 之上再叠 CMY 各 k 层


def build(width_mm=120.0, height_mm=160.0):
    gw = M.grid_w_for_print(width_mm, 300)
    px = width_mm / gw
    gh = int(round(height_mm / px))
    cols, rows, gap = 4, 4, 4
    cell = (gw - gap * (cols + 1)) // cols
    rowh = (gh - gap * (rows + 1)) // rows
    z = lambda: np.zeros((gh, gw), np.int32)
    w, c, m, y = z(), z(), z(), z()
    w[:] = 4                                # 整片底白 4 层，保证连成一片

    def box(idx):
        r, i = divmod(idx, cols)
        x0 = gap + i * (cell + gap)
        y0 = gap + r * (rowh + gap)
        return slice(y0, y0 + rowh), slice(x0, x0 + cell)

    for i, n in enumerate(TOP):             # 前 8 格（上两行）＝纯白阶梯
        w[box(i)] = n
    for i, k in enumerate(BOT):             # 后 8 格（下两行）＝CMY 阶梯
        sl = box(8 + i)
        c[sl] = k
        m[sl] = k
        y[sl] = k

    sim = M.simulate_transmitted_rgb(w, y, m, c, brightness_ratio=1.0, stretch=False)
    prev = (np.clip(sim * 1.8, 0, 1) * 255).astype(np.uint8)
    prev = cv2.resize(prev, (gw * 2, gh * 2), interpolation=cv2.INTER_NEAREST)
    png = os.path.join(OUT, "密度阶梯_模拟预览.png")
    ok, buf = cv2.imencode(".png", cv2.cvtColor(prev, cv2.COLOR_RGB2BGR))
    open(png, "wb").write(buf.tobytes())    # 中文路径下 imwrite 会静默失败

    layers = {"C": c, "M": m, "Y": y, "W": w, "shape": (gh, gw, 3)}
    layers["stats"] = M.layer_stats(layers)
    shell = M.ShellParams(enabled=True, wall_thickness=3.0, corner_radius=5.0,
                          shell_depth=18.0, fit_clearance=0.2,
                          shell_color_hex=M.normalize_hex_color(M.BAMBU_PLA_BLACK))
    mf = os.path.join(OUT, "密度阶梯标定片.3mf")
    tris = M.save_as_bambu_3mf(mf, layers, gw, width_mm,
                               shell_params=shell, target_height_mm=height_mm)

    zmax = int(M.max_layer_stack_from_layers(w, y, m, c))
    d = (M.DENSITY_C + M.DENSITY_M + M.DENSITY_Y) / 3
    lines = [
        f"实物 {width_mm:.0f} × {height_mm:.0f} mm   格子 {cell*px:.0f} × {rowh*px:.0f} mm   三角面 {tris}",
        f"最高栈 {zmax} 层 = {zmax*0.08:.2f} mm",
        "",
        "第 1–2 行（纯白层数）　：" + "  ".join(f"{n:>2}" for n in TOP),
        "  模型预测透光率　　　：" + "  ".join(f"{np.exp(-M.DENSITY_W*n):.2f}" for n in TOP),
        "第 3–4 行（白4+CMY各k）：" + "  ".join(f"{k:>2}" for k in BOT),
        "  模型预测透光率　　　：" + "  ".join(f"{np.exp(-(M.DENSITY_W*4+d*k)):.2f}" for k in BOT),
        "",
        f"每层中性密度：白 {M.DENSITY_W:.3f}/层 · CMY 三联 {d:.3f}（占 3 层 → {d/3:.3f}/层）",
        f"→ 模型认为白色做中性密度的层效率只有 CMY 三联的 {M.DENSITY_W/(d/3):.2f} 倍",
        "",
        f"  {mf}",
        f"  {png}",
    ]
    print("\n".join(lines))


if __name__ == "__main__":
    build(float(sys.argv[1]) if len(sys.argv) > 1 else 120.0,
          float(sys.argv[2]) if len(sys.argv) > 2 else 160.0)
