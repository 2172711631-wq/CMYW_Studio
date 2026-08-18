"""应用视觉主题与 ttk 样式。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

APP_NAME = "FDM Litho Studio"
APP_VERSION = "1.2.6"
APP_TAGLINE = "四色透光画 · 灯箱外壳 · Bambu Studio 一键导出"

# 配色 — 浅色商业软件风格（参考 Bambu / 现代 SaaS）
COLORS = {
    "bg": "#F0F2F5",
    "surface": "#FFFFFF",
    "surface_alt": "#F8FAFC",
    "header": "#1E293B",
    "header_sub": "#94A3B8",
    "primary": "#00AE42",
    "primary_hover": "#009A3A",
    "primary_text": "#FFFFFF",
    "secondary": "#E2E8F0",
    "secondary_text": "#334155",
    "accent": "#2563EB",
    "text": "#0F172A",
    "text_muted": "#64748B",
    "border": "#E2E8F0",
    "success": "#10B981",
    "warning": "#F59E0B",
    "error": "#EF4444",
    "log_bg": "#FAFBFC",
    "log_info": "#334155",
    "log_ok": "#059669",
    "log_warn": "#D97706",
    "log_err": "#DC2626",
}

FONTS = {
    "title": ("Segoe UI", 16, "bold"),
    "subtitle": ("Segoe UI", 9),
    "heading": ("Segoe UI", 10, "bold"),
    "body": ("Segoe UI", 10),
    "small": ("Segoe UI", 9),
    "mono": ("Consolas", 9),
    "btn": ("Segoe UI", 10),
    "btn_primary": ("Segoe UI", 10, "bold"),
}


def apply_theme(root: tk.Tk) -> ttk.Style:
    root.configure(bg=COLORS["bg"])
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=COLORS["bg"], foreground=COLORS["text"], font=FONTS["body"])
    style.configure("TFrame", background=COLORS["bg"])
    style.configure("Surface.TFrame", background=COLORS["surface"])
    style.configure("Card.TFrame", background=COLORS["surface"], relief="flat")

    style.configure(
        "Card.TLabelframe",
        background=COLORS["surface"],
        bordercolor=COLORS["border"],
        relief="solid",
        borderwidth=1,
    )
    style.configure(
        "Card.TLabelframe.Label",
        background=COLORS["surface"],
        foreground=COLORS["text"],
        font=FONTS["heading"],
    )

    style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=FONTS["body"])
    style.configure("Muted.TLabel", background=COLORS["bg"], foreground=COLORS["text_muted"], font=FONTS["small"])
    style.configure("Surface.TLabel", background=COLORS["surface"], foreground=COLORS["text"])
    style.configure("MutedSurface.TLabel", background=COLORS["surface"], foreground=COLORS["text_muted"], font=FONTS["small"])
    style.configure("HeaderTitle.TLabel", background=COLORS["header"], foreground="#FFFFFF", font=FONTS["title"])
    style.configure("HeaderSub.TLabel", background=COLORS["header"], foreground=COLORS["header_sub"], font=FONTS["subtitle"])
    style.configure("StatValue.TLabel", background=COLORS["surface"], foreground=COLORS["primary"], font=("Segoe UI", 14, "bold"))
    style.configure("StatCaption.TLabel", background=COLORS["surface"], foreground=COLORS["text_muted"], font=FONTS["small"])

    style.configure(
        "TButton",
        background=COLORS["secondary"],
        foreground=COLORS["secondary_text"],
        bordercolor=COLORS["border"],
        focusthickness=0,
        padding=(14, 8),
        font=FONTS["btn"],
    )
    style.map("TButton", background=[("active", "#CBD5E1"), ("disabled", "#F1F5F9")])

    style.configure(
        "Primary.TButton",
        background=COLORS["primary"],
        foreground=COLORS["primary_text"],
        bordercolor=COLORS["primary"],
        padding=(18, 10),
        font=FONTS["btn_primary"],
    )
    style.map(
        "Primary.TButton",
        background=[("active", COLORS["primary_hover"]), ("disabled", "#86EFAC")],
        foreground=[("disabled", "#FFFFFF")],
    )

    style.configure(
        "Accent.TButton",
        background=COLORS["accent"],
        foreground="#FFFFFF",
        bordercolor=COLORS["accent"],
        padding=(18, 10),
        font=FONTS["btn_primary"],
    )
    style.map("Accent.TButton", background=[("active", "#1D4ED8"), ("disabled", "#93C5FD")])

    style.configure("TCheckbutton", background=COLORS["surface"], foreground=COLORS["text"])
    style.map("TCheckbutton", background=[("active", COLORS["surface"])])
    style.configure("TSpinbox", fieldbackground=COLORS["surface"], padding=4)
    style.configure("TCombobox", fieldbackground=COLORS["surface"], padding=4)
    style.configure("TEntry", fieldbackground=COLORS["surface"], padding=4)

    style.configure(
        "Horizontal.TProgressbar",
        troughcolor=COLORS["secondary"],
        background=COLORS["primary"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["primary"],
        darkcolor=COLORS["primary"],
        thickness=8,
    )

    style.configure("Status.TLabel", background=COLORS["surface_alt"], foreground=COLORS["text_muted"], font=FONTS["small"])
    style.configure("StatusBar.TFrame", background=COLORS["surface_alt"])

    return style


def make_header(parent: tk.Widget) -> ttk.Frame:
    bar = tk.Frame(parent, bg=COLORS["header"], height=72)
    bar.pack(fill="x")
    bar.pack_propagate(False)

    inner = tk.Frame(bar, bg=COLORS["header"])
    inner.pack(fill="both", expand=True, padx=20, pady=12)

    left = tk.Frame(inner, bg=COLORS["header"])
    left.pack(side="left", fill="y")

    tk.Label(left, text=APP_NAME, bg=COLORS["header"], fg="#FFFFFF", font=FONTS["title"]).pack(anchor="w")
    tk.Label(left, text=APP_TAGLINE, bg=COLORS["header"], fg=COLORS["header_sub"], font=FONTS["subtitle"]).pack(anchor="w", pady=(2, 0))

    badge = tk.Label(
        inner,
        text=f"v{APP_VERSION}",
        bg="#334155",
        fg="#E2E8F0",
        font=("Segoe UI", 8),
        padx=8,
        pady=3,
    )
    badge.pack(side="right", anchor="ne")
    return bar
