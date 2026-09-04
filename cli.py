#!/usr/bin/env python3
"""CMYW Studio 命令行接口 / Command-line interface.

把一张图片转成可打印的四色透光 3MF，无需打开图形界面。
Convert a photo into a printable 4-colour backlit 3MF without opening the GUI.

例 / Examples:
    python cli.py photo.jpg
    python cli.py photo.jpg -o lightbox.3mf --width 135
    python cli.py photo.jpg --width 160 --height 120 --shell-color "#FFFFFF"
    python cli.py photo.jpg --no-shell --mm-per-px 0.25
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Windows 旧控制台默认 cp936/cp1252，中英混排会变乱码；统一改 UTF-8 输出
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

# mm/px 必须在导入 main 之前设置：main 在模块加载时读取该环境变量
_PRESET_MM_PER_PX = None
for _i, _a in enumerate(sys.argv):
    if _a == "--mm-per-px" and _i + 1 < len(sys.argv):
        _PRESET_MM_PER_PX = sys.argv[_i + 1]
    elif _a.startswith("--mm-per-px="):
        _PRESET_MM_PER_PX = _a.split("=", 1)[1]
if _PRESET_MM_PER_PX:
    os.environ["FDM_MM_PER_PX"] = _PRESET_MM_PER_PX


def _positive(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError(f"必须为正数 / must be positive: {value}")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cmyw",
        description="CMYW Studio — 彩色透光画 3MF 生成器 / colour lithophane 3MF generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("image", help="输入图片 / input image (jpg, png, webp, bmp)")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="输出 3MF 路径 / output 3MF path (默认: 与输入同名 / defaults to input name)",
    )

    size = parser.add_argument_group("尺寸 / size")
    size.add_argument(
        "--width", type=_positive, default=135.0, help="成品宽度 mm / print width in mm (默认 135)"
    )
    size.add_argument(
        "--height",
        type=_positive,
        default=None,
        help="成品高度 mm / print height in mm (默认按原图比例 / defaults to image aspect)",
    )
    size.add_argument(
        "--mm-per-px",
        type=_positive,
        default=None,
        help="网格密度 mm/像素 / grid density (默认 0.20；越小越清晰但面数暴涨)",
    )

    shell = parser.add_argument_group("灯箱外壳 / lightbox shell")
    shell.add_argument(
        "--no-shell",
        action="store_true",
        help="只导出画片，不生成外壳 / picture only, skip the shell",
    )
    shell.add_argument("--wall", type=_positive, default=3.0, help="壁厚 mm / wall thickness (默认 3.0)")
    shell.add_argument(
        "--corner", type=float, default=5.0, help="圆角半径 mm / corner radius (默认 5.0，0=直角)"
    )
    shell.add_argument("--depth", type=_positive, default=18.0, help="外壳深度 mm / shell depth (默认 18.0)")
    shell.add_argument(
        "--clearance", type=float, default=0.2, help="装配间隙 mm / fit clearance (默认 0.2)"
    )
    shell.add_argument(
        "--shell-color",
        default="#000000",
        help="外壳颜色 hex / shell colour hex (默认 #000000)",
    )

    tuning = parser.add_argument_group("分色 / colour separation")
    tuning.add_argument(
        "--profile",
        choices=("v1", "v2"),
        default="v2",
        help="分色档案 / colour profile: v2=CMY提取+自适应UCR (默认), v1=旧通道直映射",
    )
    tuning.add_argument(
        "--no-dither", action="store_true", help="关闭有序抖动 / disable ordered dithering"
    )
    tuning.add_argument(
        "--mesh-mode",
        choices=("voxel", "region"),
        default="voxel",
        help="网格模式 / mesh mode: voxel=像素方格 (默认，稳), region=色块轮廓 (实验性)",
    )

    parser.add_argument("-q", "--quiet", action="store_true", help="只输出结果路径 / print result path only")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    image_path = Path(args.image).expanduser()
    if not image_path.is_file():
        print(f"错误 / error: 找不到图片 / image not found: {image_path}", file=sys.stderr)
        return 2

    output = Path(args.output).expanduser() if args.output else image_path.with_suffix(".3mf")
    output.parent.mkdir(parents=True, exist_ok=True)

    def say(message: str) -> None:
        if not args.quiet:
            print(message, flush=True)

    say("正在加载引擎 / loading engine ...")
    try:
        from main import (
            ShellParams,
            auto_mm_per_px,
            generate_cmyw_layers,
            grid_h_for_print,
            save_as_bambu_3mf,
        )
    except ImportError as exc:
        print(f"错误 / error: 依赖未装齐 / missing dependency: {exc}", file=sys.stderr)
        print("请运行 / run: pip install -r requirements.txt", file=sys.stderr)
        return 3

    width = float(args.width)
    height = float(args.height) if args.height else None
    # 先看一眼图再定网格密度：插画靠细线吃饭，格子要密；照片标准密度就够。
    mpp = auto_mm_per_px(str(image_path))
    grid_w = int(max(80, min(1600, round(width / mpp))))
    grid_h = grid_h_for_print(width, height, grid_w=grid_w) if height else None

    say(
        f"分色中 / separating colours ... "
        f"(网格 / grid {grid_w}×{grid_h or 'auto'}, {mpp:.2f} mm/px)"
    )
    started = time.perf_counter()
    layers = generate_cmyw_layers(
        str(image_path),
        target_grid_w=grid_w,
        target_grid_h=grid_h,
        dither=not args.no_dither,
        color_profile=args.profile,
    )
    if not layers:
        print(f"错误 / error: 无法解析图片 / cannot decode image: {image_path}", file=sys.stderr)
        return 4

    shell_params = ShellParams(
        enabled=not args.no_shell,
        wall_thickness=float(args.wall),
        corner_radius=float(args.corner),
        shell_depth=float(args.depth),
        fit_clearance=float(args.clearance),
        shell_color_hex=args.shell_color,
    )

    say("生成网格与 3MF / building mesh and 3MF ...")
    try:
        triangles = save_as_bambu_3mf(
            str(output),
            layers,
            int(grid_w),
            width,
            shell_params=shell_params,
            source_image_path=str(image_path),
            mesh_mode=args.mesh_mode,
            target_height_mm=height,
        )
    except Exception as exc:  # noqa: BLE001 - CLI 边界：任何失败都要给出可读信息
        print(f"错误 / error: 导出失败 / export failed: {exc}", file=sys.stderr)
        return 5

    elapsed = time.perf_counter() - started
    size_mb = output.stat().st_size / (1024 * 1024) if output.is_file() else 0.0

    if args.quiet:
        print(str(output))
    else:
        stats = layers.get("stats") or {}
        print()
        print(f"  完成 / done      {output}")
        print(f"  三角面 / faces   {triangles:,}")
        print(f"  文件 / size      {size_mb:.1f} MB")
        print(f"  耗时 / elapsed   {elapsed:.1f}s")
        if stats:
            covered = ", ".join(
                f"{key} {stats[key]['nonzero_pct']:.0f}%" for key in ("C", "M", "Y") if key in stats
            )
            print(f"  用色 / coverage  {covered}")
        print()
        print("  用 Bambu Studio 打开，1-4 号槽装青/品红/黄/白 PLA。")
        print("  Open in Bambu Studio; load Cyan/Magenta/Yellow/White PLA in slots 1-4.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
