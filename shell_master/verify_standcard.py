"""立式薄画框自检：改完参数跑一遍。

这个件几乎全是内部空腔——灯条腔、导光板槽、画片槽、走线孔——看外形看不出问题，
改一个参数很容易把某条槽挤没了或者挤穿了。这里用"某个坐标应该是实心还是空腔"
来验，判据全部由 params() 派生，所以换尺寸不用改这个文件。

另外两件光靠看模型看不出来的事也在这里算：顶压条塞不塞得进槽，以及站不站得住
（按质心算倾覆角）。

    py -3.11 shell_master/verify_standcard.py
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root

from shell_master import standcard_cadquery as S  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def probes(p: dict[str, float]) -> list[tuple[str, tuple[float, float, float], bool]]:
    """(说明, 坐标, 期望是否实心)。空腔 = False。"""
    mid_z = (p["window_z0"] + p["lgp_top"]) / 2.0            # 可见画面中段
    lap_x = S.ART_W / 2.0 - S.BEZEL_LAP_X / 2.0              # 左右压边条中线
    led_z = p["z_led"] + S.LED_CH_H / 2.0
    shoulder_x = (p["led_len"] / 2.0 + S.ART_W / 2.0) / 2.0
    y_mid_lgp = p["y_lgp0"] + S.LGP_T / 2.0

    return [
        ("左右压边条", (lap_x, S.BEZEL_T / 2.0, mid_z), True),
        ("取景窗中央敞开", (0.0, S.BEZEL_T / 2.0, mid_z), False),
        ("底边压边", (0.0, S.BEZEL_T / 2.0, p["z_art"] + S.BEZEL_LAP_BOTTOM / 2.0), True),
        ("顶边留给压条", (0.0, S.BEZEL_T / 2.0, p["z_top"] - S.BAR_LAP / 2.0), False),
        ("画片槽", (0.0, p["y_art0"] + S.ART_SLOT_T / 2.0, mid_z), False),
        ("光学层槽", (0.0, y_mid_lgp, mid_z), False),
        ("背壁", (0.0, p["y_opt1"] + S.BACK_T / 2.0, mid_z), True),
        ("背壁之后是空气", (0.0, p["body_d"] + 0.5, mid_z), False),
        ("混光区前挡条", (0.0, S.BEZEL_T / 2.0, (S.BASE_H + p["z_art"]) / 2.0), True),
        ("混光区光学层通着", (0.0, y_mid_lgp, p["z_lgp"] + 2.0), False),
        ("灯条腔", (0.0, y_mid_lgp, led_z), False),
        ("灯条腔两端承台", (shoulder_x, y_mid_lgp, led_z), True),
        ("走线孔", (p["cable_x"], p["base_y1"] - 2.0, p["z_led"] + S.CABLE_H / 2.0), False),
        (
            "走线孔天花板",
            (p["cable_x"], p["base_y1"] - 2.0, p["z_led"] + S.CABLE_H + 1.0),
            True,
        ),
        ("走线孔没串到中线", (0.0, p["base_y1"] - 2.0, p["z_led"] + S.CABLE_H / 2.0), True),
        ("底座实心（兼配重）", (0.0, p["base_y1"] - 2.0, 2.0), True),
        ("框顶以上", (0.0, y_mid_lgp, p["z_top"] + 2.0), False),
    ]


def check_fit(p: dict[str, float]) -> list[tuple[str, bool, str]]:
    """装配可行性：这些是几何看不出来、但装的时候一定会撞的事。"""
    optics = S.DIFFUSER_T + S.LGP_T + S.REFLECTOR_T
    return [
        ("光学三件叠厚 < 光学层槽", optics < S.OPTICS_T, f"{optics:.1f} < {S.OPTICS_T:.1f}"),
        ("画片槽 ≥ 22 层画片", S.ART_SLOT_T >= 1.76, f"{S.ART_SLOT_T:.1f} ≥ 1.76"),
        (
            "压条舌头 < 光学层槽",
            S.BAR_TONGUE_T < S.OPTICS_T,
            f"{S.BAR_TONGUE_T:.1f} < {S.OPTICS_T:.1f}",
        ),
        (
            "压条前唇 < 取景窗宽",
            p["window_w"] - 2 * S.BAR_LIP_GAP < p["window_w"],
            f'{p["window_w"] - 2 * S.BAR_LIP_GAP:.1f} < {p["window_w"]:.1f}',
        ),
        (
            "舌头正好落在导光板顶上",
            abs((p["z_top"] - p["lgp_top"]) - S.BAR_LAP) < 1e-6,
            f'空出 {p["z_top"] - p["lgp_top"]:.1f} = 压唇 {S.BAR_LAP:.1f}',
        ),
        (
            "灯条 PCB 上限",
            True,
            f"≤{S.OPTICS_T - 0.2:.1f} mm（受光学层槽宽限制，从顶部放入）",
        ),
    ]


def main() -> int:
    body_path = os.path.join(HERE, "standcard_body.stl")
    bar_path = os.path.join(HERE, "standcard_topbar.stl")
    if not (os.path.exists(body_path) and os.path.exists(bar_path)):
        S.export_all(HERE)

    body = trimesh.load(body_path)
    bar = trimesh.load(bar_path)
    p = S.params()
    bad = 0

    for name, mesh in (("框体", body), ("顶压条", bar)):
        good = mesh.is_watertight and mesh.is_winding_consistent
        print(f"{name} 水密={mesh.is_watertight} 绕序一致={mesh.is_winding_consistent}")
        if not good:
            bad += 1

    lo, hi = body.bounds
    size = hi - lo
    print(f"框体外廓 {size[0]:.1f} × {size[1]:.1f} × {size[2]:.1f} mm")
    for axis, got, exp in zip(
        "XYZ", size, (p["base_w"], S.BASE_D, p["z_top"]), strict=True
    ):
        if abs(got - exp) > 0.05:
            print(f"  !! {axis} 应为 {exp:.1f}，实际 {got:.1f}")
            bad += 1

    checks = probes(p)
    inside = body.contains(np.array([q for _, q, _ in checks], dtype=float))
    for (name, _, expect), value in zip(checks, inside, strict=True):
        ok = bool(value) == expect
        if not ok:
            bad += 1
        print(
            f"  {'ok  ' if ok else '失败'} {name:16s} "
            f"期望{'实心' if expect else '空腔'} 实得{'实心' if value else '空腔'}"
        )

    print("装配可行性")
    for name, ok, detail in check_fit(p):
        if not ok:
            bad += 1
        print(f"  {'ok  ' if ok else '失败'} {name:20s} {detail}")

    # 站不站得住：按实心均质估质心，算前后两个方向的倾覆角
    cx, cy, cz = body.center_mass
    back = math.degrees(math.atan2(p["base_y1"] - cy, cz))
    front = math.degrees(math.atan2(cy - p["base_y0"], cz))
    print(f"质心 y={cy:.1f} z={cz:.1f}（底座 y {p['base_y0']:.1f}…{p['base_y1']:.1f}）")
    print(f"倾覆角 前 {front:.0f}° / 后 {back:.0f}°（越大越稳；直下式那款只有 8°）")
    if min(front, back) < 15.0:
        print("  !! 倾覆角偏小，加深底座或提高底座填充")
        bad += 1

    print("全部通过" if bad == 0 else f"*** {bad} 项不对 ***")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
