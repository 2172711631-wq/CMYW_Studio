"""非阻塞 3D 预览窗口。"""

from __future__ import annotations

import threading
from collections.abc import Callable

import numpy as np
import open3d as o3d

_warmup_lock = threading.Lock()
_warmup_done = False


def warmup_open3d() -> None:
    """后台预热 Open3D 渲染上下文，缩短首次预览等待。"""
    global _warmup_done
    with _warmup_lock:
        if _warmup_done:
            return
        try:
            vis = o3d.visualization.Visualizer()
            vis.create_window(window_name="warmup", width=64, height=64, visible=False)
            vis.destroy_window()
        except Exception:  # noqa: BLE001
            pass
        _warmup_done = True


def open_mesh_preview(
    mesh: o3d.geometry.TriangleMesh | None = None,
    *,
    picture_mesh: o3d.geometry.TriangleMesh | None = None,
    shell_mesh: o3d.geometry.TriangleMesh | None = None,
    title: str = "3D 预览",
    on_close: Callable[[], None] | None = None,
) -> None:
    """在独立线程打开 Open3D 预览；画片与外壳分几何体添加，避免被遮挡。"""

    def runner() -> None:
        try:
            warmup_open3d()
            vis = o3d.visualization.Visualizer()
            vis.create_window(window_name=title, width=1120, height=840, visible=True)

            parts: list[o3d.geometry.TriangleMesh] = []
            if mesh is not None and len(mesh.vertices) > 0:
                parts.append(mesh)
            else:
                if shell_mesh is not None and len(shell_mesh.vertices) > 0:
                    parts.append(shell_mesh)
                if picture_mesh is not None and len(picture_mesh.vertices) > 0:
                    parts.append(picture_mesh)

            if not parts:
                return

            lookat = parts[-1].get_center()
            for part in parts:
                if not part.has_vertex_normals():
                    part.compute_vertex_normals()
                vis.add_geometry(part, reset_bounding_box=False)
            vis.reset_view_point(True)

            opt = vis.get_render_option()
            opt.background_color = np.array([0.12, 0.13, 0.15])
            opt.mesh_show_back_face = True
            opt.mesh_show_wireframe = False
            opt.light_on = True
            opt.point_size = 2.0
            if any(p.has_vertex_colors() for p in parts):
                opt.mesh_color_option = o3d.visualization.MeshColorOption.Color

            ctr = vis.get_view_control()
            ctr.set_zoom(0.78)
            # 从正面偏上观察，优先看到透光画顶面
            ctr.set_front([0.15, -0.35, -0.92])
            ctr.set_lookat(lookat)
            ctr.set_up([0.0, 0.0, 1.0])

            vis.run()
            vis.destroy_window()
        finally:
            if on_close:
                on_close()

    threading.Thread(target=runner, daemon=True).start()
