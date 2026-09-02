"""发光吧唧 —— 参数母本。

谷圈的吧唧是有通用规格的，别自己定：32 / 44 / **58** / 75 / 100 mm，
其中 58 是绝对主流（配件生态——吧唧套、展示架、痛包内页——全按它做）。
`BADGE_D` 就是这个数，改它整件跟着变。

结构（三件，全部无支撑）：

    前框 badge_front.stl   正面朝下平躺打。压边 + 一个通到底的圆孔 + 统一插脚
    后盖 badge_back.stl    平躺打。压进圆孔，靠一圈卡扣扣住
    假画片 badge_disc.stl  试装用的白板，验合不合、松不松；真画片由生成器出

叠层（从正面往背面数）：

    压边 1.0 │ 画片 2.0 │ 光源腔 LIGHT_T │ 后盖 1.0

**LIGHT_T 是这一版最重要的旋钮**，因为光源还没定：

    冷光片 EL        0.3–0.5   最薄，但偏暗、偏青，要高压逆变器
    超薄背光模组      2.0–3.0   亮、均匀、直流好驱动，但只有矩形，圆的要定制
    不带光源（靠座供光） 0        整件只剩 4mm，就是一片带边的画

三种都不用改结构，只改这一个数。所以**先买回来实测亮度和颜色，再定它**，
不要反过来先把壳定死。

统一插脚：`FOOT_*` 这一组是**所有谷子共用的**——吧唧、立牌、色纸以后都长这个脚，
灯座只认脚、不认脸。所以脚**贴着正面那一侧**对齐，跟各自多厚无关。

坐标系（打印姿态）：X = 宽，Y = 高，Z = 厚（正面 z=0 往背面增大）。
"""

from __future__ import annotations

import argparse
import math
import os

import cadquery as cq

try:  # 当包导入
    from .threemf_out import place, write_3mf
except ImportError:  # 当脚本直接跑
    from threemf_out import place, write_3mf

# =============================================================================
# 参数
# =============================================================================

BADGE_D = 58.0        # 徽章外径。标准规格：32 / 44 / 58 / 75 / 100
WALL = 1.6            # 圈壁厚
BEZEL_T = 1.0         # 正面压边厚
BEZEL_LAP = 2.5       # 压边压住画片多少（吃掉的是画片，小件上别太贪）
BEZEL_CHAMFER = 0.5   # 压边背面台阶的 45° 倒角，会被钳到 BEZEL_T - 0.4

ART_T = 1.76          # 画片实厚：22 层 × 0.08
ART_SLOT_T = 2.0      # 画片槽
LIGHT_T = 0.5         # 光源腔厚：冷光片 0.3–0.5 / 背光模组 2–3 / 靠座供光填 0
BACK_T = 1.0          # 后盖厚

FIT = 0.3             # 画片、光源、后盖的直径公差（总量）
SNAP_H = 0.35         # 后盖卡扣凸起高度。圆件壁薄好弹，别做大
OUTER_CHAMFER = 0.6   # 正反面外沿倒角，手感

# —— 统一插脚：所有谷子共用，灯座只认它 ——
FOOT_W = 12.0         # 脚宽
FOOT_T = 3.0          # 脚厚（贴正面对齐）
FOOT_H = 8.0          # 脚伸出徽章外缘多少
FOOT_R = 1.0          # 脚的圆角
WIRE_W = 4.0          # 走线口：从光源腔穿出下缘，沿脚走进底座
WIRE_H = 2.0


def params() -> dict[str, float]:
    pocket_d = BADGE_D - 2.0 * WALL
    art_d = pocket_d - FIT
    window_d = pocket_d - 2.0 * BEZEL_LAP
    z_art = BEZEL_T
    z_light = z_art + ART_SLOT_T
    z_back = z_light + LIGHT_T
    depth = z_back + BACK_T
    # 一盘能摆多少（留 6mm 间距，X1C 可用 250）
    per_row = int((250.0 + 6.0) // (BADGE_D + 6.0))
    return {
        "pocket_d": pocket_d,
        "art_d": art_d,
        "window_d": window_d,
        "z_art": z_art,
        "z_light": z_light,
        "z_back": z_back,
        "depth": depth,
        "bezel_chamfer": min(BEZEL_CHAMFER, max(0.0, BEZEL_T - 0.4)),
        "visible_area_cm2": math.pi * (window_d / 2.0) ** 2 / 100.0,
        "art_area_cm2": math.pi * (art_d / 2.0) ** 2 / 100.0,
        "per_row": per_row,
        "per_plate": per_row * per_row,
    }


# =============================================================================
# 建模小工具
# =============================================================================

def _cyl(d: float, z0: float, z1: float) -> cq.Workplane:
    return cq.Workplane("XY").workplane(offset=z0).circle(d / 2.0).extrude(z1 - z0)


def _cone(d0: float, d1: float, z0: float, z1: float) -> cq.Workplane:
    """两个圆之间的过渡锥台，用来做 45° 倒角。"""
    return (
        cq.Workplane("XY")
        .workplane(offset=z0)
        .circle(d0 / 2.0)
        .workplane(offset=z1 - z0)
        .circle(d1 / 2.0)
        .loft(ruled=True)
    )


def _box_xyz(
    x0: float, x1: float, y0: float, y1: float, z0: float, z1: float
) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .box(x1 - x0, y1 - y0, z1 - z0, centered=False)
        .translate((x0, y0, z0))
    )


def _foot() -> cq.Workplane:
    """统一插脚。贴正面那一侧对齐，所以各款多厚都不影响座。"""
    y1 = -BADGE_D / 2.0 + 2.0            # 往圈里伸一点，保证焊得牢
    y0 = -BADGE_D / 2.0 - FOOT_H
    foot = _box_xyz(-FOOT_W / 2.0, FOOT_W / 2.0, y0, y1, 0.0, FOOT_T)
    try:
        foot = foot.edges("|Z").fillet(FOOT_R)
    except Exception:  # noqa: BLE001
        pass
    return foot


# =============================================================================
# 零件
# =============================================================================

def build_front() -> cq.Workplane:
    """前框。正面朝下平躺打 —— 开口一路往后变大，全是朝上的台阶，无支撑。"""
    p = params()
    solid = _cyl(BADGE_D, 0.0, p["depth"]).union(_foot())

    # 正反面外沿各倒一点角，捏着不割手
    if OUTER_CHAMFER > 1e-4:
        for sel in (">Z", "<Z"):
            try:
                solid = solid.faces(sel).edges(cq.selectors.RadiusNthSelector(-1)).chamfer(
                    OUTER_CHAMFER
                )
            except Exception:  # noqa: BLE001 - 倒角只是手感，失败不影响功能
                pass

    # 1) 取景窗
    solid = solid.cut(_cyl(p["window_d"], -1.0, BEZEL_T))

    # 2) 压边背面台阶的倒角。台阶朝下悬空（画片搁在上面），
    #    倒角把无支撑跨度从 BEZEL_LAP 砍掉一截
    ch = p["bezel_chamfer"]
    if ch > 1e-4:
        solid = solid.cut(
            _cone(p["window_d"], p["window_d"] + 2.0 * ch, BEZEL_T - ch, BEZEL_T)
        )

    # 3) 一个通到底的圆孔：画片、光源、后盖依次叠在里面
    solid = solid.cut(_cyl(p["pocket_d"], p["z_art"], p["depth"] + 1.0))

    # 4) 后盖卡扣槽：孔壁上一圈内槽，接后盖外圈的凸筋
    if SNAP_H > 1e-4:
        z_mid = p["z_back"] + BACK_T / 2.0
        solid = solid.cut(
            _cyl(p["pocket_d"] + 2.0 * SNAP_H, z_mid - BACK_T / 4.0, z_mid + BACK_T / 4.0)
        )

    # 5) 走线口：从光源腔穿出下缘，再沿脚走出去
    solid = solid.cut(
        _box_xyz(
            -WIRE_W / 2.0,
            WIRE_W / 2.0,
            -BADGE_D / 2.0 - FOOT_H - 1.0,
            -p["pocket_d"] / 2.0 + 1.0,
            p["z_light"],
            p["z_light"] + WIRE_H,
        )
    )
    return solid


def build_back() -> cq.Workplane:
    """后盖。平躺打，凸筋朝上；压进圆孔咔一下。"""
    p = params()
    cover = _cyl(p["pocket_d"] - FIT, 0.0, BACK_T)
    if SNAP_H > 1e-4:
        # 凸筋做在中间高度，上下各留一段导入
        cover = cover.union(
            _cyl(p["pocket_d"] - FIT + 2.0 * SNAP_H, BACK_T / 4.0, BACK_T * 3.0 / 4.0)
        )
    # 走线缺口，和前框那条对齐
    cover = cover.cut(
        _box_xyz(
            -WIRE_W / 2.0,
            WIRE_W / 2.0,
            -BADGE_D / 2.0,
            -p["pocket_d"] / 2.0 + 2.0,
            -1.0,
            BACK_T + 1.0,
        )
    )
    return cover


def build_disc() -> cq.Workplane:
    """试装用的假画片：跟真画片同直径同厚度的一块白板。

    真画片要等生成器支持"按 alpha 裁形"才能出圆的 —— 现在的分色只出矩形。
    在那之前用这块验合不合、松不松、压边够不够。
    """
    p = params()
    return _cyl(p["art_d"], 0.0, ART_T)


PARTS = {"front": build_front, "back": build_back, "disc": build_disc}


# =============================================================================
# 导出
# =============================================================================

def build_plate(count: int = 0) -> list[tuple[str, cq.Workplane]]:
    """摆盘。

    count = 0：一套三件排开，用来看形状、试装配。
    count > 0：N 套前框 + 后盖铺满，用来实打 —— 排废按层算，摆满才划算。
    """
    p = params()
    pitch = BADGE_D + 6.0
    if count <= 0:
        y = pitch / 2.0
        return [
            ("front", place(build_front(), -pitch * 0.75, 0.0)),
            ("back", place(build_back(), pitch * 0.35, y)),
            ("disc", place(build_disc(), pitch * 0.35, -y)),
        ]
    per_row = max(1, p["per_row"])
    out: list[tuple[str, cq.Workplane]] = []
    front, back = build_front(), build_back()
    for i in range(count):
        col, row = i % per_row, i // per_row
        x = (col - (per_row - 1) / 2.0) * pitch
        y = -(row - (min(count, per_row * per_row) // per_row) / 2.0) * pitch
        out.append((f"front{i + 1}", place(front, x, y)))
        out.append((f"back{i + 1}", place(back, x, y + pitch * 0.42)))
    return out


def export_all(out_dir: str, *, tolerance: float = 0.04, count: int = 0) -> dict[str, str]:
    paths: dict[str, str] = {}
    for name, fn in PARTS.items():
        shape = fn()
        for ext in ("stl", "step"):
            path = os.path.join(out_dir, f"badge_{name}.{ext}")
            if ext == "stl":
                cq.exporters.export(shape, path, tolerance=tolerance, angularTolerance=0.15)
            else:
                cq.exporters.export(shape, path)
            paths[f"{name}_{ext}"] = path
    paths["plate_3mf"] = write_3mf(
        os.path.join(out_dir, "badge_plate.3mf"), build_plate(count), tol=tolerance
    )
    return paths


def spec() -> list[tuple[str, str]]:
    p = params()
    light = (
        "冷光片 EL"
        if LIGHT_T <= 1.0
        else ("超薄背光模组" if LIGHT_T <= 3.5 else "自定义")
    )
    return [
        ("规格", f'⌀{BADGE_D:.0f} × 厚 {p["depth"]:.1f} mm'),
        ("可见画面", f'⌀{p["window_d"]:.1f} mm（{p["visible_area_cm2"]:.1f} cm²）'),
        ("画片", f'⌀{p["art_d"]:.1f} × {ART_T:.2f} mm（{p["art_area_cm2"]:.1f} cm²）'),
        ("光源腔", f"{LIGHT_T:.1f} mm —— 按{light}留的；换光源只改 LIGHT_T"),
        ("统一插脚", f"{FOOT_W:.0f} × {FOOT_T:.0f} mm，伸出 {FOOT_H:.0f}，贴正面对齐"),
        ("一盘", f'{p["per_row"]} × {p["per_row"]} = **{p["per_plate"]} 个**（留 6mm 间距）'),
        (
            "排废",
            f'按层算，所以一盘 {p["per_plate"]} 个的排废量 ≈ 打 1 个 —— '
            f"单件排废成本除以 {p['per_plate']}",
        ),
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description="发光吧唧：出 STL/STEP 与料单")
    ap.add_argument("--d", type=float, help="徽章外径 mm（32/44/58/75/100）")
    ap.add_argument("--light", type=float, help="光源腔厚度 mm（EL 0.5 / 背光模组 2.5 / 无 0）")
    ap.add_argument("--count", type=int, default=0, help="摆盘打几套；0 = 只摆一套看形状")
    args = ap.parse_args()
    if args.d:
        globals()["BADGE_D"] = args.d
    if args.light is not None:
        globals()["LIGHT_T"] = args.light

    here = os.path.dirname(os.path.abspath(__file__))
    paths = export_all(here, count=args.count)
    for name in sorted(paths):
        print(f"已导出 {name}: {os.path.basename(paths[name])}")
    print()
    print("== 规格 ==")
    for k, v in spec():
        print(f"  {k:8s} {v}")
    print()
    print("== 装配 ==")
    print("  1. 画片放进前框的圆孔，靠在压边上")
    print("  2. 光源贴在画片背面（面光源可以直接贴死，不需要留间隙）")
    print("  3. 线从下缘走线口穿出，沿插脚进底座")
    print("  4. 后盖压进去，一圈卡扣扣住。换画片：抠出后盖")


if __name__ == "__main__":
    main()
