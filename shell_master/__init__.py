"""外壳母本：UG 表达式约定 + CadQuery 运行时生成。"""

from shell_master.shell_cadquery import (
    build_shell_from_product_params,
    build_shell_trimesh,
    clamp_params,
    compute_xy_bounds,
    export_shell_stl,
    load_param_sheet,
)

__all__ = [
    "build_shell_from_product_params",
    "build_shell_trimesh",
    "clamp_params",
    "compute_xy_bounds",
    "export_shell_stl",
    "load_param_sheet",
]
