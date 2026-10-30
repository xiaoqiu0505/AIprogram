# -*- coding: utf-8 -*-
"""
sketchpad.py — 手绘草图窗口（三视图 / 多色画笔 / 文字标注）
=============================================================
两种模式：
  1. 自由模式  —— 一个画布随便画，导出一张图
  2. 三视图模式 —— 分别绘制主视图 / 侧视图 / 俯视图，导出三张图
                  每张图右下角自动标注视图名，方便大模型识别

工具：
  · 画笔调色板：黑 / 红 / 蓝 / 绿（红色表示"贯穿"）
  · 粗细滑杆：1 ~ 30 px
  · 文字工具：点画布任意位置输入说明文字，回车确认
"""
import os
import math
import time
import tempfile
import tkinter as tk
from tkinter import messagebox

# ---------------- 配色 ----------------
PAD_BG = "#FFFFFF"
INK = "#000000"
AXIS_X = "#E5484D"
AXIS_Y = "#22A06B"
AXIS_Z = "#4A7CFF"
BTN_BG = "#4A7CFF"
BTN_BG_D = "#3A63D4"
TEXT = "#1F2430"
SUB = "#6B7280"
BORDER = "#E3E6EC"
BAR_BG = "#FFFFFF"
PANEL_BG = "#FAFBFC"

# ---------------- 画笔颜色 ----------------
PEN_COLORS = [
    ("黑", "#000000"),
    ("红", "#E02B2B"),
    ("蓝", "#1F6FEB"),
    ("绿", "#1F9D55"),
]
DEFAULT_PEN = "#000000"

# ---------------- 视图 ----------------
VIEW_FRONT = "front"
VIEW_SIDE = "side"
VIEW_TOP = "top"

VIEW_NAMES = {
    VIEW_FRONT: "主视图",
    VIEW_SIDE: "侧视图",
    VIEW_TOP: "俯视图",
}

# 每个视图下坐标系的三个轴：(轴名, 屏幕方向向量)
VIEW_AXES = {
    VIEW_FRONT: [
        ("X", (1.0, 0.0)),
        ("Y", (0.0, -1.0)),
        ("Z", (-0.55, 0.42)),
    ],
    VIEW_SIDE: [
        ("Z", (1.0, 0.0)),
        ("Y", (0.0, -1.0)),
        ("X", (0.55, 0.42)),
    ],
    VIEW_TOP: [
        ("X", (1.0, 0.0)),
        ("Z", (0.0, 1.0)),
        ("Y", (0.55, 0.42)),
    ],
}

# 提示文字
HINT_3VIEW = "贯穿部分请用红色标注"

# ---------------- 多边形预设 ----------------
# 每个形状给出「单位轮廓」，实际绘制时按拖拽框缩放
# 坐标范围大致在 -1 ~ +1，中心在 (0,0)
def _make_regular(n, rot=0.0):
    """正 n 边形单位轮廓"""
    pts = []
    for i in range(n):
        a = math.radians(rot + 360.0 * i / n - 90.0)
        pts.append((math.cos(a), math.sin(a)))
    return pts


def _make_star(points=5, inner=0.42):
    """星形单位轮廓"""
    pts = []
    for i in range(points * 2):
        a = math.radians(360.0 * i / (points * 2) - 90.0)
        r = 1.0 if i % 2 == 0 else inner
        pts.append((r * math.cos(a), r * math.sin(a)))
    return pts


POLY_PRESETS = [
    ("triangle", "△ 三角形", _make_regular(3)),
    ("rect", "▭ 矩形", [(-1, -1), (1, -1), (1, 1), (-1, 1)]),
    ("pentagon", "⬠ 五边形", _make_regular(5)),
    ("hexagon", "⬡ 六边形", _make_regular(6)),
    ("star", "★ 星形", _make_star(5)),
]

POLY_NAMES = {pid: label for pid, label, _ in POLY_PRESETS}


class SketchPad(tk.Toplevel):
    """
    手绘画布窗口。

    用法：
        pad = SketchPad(parent, on_done=callback)
        # 自由模式：callback(image_path)            单张图
        # 三视图模式：callback([front, side, top])   三张图
    """

    def __init__(self, parent, on_done=None):
        super().__init__(parent)
        self.on_done = on_done
        self.result_path = None
        self.result_paths = None

        self.title("手绘 3D 草图 — 尽情绘制吧")
        self.geometry("1180x800")
        self.minsize(900, 620)
        self.configure(bg="#F7F8FA")

        # 绘图状态
        self.brush_size = 3
        self.pen_color = DEFAULT_PEN
        self._fullscreen = False
        self._drawing = False
        self._last_xy = None
        self.current_stroke = []      # [(x, y), ...]

        # ---- 工具状态机：pen / polygon / fill / text ----
        self.tool = "pen"

        # 文字工具
        self._text_entry = None       # 当前输入框
        self._text_pos = None         # 文字位置

        # 多边形工具
        self.poly_preset = "rect"     # 当前预设形状
        self._poly_drag_origin = None  # 拖拽起点
        self._poly_dragging = False

        # 模式
        self.view_mode = False
        self.current_view = VIEW_FRONT

        # 笔迹（每条是 dict: {"pts":[(x,y)...], "color":..., "width":...}）
        self.strokes = []
        self.views = {VIEW_FRONT: [], VIEW_SIDE: [], VIEW_TOP: []}

        # 文字（每个视图独立）
        self.texts = []
        self.view_texts = {VIEW_FRONT: [], VIEW_SIDE: [], VIEW_TOP: []}

        # 填充（每个视图独立）
        self.fills = []
        self.view_fills = {VIEW_FRONT: [], VIEW_SIDE: [], VIEW_TOP: []}

        self._build_ui()
        self._bind_events()
        self.after(150, self._center)

    # ==================== UI ====================
    def _build_ui(self):
        # ---- 顶部工具栏 ----
        bar = tk.Frame(self, bg=BAR_BG, height=54)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Frame(bar, bg=BORDER, height=1).pack(side="bottom", fill="x")

        left = tk.Frame(bar, bg=BAR_BG)
        left.pack(side="left", padx=14, pady=8)
        tk.Label(left, text="✏", font=("Segoe UI", 15), fg=BTN_BG,
                 bg=BAR_BG).pack(side="left")
        self.lbl_title = tk.Label(left, text="尽情绘制吧",
                                  font=("Microsoft YaHei UI", 12, "bold"),
                                  fg=TEXT, bg=BAR_BG)
        self.lbl_title.pack(side="left", padx=(8, 0))

        self.lbl_tip = tk.Label(left, text="F11 全屏　·　左键绘制",
                                font=("Microsoft YaHei UI", 9), fg=SUB,
                                bg=BAR_BG)
        self.lbl_tip.pack(side="left", padx=(14, 0))

        right = tk.Frame(bar, bg=BAR_BG)
        right.pack(side="right", padx=14)

        self._mk_btn(right, "清空", self.clear_all, small=True).pack(
            side="left", padx=(0, 6))
        self._mk_btn(right, "撤销", self.undo, small=True).pack(
            side="left", padx=(0, 10))
        self._mk_btn(right, "画好了！", self.finish, primary=True).pack(side="left")

        # ---- 工具面板（画笔 + 粗细 + 文字）----
        tools = tk.Frame(self, bg=PANEL_BG, height=46)
        tools.pack(fill="x")
        tools.pack_propagate(False)
        tk.Frame(tools, bg=BORDER, height=1).pack(side="bottom", fill="x")

        ti = tk.Frame(tools, bg=PANEL_BG)
        ti.pack(side="left", padx=14, pady=6)

        # 颜色按钮
        tk.Label(ti, text="颜色", font=("Microsoft YaHei UI", 9), fg=SUB,
                 bg=PANEL_BG).pack(side="left", padx=(0, 6))
        self.color_btns = {}
        for name, c in PEN_COLORS:
            cv = tk.Canvas(ti, width=26, height=26, bg=PANEL_BG,
                           highlightthickness=0, cursor="hand2")
            cv.create_oval(3, 3, 23, 23, fill=c, outline="",
                           tags="dot")
            cv.pack(side="left", padx=3)
            cv.bind("<Button-1>", lambda e, cc=c: self.set_pen_color(cc))
            self.color_btns[c] = cv
        self._refresh_color_btns()

        # 分隔
        tk.Frame(ti, bg=BORDER, width=1, height=22).pack(side="left", padx=12)

        # 粗细滑杆
        tk.Label(ti, text="粗细", font=("Microsoft YaHei UI", 9), fg=SUB,
                 bg=PANEL_BG).pack(side="left", padx=(0, 6))
        self.scale_size = tk.Scale(
            ti, from_=1, to=30, orient="horizontal", length=140,
            showvalue=True, font=("Microsoft YaHei UI", 8),
            bg=PANEL_BG, fg=TEXT, troughcolor="#E7EAF0",
            highlightthickness=0, bd=0, sliderlength=14,
            command=self._on_scale)
        self.scale_size.set(self.brush_size)
        self.scale_size.pack(side="left", padx=(0, 10))

        # 分隔
        tk.Frame(ti, bg=BORDER, width=1, height=22).pack(side="left", padx=12)

        # ---- 绘图工具按钮组 ----
        tk.Label(ti, text="工具", font=("Microsoft YaHei UI", 9), fg=SUB,
                 bg=PANEL_BG).pack(side="left", padx=(0, 6))

        self.tool_btns = {}
        tool_defs = [
            ("pen", "✏ 画笔"),
            ("polygon", "⬠ 多边形"),
            ("fill", "🪣 填充"),
            ("text", "⊞ 文字"),
        ]
        for tid, label in tool_defs:
            b = tk.Button(
                ti, text=label, font=("Microsoft YaHei UI", 9),
                command=lambda t=tid: self.set_tool(t),
                bg="#FFFFFF", fg=TEXT, activebackground="#EEF3FF",
                relief="flat", bd=0, cursor="hand2", padx=9, pady=4,
                highlightbackground=BORDER, highlightthickness=1)
            b.pack(side="left", padx=2)
            self.tool_btns[tid] = b

        # ---- 多边形预设选择（仅多边形工具生效）----
        self.preset_frame = tk.Frame(ti, bg=PANEL_BG)
        self.preset_frame.pack(side="left", padx=(8, 0))

        self.preset_btns = {}
        for pid, label, _ in POLY_PRESETS:
            pb = tk.Button(
                self.preset_frame, text=label,
                font=("Microsoft YaHei UI", 8),
                command=lambda p=pid: self.set_poly_preset(p),
                bg="#FFFFFF", fg=TEXT, activebackground="#EEF3FF",
                relief="flat", bd=0, cursor="hand2", padx=6, pady=3,
                highlightbackground=BORDER, highlightthickness=1)
            pb.pack(side="left", padx=1)
            self.preset_btns[pid] = pb

        self._refresh_preset_btns()
        self._update_preset_visibility()

        # ---- 「一键填充全部」按钮（填充工具下显示）----
        self.btn_fill_all = tk.Button(
            ti, text="⚡ 填充全部闭合区域",
            font=("Microsoft YaHei UI", 9),
            command=self.fill_all_regions,
            bg="#FFFFFF", fg=BTN_BG, activebackground="#EEF3FF",
            activeforeground=BTN_BG,
            relief="flat", bd=0, cursor="hand2", padx=10, pady=4,
            highlightbackground=BORDER, highlightthickness=1)
        # 初始隐藏，切到填充工具时显示

        self._refresh_tool_btns()

        # 右侧：三视图提示 / 模式按钮
        tr = tk.Frame(tools, bg=PANEL_BG)
        tr.pack(side="right", padx=14, pady=6)

        self.lbl_hint_color = tk.Label(
            tr, text="", font=("Microsoft YaHei UI", 9),
            fg="#E02B2B", bg=PANEL_BG)
        self.lbl_hint_color.pack(side="left", padx=(0, 12))

        self.btn_3view = tk.Button(
            tr, text="⊞ 三视图模式", font=("Microsoft YaHei UI", 9),
            command=self.enter_view_mode,
            bg="#FFFFFF", fg=BTN_BG, activebackground="#EEF3FF",
            activeforeground=BTN_BG, relief="flat", bd=0, cursor="hand2",
            padx=14, pady=4, highlightbackground=BORDER, highlightthickness=1)
        self.btn_3view.pack(side="left")

        # ---- 主区域：左栏 + 画布 ----
        main = tk.Frame(self, bg=PAD_BG)
        main.pack(fill="both", expand=True)

        # 左栏（三视图模式才显示）
        self.axis_frame = tk.Frame(main, bg=PANEL_BG, width=140)
        tk.Frame(self.axis_frame, bg=BORDER, width=1).pack(side="right", fill="y")
        self.axis_canvas = tk.Canvas(self.axis_frame, bg=PANEL_BG,
                                     highlightthickness=0, width=138)
        self.axis_canvas.pack(fill="both", expand=True)

        # 右侧容器
        self.right_area = tk.Frame(main, bg=PAD_BG)
        self.right_area.pack(side="left", fill="both", expand=True)

        # 视图切换栏
        self.view_bar = tk.Frame(self.right_area, bg=PANEL_BG, height=50)
        tk.Frame(self.view_bar, bg=BORDER, height=1).pack(side="bottom", fill="x")

        # 画布
        self.canvas = tk.Canvas(self.right_area, bg=PAD_BG,
                                highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_resize)

        self._hint_id = self.canvas.create_text(
            0, 0, text="在这里画你的零件草图\n\n（按住左键拖动即可绘制）",
            font=("Microsoft YaHei UI", 13), fill="#C8CCD4", justify="center",
            tags="empty_hint")

        # ---- 底部状态 ----
        foot = tk.Frame(self, bg="#F7F8FA", height=28)
        foot.pack(fill="x", side="bottom")
        foot.pack_propagate(False)
        self.lbl_hint = tk.Label(
            foot, text="提示：简单零件手绘更好识别",
            font=("Microsoft YaHei UI", 9), fg=SUB, bg="#F7F8FA")
        self.lbl_hint.pack(side="left", padx=14, pady=4)

        self._build_view_switcher()

    def _mk_btn(self, parent, text, cmd, small=False, primary=False):
        if primary:
            bg, fg, hbg = BTN_BG, "#FFFFFF", BTN_BG_D
        else:
            bg, fg, hbg = "#FFFFFF", TEXT, "#EEF3FF"
        font = ("Microsoft YaHei UI", 9 if small else 10)
        b = tk.Button(parent, text=text, command=cmd, font=font, bg=bg, fg=fg,
                      activebackground=hbg,
                      activeforeground=fg if primary else TEXT,
                      relief="flat", bd=0, cursor="hand2",
                      padx=16 if primary else 12, pady=6 if primary else 4,
                      highlightbackground=BORDER,
                      highlightthickness=1 if not primary else 0)
        b.bind("<Enter>", lambda e: b.config(bg=hbg))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        return b

    # ==================== 工具状态机 ====================
    TOOL_CURSORS = {
        "pen": "crosshair",
        "polygon": "crosshair",
        "fill": "spraycan",
        "text": "xterm",
    }

    TOOL_HINTS = {
        "pen": "画笔：按住左键拖动绘制",
        "polygon": "多边形：选好形状后，按住左键拖拽拉伸，松开完成",
        "fill": "填充：左键点击闭合区域，即可填充当前颜色",
        "text": "文字：点击画布任意位置 → 输入文字 → 回车确认",
    }

    def set_tool(self, tool):
        """切换工具"""
        # 切换前先收尾
        self._cancel_pending()

        self.tool = tool
        self._refresh_tool_btns()
        self._update_preset_visibility()

        cursor = self.TOOL_CURSORS.get(tool, "crosshair")
        self.canvas.config(cursor=cursor)

        if tool == "polygon":
            self.lbl_hint.config(
                text=f"已选「{POLY_NAMES.get(self.poly_preset, '')}」　·　"
                     f"按住左键拖拽拉伸大小，松开完成　·　Esc 取消")
        else:
            self.lbl_hint.config(text=self.TOOL_HINTS.get(tool, ""))

    def _cancel_pending(self):
        """取消当前未完成的操作"""
        # 取消文字输入框
        if self._text_entry is not None:
            try:
                self._text_entry.destroy()
            except Exception:
                pass
            self._text_entry = None
            self.canvas.delete("temp_text")

        # 取消未完成的多边形拖拽
        if self._poly_dragging:
            self._poly_dragging = False
            self._poly_drag_origin = None
        self.canvas.delete("poly_temp")

    def _refresh_tool_btns(self):
        for tid, b in self.tool_btns.items():
            if tid == self.tool:
                b.config(bg=BTN_BG, fg="#FFFFFF",
                         activebackground=BTN_BG_D, activeforeground="#FFFFFF")
            else:
                b.config(bg="#FFFFFF", fg=TEXT,
                         activebackground="#EEF3FF", activeforeground=TEXT)

    # ==================== 画笔颜色 ====================
    def set_pen_color(self, color):
        """切换颜色（画笔 / 多边形 / 填充 都用这个颜色）"""
        self.pen_color = color
        self._refresh_color_btns()

    def _refresh_color_btns(self):
        for c, cv in self.color_btns.items():
            cv.delete("ring")
            if c == self.pen_color:
                cv.create_oval(1, 1, 25, 25, outline=c, width=2, tags="ring")

    def _on_scale(self, val):
        try:
            self.brush_size = int(float(val))
        except Exception:
            pass

    # ==================== 文字工具 ====================
    def _place_text_entry(self, x, y):
        """在画布上放置一个输入框"""
        if self._text_entry is not None:
            try:
                self._text_entry.destroy()
            except Exception:
                pass

        self.canvas.delete("temp_text")

        ent = tk.Entry(
            self.canvas, font=("Microsoft YaHei UI", 12),
            bg="#FFFFFF", fg=self.pen_color,
            relief="solid", bd=1,
            highlightbackground=BTN_BG, highlightthickness=2,
            insertbackground=self.pen_color)

        self.canvas.create_window(x, y, window=ent, anchor="nw",
                                  tags="temp_text", width=220)
        ent.focus_set()
        ent.bind("<Return>", lambda e: self._confirm_text(x, y))
        ent.bind("<Escape>", lambda e: self.set_tool("pen"))

        self._text_entry = ent
        self._text_pos = (x, y)

    def _confirm_text(self, x, y):
        """确认输入的文字"""
        if self._text_entry is None:
            return
        txt = self._text_entry.get().strip()
        self.canvas.delete("temp_text")
        try:
            self._text_entry.destroy()
        except Exception:
            pass
        self._text_entry = None

        if txt:
            self._cur_texts().append({
                "pos": (x, y),
                "text": txt,
                "color": self.pen_color,
                "size": max(10, self.brush_size * 3 + 6),
            })
            self._redraw()

    # ==================== 多边形工具（预设 + 拖拽缩放）====================
    def set_poly_preset(self, pid):
        """选择多边形预设形状"""
        self.poly_preset = pid
        self._refresh_preset_btns()
        self.lbl_hint.config(
            text=f"已选「{POLY_NAMES.get(pid, pid)}」　·　"
                 f"按住左键拖拽可拉伸大小，松开完成")

    def _refresh_preset_btns(self):
        if not hasattr(self, "preset_btns"):
            return
        for pid, b in self.preset_btns.items():
            if pid == self.poly_preset:
                b.config(bg=BTN_BG, fg="#FFFFFF",
                         activebackground=BTN_BG_D, activeforeground="#FFFFFF")
            else:
                b.config(bg="#FFFFFF", fg=TEXT,
                         activebackground="#EEF3FF", activeforeground=TEXT)

    def _update_preset_visibility(self):
        """只有多边形工具时才显示预设选择；填充工具时显示「填充全部」"""
        if hasattr(self, "preset_frame"):
            if self.tool == "polygon":
                if not self.preset_frame.winfo_ismapped():
                    self.preset_frame.pack(side="left", padx=(8, 0))
            else:
                if self.preset_frame.winfo_ismapped():
                    self.preset_frame.pack_forget()

        if hasattr(self, "btn_fill_all"):
            if self.tool == "fill":
                if not self.btn_fill_all.winfo_ismapped():
                    self.btn_fill_all.pack(side="left", padx=(8, 0))
            else:
                if self.btn_fill_all.winfo_ismapped():
                    self.btn_fill_all.pack_forget()

    def _poly_unit_points(self):
        """取当前预设的单位轮廓"""
        for pid, _label, pts in POLY_PRESETS:
            if pid == self.poly_preset:
                return pts
        return [(-1, -1), (1, -1), (1, 1), (-1, 1)]

    def _poly_points_from_drag(self, x0, y0, x1, y1):
        """
        根据拖拽的起点和当前点，算出多边形实际顶点。

        用拖拽框（矩形）把单位轮廓缩放进去：
          · 单位轮廓 x 范围 -1~+1 → 映射到 x0~x1
          · 单位轮廓 y 范围 -1~+1 → 映射到 y0~y1
        """
        unit = self._poly_unit_points()

        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        hw = abs(x1 - x0) / 2.0
        hh = abs(y1 - y0) / 2.0

        # 拖得太小就忽略
        if hw < 4 or hh < 4:
            return []

        pts = [(cx + ux * hw, cy + uy * hh) for (ux, uy) in unit]
        return pts

    def _draw_poly_preview(self, x0, y0, x1, y1):
        """绘制拖拽中的多边形预览"""
        self.canvas.delete("poly_temp")
        pts = self._poly_points_from_drag(x0, y0, x1, y1)
        if not pts:
            return

        # 多边形本身
        flat = []
        for p in pts:
            flat.extend(p)
        flat.extend(pts[0])
        self.canvas.create_line(*flat, fill=self.pen_color,
                                width=max(1, self.brush_size),
                                capstyle="round", joinstyle="round",
                                tags="poly_temp")

        # 拖拽框（虚线参考）
        self.canvas.create_rectangle(
            min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1),
            outline="#A0A4AD", dash=(3, 3), tags="poly_temp")

        # 顶点小圆点
        for px, py in pts:
            r = 3
            self.canvas.create_oval(px - r, py - r, px + r, py + r,
                                    fill=self.pen_color, outline="",
                                    tags="poly_temp")

        # 尺寸提示
        cxm = (min(x0, x1) + max(x0, x1)) / 2.0
        cym = min(y0, y1) - 14
        self.canvas.create_text(
            cxm, cym, text=f"{abs(x1 - x0)} × {abs(y1 - y0)}",
            font=("Microsoft YaHei UI", 9), fill="#6B7280",
            tags="poly_temp")

    def _poly_commit(self, x0, y0, x1, y1):
        """松开左键：把多边形定下来"""
        pts = self._poly_points_from_drag(x0, y0, x1, y1)
        self.canvas.delete("poly_temp")
        if not pts:
            return

        self._cur_strokes().append({
            "pts": list(pts) + [pts[0]],   # 闭合
            "color": self.pen_color,
            "width": self.brush_size,
        })
        self._redraw()
        if self.view_mode:
            self._draw_axes()

    # ==================== 填充工具 ====================
    def _do_fill(self, x, y):
        """
        洪水填充：从 (x,y) 出发找到闭合区域，填充为当前颜色。

        性能做法：
          · 线条栅格化用 PIL 的 ImageDraw.line（C 实现，极快）
          · 洪水填充用 PIL 的 ImageDraw.floodfill（C 实现，10 万像素约 20ms）
          · 结果缓存成一张 RGBA 图层，作为单个 canvas image 显示
            （而不是几百上千个 create_rectangle，那样会卡死）
        """
        try:
            from PIL import Image, ImageDraw
        except Exception:
            self.lbl_hint.config(text="缺少 Pillow，无法填充")
            return

        t0 = time.time()

        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())

        # ---- 1. 构建障碍掩码（黑线 = 障碍）----
        base = self._build_fill_base(cw, ch)
        if base is None:
            return

        ix, iy = int(x), int(y)
        if not (0 <= ix < cw and 0 <= iy < ch):
            return

        # 2. 点在线上？
        pixel = base.getpixel((ix, iy))
        if pixel == (0, 0, 0):
            self.lbl_hint.config(text="点在线条上了，请点在区域内部")
            return

        # 3. 快速洪水填充（PIL C 实现）
        color_rgb = self._hex_to_rgb(self.pen_color)
        work = base.copy()
        try:
            ImageDraw.floodfill(work, (ix, iy), color_rgb, thresh=20)
        except Exception as e:
            self.lbl_hint.config(text=f"填充失败：{e}")
            return

        # 4. 计算填充了多大面积（对比原图）
        try:
            from PIL import ImageChops
            diff = ImageChops.difference(base, work)
            bbox = diff.getbbox()
            if bbox is None:
                self.lbl_hint.config(text="这里已经是这个颜色了")
                return
            area_w = bbox[2] - bbox[0]
            area_h = bbox[3] - bbox[1]
            area = area_w * area_h
        except Exception:
            area = 0
            bbox = None

        # 5. 面积太大 → 说明没闭合（整个画布都被填了）
        if area > cw * ch * 0.75:
            messagebox.showinfo(
                "需要闭合曲线",
                "没有找到闭合区域，颜色溢满整个画布了。\n\n"
                "请先用画笔或多边形画一个**闭合**的轮廓，再点它内部填充。\n"
                "（线条之间不能有缺口）", parent=self)
            return

        # 6. 存成填充记录（后填的覆盖先填的，可以重叠重填）
        self._cur_fills().append({
            "seed": (ix, iy),
            "color": self.pen_color,
        })

        dt = (time.time() - t0) * 1000
        self.lbl_hint.config(
            text=f"已填充 {area:,} 像素（{self.pen_color}）耗时 {dt:.0f}ms")

        # 8. 只重画填充层（不整体重绘，避免卡顿）
        self._render_fill_layer()
        if self.view_mode:
            self._draw_axes()

    def _build_fill_base(self, cw, ch):
        """构建填充用的基础图（白底 + 黑色线条作为障碍）"""
        # 缓存：内容没变就复用
        sig = self._fill_signature()
        if getattr(self, "_fill_base_cache", None) is not None and \
                getattr(self, "_fill_base_sig", None) == sig:
            return self._fill_base_cache

        try:
            from PIL import Image, ImageDraw

            base = Image.new("RGB", (cw, ch), (255, 255, 255))
            d = ImageDraw.Draw(base)

            for s in self._cur_strokes():
                pts = s["pts"]
                w = max(2, int(round(s.get("width", 3))))
                if len(pts) == 1:
                    px, py = pts[0]
                    d.ellipse([px - w, py - w, px + w, py + w], fill=(0, 0, 0))
                else:
                    d.line([(p[0], p[1]) for p in pts], fill=(0, 0, 0),
                           width=w, joint="curve")
                    for (ex, ey) in (pts[0], pts[-1]):
                        d.ellipse([ex - w / 2, ey - w / 2,
                                   ex + w / 2, ey + w / 2], fill=(0, 0, 0))

            self._fill_base_cache = base
            self._fill_base_sig = sig
            return base
        except Exception:
            return None

    def _fill_signature(self):
        """内容指纹，用来判断缓存是否失效"""
        st = self._cur_strokes()
        sig = []
        for s in st:
            pts = s["pts"]
            sig.append((len(pts), pts[0] if pts else None,
                        pts[-1] if pts else None,
                        round(s.get("width", 3))))
        return (self.current_view if self.view_mode else "-",
                self.canvas.winfo_width(),
                self.canvas.winfo_height(),
                tuple(sig))

    def fill_all_regions(self):
        """
        一键填充所有闭合区域：
          · 对每个闭合轮廓（首尾相连的笔迹），取其内部一点作为种子填充
          · 已经填过的区域跳过（除非颜色不同）
        """
        try:
            from PIL import Image, ImageDraw
        except Exception:
            self.lbl_hint.config(text="缺少 Pillow")
            return

        strokes = self._cur_strokes()
        if not strokes:
            self.lbl_hint.config(text="画布上还没有线条")
            return

        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        base = self._build_fill_base(cw, ch)
        if base is None:
            return

        t0 = time.time()
        added = 0
        skipped = 0

        existing = {(int(f["seed"][0]), int(f["seed"][1])) for f in self._cur_fills()}

        for s in strokes:
            pts = s["pts"]
            if len(pts) < 3:
                continue

            # 计算轮廓的种子点：包围盒中心，若在线上则往内找
            seed = self._find_seed_in_polygon(pts, base, cw, ch)
            if seed is None:
                skipped += 1
                continue

            if seed in existing:
                skipped += 1
                continue

            # 试填这个种子点，看看能填多大
            work = base.copy()
            try:
                ImageDraw.floodfill(work, seed, (1, 2, 3), thresh=20)
            except Exception:
                skipped += 1
                continue

            from PIL import ImageChops
            try:
                bbox = ImageChops.difference(base, work).getbbox()
            except Exception:
                bbox = None
            if bbox is None:
                skipped += 1
                continue

            area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
            # 太大说明漏了（跑到画布外面）
            if area > cw * ch * 0.7:
                skipped += 1
                continue

            self._cur_fills().append({
                "seed": seed,
                "color": self.pen_color,
            })
            existing.add(seed)
            added += 1

        dt = (time.time() - t0) * 1000
        self._render_fill_layer()

        msg = f"填充了 {added} 个闭合区域"
        if skipped:
            msg += f"（跳过 {skipped} 个：已填过或未闭合）"
        msg += f"  耗时 {dt:.0f}ms"
        self.lbl_hint.config(text=msg)

    def _find_seed_in_polygon(self, pts, base, cw, ch):
        """
        在多边形内部找一个安全种子点（不在线上）。
        """
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        cx = (min(xs) + max(xs)) / 2.0
        cy = (min(ys) + max(ys)) / 2.0

        candidates = [(int(cx), int(cy))]
        # 往外扩散找（有些形状中心不在实体里，如星形/环形）
        for r in (5, 10, 20, 30, 50, 80):
            for dx, dy in ((0, -r), (0, r), (-r, 0), (r, 0),
                           (-r, -r), (r, -r), (-r, r), (r, r)):
                candidates.append((int(cx) + dx, int(cy) + dy))

        for (px, py) in candidates:
            if not (2 <= px < cw - 2 and 2 <= py < ch - 2):
                continue
            if base.getpixel((px, py)) == (0, 0, 0):
                continue
            # 用射线法确认在多边形内
            if not self._point_in_poly(px, py, pts):
                continue
            return (px, py)
        return None

    @staticmethod
    def _point_in_poly(px, py, poly):
        """射线法判断点是否在多边形内"""
        n = len(poly)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if ((yi > py) != (yj > py)) and \
                    (px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi):
                inside = not inside
            j = i
        return inside

    def _render_fill_layer(self):
        """
        把「基础图 + 所有填充」合成一张 RGBA，作为单个 canvas image 显示。
        这样无论填多少区域，canvas item 数量恒定（1 个），不会卡。
        """
        try:
            from PIL import Image, ImageDraw, ImageTk
        except Exception:
            return

        fills = self._cur_fills()
        self.canvas.delete("fillimg")

        if not fills:
            self._fill_photo = None
            return

        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())

        base = self._build_fill_base(cw, ch)
        if base is None:
            return

        work = base.copy()
        for f in fills:
            seed = (int(f["seed"][0]), int(f["seed"][1]))
            rgb = self._hex_to_rgb(f.get("color", INK))
            if not (0 <= seed[0] < cw and 0 <= seed[1] < ch):
                continue
            try:
                ImageDraw.floodfill(work, seed, rgb, thresh=20)
            except Exception:
                continue

        # 把白色背景和黑色线条变透明，让 canvas 背景和上层笔迹透出来
        # 用 PIL 的向量化操作（比逐像素 Python 循环快 100 倍）
        rgb_img = work.convert("RGB")
        try:
            from PIL import ImageChops
            r, g, b = rgb_img.split()

            # 白色掩码：r>250 且 g>250 且 b>250
            white = ImageChops.multiply(
                ImageChops.multiply(r.point(lambda v: 255 if v > 250 else 0),
                                    g.point(lambda v: 255 if v > 250 else 0)),
                b.point(lambda v: 255 if v > 250 else 0))

            # 黑色掩码：r<8 且 g<8 且 b<8
            dark = ImageChops.multiply(
                ImageChops.multiply(r.point(lambda v: 255 if v < 8 else 0),
                                    g.point(lambda v: 255 if v < 8 else 0)),
                b.point(lambda v: 255 if v < 8 else 0))

            # 透明区 = 白色 ∪ 黑色 → alpha = 0
            transparent = ImageChops.lighter(white, dark)

            # 反相得到不透明区（255 = 不透明）
            alpha = transparent.point(lambda v: 0 if v > 128 else 255)

            rgba = rgb_img.convert("RGBA")
            rgba.putalpha(alpha)
        except Exception:
            # 退路：整体不透明
            rgba = rgb_img.convert("RGBA")

        try:
            self._fill_photo = ImageTk.PhotoImage(rgba)
        except Exception:
            self._fill_photo = None
            return

        self.canvas.create_image(0, 0, image=self._fill_photo,
                                 anchor="nw", tags=("fillimg", "fill"))
        self.canvas.tag_lower("fillimg")

    @staticmethod
    def _is_closed(pts, tol=6.0):
        """判断点列是否首尾接近"""
        if len(pts) < 3:
            return False
        x0, y0 = pts[0]
        x1, y1 = pts[-1]
        return ((x0 - x1) ** 2 + (y0 - y1) ** 2) ** 0.5 <= tol

    # ==================== 三视图模式 ====================
    def _build_view_switcher(self):
        """构建视图切换栏"""
        for w in self.view_bar.winfo_children():
            if w.winfo_class() != "Frame" or w.winfo_height() > 3:
                w.destroy()

        left = tk.Frame(self.view_bar, bg=PANEL_BG)
        left.pack(side="left", padx=16, pady=8)
        self.lbl_cur_view = tk.Label(
            left, text="", font=("Microsoft YaHei UI", 10, "bold"),
            fg=TEXT, bg=PANEL_BG)
        self.lbl_cur_view.pack(side="left")

        right = tk.Frame(self.view_bar, bg=PANEL_BG)
        right.pack(side="right", padx=16, pady=8)

        self.view_btns = {}
        for vid in (VIEW_FRONT, VIEW_SIDE, VIEW_TOP):
            b = tk.Button(right, text=VIEW_NAMES[vid],
                          font=("Microsoft YaHei UI", 9),
                          command=lambda v=vid: self.switch_view(v),
                          relief="flat", bd=0, cursor="hand2",
                          padx=18, pady=5,
                          highlightbackground=BORDER, highlightthickness=1)
            b.pack(side="left", padx=4)
            self.view_btns[vid] = b

    def enter_view_mode(self):
        """进入三视图模式"""
        if self.view_mode:
            return

        if self.strokes:
            if messagebox.askyesno(
                    "进入三视图",
                    "当前画布上有笔迹，要把它作为「主视图」的内容吗？\n\n"
                    "选「是」= 保留为主视图\n选「否」= 清空重新画",
                    parent=self):
                self.views[VIEW_FRONT] = list(self.strokes)
                self.view_texts[VIEW_FRONT] = list(self.texts)
            self.strokes = []
            self.texts = []

        self.view_mode = True
        self.current_view = VIEW_FRONT

        self.axis_frame.pack(side="left", fill="y", before=self.right_area)
        self.axis_frame.pack_propagate(False)
        self.axis_frame.config(width=140)
        self.axis_frame.update_idletasks()
        self.axis_canvas.config(height=self.axis_frame.winfo_height())

        self.view_bar.pack(fill="x", before=self.canvas)
        self.view_bar.pack_propagate(False)
        self.view_bar.config(height=50)

        self.btn_3view.config(text="⊟ 退出三视图", command=self.exit_view_mode)
        self.lbl_title.config(text="三视图模式")
        self.lbl_tip.config(text="F11 全屏　·　左键绘制　·　红色=贯穿")
        self.lbl_hint.config(
            text="分别绘制三个视图 · 点击上方按钮切换 · 三个都画完再点「画好了！」")

        # 三视图模式下显示红色提示
        self.lbl_hint_color.config(text="● 贯穿部分用红色标注")

        self._update_view_display()
        self.after(100, self._draw_axes)

    def exit_view_mode(self):
        """退出三视图模式"""
        if any(self.views[v] for v in self.views):
            if not messagebox.askyesno("退出三视图",
                                       "退出后三视图的笔迹会丢失，确定吗？",
                                       parent=self):
                return

        self.view_mode = False
        self.views = {VIEW_FRONT: [], VIEW_SIDE: [], VIEW_TOP: []}
        self.view_texts = {VIEW_FRONT: [], VIEW_SIDE: [], VIEW_TOP: []}

        self.axis_frame.pack_forget()
        self.view_bar.pack_forget()

        self.btn_3view.config(text="⊞ 三视图模式", command=self.enter_view_mode)
        self.lbl_title.config(text="尽情绘制吧")
        self.lbl_tip.config(text="F11 全屏　·　左键绘制")
        self.lbl_hint.config(text="提示：简单零件手绘更好识别")
        self.lbl_hint_color.config(text="")

        self._redraw()

    def switch_view(self, target):
        """切换视图"""
        if target == self.current_view:
            messagebox.showinfo("提示", "这个视图就是！", parent=self)
            return
        self._cancel_pending()
        self.current_view = target
        self._update_view_display()

    def _update_view_display(self):
        """更新视图显示"""
        name = VIEW_NAMES[self.current_view]

        if hasattr(self, "lbl_cur_view"):
            self.lbl_cur_view.config(text=f"当前：{name}")

        for vid, b in self.view_btns.items():
            if vid == self.current_view:
                b.config(bg=BTN_BG, fg="#FFFFFF",
                         activebackground=BTN_BG_D, activeforeground="#FFFFFF")
            else:
                b.config(bg="#FFFFFF", fg=TEXT,
                         activebackground="#EEF3FF", activeforeground=TEXT)

        self._draw_axes()
        self._redraw()

    def _draw_axes(self):
        """绘制坐标系"""
        c = self.axis_canvas
        c.delete("all")

        w = c.winfo_width()
        h = c.winfo_height()
        if w < 30 or h < 30:
            self.after(80, self._draw_axes)
            return

        name = VIEW_NAMES[self.current_view]

        c.create_text(w / 2, 26, text=name,
                      font=("Microsoft YaHei UI", 10, "bold"), fill=TEXT)
        c.create_text(w / 2, 44, text="坐标轴",
                      font=("Microsoft YaHei UI", 8), fill=SUB)

        ox = w * 0.46
        oy = h * 0.56
        length = min(w * 0.32, h * 0.22)

        color_map = {"X": AXIS_X, "Y": AXIS_Y, "Z": AXIS_Z}

        for axis_name, (dx, dy) in VIEW_AXES[self.current_view]:
            color = color_map.get(axis_name, TEXT)
            ex = ox + dx * length
            ey = oy + dy * length
            c.create_line(ox, oy, ex, ey, fill=color, width=2,
                          arrow="last", arrowshape=(8, 10, 4))
            lx = ox + dx * (length + 15)
            ly = oy + dy * (length + 15)
            c.create_text(lx, ly, text=axis_name,
                          font=("Segoe UI", 11, "bold"), fill=color)

        c.create_oval(ox - 3.5, oy - 3.5, ox + 3.5, oy + 3.5,
                      fill=TEXT, outline="")

        tips = {
            VIEW_FRONT: "从正面看",
            VIEW_SIDE: "从左侧看",
            VIEW_TOP: "从上方看",
        }
        c.create_text(w / 2, h - 46, text=tips.get(self.current_view, ""),
                      font=("Microsoft YaHei UI", 8), fill=SUB)

        done = [VIEW_NAMES[v] for v in (VIEW_FRONT, VIEW_SIDE, VIEW_TOP)
                if self.views[v]]
        if done:
            c.create_text(w / 2, h - 28, text="已画：" + " ".join(done),
                          font=("Microsoft YaHei UI", 7), fill="#22A06B")

        # 红色贯穿提示
        c.create_text(w / 2, h - 10, text="红色 = 贯穿",
                      font=("Microsoft YaHei UI", 8), fill="#E02B2B")

    # ==================== 事件 ====================
    def _bind_events(self):
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<ButtonPress-3>", self._on_right)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.bind("<F11>", self._toggle_fullscreen)
        self.bind("<Escape>", self._on_esc)
        self.bind("<Control-z>", lambda e: self.undo())
        self.bind("<Control-Z>", lambda e: self.undo())
        # 多边形：鼠标移动时更新预览
        self.canvas.bind("<Motion>", self._on_motion)

    def _on_motion(self, event):
        """鼠标移动：多边形拖拽时实时更新预览"""
        if self.tool == "polygon" and self._poly_dragging:
            ox, oy = self._poly_drag_origin
            self._draw_poly_preview(ox, oy, event.x, event.y)

    def _cur_strokes(self):
        if self.view_mode:
            return self.views[self.current_view]
        return self.strokes

    def _cur_texts(self):
        if self.view_mode:
            return self.view_texts[self.current_view]
        return self.texts

    def _cur_fills(self):
        if self.view_mode:
            return self.view_fills[self.current_view]
        return self.fills

    def _on_resize(self, event):
        self.canvas.coords(self._hint_id, event.width // 2, event.height // 2)
        if self.view_mode:
            self._draw_axes()

    # ---------- 鼠标事件，按工具分发 ----------
    def _on_press(self, event):
        if self.tool == "text":
            self._place_text_entry(event.x, event.y)
            return

        if self.tool == "fill":
            self._do_fill(event.x, event.y)
            return

        if self.tool == "polygon":
            # 按下左键 = 拖拽起点，开始拉伸预设形状
            self._poly_drag_origin = (event.x, event.y)
            self._poly_dragging = True
            self.canvas.itemconfigure("empty_hint", state="hidden")
            return

        # ---- 画笔 ----
        self._drawing = True
        self.current_stroke = [(event.x, event.y)]
        self._last_xy = (event.x, event.y)
        self.canvas.itemconfigure("empty_hint", state="hidden")

    def _on_drag(self, event):
        x, y = event.x, event.y

        if self.tool == "polygon":
            if self._poly_dragging and self._poly_drag_origin:
                ox, oy = self._poly_drag_origin
                self._draw_poly_preview(ox, oy, x, y)
            return

        if self.tool != "pen" or not self._drawing:
            return

        lx, ly = self._last_xy
        self.canvas.create_line(lx, ly, x, y, fill=self.pen_color,
                                width=self.brush_size,
                                capstyle="round", joinstyle="round",
                                smooth=True, tags="ink")
        self.current_stroke.append((x, y))
        self._last_xy = (x, y)

    def _on_release(self, event):
        # ---- 多边形：松开完成绘制 ----
        if self.tool == "polygon":
            if self._poly_dragging and self._poly_drag_origin:
                ox, oy = self._poly_drag_origin
                self._poly_commit(ox, oy, event.x, event.y)
            self._poly_dragging = False
            self._poly_drag_origin = None
            return

        if self.tool != "pen" or not self._drawing:
            return
        self._drawing = False
        if self.current_stroke:
            if len(self.current_stroke) == 1:
                x, y = self.current_stroke[0]
                r = max(1, self.brush_size / 2)
                self.canvas.create_oval(x - r, y - r, x + r, y + r,
                                        fill=self.pen_color,
                                        outline=self.pen_color, tags="ink")
            self._cur_strokes().append({
                "pts": list(self.current_stroke),
                "color": self.pen_color,
                "width": self.brush_size,
            })
        self.current_stroke = []
        self._last_xy = None
        if self.view_mode:
            self._draw_axes()

    def _on_right(self, event):
        """右键：取消当前操作"""
        self._cancel_pending()

    def _on_wheel(self, event):
        delta = 1 if event.delta > 0 else -1
        new = max(1, min(30, self.brush_size + delta))
        self.brush_size = new
        try:
            self.scale_size.set(new)
        except Exception:
            pass

    def _toggle_fullscreen(self, event=None):
        self._fullscreen = not self._fullscreen
        try:
            self.attributes("-fullscreen", self._fullscreen)
        except Exception:
            pass

    def _on_esc(self, event=None):
        if self._fullscreen:
            self._toggle_fullscreen()
        elif self._poly_dragging:
            self._poly_dragging = False
            self._poly_drag_origin = None
            self.canvas.delete("poly_temp")
        elif self.tool != "pen":
            self.set_tool("pen")

    def _center(self):
        try:
            self.update_idletasks()
            w, h = self.winfo_width(), self.winfo_height()
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            self.geometry(f"+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2 - 30)}")
        except Exception:
            pass

    # ==================== 操作 ====================
    def undo(self):
        st = self._cur_strokes()
        tx = self._cur_texts()
        fl = self._cur_fills()
        # 优先撤销最近的操作：填充 > 文字 > 笔迹
        if fl and (not st or len(fl) >= 1):
            fl.pop()
        elif tx:
            tx.pop()
        elif st:
            st.pop()
        self._redraw()
        if self.view_mode:
            self._draw_axes()

    def clear_all(self):
        st = self._cur_strokes()
        vname = VIEW_NAMES[self.current_view] if self.view_mode else ""
        msg = f"确定要清空{('「' + vname + '」') if vname else ''}的全部内容吗？"
        if (st or self._cur_texts() or self._cur_fills()) and \
                not messagebox.askyesno("清空", msg, parent=self):
            return
        st.clear()
        self._cur_texts().clear()
        self._cur_fills().clear()
        self._poly_dragging = False
        self._poly_drag_origin = None
        self.canvas.delete("poly_temp")
        self._redraw()
        if self.view_mode:
            self._draw_axes()

    def _redraw(self):
        self.canvas.delete("ink")
        self.canvas.delete("txt")
        self.canvas.delete("fillimg")
        st = self._cur_strokes()
        tx = self._cur_texts()
        fl = self._cur_fills()

        if not st and not tx and not fl:
            self.canvas.itemconfigure("empty_hint", state="normal")
            if self.view_mode:
                self.canvas.itemconfigure(
                    "empty_hint",
                    text=f"在这里绘制「{VIEW_NAMES[self.current_view]}」\n\n"
                         f"（贯穿部分用红色画笔）")
            else:
                self.canvas.itemconfigure(
                    "empty_hint",
                    text="在这里画你的零件草图\n\n（按住左键拖动即可绘制）")
            self._fill_photo = None
            return

        self.canvas.itemconfigure("empty_hint", state="hidden")

        # ---- 填充层（一张合成图，压在最底层）----
        if fl:
            self._render_fill_layer()
        else:
            self._fill_photo = None

        # ---- 再画笔迹（压在填充上面）----
        for s in st:
            pts = s["pts"]
            color = s.get("color", INK)
            width = s.get("width", 3)
            if len(pts) == 1:
                x, y = pts[0]
                r = max(1, width / 2)
                self.canvas.create_oval(x - r, y - r, x + r, y + r,
                                        fill=color, outline=color, tags="ink")
            else:
                for i in range(len(pts) - 1):
                    x1, y1 = pts[i]
                    x2, y2 = pts[i + 1]
                    self.canvas.create_line(x1, y1, x2, y2, fill=color,
                                            width=width,
                                            capstyle="round", joinstyle="round",
                                            smooth=True, tags="ink")

        # ---- 文字 ----
        for t in tx:
            x, y = t["pos"]
            self.canvas.create_text(
                x, y, text=t["text"], anchor="nw",
                font=("Microsoft YaHei UI", t.get("size", 14)),
                fill=t.get("color", INK), tags="txt")

    def has_content(self):
        if self.view_mode:
            return any(self.views[v] for v in self.views)
        return bool(self.strokes)

    # ==================== 导出 ====================
    def finish(self):
        self._cancel_pending()

        if self.view_mode:
            self._finish_three_views()
        else:
            self._finish_single()

    def _finish_single(self):
        if not self.strokes:
            messagebox.showwarning("画布是空的",
                                   "请先在画布上绘制草图，再点「画好了！」",
                                   parent=self)
            return
        path = os.path.join(tempfile.gettempdir(),
                            f"sketch_{int(time.time())}.png")
        if not self._export_plain(self.strokes, self.texts, path,
                                  fills=self.fills):
            messagebox.showerror("导出失败", "无法生成图片", parent=self)
            return
        self.result_path = path
        self.result_paths = [path]
        if self.on_done:
            try:
                self.on_done(path)
            except Exception as e:
                print("回调失败:", e)
        self.destroy()

    def _finish_three_views(self):
        """三视图：导出三张图，每张右下角标注视图名"""
        missing = [VIEW_NAMES[v] for v in (VIEW_FRONT, VIEW_SIDE, VIEW_TOP)
                   if not self.views[v]]
        if missing:
            messagebox.showwarning(
                "还有视图没画",
                "以下视图还是空的：\n\n　" + "、".join(missing) +
                "\n\n请把它们都画完（点上方按钮切换视图）。",
                parent=self)
            return

        ts = int(time.time())
        paths = {}
        for vid in (VIEW_FRONT, VIEW_SIDE, VIEW_TOP):
            p = os.path.join(tempfile.gettempdir(), f"sketch_{vid}_{ts}.png")
            if not self._export_annotated(
                    self.views[vid], self.view_texts[vid],
                    p, VIEW_NAMES[vid], fills=self.view_fills[vid]):
                messagebox.showerror("导出失败",
                                     f"导出「{VIEW_NAMES[vid]}」失败", parent=self)
                return
            paths[vid] = p

        self.result_paths = [paths[VIEW_FRONT], paths[VIEW_SIDE], paths[VIEW_TOP]]
        self.result_path = self.result_paths[0]

        if self.on_done:
            try:
                self.on_done(self.result_paths)
            except Exception as e:
                print("回调失败:", e)
        self.destroy()

    # ---------------- 导出实现 ----------------
    def _content_bounds(self, strokes, texts):
        """计算所有内容的外框"""
        xs, ys = [], []
        for s in strokes:
            for (x, y) in s["pts"]:
                xs.append(x)
                ys.append(y)
        for t in texts:
            xs.append(t["pos"][0])
            ys.append(t["pos"][1])
            # 粗略估算文字宽度
            xs.append(t["pos"][0] + len(t["text"]) * t.get("size", 14))
            ys.append(t["pos"][1] + t.get("size", 14) * 1.4)
        return xs, ys
    def _compute_fill_image(self, strokes, fills):
        """
        生成填充层图像（整画布大小，白底 + 彩色填充区域）。

        用 PIL 的 floodfill 实现：先把线条画成黑色障碍，
        再从种子点 floodfill 成目标颜色。
        """
        try:
            from PIL import Image, ImageDraw
        except Exception:
            return None

        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())

        img = Image.new("RGB", (cw, ch), (255, 255, 255))
        d = ImageDraw.Draw(img)

        # 1. 把线条画成黑色边界
        for s in strokes:
            pts = s["pts"]
            w = max(2, int(s.get("width", 3)))
            if len(pts) == 1:
                px, py = pts[0]
                d.ellipse([px - w, py - w, px + w, py + w], fill=(0, 0, 0))
            else:
                d.line([(p[0], p[1]) for p in pts], fill=(0, 0, 0),
                       width=w, joint="curve")

        # 2. 逐个填充
        for f in fills:
            seed = (int(f["seed"][0]), int(f["seed"][1]))
            rgb = self._hex_to_rgb(f.get("color", INK))
            if not (0 <= seed[0] < cw and 0 <= seed[1] < ch):
                continue
            try:
                ImageDraw.floodfill(img, seed, rgb, thresh=10)
            except Exception:
                continue

        # 3. 把黑色边界还原成干净的颜色（线条本身由 strokes 单独画）
        return img

    def _export_plain(self, strokes, texts, path, fills=None):
        """导出（不标注）"""
        return self._render(strokes, texts, path, label=None, fills=fills)

    def _export_annotated(self, strokes, texts, path, label, fills=None):
        """导出并在右下角标注视图名"""
        return self._render(strokes, texts, path, label=label, fills=fills)

    def _render(self, strokes, texts, path, label=None, fills=None):
        """
        渲染成 PNG。

        参数：
            strokes: [{"pts":[(x,y)...], "color":..., "width":...}, ...]
            texts:   [{"pos":(x,y), "text":..., "color":..., "size":...}, ...]
            fills:   [{"seed":(x,y), "color":...}, ...]  填充区域
            label:   右下角标注文字（None 则不标注）
        """
        try:
            from PIL import Image, ImageDraw

            fills = fills or []
            xs, ys = self._content_bounds(strokes, texts)
            if not xs:
                return False

            pad = 40
            cw_max = max(400, self.canvas.winfo_width())
            ch_max = max(300, self.canvas.winfo_height())

            x0 = max(0, int(min(xs)) - pad)
            y0 = max(0, int(min(ys)) - pad)
            x1 = min(cw_max, int(max(xs)) + pad)
            y1 = min(ch_max, int(max(ys)) + pad)

            cw = max(60, x1 - x0)
            ch = max(60, y1 - y0)

            img = Image.new("RGB", (cw, ch), (255, 255, 255))
            draw = ImageDraw.Draw(img)

            # ---- 1. 先画填充（垫底）----
            if fills:
                fimg = self._compute_fill_image(strokes, fills)
                if fimg is not None:
                    # fimg 是整画布大小，裁出需要的区域
                    fw, fh = fimg.size
                    cx0 = max(0, min(fw, x0))
                    cy0 = max(0, min(fh, y0))
                    cx1 = max(cx0, min(fw, x1))
                    cy1 = max(cy0, min(fh, y1))
                    if cx1 > cx0 and cy1 > cy0:
                        crop = fimg.crop((cx0, cy0, cx1, cy1))
                        img.paste(crop, (cx0 - x0, cy0 - y0))

            # ---- 2. 画笔迹 ----
            for s in strokes:
                pts = s["pts"]
                color = s.get("color", INK)
                width = max(1, int(s.get("width", 3)))
                rgb = self._hex_to_rgb(color)

                if len(pts) == 1:
                    x, y = pts[0]
                    r = max(1, width // 2)
                    draw.ellipse([x - x0 - r, y - y0 - r,
                                  x - x0 + r, y - y0 + r], fill=rgb)
                else:
                    shifted = [(px - x0, py - y0) for px, py in pts]
                    draw.line(shifted, fill=rgb, width=width, joint="curve")
                    for (ex, ey) in (shifted[0], shifted[-1]):
                        r = width / 2
                        draw.ellipse([ex - r, ey - r, ex + r, ey + r], fill=rgb)

            # ---- 画文字 ----
            font = self._load_font(14)
            for t in texts:
                tx, ty = t["pos"]
                fs = t.get("size", 14)
                f = self._load_font(fs)
                draw.text((tx - x0, ty - y0), t["text"],
                          fill=self._hex_to_rgb(t.get("color", INK)), font=f)

            # ---- 右下角标注视图名 ----
            if label:
                self._draw_label(draw, cw, ch, label)

            img.save(path, "PNG")
            return True
        except Exception as e:
            print("导出失败:", e)
            import traceback
            traceback.print_exc()
            return False

    def _draw_label(self, draw, cw, ch, label):
        """在图片右下角画一个带边框的视图名标签"""
        try:
            from PIL import ImageFont

            fs = max(18, min(30, cw // 16))
            font = self._load_font(fs, bold=True)

            # 文字尺寸
            bbox = draw.textbbox((0, 0), label, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]

            padx, pady = 12, 6
            box_w = tw + padx * 2
            box_h = th + pady * 2
            margin = 14

            bx0 = cw - box_w - margin
            by0 = ch - box_h - margin

            # 半透明白底 + 灰边框
            draw.rectangle([bx0, by0, bx0 + box_w, by0 + box_h],
                           fill=(255, 255, 255), outline=(150, 155, 165),
                           width=2)
            # 左侧色条（视觉标识）
            draw.rectangle([bx0, by0, bx0 + 5, by0 + box_h],
                           fill=(31, 111, 235))

            draw.text((bx0 + padx + 4 - bbox[0], by0 + pady - bbox[1]),
                      label, fill=(20, 20, 20), font=font)
        except Exception as e:
            print("标注失败:", e)

    def _load_font(self, size, bold=False):
        """加载中文字体"""
        try:
            from PIL import ImageFont
        except Exception:
            return None

        names = [
            "msyhbd.ttc" if bold else "msyh.ttc",
            "msyh.ttc",
            "simhei.ttf",
            "simsun.ttc",
        ]
        roots = [
            r"C:\Windows\Fonts",
            os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
        ]
        for r in roots:
            for n in names:
                p = os.path.join(r, n)
                if os.path.exists(p):
                    try:
                        return ImageFont.truetype(p, size)
                    except Exception:
                        continue
        try:
            return ImageFont.load_default()
        except Exception:
            return None

    @staticmethod
    def _hex_to_rgb(h):
        h = h.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
