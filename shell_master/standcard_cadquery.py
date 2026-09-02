"""立式薄画框（侧光导光板款）—— 参数母本。

和 shell_cadquery.py 的直下式灯箱是两种东西：

    直下式        灯板正对画片，靠 15.5mm 空气距离混光，厚 18mm
    本款          光从底边进导光板，网点把它散向正面，厚 9.5mm

之所以能薄，是因为光不再需要"距离"来铺开，改由导光板的网点密度梯度来铺。
代价是必须买带网点的导光板（PMMA 挤出板，均匀磨砂做不到梯度），
以及底边一段藏在压边后面的混光区。

两个零件：

    框体   standcard_body.stl     立着打，底座贴床，无支撑
    顶压条 standcard_topbar.stl   平着打，几分钟

顶压条是结构上必要的，不是装饰。画片要四边都压住才叫卡槽，而正面压边如果直接
连成一整圈，取景窗顶边就成了一条横跨整个窗口的悬空横梁——立着打是跨不过去的桥，
平着打又轮到别处塌。把顶边那一条拆成单独的压条，两个零件各自都不含悬空。
顺带它还是换画片的方式：抬掉压条，画片就能从顶上抽出来。

叠层（从正面往背面数）：

    压边 1.6 │ 画片 2.2 │ 扩散片 0.2 + 导光板 3.0 + 反射膜 0.2 + 余量 0.3 │ 背壁 2.0
                          └────────── 常驻，不随画片抽换 ──────────┘

高度方向（默认参数）：

    z=138  ┬ 框顶 / 画片顶 —— 顶压条盖在这儿，前唇往下压住画片顶边 6mm
           │ 可见画面 108
    z=24   ┼ 取景窗下沿
           │ 底边压边 6
    z=18   ┼ 画片底边，落在前挡条顶面上
           │ 结构混光区 6
    z=12   ┼ 导光板底边，坐在两端 5mm 承台上
           │ 灯条腔 3
    z=9    ┼ 灯条躺在这里，发光面朝上，线从一端正后方穿出
           │ 底座实心（兼配重）
    z=0    ┴ 桌面

    导光板底边到可见画面下沿一共 12mm，灯珠的扇形亮斑在这一段里摊平。

坐标系：X = 宽（左右对称，原点在中线），Y = 深（正面 y=0 往背面增大），Z = 上。
"""

from __future__ import annotations

import argparse
import os

import cadquery as cq

# =============================================================================
# 参数
# =============================================================================

# —— 画片（消耗品）——
ART_W = 160.0
ART_H = 120.0
# 画片实厚最多 22 层 × 0.08 = 1.76；槽留到 2.2 是为了插拔顺手，不是为了公差
ART_SLOT_T = 2.2

# —— 光学件（常驻，装一次不再动）——
LGP_T = 3.0          # 导光板厚。3mm 是甜点：再薄耦合不进光，再厚这框就不薄了
DIFFUSER_T = 0.2     # 扩散片，压在导光板正面，盖掉网点
REFLECTOR_T = 0.2    # 反射膜，贴在导光板背面，把漏向背面的光弹回来
OPTICS_SLOP = 0.3    # 三层叠起来的插拔余量
OPTICS_T = DIFFUSER_T + LGP_T + REFLECTOR_T + OPTICS_SLOP

# 结构混光区：画片底边到导光板底边。再加上正面底边压边 BEZEL_LAP_BOTTOM，
# 才是光学上真正起作用的"导光板底边到可见画面"的距离。
MIX_H = 6.0

# —— 灯条 ——
# 灯条腔就是光学层往下延长的一段，不额外加宽：灯条只能从顶部顺着 3.7mm 的槽
# 放下去，腔再宽也塞不进更宽的灯条。所以灯条 PCB 必须 ≤3.5mm（导光板背光条规格）。
LED_CH_H = 3.0       # 灯条腔净高：灯条含背胶约 1.5，剩下的是发光面到导光板边的间隙
LED_SHOULDER = 5.0   # 两端承台宽。导光板坐在它上面；代价是两端 5mm 暗角，
                     # 但它落在混光区里，光横向摊开后基本看不出来
CABLE_W = 6.0
CABLE_H = 3.0
CABLE_FROM_END = 1.0      # 走线口开在灯条一端正后方，线出了焊点直接往后走
LED_TOP_BELOW_BASE = 3.0  # 走线槽顶到底座顶面留够厚度，1mm 的天花板太薄

# —— 结构 ——
BEZEL_T = 1.6        # 正面压边壁厚
BACK_T = 2.0         # 背壁。插画片时手劲全压在它上面，1.6 偏软
SIDE_T = 3.0         # 侧壁
BEZEL_LAP_X = 6.0    # 正面左右各压住画片多少。这一条决定"像不像一个画框"
BEZEL_LAP_BOTTOM = 6.0
FIT = 0.3            # 槽的横向公差（画片、导光板共用）
BODY_R = 4.0         # 框体竖向圆角
BASE_R = 6.0         # 底座竖向圆角

BASE_H = 15.0
BASE_D = 62.0        # 底座进深，直接决定倾覆角，verify 脚本会按质心实测
BASE_EXTRA_W = 3.0   # 底座每侧比框体宽出多少

LEAD_IN = 0.6        # 顶部插入口的导角

# —— 顶压条 ——
BAR_LAP = 6.0           # 前唇往下压住画片顶边多少，和左右压边同宽才匀称
BAR_PLATE_T = 2.5       # 盖在框顶面上的那块板厚
BAR_TONGUE_T = 3.4      # 插进光学层槽的舌头厚度（槽 3.7，留 0.3 松动）
BAR_TONGUE_INSET = 5.0  # 舌头比槽两端各短多少
BAR_LIP_GAP = 0.2       # 前唇与取景窗左右边的单侧间隙


def params() -> dict[str, float]:
    """把所有派生尺寸算出来，供建模、料单、自检共用。"""
    pocket_w = ART_W + FIT
    body_w = pocket_w + 2.0 * SIDE_T
    body_d = BEZEL_T + ART_SLOT_T + OPTICS_T + BACK_T

    y_art0 = BEZEL_T
    y_art1 = y_art0 + ART_SLOT_T
    y_opt0 = y_art1
    y_opt1 = y_opt0 + OPTICS_T

    # 导光板在光学层里的实际位置：扩散片在前、反射膜在后
    y_lgp0 = y_opt0 + DIFFUSER_T
    y_lgp1 = y_lgp0 + LGP_T

    z_led = BASE_H - LED_CH_H - LED_TOP_BELOW_BASE
    z_lgp = z_led + LED_CH_H
    z_art = z_lgp + MIX_H
    z_top = z_art + ART_H

    # 导光板只需要照亮看得见的部分，顶上 BAR_LAP 那一段让给顶压条的舌头
    lgp_top = z_top - BAR_LAP

    base_y0 = -(BASE_D - body_d) / 2.0

    return {
        "pocket_w": pocket_w,
        "body_w": body_w,
        "body_d": body_d,
        "base_w": body_w + 2.0 * BASE_EXTRA_W,
        "y_art0": y_art0,
        "y_art1": y_art1,
        "y_opt0": y_opt0,
        "y_opt1": y_opt1,
        "y_lgp0": y_lgp0,
        "y_lgp1": y_lgp1,
        "z_led": z_led,
        "z_lgp": z_lgp,
        "z_art": z_art,
        "z_top": z_top,
        "lgp_top": lgp_top,
        "lgp_w": ART_W,
        "lgp_h": lgp_top - z_lgp,
        "base_y0": base_y0,
        "base_y1": base_y0 + BASE_D,
        "window_w": ART_W - 2.0 * BEZEL_LAP_X,
        "window_z0": z_art + BEZEL_LAP_BOTTOM,
        "visible_h": (z_top - BAR_LAP) - (z_art + BEZEL_LAP_BOTTOM),
        "led_len": ART_W - 2.0 * LED_SHOULDER,
        "cable_x": -(ART_W / 2.0 - LED_SHOULDER - CABLE_W / 2.0 - CABLE_FROM_END),
        # 光学上真正的混光距离：导光板底边 → 可见画面下沿
        "mix_total": MIX_H + BEZEL_LAP_BOTTOM,
    }


# =============================================================================
# 建模
# =============================================================================

def _box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .box(x1 - x0, y1 - y0, z1 - z0, centered=False)
        .translate((x0, y0, z0))
    )


def _rounded_box(
    x0: float, x1: float, y0: float, y1: float, z0: float, z1: float, r: float
) -> cq.Workplane:
    solid = _box(x0, x1, y0, y1, z0, z1)
    if r > 1e-4:
        try:
            solid = solid.edges("|Z").fillet(r)
        except Exception:  # noqa: BLE001 - 圆角失败就用直角，形状仍然可打印
            pass
    return solid


def build_body() -> cq.Workplane:
    """框体。立着打，底座贴床；全件无悬空，走线孔那 6mm 天花板是短桥接。"""
    p = params()
    hw_body = p["body_w"] / 2.0
    hw_base = p["base_w"] / 2.0
    hw_pocket = p["pocket_w"] / 2.0

    # 框体从 z=0 起，穿过底座区一直到顶；底座是套在它外面的一圈实心
    body = _rounded_box(-hw_body, hw_body, 0.0, p["body_d"], 0.0, p["z_top"], BODY_R)
    base = _rounded_box(-hw_base, hw_base, p["base_y0"], p["base_y1"], 0.0, BASE_H, BASE_R)
    solid = body.union(base)

    # 1) 光学层槽：导光板底边以上开通到顶
    solid = solid.cut(
        _box(-hw_pocket, hw_pocket, p["y_opt0"], p["y_opt1"], p["z_lgp"], p["z_top"] + 1.0)
    )

    # 2) 画片槽：画片底边以上开通到顶。它比光学层短，让出下面的混光区
    solid = solid.cut(
        _box(-hw_pocket, hw_pocket, p["y_art0"], p["y_art1"], p["z_art"], p["z_top"] + 1.0)
    )

    # 3) 正面取景窗。左右与底边各留一条压边；顶边一直开到框顶，那一条由顶压条来做，
    #    否则这里会变成一条横跨整个窗口的悬空横梁
    solid = solid.cut(
        _box(
            -p["window_w"] / 2.0,
            p["window_w"] / 2.0,
            -1.0,
            p["y_art0"],
            p["window_z0"],
            p["z_top"] + 1.0,
        )
    )

    # 4) 灯条腔：光学层往下延长 LED_CH_H。两端各留 LED_SHOULDER 的承台托住导光板
    solid = solid.cut(
        _box(
            -p["led_len"] / 2.0,
            p["led_len"] / 2.0,
            p["y_opt0"],
            p["y_opt1"],
            p["z_led"],
            p["z_lgp"],
        )
    )

    # 5) 走线槽：从灯条一端的正后方穿出底座背面。顶是 6mm 跨度的桥接，不用支撑
    solid = solid.cut(
        _box(
            p["cable_x"] - CABLE_W / 2.0,
            p["cable_x"] + CABLE_W / 2.0,
            p["y_opt0"],
            p["base_y1"] + 1.0,
            p["z_led"],
            p["z_led"] + CABLE_H,
        )
    )

    # 6) 顶部插入口导角，插画片时不用对得很准
    if LEAD_IN > 1e-4:
        try:
            solid = solid.faces(">Z").edges("not(<X or >X)").chamfer(LEAD_IN)
        except Exception:  # noqa: BLE001 - 导角只是手感，失败不影响功能
            pass

    return solid


def build_topbar(*, print_orientation: bool = True) -> cq.Workplane:
    """顶压条：盖板 + 前唇 + 舌头。

    平着打，板贴床、唇和舌朝上，整件没有一处悬空。
    """
    p = params()
    hw_body = p["body_w"] / 2.0

    # 盖板：盖住整个框顶面
    bar = _rounded_box(
        -hw_body, hw_body, 0.0, p["body_d"], p["z_top"], p["z_top"] + BAR_PLATE_T, BODY_R
    )

    # 前唇：落进取景窗顶端，与正面压边同一平面，往下压住画片顶边 BAR_LAP
    lip_hw = p["window_w"] / 2.0 - BAR_LIP_GAP
    bar = bar.union(_box(-lip_hw, lip_hw, 0.0, p["y_art0"], p["z_top"] - BAR_LAP, p["z_top"]))

    # 舌头：插进光学层槽，坐在导光板顶边上，顺手把导光板压住不让它往上窜
    tongue_hw = p["pocket_w"] / 2.0 - BAR_TONGUE_INSET
    y0 = p["y_opt0"] + (OPTICS_T - BAR_TONGUE_T) / 2.0
    bar = bar.union(
        _box(-tongue_hw, tongue_hw, y0, y0 + BAR_TONGUE_T, p["lgp_top"], p["z_top"])
    )

    if print_orientation:
        bar = bar.rotate((0, 0, 0), (1, 0, 0), 180)
        bb = bar.val().BoundingBox()
        bar = bar.translate((0, -bb.ymin, -bb.zmin))
    return bar


# =============================================================================
# 导出与料单
# =============================================================================

def export_all(out_dir: str, *, tolerance: float = 0.05) -> dict[str, str]:
    """STL 给切片，STEP 给改模。

    STEP 是 B-rep 实体，尺寸、圆角、平面都还是可编辑的特征；STL 只是一堆三角形，
    在 CAD 里改等于重画。要动结构就改 STEP。
    """
    body = build_body()
    topbar = build_topbar()
    paths = {
        "body_stl": os.path.join(out_dir, "standcard_body.stl"),
        "topbar_stl": os.path.join(out_dir, "standcard_topbar.stl"),
        "body_step": os.path.join(out_dir, "standcard_body.step"),
        "topbar_step": os.path.join(out_dir, "standcard_topbar.step"),
        "assembly_step": os.path.join(out_dir, "standcard_assembly.step"),
    }
    cq.exporters.export(body, paths["body_stl"], tolerance=tolerance, angularTolerance=0.2)
    cq.exporters.export(topbar, paths["topbar_stl"], tolerance=tolerance, angularTolerance=0.2)
    cq.exporters.export(body, paths["body_step"])
    cq.exporters.export(topbar, paths["topbar_step"])

    # 装配位的两个实体放在一个文件里，方便看压条和槽对不对得上。
    # 注意这里的顶压条是装配姿态，不是打印姿态。
    assembly = cq.Compound.makeCompound(
        [body.val(), build_topbar(print_orientation=False).val()]
    )
    cq.exporters.export(cq.Workplane("XY").add(assembly), paths["assembly_step"])
    return paths


def spec() -> list[tuple[str, str]]:
    """出料单：要买什么、多大。全部由参数派生，改尺寸这里跟着变。"""
    p = params()
    return [
        (
            "外形",
            f'{p["base_w"]:.1f} × {BASE_D:.0f} × {p["z_top"] + BAR_PLATE_T:.1f} mm'
            f"（含底座与顶压条）",
        ),
        ("框体厚", f'{p["body_d"]:.1f} mm'),
        ("画片", f"{ART_W:.0f} × {ART_H:.0f} mm，厚 ≤1.76（22 层 × 0.08）"),
        (
            "画片可见",
            f'{p["window_w"]:.0f} × {p["visible_h"]:.0f} mm（四边各压 {BEZEL_LAP_X:.0f}）',
        ),
        (
            "导光板",
            f'{p["lgp_w"]:.0f} × {p["lgp_h"]:.0f} × {LGP_T:.1f} mm，PMMA 挤出板，带网点，'
            f'入光边 = {p["lgp_w"]:.0f} 那条长边（网点由该边向上递增）',
        ),
        ("扩散片", f'{p["lgp_w"]:.0f} × {p["lgp_h"]:.0f} × {DIFFUSER_T:.1f} mm，磨砂 PET / PP'),
        ("反射膜", f'{p["lgp_w"]:.0f} × {p["lgp_h"]:.0f} × {REFLECTOR_T:.1f} mm，白色 PET'),
        (
            "灯条",
            f'5V、PCB 宽 ≤{OPTICS_T - 0.2:.1f}mm（导光板背光条）、长 {p["led_len"]:.0f} mm 以内、'
            f"120 珠/米、CRI ≥ 90、4000–5000K",
        ),
        ("反光胶带", "导光板除入光边外的另三条边；混光区内壁也值得贴"),
        ("混光距离", f'导光板底边 → 可见画面下沿 {p["mix_total"]:.0f} mm'),
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description="立式薄画框：出 STL 与料单")
    ap.add_argument("--art", metavar="WxH", help="画片尺寸，例如 150x100")
    ap.add_argument("--base-depth", type=float, help="底座进深 mm")
    args = ap.parse_args()

    if args.art:
        w, h = (float(v) for v in args.art.lower().split("x"))
        globals()["ART_W"], globals()["ART_H"] = w, h
    if args.base_depth:
        globals()["BASE_D"] = args.base_depth

    here = os.path.dirname(os.path.abspath(__file__))
    paths = export_all(here)
    p = params()

    for name, path in paths.items():
        print(f"已导出 {name}: {path}")
    print()
    print("== 尺寸 ==")
    for k, v in spec():
        print(f"  {k:8s} {v}")
    print()
    print("== 装配 ==")
    print(f"  1. 灯条躺进 z={p['z_led']:.0f} 的腔，发光面朝上，线从背面走线槽出去")
    print(f"  2. 反射膜 → 导光板（网点面朝反射膜）→ 扩散片，坐在 z={p['z_lgp']:.0f} 的承台上")
    print(f"  3. 画片从顶部滑进画片槽，落在 z={p['z_art']:.0f} 的挡条上")
    print("  4. 顶压条盖上：舌头插进光学层槽，前唇压住画片顶边。换画片时抬掉它")


if __name__ == "__main__":
    main()
