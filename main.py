"""FDM 图片画生成器 — 四色 3MF + 圆角灯箱外壳，支持 Open3D 预览。"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
if sys.platform == "win32":
    import winreg
else:  # winreg 仅 Windows 提供；其它平台走 ~/Desktop 回退
    winreg = None  # type: ignore[assignment]
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from collections.abc import Callable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def _ensure_dependencies() -> None:
    missing: list[str] = []
    for module_name, pip_name in (
        ("cv2", "opencv-python"),
        ("numpy", "numpy"),
        ("open3d", "open3d"),
    ):
        try:
            __import__(module_name)
        except ImportError:
            missing.append(pip_name)
    if not missing:
        return

    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "缺少依赖",
        "缺少必要组件：\n"
        + "\n".join(f"  - {name}" for name in missing)
        + "\n\n请先双击运行「安装依赖.bat」，完成后再用「启动.vbs」打开程序。",
    )
    root.destroy()
    sys.exit(1)


_ensure_dependencies()

import cv2
import numpy as np
import open3d as o3d

from bambu_export import (
    BAMBU_PLA_BLACK,
    BAMBU_PLA_CYAN,
    BAMBU_PLA_JADE_WHITE,
    BAMBU_PLA_MAGENTA,
    BAMBU_PLA_YELLOW,
    DEFAULT_SHELL_COLOR,
    FILAMENT_SLOTS,
    MeshPart,
    ShellPart,
    compute_bed_offset,
    hex_to_rgb01,
    normalize_hex_color,
    save_bambu_project_3mf,
)
from preview_window import open_mesh_preview, warmup_open3d
from shell import build_lightbox_shell, shell_mesh_to_3mf_xml, top_solid_modifier_to_3mf_xml
from ui_theme import APP_NAME, APP_VERSION, COLORS, FONTS, apply_theme, make_header

# ---------------------------------------------------------------------------
# 打印 / 光学模型常量
# ---------------------------------------------------------------------------
LAYER_HEIGHT = 0.08
MIN_WHITE_LAYERS = 4

DENSITY_W, DENSITY_C, DENSITY_M, DENSITY_Y = 0.11, 0.58, 0.50, 0.68
MAX_LAYERS_C, MAX_LAYERS_M, MAX_LAYERS_Y = 6, 6, 6

GAMMA_EXPONENT = 0.72
LINEAR_COEFFICIENT = 1.78
RGB_CLIP_MIN = 0.004

# v1=旧通道直映；v2=从图片提取 CMY 三色堆叠（Beer–Lambert + 自适应 UCR）
COLOR_PROFILE = (os.environ.get("FDM_COLOR_PROFILE") or "v3").strip().lower()

# v3：抽掉的中性成分往回加多少。
#
# 印刷里 UCR 抽掉的灰是由黑墨补回去的，我们没有黑墨 —— 补不回来的那部分就是
# 凭空丢掉的暗部。所以物理上唯一站得住的值是 1.0：抽多少，原样加回多少。
#
# 之前设 0.75，理由是"让墨量跟 v2 持平、观感不变"。那个目标本身就选错了：
# v2 的暗部本来就是虚的，跟着它持平等于把这个毛病继承下来。实测那 25% 扣的
# 全是暗部 —— 灰阶明暗跨度 0.566 → 0.607，最暗处透射 0.078 → 0.037，
# 调色板色差 22.3 → 19.7，代价只是墨量多 6%、灯要略亮一点。
UCR_ADD_BACK = float(os.environ.get("FDM_UCR_ADD_BACK", "1.0") or "1.0")
# voxel=像素方格合并（默认，颜色准、切片快）；region=色块轮廓融合（易糊成乱色块）
MESH_MODE = (os.environ.get("FDM_MESH_MODE") or "voxel").strip().lower()
# 300→0.40mm/px（0.4喷嘴）；500→0.25mm/px（0.2喷嘴）；网站统一用 UNIFIED
MM_PER_PX_STANDARD = 0.40
MM_PER_PX_FINE = 0.25
try:
    # 0.20 ≈ 更高清像素点；再密则面数暴涨、切片变慢
    UNIFIED_MM_PER_PX = float(os.environ.get("FDM_MM_PER_PX", "0.20") or "0.20")
except ValueError:
    UNIFIED_MM_PER_PX = 0.20
# 有序抖动幅度（层）：光学分色后只需轻抖动，避免浅灰被铺满
LAYER_DITHER_AMT = float(os.environ.get("FDM_DITHER_AMT", "0.22") or "0.22")
# 有色度时才抬浅层；过低会把灰底也打成三色薄雾
LAYER_KEEP_FLOOR = float(os.environ.get("FDM_KEEP_FLOOR", "0.32") or "0.32")
# 网格前轻度中值：3 即可合并，过大易把薄雾抹成大色块
MESH_MERGE_FILTER = int(os.environ.get("FDM_MESH_MERGE_FILTER", "3") or "3")

FILAMENT_COLORS = {
    "W": np.array(hex_to_rgb01(BAMBU_PLA_JADE_WHITE)),
    "Y": np.array(hex_to_rgb01(BAMBU_PLA_YELLOW)),
    "M": np.array(hex_to_rgb01(BAMBU_PLA_MAGENTA)),
    "C": np.array(hex_to_rgb01(BAMBU_PLA_CYAN)),
}

_BAYER4 = (
    np.array(
        [
            [0, 8, 2, 10],
            [12, 4, 14, 6],
            [3, 11, 1, 9],
            [15, 7, 13, 5],
        ],
        dtype=np.float32,
    )
    / 16.0
    - 0.5
)

BOX_TRIANGLES = np.array(
    [
        (0, 1, 2),
        (0, 2, 3),
        (4, 6, 5),
        (4, 7, 6),
        (0, 4, 5),
        (0, 5, 1),
        (1, 5, 6),
        (1, 6, 2),
        (2, 6, 7),
        (2, 7, 3),
        (3, 7, 4),
        (3, 4, 0),
    ],
    dtype=np.int32,
)


# ---------------------------------------------------------------------------
# 图像与分层
# ---------------------------------------------------------------------------
def load_image_bgr(image_path: str) -> np.ndarray | None:
    try:
        buffer = np.fromfile(image_path, dtype=np.uint8)
        image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    except OSError:
        return None
    return image


# =============================================================================
# 按画风自动取值
#
# 这一套判据和网页端 web/src/ui/studio.ts 里的是同一份，搬过来是因为两边分开
# 各调各的，同一张图桌面 App 和网站就会出两张不一样的画片 —— 而它们本该是
# 同一个产品的两个入口。
#
# 分工也照搬网页：**引擎的默认值一个不动**（parity fixture 钉的就是它们），
# 自动取值是应用层的策略，由 generate_cmyw_layers 算好再传下去。
# =============================================================================

# 量平坦度用的探针尺寸。太小量不准，太大白费时间；网页端也是 192。
FLATNESS_PROBE = 192

# 喷嘴直径。XY 方向上比它细的东西印不出来 —— 要么消失，要么被挤成它这么粗。
NOZZLE_MM = 0.4


def flatness_of(img: np.ndarray) -> float:
    """量这张图有多"平"：相邻像素几乎没有差别的比例。

    平色插画大片同色 → 高；照片就算降采样过也到处是细微渐变 → 低。
    拿它在"照片"和"插画"之间连续取值，比让人自己二选一细腻 ——
    真实素材（带纹理的厚涂、有噪点的扫描线稿）大多落在中间。

    **只量，不缩**。缩放放在 flatness_probe() 里 —— 这个分工要和 TS 侧一致，
    否则两边同名函数吃的其实是不同分辨率的图，量出来的数当然对不上，
    而且这种错在各自单测里都看不出来。
    """
    a = img.astype(np.int16)
    right = np.abs(a[:-1, :-1] - a[:-1, 1:]).max(axis=2)
    down = np.abs(a[:-1, :-1] - a[1:, :-1]).max(axis=2)
    return float((np.maximum(right, down) <= 2).mean())


def flatness_probe(img_bgr: np.ndarray) -> float:
    """流水线用：先缩到探针尺寸再量。太小量不准，太大白费时间。"""
    probe = cv2.resize(
        img_bgr, (FLATNESS_PROBE, FLATNESS_PROBE), interpolation=cv2.INTER_AREA
    )
    return flatness_of(probe)


def art_score(flat: float) -> float:
    """平坦度 → 0（照片）..1（插画）。两端阈值按降采样后的实测量级定。"""
    return float(min(1.0, max(0.0, (flat - 0.35) / 0.4)))


def dither_amount_for(flat: float) -> float:
    """抖动幅度：按平坦度在照片档和插画档之间连续取值。

    实测过一件要紧的事：**抖动幅度不到一整个量化步长，等于完全没开**。
    0.22 / 0.5 / 0.7 三档量出来的色调误差都是 0.230，和关掉一模一样 ——
    因为抖动只有跨过一整步才可能改变取整的结果。

    所以这里只有两个真实档位：这个（≈ 关）和满幅。满幅确实把色调误差压到
    0.041，但相邻格子有 7% 的层数不同，落到实物上就是满脸 0.4mm 的网点，
    实测下来不能接受。真正的出路是让量化台阶变细，不是在粗台阶上抖 ——
    见 README 里记的那条：在 343 种可打印组合里找渲染最接近的一组，
    平均色差 24.6 → 16.9，而且不用抖动。那条路的距离判据还没调好，没上。
    """
    return float(LAYER_DITHER_AMT) * (1.0 - art_score(flat))


def keep_floor_for(flat: float) -> float:
    """浅色保留阈值：越"平"压得越低，最低压到默认值的两成。

    这条线在照片里挡的是噪点，在线稿里挡掉的却是淡线和抗锯齿边 ——
    而平色画面本来就没有噪点要挡。
    """
    return float(LAYER_KEEP_FLOOR) * (1.0 - 0.8 * art_score(flat))


def lift_chroma_only_for(flat: float) -> bool:
    """门槛一降就必须同时打开它，否则降下来的门槛会被中性底顶穿。

    need = 这一色自己的彩色度 + k_back（三色平摊的中性成分）。门槛压在 need 上时，
    彩色度为 0 的通道也能靠 k_back 顶过去，被抬成整整一层：饱和蓝里多一层黄就发绿，
    中性灰细线里多一层品红就发粉。这两种情况只在门槛降下来之后才够得着，
    所以这两件事是同一个开关的两半，不该分开。
    """
    return keep_floor_for(flat) < float(LAYER_KEEP_FLOOR)


def mesh_merge_filter_for(flat: float) -> int:
    """网格化前的中值滤波：线稿要关掉，否则 1–2 像素宽的笔画会被抹平。

    代价是矩形变多、三角形涨。
    """
    return 1 if art_score(flat) > 0.5 else int(MESH_MERGE_FILTER)


def dither_screen_for(flat: float) -> str:
    """用网点，按喷嘴尺寸放大。

    中间试过线网（每行一条连续挤出线），几何量确实只有网点的四分之一，
    但**图案周期 = 级数 × 行距 = 1.6mm**，横在 97mm 宽的画上就是六十道杠，
    脸上一眼就看得见。线网适合行距能压到看不见的场合，这儿压不下去 ——
    再细就掉到喷嘴以下了。

    换线网本来是为了救「切不动」，而切不动的真正原因是导出没收到抖动块参数，
    跑成了格子尺度的网点（750 万三角形）。那个修好之后，按喷嘴放大的网点是
    66 万三角形，切得动，色调误差也更小（0.041 对线网的 0.094）。

    线网的实现留着（dither_screen="line"），行距能压下去的场合还用得上。
    """
    del flat
    return "bayer"


def mm_per_px_for(flat: float) -> float:
    """网格密度 mm/px：插画靠细线吃饭，格子给密一点。

    照片是连续调，标准密度就够，再密只是把三角形和文件撑大。
    喷嘴 0.4mm 是物理下限，0.1 已经比它细一倍，继续加不增加细节。
    """
    k = art_score(flat)
    if k > 0.6:
        return 0.10
    if k > 0.3:
        return 0.15
    return float(UNIFIED_MM_PER_PX)


def dither_block_for(mm_per_px: float | None) -> int:
    """抖动格子要多大：按喷嘴来，不是按网格来。

    抖动是拿相邻格子的层数高低差去换视觉上的中间色。格子比喷嘴小的时候这笔交易
    根本不成立 —— 0.1mm/px 下一个孤立的抖动点只有喷嘴面积的十六分之一，
    印不出来，只会变成一堆多余的三角形，或者被挤成 0.4mm 的一颗麻点。

    所以把 4×4 的 Bayer 图案整体放大到喷嘴尺寸：每个抖动决定覆盖 block×block 个
    格子，落到实物上正好是一个能印出来的点。实测 0.1mm/px、插画度 52% 时，
    亚喷嘴的等值连通块从 1705 个降到 24 个，等值块总数从 1716 降到 132。

    mm_per_px 不知道时返回 1 —— 也就是原来的行为。
    """
    if not mm_per_px or mm_per_px <= 0:
        return 1
    return max(1, int(round(NOZZLE_MM / float(mm_per_px))))


def auto_mm_per_px(image_path: str) -> float:
    """先看一眼图再定网格密度。读不出图就退回统一密度。"""
    img = load_image_bgr(image_path)
    if img is None:
        return float(UNIFIED_MM_PER_PX)
    return mm_per_px_for(flatness_probe(img))


def resolution_to_mm_per_px(resolution: int | float | str | None) -> float:
    """档位 → mm/像素。None / 统一模式 → UNIFIED_MM_PER_PX。"""
    if resolution is None or resolution == "" or resolution == "auto":
        return float(UNIFIED_MM_PER_PX)
    try:
        res = int(resolution)
    except (TypeError, ValueError):
        return float(UNIFIED_MM_PER_PX)
    # 兼容旧订单：300/500 仍映射；其它数值视为已是网格宽，用统一密度
    if res == 300:
        return MM_PER_PX_STANDARD
    if res == 500:
        return MM_PER_PX_FINE
    if 80 <= res <= 1600:
        return float(UNIFIED_MM_PER_PX)
    return float(UNIFIED_MM_PER_PX)


def grid_w_for_print(width_mm: float, resolution: int | float | str | None = None) -> int:
    """按画幅宽度计算解析网格宽。网站默认忽略档位，统一 mm/px。"""
    w = float(width_mm) if width_mm else 120.0
    # 若传入的是已经算好的网格宽（旧草稿/桌面），直接采用
    try:
        res_i = int(resolution) if resolution not in (None, "", "auto") else 0
    except (TypeError, ValueError):
        res_i = 0
    if res_i >= 80 and res_i not in (300, 500):
        return int(max(80, min(1600, res_i)))
    mpp = resolution_to_mm_per_px(resolution)
    return int(max(80, min(1600, round(w / mpp))))


def grid_h_for_print(
    width_mm: float,
    height_mm: float,
    grid_w: int | None = None,
    resolution: int | float | str | None = None,
) -> int:
    """按订单高宽比算网格高，保证实物 mm 尺寸与下单一致（不跟原图比例跑偏）。"""
    w = float(width_mm) if width_mm else 120.0
    h = float(height_mm) if height_mm else w
    gw = int(grid_w) if grid_w and int(grid_w) > 0 else grid_w_for_print(w, resolution)
    pixel = w / max(1, gw)
    return int(max(80, min(1600, round(h / pixel))))


def generate_cmyw_layers(
    image_path: str,
    min_white_layers: int = MIN_WHITE_LAYERS,
    *,
    target_grid_w: int | None = None,
    target_grid_h: int | None = None,
    dither: bool | None = None,
    color_profile: str | None = None,
    auto_tune: bool = True,
    mm_per_px: float | None = None,
) -> dict | None:
    """
    RGB → CMYW 层数：从图片提取 C/M/Y 光学密度并堆叠（v2），白底固定。
    若给 target_grid_w：先缩到打印网格再算层。
    若同时给 target_grid_h：拉伸铺满订单画幅（手动宽高 / 积木相框等）。
    """
    img_bgr = load_image_bgr(image_path)
    if img_bgr is None:
        return None

    # 平坦度必须在缩到打印网格**之前**量：网格重采样本身会抹掉细微渐变，
    # 量出来的"平"就不是这张画的平，而是网格密度的平。网页端也是先在
    # 192×192 的探针上量，再决定参数。
    flat = flatness_probe(img_bgr) if auto_tune else 0.0
    tune = (
        {
            "flatness": round(flat, 4),
            "art_score": round(art_score(flat), 4),
            "dither_amount": round(dither_amount_for(flat), 4),
            "keep_floor": round(keep_floor_for(flat), 4),
            "lift_chroma_only": lift_chroma_only_for(flat),
            "merge_filter": mesh_merge_filter_for(flat),
            "mm_per_px": mm_per_px_for(flat),
            "dither_block": dither_block_for(mm_per_px),
            "dither_screen": dither_screen_for(flat),
        }
        if auto_tune
        else None
    )

    if target_grid_w and target_grid_w > 0:
        tw = int(target_grid_w)
        if target_grid_h and int(target_grid_h) > 0:
            th = int(target_grid_h)
            img_bgr = cv2.resize(img_bgr, (tw, th), interpolation=cv2.INTER_AREA)
        else:
            h0, w0 = img_bgr.shape[:2]
            th = max(1, int(round(h0 * float(tw) / max(1, w0))))
            img_bgr = cv2.resize(img_bgr, (tw, th), interpolation=cv2.INTER_AREA)

    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    img_rgb = np.clip(img_rgb, RGB_CLIP_MIN, 1.0)

    profile = (color_profile or COLOR_PROFILE or "v3").strip().lower()
    use_dither = profile != "v1" if dither is None else bool(dither)
    if profile == "v1":
        n_w, n_y, n_m, n_c = _layers_from_rgb_v1(
            img_rgb, min_white_layers, dither=use_dither
        )
    else:
        builder = _layers_from_rgb_v2 if profile == "v2" else _layers_from_rgb_v3
        n_w, n_y, n_m, n_c = builder(
            img_rgb,
            min_white_layers,
            dither=use_dither,
            dither_amount=tune["dither_amount"] if tune else None,
            keep_floor=tune["keep_floor"] if tune else None,
            lift_chroma_only=bool(tune["lift_chroma_only"]) if tune else False,
            dither_block=int(tune["dither_block"]) if tune else 1,
            dither_screen=str(tune["dither_screen"]) if tune else "bayer",
        )

    result = {"C": n_c, "M": n_m, "Y": n_y, "W": n_w, "shape": img_bgr.shape}
    result["stats"] = layer_stats(result)
    result["color_profile"] = profile
    if tune is not None:
        result["auto"] = tune
    return result


def _bayer_tile(h: int, w: int, block: int = 1) -> np.ndarray:
    """4×4 Bayer 图案铺满整幅。block > 1 时每个格子放大成 block×block。"""
    b = max(1, int(block))
    yy = (np.arange(h) // b) & 3
    xx = (np.arange(w) // b) & 3
    return _BAYER4[yy[:, None], xx[None, :]]


# 线网的级数。级数越多色调越准，但图案周期 = 级数 × 行距，太长就看得见条纹。
LINE_SCREEN_LEVELS = 4


def _line_tile(h: int, w: int, block: int = 1, levels: int = LINE_SCREEN_LEVELS) -> np.ndarray:
    """线网：阈值只沿 Y 变，同一行整行一个值。

    为什么不用网点。网点在 0.4mm（= 喷嘴）尺度上是一颗颗**孤立的点**，
    切片器只能一个个去补 —— 出来满屏的缝隙填充、上千次回抽、换料次数暴涨，
    实测同一张图 44 万三角形还切得一塌糊涂。
    线网的每一行是一条**连续的挤出线**，正是 FDM 干得最顺的事：
    同样的图 1.9 万三角形，色调误差 0.230 → 0.094（网点是 0.041）。
    二十分之一的几何量换来四成的色调精度，而且是真能打出来的那种。
    """
    b = max(1, int(block))
    n = max(2, int(levels))
    row = (np.arange(h) // b) % n
    thr = ((row + 0.5) / n - 0.5).astype(np.float32)
    return np.repeat(thr[:, None], w, axis=1)


def _quantize_layers(
    need: np.ndarray,
    max_layers: int,
    *,
    dither: bool,
    keep_mask: np.ndarray | None = None,
    dither_amount: float | None = None,
    keep_floor: float | None = None,
    neutral: np.ndarray | None = None,
    dither_block: int = 1,
    dither_screen: str = "bayer",
) -> np.ndarray:
    """浮点需求层 → 整数层；抖动减少丢浅色与等高线。

    dither_amount / keep_floor 不传就用模块常数，也就是原来的行为。
    neutral 传进来时，抬浅层的判据先把中性底扣掉 —— 见 lift_chroma_only_for()。
    """
    amount = float(LAYER_DITHER_AMT if dither_amount is None else dither_amount)
    x = need.astype(np.float32)
    if dither and amount > 0.0:
        tile = _line_tile if dither_screen == "line" else _bayer_tile
        x = x + tile(x.shape[0], x.shape[1], dither_block) * amount

    # 抬浅层：把够不到 0.5 的浅色抬成一整层，免得整片消失。
    #
    # 但**满幅抖动时必须让开**。抖动幅度到一整个量化步长时，0.67 层的需求会有
    # 67% 的格子落到 1 层、33% 落到 0 层，平均正好是 0.67 —— 这才是分数层唯一的
    # 表达方式。这时候再抬一手，等于把每一格都按成 1 层，肉色就从 0.67 变成 1.00，
    # 深了一半。抬层是抖动关掉时的兜底，不是和抖动并用的。
    floor = float(LAYER_KEEP_FLOOR if keep_floor is None else keep_floor)
    full_dither = dither and amount >= 1.0
    weight = need if neutral is None else (need - neutral)
    lift = (weight >= floor) & (x < 0.5) & (not full_dither)
    if keep_mask is not None:
        lift = lift & keep_mask.astype(bool)
    x = np.where(lift, 0.51, x)
    return np.clip(np.round(x), 0, max_layers).astype(np.int32)


def _layers_from_rgb_v1(
    img_rgb: np.ndarray,
    min_white_layers: int,
    *,
    dither: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    e_r = (-np.log(img_rgb[..., 0])) ** GAMMA_EXPONENT * LINEAR_COEFFICIENT
    e_g = (-np.log(img_rgb[..., 1])) ** GAMMA_EXPONENT * LINEAR_COEFFICIENT
    e_b = (-np.log(img_rgb[..., 2])) ** GAMMA_EXPONENT * LINEAR_COEFFICIENT
    n_w = np.full(e_r.shape, min_white_layers, dtype=np.int32)
    white_cost = DENSITY_W * n_w
    n_c = _quantize_layers((e_r - white_cost) / DENSITY_C, MAX_LAYERS_C, dither=dither)
    n_m = _quantize_layers((e_g - white_cost) / DENSITY_M, MAX_LAYERS_M, dither=dither)
    n_y = _quantize_layers((e_b - white_cost) / DENSITY_Y, MAX_LAYERS_Y, dither=dither)
    return n_w, n_y, n_m, n_c


def _layers_from_rgb_v2(
    img_rgb: np.ndarray,
    min_white_layers: int,
    *,
    dither: bool,
    dither_amount: float | None = None,
    keep_floor: float | None = None,
    lift_chroma_only: bool = False,
    dither_block: int = 1,
    dither_screen: str = "bayer",
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """从图片直接提取 C/M/Y 三色并堆叠（随图自适应，无偏色补偿旋钮）。

    光学流程（背光透射 / Beer–Lambert）：
      1. 像素 RGB → 目标光学密度 e = (-log T)^γ · α
      2. 扣掉固定白底层吸收，得到各通道还需吸收的密度
      3. 青吸红、品红吸绿、黄吸蓝 → 直接得到 C/M/Y 层需求
      4. 灰成分 K=min(C,M,Y) 按印刷 UCR 拆出：色墨只留色相；
         暗部按该像素自身亮度把一部分 K 加回（换图自动变）
    """
    r = np.asarray(img_rgb[..., 0], dtype=np.float32)
    g = np.asarray(img_rgb[..., 1], dtype=np.float32)
    b = np.asarray(img_rgb[..., 2], dtype=np.float32)

    e_r = (-np.log(r)) ** GAMMA_EXPONENT * LINEAR_COEFFICIENT
    e_g = (-np.log(g)) ** GAMMA_EXPONENT * LINEAR_COEFFICIENT
    e_b = (-np.log(b)) ** GAMMA_EXPONENT * LINEAR_COEFFICIENT

    n_w = np.full(e_r.shape, int(min_white_layers), dtype=np.int32)
    white_cost = float(DENSITY_W) * float(min_white_layers)

    # 提取三色：密度差 / 单层丝密度 = 需求层数
    c = np.maximum(0.0, (e_r - white_cost) / float(DENSITY_C))
    m = np.maximum(0.0, (e_g - white_cost) / float(DENSITY_M))
    y = np.maximum(0.0, (e_b - white_cost) / float(DENSITY_Y))

    # 自适应 UCR：灰雾来自该像素自己的 min(C,M,Y)
    k = np.minimum(np.minimum(c, m), y)
    c_chr = c - k
    m_chr = m - k
    y_chr = y - k
    lum = np.clip((r + g + b) / 3.0, 0.0, 1.0)
    k_back = k * (1.0 - lum) * 0.45
    c = c_chr + k_back
    m = m_chr + k_back
    y = y_chr + k_back

    # 有彩色墨才抬浅层（阈值与 keep_floor 对齐，避免双旋钮漂移）
    floor = float(LAYER_KEEP_FLOOR if keep_floor is None else keep_floor)
    keep_mask = (c_chr + m_chr + y_chr) >= floor
    neutral = k_back if lift_chroma_only else None

    kw = {
        "dither": dither,
        "keep_mask": keep_mask,
        "dither_amount": dither_amount,
        "keep_floor": keep_floor,
        "neutral": neutral,
        "dither_block": dither_block,
        "dither_screen": dither_screen,
    }
    n_c = _quantize_layers(c, MAX_LAYERS_C, **kw)
    n_m = _quantize_layers(m, MAX_LAYERS_M, **kw)
    n_y = _quantize_layers(y, MAX_LAYERS_Y, **kw)
    return n_w, n_y, n_m, n_c



def _layers_from_rgb_v3(
    img_rgb: np.ndarray,
    min_white_layers: int,
    *,
    dither: bool,
    dither_amount: float | None = None,
    keep_floor: float | None = None,
    lift_chroma_only: bool = False,
    dither_block: int = 1,
    dither_screen: str = "bayer",
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """v3：和 v2 同一个光学模型，只改了两处顺序，浅色和中性色就正常了。

    v2 的两个毛病都出在「先除以各自的单层密度，再做 UCR」：

      1. **浅色整段丢失。** 白底自己就吸收 0.44，v2 把它从每个通道扣掉之后
         各自裁到 0 —— 于是任何通道只要亮过 221/255 就一层墨都拿不到。
         浅粉、肉色、脸蛋红晕正好落在这一带，裁完三个通道全是 0，印出来是纯白。
         裁切发生在算色度**之前**，色相信息就这么没了。
      2. **中性色偏粉。** 三色单层密度不等（C .58 / M .50 / Y .68），
         同样的光密度除下来层数就不等，min() 取到的"中性"于是不在同一处，
         一块纯灰会凭空长出色度 —— 量下来 54 级灰阶里 34 级三色不等。

    v3 把 UCR 挪到**光密度空间**：先在 e 上取 min 当中性成分，剩下的才是色度，
    最后各自除以自己的密度。这样纯灰的色度精确是 0（不受密度差影响），
    而浅色的色度也不再被裁切吃掉 —— 印不出来的只有"比白底还亮"的那部分中性量，
    那本来就印不出来。

    实测（946 个浅色 / 54 级灰阶）：
        浅色完全没墨   39% → 1%
        中性灰偏色     34/54 → 11/54
        与原图平均色差 29.1 → 26.9（各自拟合整体增益之后）

    v2 原样保留，--profile v2 还能跑。
    """
    r = np.asarray(img_rgb[..., 0], dtype=np.float32)
    g = np.asarray(img_rgb[..., 1], dtype=np.float32)
    b = np.asarray(img_rgb[..., 2], dtype=np.float32)

    e_r = (-np.log(r)) ** GAMMA_EXPONENT * LINEAR_COEFFICIENT
    e_g = (-np.log(g)) ** GAMMA_EXPONENT * LINEAR_COEFFICIENT
    e_b = (-np.log(b)) ** GAMMA_EXPONENT * LINEAR_COEFFICIENT

    n_w = np.full(e_r.shape, int(min_white_layers), dtype=np.int32)
    white_cost = float(DENSITY_W) * float(min_white_layers)

    # 中性成分在光密度上取，不在层数上取 —— 这是 v3 和 v2 唯一的实质区别
    e_k = np.minimum(np.minimum(e_r, e_g), e_b)

    # 色度：各通道比中性多吸收的那部分，除以自己的单层密度
    c_chr = (e_r - e_k) / float(DENSITY_C)
    m_chr = (e_g - e_k) / float(DENSITY_M)
    y_chr = (e_b - e_k) / float(DENSITY_Y)

    # 中性成分扣掉白底自己的吸收；比白底还亮的部分印不出来，裁掉的只是它
    lum = np.clip((r + g + b) / 3.0, 0.0, 1.0)
    k_back = np.maximum(0.0, e_k - white_cost) * (1.0 - lum) * float(UCR_ADD_BACK)

    c = c_chr + k_back / float(DENSITY_C)
    m = m_chr + k_back / float(DENSITY_M)
    y = y_chr + k_back / float(DENSITY_Y)

    floor = float(LAYER_KEEP_FLOOR if keep_floor is None else keep_floor)
    keep_mask = (c_chr + m_chr + y_chr) >= floor
    # 抬浅层的判据看色度本身，中性底不算数（和 v2 的 lift_chroma_only 同义）
    kw = {
        "dither": dither,
        "keep_mask": keep_mask,
        "dither_amount": dither_amount,
        "keep_floor": keep_floor,
        "dither_block": dither_block,
        "dither_screen": dither_screen,
    }
    n_c = _quantize_layers(
        c, MAX_LAYERS_C, neutral=(k_back / float(DENSITY_C)) if lift_chroma_only else None, **kw
    )
    n_m = _quantize_layers(
        m, MAX_LAYERS_M, neutral=(k_back / float(DENSITY_M)) if lift_chroma_only else None, **kw
    )
    n_y = _quantize_layers(
        y, MAX_LAYERS_Y, neutral=(k_back / float(DENSITY_Y)) if lift_chroma_only else None, **kw
    )
    return n_w, n_y, n_m, n_c


def layer_stats(layers_dict: dict) -> dict:
    """导出/调试用：非零占比与饱和截断粗估。"""
    out: dict = {}
    for key in ("C", "M", "Y", "W"):
        arr = layers_dict.get(key)
        if arr is None:
            continue
        total = int(arr.size)
        nz = int(np.count_nonzero(arr))
        out[key] = {
            "nonzero_pct": round(100.0 * nz / max(1, total), 2),
            "max": int(arr.max()) if total else 0,
            "mean": round(float(arr.mean()), 3) if total else 0.0,
        }
    return out


@dataclass(frozen=True)
class ResizedLayers:
    w: np.ndarray
    y: np.ndarray
    m: np.ndarray
    c: np.ndarray
    grid_h: int
    grid_w: int


def resize_layers(layers_dict: dict, grid_w: int) -> ResizedLayers:
    h_raw, w_raw = layers_dict["W"].shape
    grid_h = int(h_raw * grid_w / w_raw)
    size = (grid_w, grid_h)
    # 已在目标网格上算好的层：直接返回，避免再次最近邻损坏
    if w_raw == grid_w and h_raw == grid_h:
        return ResizedLayers(
            w=layers_dict["W"],
            y=layers_dict["Y"],
            m=layers_dict["M"],
            c=layers_dict["C"],
            grid_h=grid_h,
            grid_w=grid_w,
        )

    return ResizedLayers(
        w=cv2.resize(layers_dict["W"], size, interpolation=cv2.INTER_NEAREST),
        y=cv2.resize(layers_dict["Y"], size, interpolation=cv2.INTER_NEAREST),
        m=cv2.resize(layers_dict["M"], size, interpolation=cv2.INTER_NEAREST),
        c=cv2.resize(layers_dict["C"], size, interpolation=cv2.INTER_NEAREST),
        grid_h=grid_h,
        grid_w=grid_w,
    )


def compute_z_stacks(
    l_w: np.ndarray, l_y: np.ndarray, l_m: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    z_w = np.zeros_like(l_w)
    z_y = l_w.copy()
    z_m = l_w + l_y
    z_c = l_w + l_y + l_m
    return z_w, z_y, z_m, z_c


def max_layer_stack_from_layers(l_w: np.ndarray, l_y: np.ndarray, l_m: np.ndarray, l_c: np.ndarray) -> int:
    return int(np.max(l_w + l_y + l_m + l_c))


def _mesh_merge_filter(layer: np.ndarray, *, size: int = 3) -> np.ndarray:
    """对层高做轻度中值：同高像素连成片，矩形合并率↑、切片更快；0 处保持空洞。"""
    k = int(size)
    if k < 3 or layer.size == 0:
        return layer
    if k % 2 == 0:
        k += 1
    try:
        from scipy.ndimage import median_filter
    except ImportError:
        # OpenCV 中值只支持 8bit；层高通常 ≤6，可安全压缩
        u8 = np.clip(layer, 0, 255).astype(np.uint8)
        med = cv2.medianBlur(u8, k)
        return np.where(layer <= 0, 0, med.astype(np.int32))
    work = layer.astype(np.int32)
    med = median_filter(work, size=k)
    return np.where(work <= 0, 0, med.astype(np.int32))


def merge_voxel_rectangles(
    matrix: np.ndarray,
    z_start_matrix: np.ndarray,
    *,
    layer_height: float = LAYER_HEIGHT,
) -> list[tuple[int, int, int, int, float, float]]:
    """把相同高度/起点的体素合并成大方块，显著减少三角面数量。"""
    h, w = matrix.shape
    used = np.zeros((h, w), dtype=bool)
    rects: list[tuple[int, int, int, int, float, float]] = []

    for y in range(h):
        x = 0
        while x < w:
            if used[y, x] or matrix[y, x] <= 0:
                x += 1
                continue

            layers = int(matrix[y, x])
            zs = int(z_start_matrix[y, x])
            x_end = x + 1
            while (
                x_end < w
                and not used[y, x_end]
                and int(matrix[y, x_end]) == layers
                and int(z_start_matrix[y, x_end]) == zs
            ):
                x_end += 1

            y_end = y + 1
            while y_end < h:
                # 只检查新行，避免反复扫整块
                if (
                    np.any(used[y_end, x:x_end])
                    or not np.all(matrix[y_end, x:x_end] == layers)
                    or not np.all(z_start_matrix[y_end, x:x_end] == zs)
                ):
                    break
                y_end += 1

            used[y:y_end, x:x_end] = True
            z0 = zs * layer_height
            z1 = (zs + layers) * layer_height
            rects.append((x, x_end, y, y_end, z0, z1))
            x = x_end

    return rects


def _boxes_to_3mf_xml(
    x0: np.ndarray,
    x1: np.ndarray,
    y0: np.ndarray,
    y1: np.ndarray,
    z0: np.ndarray,
    z1: np.ndarray,
) -> tuple[str, str]:
    """批量生成立方体 3MF 网格 XML。"""
    count = len(x0)
    if count == 0:
        return "", ""

    verts = np.empty((count, 8, 3), dtype=np.float64)
    verts[:, 0] = np.column_stack([x0, y0, z0])
    verts[:, 1] = np.column_stack([x1, y0, z0])
    verts[:, 2] = np.column_stack([x1, y1, z0])
    verts[:, 3] = np.column_stack([x0, y1, z0])
    verts[:, 4] = np.column_stack([x0, y0, z1])
    verts[:, 5] = np.column_stack([x1, y0, z1])
    verts[:, 6] = np.column_stack([x1, y1, z1])
    verts[:, 7] = np.column_stack([x0, y1, z1])
    flat = verts.reshape(-1, 3)

    vertex_parts: list[str] = []
    chunk = 20000
    for i in range(0, len(flat), chunk):
        block = flat[i : i + chunk]
        vertex_parts.extend(
            f'<vertex x="{a:.3f}" y="{b:.3f}" z="{c:.3f}"/>'
            for a, b, c in block
        )
    vertex_xml = "".join(vertex_parts)

    offsets = np.arange(count, dtype=np.int32) * 8
    triangles = (BOX_TRIANGLES[np.newaxis, :, :] + offsets[:, np.newaxis, np.newaxis]).reshape(-1, 3)
    triangle_xml = "".join(
        f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in triangles
    )
    return vertex_xml, triangle_xml


def _rects_to_world_mm(
    rects: list[tuple[int, int, int, int, float, float]],
    grid_h: int,
    pixel_size: float,
    *,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if not rects:
        empty = np.empty(0, dtype=np.float64)
        return empty, empty, empty, empty, empty, empty

    arr = np.asarray(rects, dtype=np.float64)
    xs0, xs1, ys0, ys1, z0, z1 = arr.T
    x0 = xs0 * pixel_size + offset_x
    x1 = xs1 * pixel_size + offset_x
    y0 = (grid_h - ys1) * pixel_size + offset_y
    y1 = (grid_h - ys0) * pixel_size + offset_y
    return x0, x1, y0, y1, z0, z1


def _mesh_from_rects(
    rects: list[tuple[int, int, int, int, float, float]],
    grid_h: int,
    pixel_size: float,
    filament_color: np.ndarray,
) -> o3d.geometry.TriangleMesh | None:
    if not rects:
        return None

    x0, x1, y0, y1, z0, z1 = _rects_to_world_mm(rects, grid_h, pixel_size)
    count = len(rects)

    verts = np.empty((count, 8, 3), dtype=np.float32)
    verts[:, 0] = np.column_stack([x0, y0, z0])
    verts[:, 1] = np.column_stack([x1, y0, z0])
    verts[:, 2] = np.column_stack([x1, y1, z0])
    verts[:, 3] = np.column_stack([x0, y1, z0])
    verts[:, 4] = np.column_stack([x0, y0, z1])
    verts[:, 5] = np.column_stack([x1, y0, z1])
    verts[:, 6] = np.column_stack([x1, y1, z1])
    verts[:, 7] = np.column_stack([x0, y1, z1])
    vertices_all = verts.reshape(-1, 3)

    colors_all = np.tile(filament_color.astype(np.float32), (count * 8, 1))

    offsets = np.arange(count, dtype=np.int32) * 8
    triangles_all = (BOX_TRIANGLES[np.newaxis, :, :] + offsets[:, np.newaxis, np.newaxis]).reshape(-1, 3)

    mesh = o3d.geometry.TriangleMesh()
    mesh.vertices = o3d.utility.Vector3dVector(vertices_all.astype(np.float64))
    mesh.triangles = o3d.utility.Vector3iVector(triangles_all)
    mesh.vertex_colors = o3d.utility.Vector3dVector(colors_all.astype(np.float64))
    mesh.compute_vertex_normals()
    return mesh


def simulate_transmitted_rgb(
    l_w: np.ndarray,
    l_y: np.ndarray,
    l_m: np.ndarray,
    l_c: np.ndarray,
    brightness_ratio: float = 1.6,
    *,
    stretch: bool = True,
) -> np.ndarray:
    e_r = DENSITY_C * l_c + DENSITY_W * l_w + 0.04 * l_m
    e_g = DENSITY_M * l_m + DENSITY_W * l_w + 0.02 * l_y
    e_b = DENSITY_Y * l_y + DENSITY_W * l_w + 0.03 * l_c

    sim_rgb = np.stack([np.exp(-e_r), np.exp(-e_g), np.exp(-e_b)], axis=-1)
    if stretch:
        # 桌面/体素预览：拉满对比方便看层
        sim_min = sim_rgb.min()
        sim_rgb = (sim_rgb - sim_min) / (sim_rgb.max() - sim_min + 1e-5)
    else:
        # 贴图预览：保留光学相对亮度，避免整图被拉爆成海报色块
        sim_rgb = np.clip(sim_rgb, 0.0, 1.0)
    return np.clip(sim_rgb * brightness_ratio, 0.0, 1.0)


def build_layer_block_preview(
    layer_matrix: np.ndarray,
    z_start_matrix: np.ndarray,
    filament_color: np.ndarray,
    top_override_mask: np.ndarray,
    *,
    grid_h: int,
    pixel_size: float,
    transmitted_colors: np.ndarray,
) -> o3d.geometry.TriangleMesh | None:
    """预览专用：逐像素体素 + 顶面透光色，还原真实观感。"""
    mask = layer_matrix > 0
    if not np.any(mask):
        return None

    y_idx, x_idx = np.where(mask)
    layers = layer_matrix[mask]
    z_start = z_start_matrix[mask]
    count = len(layers)

    x0 = x_idx * pixel_size
    x1 = (x_idx + 1) * pixel_size
    y0 = (grid_h - 1 - y_idx) * pixel_size
    y1 = (grid_h - y_idx) * pixel_size
    z0 = z_start * LAYER_HEIGHT
    z1 = (z_start + layers) * LAYER_HEIGHT

    verts = np.zeros((count, 8, 3), dtype=np.float32)
    verts[:, 0] = np.stack([x0, y0, z0], axis=1)
    verts[:, 1] = np.stack([x1, y0, z0], axis=1)
    verts[:, 2] = np.stack([x1, y1, z0], axis=1)
    verts[:, 3] = np.stack([x0, y1, z0], axis=1)
    verts[:, 4] = np.stack([x0, y0, z1], axis=1)
    verts[:, 5] = np.stack([x1, y0, z1], axis=1)
    verts[:, 6] = np.stack([x1, y1, z1], axis=1)
    verts[:, 7] = np.stack([x0, y1, z1], axis=1)
    vertices_all = verts.reshape(-1, 3)

    colors_cube = np.zeros((count, 8, 3), dtype=np.float32)
    colors_cube[..., :] = filament_color
    colors_cube[:, :4] *= 0.65

    is_top = top_override_mask[mask] == 1
    if np.any(is_top):
        colors_cube[is_top, 4:8] = transmitted_colors[mask][is_top, np.newaxis, :]

    colors_all = colors_cube.reshape(-1, 3)

    offsets = np.arange(count, dtype=np.int32) * 8
    triangles_all = (BOX_TRIANGLES[np.newaxis, :, :] + offsets[:, np.newaxis, np.newaxis]).reshape(-1, 3)

    mesh = o3d.geometry.TriangleMesh()
    mesh.vertices = o3d.utility.Vector3dVector(vertices_all.astype(np.float64))
    mesh.triangles = o3d.utility.Vector3iVector(triangles_all)
    mesh.vertex_colors = o3d.utility.Vector3dVector(colors_all.astype(np.float64))
    # 法线留给预览窗口一次性计算，避免大网格重复开销
    return mesh


def build_layer_block(
    layer_matrix: np.ndarray,
    z_start_matrix: np.ndarray,
    filament_color: np.ndarray,
    *,
    grid_h: int,
    pixel_size: float,
) -> o3d.geometry.TriangleMesh | None:
    rects = merge_voxel_rectangles(layer_matrix, z_start_matrix)
    return _mesh_from_rects(rects, grid_h, pixel_size, filament_color)


@dataclass(frozen=True)
class ShellParams:
    enabled: bool
    wall_thickness: float
    corner_radius: float
    shell_depth: float
    fit_clearance: float
    shell_color_hex: str


def resolve_corner_radius(
    corner_radius: float | None,
    *,
    default: float = 5.0,
) -> float:
    """画片与外壳共用的有效圆角（mm）。

    - None / 未传 → default（默认 5，保证圆角盘面）
    - 显式 0 → 直角（画片与外壳一致）
    - 负值 → 0
    """
    if corner_radius is None:
        return float(default)
    c = float(corner_radius)
    if c < 0.0:
        return 0.0
    return c


def apply_rounded_corner_mask(
    layers: tuple[np.ndarray, ...],
    *,
    physical_width_mm: float,
    corner_radius_mm: float,
) -> tuple[np.ndarray, ...]:
    """按灯箱圆角切除画片四角体素，使画面与圆角框贴合。

    用像素方块与圆角矩形是否相交判断（非仅中心点），避免圆弧上出现缺口。
    """
    if corner_radius_mm <= 1e-6 or not layers:
        return layers
    sample = layers[0]
    grid_h, grid_w = sample.shape
    if grid_w < 2 or grid_h < 2:
        return layers

    pixel = physical_width_mm / grid_w
    w = physical_width_mm
    h = physical_width_mm * grid_h / grid_w
    r = min(float(corner_radius_mm), w * 0.5 - pixel * 0.25, h * 0.5 - pixel * 0.25)
    if r <= 1e-6:
        return layers

    xs = (np.arange(grid_w, dtype=np.float64) + 0.5) * pixel
    ys = (grid_h - np.arange(grid_h, dtype=np.float64) - 0.5) * pixel
    xx, yy = np.meshgrid(xs, ys)
    half = pixel * 0.5

    def _corner_cut(cx: float, cy: float, in_quad: np.ndarray) -> np.ndarray:
        """像素方块完全落在圆角外侧才切除（最近距离 > r）。"""
        nearest_x = np.clip(cx, xx - half, xx + half)
        nearest_y = np.clip(cy, yy - half, yy + half)
        dist2 = (nearest_x - cx) ** 2 + (nearest_y - cy) ** 2
        return in_quad & (dist2 > (r * r))

    outside = (
        _corner_cut(r, r, (xx < r) & (yy < r))
        | _corner_cut(w - r, r, (xx > w - r) & (yy < r))
        | _corner_cut(w - r, h - r, (xx > w - r) & (yy > h - r))
        | _corner_cut(r, h - r, (xx < r) & (yy > h - r))
    )
    keep = ~outside

    # 闭运算补圆弧上的单像素豁口
    keep_u8 = cv2.morphologyEx(
        (keep.astype(np.uint8) * 255),
        cv2.MORPH_CLOSE,
        np.ones((3, 3), np.uint8),
        iterations=1,
    )
    # 软边界：中心不得超过圆角外约 0.35px，防止闭运算糊出灯箱
    r_soft = r + 0.35 * pixel
    soft_out = (
        ((xx < r) & (yy < r) & ((xx - r) ** 2 + (yy - r) ** 2 > r_soft * r_soft))
        | ((xx > w - r) & (yy < r) & ((xx - (w - r)) ** 2 + (yy - r) ** 2 > r_soft * r_soft))
        | (
            (xx > w - r)
            & (yy > h - r)
            & ((xx - (w - r)) ** 2 + (yy - (h - r)) ** 2 > r_soft * r_soft)
        )
        | ((xx < r) & (yy > h - r) & ((xx - r) ** 2 + (yy - (h - r)) ** 2 > r_soft * r_soft))
    )
    keep = (keep_u8 > 0) & (~soft_out)

    masked: list[np.ndarray] = []
    for layer in layers:
        out = layer.copy()
        out[~keep] = 0
        masked.append(out)
    return tuple(masked)


def compile_preview_parts(
    layers_dict: dict,
    physical_width_mm: float,
    grid_w: int,
    shell_params: ShellParams | None = None,
) -> tuple[o3d.geometry.TriangleMesh, o3d.geometry.TriangleMesh | None]:
    """构建预览用画片网格与（可选）灯箱外壳，分体返回。"""
    resized = resize_layers(layers_dict, grid_w)
    l_w, l_y, l_m, l_c = resized.w, resized.y, resized.m, resized.c
    grid_h = resized.grid_h
    corner = resolve_corner_radius(
        shell_params.corner_radius if shell_params else None,
        default=5.0,
    )
    # 与导出一致：画片先挖圆角
    if corner > 1e-6:
        l_w, l_y, l_m, l_c = apply_rounded_corner_mask(
            (l_w, l_y, l_m, l_c),
            physical_width_mm=float(physical_width_mm),
            corner_radius_mm=float(corner),
        )

    pixel_size = physical_width_mm / grid_w
    transmitted = simulate_transmitted_rgb(l_w, l_y, l_m, l_c)
    z_w, z_y, z_m, z_c = compute_z_stacks(l_w, l_y, l_m)

    top_w = (l_y == 0) & (l_m == 0) & (l_c == 0)
    top_y = (l_m == 0) & (l_c == 0)
    top_m = l_c == 0
    top_c = np.ones_like(l_c, dtype=np.int32)

    preview_kwargs = dict(grid_h=grid_h, pixel_size=pixel_size, transmitted_colors=transmitted)

    picture_mesh = o3d.geometry.TriangleMesh()
    for layer_matrix, z_start, color, top_mask in (
        (l_w, z_w, FILAMENT_COLORS["W"], top_w.astype(np.int32)),
        (l_y, z_y, FILAMENT_COLORS["Y"], top_y.astype(np.int32)),
        (l_m, z_m, FILAMENT_COLORS["M"], top_m.astype(np.int32)),
        (l_c, z_c, FILAMENT_COLORS["C"], top_c),
    ):
        mesh = build_layer_block_preview(
            layer_matrix, z_start, color, top_mask, **preview_kwargs
        )
        if mesh is not None:
            picture_mesh += mesh

    shell_mesh: o3d.geometry.TriangleMesh | None = None
    if shell_params and shell_params.enabled:
        max_stack = max_layer_stack_from_layers(l_w, l_y, l_m, l_c)
        art_z = max_stack * LAYER_HEIGHT
        # 画片顶面与灯箱开口齐平并略凸出，减少被侧壁遮挡 / Z-fighting
        slot_z = max(shell_params.wall_thickness, shell_params.shell_depth - art_z + 0.08)
        clearance = max(0.0, shell_params.fit_clearance)
        if len(picture_mesh.vertices) > 0:
            picture_mesh.translate((clearance, clearance, slot_z))
        shell_mesh = build_lightbox_shell(
            physical_width_mm,
            grid_w,
            grid_h,
            max_stack,
            layer_height=LAYER_HEIGHT,
            fit_clearance=shell_params.fit_clearance,
            wall_thickness=shell_params.wall_thickness,
            corner_radius=corner,
            shell_depth=shell_params.shell_depth,
            shell_color=hex_to_rgb01(shell_params.shell_color_hex),
        )
    elif len(picture_mesh.vertices) > 0:
        max_x = physical_width_mm
        max_y = physical_width_mm * grid_h / grid_w
        back_panel = o3d.geometry.TriangleMesh.create_box(max_x, max_y, 1.5)
        back_panel.paint_uniform_color([1.0, 1.0, 1.0])
        back_panel.translate((0, 0, -1.51))
        back_panel.compute_vertex_normals()
        shell_mesh = back_panel

    return picture_mesh, shell_mesh


def build_mesh_xml(
    matrix: np.ndarray,
    z_start_matrix: np.ndarray,
    pixel_size: float,
    layer_height: float = LAYER_HEIGHT,
    *,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    mesh_mode: str | None = None,
    art_width_mm: float | None = None,
    art_height_mm: float | None = None,
    corner_radius_mm: float = 0.0,
) -> tuple[str, str, int]:
    mode = (mesh_mode or MESH_MODE or "voxel").strip().lower()
    if mode == "region":
        try:
            from region_mesh import build_region_mesh_xml

            return build_region_mesh_xml(
                matrix,
                z_start_matrix,
                pixel_size,
                layer_height=layer_height,
                offset_x=offset_x,
                offset_y=offset_y,
                art_width_mm=art_width_mm,
                art_height_mm=art_height_mm,
                corner_radius_mm=corner_radius_mm,
            )
        except Exception as exc:
            import warnings

            warnings.warn(f"region 网格失败，回退体素: {exc}", RuntimeWarning, stacklevel=2)

    # 像素体素：先挖圆角体素 → 同高矩形合并 → 轴对齐盒子（切片快，不做整板布尔）
    if (
        float(corner_radius_mm or 0.0) > 1e-6
        and art_width_mm
        and float(art_width_mm) > 1e-6
    ):
        matrix, z_start_matrix = apply_rounded_corner_mask(
            (matrix, z_start_matrix),
            physical_width_mm=float(art_width_mm),
            corner_radius_mm=float(corner_radius_mm),
        )

    h, _w = matrix.shape
    rects = merge_voxel_rectangles(matrix, z_start_matrix, layer_height=layer_height)
    if not rects:
        return "", "", 0

    x0, x1, y0, y1, z0, z1 = _rects_to_world_mm(
        rects,
        h,
        pixel_size,
        offset_x=offset_x,
        offset_y=offset_y,
    )
    vertices, triangles = _boxes_to_3mf_xml(x0, x1, y0, y1, z0, z1)
    return vertices, triangles, len(rects) * 12


def save_as_bambu_3mf(
    output_path: str,
    layers_dict: dict,
    render_res: int,
    target_width_mm: float,
    shell_params: ShellParams | None = None,
    source_image_path: str | None = None,
    *,
    mesh_mode: str | None = None,
    target_height_mm: float | None = None,
) -> int:
    # render_res 兼容旧调用：既可是「档位 300/500」，也可是已经算好的 grid_w
    if render_res in (300, 500) or render_res < 80:
        grid_w = grid_w_for_print(target_width_mm, render_res if render_res in (300, 500) else 300)
    else:
        grid_w = int(render_res)

    resized = resize_layers(layers_dict, grid_w)
    l_w, l_y, l_m, l_c = resized.w, resized.y, resized.m, resized.c
    # 轻度中值：同层高连成片，矩形合并↑、切片更快（不改分色逻辑，只平滑层高台阶）。
    # 插画档会把它关掉（filt=1），否则 1–2 像素宽的笔画会被整条抹平。
    filt = int((layers_dict.get("auto") or {}).get("merge_filter", MESH_MERGE_FILTER))
    if filt >= 3:
        l_w = _mesh_merge_filter(l_w, size=filt)
        l_y = _mesh_merge_filter(l_y, size=filt)
        l_m = _mesh_merge_filter(l_m, size=filt)
        l_c = _mesh_merge_filter(l_c, size=filt)
    wall = shell_params.wall_thickness if shell_params else 3.0
    clearance = shell_params.fit_clearance if shell_params else 0.0
    # 画片与外壳共用圆角（None→5；显式 0→直角）
    corner = resolve_corner_radius(
        shell_params.corner_radius if shell_params else None,
        default=5.0,
    )
    # 像素体素：挖圆角后矩形合并导出（不做整板布尔）
    z_w, z_y, z_m, z_c = compute_z_stacks(l_w, l_y, l_m)
    pixel_size = target_width_mm / grid_w
    # 订单手动高优先；否则按网格比例（跟原图）
    if target_height_mm is not None and float(target_height_mm) > 1.0:
        art_h = float(target_height_mm)
        # 若层图比例与订单不一致，按订单高重采样，避免仍打出「图比例高度」
        expect_h = grid_h_for_print(target_width_mm, art_h, grid_w=grid_w)
        if abs(int(resized.grid_h) - int(expect_h)) > 0:
            size = (grid_w, expect_h)
            l_w = cv2.resize(l_w, size, interpolation=cv2.INTER_NEAREST)
            l_y = cv2.resize(l_y, size, interpolation=cv2.INTER_NEAREST)
            l_m = cv2.resize(l_m, size, interpolation=cv2.INTER_NEAREST)
            l_c = cv2.resize(l_c, size, interpolation=cv2.INTER_NEAREST)
            z_w, z_y, z_m, z_c = compute_z_stacks(l_w, l_y, l_m)
            resized = ResizedLayers(
                w=l_w, y=l_y, m=l_m, c=l_c, grid_h=expect_h, grid_w=grid_w
            )
    else:
        art_h = target_width_mm * resized.grid_h / grid_w
    offset_x, offset_y = compute_bed_offset(
        target_width_mm,
        art_h,
        wall,
        fit_clearance=clearance,
        corner_radius=corner,
    )

    layer_specs = (
        (1, "1_Cyan", l_c, z_c, 1),
        (2, "2_Magenta", l_m, z_m, 2),
        (3, "3_Yellow", l_y, z_y, 3),
        (4, "4_White", l_w, z_w, 4),
    )

    mode = mesh_mode or MESH_MODE
    color_layers: list[MeshPart] = []
    total_tris = 0
    for part_id, name, matrix, z_start, extruder in layer_specs:
        vertices, triangles, tri_count = build_mesh_xml(
            matrix,
            z_start,
            pixel_size,
            offset_x=offset_x,
            offset_y=offset_y,
            mesh_mode=mode,
            art_width_mm=target_width_mm,
            art_height_mm=art_h,
            corner_radius_mm=float(corner),
        )
        total_tris += tri_count
        if not vertices:
            continue
        color_layers.append(
            MeshPart(
                part_id=part_id,
                name=name,
                extruder=extruder,
                vertices_xml=vertices,
                triangles_xml=triangles,
            )
        )

    shell: ShellPart | None = None
    shell_tris = 0
    if shell_params and shell_params.enabled:
        max_stack = max_layer_stack_from_layers(l_w, l_y, l_m, l_c)
        shell_vertices, shell_triangles = shell_mesh_to_3mf_xml(
            target_width_mm,
            grid_w,
            resized.grid_h,
            max_stack,
            layer_height=LAYER_HEIGHT,
            fit_clearance=shell_params.fit_clearance,
            wall_thickness=shell_params.wall_thickness,
            corner_radius=corner,
            shell_depth=shell_params.shell_depth,
            offset_x=offset_x,
            offset_y=offset_y,
        )
        mod_vertices, mod_triangles = top_solid_modifier_to_3mf_xml(
            target_width_mm,
            grid_w,
            resized.grid_h,
            max_stack,
            layer_height=LAYER_HEIGHT,
            fit_clearance=shell_params.fit_clearance,
            wall_thickness=shell_params.wall_thickness,
            corner_radius=corner,
            shell_depth=shell_params.shell_depth,
            offset_x=offset_x,
            offset_y=offset_y,
        )
        if shell_vertices:
            shell_tris = shell_triangles.count("<triangle")
            shell = ShellPart(
                name="Lightbox_Shell_Box",
                extruder=5,
                vertices_xml=shell_vertices,
                triangles_xml=shell_triangles,
                modifier_vertices_xml=mod_vertices,
                modifier_triangles_xml=mod_triangles,
            )

    shell_hex = DEFAULT_SHELL_COLOR
    if shell_params:
        shell_hex = shell_params.shell_color_hex

    picture_name = os.path.splitext(os.path.basename(output_path))[0] or "FDM图片画"
    thumb = None
    thumb_src = source_image_path or ""
    if thumb_src:
        from bambu_export import make_package_thumbnail_png

        thumb = make_package_thumbnail_png(thumb_src)
    save_bambu_project_3mf(
        output_path,
        color_layers,
        shell,
        picture_name=picture_name,
        offset_x=offset_x,
        offset_y=offset_y,
        shell_color_hex=shell_hex,
        thumbnail_png=thumb,
    )
    return total_tris + shell_tris


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
LogLevel = Literal["info", "ok", "warn", "err"]


class CMYWApp:
    RESOLUTION_OPTIONS = (
        "300 — 0.4mm 喷嘴 · 标准丝滑",
        "500 — 0.2mm 喷嘴 · 精细丝滑",
    )
    RECENT_MAX = 5

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry("920x780")
        self.root.minsize(860, 720)
        self.root.configure(bg=COLORS["bg"])

        self.current_img_path: str | None = None
        self.layers_dict: dict | None = None
        self._busy = False
        self._thumb_photo: tk.PhotoImage | None = None
        self._recent_files: list[str] = []
        self._last_export_dir: str | None = None

        apply_theme(root)
        self._setup_menu()
        self._bind_shortcuts()
        self._create_widgets()
        self._set_status("就绪 — 请加载图片开始")
        self.log("软件已启动。耗材已对齐拓竹 PLA Basic CMYK，默认适配 X1 Carbon。", "ok")

    def _setup_menu(self) -> None:
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="文件", menu=file_menu)
        file_menu.add_command(label="打开图片…  Ctrl+O", command=self.load_image)
        file_menu.add_command(label="导出到桌面  Ctrl+E", command=self.run_export)
        file_menu.add_command(label="自定义导出…", command=self.run_custom_export)
        self.recent_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="最近打开", menu=self.recent_menu)
        self.recent_menu.add_command(label="（无）", state="disabled")
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.quit)

        tool_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="工具", menu=tool_menu)
        tool_menu.add_command(label="3D 预览  Ctrl+P", command=self.run_preview)
        tool_menu.add_command(label="打开上次导出目录", command=self.open_last_export_dir)

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="帮助", menu=help_menu)
        help_menu.add_command(label="快捷键说明", command=self.show_shortcuts_help)
        help_menu.add_command(label="关于", command=self.show_about)

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-o>", lambda _e: self.load_image())
        self.root.bind("<Control-e>", lambda _e: self.run_export())
        self.root.bind("<Control-p>", lambda _e: self.run_preview())

    def _create_widgets(self) -> None:
        make_header(self.root)

        body = ttk.Frame(self.root, padding=(16, 12, 16, 8))
        body.pack(fill="both", expand=True)

        # --- 左栏：源图 + 快捷信息 ---
        left = ttk.Frame(body, style="Card.TFrame", padding=16)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        ttk.Label(left, text="源图片", style="Surface.TLabel", font=FONTS["heading"]).pack(anchor="w")

        self.thumb_frame = tk.Frame(left, bg=COLORS["surface_alt"], width=200, height=200, highlightbackground=COLORS["border"], highlightthickness=1)
        self.thumb_frame.pack(pady=(10, 12))
        self.thumb_frame.pack_propagate(False)
        self.lbl_thumb = tk.Label(
            self.thumb_frame,
            text="暂无预览\n\n点击选择图片",
            bg=COLORS["surface_alt"],
            fg=COLORS["text_muted"],
            font=FONTS["small"],
            justify="center",
        )
        self.lbl_thumb.pack(expand=True, fill="both")

        self.btn_load = ttk.Button(left, text="选择图片", command=self.load_image, style="Accent.TButton")
        self.btn_load.pack(fill="x", pady=(0, 8))

        self.lbl_file = ttk.Label(left, text="尚未加载", style="MutedSurface.TLabel", wraplength=200)
        self.lbl_file.pack(anchor="w", pady=(0, 12))

        stats = ttk.Frame(left, style="Card.TFrame")
        stats.pack(fill="x")
        self.lbl_stat_res = ttk.Label(stats, text="—", style="StatValue.TLabel")
        self.lbl_stat_res.pack(anchor="w")
        ttk.Label(stats, text="源图分辨率", style="StatCaption.TLabel").pack(anchor="w", pady=(0, 8))
        self.lbl_stat_size = ttk.Label(stats, text="—", style="StatValue.TLabel")
        self.lbl_stat_size.pack(anchor="w")
        ttk.Label(stats, text="打印宽度 (mm)", style="StatCaption.TLabel").pack(anchor="w")

        # --- 右栏：参数 ---
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        print_card = ttk.LabelFrame(right, text=" 打印参数 ", style="Card.TLabelframe", padding=16)
        print_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        ttk.Label(print_card, text="打印宽度", style="Surface.TLabel").grid(row=0, column=0, sticky="w")
        width_row = ttk.Frame(print_card, style="Card.TFrame")
        width_row.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.var_width = tk.IntVar(value=120)
        ttk.Spinbox(width_row, from_=50, to=256, textvariable=self.var_width, width=8).pack(side="left")
        ttk.Label(width_row, text="mm", style="MutedSurface.TLabel").pack(side="left", padx=(6, 0))

        ttk.Label(print_card, text="像素精度", style="Surface.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.combo_res = ttk.Combobox(print_card, values=self.RESOLUTION_OPTIONS, state="readonly", width=28)
        self.combo_res.current(0)
        self.combo_res.grid(row=1, column=1, sticky="w", padx=(12, 0), pady=(10, 0))

        ttk.Label(
            print_card,
            text="盘1 建议 0.08mm 层高 · 盘2 灯箱建议 0.2mm",
            style="MutedSurface.TLabel",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))

        shell_card = ttk.LabelFrame(right, text=" 灯箱外壳 ", style="Card.TLabelframe", padding=16)
        shell_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        self.var_shell_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            shell_card,
            text="同步生成圆角灯箱（尺寸自动匹配画面）",
            variable=self.var_shell_enabled,
            command=self._toggle_shell_fields,
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))

        shell_fields = [
            ("壁厚", "var_wall", 3.0, 1.0, 8.0, "mm", 0.5),
            ("圆角", "var_corner", 5.0, 0.0, 30.0, "mm", 0.5),
            ("深度", "var_depth", 18.0, 8.0, 60.0, "mm", 0.5),
            ("间隙", "var_clearance", 0.2, 0.0, 0.5, "mm", 0.02),
        ]
        self._shell_spinboxes: list[ttk.Spinbox] = []
        for col, (label, attr, default, min_v, max_v, unit, step) in enumerate(shell_fields):
            ttk.Label(shell_card, text=label, style="Surface.TLabel").grid(row=1, column=col, sticky="w", padx=(0, 4))
            var = tk.DoubleVar(value=default)
            setattr(self, attr, var)
            sb = ttk.Spinbox(shell_card, from_=min_v, to=max_v, increment=step, textvariable=var, width=7)
            sb.grid(row=2, column=col, sticky="w", pady=(4, 0))
            self._shell_spinboxes.append(sb)
            ttk.Label(shell_card, text=unit, style="MutedSurface.TLabel").grid(row=3, column=col, sticky="w")

        color_row = ttk.Frame(shell_card, style="Card.TFrame")
        color_row.grid(row=4, column=0, columnspan=4, sticky="w", pady=(14, 0))
        self._color_row = color_row
        ttk.Label(color_row, text="外壳颜色", style="Surface.TLabel").pack(side="left")
        self.color_swatch = tk.Label(color_row, width=3, bg=BAMBU_PLA_BLACK, relief="solid", bd=1)
        self.color_swatch.pack(side="left", padx=(10, 6))
        self.var_shell_color = tk.StringVar(value=BAMBU_PLA_BLACK)
        self.var_shell_color.trace_add("write", lambda *_: self._update_color_swatch())
        ttk.Entry(color_row, textvariable=self.var_shell_color, width=10).pack(side="left")
        ttk.Button(color_row, text="选色", command=self.pick_shell_color, width=6).pack(side="left", padx=(6, 0))
        self.combo_shell_color = ttk.Combobox(
            color_row,
            values=("黑色 #000000", "白色 #FFFFFF", "深灰 #545454"),
            state="readonly",
            width=14,
        )
        self.combo_shell_color.pack(side="left", padx=(6, 0))
        self.combo_shell_color.bind("<<ComboboxSelected>>", self._on_shell_color_preset)

        action_card = ttk.Frame(right, style="Card.TFrame", padding=(0, 4))
        action_card.grid(row=2, column=0, sticky="ew")

        btn_row = ttk.Frame(action_card, style="Card.TFrame")
        btn_row.pack(fill="x")
        self.btn_preview = ttk.Button(btn_row, text="3D 预览", command=self.run_preview, state="disabled")
        self.btn_preview.pack(side="left", padx=(0, 8))
        self.btn_export = ttk.Button(
            btn_row, text="导出到桌面", command=self.run_export, state="disabled", style="Primary.TButton"
        )
        self.btn_export.pack(side="left")
        self.btn_export_custom = ttk.Button(
            btn_row, text="自定义导出…", command=self.run_custom_export, state="disabled"
        )
        self.btn_export_custom.pack(side="left", padx=(8, 0))

        prog_row = ttk.Frame(action_card, style="Card.TFrame")
        prog_row.pack(fill="x", pady=(12, 0))
        self.progress = ttk.Progressbar(prog_row, mode="indeterminate", style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", side="left", expand=True)
        self.lbl_progress = ttk.Label(prog_row, text="", style="Muted.TLabel", width=18)
        self.lbl_progress.pack(side="right", padx=(8, 0))

        log_card = ttk.LabelFrame(body, text=" 活动日志 ", style="Card.TLabelframe", padding=10)
        log_card.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(12, 0))

        log_inner = ttk.Frame(log_card, style="Card.TFrame")
        log_inner.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(log_inner)
        scroll.pack(side="right", fill="y")
        self.txt_log = tk.Text(
            log_inner,
            wrap="word",
            height=8,
            font=FONTS["mono"],
            bg=COLORS["log_bg"],
            fg=COLORS["log_info"],
            relief="flat",
            padx=8,
            pady=6,
            yscrollcommand=scroll.set,
        )
        self.txt_log.pack(fill="both", expand=True)
        scroll.config(command=self.txt_log.yview)
        for tag, color in (
            ("info", COLORS["log_info"]),
            ("ok", COLORS["log_ok"]),
            ("warn", COLORS["log_warn"]),
            ("err", COLORS["log_err"]),
            ("time", COLORS["text_muted"]),
        ):
            self.txt_log.tag_configure(tag, foreground=color)

        status_bar = ttk.Frame(self.root, style="StatusBar.TFrame", padding=(16, 6))
        status_bar.pack(fill="x", side="bottom")
        self.lbl_status = ttk.Label(status_bar, text="", style="Status.TLabel")
        self.lbl_status.pack(side="left")
        ttk.Label(status_bar, text=f"{APP_NAME} · X1 Carbon · PLA Basic CMYK", style="Status.TLabel").pack(side="right")

        body.columnconfigure(0, weight=0, minsize=232)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)

        self.var_width.trace_add("write", lambda *_: self._refresh_stats())
        self.combo_res.bind("<<ComboboxSelected>>", lambda _e: self._refresh_stats())
        self._toggle_shell_fields()
        self._update_color_swatch()

    def _toggle_shell_fields(self) -> None:
        enabled = self.var_shell_enabled.get()
        state = "normal" if enabled else "disabled"
        for sb in self._shell_spinboxes:
            sb.config(state=state)
        self.combo_shell_color.config(state="readonly" if enabled else "disabled")
        for child in self._color_row.winfo_children():
            if isinstance(child, (ttk.Entry, ttk.Button)):
                child.config(state=state)

    def _update_color_swatch(self) -> None:
        hex_color = normalize_hex_color(self.var_shell_color.get())
        try:
            self.color_swatch.config(bg=hex_color)
        except tk.TclError:
            self.color_swatch.config(bg=DEFAULT_SHELL_COLOR)

    def _refresh_stats(self) -> None:
        if self.layers_dict:
            h, w = self.layers_dict["shape"][:2]
            self.lbl_stat_res.config(text=f"{w} × {h}")
        self.lbl_stat_size.config(text=str(self.var_width.get()))

    def _set_status(self, text: str) -> None:
        self.lbl_status.config(text=text)

    def _start_busy(self, message: str) -> None:
        self._busy = True
        self._set_all_buttons("disabled")
        self.lbl_progress.config(text=message)
        self.progress.start(12)
        self._set_status(message)

    def _stop_busy(self) -> None:
        self._busy = False
        self.progress.stop()
        self.lbl_progress.config(text="")
        self._set_all_buttons("normal")
        if self.layers_dict:
            self._set_action_buttons("normal")
        self._set_status("就绪")

    def log(self, message: str, level: LogLevel = "info") -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.txt_log.insert(tk.END, f"[{stamp}] ", "time")
        self.txt_log.insert(tk.END, message + "\n", level)
        self.txt_log.see(tk.END)

    def _on_shell_color_preset(self, _event: object = None) -> None:
        preset = self.combo_shell_color.get()
        if "#" in preset:
            self.var_shell_color.set(preset.rsplit(" ", 1)[-1])

    def pick_shell_color(self) -> None:
        from tkinter import colorchooser

        initial = normalize_hex_color(self.var_shell_color.get())
        rgb = tuple(int(initial[i : i + 2], 16) for i in (1, 3, 5))
        picked = colorchooser.askcolor(color=rgb, title="选择灯箱外壳颜色")
        if picked[1]:
            self.var_shell_color.set(normalize_hex_color(picked[1]))
            self.combo_shell_color.set("")

    def get_shell_params(self) -> ShellParams:
        return ShellParams(
            enabled=self.var_shell_enabled.get(),
            wall_thickness=float(self.var_wall.get()),
            corner_radius=float(self.var_corner.get()),
            shell_depth=float(self.var_depth.get()),
            fit_clearance=float(self.var_clearance.get()),
            shell_color_hex=normalize_hex_color(self.var_shell_color.get()),
        )

    def get_resolution(self) -> int:
        return 500 if "500" in self.combo_res.get() else 300

    def _set_action_buttons(self, state: str) -> None:
        self.btn_preview.config(state=state)
        self.btn_export.config(state=state)
        self.btn_export_custom.config(state=state)

    @staticmethod
    def _desktop_dir() -> str:
        if sys.platform == "win32":
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
                )
                desktop, _ = winreg.QueryValueEx(key, "Desktop")
                path = os.path.expanduser(desktop)
                if os.path.isdir(path):
                    return path
            except OSError:
                pass
            profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
            for candidate in (
                os.path.join(profile, "Desktop"),
                os.path.join(profile, "OneDrive", "Desktop"),
                os.path.join(profile, "OneDrive", "桌面"),
                os.path.join(profile, "桌面"),
            ):
                if os.path.isdir(candidate):
                    return candidate
        return os.path.join(os.path.expanduser("~"), "Desktop")

    def _desktop_export_path(self, base_name: str) -> str:
        safe = re.sub(r'[<>:"/\\|?*]', "_", base_name).strip() or "FDM图片画"
        desktop = self._desktop_dir()
        os.makedirs(desktop, exist_ok=True)
        path = os.path.join(desktop, f"{safe}.3mf")
        if not os.path.exists(path):
            return path
        index = 1
        while True:
            candidate = os.path.join(desktop, f"{safe}_{index}.3mf")
            if not os.path.exists(candidate):
                return candidate
            index += 1

    def _set_all_buttons(self, state: str) -> None:
        self.btn_load.config(state=state)
        if state == "normal" and not self.layers_dict:
            self._set_action_buttons("disabled")
        elif state == "normal":
            self._set_action_buttons("normal")
        else:
            self._set_action_buttons("disabled")

    def _run_async(self, worker: Callable[[], None], *, busy_message: str = "处理中…") -> None:
        self._start_busy(busy_message)

        def runner() -> None:
            try:
                worker()
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda e=exc: self._on_worker_error(e))

        threading.Thread(target=runner, daemon=True).start()

    def _on_worker_error(self, exc: Exception) -> None:
        self._stop_busy()
        self.log(f"操作失败: {exc}", "err")
        messagebox.showerror("错误", str(exc))

    def _update_thumbnail(self, path: str) -> None:
        img = load_image_bgr(path)
        if img is None:
            return
        h, w = img.shape[:2]
        max_side = 196
        scale = max_side / max(w, h)
        thumb = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))))
        tmp = os.path.join(tempfile.gettempdir(), "fdm_litho_thumb.png")
        cv2.imwrite(tmp, thumb)
        self._thumb_photo = tk.PhotoImage(file=tmp)
        self.lbl_thumb.config(image=self._thumb_photo, text="")
        self.lbl_stat_res.config(text=f"{w} × {h}")

    def _add_recent(self, path: str) -> None:
        path = os.path.abspath(path)
        if path in self._recent_files:
            self._recent_files.remove(path)
        self._recent_files.insert(0, path)
        self._recent_files = self._recent_files[: self.RECENT_MAX]
        self.recent_menu.delete(0, tk.END)
        if not self._recent_files:
            self.recent_menu.add_command(label="（无）", state="disabled")
            return
        for item in self._recent_files:
            label = os.path.basename(item)
            self.recent_menu.add_command(label=label, command=lambda p=item: self.load_image_path(p))

    def load_image_path(self, path: str) -> None:
        if not os.path.isfile(path):
            messagebox.showwarning("文件不存在", path)
            return
        self.current_img_path = path
        self.lbl_file.config(text=os.path.basename(path))
        self._set_action_buttons("disabled")
        self.log(f"加载: {os.path.basename(path)}")
        self._run_async(self._process_image_worker, busy_message="解析 CMYW 分层…")

    def _process_image_worker(self) -> None:
        path = self.current_img_path
        assert path
        # 加载时按当前档位目标网格解析，与导出一致
        try:
            width = float(self.var_width.get())
        except (TypeError, ValueError, tk.TclError):
            width = 120.0
        grid_w = grid_w_for_print(width, self.get_resolution())
        result = generate_cmyw_layers(path, target_grid_w=grid_w)

        def update_ui() -> None:
            self._stop_busy()
            if result is None:
                self.log("图像解析失败，请检查文件格式。", "err")
                return
            self.layers_dict = result
            self._add_recent(path)
            self._update_thumbnail(path)
            self._refresh_stats()
            self._set_action_buttons("normal")
            shell = self.get_shell_params()
            if shell.enabled:
                self.log(
                    f"解析完成 · 打印宽度 {self.var_width.get()}mm · 外壳已同步",
                    "ok",
                )
            else:
                self.log("解析完成，可以预览或导出。", "ok")

        self.root.after(0, update_ui)

    def load_image(self) -> None:
        if self._busy:
            return
        path = filedialog.askopenfilename(
            title="选择源图片",
            filetypes=[("图片", "*.jpg *.jpeg *.png *.bmp"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.load_image_path(path)

    def run_preview(self) -> None:
        if not self.layers_dict or self._busy:
            return

        width_mm = self.var_width.get()
        res_px = self.get_resolution()
        grid_w = grid_w_for_print(float(width_mm), res_px)
        shell_params = self.get_shell_params()
        self.log(
            f"正在构建 {width_mm}mm 预览（档位 {res_px} · 网格 {grid_w} · {resolution_to_mm_per_px(res_px)}mm/px）…"
        )

        def worker() -> None:
            # 按当前尺寸重算层，保证与导出一致
            path = self.current_img_path
            layers = (
                generate_cmyw_layers(path, target_grid_w=grid_w)
                if path
                else self.layers_dict
            )
            if not layers:
                raise RuntimeError("图片无法解析")
            picture_mesh, shell_mesh = compile_preview_parts(
                layers,
                width_mm,
                grid_w,
                shell_params=shell_params,
            )
            center = picture_mesh.get_center()
            if shell_mesh is not None and len(shell_mesh.vertices) > 0:
                center = (center + shell_mesh.get_center()) / 2.0
            rotation = o3d.geometry.get_rotation_matrix_from_xyz(
                (np.radians(-22), 0.0, np.radians(5))
            )
            if len(picture_mesh.vertices) > 0:
                picture_mesh.rotate(rotation, center=center)
            if shell_mesh is not None and len(shell_mesh.vertices) > 0:
                shell_mesh.rotate(rotation, center=center)

            def show_preview() -> None:
                self._stop_busy()
                shell_note = "含灯箱" if shell_params.enabled else "仅画片"
                title = f"{APP_NAME} — {width_mm}mm · 网格{grid_w} · {shell_note}"
                self.log("预览窗口已打开（可拖动旋转，主界面继续操作）。", "ok")

                def on_close() -> None:
                    self.root.after(0, lambda: self.log("预览已关闭。", "info"))

                open_mesh_preview(
                    picture_mesh=picture_mesh,
                    shell_mesh=shell_mesh,
                    title=title,
                    on_close=on_close,
                )

            self.root.after(0, show_preview)

        self._run_async(worker, busy_message="构建 3D 预览…")

    def run_export(self) -> None:
        self._export_to_path(custom_path=False)

    def run_custom_export(self) -> None:
        self._export_to_path(custom_path=True)

    def _export_to_path(self, *, custom_path: bool) -> None:
        if not self.layers_dict or self._busy:
            return

        if custom_path:
            initial_dir = self._last_export_dir or self._desktop_dir()
            initial_name = ""
            if self.current_img_path:
                initial_name = os.path.splitext(os.path.basename(self.current_img_path))[0] + ".3mf"
            save_path = filedialog.asksaveasfilename(
                title="保存 Bambu Studio 3MF",
                initialdir=initial_dir,
                initialfile=initial_name,
                defaultextension=".3mf",
                filetypes=[("Bambu 3MF", "*.3mf")],
            )
            if not save_path:
                return
        else:
            base_name = "FDM图片画"
            if self.current_img_path:
                base_name = os.path.splitext(os.path.basename(self.current_img_path))[0]
            save_path = self._desktop_export_path(base_name)

        width_mm = self.var_width.get()
        res_px = self.get_resolution()
        grid_w = grid_w_for_print(float(width_mm), res_px)
        shell_params = self.get_shell_params()
        self.log(f"正在导出: {save_path}（网格 {grid_w}）", "info")

        def worker() -> None:
            try:
                path = self.current_img_path
                layers = (
                    generate_cmyw_layers(path, target_grid_w=grid_w)
                    if path
                    else self.layers_dict
                )
                if not layers:
                    raise RuntimeError("图片无法解析")
                tri_count = save_as_bambu_3mf(
                    save_path,
                    layers,
                    grid_w,
                    width_mm,
                    shell_params=shell_params,
                    source_image_path=self.current_img_path,
                )
            except Exception as exc:
                self.root.after(0, lambda e=exc: self._finish_export(False, save_path, e, 0))
                return
            self.root.after(0, lambda: self._finish_export(True, save_path, None, tri_count))

        self._run_async(worker, busy_message="打包 3MF…")

    def _finish_export(self, success: bool, save_path: str, error: Exception | None, tri_count: int) -> None:
        self._stop_busy()
        if success:
            self._last_export_dir = os.path.dirname(os.path.abspath(save_path))
            slots = list(FILAMENT_SLOTS[:4])
            shell_hex = normalize_hex_color(
                self.var_shell_color.get() if self.var_shell_enabled.get() else DEFAULT_SHELL_COLOR
            )
            slots.append({**FILAMENT_SLOTS[4], "hex": shell_hex})
            tri_hint = f"{tri_count:,} 三角面" if tri_count else "已优化"
            self.log(f"导出成功 → {save_path}", "ok")
            self.log(f"分盘: 四色画片 / 灯箱外壳 · 网格: {tri_hint}", "info")
            self.log("提示: 盘2 为圆角深盒。", "warn")
        else:
            self.log(f"导出失败: {error}", "err")
            messagebox.showerror("导出失败", str(error))

    def _open_folder(self, folder: str | None) -> None:
        if not folder or not os.path.isdir(folder):
            return
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", folder], check=False)
        else:
            subprocess.run(["xdg-open", folder], check=False)

    def open_last_export_dir(self) -> None:
        if self._last_export_dir:
            self._open_folder(self._last_export_dir)
        else:
            messagebox.showinfo("提示", "尚未导出过文件。")

    def show_shortcuts_help(self) -> None:
        messagebox.showinfo(
            "快捷键",
            "Ctrl+O  打开图片\nCtrl+P  3D 预览\nCtrl+E  导出到桌面\n\n"
            "「自定义导出…」可手动选择保存路径。\n"
            "预览窗口：鼠标左键旋转 · 滚轮缩放 · 右键平移",
        )

    def show_about(self) -> None:
        messagebox.showinfo(
            "关于",
            f"{APP_NAME} v{APP_VERSION}\n\n"
            "四色 CMYW 透光画 + 圆角灯箱外壳\n"
            "一键导出 Bambu Studio 分盘 3MF\n\n"
            "打印机: Bambu Lab X1 Carbon\n"
            "耗材: PLA Basic CMYK 套装",
        )


if __name__ == "__main__":
    root = tk.Tk()
    app = CMYWApp(root)
    threading.Thread(target=warmup_open3d, daemon=True).start()
    root.mainloop()
