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
import itertools
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
# 画片槽。实测最厚 1.6；生成器的理论上限是 22 层 × 0.08 = 1.76，槽必须连它也吃得下。
# 1.85 对 1.6 的片子留 0.25，对 1.76 的极限片子还留 0.09 —— 再厚的片子生成器出不来。
# 和扩散片槽加起来的总间隙是 0.45，就是"卡得住又推得进"的那个量。
ART_T_MEASURED = 1.6  # 你量的实物
ART_T_MAX = 22 * 0.08  # 生成器能出的最厚
ART_SLOT_T = 1.85

# —— 光学 ——
DIFFUSER_T = 0.5      # 扩散片，磨砂 PET/PP。雾度靠材料不靠厚度
DIFFUSER_SLOT_T = 0.7
CAVITY_D = 10.0       # 灯板盘壁高度，也就是腔深。灯带平贴只占 LED_T，剩下的是混光距离
# 前框里托住扩散片的那圈台阶宽度，同时决定灯板插口大小。
# 必须小于 BEZEL_LAP，否则台阶会从取景窗里露出来。
#
# 从 1.5 收到 0.6：画片要从背面**穿过这个插口**才能进槽，所以画片印多大被它卡死。
# 1.5 时画片只能印到 156.8，比自己的槽（160.3）小了每边 1.75mm —— 实物里
# "跟灯板一样大、卡不住"就是这么来的。收窄之后画片印到 158.5，余量降到 0.9。
# 收到 0：画片要从背面**穿过这个插口**才进得了槽，所以插口有多大，画片就只能印多大。
# 0.6 时画片印 98.6，而它自己的槽是 100.3 —— 每边空 0.85，画片在里面晃，
# 正面还看得见一圈缝（网站上画片是贴着框的，实物却离框有段距离，就是这 0.85）。
# 归零之后插口和槽一样宽，画片印到 100.0 = 画幅原尺寸，每边只剩 0.15 的装配缝。
#
# 扩散片原来靠这圈台阶托着，现在改成叠在画片上、一起压在压边上 —— 本来就是一摞，
# 少一级台阶不影响。灯腔口比取景窗每边还宽 4.35，不会在画面上投影。
CAVITY_INSET = 0.0

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
# 正面四边各压住画片多少。压边吃掉的是画片，本来一直往小了取 ——
# 但实物证明压不住：4.0 时只压住画片 2.25mm，而画片在自己的槽里每边还有
# 1.75mm 的横向余量，一晃就走位。压边宽一点是唯一能从正面按住它的东西。
BEZEL_LAP = 6.0
BEZEL_CHAMFER = 1.0   # 压边背面台阶根部的 45° 倒角，会被钳到 BEZEL_T - 0.6
WALL = 7.0            # 画片槽外侧的结构壁厚。看到的边框 = BEZEL_LAP + WALL
FIT = 0.3             # 画片槽 / 扩散片槽的横向公差
# 画片实际印多大：比灯板插口再小一点，能**直着推进去**，不用掰。
# 以前画片是按画片槽做的，比插口每边大 1.5mm，只能斜着掰 —— 越厚越掰不动，
# 1.2mm 就是掰得动的极限。缩到插口以内之后，多厚都进得去。
# 代价是白边窄一圈：可见画面一点没少，少的是本来就被压边盖住的那一圈。
ART_INSERT_FIT = 0.3  # 画片比插口小多少（总量）。0.15/边，够推进去，又不至于晃
FRAME_R = 6.0         # 外圆角。必须大于 BACK_BEVEL，见 build_frame 里的钳位
BACK_BEVEL = 5.0      # 背面外沿的 45° 斜切，让侧面看着薄

# —— 灯板模块 ——
# 盘底厚，它就是背板。1.0 的时候用手一推就能把画片整个顶动 ——
# 背板是画片唯一的后靠，薄了就等于没靠。
#
# 1.8 还是不够：这块板 159 × 119，四周只有 1.5mm 的盘壁撑着，中间什么都没有，
# 实物上肉眼可见地凹下去一片。板的抗弯正比于厚度的三次方 ——
# 1.8 → 2.8 是 (2.8/1.8)³ ≈ 3.8 倍，这一步比加什么加强筋都直接，
# 而且盘底在腔里，加筋会在画面上投出暗带，加厚不会。
MODULE_BACK_T = 2.8
MODULE_RIM = 1.5      # 盘壁厚
MODULE_FIT = 0.3      # 灯板外形比前框插口小多少（总量）
# 卡扣。原来不生效的原因很硬：盘壁四边闭合成一个盒，**盒是不会向内让的**，
# 0.25mm 的过盈要么插不进去、要么直接把凸起刮平，两种都等于没有卡扣。
# 所以每个卡扣两侧各开一条通到盘口的豁口，把它变成一根从盘底悬出来的舌头 ——
# 有了舌头才谈得上"压下去再弹回来"。能让了，凸起也就敢做高一点。
SNAP_H = 0.6          # 卡扣凸起高度
SNAP_LEN = 15.0       # 每个卡扣长度
SNAP_AT = 0.55        # 卡扣在盘壁高度上的相对位置
SNAP_RELIEF = 0.8     # 卡扣两侧的让位豁口宽度，0 = 不开（退回闭合盒）

# —— 底座 ——
# 底座同时是配重、插座和电池仓。电池和电路板只能放这儿：
# 灯板那个腔是光学件，塞进去任何不透光的东西都会在画面上投影。
BASE_T = 16.0         # 底板厚。要装得下 10.5mm 的软包电池，10mm 远不够
BASE_D = 84.0         # 进深。插槽挪到靠前，后面整片留给电池仓
BASE_MARGIN = 5.0
GROOVE_Y = 24.0       # 插槽中心距底座前沿。靠前放，后面才腾得出电池仓
# 插槽**打穿**到底盖：不再留槽底。
#
# 留槽底的代价是一道 107 × 13 的平顶悬在 10mm 高处（底座是上表面朝下打的，
# 槽底在打印姿态里就是个天花板）。13mm 的桥本来跨得过去，但只要开着支撑，
# 切片器就会往槽里灌一堆。打穿之后那个面根本不存在，整个底座一处朝下悬空都没有。
#
# 顺带两个好处：插深从 10 变成 14.4（= BASE_T − COVER_T），晃动量跟着降；
# 画片的重量直接压在底盖上，而底盖是与底面齐平坐在桌上的，不吃弯。
# 0.12 实物偏松：插深只有 14.4，而立牌有 136 高，间隙被放大将近十倍 ——
# 顶端晃 ±1.19mm，手一碰画框就摆。减半到 0.06，晃动跟着减半到 ±0.60。
# 再往下就有装不进去的风险（打印的槽本来就偏窄），先走这一步。
GROOVE_FIT = 0.06       # 实物偏松、画框会晃，从 0.25 收到 0.12
COVER_EDGE = 2.8      # 底盖四周留给外壁的宽度
TILT = 0.0            # 90° 直立。要回后仰版把这里改回 8
BASE_R = 6.0
# 插槽后墙正中一条口子，过两根线（正负）就够，不用更大
BASE_WIRE_W = 6.0
BASE_WIRE_H = 3.0

# —— 电池仓（按手上的实物件定）——
# 电池：523450 锂电 1000mAh 带保护板。裸电芯 5.2×34×50，
#       保护板贴在短边上，长度按 52 算，厚度留到 6.0（软包会鼓一点）。
# 电路板：图里那块半圆板，35.5 × 18.8，Type-C 焊在直边正中。
# 电池横着放：长边沿 X，短边沿 Y（吃电池仓的进深）。
BAT_LONG = 52.0       # 电池长边（沿 X），含保护板
BAT_SHORT = 34.0      # 电池短边（沿 Y）—— 电池仓进深要大于它
BAT_H = 6.0           # 电池厚 —— 电池仓净高要大于它
PCB_W = 35.5          # 电路板宽（沿 X）
PCB_D = 18.8          # 电路板深（沿 Y）
PCB_H = 7.0           # 连 Type-C 壳一起的最高点
# 背面 USB-C 开口。尺寸和圆角照抄灯箱那个母本（web/src/engine/shell.ts 的 USB）——
# 切成直角方口插头也塞得进，但四角各露一块空隙，插头还不被孔壁扶正，手感和外观都是坏的。
USB_W = 9.3
USB_H = 3.5
USB_R = 1.65
# 开口下沿距仓底 = 板子坐在仓底时，Type-C 壳底离板底的高度。
# 这个数直接抄灯箱母本（web/src/engine/shell.ts 的 USB.liftZ）—— 那边是
# 「躺倒的外壳，内底面到 Type-C 口底」，和这里是同一个量，也正是这块板的高度。
USB_Z = 1.55
# **口的位置从仓顶算，不从仓底算，而且用的就是 USB_Z 这个数。**
#
# 灯箱那边 USB_Z 量的是「板子贴着安装面时，Type-C 壳底离安装面多高」。
# 灯箱的安装面在下（板子躺在内底面上），立牌这边板子是热熔螺丝吊在顶壁上、
# **板底贴着仓顶**，安装面翻到了上面 —— 同一个 1.55，方向反过来：
# 从仓顶往下量到口的上沿。
#
# 仓高 11.9、板高 7.0，底下空着 4.9mm 什么都没有。按仓底算就是赌板子会落到底，
# 而它被螺丝吊着，根本不会 —— 实物里得在底下垫一块电池才对得上口。
USB_FROM_TOP = True
# 沉台离底座外顶面至少留这么多料。口挪到仓顶附近之后，14×8 的沉台会往上顶到
# 顶壁里；不管的话那一角只剩薄薄一层，看着像没做完。够不到就整体往下让。
USB_BORE_TOP_MIN = 1.2
# Type-C 靠左摆：板子 35.5 宽，贴着电池仓左端放，右边整条留给 52mm 的电池。
# 居中的话板子会把仓从中间劈开，两边谁都放不下电池。
USB_X = -1.0          # <0 = 靠左，0 = 居中，>0 = 靠右

# —— 侧面触摸 ——
# 拨动开关换成侧面轻触。开关要在壳上开个洞、还要对准拨柄，触摸只要一块够薄够实的壁。
# 「实」比「薄」更要紧：稀疏填充里全是空腔，电容耦合会被吃掉大半，所以触摸区那块
# 必须 100% 填充 —— 和灯箱顶面触摸用的是同一招（buildTopSolidModifier），
# 这里由 build_touch_solid() 出一块修改器体，在切片器里挂上去。
# —— 侧面触摸（右侧壁）——
# 内壁保持平的：铜箔是贴上去的，一凹进去就贴不平、贴不牢。所以不掏座、不减壁，
# 只在外面凸一块当指示 —— 手摸得到才知道往哪按。
# 代价是感应要穿过整道 4mm 侧壁再加这块凸台，比原来的 1.5mm 厚不少，
# 所以触摸区 100% 填充这一步（ringframe_touch_modifier）从"建议"变成"必须"。
TOUCH_SIDE = 1        # +1 = 右侧壁，-1 = 左侧壁
TOUCH_PAD_W = 26.0    # 外凸指示块，沿 Y
TOUCH_PAD_H = 10.0    # 沿 Z
# 改成**往里凹**。外凸有两处不好：手指摸到的是最厚的地方（壁厚 3.0 再加 1.2），
# 感应要穿 4.2mm；而且凸起在侧面很扎眼。凹进去正相反 —— 手指自然落进这个窝，
# 位置比凸起还好找，而且那一块壁只剩 3.0 − 1.2 = 1.8mm，耦合路径短了一半还多。
TOUCH_PAD_OUT = -1.2  # <0 = 内凹，>0 = 外凸
TOUCH_PAD_R = 3.0     # 凸块圆角，别硌手
# 凸起做成**空心环**，不是实心块。实心块正好压在感应区上，手指到内壁的路径
# 从 3.0 变成 4.2 —— 本来就是要让它薄一点，加个实心块等于反着来。
# 环只在四周凸，中间那一块还是原壁厚，摸得到位置又不增加厚度。
# 内凹之后不需要留环了：环当初是为了避开"实心块压在感应区上加厚路径"，
# 而凹坑本来就是在减厚。整块凹下去，手感也整。
TOUCH_PAD_RING = 0.0  # 环的宽度；0 = 整块（内凹时固定用这个）
BAY_WALL = 2.5        # 电池仓顶壁（也就是底座上表面那层）
# 电池仓四周的壁厚。原来写死 4.0，比顶壁 2.5 厚不少 —— 壁厚不匀不好看，
# 而且 Type-C 那面 4mm 太厚：插头的包胶还没进去就顶到壳了，插不到位。
BASE_WALL = 3.0
# Type-C 口那一面单独再薄一点：外面挖个沉台，只留这么厚。
# 插头包胶那一圈能沉进去，才插得到底。
USB_FACE_T = 1.5
USB_BORE_W = 14.0     # 沉台开多大（按 Type-C 插头包胶的常见外形留的）
USB_BORE_H = 8.0
USB_BORE_R = 2.0
COVER_T = 1.6         # 底盖厚
COVER_FIT = 0.3
COVER_LIP = 1.2       # 底盖沉入量，装上后与底面齐平
# —— 底盖卡扣 ——
# 原来是一道方棱：从底盖侧面直挺挺凸出 0.4，跨在 z = COVER_T ± 0.6 上。
# 三处都不成立，所以实物上按不进去、按进去也留不住：
#
#   · **没有东西会让。** 棱长在一块 1.6 厚的整板边上，对面是 3mm 厚的箱壁 ——
#     两边都不弯，那 0.4 就只能硬挤，挤不过去。
#   · **没有导入斜面。** 方棱对方坑，是"撞上去"而不是"滑进去"。
#   · **打印姿态不成立。** 底盖平躺打，这道棱有一半悬在板面之上（1.6 → 2.2），
#     底下什么都没有，打出来是塌的、尺寸也不准 —— 就是你说的摆放问题。
#
# 改法三条一起：棱做成**上窄下宽的楔形**（平躺打时逐层内收，自支撑，
# 顺带上面那面就是导入斜面）；棱**只占底盖自己的厚度**，不再探到板面之上；
# 两侧开豁口，让它坐在一根悬臂舌头上 —— 有东西能让，才谈得上卡扣。
COVER_SNAP = 0.5      # 凸出多少（有舌头能让，比原来的 0.4 再给一点，扣得更实）
COVER_SNAP_H = 1.0    # 楔形的高度：底面到顶面，1.0 升 0.5 是 27° 的自支撑斜面
COVER_SNAP_LEN = 20.0 # 每处的长度
COVER_SNAP_RELIEF = 1.0  # 舌头两侧的豁口宽；0 = 不开（退回不会弯的整板）
# **给打印偏差留的余量。**
#
# 图纸上对得上，实物上对不上 —— 因为 FDM 的坑总比图纸小、凸总比图纸大：
# 坑的顶面是悬空的，会往下垂进坑里；凸出来的料会往外摊。两头一凑，
# 0.15 的间隙实际是负的，所以按不进去。
#
# 更要命的是底座**倒着打**（上表面朝下），底盖坑那道留住卡扣的台肩正好朝下 ——
# 整个零件上最容易垂的位置，偏偏是配合面。
#
# 两条一起治：坑四周各放 0.35；卡扣和坑都做成**上下都是斜面的菱形**，
# 没有一个水平面朝下，垂不下来。留住底盖靠的是舌头的弹力顶住斜面，
# 不是靠一道方肩勾住 —— 对一块电池盖够用，而且这个能打得出来。
COVER_SNAP_CLR = 0.35
# 舌头单独削薄。**板厚才是按不进去的主因** —— 1.6 的板在 20mm 长度上几乎不弯，
# 开了豁口也一样，因为弯的刚度按厚度三次方走：1.6 → 1.0 就软了 4 倍，
# 同样的力才推得动那 0.5 的过盈。
# 只削舌头那一小条，底盖其余部分还是 1.6，跨 111mm 不会软塌塌。
COVER_TONGUE_T = 1.0


def _cover_snap_plan(depth: float) -> dict:
    """底盖卡扣落在哪、多长 —— 底盖和底座都读这一份，不各算各的。"""
    slot_half = (depth + GROOVE_FIT) / 2.0
    a0, a1 = COVER_EDGE, GROOVE_Y - slot_half              # 插槽前面那段净空
    b0, b1 = GROOVE_Y + slot_half, BASE_D - COVER_EDGE     # 插槽后面那段
    margin = 2.0                                           # 两头各留一点，别顶到尽头
    usable = min(a1 - a0, b1 - b0) - 2.0 * margin
    length = max(6.0, min(COVER_SNAP_LEN, usable))
    return {
        "snap_len": length,
        "snap_y0": (a0 + a1) / 2.0,
        "snap_y1": (b0 + b1) / 2.0,
    }


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
        # 画片实际印多大（网站按这个出图），以及压边还能压住它多少
        "art_print_w": socket_w - ART_INSERT_FIT,
        "art_print_h": socket_h - ART_INSERT_FIT,
        "bezel_hold": ((socket_w - ART_INSERT_FIT) - window_w) / 2.0,
        # 底盖卡扣的 y 位置与长度。**必须避开画框插槽** —— 插槽从上面一直切到
        # 底盖，落在它范围里的卡扣坑会被整个铲掉。原来按沉槽长度的 0.25/0.75 摆，
        # 前面那个正好骑在插槽上：坑长 20.7，被切走 17.0，只剩两截碎的，
        # 一长一短、中心也不在卡扣中间 —— 而底盖上的卡扣是对称的，于是对不上。
        # 现在把插槽前后两段净空各取中点，长度按短的那段来定。
        **_cover_snap_plan(z_socket + module_h),
        # 灯条平贴盘底，凸进腔里的只有它自己的厚度；剩下的全是混光距离
        "mix_gap": CAVITY_D - LED_T,
        "led_run": cav_w - 8.0,
        # 盘底减掉四周那圈灯带之后，中间还剩多大一块没有直射光
        "dark_w": cav_w - 2.0 * LED_W,
        "dark_h": cav_h - 2.0 * LED_W,
        # Type-C 在 X 上的位置：板子贴着仓的一端放，孔跟着板子中心走
        "usb_cx": (
            0.0
            if abs(USB_X) < 1e-9
            else (1.0 if USB_X > 0 else -1.0)
            * (((frame_w + 2.0 * BASE_MARGIN) / 2.0 - BASE_WALL) - PCB_W / 2.0 - 2.0)
        ),
        # 触摸区在底座侧壁上，壁厚由电池仓的让位决定
        "side_wall": ((frame_w + 2.0 * BASE_MARGIN) / 2.0) - ((frame_w + 2.0 * BASE_MARGIN) / 2.0 - 4.0),
        "bevel": min(BACK_BEVEL, max(0.0, FRAME_R - 0.8)),
        "bezel_chamfer": min(BEZEL_CHAMFER, max(0.0, BEZEL_T - 0.6)),
        # 卡扣在前框坐标里的深度（灯板背面与前框背面齐平）
        "snap_z": depth - (MODULE_BACK_T + CAVITY_D * SNAP_AT),
        "base_w": frame_w + 2.0 * BASE_MARGIN,
        # 插槽打穿到底盖顶面，所以插深由板厚和底盖厚定，不再是一个独立参数
        "groove_depth": BASE_T - COVER_T,
        # 电池仓：插槽后方那一整片。前沿离插槽留 4mm 肉
        "bay_y0": GROOVE_Y + (depth + GROOVE_FIT) / 2.0 + BASE_WALL,
        "bay_y1": BASE_D - BASE_WALL,
        # 仓底就是底盖沉槽的顶，中间不该再留一层 —— 留了就是把仓封死
        "bay_h": BASE_T - BAY_WALL - COVER_T,
        "bay_w": (frame_w + 2.0 * BASE_MARGIN) - 2.0 * BASE_WALL,
        "bay_d": (BASE_D - BASE_WALL) - (GROOVE_Y + (depth + GROOVE_FIT) / 2.0 + BASE_WALL),
        "stand_h": BASE_T + (frame_h - (BASE_T - COVER_T)) * math.cos(math.radians(TILT)),
        # 顶端能晃多少：槽里的间隙被画高放大了这么多倍
        "sway": (frame_h - (BASE_T - COVER_T)) * (GROOVE_FIT / (BASE_T - COVER_T)),
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

        # 先开让位豁口：每个卡扣两侧各一条，从盘底往上一路通到盘口，
        # 中间那段盘壁就成了一根悬臂舌头，能被压进去再弹回来。
        # 豁口不切到盘底：底留 0.6，腔还是密的，光不会从这儿漏出去。
        if SNAP_RELIEF > 1e-4:
            for sx in (-1, 1):
                inner = sx * (p["mod_w"] / 2.0 - MODULE_RIM - 0.6)
                outer = sx * (p["mod_w"] / 2.0 + SNAP_H + 1.0)
                for sy in (-1, 1):
                    cy = sy * p["mod_h"] / 4.0
                    for side in (-1, 1):
                        y0 = cy + side * SNAP_LEN / 2.0 - SNAP_RELIEF / 2.0
                        tray = tray.cut(
                            _box_xyz(
                                min(inner, outer), max(inner, outer),
                                y0, y0 + SNAP_RELIEF,
                                MODULE_BACK_T + 0.6, p["module_h"] + 1.0,
                            )
                        )

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

    # 插槽，挪到靠前。往下一直开到底盖沉槽顶面 —— 打穿，不留槽底
    slot = (
        cq.Workplane("XY")
        .rect(p["frame_w"] + GROOVE_FIT, p["depth"] + GROOVE_FIT)
        .extrude(60.0)
        .translate((0.0, 0.0, -p["groove_depth"]))
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
    bay_x = p["base_w"] / 2.0 - BASE_WALL
    z_bay0 = COVER_T
    z_bay1 = z_bay0 + p["bay_h"]
    base = base.cut(
        _box_xyz(-bay_x, bay_x, p["bay_y0"], p["bay_y1"], z_bay0, z_bay1)
    )

    # 底盖沉槽：铺满整个底面（只留四周外壁），底盖沉进去与底面齐平。
    # 铺满是必须的 —— 插槽要打穿到这儿，槽底才不存在；顺带底盖变成一整块底板，
    # 前后两段被插槽切开之后靠它连成一体，走线也藏在下面。
    base = base.cut(
        _box_xyz(
            -(bay_x + COVER_LIP),
            bay_x + COVER_LIP,
            COVER_EDGE,
            BASE_D - COVER_EDGE,
            -1.0,
            COVER_T + 0.1,
        )
    )

    # 底盖卡扣凹坑。坑要比楔形高一点、深一点：楔形靠底面那道肩留住，
    # 坑底就得在肩的下面，扣进去才有"咔"的一下。
    if COVER_SNAP > 1e-4:
        # 坑跟着卡扣做成菱形，四周放 COVER_SNAP_CLR。坑里没有一个水平面朝下，
        # 倒着打也垂不下来 —— 这正是原来那道方坑做不到的事。
        z_mid = max(0.5, COVER_T - COVER_SNAP_H / 2.0)
        c = COVER_SNAP_CLR
        snap_len = p["snap_len"]
        for sx in (-1, 1):
            for y in (p["snap_y0"], p["snap_y1"]):
                x_in = sx * (bay_x + COVER_LIP)
                x_out = sx * (bay_x + COVER_LIP + COVER_SNAP + c)
                prof = (
                    cq.Workplane("XZ")
                    .polyline([
                        (x_in, z_mid - COVER_SNAP_H / 2.0 - c),
                        (x_out, z_mid),
                        (x_in, z_mid + COVER_SNAP_H / 2.0 + c),
                    ])
                    .close()
                    .extrude(snap_len + 2.0 * c)
                    .translate((0.0, y - snap_len / 2.0 - c, 0.0))
                )
                base = base.cut(prof)

    # 走线：从插槽后墙通到电池仓，贴着底盖走
    z0 = COVER_T + 0.1
    base = base.cut(
        _box_xyz(
            -BASE_WIRE_W / 2.0, BASE_WIRE_W / 2.0,
            GROOVE_Y, p["bay_y0"] + 2.0, z0, z0 + BASE_WIRE_H,
        )
    )

    # 背面 Type-C：圆角口，尺寸照灯箱母本；靠一边摆，把电池那条留整。
    # 高度从**仓顶**往下量，见 USB_FROM_TOP —— 仓比板子高出 4.9mm，
    # 按仓底算等于赌板子会落到底。
    usb_cx = p["usb_cx"]
    if USB_FROM_TOP:
        usb_cz = z_bay1 - USB_Z - USB_H / 2.0      # 板底贴仓顶，同一个 USB_Z 反着量
    else:
        usb_cz = z_bay0 + USB_Z + USB_H / 2.0
    # 沉台单独定心：口贴着仓顶时，居中的沉台会顶穿顶壁。往下让到留够料为止，
    # 但不能让到盖不住口 —— 两个条件夹出来的位置。
    bore_cz = usb_cz
    top_limit = BASE_T - USB_BORE_TOP_MIN - USB_BORE_H / 2.0
    if bore_cz > top_limit:
        bore_cz = max(top_limit, usb_cz + USB_H / 2.0 - USB_BORE_H / 2.0 + 0.4)
    base = base.cut(
        _round_slot(
            USB_W, USB_H, USB_R,
            p["bay_y1"] - 1.0, BASE_D + 1.0,
            cx=usb_cx,
            cz=usb_cz,
        )
    )

    # Type-C 外面挖个沉台：这一面只留 USB_FACE_T，插头的包胶才沉得进去。
    # 不挖的话要穿 BASE_WALL 整道壁，插头顶着壳，插不到底。
    if BASE_WALL - USB_FACE_T > 0.05:
        base = base.cut(
            _round_slot(
                USB_BORE_W, USB_BORE_H, USB_BORE_R,
                BASE_D - (BASE_WALL - USB_FACE_T), BASE_D + 1.0,
                cx=usb_cx,
                cz=bore_cz,
            )
        )

    # 侧面触摸。TOUCH_PAD_OUT < 0 = 往里凹一个窝：手指自然落进去，比凸起还好找，
    # 而且那一块壁只剩 BASE_WALL − |OUT|，感应路径短一半还多。内壁不动 ——
    # 铜箔仍然贴在平的内壁上。
    sx = 1.0 if TOUCH_SIDE >= 0 else -1.0
    tx = p["base_w"] / 2.0
    ty = (p["bay_y0"] + p["bay_y1"]) / 2.0
    tz = z_bay0 + p["bay_h"] / 2.0
    if abs(TOUCH_PAD_OUT) > 1e-4:
        depth_out = abs(TOUCH_PAD_OUT)
        recess = TOUCH_PAD_OUT < 0.0

        def _pad(w: float, h: float, r: float) -> cq.Workplane:
            # 凸：从外壁往外长 depth_out，再往里咬 0.6 保证和壁焊在一起。
            # 凹：从外壁往里挖 depth_out，再往外伸 0.6 保证切得干净。
            blk = (
                cq.Workplane("XY")
                .box(depth_out + 0.6, w, h, centered=(False, True, True))
                .translate((
                    sx * tx - (
                        (0.6 if sx > 0 else depth_out) if not recess
                        else (depth_out if sx > 0 else 0.6)
                    ),
                    ty, tz,
                ))
            )
            if r > 1e-4:
                try:
                    blk = blk.edges("|X").fillet(min(r, min(w, h) / 2.0 - 0.01))
                except Exception:  # noqa: BLE001
                    pass
            return blk

        pad = _pad(TOUCH_PAD_W, TOUCH_PAD_H, TOUCH_PAD_R)
        if not recess and TOUCH_PAD_RING > 1e-4:
            iw = TOUCH_PAD_W - 2.0 * TOUCH_PAD_RING
            ih = TOUCH_PAD_H - 2.0 * TOUCH_PAD_RING
            if iw > 1.0 and ih > 1.0:
                pad = pad.cut(_pad(iw, ih, max(0.0, TOUCH_PAD_R - TOUCH_PAD_RING)))
        base = base.cut(pad) if recess else base.union(pad)

    if print_orientation:
        base = base.rotate((0, 0, 0), (1, 0, 0), 180)
        bb = base.val().BoundingBox()
        base = base.translate((0.0, -bb.ymin, -bb.zmin))
    return base


def build_cover() -> cq.Workplane:
    """电池仓底盖。平躺打，卡扣朝上。"""
    p = params()
    bay_x = p["base_w"] / 2.0 - BASE_WALL
    w = 2.0 * (bay_x + COVER_LIP) - COVER_FIT
    d = (BASE_D - 2.0 * COVER_EDGE) - COVER_FIT
    cover = (
        cq.Workplane("XY")
        .box(w, d, COVER_T, centered=(True, True, False))
        .edges("|Z")
        .fillet(3.0)
    )
    if COVER_SNAP > 1e-4:
        # 菱形剖面：最宽处在中间，上下各一道斜面。
        # 上面那道是导入斜面（推进去时先碰到它），下面那道负责留住。
        # 两道都是斜的 = 没有水平面朝下 = 打印时不会垂，见 COVER_SNAP_CLR。
        z_mid = max(0.5, COVER_T - COVER_SNAP_H / 2.0)
        z_top = COVER_T
        z_bot = max(0.2, z_mid - COVER_SNAP_H / 2.0)
        snap_len = p["snap_len"]
        half = snap_len / 2.0
        # 底盖是居中建的，而 snap_y* 是底座坐标 —— 减去沉槽中心换算过去
        recess_mid = (COVER_EDGE + (BASE_D - COVER_EDGE)) / 2.0
        for sx in (-1, 1):
            for yc in (p["snap_y0"] - recess_mid, p["snap_y1"] - recess_mid):
                prof = (
                    cq.Workplane("XZ")
                    .polyline([
                        (sx * w / 2.0, z_bot),
                        (sx * (w / 2.0 + COVER_SNAP), z_mid),
                        (sx * w / 2.0, z_top),
                    ])
                    .close()
                    .extrude(snap_len)
                    .translate((0.0, yc + half, 0.0))
                )
                cover = cover.union(prof)
                # 舌头削薄：从板顶挖掉一层，只留 COVER_TONGUE_T。
                # 削的是朝仓内那一面，外面看不出来。
                if COVER_TONGUE_T < COVER_T - 1e-4:
                    cover = cover.cut(
                        _box_xyz(
                            min(sx * (w / 2.0 - 6.0), sx * (w / 2.0 + 1.0)),
                            max(sx * (w / 2.0 - 6.0), sx * (w / 2.0 + 1.0)),
                            yc - half - COVER_SNAP_RELIEF,
                            yc + half + COVER_SNAP_RELIEF,
                            COVER_TONGUE_T, COVER_T + 1.0,
                        )
                    )
                # 豁口：把卡扣那一段从整板上"切"出一根悬臂舌头。
                # 不开豁口的话，0.5 的过盈要靠整块板去弯 —— 弯不动，就按不进去。
                if COVER_SNAP_RELIEF > 1e-4:
                    for sy2 in (-1, 1):
                        y = yc + sy2 * (half + COVER_SNAP_RELIEF / 2.0)
                        cover = cover.cut(
                            _box_xyz(
                                min(sx * (w / 2.0 - 5.0), sx * (w / 2.0 + 1.0)),
                                max(sx * (w / 2.0 - 5.0), sx * (w / 2.0 + 1.0)),
                                y - COVER_SNAP_RELIEF / 2.0, y + COVER_SNAP_RELIEF / 2.0,
                                -1.0, COVER_T + 1.0,
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
    sx = 1.0 if TOUCH_SIDE >= 0 else -1.0
    tx = p["base_w"] / 2.0
    ty = (p["bay_y0"] + p["bay_y1"]) / 2.0
    tz = COVER_T + p["bay_h"] / 2.0
    pad = 3.0  # 四周多罩一点，别让修改器边界正好压在触摸区边上
    x0 = sx * tx - (0.0 if sx > 0 else TOUCH_PAD_OUT + 1.0)
    x1 = sx * tx + (TOUCH_PAD_OUT + 1.0 if sx > 0 else 0.0)
    inner = sx * (tx - BASE_WALL - 1.5)   # 罩穿整道侧壁：铜箔贴内壁，中间不能有稀疏填充
    return _box_xyz(
        min(x0, x1, inner), max(x0, x1, inner),
        ty - TOUCH_PAD_W / 2.0 - pad, ty + TOUCH_PAD_W / 2.0 + pad,
        tz - TOUCH_PAD_H / 2.0 - pad, tz + TOUCH_PAD_H / 2.0 + pad,
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
    dz = BASE_T - p["groove_depth"] - bb.zmin   # 画片坐到底盖顶面上
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

    # 底盖：现在是一整块底板，扣满整个底面
    cover = build_cover().translate((0.0, BASE_D / 2.0, 0.0))

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


# 整组在床上的偏移：往右、往后各挪一点，离前沿左边那块屏蔽区远些。
#
# 这只能是补刀，不是主刀。整组 234 宽、床 256，左右一共就 22mm 余量：
# 居中是左右各 11，往右挪 3 就变成左 14 / 右 8，再挪右边比原来的左边还窄，
# 等于把问题从一边搬到另一边。真正解决问题的是让前角本来就没有零件
# （见 plate_layout 里的 clears_corners），偏移只是顺手再多要 3mm。
PLATE_BIAS = (3.0, 3.0)


def plate_split(
    shapes: dict[str, cq.Workplane],
    *,
    attach: dict | None = None,
    bed: float = 256.0,
) -> list:
    """能一盘就一盘，一盘放不下就找一个两盘的分法。

    **立牌（--preset standee，100×150）是放得下的**：四件 235.8 × 227.6 一盘装完，
    底盖套在前框的取景窗里。会走到分盘这条路的是默认的 frame 预设（160×120 横幅），
    它的前框 174×134、灯板 159×119，光这两件最紧也要 174 × 256，超 9mm；
    四件一起要 240 × 366，超 119mm。

    以前排不下就退化成"一列排到底"，出来 452mm 长的一盘，等于把摆盘丢回给人。
    现在穷举所有二分，两边都得自己排得下，取**较大那盘最小**的一组 ——
    frame 预设下最优是「前框 + 底盖」和「底座 + 灯板」，各 181×215 和 184×206。
    """
    one = plate_layout(shapes, attach=attach, bed=bed, strict=True)
    if one is not None:
        return [one]

    names = list(shapes)
    best = None
    for r in range(1, len(names)):
        for pick in itertools.combinations(names, r):
            rest = tuple(n for n in names if n not in pick)
            if not rest:
                continue
            a = plate_layout({k: shapes[k] for k in pick},
                             attach=attach, bed=bed, strict=True)
            if a is None:
                continue
            b = plate_layout({k: shapes[k] for k in rest},
                             attach=attach, bed=bed, strict=True)
            if b is None:
                continue
            span = max(_span(a), _span(b))
            if best is None or span < best[0]:
                best = (span, a, b, pick, rest)
    if best is None:
        print("  ⚠ 连两盘都排不下 —— 退回一列排到底，自己在切片器里摆")
        return [plate_layout(shapes, attach=attach, bed=bed)]
    _, a, b, pick, rest = best
    print(f"  一盘放不下，拆两盘：[{' + '.join(pick)}] 和 [{' + '.join(rest)}]")
    return [a, b]


def _span(items: list) -> float:
    """一盘上所有零件的最长边。"""
    xs0 = xs1 = ys0 = ys1 = None
    for entry in items:
        bb = entry[1].val().BoundingBox()
        xs0 = bb.xmin if xs0 is None else min(xs0, bb.xmin)
        xs1 = bb.xmax if xs1 is None else max(xs1, bb.xmax)
        ys0 = bb.ymin if ys0 is None else min(ys0, bb.ymin)
        ys1 = bb.ymax if ys1 is None else max(ys1, bb.ymax)
    return max(xs1 - xs0, ys1 - ys0)


def plate_layout(
    shapes: dict[str, cq.Workplane] | None = None,
    *,
    bed: float = 256.0,
    gap: float = 3.0,
    keepout: tuple[float, float] = (28.0, 34.0),
    strict: bool = False,
    bias: tuple[float, float] = PLATE_BIAS,
    attach: dict[str, list[tuple[str, cq.Workplane]]] | None = None,
) -> list:
    """壳子四件怎么摆在一个盘上。

    穷举「每件转不转 90°」「先放谁」「一行放多宽」，挑最长边最短的那个。之后再做
    两件事，都是为了躲开热床前沿那两块屏蔽区：

      · **宽的行摆后面，窄的摆前面。** 前沿才是屏蔽区所在，让最窄的一行去靠前。
      · **每行左右居中。** 行一居中，窄行的两个前角就空出来了 —— 整组还是 234 宽，
        但前面那一行只有 157，左右各让出 38mm。

    光把整组居中是不够的：234 宽的组居中之后四边各剩 11mm，而屏蔽区比 11mm 深，
    落在前排最外侧的那一件照样会踩进去。得让那个角上**没有零件**，不是让它离得远。

    底盖如果塞得进前框的取景窗就塞进去 —— 那块地方本来就是空的。
    """
    if shapes is None:
        shapes = {name: fn() for name, fn in PARTS.items()}
    attach = attach or {}

    def size(w: cq.Workplane) -> tuple[float, float]:
        bb = w.val().BoundingBox()
        return bb.xlen, bb.ylen

    def rot(w: cq.Workplane, deg: int) -> cq.Workplane:
        return w if deg == 0 else w.rotate((0, 0, 0), (0, 0, 1), 90.0)

    p = params()
    # 套嵌只在「前框和底盖同在一盘」时才谈得上 —— 分盘之后可能只来一件
    cw, ch = size(shapes["cover"]) if "cover" in shapes else (0.0, 0.0)
    kx, ky = keepout

    def arrange(placed, total_w):
        """按行重排：宽的行往后，每行左右居中。返回 (新的 placed, 总高)。"""
        rows: dict[float, list] = {}
        for item in placed:
            rows.setdefault(round(item[2], 3), []).append(item)
        packs = []
        for items in rows.values():
            w = max(x + w_ for _, x, _, w_, _ in items) - min(x for _, x, _, _, _ in items)
            packs.append((w, max(h for *_, h in items), items))
        packs.sort(key=lambda r: -r[0])          # 宽的排前面 = 摆到后面
        out = []
        y = 0.0
        for w, h, items in packs:
            x0 = min(it[1] for it in items)
            dx = (total_w - w) / 2.0 - x0        # 这一行整体居中
            for i, x, _, iw, ih in items:
                out.append((i, x + dx, y, iw, ih))
            y += h + gap
        return out, y - gap

    def clears_corners(placed, total_w, total_h):
        """整组摆到床上之后，两个前角的屏蔽区里不能有零件。"""
        ox = (bed - total_w) / 2.0 + bias[0]
        oy = (bed - total_h) / 2.0 + bias[1]
        for _, x, y, w, h in placed:
            bx0, bx1 = ox + x, ox + x + w
            by0 = oy + (total_h - (y + h))       # 组内 y 向下 → 床上 y 向后
            if by0 >= ky:
                continue
            if bx0 < kx or bx1 > bed - kx:
                return False
        return True

    best = None
    have = [n for n in ("frame", "base", "module", "cover") if n in shapes]
    can_nest = "cover" in shapes and "frame" in shapes
    for nest in ((True, False) if can_nest else (False,)):
        names = [n for n in have if not (nest and n == "cover")]
        for rots in itertools.product((0, 90), repeat=len(names)):
            dims = []
            for n, r in zip(names, rots, strict=True):
                w, h = size(shapes[n])
                dims.append((h, w) if r == 90 else (w, h))
            if nest:
                win = (p["window_w"], p["window_h"])
                if rots[names.index("frame")] == 90:
                    win = (win[1], win[0])
                if not (cw + 2.0 <= win[0] and ch + 2.0 <= win[1]):
                    continue
            for order in itertools.permutations(range(len(names))):
                for limit in (150.0, 170.0, 190.0, 200.0, 210.0, 220.0, 230.0, 240.0, bed - 9.0):
                    x = y = row_h = 0.0
                    total_w = 0.0
                    placed = []
                    for i in order:
                        w, h = dims[i]
                        if x > 0 and x + gap + w > limit:
                            y += row_h + gap
                            x = 0.0
                            row_h = 0.0
                        if x > 0:
                            x += gap
                        placed.append((i, x, y, w, h))
                        x += w
                        total_w = max(total_w, x)
                        row_h = max(row_h, h)
                    placed, total_h = arrange(placed, total_w)
                    if max(total_w, total_h) > bed - 9.0:
                        continue
                    if not clears_corners(placed, total_w, total_h):
                        continue
                    key = (round(max(total_w, total_h), 2), round(total_w + total_h, 2))
                    if best is None or key < best[0]:
                        best = (key, total_w, total_h, nest, names, rots, placed)

    if best is None:
        if strict:
            return None
        print("  ⚠ 排不出既放得下、前角又空着的摆法 —— 这个规格得拆两盘")
        y = 0.0
        out = []
        for n, sh in shapes.items():
            w, h = size(sh)
            out.append((n, place(sh, 0.0, -y)))
            y += h + gap
        return out

    _, total_w, total_h, nest, names, rots, placed = best
    bx, by = bias
    out: list = []
    frame_box = None
    for i, x, y, w, h in placed:
        name = names[i]
        shape = rot(shapes[name], rots[i])
        bb = shape.val().BoundingBox()
        tx = (bx + x + w / 2.0 - total_w / 2.0) - (bb.xmin + bb.xmax) / 2.0
        ty = (by + total_h / 2.0 - (y + h / 2.0)) - (bb.ymin + bb.ymax) / 2.0
        moved = shape.translate((tx, ty, 0.0))
        if name == "frame":
            frame_box = moved.val().BoundingBox()
        # 附件（比如触摸区的修改器）必须走**同一套**转向 + 平移。
        # 只跟平移不跟转向的话，零件转了 90° 修改器还留在原地，罩到零件外面去 ——
        # 而这种错切片器不报，只是静静地不生效。
        mods = [
            (mname, rot(mshape, rots[i]).translate((tx, ty, 0.0)))
            for mname, mshape in attach.get(name, [])
        ]
        out.append((name, moved, mods) if mods else (name, moved))
    if nest and frame_box is not None:
        out.append(
            (
                "cover",
                place(
                    shapes["cover"],
                    (frame_box.xmin + frame_box.xmax) / 2.0,
                    (frame_box.ymin + frame_box.ymax) / 2.0,
                ),
            )
        )
    return out


# 生成物统一放 out/，跟源码分开。
#
# 以前是直接吐在 shell_master/ 里：6 个源文件混着三十来个 stl/step/3mf/png，
# 四百多 KB 的源码埋在 4.5MB 的产物里，`ls` 一下根本找不到要改的那个文件。
# 产物全是跑一次脚本就能重来的东西，不该和源码平级。
OUT_SUBDIR = "out"


def _out_dir(here: str) -> str:
    d = os.path.join(here, OUT_SUBDIR)
    os.makedirs(d, exist_ok=True)
    return d


# 当前跑的是哪个预设。两个预设的零件尺寸差着一大截（frame 前框 174×134，
# standee 107×157），以前却都写同一个 ringframe.3mf —— 谁后跑谁覆盖，
# 而文件名上看不出区别。拿错了要到切片器里量尺寸才发现。
PRESET = "frame"


def _stem() -> str:
    return "ringframe" if PRESET == "frame" else f"ringframe_{PRESET}"


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
    # 触摸区的实心修改器挂在底座对象上，不再让人手动加载一个 STL。
    # 修改器必须和它要修改的本体同对象 —— 单独摆一个对象修改不到任何东西，
    # 灯箱那边的顶壁实心也是这么挂的。
    #
    # 先跟着底座翻成打印姿态；排盘那一步的转向和平移由 plate_layout 一并施加。
    touch = (
        build_touch_solid()
        .rotate((0, 0, 0), (1, 0, 0), 180)
        .translate((0.0, BASE_D, BASE_T))
    )
    packed = plate_split(shapes, attach={"base": [("触摸区实心", touch)]})
    plates = [
        (f"外壳 {i + 1}/{len(packed)}" if len(packed) > 1 else "外壳全套", items)
        for i, items in enumerate(packed)
    ]
    paths["project_3mf"] = write_bambu_3mf(
        os.path.join(out_dir, f"{_stem()}.3mf"), plates, tol=tolerance
    )
    paths["_plates"] = str(len(packed))
    # 再出一份"四件摊平"的 STEP：装配体适合看，但要改尺寸、加特征的时候
    # 四件叠在一起没法下手。这一份就是盘上那个摆位，一个文件拖进 CAD 就能改。
    flat = cq.Workplane("XY")
    for entry in packed[0]:
        flat = flat.add(entry[1])   # 条目可能带修改器，只取本体
    paths["parts_step"] = os.path.join(out_dir, "ringframe_parts.step")
    cq.exporters.export(flat, paths["parts_step"])

    # 触摸修改器也单独出一份：3MF 里已经挂在底座上了，这份是留给
    # 手动装配 / 换切片软件的时候用的
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
    shapes = {
        "frame": build_frame(), "module": build_module(),
        "base": build_base(print_orientation=True), "cover": build_cover(),
    }
    plates = plate_split(shapes)
    out = []
    for items in plates:
        bbs = [entry[1].val().BoundingBox() for entry in items]
        w = max(b.xmax for b in bbs) - min(b.xmin for b in bbs)
        h = max(b.ymax for b in bbs) - min(b.ymin for b in bbs)
        out.append(f"{'+'.join(n for n, *_ in items)} {w:.1f} × {h:.1f}")
    return (
        f"{len(plates)} 盘：" + "；".join(out)
        + "（穷举取最长边最短；宽的行摆后面、每行居中，让开前沿屏蔽区）"
    )


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
            f"打穿到底盖，插深 {p['groove_depth']:.1f}、间隙 {GROOVE_FIT:.2f} → "
            f"顶端晃动 ±{p['sway']:.1f} mm"
            + ("" if p["sway"] < 5.0 else "  ← **太晃，把间隙收紧**"),
        ),
        ("底盖", f'{p["base_w"] - 5.6 - COVER_FIT:.1f} × {BASE_D - 2 * COVER_EDGE - COVER_FIT:.1f} '
                 f"× {COVER_T} mm 整块底板；插槽的底就是它"),
        (
            "画片",
            f'实印 {p["art_print_w"]:.1f} × {p["art_print_h"]:.1f} mm（比插口小 {ART_INSERT_FIT}，'
            f"直着推进去，不用掰)，厚 ≤1.76（22 层 × 0.08）",
        ),
        (
            "压边压住",
            f'每边 {p["bezel_hold"]:.2f} mm'
            + ("" if p["bezel_hold"] >= 1.5 else "  ← **太少，画片边缘会从正面露出来**"),
        ),
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
            "卡扣",
            f"凸起 {SNAP_H}、每侧两处 × {SNAP_LEN:.0f} 长；两边各开 {SNAP_RELIEF} 的让位豁口，"
            f"盘壁才让得动 —— 不开豁口的闭合盒压不下去，等于没有卡扣",
        ),
        ("背板", f"盘底 {MODULE_BACK_T} 厚，画片的后靠就是它"),
        ("底座壁厚", f"四周 {BASE_WALL}、顶 {BAY_WALL}、底盖 {COVER_T}（Type-C 那面 {USB_FACE_T}）"),
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
            f"背面 Type-C {USB_W:.1f}×{USB_H:.1f}（R{USB_R}，同灯箱），"
            f"口上沿离**仓顶** {USB_Z} mm"
            f"（板底热熔螺丝吊在顶壁上，同灯箱那个数反着量）、"
            f"{'靠左' if USB_X < 0 else ('靠右' if USB_X > 0 else '居中')}；"
            f"外面挖 {USB_BORE_W:.0f}×{USB_BORE_H:.0f} 沉台，那一面只剩 {USB_FACE_T} 厚，插头才插得到底",
        ),
        (
            "侧面触摸",
            f"{'右' if TOUCH_SIDE >= 0 else '左'}侧壁，内壁保持平的（铜箔贴内壁）；"
            f"外面{'凹进去' if TOUCH_PAD_OUT < 0 else '凸出'}一块 "
            f"{TOUCH_PAD_W:.0f}×{TOUCH_PAD_H:.0f}、深 {abs(TOUCH_PAD_OUT)} 的"
            f"{'窝' if TOUCH_PAD_OUT < 0 else '台'}，那一块壁"
            f"{'只剩' if TOUCH_PAD_OUT < 0 else '仍是'} "
            f"{BASE_WALL - abs(TOUCH_PAD_OUT) if TOUCH_PAD_OUT < 0 else BASE_WALL:.1f} mm。"
            f"**触摸区必须 100% 填充** —— "
            f"用 ringframe_touch_modifier 当修改器，这步不能省",
        ),
        ("摆盘", f"{_stem()}.3mf —— {_plate_note()}"),
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
        globals()["PRESET"] = "standee"

    if args.art:
        w, h = (float(v) for v in args.art.lower().split("x"))
        globals()["ART_W"], globals()["ART_H"] = w, h
    if args.cavity:
        globals()["CAVITY_D"] = args.cavity
    if args.tilt is not None:
        globals()["TILT"] = args.tilt

    here = os.path.dirname(os.path.abspath(__file__))
    paths = export_all(_out_dir(here))
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
