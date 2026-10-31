# -*- coding: utf-8 -*-
"""
assembly.py — 组装零件页面
===========================
流程：
  1. 上传多个零件文件（按钮选择 / 拖拽）
  2. 每个文件显示 3D 预览缩略图，可单独删除
  3. 点「开始组装！」打开 3D 组装界面

3D 组装界面：
  · 下方是零件托盘（拖拽源）
  · 中央是组装区（放置目标）
  · 从托盘拖到组装区，零件自动 3D 显示并可移动
  · 右键拖拽空白处旋转视角（零件随之旋转）
  · 左下角显示坐标系
"""
import os
import math
import time
import tkinter as tk
from tkinter import filedialog, messagebox
import threading

import config as cfg
import part_reader

# 配色（从 app 模块动态取，这里用函数读取最新值）
def _T():
    """取当前主题的配色"""
    import app as A
    return {
        "BG": A.C_BG, "CARD": A.C_CARD, "TEXT": A.C_TEXT,
        "SUB": A.C_SUB, "BORDER": A.C_BORDER, "INPUT": A.C_INPUT_BG,
        "PRIMARY": A.C_PRIMARY, "PRIMARY_D": A.C_PRIMARY_D,
        "OK": A.C_OK, "ERR": A.C_ERR, "PANEL": A.C_PANEL,
        "HOVER": A.C_HOVER, "PLACE": A.C_PLACEHOLDER,
    }

FONT = ("Microsoft YaHei UI", 10)
FONT_S = ("Microsoft YaHei UI", 9)
FONT_XL = ("Microsoft YaHei UI", 20, "bold")
FONT_L = ("Microsoft YaHei UI", 14, "bold")


# ==================== 3D 数学 ====================
class Camera:
    """
    简单的 3D 相机：球坐标 + 正交投影。

    旋转：yaw（水平）、pitch（俯仰）
    投影：把 3D 点映射到 2D 屏幕坐标
    """

    def __init__(self):
        self.yaw = math.radians(45)      # 水平角
        self.pitch = math.radians(25)    # 俯仰角
        self.zoom = 1.0
        self.cx = 0.0                    # 屏幕中心
        self.cy = 0.0
        self.scale = 1.0                 # 像素 / 毫米

    def rotate(self, p):
        """把世界坐标旋转到相机坐标"""
        x, y, z = p
        # 先绕 Y 轴转 yaw
        ca, sa = math.cos(self.yaw), math.sin(self.yaw)
        x1 = x * ca - z * sa
        z1 = x * sa + z * ca
        # 再绕 X 轴转 pitch
        cb, sb = math.cos(self.pitch), math.sin(self.pitch)
        y2 = y * cb - z1 * sb
        z2 = y * sb + z1 * cb
        return x1, y2, z2

    def project(self, p):
        """3D → 屏幕 (x, y, depth)"""
        x1, y2, z2 = self.rotate(p)
        sx = self.cx + x1 * self.scale
        sy = self.cy - y2 * self.scale
        return sx, sy, z2

    def depth_of(self, p):
        return self.rotate(p)[2]


# ==================== 3D 画布 ====================
class Viewer3D(tk.Canvas):
    """
    3D 渲染画布。

    交互：
      · 左键点零件 = 选中
      · 左键拖零件 = 在水平面 (XZ) 里移动
      · 滚轮 = 缩放相机
      · 右键拖 = 旋转视角
      · Ctrl + 上下方向键 / Shift+滚轮 = 等比缩放选中的零件
    """

    def __init__(self, master, on_change=None, **kw):
        super().__init__(master, bg=_T()["INPUT"], highlightthickness=0, **kw)
        self.on_change = on_change
        self.cam = Camera()
        self.items = []      # 已放置的零件
        self.selected = -1   # 当前选中的零件索引
        self._drag_rot = None
        self._drag_item = None    # 正在拖动的零件
        self._drag_start = None
        self._photos = []

        self.bind("<ButtonPress-3>", self._start_rot)
        self.bind("<B3-Motion>", self._do_rot)
        self.bind("<ButtonRelease-3>", self._end_rot)
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Configure>", lambda e: self.redraw())

        # 左键：选中 + 拖动
        self.bind("<ButtonPress-1>", self._on_left_press)
        self.bind("<B1-Motion>", self._on_left_drag)
        self.bind("<ButtonRelease-1>", self._on_left_release)

        # 键盘缩放
        self.bind("<Up>", lambda e: self.scale_selected(1.1))
        self.bind("<Down>", lambda e: self.scale_selected(1 / 1.1))
        self.bind("<Control-Up>", lambda e: self.scale_selected(1.25))
        self.bind("<Control-Down>", lambda e: self.scale_selected(1 / 1.25))
        self.configure(takefocus=1)

    # ---------- 相机操作 ----------
    def _start_rot(self, e):
        self._drag_rot = (e.x, e.y, self.cam.yaw, self.cam.pitch)
        self.config(cursor="fleur")

    def _do_rot(self, e):
        if not self._drag_rot:
            return
        x0, y0, yaw0, pitch0 = self._drag_rot
        self.cam.yaw = yaw0 + (e.x - x0) * 0.01
        self.cam.pitch = max(-math.radians(89),
                             min(math.radians(89),
                                 pitch0 + (e.y - y0) * 0.01))
        self.redraw()

    def _end_rot(self, e):
        self._drag_rot = None
        self.config(cursor="")

    def _on_wheel(self, e):
        # Shift + 滚轮 = 缩放选中零件；否则缩放相机
        if (e.state & 0x0001) and self.selected >= 0:
            self.scale_selected(1.08 if e.delta > 0 else 1 / 1.08)
            return
        f = 1.12 if e.delta > 0 else 1 / 1.12
        self.cam.zoom = max(0.1, min(20, self.cam.zoom * f))
        self.redraw()

    # ---------- 左键：选中 / 拖动 ----------
    def _on_left_press(self, e):
        idx = self._pick(e.x, e.y)
        if idx >= 0:
            self.selected = idx
            self._drag_item = idx
            self._drag_start = (e.x, e.y,
                                self.items[idx]["pos"][0],
                                self.items[idx]["pos"][2])
            self.config(cursor="fleur")
            self.focus_set()
            self.redraw()
        else:
            self.selected = -1
            self.redraw()

    def _on_left_drag(self, e):
        if self._drag_item is None or not self._drag_start:
            return
        x0, y0, ox, oz = self._drag_start
        # 屏幕位移 → 世界位移（简单映射）
        k = 1.0 / max(0.01, self.cam.scale)
        # 屏幕 x 对应世界 x（近似），屏幕 y 对应世界 z
        dx = (e.x - x0) * k * math.cos(self.cam.yaw)
        dz = -(e.x - x0) * k * math.sin(self.cam.yaw)
        dz += (e.y - y0) * k
        item = self.items[self._drag_item]
        item["pos"] = (ox + dx, item["pos"][1], oz + dz)
        self.redraw()

    def _on_left_release(self, e):
        if self._drag_item is not None:
            self._drag_item = None
            self._drag_start = None
            self.config(cursor="")
            self._notify()

    def _notify(self):
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    def _pick(self, sx, sy, tol=26):
        """屏幕坐标 → 最靠近的零件索引（按屏幕距离判断）"""
        best = -1
        bestd = tol
        for i, it in enumerate(self.items):
            if not it["tris"]:
                continue
            ox, oy, oz = it["pos"]
            s = it.get("scale", 1.0)
            # 用零件包围盒中心作为拾取点
            xs, ys, zs = [], [], []
            for (a, b, c) in it["tris"][:120]:
                for v in (a, b, c):
                    xs.append(v[0] * s + ox)
                    ys.append(v[1] * s + oy)
                    zs.append(v[2] * s + oz)
            if not xs:
                continue
            cx = (min(xs) + max(xs)) / 2
            cy = (min(ys) + max(ys)) / 2
            cz = (min(zs) + max(zs)) / 2
            px, py, _ = self.cam.project((cx, cy, cz))
            d = math.hypot(px - sx, py - sy)
            if d < bestd:
                bestd = d
                best = i
        return best

    # ---------- 零件管理 ----------
    def add_part(self, part, pos=(0, 0, 0), color=None):
        """把一个零件加入场景"""
        name = part.get("name", "part")
        palette = [
            (110, 135, 180), (180, 130, 110), (120, 170, 130),
            (170, 130, 175), (185, 165, 110), (120, 155, 185),
        ]
        if color is None:
            color = palette[len(self.items) % len(palette)]
        self.items.append({
            "tris": part.get("triangles") or [],
            "pos": pos,
            "color": color,
            "name": name,
            "bbox": part.get("bbox"),
            "part": part,
            "scale": 1.0,          # 等比缩放
            "orig_scale": 1.0,
        })
        self.selected = len(self.items) - 1
        self.redraw()
        self._notify()
        return len(self.items) - 1

    def scale_selected(self, factor):
        """等比缩放当前选中的零件（不改形状，只改大小）"""
        if not (0 <= self.selected < len(self.items)):
            return
        it = self.items[self.selected]
        ns = it.get("scale", 1.0) * factor
        ns = max(0.05, min(50.0, ns))
        it["scale"] = ns
        self.redraw()
        self._notify()

    def remove_selected(self):
        if 0 <= self.selected < len(self.items):
            self.items.pop(self.selected)
            self.selected = -1
            self.redraw()
            self._notify()

    def clear_all(self):
        self.items = []
        self.selected = -1
        self.redraw()
        self._notify()


    # ---------- 渲染 ----------
    def _scene_bounds(self):
        """所有零件的世界包围盒（考虑等比缩放）"""
        xs, ys, zs = [], [], []
        for it in self.items:
            ox, oy, oz = it["pos"]
            s = it.get("scale", 1.0)
            for (a, b, c) in it["tris"]:
                for v in (a, b, c):
                    xs.append(v[0] * s + ox)
                    ys.append(v[1] * s + oy)
                    zs.append(v[2] * s + oz)
        if not xs:
            return None
        return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))

    def redraw(self):
        self.delete("all")
        W = max(1, self.winfo_width())
        H = max(1, self.winfo_height())
        t = _T()

        # 网格背景
        self._draw_grid(W, H, t)

        if not self.items:
            self.cam.cx = W / 2
            self.cam.cy = H / 2
            self.create_text(W / 2, H / 2,
                             text="把下方的零件拖到这里",
                             font=FONT_L, fill=t["PLACE"])
            self._draw_axes(W, H, t)
            return

        # 自动缩放 + 居中
        b = self._scene_bounds()
        center = (0.0, 0.0, 0.0)
        if b:
            ex = b[1] - b[0]
            ey = b[3] - b[2]
            ez = b[5] - b[4]
            span = max(ex, ey, ez, 1.0)
            self.cam.scale = min(W, H) * 0.55 / span * self.cam.zoom
            # 场景中心（用来把模型搬到屏幕正中）
            center = ((b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2)

        # 把相机中心设成「场景中心投影后的位置」的相反数，
        # 这样场景中心就落在屏幕中心
        cxs, cys, _ = self.cam.rotate(center)[0], self.cam.rotate(center)[1], 0
        self.cam.cx = W / 2 - cxs * self.cam.scale
        self.cam.cy = H / 2 + cys * self.cam.scale

        # 收集所有三角形（含世界坐标，应用等比缩放）
        faces = []
        for idx, it in enumerate(self.items):
            ox, oy, oz = it["pos"]
            s = it.get("scale", 1.0)
            sel = (idx == self.selected)
            for (a, bb, c) in it["tris"]:
                p0 = (a[0] * s + ox, a[1] * s + oy, a[2] * s + oz)
                p1 = (bb[0] * s + ox, bb[1] * s + oy, bb[2] * s + oz)
                p2 = (c[0] * s + ox, c[1] * s + oy, c[2] * s + oz)
                d = (self.cam.depth_of(p0) + self.cam.depth_of(p1)
                     + self.cam.depth_of(p2)) / 3.0
                faces.append((d, p0, p1, p2, it["color"], sel))

        # 远的先画
        faces.sort(key=lambda x: x[0])

        # 光照
        lx, ly, lz = 0.35, 0.65, 0.68
        ln = math.sqrt(lx * lx + ly * ly + lz * lz)
        lx, ly, lz = lx / ln, ly / ln, lz / ln

        for (d, p0, p1, p2, base, sel) in faces:
            ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
            vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
            nx = uy * vz - uz * vy
            ny = uz * vx - ux * vz
            nz = ux * vy - uy * vx
            nn = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            nx, ny, nz = nx / nn, ny / nn, nz / nn

            lam = abs(nx * lx + ny * ly + nz * lz)
            shade = 0.35 + 0.65 * lam
            # 选中的零件整体提亮，方便辨认
            if sel:
                shade = min(1.35, shade * 1.35)
            col = "#%02x%02x%02x" % tuple(
                max(0, min(255, int(ch * shade))) for ch in base)

            s0 = self.cam.project(p0)
            s1 = self.cam.project(p1)
            s2 = self.cam.project(p2)
            self.create_polygon(s0[0], s0[1], s1[0], s1[1], s2[0], s2[1],
                               fill=col, outline=col)

        # 选中零件的说明
        if 0 <= self.selected < len(self.items):
            it = self.items[self.selected]
            sc = it.get("scale", 1.0)
            txt = f"已选中：{it['name']}"
            if abs(sc - 1.0) > 1e-6:
                txt += f"   缩放 {sc * 100:.0f}%（{sc:.3f}×）"
            self.create_text(W / 2, 22, text=txt,
                             font=FONT_S, fill="#4A7CFF")

        self._draw_axes(W, H, t)

    def _draw_grid(self, W, H, t):
        """淡网格背景"""
        step = 40
        col = "#2A2E36" if t["BG"].lower() < "#808080" else "#F0F2F6"
        for x in range(0, W, step):
            self.create_line(x, 0, x, H, fill=col)
        for y in range(0, H, step):
            self.create_line(0, y, W, y, fill=col)

    def _draw_axes(self, W, H, t):
        """左下角画坐标系"""
        ox, oy = 60, H - 60
        L = 42
        axes = [
            ("X", (1, 0, 0), "#E5484D"),
            ("Y", (0, 1, 0), "#22A06B"),
            ("Z", (0, 0, 1), "#4A7CFF"),
        ]
        for (name, vec, col) in axes:
            sx, sy, _ = self.cam.project(
                (vec[0] * L / max(1e-6, self.cam.scale) + 0,
                 vec[1] * L / max(1e-6, self.cam.scale) + 0,
                 vec[2] * L / max(1e-6, self.cam.scale) + 0))
            x1, y1, _ = self.cam.project((0, 0, 0))
            # 用相对偏移画
            dx = (sx - x1)
            dy = (sy - y1)
            n = math.sqrt(dx * dx + dy * dy) or 1.0
            ex = ox + dx / n * L
            ey = oy + dy / n * L
            self.create_line(ox, oy, ex, ey, fill=col, width=2,
                             arrow="last", arrowshape=(9, 11, 4))
            self.create_text(ex + (ex - ox) * 0.18, ey + (ey - oy) * 0.18,
                             text=name, font=("Segoe UI", 10, "bold"),
                             fill=col)
        self.create_oval(ox - 3, oy - 3, ox + 3, oy + 3,
                         fill=t["TEXT"], outline="")


# ==================== 视图3D 组装窗口 ====================
class AssemblyWindow(tk.Toplevel):
    """3D 组装界面（独立大窗口）"""

    def __init__(self, parent, parts, app=None):
        super().__init__(parent)
        self.app = app
        self.parts = parts          # [{part_dict, name, ...}]
        self.placed = []            # 已放进组装区的零件
        self._drag_item = None
        self._thumbs = []

        t = _T()
        self.title("3D 组装 — 拖拽零件到中央")
        self.configure(bg=t["BG"])
        self.geometry("1200x820")
        self.minsize(900, 640)

        self._build()
        self.after(100, self._center)

    def _build(self):
        t = _T()

        # 顶部
        top = tk.Frame(self, bg=t["CARD"], height=56)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Frame(top, bg=t["BORDER"], height=1).pack(side="bottom", fill="x")

        tl = tk.Frame(top, bg=t["CARD"])
        tl.pack(side="left", padx=18, pady=10)
        tk.Label(tl, text="🧩", font=("Segoe UI Emoji", 16),
                 bg=t["CARD"], fg=t["TEXT"]).pack(side="left")
        tk.Label(tl, text="3D 组装", font=FONT_L, fg=t["TEXT"],
                 bg=t["CARD"]).pack(side="left", padx=(8, 0))
        tk.Label(tl, text="拖零件到中央　·　左键选中/拖动　·　"
                          "Shift+滚轮 或 ↑↓ 缩放　·　右键拖拽旋转",
                 font=FONT_S, fg=t["SUB"], bg=t["CARD"]).pack(side="left",
                                                             padx=(14, 0))

        tr = tk.Frame(top, bg=t["CARD"])
        tr.pack(side="right", padx=18)

        # 缩放控制
        self.btn_scale_dn = tk.Button(
            tr, text="−", font=("Microsoft YaHei UI", 12, "bold"),
            command=lambda: self.viewer.scale_selected(1 / 1.15),
            bg=t["CARD"], fg=t["TEXT"], activebackground=t["HOVER"],
            relief="flat", bd=0, cursor="hand2", padx=9, pady=1,
            highlightbackground=t["BORDER"], highlightthickness=1)
        self.btn_scale_dn.pack(side="left", padx=(0, 2))

        self.lbl_scale = tk.Label(tr, text="100%", font=FONT_S,
                                  fg=t["SUB"], bg=t["CARD"], width=6)
        self.lbl_scale.pack(side="left")

        self.btn_scale_up = tk.Button(
            tr, text="+", font=("Microsoft YaHei UI", 12, "bold"),
            command=lambda: self.viewer.scale_selected(1.15),
            bg=t["CARD"], fg=t["TEXT"], activebackground=t["HOVER"],
            relief="flat", bd=0, cursor="hand2", padx=9, pady=1,
            highlightbackground=t["BORDER"], highlightthickness=1)
        self.btn_scale_up.pack(side="left", padx=(2, 10))

        self.btn_clear = tk.Button(
            tr, text="清空组装区", font=FONT_S, command=self.clear_scene,
            bg=t["CARD"], fg=t["TEXT"], activebackground=t["HOVER"],
            relief="flat", bd=0, cursor="hand2", padx=12, pady=5,
            highlightbackground=t["BORDER"], highlightthickness=1)
        self.btn_clear.pack(side="left", padx=(0, 8))

        # ★ 完成组装
        self.btn_done = tk.Button(
            tr, text="✅  完成组装", font=FONT,
            command=self.finish_assembly,
            bg=t["OK"], fg="#FFFFFF", activebackground="#1a8a5a",
            activeforeground="#FFFFFF", relief="flat", bd=0,
            cursor="hand2", padx=18, pady=5)
        self.btn_done.pack(side="left", padx=(0, 8))

        self.btn_close = tk.Button(
            tr, text="关闭", font=FONT, command=self.destroy,
            bg=t["CARD"], fg=t["TEXT"], activebackground=t["HOVER"],
            relief="flat", bd=0, cursor="hand2", padx=14, pady=5,
            highlightbackground=t["BORDER"], highlightthickness=1)
        self.btn_close.pack(side="left")

        # 中央 3D
        self.viewer = Viewer3D(self, on_change=self._on_scene_change)
        self.viewer.pack(fill="both", expand=True, padx=12, pady=(10, 0))

        # 下方托盘
        tray_wrap = tk.Frame(self, bg=t["CARD"], height=150)
        tray_wrap.pack(fill="x", side="bottom")
        tray_wrap.pack_propagate(False)
        tk.Frame(tray_wrap, bg=t["BORDER"], height=1).pack(side="top", fill="x")

        head = tk.Frame(tray_wrap, bg=t["CARD"])
        head.pack(fill="x", padx=16, pady=(8, 2))
        tk.Label(head, text="零件托盘", font=FONT_S, fg=t["TEXT"],
                 bg=t["CARD"]).pack(side="left")
        tk.Label(head, text="（按住缩略图拖到上面的画布）", font=("Microsoft YaHei UI", 8),
                 fg=t["SUB"], bg=t["CARD"]).pack(side="left", padx=(6, 0))

        self.tray = tk.Frame(tray_wrap, bg=t["CARD"])
        self.tray.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        self._build_tray()

    def _build_tray(self):
        from PIL import Image, ImageTk
        t = _T()

        for i, item in enumerate(self.parts):
            card = tk.Frame(self.tray, bg=t["PANEL"],
                            highlightbackground=t["BORDER"],
                            highlightthickness=1, cursor="hand2")
            card.pack(side="left", padx=6, pady=4)

            png = item.get("preview_png")
            img_lbl = None
            if png and os.path.exists(png):
                try:
                    im = Image.open(png)
                    im.thumbnail((110, 84))
                    ph = ImageTk.PhotoImage(im)
                    self._thumbs.append(ph)
                    img_lbl = tk.Label(card, image=ph, bg=t["PANEL"])
                    img_lbl.pack(padx=4, pady=(4, 0))
                except Exception:
                    img_lbl = None

            if img_lbl is None:
                tk.Label(card, text="零件", font=FONT_S, fg=t["SUB"],
                         bg=t["PANEL"], width=12, height=4).pack(padx=4, pady=4)

            name = item["part"]["name"]
            if len(name) > 14:
                name = name[:12] + "…"
            tk.Label(card, text=name, font=("Microsoft YaHei UI", 8),
                     fg=t["TEXT"], bg=t["PANEL"]).pack(pady=(2, 4))

            # 拖拽绑定
            for w in ([card] + (list(card.winfo_children()))):
                w.bind("<ButtonPress-1>",
                       lambda e, idx=i: self._drag_start(e, idx))
                w.bind("<B1-Motion>", self._drag_move)
                w.bind("<ButtonRelease-1>", self._drag_end)

    # ---------- 拖拽 ----------
    def _drag_start(self, e, idx):
        self._drag_item = idx
        self.config(cursor="fleur")

    def _drag_move(self, e):
        pass

    def _drag_end(self, e):
        self.config(cursor="")
        if self._drag_item is None:
            return

        # 判断是否落在 3D 画布内
        vx = self.viewer.winfo_rootx()
        vy = self.viewer.winfo_rooty()
        vw = self.viewer.winfo_width()
        vh = self.viewer.winfo_height()
        rx = e.x_root
        ry = e.y_root

        if vx <= rx <= vx + vw and vy <= ry <= vy + vh:
            item = self.parts[self._drag_item]
            part = item["part"]

            if not part.get("triangles"):
                messagebox.showwarning(
                    "无法显示 3D",
                    f"「{part['name']}」没有可用的三角网格数据，无法在 3D 里显示。\n\n"
                    f"{part.get('error') or '文件可能是装配体或不支持的格式。'}",
                    parent=self)
                self._drag_item = None
                return

            # 按已放置数量，围绕原点错开摆放（避免重叠）
            n = len(self.placed)
            ring = [0, 1, 2, 3, 4, 5, 6, 7]
            idx = n % 8
            L = 70
            offsets = [(0, 0), (L, 0), (-L, 0), (0, L),
                       (0, -L), (L, L), (-L, -L), (L, -L)]
            ox, oz = offsets[idx]
            self.viewer.add_part(part, pos=(ox, 0, oz))
            self.placed.append(item)
        self._drag_item = None

    # ---------- 场景变化 ----------
    def _on_scene_change(self):
        """场景内容变化时更新缩放显示"""
        try:
            sel = self.viewer.selected
            if 0 <= sel < len(self.viewer.items):
                sc = self.viewer.items[sel].get("scale", 1.0)
                self.lbl_scale.config(text=f"{sc * 100:.0f}%")
            else:
                self.lbl_scale.config(text="—")
        except Exception:
            pass

    # ---------- 完成组装 ----------
    def finish_assembly(self):
        """导出图纸 + 发给 AI 组装"""
        if not self.viewer.items:
            messagebox.showwarning(
                "组装区是空的",
                "请先把零件拖到中间的组装区，再点「完成组装」。",
                parent=self)
            return

        # 保存图纸
        import blueprint
        t0 = time.time()
        try:
            bdata = blueprint.build_blueprint(
                self.viewer.items, [{"path": it["part"].get("path"),
                                     "part": it["part"]}
                                    for it in self.parts
                                    if it.get("part")])
        except Exception as e:
            messagebox.showerror("生成图纸失败", str(e), parent=self)
            return

        # 图纸路径（和零件放一起）
        out_dir = cfg.get_model_dir()
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception:
            out_dir = os.environ.get("TEMP", ".")

        name = bdata.get("assembly", {}).get("part_count", 0)
        ts = time.strftime("%Y%m%d_%H%M%S")
        bp_path = os.path.join(out_dir, f"组装图纸_{ts}.swbp")
        try:
            blueprint.save_blueprint(bdata, bp_path)
        except Exception as e:
            messagebox.showerror("保存图纸失败", str(e), parent=self)
            return

        n_mod = len(bdata.get("modifications", []))
        # 询问用户是否继续发给 AI
        msg = (f"图纸已保存：\n{bp_path}\n\n"
               f"包含 {name} 个零件")
        if n_mod:
            msg += f"，其中 {n_mod} 个被缩放"
        msg += "\n\n要把这张图纸发给 AI，让它生成装配体吗？"

        if not messagebox.askyesno("完成组装", msg, parent=self):
            try:
                os.startfile(out_dir)
            except Exception:
                pass
            return

        # 关闭组装窗口，进入 AI 流程
        self.app.run_assembly_ai(bdata, bp_path, self.parts, parent=self)

    def clear_scene(self):
        if not self.placed:
            return
        if not messagebox.askyesno("清空", "把组装区里的零件全部移除？",
                                   parent=self):
            return
        self.viewer.clear_all()
        self.placed = []

    def _center(self):
        try:
            self.update_idletasks()
            w, h = self.winfo_width(), self.winfo_height()
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            self.geometry(f"+{max(0,(sw-w)//2)}+{max(0,(sh-h)//2-20)}")
        except Exception:
            pass


# ==================== 组装页面 ====================
class AssemblyPage(tk.Frame):
    """上传零件 → 开始组装的页面"""

    # 支持的扩展名
    EXTS = (".sldprt", ".sldasm", ".step", ".stp", ".igs", ".iges",
            ".x_t", ".x_b", ".sat", ".stl", ".obj")

    def __init__(self, master, app):
        super().__init__(master, bg=_T()["BG"])
        self.app = app
        self.files = []      # [{path, part, preview_png, ok}]
        self._photos = []
        self._dropper = None
        self._busy = False

        self._build()
        self._setup_drop()

    def _build(self):
        t = _T()

        wrap = tk.Frame(self, bg=t["BG"])
        wrap.pack(fill="both", expand=True, padx=36, pady=22)

        top = tk.Frame(wrap, bg=t["BG"])
        top.pack(fill="x")
        self.app._mk_btn(top, "← 返回",
                         lambda: self.app.show_page("choice"),
                         kind="ghost").pack(side="left")

        tk.Label(wrap, text="组装零件", font=FONT_XL, fg=t["TEXT"],
                 bg=t["BG"]).pack(anchor="w", pady=(16, 4))
        tk.Label(wrap,
                 text="上传多个零件文件，然后拖到 3D 组装区里摆放。",
                 font=FONT_S, fg=t["SUB"], bg=t["BG"]).pack(anchor="w",
                                                            pady=(0, 16))

        # ---------- 上传区 ----------
        self.upload_box = tk.Frame(
            wrap, bg=t["INPUT"], height=92,
            highlightbackground=t["BORDER"], highlightthickness=1,
            cursor="hand2")
        self.upload_box.pack(fill="x")
        self.upload_box.pack_propagate(False)

        self.lbl_upload = tk.Label(
            self.upload_box,
            text="📂  上传多个 SolidWorks 文件",
            font=FONT, fg=t["TEXT"], bg=t["INPUT"], cursor="hand2")
        self.lbl_upload.pack(pady=(14, 2))
        tk.Label(self.upload_box,
                 text="其他 CAD 文件也可以（STEP / IGES / STL / OBJ / X_T）\n"
                      "⚠ 多个文件的格式要保持一致，或者把文件拖进来",
                 font=("Microsoft YaHei UI", 8), fg=t["SUB"], bg=t["INPUT"],
                 justify="center").pack()

        for w in (self.upload_box, self.lbl_upload):
            w.bind("<Button-1>", lambda e: self.pick_files())

        # ---------- 已上传文件列表 ----------
        list_head = tk.Frame(wrap, bg=t["BG"])
        list_head.pack(fill="x", pady=(16, 6))
        tk.Label(list_head, text="已上传的零件", font=FONT, fg=t["TEXT"],
                 bg=t["BG"]).pack(side="left")
        self.lbl_count = tk.Label(list_head, text="0 个", font=FONT_S,
                                  fg=t["SUB"], bg=t["BG"])
        self.lbl_count.pack(side="left", padx=(8, 0))

        self.btn_clear = tk.Button(
            list_head, text="全部清除", font=("Microsoft YaHei UI", 8),
            command=self.clear_all,
            bg=t["CARD"], fg=t["SUB"], activebackground=t["HOVER"],
            relief="flat", bd=0, cursor="hand2", padx=10, pady=3,
            highlightbackground=t["BORDER"], highlightthickness=1)
        self.btn_clear.pack(side="right")

        # 卡片容器（可滚动）
        outer = tk.Frame(wrap, bg=t["BG"])
        outer.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(outer, bg=t["BG"], highlightthickness=0)
        sb = tk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.cards = tk.Frame(self.canvas, bg=t["BG"])
        self.cards.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.cards, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas.bind(
            "<MouseWheel>",
            lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))

        self._show_empty_hint()

        # ---------- 底部按钮 ----------
        foot = tk.Frame(wrap, bg=t["BG"])
        foot.pack(fill="x", pady=(12, 0))

        self.btn_start = tk.Button(
            foot, text="🧩  开始组装！", font=FONT,
            command=self.start_assembly,
            bg=t["PRIMARY"], fg="#FFFFFF",
            activebackground=t["PRIMARY_D"], activeforeground="#FFFFFF",
            relief="flat", bd=0, cursor="hand2", padx=26, pady=10)
        self.btn_start.pack(side="left")

        self.lbl_status = tk.Label(foot, text="", font=FONT_S,
                                   fg=t["SUB"], bg=t["BG"])
        self.lbl_status.pack(side="left", padx=(14, 0))

    def _show_empty_hint(self):
        t = _T()
        for w in self.cards.winfo_children():
            w.destroy()
        tk.Label(self.cards, text="还没有上传零件", font=FONT_S,
                 fg=t["PLACE"], bg=t["BG"]).pack(anchor="w", pady=20)

    # ---------- 拖放 ----------
    def _setup_drop(self):
        try:
            from filedrop import FileDropTarget
            self._dropper = FileDropTarget(
                self.upload_box,
                on_drop=self._on_drop,
                accept_exts=list(self.EXTS))
        except Exception as e:
            print(f"[组装页拖放] {e}")

    def _on_drop(self, paths):
        self.add_files(paths)

    # ---------- 文件操作 ----------
    def pick_files(self):
        exts = " ".join("*" + e for e in self.EXTS)
        paths = filedialog.askopenfilenames(
            parent=self, title="选择零件文件（可多选）",
            filetypes=[("CAD 零件文件", exts), ("所有文件", "*.*")])
        if paths:
            self.add_files(list(paths))

    def add_files(self, paths):
        """添加多个文件，后台解析"""
        valid = []
        for p in paths:
            if not os.path.isfile(p):
                continue
            if os.path.splitext(p)[1].lower() not in self.EXTS:
                continue
            if any(f["path"] == p for f in self.files):
                continue    # 去重
            valid.append(p)

        if not valid:
            if paths:
                messagebox.showwarning("没有可用的文件",
                                       "只支持：" + " ".join(self.EXTS),
                                       parent=self)
            return

        self.lbl_status.config(text=f"正在解析 {len(valid)} 个文件…",
                               fg=_T()["PRIMARY"])

        def work():
            results = []
            for p in valid:
                try:
                    part = part_reader.read_part(p)
                    png = None
                    if part["ok"]:
                        png = os.path.join(
                            os.environ.get("TEMP", "."),
                            f"_asm_{abs(hash(p)) % 10**8}.png")
                        part_reader.make_preview_png(part, png)
                    results.append({"path": p, "part": part,
                                    "preview_png": png, "ok": part["ok"]})
                except Exception as e:
                    results.append({
                        "path": p,
                        "part": {"name": os.path.basename(p), "ok": False,
                                 "error": str(e)[:80], "triangles": [],
                                 "bbox": None},
                        "preview_png": None, "ok": False})
            # ★ 线程安全：把结果放进队列，由主线程轮询取走
            self._result_queue.append(results)

        self._result_queue = getattr(self, "_result_queue", [])
        threading.Thread(target=work, daemon=True).start()
        self._poll_results()

    def _poll_results(self):
        """主线程轮询后台结果（避免子线程直接操作 Tk）"""
        q = getattr(self, "_result_queue", [])
        while q:
            results = q.pop(0)
            try:
                self._add_done(results)
            except Exception as e:
                print(f"[组装] 处理结果失败: {e}")
        try:
            if self.winfo_exists():
                self.after(120, self._poll_results)
        except Exception:
            pass

    def _add_done(self, results):
        self.files.extend(results)
        self._refresh_cards()
        ok_n = sum(1 for f in self.files if f["ok"])
        self.lbl_status.config(
            text=f"✓ 已添加 {len(results)} 个（可组装 {ok_n} 个）",
            fg=_T()["OK"])

    def remove_file(self, idx):
        if 0 <= idx < len(self.files):
            self.files.pop(idx)
        self._refresh_cards()

    def clear_all(self):
        if not self.files:
            return
        if not messagebox.askyesno("清除", "清空所有已上传的零件？",
                                   parent=self):
            return
        self.files = []
        self._refresh_cards()

    def _refresh_cards(self):
        from PIL import Image, ImageTk
        t = _T()

        for w in self.cards.winfo_children():
            w.destroy()
        self._photos = []

        self.lbl_count.config(text=f"{len(self.files)} 个")
        ok_n = sum(1 for f in self.files if f["ok"])
        self.btn_start.config(
            state="normal" if ok_n >= 1 else "disabled",
            bg=t["PRIMARY"] if ok_n >= 1 else t["PANEL"],
            fg="#FFFFFF" if ok_n >= 1 else t["PLACE"],
            cursor="hand2" if ok_n >= 1 else "")

        if not self.files:
            self._show_empty_hint()
            return

        row = None
        for i, f in enumerate(self.files):
            if i % 4 == 0:
                row = tk.Frame(self.cards, bg=t["BG"])
                row.pack(fill="x", pady=4)

            card = tk.Frame(row, bg=t["PANEL"],
                            highlightbackground=t["BORDER"],
                            highlightthickness=1)
            card.pack(side="left", padx=(0, 10), pady=4)

            # 缩略图
            thumb = tk.Frame(card, bg=t["PANEL"])
            thumb.pack(padx=6, pady=(6, 0))

            shown = False
            if f["preview_png"] and os.path.exists(f["preview_png"]):
                try:
                    im = Image.open(f["preview_png"])
                    im.thumbnail((120, 90))
                    ph = ImageTk.PhotoImage(im)
                    self._photos.append(ph)
                    tk.Label(thumb, image=ph, bg=t["PANEL"]).pack()
                    shown = True
                except Exception:
                    pass
            if not shown:
                tk.Label(thumb, text="×" if not f["ok"] else "零件",
                         font=FONT_S, fg=t["ERR"] if not f["ok"] else t["SUB"],
                         bg=t["PANEL"], width=14, height=5).pack()

            # 删除按钮
            del_btn = tk.Label(thumb, text="×",
                               font=("Microsoft YaHei UI", 9, "bold"),
                               fg="#FFFFFF", bg=t["ERR"], cursor="hand2",
                               padx=4)
            del_btn.place(relx=1.0, rely=0.0, anchor="ne")
            del_btn.bind("<Button-1>", lambda e, idx=i: self.remove_file(idx))

            # 文件名
            nm = f["part"]["name"]
            if len(nm) > 16:
                nm = nm[:14] + "…"
            tk.Label(card, text=nm, font=("Microsoft YaHei UI", 8),
                     fg=t["TEXT"], bg=t["PANEL"]).pack(padx=6, pady=(3, 0))

            # 尺寸信息
            if f["ok"] and f["part"].get("bbox"):
                b = f["part"]["bbox"]
                info = f"{b[0]:.0f}×{b[1]:.0f}×{b[2]:.0f} mm"
            elif not f["ok"]:
                info = f["part"].get("error", "解析失败")[:20]
            else:
                info = "—"
            tk.Label(card, text=info, font=("Microsoft YaHei UI", 7),
                     fg=t["SUB"] if f["ok"] else t["ERR"],
                     bg=t["PANEL"]).pack(padx=6, pady=(0, 6))

    # ---------- 开始组装 ----------
    def start_assembly(self):
        usable = [f for f in self.files if f["ok"] and f["part"].get("triangles")]
        if not usable:
            messagebox.showwarning(
                "没有可组装的零件",
                "至少需要一个能解析出 3D 数据的零件。\n\n"
                "（装配体 .SLDASM 或解析失败的格式无法显示 3D）",
                parent=self)
            return

        # ★ 保存引用，否则窗口可能被垃圾回收导致一闪而过
        self._assembly_win = AssemblyWindow(self, usable, app=self.app)

    # ---------- 生命周期 ----------
    def on_show(self):
        pass
