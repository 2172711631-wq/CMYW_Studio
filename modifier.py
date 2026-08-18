"""
FDM修改器 — 与线上网站定制参数一致的本地改单导出工具

用途：顾客线上单偏大时，按网站同一规则（最长边 100/120/150/200）改尺寸后重导出 3MF。
3MF 会内嵌顾客图作为文件图标。
"""

from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bambu_export import DEFAULT_SHELL_COLOR, FILAMENT_SLOTS, normalize_hex_color  # noqa: E402
from main import ShellParams, generate_cmyw_layers, save_as_bambu_3mf, warmup_open3d  # noqa: E402
from ui_theme import COLORS, FONTS, apply_theme  # noqa: E402

APP_TITLE = "FDM修改器"
APP_VERSION = "1.0.0"
APP_SUB = "改尺寸重导出 3MF"

# 与 web/config、customize 一致
PRINT_EDGE_OPTIONS = (100, 120, 150, 200)
DEFAULT_PRINT_EDGE = 120
MAX_PRINT_EDGE = 200
FIT_CLEARANCE_MM = 0.2

SHELL_COLOR_PRESETS: tuple[dict, ...] = (
    {"sku": "10100", "label": "象牙白", "hex": "#FFFFFF", "common": True},
    {"sku": "10200", "label": "柠檬黄", "hex": "#F4EE2A", "common": True},
    {"sku": "10101", "label": "曜石黑", "hex": "#000000", "common": True},
    {"sku": "10500", "label": "竹叶绿", "hex": "#00AE42", "common": True},
    {"sku": "10400", "label": "火焰红", "hex": "#C12E1F", "common": True},
    {"sku": "10601", "label": "群青蓝", "hex": "#0A2989", "common": True},
    {"sku": "10300", "label": "南瓜橙", "hex": "#FF6A13", "common": False},
    {"sku": "10203", "label": "珊瑚粉", "hex": "#F55A74", "common": False},
    {"sku": "10700", "label": "罗兰紫", "hex": "#5E43B7", "common": False},
    {"sku": "10603", "label": "冰晶蓝", "hex": "#0086D6", "common": False},
    {"sku": "10502", "label": "雾凇绿", "hex": "#3F8E43", "common": False},
    {"sku": "10800", "label": "拿铁咖", "hex": "#9D432C", "common": False},
    {"sku": "10102", "label": "银灰", "hex": "#A6A9AA", "common": False},
    {"sku": "10105", "label": "玄武灰", "hex": "#545454", "common": False},
    {"sku": "10103", "label": "中灰", "hex": "#8E9089", "common": False},
    {"sku": "10201", "label": "米杏", "hex": "#F7E6DE", "common": False},
    {"sku": "10401", "label": "金属金", "hex": "#E4BD68", "common": False},
    {"sku": "10202", "label": "品红", "hex": "#EC008C", "common": False},
    {"sku": "10602", "label": "青灰", "hex": "#5B6579", "common": False},
    {"sku": "10801", "label": "青铜", "hex": "#847D48", "common": False},
)


def size_from_image(iw: int, ih: int, edge: float) -> tuple[float, float]:
    iw = max(1, int(iw))
    ih = max(1, int(ih))
    edge = float(edge)
    if iw >= ih:
        return edge, round(edge * ih / iw, 2)
    return round(edge * iw / ih, 2), edge


def desktop_dir() -> Path:
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            )
            desktop, _ = winreg.QueryValueEx(key, "Desktop")
            path = Path(os.path.expandvars(desktop))
            if path.is_dir():
                return path
        except OSError:
            pass
    return Path.home() / "Desktop"


class ModifierApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"{APP_TITLE} v{APP_VERSION}")
        self.root.geometry("880x720")
        self.root.minsize(820, 640)
        self.root.configure(bg=COLORS["bg"])

        self.current_img_path: str | None = None
        self.image_w = 0
        self.image_h = 0
        self.layers_dict: dict | None = None
        self._busy = False
        self._thumb_photo: tk.PhotoImage | None = None

        apply_theme(root)
        self._build_header()
        self._build_body()
        self._set_status("就绪 — 加载顾客图片后按线上规则改尺寸并导出")

    def _build_header(self) -> None:
        bar = tk.Frame(self.root, bg=COLORS["header"], height=72)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        inner = tk.Frame(bar, bg=COLORS["header"])
        inner.pack(fill="both", expand=True, padx=20, pady=12)
        left = tk.Frame(inner, bg=COLORS["header"])
        left.pack(side="left", fill="y")
        tk.Label(left, text=APP_TITLE, bg=COLORS["header"], fg="#FFFFFF", font=FONTS["title"]).pack(anchor="w")
        tk.Label(left, text=APP_SUB, bg=COLORS["header"], fg=COLORS["header_sub"], font=FONTS["subtitle"]).pack(
            anchor="w", pady=(2, 0)
        )
        tk.Label(
            inner,
            text=f"v{APP_VERSION}",
            bg="#334155",
            fg="#E2E8F0",
            font=("Segoe UI", 8),
            padx=8,
            pady=3,
        ).pack(side="right", anchor="ne")

    def _build_body(self) -> None:
        body = ttk.Frame(self.root, padding=(16, 12, 16, 8))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        left = ttk.Frame(body, style="Card.TFrame", padding=16)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        ttk.Label(left, text="顾客图片", style="Surface.TLabel", font=FONTS["heading"]).pack(anchor="w")
        self.thumb_frame = tk.Frame(
            left,
            bg=COLORS["surface_alt"],
            width=220,
            height=220,
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
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
        self.lbl_thumb.bind("<Button-1>", lambda _e: self.load_image())

        ttk.Button(left, text="选择图片", command=self.load_image, style="Accent.TButton").pack(fill="x", pady=(0, 8))
        self.lbl_file = ttk.Label(left, text="尚未加载", style="MutedSurface.TLabel", wraplength=220)
        self.lbl_file.pack(anchor="w")

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")

        size_card = ttk.LabelFrame(right, text=" 画幅（与线上一致） ", style="Card.TLabelframe", padding=16)
        size_card.pack(fill="x", pady=(0, 10))

        ttk.Label(size_card, text="最长边", style="Surface.TLabel").grid(row=0, column=0, sticky="w")
        edge_labels = [
            "100 mm — 桌面小幅（省时省料）",
            "120 mm — 常用推荐",
            "150 mm — 较大",
            "200 mm — 上限最大（费时费料）",
        ]
        self.combo_edge = ttk.Combobox(size_card, values=edge_labels, state="readonly", width=34)
        self.combo_edge.current(1)  # 120
        self.combo_edge.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.combo_edge.bind("<<ComboboxSelected>>", lambda _e: self._refresh_size())

        ttk.Label(size_card, text="实物尺寸", style="Surface.TLabel").grid(row=1, column=0, sticky="w", pady=(12, 0))
        self.var_size_text = tk.StringVar(value="—")
        ttk.Label(size_card, textvariable=self.var_size_text, style="StatValue.TLabel").grid(
            row=1, column=1, sticky="w", padx=(12, 0), pady=(12, 0)
        )
        ttk.Label(
            size_card,
            text="按图片比例自动算宽高；200 仅为上限，默认不必打满",
            style="MutedSurface.TLabel",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Label(size_card, text="像素精度", style="Surface.TLabel").grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.combo_res = ttk.Combobox(
            size_card,
            values=("300 px — 0.4mm 喷嘴（推荐）", "500 px — 0.2mm 喷嘴（精细）"),
            state="readonly",
            width=34,
        )
        self.combo_res.current(0)
        self.combo_res.grid(row=3, column=1, sticky="w", padx=(12, 0), pady=(12, 0))

        shell_card = ttk.LabelFrame(right, text=" 灯箱外壳（与线上一致） ", style="Card.TLabelframe", padding=16)
        shell_card.pack(fill="x", pady=(0, 10))

        self.var_shell_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            shell_card,
            text="同步生成圆角灯箱",
            variable=self.var_shell_enabled,
            command=self._toggle_shell,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        fields = (
            ("壁厚 2–3", "var_wall", 3.0, 2.0, 3.0),
            ("圆角 0–10", "var_corner", 5.0, 0.0, 10.0),
            ("深度 18–30", "var_depth", 18.0, 18.0, 30.0),
        )
        self._shell_spinboxes: list[ttk.Spinbox] = []
        for col, (label, attr, default, lo, hi) in enumerate(fields):
            ttk.Label(shell_card, text=label, style="Surface.TLabel").grid(row=1, column=col, sticky="w")
            var = tk.DoubleVar(value=default)
            setattr(self, attr, var)
            sb = ttk.Spinbox(shell_card, from_=lo, to=hi, increment=0.5, textvariable=var, width=8)
            sb.grid(row=2, column=col, sticky="w", pady=(4, 0))
            self._shell_spinboxes.append(sb)

        ttk.Label(shell_card, text="外壳颜色（PLA Basic）", style="Surface.TLabel").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(14, 4)
        )
        color_vals = []
        self._color_by_label: dict[str, dict] = {}
        for c in SHELL_COLOR_PRESETS:
            tag = "常用" if c["common"] else "不常用"
            label = f"{c['label']} · {c['sku']}（{tag}）"
            color_vals.append(label)
            self._color_by_label[label] = c
        self.combo_color = ttk.Combobox(shell_card, values=color_vals, state="readonly", width=40)
        # 默认曜石黑
        black_idx = next(i for i, c in enumerate(SHELL_COLOR_PRESETS) if c["sku"] == "10101")
        self.combo_color.current(black_idx)
        self.combo_color.grid(row=4, column=0, columnspan=2, sticky="w")
        self.color_swatch = tk.Label(shell_card, width=3, bg="#000000", relief="solid", bd=1)
        self.color_swatch.grid(row=4, column=2, sticky="w", padx=(8, 0))
        self.combo_color.bind("<<ComboboxSelected>>", lambda _e: self._sync_swatch())

        ttk.Label(
            shell_card,
            text=f"装配间隙固定 {FIT_CLEARANCE_MM} mm（与网站一致，不可改）",
            style="MutedSurface.TLabel",
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 0))

        actions = ttk.Frame(right, style="Card.TFrame", padding=(0, 4))
        actions.pack(fill="x")
        self.btn_parse = ttk.Button(actions, text="解析图片", command=self.parse_image, state="disabled")
        self.btn_parse.pack(side="left", padx=(0, 8))
        self.btn_export = ttk.Button(
            actions, text="导出 3MF 到桌面", command=self.export_3mf, state="disabled", style="Primary.TButton"
        )
        self.btn_export.pack(side="left", padx=(0, 8))
        self.btn_export_as = ttk.Button(actions, text="另存为…", command=self.export_as, state="disabled")
        self.btn_export_as.pack(side="left")

        log_card = ttk.LabelFrame(self.root, text=" 日志 ", style="Card.TLabelframe", padding=8)
        log_card.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self.log_box = tk.Text(log_card, height=8, wrap="word", bg=COLORS["log_bg"], font=FONTS["mono"], relief="flat")
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(state="disabled")

        status = ttk.Frame(self.root, style="Status.TFrame", padding=(16, 6))
        status.pack(fill="x")
        self.status_var = tk.StringVar(value="")
        ttk.Label(status, textvariable=self.status_var, style="Status.TLabel").pack(side="left")
        ttk.Label(status, text=f"{APP_TITLE}", style="Status.TLabel").pack(side="right")

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def log(self, msg: str, level: str = "info") -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        del level

    def selected_edge(self) -> int:
        text = self.combo_edge.get() or ""
        for e in PRINT_EDGE_OPTIONS:
            if text.startswith(str(e)):
                return int(e)
        return DEFAULT_PRINT_EDGE

    def selected_resolution(self) -> int:
        return 500 if "500" in (self.combo_res.get() or "") else 300

    def selected_size(self) -> tuple[float, float]:
        if not self.image_w or not self.image_h:
            return 0.0, 0.0
        return size_from_image(self.image_w, self.image_h, self.selected_edge())

    def _refresh_size(self) -> None:
        w, h = self.selected_size()
        if not w:
            self.var_size_text.set("—")
            return
        edge = self.selected_edge()
        note = "（上限）" if edge >= MAX_PRINT_EDGE else ""
        self.var_size_text.set(f"{w} × {h} mm · 最长边 {edge}mm{note}")

    def _sync_swatch(self) -> None:
        c = self._color_by_label.get(self.combo_color.get())
        if c:
            self.color_swatch.config(bg=c["hex"])

    def _toggle_shell(self) -> None:
        state = "normal" if self.var_shell_enabled.get() else "disabled"
        for sb in self._shell_spinboxes:
            sb.configure(state=state)
        self.combo_color.configure(state="readonly" if self.var_shell_enabled.get() else "disabled")

    def get_shell_params(self) -> ShellParams:
        color = self._color_by_label.get(self.combo_color.get()) or {
            "hex": DEFAULT_SHELL_COLOR,
        }
        wall = float(min(3.0, max(2.0, float(self.var_wall.get()))))
        corner = float(min(10.0, max(0.0, float(self.var_corner.get()))))
        depth = float(min(30.0, max(18.0, float(self.var_depth.get()))))
        return ShellParams(
            enabled=bool(self.var_shell_enabled.get()),
            wall_thickness=wall,
            corner_radius=corner,
            shell_depth=depth,
            fit_clearance=FIT_CLEARANCE_MM,
            shell_color_hex=normalize_hex_color(color["hex"]),
        )

    def load_image(self) -> None:
        path = filedialog.askopenfilename(
            title="选择顾客图片",
            filetypes=[("图片", "*.png;*.jpg;*.jpeg;*.webp;*.bmp"), ("全部", "*.*")],
        )
        if not path:
            return
        self.current_img_path = path
        self.layers_dict = None
        self.lbl_file.config(text=os.path.basename(path))
        self._update_thumb(path)
        self._refresh_size()
        self.btn_parse.config(state="normal")
        self.btn_export.config(state="disabled")
        self.btn_export_as.config(state="disabled")
        self.log(f"已加载：{path} · {self.image_w}×{self.image_h}px")
        self._set_status("已选图 — 可先解析，或直接导出（将自动解析）")

    def _update_thumb(self, path: str) -> None:
        try:
            import cv2
            import numpy as np

            data = np.fromfile(path, dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError("decode fail")
            self.image_h, self.image_w = img.shape[:2]
            h, w = img.shape[:2]
            scale = min(210 / w, 210 / h, 1.0)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            small = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            # Tk PhotoImage via PPM
            ppm = Path(os.environ.get("TEMP", ".")) / "fdm_mod_thumb.ppm"
            header = f"P6\n{nw} {nh}\n255\n".encode("ascii")
            ppm.write_bytes(header + rgb.tobytes())
            self._thumb_photo = tk.PhotoImage(file=str(ppm))
            self.lbl_thumb.config(image=self._thumb_photo, text="")
        except Exception:
            self.lbl_thumb.config(image="", text="已选图片\n（缩略图预览失败）")

    def parse_image(self) -> None:
        if not self.current_img_path or self._busy:
            return
        self._busy = True
        self._set_status("正在解析 CMYW 分层…")
        path = self.current_img_path

        def work() -> None:
            try:
                layers = generate_cmyw_layers(path)
                if not layers:
                    raise ValueError("图片无法解析")
                self.layers_dict = layers
                self.root.after(0, lambda: self._on_parsed(True, "解析完成，可导出 3MF"))
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda e=exc: self._on_parsed(False, str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _on_parsed(self, ok: bool, msg: str) -> None:
        self._busy = False
        if ok:
            self.log(msg, "ok")
            self.btn_export.config(state="normal")
            self.btn_export_as.config(state="normal")
            self._set_status(msg)
        else:
            self.layers_dict = None
            self.log(f"解析失败：{msg}", "err")
            messagebox.showerror(APP_TITLE, msg)
            self._set_status("解析失败")

    def _ensure_layers(self) -> bool:
        if self.layers_dict:
            return True
        if not self.current_img_path:
            messagebox.showwarning(APP_TITLE, "请先选择图片")
            return False
        self._set_status("自动解析中…")
        try:
            layers = generate_cmyw_layers(self.current_img_path)
            if not layers:
                raise ValueError("图片无法解析")
            self.layers_dict = layers
            self.log("自动解析完成")
            return True
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, str(exc))
            return False

    def export_3mf(self) -> None:
        if not self.current_img_path:
            return
        base = Path(self.current_img_path).stem
        edge = self.selected_edge()
        out = desktop_dir() / f"{base}_{edge}mm.3mf"
        self._do_export(out)

    def export_as(self) -> None:
        if not self.current_img_path:
            return
        base = Path(self.current_img_path).stem
        edge = self.selected_edge()
        path = filedialog.asksaveasfilename(
            title="保存 3MF",
            initialdir=str(desktop_dir()),
            initialfile=f"{base}_{edge}mm.3mf",
            defaultextension=".3mf",
            filetypes=[("Bambu 3MF", "*.3mf")],
        )
        if path:
            self._do_export(Path(path))

    def _do_export(self, out: Path) -> None:
        if self._busy:
            return
        if not self._ensure_layers():
            return
        w, h = self.selected_size()
        if not w:
            messagebox.showwarning(APP_TITLE, "无法计算尺寸，请重新选图")
            return
        res = self.selected_resolution()
        shell = self.get_shell_params()
        img_path = self.current_img_path
        self._busy = True
        self._set_status(f"正在导出 {w}×{h} mm · {res}px…")
        self.log(f"导出 → {out} · {w}×{h}mm · {res}px · 最长边 {self.selected_edge()}")

        def work() -> None:
            try:
                tris = save_as_bambu_3mf(
                    str(out),
                    self.layers_dict,
                    res,
                    float(w),
                    shell_params=shell,
                    source_image_path=img_path,
                )
                slots = list(FILAMENT_SLOTS[:4])
                if shell.enabled:
                    slots.append({**FILAMENT_SLOTS[4], "hex": shell.shell_color_hex})
                color_note = " / ".join(s["display"] for s in slots[:5])
                self.root.after(
                    0,
                    lambda: self._on_exported(True, f"已导出：{out.name} · {tris} 三角 · {color_note}"),
                )
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda e=exc: self._on_exported(False, str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _on_exported(self, ok: bool, msg: str) -> None:
        self._busy = False
        if ok:
            self.log(msg, "ok")
            self._set_status("导出完成")
            messagebox.showinfo(APP_TITLE, msg)
        else:
            self.log(f"导出失败：{msg}", "err")
            self._set_status("导出失败")
            messagebox.showerror(APP_TITLE, msg)


def main() -> None:
    root = tk.Tk()
    ModifierApp(root)
    threading.Thread(target=warmup_open3d, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    main()
