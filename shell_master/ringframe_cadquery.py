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
# 8mm 的灯条竖不进 7.5mm 的腔，所以它是**平贴在盘底上**绕一圈、灯珠朝前的，
# 8mm 是它在盘底上占掉的一圈带宽，往腔里凸的只有 LED_T 那点厚度。
# 代价说清楚：这样中间没有直射光，全靠扩散片和白内壁匀，画面正中会比四边暗一点。
LED_W = 8.0           # 灯条 PCB 宽 —— 平贴盘底，占掉盘底四周这么宽一圈
LED_T = 1.2           # 灯条含背胶的厚度，也就是它往腔里凸多少
LED_SEAT = 0.3        # 盘底那一圈浅浅的定位沉台，贴的时候不用比着尺子
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
# 后仰版可以整块靠在槽的后壁上，直立版没有这个便宜可占 —— 画片能不能站直
# 全看这个槽。槽浅一点、松一点，顶上就晃：晃动量 ≈ 画高 × 间隙 / 槽深，
# 7mm / 0.4 的组合在 157mm 高的画上是 ±9mm，站着都在抖。
GROOVE_DEPTH = 10.0
GROOVE_FIT = 0.25
TILT = 0.0            # 90° 直立。要回后仰版把这里改回 8
BASE_R = 6.0
# 插槽后墙正中一条口子，过两根线（正负）就够，不用更大
BASE_WIRE_W = 6.0
BASE_WIRE_H = 3.0

# —— 电池仓（尺寸按常见件预设，换件改这里）——
# 预设：103450 软包锂电（10×34×50，约 2000mAh）+ USB-C 充电升压一体板 + 侧拨开关
# 电池横着放：长边沿 X（底座宽 176mm，随便放），短边沿 Y（吃电池仓的进深）
BAT_LONG = 52.0       # 电池长边（沿 X）
BAT_SHORT = 36.0      # 电池短边（沿 Y）—— 电池仓进深要大于它
BAT_H = 10.5          # 电池厚 —— 电池仓净高要大于它
PCB_W = 30.0          # 电路板槽
PCB_D = 20.0
PCB_H = 7.0
# 背面 USB-C 开口。尺寸和圆角照抄灯箱那个母本（web/src/engine/shell.ts 的 USB）——
# 切成直角方口插头也塞得进，但四角各露一块空隙，插头还不被孔壁扶正，手感和外观都是坏的。
USB_W = 9.3
USB_H = 3.5
USB_R = 1.65
USB_Z = 4.0           # 开口下沿距仓底

# —— 侧面触摸 ——
# 拨动开关换成侧面轻触。开关要在壳上开个洞、还要对准拨柄，触摸只要一块够薄够实的壁。
# 「实」比「薄」更要紧：稀疏填充里全是空腔，电容耦合会被吃掉大半，所以触摸区那块
# 必须 100% 填充 —— 和灯箱顶面触摸用的是同一招（buildTopSolidModifier），
# 这里由 build_touch_solid() 出一块修改器体，在切片器里挂上去。
TOUCH_W = 16.0        # 触摸模块（TTP223 一类）的座宽
TOUCH_H = 9.0         # 座高。电池仓净高就那么点，别超
TOUCH_SEAT = 1.0      # 模块沉进座里多少
TOUCH_WALL = 1.5      # 触摸区剩下的壁厚。4mm 实心 PLA 也能触发，但 1.5 稳得多
TOUCH_MARK_W = 26.0   # 外表面那圈浅指示凹坑，手摸得到才知道往哪按
TOUCH_MARK_H = 10.0
TOUCH_MARK_D = 0.4
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
        # 灯条平贴盘底，凸进腔里的只有它自己的厚度；剩下的全是混光距离
        "mix_gap": CAVITY_D - LED_T,
        "led_run": cav_w - 8.0,
        # 盘底减掉四周那圈灯带之后，中间还剩多大一块没有直射光
        "dark_w": cav_w - 2.0 * LED_W,
        "dark_h": cav_h - 2.0 * LED_W,
        # 触摸区在底座侧壁上，壁厚由电池仓的让位决定
        "side_wall": ((frame_w + 2.0 * BASE_MARGIN) / 2.0) - ((frame_w + 2.0 * BASE_MARGIN) / 2.0 - 4.0),
        "bevel": min(BACK_BEVEL, max(0.0, FRAME_R - 0.8)),
        "bezel_chamfer": min(BEZEL_CHAMFER, max(0.0, BEZEL_T - 0.6)),
        # 卡扣在前框坐标里的深度（灯板背面与前框背面齐平）
        "snap_z": depth - (MODULE_BACK_T + CAVITY_D * SNAP_AT),
        "base_w": frame_w + 2.0 * BASE_MARGIN,
        # 电池仓：插槽后方那一整片。前沿离插槽留 4mm 肉
        "bay_y0": GROOVE_Y + (depth + GROOVE_FIT) / 2.0 + 4.0,
        "bay_y1": BASE_D - 4.0,
        # 仓底就是底盖沉槽的顶，中间不该再留一层 —— 留了就是把仓封死
        "bay_h": BASE_T - BAY_WALL - COVER_T,
        "bay_w": (frame_w + 2.0 * BASE_MARGIN) - 8.0,
        "bay_d": (BASE_D - 4.0) - (GROOVE_Y + (depth + GROOVE_FIT) / 2.0 + 4.0),
        "stand_h": BASE_T + (frame_h - GROOVE_DEPTH) * math.cos(math.radians(TILT)),
        # 顶端能晃多少：槽里的间隙被画高放大了这么多倍
        "sway": (frame_h - GROOVE_DEPTH) * (GROOVE_FIT / GROOVE_DEPTH),
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


def _round_slot(
    w: float, h: float, r: float, y0: float, y1: float, cx: float = 0.0, cz: float = 0.0
) -> cq.Workplane:
    """一根圆角矩形柱，沿 Y 从 y0 贯到 y1，用来挖 Type-C 那种圆角口。"""
    wp = (
        cq.Workplane("XY")
        .box(w, y1 - y0, h, centered=(True, False, True))
        .translate((cx, y0, cz))
    )
    if r > 1e-4:
        try:
            wp = wp.edges("|Y").fillet(min(r, min(w, h) / 2.0 - 0.01))
        except Exception:  # noqa: BLE001
            pass
    return wp


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

    # 5) 出线口：底梁上开一条，从灯板插口的底壁一路通到前框底面。
    #    灯板的出线豁口开在它自己的下缘，出来正对着这条 —— 前框这边不开的话，
    #    线出了灯板就撞在 5mm 厚的底梁上，整条线被闷死在框里出不来。
    #    只在背半段开（z_socket 往后），正面看不见；朝上开口，打印也不用支撑。
    solid = solid.cut(
        _box_xyz(
            -(WIRE_W + 1.0) / 2.0, (WIRE_W + 1.0) / 2.0,
            -p["frame_h"] / 2.0 - 1.0, -p["socket_h"] / 2.0 + 0.5,
            p["z_socket"], p["depth"] + 1.0,
        )
    )

    # 6) 卡扣凹坑：插口左右两壁各一对，接灯板上的凸起
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

    # 灯带定位沉台：盘底四周一圈，宽 LED_W、深 LED_SEAT。灯带往里一贴就正，
    # 而且沉下去这一点还把它凸进腔里的高度又减了 0.3。
    if LED_SEAT > 1e-4 and LED_W > 1e-4:
        ring = _prism(p["cav_w"], p["cav_h"], MODULE_BACK_T - LED_SEAT, MODULE_BACK_T + 0.01)
        ring = ring.cut(
            _prism(
                p["cav_w"] - 2.0 * LED_W,
                p["cav_h"] - 2.0 * LED_W,
                MODULE_BACK_T - LED_SEAT - 1.0,
                MODULE_BACK_T + 1.0,
            )
        )
        tray = tray.cut(ring)

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

    # 电池仓：从底面往上掏，顶上留 BAY_WALL。
    #
    # 仓底必须正好落在底盖沉槽的顶面（z = COVER_T）。以前写的是 COVER_T + COVER_LIP，
    # 于是沉槽顶和仓底之间夹着一片 1.1mm 的实心，横跨 109 × 45 的仓口 —— 电池根本
    # 塞不进去，而且底座是上表面朝下打的，这片实心在打印姿态里就是悬在仓上方
    # 10mm 的一整块平顶，切片器只能往仓里灌支撑。
    # 底盖靠的是四周那圈 COVER_LIP 宽的台肩，不是这一片。
    bay_x = p["base_w"] / 2.0 - 4.0
    z_bay0 = COVER_T
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

    # 背面 Type-C：圆角口，尺寸照灯箱母本
    base = base.cut(
        _round_slot(
            USB_W, USB_H, USB_R,
            p["bay_y1"] - 1.0, BASE_D + 1.0,
            cz=z_bay0 + USB_Z + USB_H / 2.0,
        )
    )

    # 侧面触摸：外面一个浅指示坑，里面一个模块座，中间留 TOUCH_WALL 的壁
    tx = p["base_w"] / 2.0
    ty = (p["bay_y0"] + p["bay_y1"]) / 2.0
    tz = z_bay0 + p["bay_h"] / 2.0
    base = base.cut(                       # 外侧：摸得到的指示坑
        _box_xyz(-tx - 1.0, -tx + TOUCH_MARK_D,
                 ty - TOUCH_MARK_W / 2.0, ty + TOUCH_MARK_W / 2.0,
                 tz - TOUCH_MARK_H / 2.0, tz + TOUCH_MARK_H / 2.0)
    )
    base = base.cut(                       # 内侧：模块座，挖到只剩 TOUCH_WALL
        _box_xyz(-tx + TOUCH_WALL, -bay_x + 0.01,
                 ty - TOUCH_W / 2.0, ty + TOUCH_W / 2.0,
                 tz - TOUCH_H / 2.0, tz + TOUCH_H / 2.0)
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


def build_touch_solid() -> cq.Workplane:
    """触摸区的实心修改器体。

    它不是零件，是**给切片器看的一块体积**：罩住底座侧壁的触摸区，在 Bambu Studio 里
    右键底座 → 添加修改器 → 加载这个 → 稀疏填充改 100%。稀疏填充里全是空腔，
    电容耦合会被吃掉大半，触摸时灵时不灵，问题就出在这儿。灯箱的顶面触摸也是这么做的。
    """
    p = params()
    tx = p["base_w"] / 2.0
    ty = (p["bay_y0"] + p["bay_y1"]) / 2.0
    tz = COVER_T + COVER_LIP + p["bay_h"] / 2.0
    pad = 3.0  # 四周多罩一点，别让修改器边界正好压在触摸区边上
    return _box_xyz(
        -tx - 0.5, -tx + TOUCH_WALL + 1.0,
        ty - TOUCH_MARK_W / 2.0 - pad, ty + TOUCH_MARK_W / 2.0 + pad,
        tz - TOUCH_MARK_H / 2.0 - pad, tz + TOUCH_MARK_H / 2.0 + pad,
    )


def build_art_mock() -> cq.Workplane:
    """模拟画片：22 层 × 0.08 = 1.76mm 的一片，按公差做小一点（和真画片一样）。

    只进展示模型，不进盘 —— 真画片是网站导的。
    """
    return _prism(ART_W, ART_H, 0.0, 22 * 0.08)


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

    # 灯板翻过来插进前框：盘口朝前，盘底与前框背面齐平。
    # 绕 **Y** 翻，不是绕 X —— 绕 X 翻会把出线豁口一起翻到顶上去，
    # 线就得从画的头顶绕下来。绕 Y 翻只镜像左右（灯板左右对称，无所谓），
    # 豁口留在下缘，正对前框底梁那条出线口。
    module = upright(
        build_module()
        .rotate((0, 0, 0), (0, 1, 0), 180)
        .translate((0.0, 0.0, p["depth"]))
    ).translate((0.0, dy, dz))

    # 模拟画片：躺在前框的画片槽里（z_art 起，留 FIT 的横向间隙）
    art = upright(build_art_mock().translate((0.0, 0.0, p["z_art"]))).translate((0.0, dy, dz))

    # 底盖：扣在电池仓下面，沉进去和底面齐平
    bay_y = (p["bay_y0"] + p["bay_y1"]) / 2.0
    cover = build_cover().translate((0.0, bay_y, 0.0))

    return cq.Workplane("XY").add(
        cq.Compound.makeCompound(
            [build_base().val(), cover.val(), frame.val(), module.val(), art.val()]
        )
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


def plate_layout(
    shapes: dict[str, cq.Workplane] | None = None, *, bed: float = 256.0, gap: float = 3.0
) -> list[tuple[str, cq.Workplane]]:
    """壳子四件怎么摆在一个盘上。

    通用的货架排盘器把四件排成 232 × 244，两头都顶到床边，Bambu 直接报"太靠近
    屏蔽区域"。这里改成按零件自己的形状摆，两个要点：

      · **前框转 90°。** 157 × 107 横着放，才和底座并得成一排；竖着放这一排就
        剩不下宽度了。
      · **底盖塞进前框的取景窗里。** 那块地方本来就是空的，让底盖白占一份面积
        不值。窗口装不下（小规格）时它自动退回去，排在第二排。

    出来大约 244 × 218（100×150 那档），比原来矮了 26mm —— 屏蔽区在床的前后两头，
    矮下来才是有用的。
    """
    if shapes is None:
        shapes = {name: fn() for name, fn in PARTS.items()}

    def rot90(w: cq.Workplane) -> cq.Workplane:
        return w.rotate((0, 0, 0), (0, 0, 1), 90.0)

    def size(w: cq.Workplane) -> tuple[float, float]:
        bb = w.val().BoundingBox()
        return bb.xlen, bb.ylen

    frame = rot90(shapes["frame"])
    base_ = rot90(shapes["base"])
    module = rot90(shapes["module"])
    cover = shapes["cover"]

    fw, fh = size(frame)
    bw, bh = size(base_)
    mw, mh = size(module)
    cw, ch = size(cover)

    # 底盖能不能塞进取景窗：窗口跟着前框一起转了 90°，留 2mm 不贴边
    p = params()
    win_w, win_h = p["window_h"], p["window_w"]
    nested = cw + 2.0 <= win_w and ch + 2.0 <= win_h

    row1_h = max(fh, bh)
    row2_w = mw if nested else mw + gap + cw
    row2_h = mh if nested else max(mh, ch)
    total_w = max(fw + gap + bw, row2_w)
    total_h = row1_h + gap + row2_h

    if max(total_w, total_h) > bed - 8.0:
        print(f"  ⚠ 摆盘 {total_w:.1f} × {total_h:.1f} 超出可用范围，这个规格得拆两盘")

    # 组内坐标（左上角为原点、y 向下）→ 床坐标
    def put(shape: cq.Workplane, x: float, y: float, w: float, h: float) -> cq.Workplane:
        return place(shape, x + w / 2.0 - total_w / 2.0, total_h / 2.0 - (y + h / 2.0))

    out = [
        ("frame", put(frame, 0.0, 0.0, fw, fh)),
        ("base", put(base_, fw + gap, 0.0, bw, bh)),
        ("module", put(module, 0.0, row1_h + gap, mw, mh)),
    ]
    if nested:
        # 和前框同心 —— 前框的包围盒中心就是窗口中心
        fb = out[0][1].val().BoundingBox()
        out.append(("cover", place(cover, (fb.xmin + fb.xmax) / 2.0, (fb.ymin + fb.ymax) / 2.0)))
    else:
        out.append(("cover", put(cover, mw + gap, row1_h + gap, cw, ch)))
    return out


def export_all(out_dir: str, *, tolerance: float = 0.05) -> dict[str, str]:
    paths: dict[str, str] = {}
    shapes = {name: fn() for name, fn in PARTS.items()}
    for name, shape in shapes.items():
        stl = os.path.join(out_dir, f"ringframe_{name}.stl")
        step = os.path.join(out_dir, f"ringframe_{name}.step")
        cq.exporters.export(shape, stl, tolerance=tolerance, angularTolerance=0.2)
        cq.exporters.export(shape, step)
        paths[f"{name}_stl"], paths[f"{name}_step"] = stl, step

    # 壳子四件的摆盘见 plate_layout()。
    # 画片不在这儿 —— 它由网站按画幅单独出，壳只打一次、画片要打很多次。
    packed = [plate_layout(shapes)]
    plates = [
        (f"外壳 {i + 1}/{len(packed)}" if len(packed) > 1 else "外壳全套", items)
        for i, items in enumerate(packed)
    ]
    paths["project_3mf"] = write_bambu_3mf(
        os.path.join(out_dir, "ringframe.3mf"), plates, tol=tolerance
    )
    paths["_plates"] = str(len(packed))
    # 再出一份"四件摊平"的 STEP：装配体适合看，但要改尺寸、加特征的时候
    # 四件叠在一起没法下手。这一份就是盘上那个摆位，一个文件拖进 CAD 就能改。
    flat = cq.Workplane("XY")
    for _, shape in packed[0]:
        flat = flat.add(shape)
    paths["parts_step"] = os.path.join(out_dir, "ringframe_parts.step")
    cq.exporters.export(flat, paths["parts_step"])

    # 触摸修改器：单独一件，不进盘（它不是要打的东西）
    touch = build_touch_solid()
    paths["touch_step"] = os.path.join(out_dir, "ringframe_touch_modifier.step")
    paths["touch_stl"] = os.path.join(out_dir, "ringframe_touch_modifier.stl")
    cq.exporters.export(touch, paths["touch_step"])
    cq.exporters.export(touch, paths["touch_stl"], tolerance=tolerance, angularTolerance=0.2)

    # 装配好的展示模型：四件 + 模拟画片，看的就是这一个
    asm = build_assembly()
    paths["assembly_step"] = os.path.join(out_dir, "ringframe_assembly.step")
    paths["assembly_stl"] = os.path.join(out_dir, "ringframe_assembly.stl")
    cq.exporters.export(asm, paths["assembly_step"])
    cq.exporters.export(asm, paths["assembly_stl"], tolerance=tolerance, angularTolerance=0.2)
    return paths


def _plate_note() -> str:
    items = plate_layout()
    xs = [v for _, sh in items for v in (sh.val().BoundingBox().xmin, sh.val().BoundingBox().xmax)]
    ys = [v for _, sh in items for v in (sh.val().BoundingBox().ymin, sh.val().BoundingBox().ymax)]
    return f"整组 {max(xs) - min(xs):.1f} × {max(ys) - min(ys):.1f} mm（前框转 90°，底盖尽量塞进取景窗）"


def spec() -> list[tuple[str, str]]:
    p = params()
    return [
        ("前框", f'{p["frame_w"]:.1f} × {p["frame_h"]:.1f} × {p["depth"]:.1f} mm'),
        ("灯板模块", f'{p["mod_w"]:.1f} × {p["mod_h"]:.1f} × {p["module_h"]:.1f} mm 浅盘'),
        (
            "立起来",
            f'{p["base_w"]:.1f} 宽 × {BASE_D:.0f} 深 × 约 {p["stand_h"]:.0f} 高，'
            + ("直立 90°" if abs(TILT) < 0.01 else f"后仰 {TILT:.0f}°"),
        ),
        (
            "插槽",
            f"深 {GROOVE_DEPTH:.0f}、间隙 {GROOVE_FIT:.2f} → 顶端晃动 ±{p['sway']:.1f} mm"
            + ("" if p["sway"] < 5.0 else "  ← **太晃，把槽加深或把间隙收紧**"),
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
            f'5V、PCB 宽 {LED_W:.0f}mm，**平贴盘底绕一圈**、灯珠朝前，'
            f"120 珠/米、CRI ≥ 90、4000–5000K",
        ),
        ("腔深", f'{CAVITY_D:.1f} mm，灯条平贴只占 {LED_T:.1f}，**混光距离 {p["mix_gap"]:.1f} mm**'),
        (
            "直射盲区",
            f'中间 {p["dark_w"]:.0f} × {p["dark_h"]:.0f} mm 没有直射光，'
            f"靠扩散片和白内壁匀 —— 正中会比四边暗一点，这是平贴一圈的代价",
        ),
        (
            "发光区余量",
            f'灯板腔口比取景窗每边宽 {p["lit_margin"]:.1f} mm'
            + ("" if p["lit_margin"] > 0.3 else "  ← **不够！盘壁会在画面边上投影，把 BEZEL_LAP 调大**"),
        ),
        ("内腔", "必须够白：灯板用白色 PLA 打，或盘内贴白色反光膜。这是功能不是装饰"),
        (
            "电池仓",
            f'{p["bay_w"]:.0f} × {p["bay_d"]:.0f} × {p["bay_h"]:.1f} mm（底座后半段，底盖可拆）；'
            f'电池 {BAT_LONG:.0f}×{BAT_SHORT:.0f}×{BAT_H:.1f} '
            f'{"装得下" if p["bay_d"] >= BAT_SHORT and p["bay_h"] >= BAT_H and p["bay_w"] >= BAT_LONG else "**装不下**"}',
        ),
        (
            "电路板",
            f'{PCB_W:.0f} × {PCB_D:.0f} × {PCB_H:.0f} mm 的位；'
            f"背面 Type-C {USB_W:.1f}×{USB_H:.1f}（R{USB_R}，同灯箱）",
        ),
        (
            "侧面触摸",
            f"左侧壁，模块座 {TOUCH_W:.0f}×{TOUCH_H:.0f}，剩壁厚 {TOUCH_WALL:.1f}；"
            f"外面 {TOUCH_MARK_W:.0f}×{TOUCH_MARK_H:.0f} 浅坑指示。"
            f"**触摸区必须 100% 填充** —— 用 ringframe_touch_modifier 当修改器",
        ),
        ("摆盘", f"ringframe.3mf —— 一盘四件：{_plate_note()}"),
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description="两件式灯画框：出 STL/STEP/3MF 与料单")
    ap.add_argument(
        "--preset",
        choices=["frame", "standee"],
        help="frame = 160×120 横幅画框（默认）；standee = 100×150 竖版立牌，边框收窄",
    )
    ap.add_argument("--art", metavar="WxH", help="画片尺寸，例如 150x100")
    ap.add_argument("--cavity", type=float, help="腔深 mm")
    ap.add_argument("--tilt", type=float, help="后仰角度")
    args = ap.parse_args()
    if args.preset == "standee":
        # 立牌：竖版、边框收窄。压边不能再往下压了 —— 它必须大于
        # CAVITY_INSET + MODULE_RIM，否则灯板的盘壁会从取景窗里探出来挡光，
        # 所以窄边框只能从 WALL 上要。
        globals()["ART_W"], globals()["ART_H"] = 100.0, 150.0
        globals()["WALL"] = 3.5

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
    print("  1. 灯带平贴进盘底四周那圈沉台，灯珠朝前（朝画片）；线从盘底豁口出去")
    print("  2. 画片、扩散片从前框背面放进去，靠在压边上")
    print("  3. 灯板整体压进前框插口，四个卡扣咔一下。背面与前框齐平")
    print("  4. 换画片：抠出灯板 → 换画片 → 压回去")
    print("  5. 电池与电路板装在底座后半段的仓里，线从插槽后墙那条口子通到灯板；底盖卡上")
    print("  6. 触摸模块贴进左侧壁那个座里，感应面朝外贴住 1.5mm 的壁")


if __name__ == "__main__":
    main()
