import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import cv2
import numpy as np
import open3d as o3d
import os
import zipfile
import threading


# ==================== 1. 核心算法层 ====================
def generate_cmyw_layers(image_path, min_white_layers=4, max_white_layers=16):
    try:
        img_array = np.fromfile(image_path, dtype=np.uint8)
        img_bgr = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    except Exception:
        return None

    if img_bgr is None: return None

    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    img_rgb = np.clip(img_rgb, 0.005, 1.0)

    E_R_raw = -np.log(img_rgb[:, :, 0])
    E_G_raw = -np.log(img_rgb[:, :, 1])
    E_B_raw = -np.log(img_rgb[:, :, 2])

    d_W, d_C, d_M, d_Y = 0.11, 0.62, 0.54, 0.72
    n_W = np.full(E_R_raw.shape, min_white_layers, dtype=np.int32)

    gamma_exponent = 0.75
    linear_coefficient = 1.65

    E_R = (E_R_raw ** gamma_exponent) * linear_coefficient
    E_G = (E_G_raw ** gamma_exponent) * linear_coefficient
    E_B = (E_B_raw ** gamma_exponent) * linear_coefficient

    n_C = np.clip(np.round((E_R - d_W * n_W) / d_C), 0, 6).astype(np.int32)
    n_M = np.clip(np.round((E_G - d_W * n_W) / d_M), 0, 4).astype(np.int32)
    n_Y = np.clip(np.round((E_B - d_W * n_W) / d_Y), 0, 6).astype(np.int32)

    return {"C": n_C, "M": n_M, "Y": n_Y, "W": n_W, "shape": img_bgr.shape}


# ==================== 2. 1:1 真实物理 3D 编译器 ====================
def compile_studio_mesh(layers_dict, physical_width_mm, grid_w, brightness_ratio=1.6):
    h_raw, w_raw = layers_dict["W"].shape
    grid_h = int(h_raw * (grid_w / w_raw))

    L_W = cv2.resize(layers_dict["W"], (grid_w, grid_h), interpolation=cv2.INTER_NEAREST)
    L_Y = cv2.resize(layers_dict["Y"], (grid_w, grid_h), interpolation=cv2.INTER_NEAREST)
    L_M = cv2.resize(layers_dict["M"], (grid_w, grid_h), interpolation=cv2.INTER_NEAREST)
    L_C = cv2.resize(layers_dict["C"], (grid_w, grid_h), interpolation=cv2.INTER_NEAREST)

    layer_height = 0.08

    pixel_size = physical_width_mm / grid_w

    c_white = np.array([0.95, 0.95, 0.93])
    c_yellow = np.array([0.90, 0.78, 0.05])
    c_magenta = np.array([0.83, 0.06, 0.38])
    c_cyan = np.array([0.03, 0.58, 0.78])

    d_W, d_C, d_M, d_Y = 0.11, 0.62, 0.54, 0.72
    E_R = d_C * L_C + d_W * L_W + 0.04 * L_M
    E_G = d_M * L_M + d_W * L_W + 0.02 * L_Y
    E_B = d_Y * L_Y + d_W * L_W + 0.03 * L_C
    sim_rgb = np.stack([np.exp(-E_R), np.exp(-E_G), np.exp(-E_B)], axis=-1)
    sim_rgb = (sim_rgb - sim_rgb.min()) / (sim_rgb.max() - sim_rgb.min() + 1e-5)
    transmitted_colors = np.clip(sim_rgb * brightness_ratio, 0.0, 1.0)

    z_W = np.zeros_like(L_W)
    z_Y = L_W
    z_M = L_W + L_Y
    z_C = L_W + L_Y + L_M

    def build_layer_block(L_layer, Z_start, filament_color, top_override_mask):
        mask = L_layer > 0
        if not np.any(mask): return None

        y_idx, x_idx = np.where(mask)
        layers = L_layer[mask]
        z_start = Z_start[mask]
        total_pixels = len(layers)

        x0, x1 = x_idx * pixel_size, (x_idx + 1) * pixel_size
        y0, y1 = (grid_h - 1 - y_idx) * pixel_size, (grid_h - y_idx) * pixel_size
        z0, z1 = z_start * layer_height, (z_start + layers) * layer_height

        verts = np.zeros((total_pixels, 8, 3), dtype=np.float32)
        verts[:, 0, :] = np.stack([x0, y0, z0], axis=-1);
        verts[:, 1, :] = np.stack([x1, y0, z0], axis=-1)
        verts[:, 2, :] = np.stack([x1, y1, z0], axis=-1);
        verts[:, 3, :] = np.stack([x0, y1, z0], axis=-1)
        verts[:, 4, :] = np.stack([x0, y0, z1], axis=-1);
        verts[:, 5, :] = np.stack([x1, y0, z1], axis=-1)
        verts[:, 6, :] = np.stack([x1, y1, z1], axis=-1);
        verts[:, 7, :] = np.stack([x0, y1, z1], axis=-1)
        vertices_all = verts.reshape(-1, 3)

        colors_cube = np.zeros((total_pixels, 8, 3), dtype=np.float32)
        colors_cube[:, :, :] = filament_color[np.newaxis, np.newaxis, :]
        colors_cube[:, 0:4, :] *= 0.65

        is_top_exposed = top_override_mask[mask] == 1
        if np.any(is_top_exposed):
            p_colors = transmitted_colors[mask]
            colors_cube[is_top_exposed, 4:8, :] = p_colors[is_top_exposed, np.newaxis, :]

        colors_all = colors_cube.reshape(-1, 3)

        local_tris = np.array([
            [0, 1, 2], [0, 2, 3], [4, 6, 5], [4, 7, 6], [0, 4, 5], [0, 5, 1],
            [1, 5, 6], [1, 6, 2], [2, 6, 7], [2, 7, 3], [3, 7, 4], [3, 4, 0]
        ], dtype=np.int32)
        triangles_all = (local_tris[np.newaxis, :, :] + np.arange(0, total_pixels * 8, 8, dtype=np.int32)[
            :, np.newaxis, np.newaxis]).reshape(-1, 3)

        mesh = o3d.geometry.TriangleMesh()
        mesh.vertices = o3d.utility.Vector3dVector(vertices_all.astype(np.float64))
        mesh.triangles = o3d.utility.Vector3iVector(triangles_all.astype(np.int32))
        mesh.vertex_colors = o3d.utility.Vector3dVector(colors_all.astype(np.float64))
        mesh.compute_vertex_normals()
        return mesh

    top_W = np.where((L_Y == 0) & (L_M == 0) & (L_C == 0), 1, 0)
    top_Y = np.where((L_M == 0) & (L_C == 0), 1, 0)
    top_M = np.where((L_C == 0), 1, 0)
    top_C = np.ones_like(L_C)

    final_studio_mesh = o3d.geometry.TriangleMesh()

    mW = build_layer_block(L_W, z_W, c_white, top_W)
    mY = build_layer_block(L_Y, z_Y, c_yellow, top_Y)
    mM = build_layer_block(L_M, z_M, c_magenta, top_M)
    mC = build_layer_block(L_C, z_C, c_cyan, top_C)

    for m in [mW, mY, mM, mC]:
        if m is not None: final_studio_mesh += m

    # 创建物理尺寸的背板，厚度 1.5mm，放置在模型后方模拟灯箱底壳
    max_x, max_y = physical_width_mm, physical_width_mm * (grid_h / grid_w)
    back_panel = o3d.geometry.TriangleMesh.create_box(width=max_x, height=max_y, depth=1.5)
    back_panel.paint_uniform_color([1.0, 1.0, 1.0])
    back_panel.translate((0, 0, -1.51))
    back_panel.compute_vertex_normals()

    final_studio_mesh += back_panel
    return final_studio_mesh


# ==================== 3. 3MF 工业打包导出引擎 ====================
def build_mesh_xml(matrix, z_start_matrix, layer_height=0.08, pixel_size=0.8):
    vertices, triangles = [], []
    v_idx = 0
    h, w = matrix.shape
    for y in range(h):
        for x in range(w):
            layers = matrix[y, x]
            if layers <= 0: continue

            x0, x1 = x * pixel_size, (x + 1) * pixel_size
            y0, y1 = (h - y - 1) * pixel_size, (h - y) * pixel_size
            z0 = z_start_matrix[y, x] * layer_height
            z1 = z0 + (layers * layer_height)

            vertices.append(f'<vertex x="{x0:.3f}" y="{y0:.3f}" z="{z0:.3f}"/>')
            vertices.append(f'<vertex x="{x1:.3f}" y="{y0:.3f}" z="{z0:.3f}"/>')
            vertices.append(f'<vertex x="{x1:.3f}" y="{y1:.3f}" z="{z0:.3f}"/>')
            vertices.append(f'<vertex x="{x0:.3f}" y="{y1:.3f}" z="{z0:.3f}"/>')
            vertices.append(f'<vertex x="{x0:.3f}" y="{y0:.3f}" z="{z1:.3f}"/>')
            vertices.append(f'<vertex x="{x1:.3f}" y="{y0:.3f}" z="{z1:.3f}"/>')
            vertices.append(f'<vertex x="{x1:.3f}" y="{y1:.3f}" z="{z1:.3f}"/>')
            vertices.append(f'<vertex x="{x0:.3f}" y="{y1:.3f}" z="{z1:.3f}"/>')

            t = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6), (0, 4, 5), (0, 5, 1), (1, 5, 6), (1, 6, 2), (2, 6, 7),
                 (2, 7, 3), (3, 7, 4), (3, 4, 0)]
            for tri in t: triangles.append(
                f'<triangle v1="{v_idx + tri[0]}" v2="{v_idx + tri[1]}" v3="{v_idx + tri[2]}"/>')
            v_idx += 8
    return "".join(vertices), "".join(triangles)


def save_as_bambu_3mf(output_path, layers_dict, render_res, target_width_mm):
    h_raw, w_raw = layers_dict["W"].shape
    target_height = int(h_raw * (render_res / w_raw))

    L_W = cv2.resize(layers_dict["W"], (render_res, target_height), interpolation=cv2.INTER_NEAREST)
    L_Y = cv2.resize(layers_dict["Y"], (render_res, target_height), interpolation=cv2.INTER_NEAREST)
    L_M = cv2.resize(layers_dict["M"], (render_res, target_height), interpolation=cv2.INTER_NEAREST)
    L_C = cv2.resize(layers_dict["C"], (render_res, target_height), interpolation=cv2.INTER_NEAREST)

    z_W = np.zeros_like(L_W)
    z_Y = L_W
    z_M = L_W + L_Y
    z_C = L_W + L_Y + L_M

    pixel_size = target_width_mm / render_res

    w_v, w_t = build_mesh_xml(L_W, z_W, pixel_size=pixel_size)
    y_v, y_t = build_mesh_xml(L_Y, z_Y, pixel_size=pixel_size)
    m_v, m_t = build_mesh_xml(L_M, z_M, pixel_size=pixel_size)
    c_v, c_t = build_mesh_xml(L_C, z_C, pixel_size=pixel_size)

    model_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <resources>
    <object id="1" name="1_Cyan" type="model"><mesh><vertices>{c_v}</vertices><triangles>{c_t}</triangles></mesh></object>
    <object id="2" name="2_Magenta" type="model"><mesh><vertices>{m_v}</vertices><triangles>{m_t}</triangles></mesh></object>
    <object id="3" name="3_Yellow" type="model"><mesh><vertices>{y_v}</vertices><triangles>{y_t}</triangles></mesh></object>
    <object id="4" name="4_White" type="model"><mesh><vertices>{w_v}</vertices><triangles>{w_t}</triangles></mesh></object>
  </resources>
  <build><item objectid="1"/><item objectid="2"/><item objectid="3"/><item objectid="4"/></build>
</model>"""

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml",
                    """<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>""")
        zf.writestr("_rels/.rels",
                    """<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>""")
        zf.writestr("3D/3dmodel.model", model_xml)


# ==================== 4. 工作台界面 (Tkinter) ====================
class CMYWApp:
    def __init__(self, root):
        self.root = root
        self.root.title("超级FDM打印图片生成器")
        self.root.geometry("500x600")
        self.root.resizable(False, False)

        # 内部状态
        self.current_img_path = None
        self.layers_dict = None

        # 设置现代化主题
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")

        self.create_widgets()

    def create_widgets(self):
        # --- 步骤 1：图像载入 ---
        frame1 = ttk.LabelFrame(self.root, text=" 步骤 1：载入源图片 ", padding=15)
        frame1.pack(fill="x", padx=20, pady=10)

        self.btn_load = ttk.Button(frame1, text="选择电脑图片...", command=self.load_image)
        self.btn_load.pack(side="left")

        self.lbl_file = ttk.Label(frame1, text="状态: 尚未导入任何图片", foreground="gray")
        self.lbl_file.pack(side="left", padx=10)

        # --- 步骤 2：物理参数设置 ---
        frame2 = ttk.LabelFrame(self.root, text=" 步骤 2：物理打印参数设置 ", padding=15)
        frame2.pack(fill="x", padx=20, pady=10)

        ttk.Label(frame2, text="打印尺寸 (毫米 mm):").grid(row=0, column=0, sticky="w", pady=5)
        self.var_width = tk.IntVar(value=120)
        spin_width = ttk.Spinbox(frame2, from_=50, to=256, textvariable=self.var_width, width=10)
        spin_width.grid(row=0, column=1, sticky="w", padx=10)

        ttk.Label(frame2, text="切片分辨率 (像素 Px):").grid(row=1, column=0, sticky="w", pady=5)
        self.combo_res = ttk.Combobox(frame2, values=["300 (适配0.4喷嘴标准)", "500 (适配0.2喷嘴极限)"],
                                      state="readonly", width=22)
        self.combo_res.current(0)
        self.combo_res.grid(row=1, column=1, sticky="w", padx=10)

        # --- 步骤 3：核心操作 ---
        frame3 = ttk.Frame(self.root)
        frame3.pack(fill="x", padx=20, pady=10)

        self.btn_preview = ttk.Button(frame3, text="1:1 打印实物预览图", command=self.run_preview, state="disabled")
        self.btn_preview.pack(fill="x", ipady=5, pady=5)

        self.btn_export = ttk.Button(frame3, text="保存拓竹多色 3MF 固件", command=self.run_export, state="disabled")
        self.btn_export.pack(fill="x", ipady=5, pady=5)

        # --- 状态与日志 ---
        frame4 = ttk.LabelFrame(self.root, text=" 工作台终端日志 ", padding=10)
        frame4.pack(fill="both", expand=True, padx=20, pady=10)

        self.txt_log = tk.Text(frame4, wrap="word", height=8, font=("Microsoft YaHei", 9), bg="#f4f4f4")
        self.txt_log.pack(fill="both", expand=True)
        self.log("就绪。请选择图片。")

    def log(self, msg):
        self.txt_log.insert(tk.END, msg + "\n")
        self.txt_log.see(tk.END)
        self.root.update()

    def get_resolution(self):
        val = self.combo_res.get()
        if "500" in val: return 500
        return 300

    def load_image(self):
        path = filedialog.askopenfilename(title="选择源图片", filetypes=[("图片", "*.jpg *.jpeg *.png *.bmp")])
        if not path: return

        self.current_img_path = path
        self.lbl_file.config(text=f"已载入: {os.path.basename(path)}", foreground="black")
        self.btn_preview.config(state="disabled")
        self.btn_export.config(state="disabled")

        self.log(f"已选择图片: {os.path.basename(path)}")
        self.log("正在解析 CMYW 物理图层，请稍候...")

        # 异步计算图层，防止界面卡死
        def worker():
            res = generate_cmyw_layers(self.current_img_path)

            def update_ui():
                if res is None:
                    self.log("❌ 图像解析失败，请检查文件格式！")
                else:
                    self.layers_dict = res
                    self.btn_preview.config(state="normal")
                    self.btn_export.config(state="normal")
                    self.log("✅ 解析成功！您可以开始预览或导出了。")

            self.root.after(0, update_ui)

        threading.Thread(target=worker, daemon=True).start()

    def run_preview(self):
        if not self.layers_dict: return

        width_mm = self.var_width.get()
        res_px = self.get_resolution()

        self.btn_preview.config(state="disabled")
        self.log(f"🚀 正在编译 {width_mm}mm 物理尺寸网格，请稍候...")

        def worker():
            mesh = compile_studio_mesh(self.layers_dict, physical_width_mm=width_mm, grid_w=res_px,
                                       brightness_ratio=1.6)

            # 将模型平躺，并稍微倾斜，模拟打印床上的视角
            center = mesh.get_center()
            R = mesh.get_rotation_matrix_from_xyz((np.radians(-30), np.radians(0), np.radians(0)))
            mesh.rotate(R, center)

            def show():
                self.log("✨ 预览窗口已弹出！使用鼠标左键拖拽可查看物理厚度。关闭 3D 窗口后可继续操作。")
                o3d.visualization.draw_geometries(
                    [mesh],
                    window_name=f"1:1 绝对物理预览 - 宽度:{width_mm}mm | 分辨率:{res_px}Px",
                    width=1000,
                    height=800,
                    mesh_show_back_face=True
                )
                self.btn_preview.config(state="normal")
                self.log("预览已关闭，工作台就绪。")

            self.root.after(0, show)

        threading.Thread(target=worker, daemon=True).start()

    def run_export(self):
        if not self.layers_dict: return

        save_path = filedialog.asksaveasfilename(
            title="保存 Bambu Studio 3MF 文件",
            defaultextension=".3mf",
            filetypes=[("Bambu 3MF", "*.3mf")]
        )
        if not save_path: return

        width_mm = self.var_width.get()
        res_px = self.get_resolution()

        self.btn_export.config(state="disabled")
        self.btn_preview.config(state="disabled")
        self.btn_load.config(state="disabled")

        self.log(f"💾 正在将 {width_mm}mm 物理尺寸模型打包为 3MF，这需要十几秒，请勿关闭软件...")

        def worker():
            try:
                save_as_bambu_3mf(save_path, self.layers_dict, render_res=res_px, target_width_mm=width_mm)

                def success():
                    self.log(f"🎉 导出成功！文件存于:\n{save_path}")
                    self.btn_export.config(state="normal")
                    self.btn_preview.config(state="normal")
                    self.btn_load.config(state="normal")

                self.root.after(0, success)
            except Exception as e:
                def fail():
                    self.log(f"❌ 导出失败: {str(e)}")
                    self.btn_export.config(state="normal")
                    self.btn_preview.config(state="normal")
                    self.btn_load.config(state="normal")

                self.root.after(0, fail)

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    app = CMYWApp(root)
    root.mainloop()