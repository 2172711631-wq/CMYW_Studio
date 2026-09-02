"""两件式灯画框（前框 + 灯板模块）—— 参数母本。

演进到第三版。前两版的问题都出在"什么东西从哪儿装进去"：

    v1 背面卡扣    画片从背面进，装拆要撬一片 1mm 薄板
    v2 顶边滑入    什么都从顶上滑，于是上边框只能整段开通，装好之后顶边缺一块
    v3 本版        前框和灯板分家，各自完整；灯板从背面插进前框，咔一下

分家之后每件都变简单了：

    前框   四边压边完整闭合，顶边不再有豁口，正面看就是一个正常的相框
    灯板   一个浅盘，灯条就贴在盘壁与盘底交界的那道内角里 —— 不用开让台，
           那道内角本身就是天然的定位基准，摸着贴都不会歪
    底座   照旧，一块带斜插槽的平板

叠层（从正面往背面数，总厚 12.8mm）：

    压边 1.6 │ 画片 2.0 │ 扩散片 0.7 │ ←── 灯板模块 8.5 ──→
                                      盘壁 7.5（灯条贴内角）+ 盘底 1.0

灯板模块的盘底就是背板，所以背板不再是单独一片，也不用滑槽和挡边 ——
v2 为这两样花掉的 1.7mm 直接省了。

打印姿态（都不用支撑）：

    前框   正面朝下平躺。开口一路往后变大，全是朝上的台阶
    灯板   盘底朝下平躺。盘壁朝上，同样没有一处悬空
    底座   平躺

坐标系（前框与灯板均为打印姿态）：X = 宽，Y = 高，Z = 深（前框正面 z=0 往后增大；
灯板盘底外表面 z=0 往盘口增大）。底座另算，见 build_base()。
"""

from __future__ import annotations

import argparse
import math
import os

import cadquery as cq

try:  # 当包导入
    from .threemf_out import place, write_bambu_3mf
except ImportError:  # 当脚本直接跑
    from threemf_out import place, write_bambu_3mf

# =============================================================================
# 参数
# =============================================================================

# —— 画片（消耗品）——
ART_W = 160.0
ART_H = 120.0
ART_SLOT_T = 2.0      # 画片槽。实厚 ≤1.76（22 层 × 0.08）

# —— 光学 ——
DIFFUSER_T = 0.5      # 扩散片，磨砂 PET/PP。雾度靠材料不靠厚度
DIFFUSER_SLOT_T = 0.7
CAVITY_D = 7.5        # 灯板盘壁高度，也就是腔深。灯条占掉 3.0，剩下的是混光距离
CAVITY_INSET = 1.5    # 前框里托住扩散片的那圈台阶宽度，同时决定灯板插口大小。
                      # 必须小于 BEZEL_LAP，否则台阶会从取景窗里露出来

# —— 灯条 ——
# 不做让台：灯条直接贴在灯板盘壁与盘底的那道内角里，那道角本身就是定位基准。
# 灯条也因此紧贴盘底，直射光先打到盘底和对面盘壁，弹一次再往前，边缘不会亮一圈。
LED_W = 3.0           # 灯条 PCB 宽
LED_T = 1.2           # 灯条含背胶的厚度，只用来算它往腔里凸多少
WIRE_W = 6.0          # 盘底出线口
WIRE_H = 3.0

# —— 前框 ——
BEZEL_T = 1.6         # 正面压边厚
BEZEL_LAP = 4.0       # 正面四边各压住画片多少。压边吃掉的是画片，尽量小
BEZEL_CHAMFER = 1.0   # 压边背面台阶根部的 45° 倒角，会被钳到 BEZEL_T - 0.6
WALL = 7.0            # 画片槽外侧的结构壁厚。看到的边框 = BEZEL_LAP + WALL
FIT = 0.3             # 画片 / 扩散片的横向公差
FRAME_R = 6.0         # 外圆角。必须大于 BACK_BEVEL，见 build_frame 里的钳位
BACK_BEVEL = 5.0      # 背面外沿的 45° 斜切，让侧面看着薄

# —— 灯板模块 ——
MODULE_BACK_T = 1.0   # 盘底厚，它就是背板
MODULE_RIM = 1.5      # 盘壁厚
MODULE_FIT = 0.3      # 灯板外形比前框插口小多少（总量）
SNAP_H = 0.4          # 卡扣凸起高度
SNAP_LEN = 15.0       # 每个卡扣长度
SNAP_AT = 0.55        # 卡扣在盘壁高度上的相对位置

# —— 底座 ——
# 底座同时是配重、插座和电池仓。电池和电路板只能放这儿：
# 灯板那个腔是光学件，塞进去任何不透光的东西都会在画面上投影。
BASE_T = 16.0         # 底板厚。要装得下 10.5mm 的软包电池，10mm 远不够
BASE_D = 84.0         # 进深。插槽挪到靠前，后面整片留给电池仓
BASE_MARGIN = 5.0
GROOVE_Y = 24.0       # 插槽中心距底座前沿。靠前放，后面才腾得出电池仓
GROOVE_DEPTH = 7.0
GROOVE_FIT = 0.4
TILT = 8.0
BASE_R = 6.0
BASE_WIRE_W = 8.0
BASE_WIRE_H = 3.5

# —— 电池仓（尺寸按常见件预设，换件改这里）——
# 预设：103450 软包锂电（10×34×50，约 2000mAh）+ USB-C 充电升压一体板 + 侧拨开关
# 电池横着放：长边沿 X（底座宽 176mm，随便放），短边沿 Y（吃电池仓的进深）
BAT_LONG = 52.0       # 电池长边（沿 X）
BAT_SHORT = 36.0      # 电池短边（沿 Y）—— 电池仓进深要大于它
BAT_H = 10.5          # 电池厚 —— 电池仓净高要大于它
PCB_W = 30.0          # 电路板槽
PCB_D = 20.0
PCB_H = 7.0
USB_W = 11.0          # 背面 USB-C 开口
USB_H = 5.0
USB_Z = 4.0           # 开口下沿距仓底
SW_W = 13.0           # 背面开关开口
SW_H = 8.0
BAY_WALL = 2.5        # 电池仓顶壁（也就是底座上表面那层）
COVER_T = 1.6         # 底盖厚
COVER_FIT = 0.3
COVER_LIP = 1.2       # 底盖沉入量，装上后与底面齐平
COVER_SNAP = 0.4


def params() -> dict[str, float]:
    pocket_w = ART_W + FIT
    pocket_h = ART_H + FIT
    frame_w = pocket_w + 2.0 * WALL
    frame_h = pocket_h + 2.0 * WALL

    z_art = BEZEL_T
    z_diff = z_art + ART_SLOT_T
    z_socket = z_diff + DIFFUSER_SLOT_T
    module_h = MODULE_BACK_T + CAVITY_D
    depth = z_socket + module_h

    socket_w = pocket_w - 2.0 * CAVITY_INSET
    socket_h = pocket_h - 2.0 * CAVITY_INSET
    mod_w = socket_w - MODULE_FIT
    mod_h = socket_h - MODULE_FIT
    cav_w = mod_w - 2.0 * MODULE_RIM
    cav_h = mod_h - 2.0 * MODULE_RIM

    window_w = pocket_w - 2.0 * BEZEL_LAP
    window_h = pocket_h - 2.0 * BEZEL_LAP

    return {
        "pocket_w": pocket_w,
        "pocket_h": pocket_h,
        "frame_w": frame_w,
        "frame_h": frame_h,
        "window_w": window_w,
        "window_h": window_h,
        "z_art": z_art,
        "z_diff": z_diff,
        "z_socket": z_socket,
        "depth": depth,
        "socket_w": socket_w,
        "socket_h": socket_h,
        "mod_w": mod_w,
        "mod_h": mod_h,
        "module_h": module_h,
        "cav_w": cav_w,
        "cav_h": cav_h,
        # 灯板腔口比取景窗宽出多少 —— 小于 0 就说明盘壁会在画面边上投影
        "lit_margin": (cav_w - window_w) / 2.0,
        # 灯条前沿到扩散片，真正的混光距离
        "mix_gap": CAVITY_D - LED_W,
        "led_run": cav_w - 8.0,
        "bevel": min(BACK_BEVEL, max(0.0, FRAME_R - 0.8)),
        "bezel_chamfer": min(BEZEL_CHAMFER, max(0.0, BEZEL_T - 0.6)),
        # 卡扣在前框坐标里的深度（灯板背面与前框背面齐平）
        "snap_z": depth - (MODULE_BACK_T + CAVITY_D * SNAP_AT),
        "base_w": frame_w + 2.0 * BASE_MARGIN,
        # 电池仓：插槽后方那一整片。前沿离插槽留 4mm 肉
        "bay_y0": GROOVE_Y + (depth + GROOVE_FIT) / 2.0 + 4.0,
        "bay_y1": BASE_D - 4.0,
        "bay_h": BASE_T - BAY_WALL - COVER_T - COVER_LIP,
        "bay_w": (frame_w + 2.0 * BASE_MARGIN) - 8.0,
        "bay_d": (BASE_D - 4.0) - (GROOVE_Y + (depth + GROOVE_FIT) / 2.0 + 4.0),
        "stand_h": BASE_T + (frame_h - GROOVE_DEPTH) * math.cos(math.radians(TILT)),
    }


# =============================================================================
# 建模小工具
# =============================================================================

def _prism(w: float, h: float, z0: float, z1: float, r: float = 0.0) -> cq.Workplane:
    wp = cq.Workplane("XY").workplane(offset=z0).rect(w, h).extrude(z1 - z0)
    if r > 1e-4:
        try:
            wp = wp.edges("|Z").fillet(r)
        except Exception:  # noqa: BLE001
            pass
    return wp


def _box_xyz(
    x0: float, x1: float, y0: float, y1: float, z0: float, z1: float
) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .box(x1 - x0, y1 - y0, z1 - z0, centered=False)
        .translate((x0, y0, z0))
    )


def _taper(w0: float, h0: float, w1: float, h1: float, z0: float, z1: float) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .workplane(offset=z0)
        .rect(w0, h0)
        .workplane(offset=z1 - z0)
        .rect(w1, h1)
        .loft(ruled=True)
    )


# =============================================================================
# 零件
# =============================================================================

def build_frame() -> cq.Workplane:
    """前框。正面朝下平躺打；开口一路往后变大，全是朝上的台阶，无支撑。"""
    p = params()
    outer = _prism(p["frame_w"], p["frame_h"], 0.0, p["depth"], FRAME_R)

    # 背面外沿削一圈 45°。趁 outer 还是干净的圆角方柱时就削 —— 这时 faces(">Z")
    # 只有一条外轮廓，选边不会误伤；等挖完插口再削会在圆角处留下 T 型接点。
    bevel = p["bevel"]
    if bevel > 1e-4:
        try:
            outer = outer.faces(">Z").chamfer(bevel)
        except Exception:  # noqa: BLE001
            pass

    # 1) 取景窗
    solid = outer.cut(_prism(p["window_w"], p["window_h"], -1.0, BEZEL_T))

    # 2) 压边背面台阶根部的倒角。台阶是朝下的悬空（画片搁在上面），
    #    倒角把无支撑跨度从 BEZEL_LAP 砍到 BEZEL_LAP - 倒角
    ch = p["bezel_chamfer"]
    if ch > 1e-4:
        solid = solid.cut(
            _taper(
                p["window_w"],
                p["window_h"],
                p["window_w"] + 2.0 * ch,
                p["window_h"] + 2.0 * ch,
                BEZEL_T - ch,
                BEZEL_T,
            )
        )

    # 3) 画片槽 + 扩散片槽：同一个开口，一前一后
    solid = solid.cut(_prism(p["pocket_w"], p["pocket_h"], p["z_art"], p["z_socket"]))

    # 4) 灯板插口。它比画片槽每边小 CAVITY_INSET，让出的台阶就托住扩散片
    solid = solid.cut(
        _prism(p["socket_w"], p["socket_h"], p["z_socket"], p["depth"] + 1.0)
    )

    # 5) 卡扣凹坑：插口左右两壁各一对，接灯板上的凸起
    if SNAP_H > 1e-4:
        for sx in (-1, 1):
            for sy in (-1, 1):
                x0 = sx * p["socket_w"] / 2.0
                x1 = sx * (p["socket_w"] / 2.0 + SNAP_H + 0.15)
                solid = solid.cut(
                    _box_xyz(
                        min(x0, x1),
                        max(x0, x1),
                        sy * p["socket_h"] / 4.0 - SNAP_LEN / 2.0,
                        sy * p["socket_h"] / 4.0 + SNAP_LEN / 2.0,
                        p["snap_z"] - SNAP_LEN * 0.0 - 1.2,
                        p["snap_z"] + 1.2,
                    )
                )
    return solid


def build_module() -> cq.Workplane:
    """灯板模块。一个浅盘：盘底就是背板，灯条贴盘壁与盘底的内角。

    盘底朝下平躺打，盘壁朝上，全件无悬空。
    """
    p = params()
    tray = _prism(p["mod_w"], p["mod_h"], 0.0, p["module_h"], max(0.0, FRAME_R - 2.0))

    # 盘腔
    tray = tray.cut(
        _prism(p["cav_w"], p["cav_h"], MODULE_BACK_T, p["module_h"] + 1.0)
    )

    # 出线口：盘底下缘开一个豁口，线直接从背面下方走进底座的走线槽
    tray = tray.cut(
        _box_xyz(
            -WIRE_W / 2.0,
            WIRE_W / 2.0,
            -p["mod_h"] / 2.0 - 1.0,
            -p["cav_h"] / 2.0 + 1.0,
            -1.0,
            MODULE_BACK_T + WIRE_H,
        )
    )

    # 卡扣凸起：盘壁外侧左右各一对，带 45° 导入坡，插进去咔一下
    if SNAP_H > 1e-4:
        z_snap = MODULE_BACK_T + CAVITY_D * SNAP_AT
        for sx in (-1, 1):
            for sy in (-1, 1):
                cx = sx * (p["mod_w"] / 2.0 + SNAP_H / 2.0)
                cy = sy * p["mod_h"] / 4.0
                tray = tray.union(
                    cq.Workplane("XY")
                    .workplane(offset=z_snap - 1.0)
                    .center(cx, cy)
                    .rect(SNAP_H, SNAP_LEN)
                    .extrude(2.0)
                )
                # 上方的导入坡：插入时先碰到它，把盘壁压进去
                tray = tray.union(
                    _taper(
                        SNAP_H,
                        SNAP_LEN,
                        0.02,
                        SNAP_LEN,
                        z_snap + 1.0,
                        z_snap + 1.0 + SNAP_H,
                    ).translate((cx, cy, 0.0))
                )
    return tray


def build_base(*, print_orientation: bool = False) -> cq.Workplane:
    """底座 = 配重 + 斜插槽 + 电池仓。

    坐标（使用姿态）：X = 宽，Y = 深（前沿 y=0 往后增大），Z = 上。

    打印姿态是**上表面朝下**平躺：电池仓开口朝上，不用支撑；插槽变成从热床往上
    的一个洞，7mm 处封顶——那道桥只有插槽宽度（约 14mm），随便就过。
    反过来（底面朝下）打的话，电池仓的顶就得跨 45×176mm，没法打。
    """
    p = params()
    base = _prism(p["base_w"], BASE_D, 0.0, BASE_T, BASE_R).translate(
        (0.0, BASE_D / 2.0, 0.0)
    )

    # 斜插槽，挪到靠前
    slot = (
        cq.Workplane("XY")
        .rect(p["frame_w"] + GROOVE_FIT, p["depth"] + GROOVE_FIT)
        .extrude(60.0)
        .translate((0.0, 0.0, -GROOVE_DEPTH))
        .rotate((0, 0, 0), (1, 0, 0), -TILT)
        .translate((0.0, GROOVE_Y, BASE_T))
    )
    base = base.cut(slot)

    # 电池仓：从底面往上掏，顶上留 BAY_WALL
    bay_x = p["base_w"] / 2.0 - 4.0
    z_bay0 = COVER_T + COVER_LIP
    z_bay1 = z_bay0 + p["bay_h"]
    base = base.cut(
        _box_xyz(-bay_x, bay_x, p["bay_y0"], p["bay_y1"], z_bay0, z_bay1)
    )

    # 底盖沉槽：比电池仓大一圈，底盖沉进去与底面齐平
    base = base.cut(
        _box_xyz(
            -(bay_x + COVER_LIP),
            bay_x + COVER_LIP,
            p["bay_y0"] - COVER_LIP,
            p["bay_y1"] + COVER_LIP,
            -1.0,
            COVER_T + 0.1,
        )
    )

    # 底盖卡扣凹坑
    if COVER_SNAP > 1e-4:
        for sx in (-1, 1):
            for sy in (0.3, 0.7):
                y = p["bay_y0"] + (p["bay_y1"] - p["bay_y0"]) * sy
                x0 = sx * (bay_x + COVER_LIP)
                x1 = sx * (bay_x + COVER_LIP + COVER_SNAP + 0.15)
                base = base.cut(
                    _box_xyz(
                        min(x0, x1), max(x0, x1), y - 10.0, y + 10.0,
                        COVER_T - 0.6, COVER_T + 0.6,
                    )
                )

    # 走线：从插槽后墙通到电池仓
    z0 = BASE_T - GROOVE_DEPTH
    base = base.cut(
        _box_xyz(
            -BASE_WIRE_W / 2.0, BASE_WIRE_W / 2.0,
            GROOVE_Y, p["bay_y0"] + 2.0, z0 - BASE_WIRE_H, z0 + 0.1,
        )
    )

    # 背面 USB-C 与开关开口
    base = base.cut(
        _box_xyz(-USB_W / 2.0, USB_W / 2.0, p["bay_y1"] - 1.0, BASE_D + 1.0,
                 z_bay0 + USB_Z, z_bay0 + USB_Z + USB_H)
    )
    base = base.cut(
        _box_xyz(-USB_W / 2.0 - 30.0 - SW_W, -USB_W / 2.0 - 30.0,
                 p["bay_y1"] - 1.0, BASE_D + 1.0,
                 z_bay0 + USB_Z - 1.0, z_bay0 + USB_Z - 1.0 + SW_H)
    )

    if print_orientation:
        base = base.rotate((0, 0, 0), (1, 0, 0), 180)
        bb = base.val().BoundingBox()
        base = base.translate((0.0, -bb.ymin, -bb.zmin))
    return base


def build_cover() -> cq.Workplane:
    """电池仓底盖。平躺打，卡扣朝上。"""
    p = params()
    bay_x = p["base_w"] / 2.0 - 4.0
    w = 2.0 * (bay_x + COVER_LIP) - COVER_FIT
    d = (p["bay_y1"] - p["bay_y0"]) + 2.0 * COVER_LIP - COVER_FIT
    cover = (
        cq.Workplane("XY")
        .box(w, d, COVER_T, centered=(True, True, False))
        .edges("|Z")
        .fillet(3.0)
    )
    if COVER_SNAP > 1e-4:
        for sx in (-1, 1):
            for sy in (-1, 1):
                cover = cover.union(
                    _box_xyz(
                        min(sx * w / 2.0, sx * (w / 2.0 + COVER_SNAP)),
                        max(sx * w / 2.0, sx * (w / 2.0 + COVER_SNAP)),
                        sy * d / 4.0 - 10.0, sy * d / 4.0 + 10.0,
                        COVER_T - 0.6, COVER_T + 0.6,
                    )
                )
    return cover


def build_assembly() -> cq.Workplane:
    """装配姿态，仅供看配合。"""
    p = params()

    def upright(wp: cq.Workplane) -> cq.Workplane:
        return (
            wp.rotate((0, 0, 0), (1, 0, 0), 90)
            .rotate((0, 0, 0), (0, 0, 1), 180)
            .rotate((0, 0, 0), (1, 0, 0), -TILT)
        )

    frame = upright(build_frame())
    bb = frame.val().BoundingBox()
    dy = GROOVE_Y - (bb.ymin + bb.ymax) / 2.0
    dz = BASE_T - GROOVE_DEPTH - bb.zmin
    frame = frame.translate((0.0, dy, dz))

    # 灯板翻过来插进前框：盘口朝前，盘底与前框背面齐平
    module = upright(
        build_module()
        .rotate((0, 0, 0), (1, 0, 0), 180)
        .translate((0.0, 0.0, p["depth"]))
    ).translate((0.0, dy, dz))

    return cq.Workplane("XY").add(
        cq.Compound.makeCompound([build_base().val(), frame.val(), module.val()])
    )


# =============================================================================
# 导出
# =============================================================================

PARTS = {
    "frame": build_frame,
    "module": build_module,
    "base": lambda: build_base(print_orientation=True),
    "cover": build_cover,
}


def export_all(out_dir: str, *, tolerance: float = 0.05) -> dict[str, str]:
    paths: dict[str, str] = {}
    shapes = {name: fn() for name, fn in PARTS.items()}
    for name, shape in shapes.items():
        stl = os.path.join(out_dir, f"ringframe_{name}.stl")
        step = os.path.join(out_dir, f"ringframe_{name}.step")
        cq.exporters.export(shape, stl, tolerance=tolerance, angularTolerance=0.2)
        cq.exporters.export(shape, step)
        paths[f"{name}_stl"], paths[f"{name}_step"] = stl, step

    # 一个文件、两个盘。四件的包围盒面积合计 65867mm² > 床的 65536mm²，
    # 一个盘装不下是算出来的，不是排不好。
    p = params()
    gap = 6.0

    cov_d = p["bay_d"] + 2.0 * COVER_LIP
    left_w = max(p["frame_w"], p["base_w"])
    total_w = left_w + gap + cov_d
    lx = -total_w / 2.0 + left_w / 2.0
    rx = total_w / 2.0 - cov_d / 2.0
    left_h = p["frame_h"] + gap + BASE_D
    plates = [
        (
            "外壳三件",
            [
                ("frame", place(shapes["frame"], lx, left_h / 2.0 - p["frame_h"] / 2.0)),
                ("base", place(shapes["base"], lx, -left_h / 2.0 + BASE_D / 2.0)),
                ("cover", place(shapes["cover"], rx, 0.0, rot=90.0)),
            ],
        ),
        ("灯板", [("module", place(shapes["module"], 0.0, 0.0))]),
    ]
    paths["project_3mf"] = write_bambu_3mf(
        os.path.join(out_dir, "ringframe.3mf"), plates, tol=tolerance
    )
    paths["assembly_step"] = os.path.join(out_dir, "ringframe_assembly.step")
    cq.exporters.export(build_assembly(), paths["assembly_step"])
    return paths


def spec() -> list[tuple[str, str]]:
    p = params()
    return [
        ("前框", f'{p["frame_w"]:.1f} × {p["frame_h"]:.1f} × {p["depth"]:.1f} mm'),
        ("灯板模块", f'{p["mod_w"]:.1f} × {p["mod_h"]:.1f} × {p["module_h"]:.1f} mm 浅盘'),
        (
            "立起来",
            f'{p["base_w"]:.1f} 宽 × {BASE_D:.0f} 深 × 约 {p["stand_h"]:.0f} 高，后仰 {TILT:.0f}°',
        ),
        ("画片", f"{ART_W:.0f} × {ART_H:.0f} mm，厚 ≤1.76（22 层 × 0.08）"),
        (
            "画片可见",
            f'{p["window_w"]:.1f} × {p["window_h"]:.1f} mm，'
            f"利用率 {p['window_w'] * p['window_h'] / (ART_W * ART_H) * 100:.0f}%",
        ),
        ("扩散片", f'{p["pocket_w"]:.0f} × {p["pocket_h"]:.0f} × {DIFFUSER_T:.1f} mm 磨砂 PET/PP'),
        (
            "灯条",
            f'5V、PCB 宽 {LED_W:.0f}mm、上下各一条约 {p["led_run"]:.0f} mm、'
            f"120 珠/米、CRI ≥ 90、4000–5000K",
        ),
        ("腔深", f'{CAVITY_D:.1f} mm，灯条占 {LED_W:.1f}，**混光距离 {p["mix_gap"]:.1f} mm**'),
        ("发光区余量", f'灯板腔口比取景窗每边宽 {p["lit_margin"]:.1f} mm'),
        ("内腔", "必须够白：灯板用白色 PLA 打，或盘内贴白色反光膜。这是功能不是装饰"),
        (
            "电池仓",
            f'{p["bay_w"]:.0f} × {p["bay_d"]:.0f} × {p["bay_h"]:.1f} mm（底座后半段，底盖可拆）；'
            f'电池 {BAT_LONG:.0f}×{BAT_SHORT:.0f}×{BAT_H:.1f} '
            f'{"装得下" if p["bay_d"] >= BAT_SHORT and p["bay_h"] >= BAT_H and p["bay_w"] >= BAT_LONG else "**装不下**"}',
        ),
        ("电路板", f'{PCB_W:.0f} × {PCB_D:.0f} × {PCB_H:.0f} mm 的位；背面开 USB-C {USB_W:.0f}×{USB_H:.0f} 与开关 {SW_W:.0f}×{SW_H:.0f}'),
        ("摆盘", "ringframe.3mf 一个文件两个盘：盘 1 = 前框/底座/底盖，盘 2 = 灯板"),
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description="两件式灯画框：出 STL/STEP/3MF 与料单")
    ap.add_argument("--art", metavar="WxH", help="画片尺寸，例如 150x100")
    ap.add_argument("--cavity", type=float, help="腔深 mm")
    ap.add_argument("--tilt", type=float, help="后仰角度")
    args = ap.parse_args()
    if args.art:
        w, h = (float(v) for v in args.art.lower().split("x"))
        globals()["ART_W"], globals()["ART_H"] = w, h
    if args.cavity:
        globals()["CAVITY_D"] = args.cavity
    if args.tilt is not None:
        globals()["TILT"] = args.tilt

    here = os.path.dirname(os.path.abspath(__file__))
    paths = export_all(here)
    for name in sorted(paths):
        print(f"已导出 {name}: {os.path.basename(paths[name])}")
    print()
    print("== 尺寸 ==")
    for k, v in spec():
        print(f"  {k:10s} {v}")
    print()
    print("== 装配 ==")
    print("  1. 两条灯条贴进灯板的内角（盘壁与盘底交界处），朝内；线从盘底豁口出去")
    print("  2. 画片、扩散片从前框背面放进去，靠在压边上")
    print("  3. 灯板整体压进前框插口，四个卡扣咔一下。背面与前框齐平")
    print("  4. 换画片：抠出灯板 → 换画片 → 压回去")
    print("  5. 电池与电路板装在底座后半段的仓里，线从插槽后墙的槽通到灯板；底盖卡上")


if __name__ == "__main__":
    main()
