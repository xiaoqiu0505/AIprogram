# -*- coding: utf-8 -*-
"""
app.py — SolidWorks 零件生成器 主程序
=======================================
浅色系 GUI，流程：
  页面1 主页：左上入口「设计一个小东西吧」+ 右上 API Key
  页面2 选择身份：CAD 学生/工作者  或  我是小白（暂未开放）
  页面3 零件设计：文字描述 / 上传图片 → AI 深度思考 → 自动建模
"""
import os
import sys
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# 让打包后也能找到同目录模块
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
    SRC_DIR = os.path.join(sys._MEIPASS, "src") if hasattr(sys, "_MEIPASS") else BASE_DIR
    for p in (SRC_DIR, BASE_DIR):
        if p not in sys.path:
            sys.path.insert(0, p)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)

import config as cfg
import api_client

# ==================== 配色 ====================
# 浅色（默认）
LIGHT = {
    "C_BG":        "#F7F8FA",
    "C_CARD":      "#FFFFFF",
    "C_PRIMARY":   "#4A7CFF",
    "C_PRIMARY_D": "#3A63D4",
    "C_TEXT":      "#1F2430",
    "C_SUB":       "#6B7280",
    "C_BORDER":    "#E3E6EC",
    "C_INPUT_BG":  "#FBFCFD",
    "C_OK":        "#22A06B",
    "C_ERR":       "#E5484D",
    "C_WARN":      "#E8A33D",
    "C_HOVER":     "#EEF3FF",
    "C_PANEL":     "#F7F9FC",
    "C_DISABLED":  "#F0F1F4",
    "C_ON_PRIMARY": "#FFFFFF",
    "C_TAG_BG":    "#EEF3FF",
    "C_PLACEHOLDER": "#A0A4AD",
}

# 深色
DARK = {
    "C_BG":        "#16181D",
    "C_CARD":      "#22252C",
    "C_PRIMARY":   "#5B8CFF",
    "C_PRIMARY_D": "#4A7CFF",
    "C_TEXT":      "#E8EAED",
    "C_SUB":       "#9AA0AB",
    "C_BORDER":    "#33373F",
    "C_INPUT_BG":  "#1B1E24",
    "C_OK":        "#3DDC97",
    "C_ERR":       "#FF6B6B",
    "C_WARN":      "#F0B44C",
    "C_HOVER":     "#2C313A",
    "C_PANEL":     "#1F2229",
    "C_DISABLED":  "#2A2E36",
    "C_ON_PRIMARY": "#FFFFFF",
    "C_TAG_BG":    "#2C3A55",
    "C_PLACEHOLDER": "#6E7480",
}

# 当前主题（模块级变量，供各控件读取）
C_BG        = LIGHT["C_BG"]
C_CARD      = LIGHT["C_CARD"]
C_PRIMARY   = LIGHT["C_PRIMARY"]
C_PRIMARY_D = LIGHT["C_PRIMARY_D"]
C_TEXT      = LIGHT["C_TEXT"]
C_SUB       = LIGHT["C_SUB"]
C_BORDER    = LIGHT["C_BORDER"]
C_INPUT_BG  = LIGHT["C_INPUT_BG"]
C_OK        = LIGHT["C_OK"]
C_ERR       = LIGHT["C_ERR"]
C_WARN      = LIGHT["C_WARN"]
C_HOVER     = LIGHT["C_HOVER"]
C_PANEL     = LIGHT["C_PANEL"]
C_DISABLED  = LIGHT["C_DISABLED"]
C_TAG_BG    = LIGHT["C_TAG_BG"]
C_PLACEHOLDER = LIGHT["C_PLACEHOLDER"]


def apply_theme(name):
    """切换模块级配色变量，返回主题字典"""
    global C_BG, C_CARD, C_PRIMARY, C_PRIMARY_D, C_TEXT, C_SUB
    global C_BORDER, C_INPUT_BG, C_OK, C_ERR, C_WARN, C_HOVER, C_PANEL
    global C_DISABLED, C_TAG_BG, C_PLACEHOLDER

    pal = DARK if name == "dark" else LIGHT
    C_BG        = pal["C_BG"]
    C_CARD      = pal["C_CARD"]
    C_PRIMARY   = pal["C_PRIMARY"]
    C_PRIMARY_D = pal["C_PRIMARY_D"]
    C_TEXT      = pal["C_TEXT"]
    C_SUB       = pal["C_SUB"]
    C_BORDER    = pal["C_BORDER"]
    C_INPUT_BG  = pal["C_INPUT_BG"]
    C_OK        = pal["C_OK"]
    C_ERR       = pal["C_ERR"]
    C_WARN      = pal["C_WARN"]
    C_HOVER     = pal["C_HOVER"]
    C_PANEL     = pal["C_PANEL"]
    C_DISABLED  = pal["C_DISABLED"]
    C_TAG_BG    = pal["C_TAG_BG"]
    C_PLACEHOLDER = pal["C_PLACEHOLDER"]
    return pal

FONT_MAIN = ("Microsoft YaHei UI", 10)
FONT_SM   = ("Microsoft YaHei UI", 9)
FONT_MID  = ("Microsoft YaHei UI", 12)
FONT_LG   = ("Microsoft YaHei UI", 15, "bold")
FONT_XL   = ("Microsoft YaHei UI", 22, "bold")


class RoundedFrame(tk.Frame):
    """带边框的卡片容器"""
    def __init__(self, master, **kw):
        bg = kw.pop("bg", C_CARD)
        super().__init__(master, bg=bg, highlightbackground=C_BORDER,
                         highlightthickness=1, **kw)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SolidWorks 零件生成器")
        self.geometry("1180x740")
        self.minsize(1040, 660)

        # 先读主题并应用（必须在建控件之前）
        try:
            saved = cfg.load_config().get("theme") or "light"
        except Exception:
            saved = "light"
        self.current_theme = saved if saved in ("light", "dark") else "light"
        apply_theme(self.current_theme)

        self.configure(bg=C_BG)

        # 状态
        self.selected_image = None
        self._busy = False
        self._last_spec = None
        self._last_result = None

        self._setup_style()
        self._build_topbar()

        # 页面容器
        self.container = tk.Frame(self, bg=C_BG)
        self.container.pack(fill="both", expand=True)

        self.pages = {}
        self._create_pages()
        self.show_page("home")

    # ---------------- 样式 ----------------
    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TNotebook", background=C_BG, borderwidth=0)
        style.configure("TProgressbar", troughcolor=C_BORDER,
                        background=C_PRIMARY, borderwidth=0)

    # ---------------- 顶栏 ----------------
    def _build_topbar(self):
        bar = tk.Frame(self, bg=C_CARD, height=64)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Frame(bar, bg=C_BORDER, height=1).pack(side="bottom", fill="x")

        # 左：Logo
        left = tk.Frame(bar, bg=C_CARD)
        left.pack(side="left", padx=20)
        tk.Label(left, text="◆", font=("Segoe UI", 18), fg=C_PRIMARY,
                 bg=C_CARD).pack(side="left")
        tk.Label(left, text="零件生成器", font=FONT_LG, fg=C_TEXT,
                 bg=C_CARD).pack(side="left", padx=(8, 0))
        tk.Label(left, text="AI × SolidWorks", font=FONT_SM, fg=C_SUB,
                 bg=C_CARD).pack(side="left", padx=(10, 0))

        # 右：API Key 管理按钮
        right = tk.Frame(bar, bg=C_CARD)
        right.pack(side="right", padx=16)

        self.key_entries = {}
        self.key_status = {}

        # 当前使用的模型状态
        self.lbl_current = tk.Label(right, text="", font=FONT_SM,
                                    fg=C_SUB, bg=C_CARD)
        self.lbl_current.pack(side="left", padx=(0, 10))

        self.btn_keys = tk.Button(
            right, text="🔑  填写你的 API Key", font=FONT_MAIN,
            command=self.open_key_dialog,
            bg=C_PRIMARY, fg="#FFFFFF",
            activebackground=C_PRIMARY_D, activeforeground="#FFFFFF",
            relief="flat", bd=0, cursor="hand2", padx=18, pady=8)
        self.btn_keys.pack(side="left")
        self.btn_keys.bind("<Enter>", lambda e: self.btn_keys.config(bg=C_PRIMARY_D))
        self.btn_keys.bind("<Leave>", lambda e: self.btn_keys.config(bg=C_PRIMARY))

        # 深色模式切换按钮
        self.btn_theme = tk.Button(
            right, text=("☀ 浅色" if self.current_theme == "dark" else "🌙 深色"),
            font=FONT_SM, command=self.toggle_theme,
            bg=C_CARD, fg=C_TEXT,
            activebackground=C_HOVER, activeforeground=C_TEXT,
            relief="flat", bd=0, cursor="hand2", padx=12, pady=6,
            highlightbackground=C_BORDER, highlightthickness=1)
        self.btn_theme.pack(side="left", padx=(0, 8))

        self._refresh_key_status()

    # ---------------- 主题切换 ----------------
    def toggle_theme(self):
        """浅色 <-> 深色（建模进行中禁止切换）"""
        # ★ 关键保护：建模/导出进行中不能重建界面，
        #   否则后台线程会往已销毁的控件写数据，导致界面错乱
        if getattr(self, "_busy", False):
            self._show_busy_hint()
            return

        new = "dark" if self.current_theme == "light" else "light"
        self.set_theme(new)

    def _show_busy_hint(self):
        """提示当前正忙，不能切换主题"""
        try:
            messagebox.showinfo(
                "正在处理中",
                "AI 正在思考或建模，这会儿不能切换深浅色。\n\n"
                "请等这一步完成后再切换（只需几秒到一分钟）。")
        except Exception:
            pass

    def set_theme(self, name):
        """应用主题并重建界面"""
        if getattr(self, "_busy", False):
            self._show_busy_hint()
            return

        self.current_theme = name

        # 保存到配置
        try:
            d = cfg.load_config()
            d["theme"] = name
            cfg.save_config(d)
        except Exception:
            pass

        # 切换配色
        apply_theme(name)

        # 重建全部界面（配色是模块级变量，控件创建时读取）
        self._rebuild_ui()

    def _rebuild_ui(self):
        """按当前主题重建整个界面"""
        # ★ 双保险：忙的时候绝不重建
        if getattr(self, "_busy", False):
            self._show_busy_hint()
            return

        # 记住当前页面
        cur_page = "home"
        for nm, p in getattr(self, "pages", {}).items():
            if p.winfo_ismapped():
                cur_page = nm
                break

        # 记住设计页的输入内容（防止重建后丢失）
        saved_inputs = None
        try:
            dp = self.pages.get("design")
            if dp is not None:
                saved_inputs = {
                    "image_paths": list(getattr(dp, "image_paths", []) or []),
                    "image_path": getattr(dp, "image_path", None),
                    "image_is_sketch": getattr(dp, "image_is_sketch", False),
                    "image_is_three_view": getattr(dp, "image_is_three_view", False),
                    "desc": dp.get_desc(),
                }
        except Exception:
            saved_inputs = None

        # ★ 记住组装页已上传的零件（同样不能丢）
        saved_assembly = None
        try:
            ap = self.pages.get("assembly")
            if ap is not None:
                saved_assembly = list(getattr(ap, "files", []) or [])
        except Exception:
            saved_assembly = None

        self._rebuilding = True
        try:
            # 销毁旧控件
            for w in self.winfo_children():
                try:
                    w.destroy()
                except Exception:
                    pass
            self.pages = {}

            # 重建
            self.configure(bg=C_BG)
            self._setup_style()
            self._build_topbar()
            self.container = tk.Frame(self, bg=C_BG)
            self.container.pack(fill="both", expand=True)
            self._create_pages()

            # 恢复设计页的输入内容
            if saved_inputs:
                try:
                    dp = self.pages.get("design")
                    if dp is not None:
                        dp.image_paths = saved_inputs["image_paths"]
                        dp.image_path = saved_inputs["image_path"]
                        dp.image_is_sketch = saved_inputs["image_is_sketch"]
                        dp.image_is_three_view = saved_inputs["image_is_three_view"]
                        dp._refresh_images()
                        if saved_inputs["desc"]:
                            dp.set_desc(saved_inputs["desc"])
                except Exception:
                    pass

            # ★ 恢复组装页已上传的零件
            if saved_assembly:
                try:
                    ap = self.pages.get("assembly")
                    if ap is not None:
                        ap.files = saved_assembly
                        ap._refresh_cards()
                except Exception:
                    pass

            try:
                self.show_page(cur_page)
            except Exception:
                self.show_page("home")
        finally:
            self._rebuilding = False

    def open_key_dialog(self):
        """打开 API Key 管理窗口"""
        KeyDialog(self, self)

    def open_path_dialog(self):
        """打开保存路径设置窗口"""
        PathDialog(self, self)

    def _refresh_current_label(self):
        """刷新顶栏「当前模型」显示"""
        pid = self.get_active_provider()
        info = cfg.get_provider_info(pid)
        has_key = bool(cfg.get_api_key(pid))

        if not any(cfg.get_api_key(p) for p in cfg.PROVIDER_ORDER):
            self.lbl_current.config(text="未配置 Key", fg=C_SUB)
        elif has_key:
            mark = "●" if cfg.is_key_verified(pid) else "○"
            color = C_OK if cfg.is_key_verified(pid) else C_WARN
            self.lbl_current.config(
                text=f"{mark} 当前：{info['name']}", fg=color)
        else:
            self.lbl_current.config(text="所选模型未配置", fg=C_WARN)

    # ---------------- Key 状态 ----------------
    def _refresh_key_status(self):
        """刷新状态（顶栏显示 + 弹窗节点）"""
        self._refresh_current_label()

    # ---------------- 控件工具 ----------------
    def _mk_btn(self, parent, text, cmd, width=None, small=False, kind="primary"):
        if kind == "primary":
            bg, fg, hbg = C_PRIMARY, "#FFFFFF", C_PRIMARY_D
        elif kind == "ghost":
            bg, fg, hbg = C_CARD, C_TEXT, C_HOVER
        else:
            bg, fg, hbg = C_CARD, C_TEXT, C_HOVER
        font = FONT_SM if small else FONT_MAIN
        btn = tk.Button(parent, text=text, command=cmd, font=font,
                        bg=bg, fg=fg, activebackground=hbg, activeforeground=fg,
                        relief="flat", cursor="hand2", bd=0,
                        padx=14, pady=6)
        if width:
            btn.config(width=width)
        btn.bind("<Enter>", lambda e: btn.config(bg=hbg))
        btn.bind("<Leave>", lambda e: btn.config(bg=bg))
        return btn

    # ---------------- 页面管理 ----------------
    def _create_pages(self):
        self.pages["home"] = HomePage(self.container, self)
        self.pages["choice"] = ChoicePage(self.container, self)
        self.pages["design"] = DesignPage(self.container, self)
        try:
            from assembly import AssemblyPage
            self.pages["assembly"] = AssemblyPage(self.container, self)
        except Exception as e:
            print(f"[组装页] 加载失败: {e}")

    def show_page(self, name):
        for p in self.pages.values():
            p.pack_forget()
        page = self.pages[name]
        page.pack(fill="both", expand=True)
        if hasattr(page, "on_show"):
            page.on_show()

    # ---------------- 业务逻辑 ----------------
    def get_active_provider(self):
        """取当前使用的服务商 id（从配置读取，弹窗里切换）"""
        pid = cfg.get_active_provider()
        # 如果当前选的没 key，自动切到有 key 的
        if not cfg.get_api_key(pid):
            for alt in cfg.PROVIDER_ORDER:
                if cfg.get_api_key(alt):
                    return alt
        return pid

    def get_api_key(self, provider=None):
        """取指定或当前服务商的 Key"""
        pid = provider or self.get_active_provider()
        return cfg.get_api_key(pid)

    def _set_status(self, text, color=C_SUB):
        """状态提示（显示在顶栏当前模型位置）"""
        if hasattr(self, "lbl_current"):
            self.lbl_current.config(text=text, fg=color)

    def check_key_and_go(self):
        """检查当前服务商的 API Key，有效则进入设计页"""
        pid = self.get_active_provider()
        info = cfg.get_provider_info(pid)
        key = cfg.get_api_key(pid)

        if not key:
            messagebox.showwarning(
                "需要 API Key",
                f"当前使用的 AI 服务是「{info['name']}」，但还没填写它的 API Key。\n\n"
                f"请点右上角「🔑 填写你的 API Key」按钮，填入后保存再继续。")
            return

        # 已校验过且 Key 没变 → 直接进
        if cfg.is_key_verified(pid):
            self.show_page("design")
            return

        # 需要校验
        self._set_status("校验中…", C_PRIMARY)
        self.update_idletasks()

        def work():
            ok, msg = api_client.verify_key(key, pid)
            self.after(0, lambda: done(ok, msg))

        def done(ok, msg):
            if ok:
                cfg.mark_verified(pid)
                self._refresh_key_status()
                self.show_page("design")
            else:
                cfg.clear_verification(pid)
                self._refresh_key_status()
                self.show_page("home")
                messagebox.showerror(
                    f"{info['name']} API Key 无效",
                    f"{msg}\n\n请检查右上角的 Key 是否正确，或前往 "
                    f"{info['doc']} 确认账户状态。")

        threading.Thread(target=work, daemon=True).start()


# ==================== API Key 管理弹窗 ====================
class KeyDialog(tk.Toplevel):
    """
    填写 API Key 的弹窗。
    国内 3 家 + 国外 2 家，每家一个输入框 + 保存/校验按钮。
    底部可选「当前使用」的模型。
    """

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

        self.title("API Key 设置")
        self.configure(bg=C_BG)
        self.resizable(False, False)
        self.transient(parent)

        W, H = 640, 660
        self.geometry(f"{W}x{H}")
        self.minsize(640, 620)
        try:
            parent.update_idletasks()
            px = parent.winfo_rootx() + (parent.winfo_width() - W) // 2
            py = parent.winfo_rooty() + (parent.winfo_height() - H) // 2
            self.geometry(f"+{max(0, px)}+{max(0, py)}")
        except Exception:
            pass

        self.entries = {}
        self.status_lbls = {}
        self._build()

        self.grab_set()          # 模态
        self.focus_force()

    # ---------------- UI ----------------
    def _build(self):
        # 标题栏
        head = tk.Frame(self, bg=C_CARD, height=64)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Frame(head, bg=C_BORDER, height=1).pack(side="bottom", fill="x")

        hleft = tk.Frame(head, bg=C_CARD)
        hleft.pack(side="left", padx=20, pady=12)
        tk.Label(hleft, text="🔑", font=("Segoe UI Emoji", 14),
                 bg=C_CARD, fg=C_TEXT).pack(side="left")
        tk.Label(hleft, text="API Key 设置", font=("Microsoft YaHei UI", 13, "bold"),
                 fg=C_TEXT, bg=C_CARD).pack(side="left", padx=(8, 0))
        tk.Label(hleft, text="填一个就能用", font=("Microsoft YaHei UI", 9),
                 fg=C_SUB, bg=C_CARD).pack(side="left", padx=(10, 0))

        # 内容区（可滚动）
        body = tk.Frame(self, bg=C_BG)
        body.pack(fill="both", expand=True, padx=18, pady=12)

        # 国内
        self._region_block(body, "cn", "🇨🇳  国内模型（无需代理）")
        # 国外
        self._region_block(body, "intl", "🌍  国外模型（需要网络代理）")

        # 底部：当前使用 + 关闭
        foot = tk.Frame(self, bg=C_CARD)
        foot.pack(fill="x", side="bottom")
        tk.Frame(foot, bg=C_BORDER, height=1).pack(fill="x")

        finner = tk.Frame(foot, bg=C_CARD)
        finner.pack(fill="x", padx=18, pady=12)

        tk.Label(finner, text="当前使用", font=("Microsoft YaHei UI", 9),
                 fg=C_SUB, bg=C_CARD).pack(side="left", padx=(0, 8))

        # 只列出已填 Key 的
        self.combo = ttk.Combobox(finner, state="readonly", width=22,
                                  font=("Microsoft YaHei UI", 9))
        self.combo.pack(side="left")
        self.combo.bind("<<ComboboxSelected>>", self._on_switch)
        self._refresh_combo()

        close_btn = tk.Button(finner, text="完成", font=("Microsoft YaHei UI", 10),
                              command=self.close,
                              bg=C_PRIMARY, fg="#FFFFFF",
                              activebackground=C_PRIMARY_D, activeforeground="#FFFFFF",
                              relief="flat", bd=0, cursor="hand2",
                              padx=22, pady=6)
        close_btn.pack(side="right")
        close_btn.bind("<Enter>", lambda e: close_btn.config(bg=C_PRIMARY_D))
        close_btn.bind("<Leave>", lambda e: close_btn.config(bg=C_PRIMARY))

        # ESC 关闭
        self.bind("<Escape>", lambda e: self.close())

    def _region_block(self, parent, region, title):
        """一个区域块"""
        card = tk.Frame(parent, bg=C_CARD, highlightbackground=C_BORDER,
                        highlightthickness=1)
        card.pack(fill="x", pady=(0, 10))

        inner = tk.Frame(card, bg=C_CARD)
        inner.pack(fill="x", padx=14, pady=10)

        # 标题
        tk.Label(inner, text=title, font=("Microsoft YaHei UI", 9, "bold"),
                 fg=C_SUB, bg=C_CARD).pack(anchor="w", pady=(0, 8))

        for pid in cfg.REGIONS[region]["providers"]:
            info = cfg.get_provider_info(pid)
            row = tk.Frame(inner, bg=C_CARD)
            row.pack(fill="x", pady=3)

            # 色点 + 名称
            tagf = tk.Frame(row, bg=C_CARD)
            tagf.pack(side="left")
            dot = tk.Canvas(tagf, width=10, height=10, bg=C_CARD,
                            highlightthickness=0)
            dot.create_oval(1, 1, 9, 9, fill=info["color"], outline="")
            dot.pack(side="left", padx=(0, 6))
            lbl = tk.Label(tagf, text=info["name"],
                           font=("Microsoft YaHei UI", 9), fg=C_TEXT,
                           bg=C_CARD, width=9, anchor="w")
            lbl.pack(side="left")

            # 输入框
            ent = tk.Entry(row, font=("Microsoft YaHei UI", 9), width=28,
                           show="●", bg=C_INPUT_BG, fg=C_TEXT, relief="flat",
                           highlightbackground=C_BORDER, highlightthickness=1,
                           insertbackground=C_TEXT)
            ent.pack(side="left", ipady=4, padx=(0, 6))
            saved = cfg.get_api_key(pid)
            if saved:
                ent.insert(0, saved)

            # 显示/隐藏密码
            def toggle(e=ent):
                e.config(show="" if e.cget("show") else "●")
            eye = tk.Button(row, text="👁", font=("Segoe UI Emoji", 8),
                            command=toggle, bg=C_CARD, fg=C_SUB,
                            activebackground=C_HOVER, relief="flat", bd=0,
                            cursor="hand2", padx=4)
            eye.pack(side="left")

            # 保存+校验
            sv = tk.Button(row, text="保存", font=("Microsoft YaHei UI", 8),
                           command=lambda p=pid: self._save(p),
                           bg=C_PRIMARY, fg="#FFFFFF",
                           activebackground=C_PRIMARY_D, activeforeground="#FFFFFF",
                           relief="flat", bd=0, cursor="hand2",
                           padx=10, pady=3)
            sv.pack(side="left", padx=(2, 6))

            # 状态
            st = tk.Label(row, text="", font=("Microsoft YaHei UI", 8),
                          fg=C_SUB, bg=C_CARD, width=11, anchor="w")
            st.pack(side="left")

            self.entries[pid] = ent
            self.status_lbls[pid] = st

            # 提示申请地址
            self._update_status(pid)

            hint = tk.Label(inner, text="", font=("Microsoft YaHei UI", 7),
                            fg=C_PLACEHOLDER, bg=C_CARD)

    def _update_status(self, pid):
        lbl = self.status_lbls[pid]
        if cfg.is_key_verified(pid):
            lbl.config(text="● 已验证", fg=C_OK)
        elif cfg.get_api_key(pid):
            lbl.config(text="○ 待验证", fg=C_WARN)
        else:
            info = cfg.get_provider_info(pid)
            lbl.config(text="未设置", fg="#B0B4BD")

    # ---------------- 操作 ----------------
    def _save(self, pid):
        """保存并校验指定服务商的 Key"""
        info = cfg.get_provider_info(pid)
        ent = self.entries[pid]
        key = ent.get().strip()

        if not key:
            cfg.set_api_key("", provider=pid)
            self._update_status(pid)
            self._refresh_combo()
            self.app._refresh_key_status()
            return

        # 先存
        cfg.set_api_key(key, provider=pid, verified=False)
        self._update_status(pid)

        # 后台校验
        lbl = self.status_lbls[pid]
        lbl.config(text="校验中…", fg=C_PRIMARY)

        def work():
            ok, msg = api_client.verify_key(key, pid)
            # 窗口可能已经关闭，用安全的方式回主线程
            try:
                self.after(0, lambda: done(ok, msg))
            except Exception:
                # 窗口已销毁，仍然完成配置更新
                if ok:
                    cfg.mark_verified(pid)
                else:
                    cfg.clear_verification(pid)

        def done(ok, msg):
            try:
                if ok:
                    cfg.mark_verified(pid)
                    lbl.config(text="● 已验证", fg=C_OK)
                    # 如果是当前选中的，或是第一个可用的，自动设为当前
                    active = cfg.get_active_provider()
                    if not cfg.get_api_key(active) or active == pid:
                        cfg.set_active_provider(pid)
                else:
                    cfg.clear_verification(pid)
                    lbl.config(text="✗ " + msg[:14], fg=C_ERR)
                self._refresh_combo()
                self.app._refresh_key_status()
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _refresh_combo(self):
        """刷新「当前使用」下拉框"""
        items = []
        self._pmap = {}
        for region in ("cn", "intl"):
            rname = cfg.REGIONS[region]["name"]
            for pid in cfg.REGIONS[region]["providers"]:
                if not cfg.get_api_key(pid):
                    continue
                info = cfg.get_provider_info(pid)
                mark = "●" if cfg.is_key_verified(pid) else "○"
                label = f"{mark} {info['name']}（{rname}）"
                items.append(label)
                self._pmap[label] = pid

        self.combo.config(values=items)
        active = cfg.get_active_provider()
        for label, pid in self._pmap.items():
            if pid == active:
                self.combo.set(label)
                break
        else:
            if items:
                self.combo.current(0)

    def _on_switch(self, event=None):
        label = self.combo.get()
        pid = getattr(self, "_pmap", {}).get(label)
        if pid:
            cfg.set_active_provider(pid)
            self.app._refresh_key_status()

    def close(self):
        try:
            self.app._refresh_key_status()
        except Exception:
            pass
        self.grab_release()
        self.destroy()


# ==================== 保存路径设置弹窗 ====================
class PathDialog(tk.Toplevel):
    """
    模型文件保存路径设置窗口。

    两行：
      1. SolidWorks 文件存放地址
      2. 3D 打印文件存放地址（默认跟随第一行）
    每行路径可选中复制，下面有「更改路径」按钮。
    """

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

        self.title("模型文件保存路径")
        self.configure(bg=C_BG)
        self.resizable(False, False)
        self.transient(parent)

        W, H = 640, 420
        try:
            parent.update_idletasks()
            px = parent.winfo_rootx() + (parent.winfo_width() - W) // 2
            py = parent.winfo_rooty() + (parent.winfo_height() - H) // 2
            self.geometry(f"{W}x{H}+{max(0, px)}+{max(0, py)}")
        except Exception:
            self.geometry(f"{W}x{H}")

        # 当前路径
        self.model_path = cfg.get_model_dir()
        self.print_path = cfg.get_print_dir()

        self._build()
        self.grab_set()
        self.focus_force()

    def _build(self):
        # 标题栏
        head = tk.Frame(self, bg=C_CARD, height=64)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Frame(head, bg=C_BORDER, height=1).pack(side="bottom", fill="x")

        hl = tk.Frame(head, bg=C_CARD)
        hl.pack(side="left", padx=20, pady=12)
        tk.Label(hl, text="📁", font=("Segoe UI Emoji", 14),
                 bg=C_CARD, fg=C_TEXT).pack(side="left")
        tk.Label(hl, text="模型文件保存路径", font=("Microsoft YaHei UI", 13, "bold"),
                 fg=C_TEXT, bg=C_CARD).pack(side="left", padx=(8, 0))
        tk.Label(hl, text="生成的零件文件放在哪里", font=("Microsoft YaHei UI", 9),
                 fg=C_SUB, bg=C_CARD).pack(side="left", padx=(10, 0))

        body = tk.Frame(self, bg=C_BG)
        body.pack(fill="both", expand=True, padx=18, pady=14)

        # ---- 第一行：SolidWorks 文件 ----
        self.entry_model, self.lbl_status_model = self._mk_path_row(
            body,
            "SolidWorks 文件存放地址",
            "生成的 .SLDPRT 零件文件会保存到这里",
            self.model_path,
            lambda: self.change_path("model"))

        # ---- 第二行：3D 打印文件 ----
        self.entry_print, self.lbl_status_print = self._mk_path_row(
            body,
            "3D 打印文件存放地址",
            "导出的 .STL 文件会保存到这里（默认与上面相同）",
            self.print_path,
            lambda: self.change_path("print"))

        # ---- 底部按钮 ----
        foot = tk.Frame(self, bg=C_CARD)
        foot.pack(fill="x", side="bottom")
        tk.Frame(foot, bg=C_BORDER, height=1).pack(fill="x")

        fin = tk.Frame(foot, bg=C_CARD)
        fin.pack(fill="x", padx=18, pady=12)

        reset_btn = tk.Button(
            fin, text="恢复默认", font=("Microsoft YaHei UI", 9),
            command=self.reset_default,
            bg=C_CARD, fg=C_SUB,
            activebackground=C_HOVER, relief="flat", bd=0,
            cursor="hand2", padx=14, pady=5,
            highlightbackground=C_BORDER, highlightthickness=1)
        reset_btn.pack(side="left")

        close_btn = tk.Button(
            fin, text="完成", font=("Microsoft YaHei UI", 10),
            command=self.close,
            bg=C_PRIMARY, fg="#FFFFFF",
            activebackground=C_PRIMARY_D, activeforeground="#FFFFFF",
            relief="flat", bd=0, cursor="hand2", padx=22, pady=6)
        close_btn.pack(side="right")

        self.bind("<Escape>", lambda e: self.close())

    def _mk_path_row(self, parent, title, hint, path, on_change):
        """一行路径设置"""
        card = tk.Frame(parent, bg=C_CARD, highlightbackground=C_BORDER,
                        highlightthickness=1)
        card.pack(fill="x", pady=(0, 12))

        inner = tk.Frame(card, bg=C_CARD)
        inner.pack(fill="x", padx=14, pady=12)

        tk.Label(inner, text=title, font=("Microsoft YaHei UI", 9, "bold"),
                 fg=C_TEXT, bg=C_CARD).pack(anchor="w")
        tk.Label(inner, text=hint, font=("Microsoft YaHei UI", 8),
                 fg=C_SUB, bg=C_CARD).pack(anchor="w", pady=(2, 6))

        # 路径文本框（只读但可选中复制）
        wrap = tk.Frame(inner, bg=C_INPUT_BG, highlightbackground=C_BORDER,
                        highlightthickness=1)
        wrap.pack(fill="x")

        ent = tk.Entry(wrap, font=("Consolas", 9), bg=C_INPUT_BG, fg=C_TEXT,
                       relief="flat", bd=0, insertbackground=C_TEXT,
                       readonlybackground=C_INPUT_BG)
        ent.insert(0, path)
        ent.config(state="readonly")
        ent.pack(fill="x", padx=8, pady=6)

        # 点击就能全选，方便 Ctrl+C
        def on_click(e):
            ent.config(state="normal")
            ent.select_range(0, "end")
            ent.icursor("end")
            ent.config(state="readonly")
            return "break"

        ent.bind("<Button-1>", on_click)

        # 按钮行：更改路径 + 状态提示
        btn_row = tk.Frame(inner, bg=C_CARD)
        btn_row.pack(fill="x", pady=(8, 0))

        btn = tk.Button(
            btn_row, text="更改路径", font=("Microsoft YaHei UI", 9),
            command=on_change,
            bg=C_PRIMARY, fg="#FFFFFF",
            activebackground=C_PRIMARY_D, activeforeground="#FFFFFF",
            relief="flat", bd=0, cursor="hand2", padx=14, pady=4)
        btn.pack(side="left")

        status = tk.Label(btn_row, text="", font=("Microsoft YaHei UI", 8),
                          fg=C_SUB, bg=C_CARD, anchor="w")
        status.pack(side="left", padx=(10, 0))

        return ent, status

    # ---------------- 操作 ----------------
    def change_path(self, which):
        """弹出资源管理器选择新路径（两个按钮完全独立）"""
        is_model = (which == "model")
        cur = self.model_path if is_model else self.print_path
        title = ("选择 SolidWorks 文件存放位置"
                 if is_model else "选择 3D 打印文件存放位置")

        # 用一个可见的普通窗口做父窗口，保证对话框焦点正常、能置顶
        new = filedialog.askdirectory(
            parent=self, title=title, initialdir=cur, mustexist=True)
        if not new:
            return

        new = os.path.normpath(new)
        if not os.path.isdir(new):
            messagebox.showwarning("路径无效",
                                   f"文件夹不存在：\n{new}", parent=self)
            return

        # 检查可写
        try:
            test = os.path.join(new, ".swpg_write_test")
            with open(test, "w", encoding="utf-8") as f:
                f.write("x")
            os.remove(test)
        except Exception as e:
            messagebox.showerror("没有写入权限",
                                 f"这个文件夹不能写入：\n{new}\n\n{e}",
                                 parent=self)
            return

        # ---- 保存并立即更新对应文本框 ----
        if is_model:
            ok = cfg.set_model_dir(new)
            if not ok:
                messagebox.showerror("保存失败",
                                     "写入配置文件失败，请检查磁盘空间。",
                                     parent=self)
                return
            self.model_path = new
            self._set_entry(self.entry_model, new)   # 只更新第一行

            # 状态提示
            self.lbl_status_model.config(
                text=f"✓ 已更新：{new}", fg=C_OK)
        else:
            ok = cfg.set_print_dir(new)
            if not ok:
                messagebox.showerror("保存失败",
                                     "写入配置文件失败，请检查磁盘空间。",
                                     parent=self)
                return
            self.print_path = new
            self._set_entry(self.entry_print, new)   # 只更新第二行

            self.lbl_status_print.config(
                text=f"✓ 已更新：{new}", fg=C_OK)

    def reset_default(self):
        """恢复默认（系统下载文件夹）"""
        if not messagebox.askyesno("恢复默认",
                                   "两个路径都恢复到系统「下载」文件夹？",
                                   parent=self):
            return
        cfg.reset_paths()
        self.model_path = cfg.get_model_dir()
        self.print_path = cfg.get_print_dir()
        self._set_entry(self.entry_model, self.model_path)
        self._set_entry(self.entry_print, self.print_path)
        self.lbl_status_model.config(
            text=f"✓ 已恢复默认：{self.model_path}", fg=C_OK)
        self.lbl_status_print.config(
            text=f"✓ 已恢复默认：{self.print_path}", fg=C_OK)

    @staticmethod
    def _set_entry(ent, text):
        ent.config(state="normal")
        ent.delete(0, "end")
        ent.insert(0, text)
        ent.config(state="readonly")

    def close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


# ==================== 页面1：主页 ====================
class HomePage(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=C_BG)
        self.app = app

        wrap = tk.Frame(self, bg=C_BG)
        wrap.pack(fill="both", expand=True, padx=40, pady=30)

        # 欢迎区
        tk.Label(wrap, text="你好 👋", font=FONT_XL, fg=C_TEXT,
                 bg=C_BG).pack(anchor="w")
        tk.Label(wrap, text="用一个想法，生成一个真实的三维零件。",
                 font=FONT_MID, fg=C_SUB, bg=C_BG).pack(anchor="w", pady=(6, 24))

        # 目录卡片
        card = RoundedFrame(wrap, bg=C_CARD)
        card.pack(fill="x")

        row = tk.Frame(card, bg=C_CARD)
        row.pack(fill="x", padx=22, pady=18)

        tk.Label(row, text="📁", font=("Segoe UI Emoji", 20), bg=C_CARD,
                 fg=C_TEXT).pack(side="left")
        txt = tk.Frame(row, bg=C_CARD)
        txt.pack(side="left", padx=(14, 0), fill="x", expand=True)
        tk.Label(txt, text="设计一个小东西吧", font=FONT_MID, fg=C_TEXT,
                 bg=C_CARD).pack(anchor="w")
        tk.Label(txt, text="开始一个新的零件设计", font=FONT_SM, fg=C_SUB,
                 bg=C_CARD).pack(anchor="w", pady=(2, 0))

        btn = self.app._mk_btn(row, "进入  →", self.goto_choice)
        btn.pack(side="right")

        # 说明区
        info = RoundedFrame(wrap, bg=C_CARD)
        info.pack(fill="both", expand=True, pady=(20, 0))
        inner = tk.Frame(info, bg=C_CARD)
        inner.pack(fill="both", expand=True, padx=24, pady=20)
        tk.Label(inner, text="它能做什么", font=FONT_MID, fg=C_TEXT,
                 bg=C_CARD).pack(anchor="w")
        tips = [
            ("🖼", "上传一张零件图片，AI 识别形状后自动建模"),
            ("✍", "或者用文字描述你想要的零件"),
            ("⚙", "AI 深度思考后生成建模方案，直接驱动 SolidWorks 出图"),
            ("💾", "成品 .SLDPRT 自动保存到你的「下载」文件夹"),
        ]
        for icon, text in tips:
            r = tk.Frame(inner, bg=C_CARD)
            r.pack(anchor="w", pady=4)
            tk.Label(r, text=icon, font=("Segoe UI Emoji", 11), bg=C_CARD,
                     fg=C_PRIMARY, width=2).pack(side="left")
            tk.Label(r, text=text, font=FONT_SM, fg=C_SUB,
                     bg=C_CARD).pack(side="left")

    def goto_choice(self):
        # 进来前先确保至少有一个 key
        pid = self.app.get_active_provider()
        ent = self.app.key_entries.get(pid)
        typed = ent.get().strip() if ent else ""
        if typed:
            cfg.set_api_key(typed, provider=pid)

        if not cfg.has_any_key():
            messagebox.showwarning(
                "需要 API Key",
                "请先在右上角任选一个 AI 服务（DeepSeek / Claude / ChatGPT），\n"
                "填入对应的 API Key 并点「存」，再开始设计。")
            return
        self.app.show_page("choice")


# ==================== 页面2：选择身份 ====================
class ChoicePage(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=C_BG)
        self.app = app

        wrap = tk.Frame(self, bg=C_BG)
        wrap.pack(fill="both", expand=True, padx=40, pady=28)

        top = tk.Frame(wrap, bg=C_BG)
        top.pack(fill="x")
        self.app._mk_btn(top, "← 返回", lambda: app.show_page("home"),
                         kind="ghost").pack(side="left")

        tk.Label(wrap, text="你想做什么？", font=FONT_XL, fg=C_TEXT,
                 bg=C_BG).pack(anchor="w", pady=(18, 6))
        tk.Label(wrap, text="选一个方向，AI 会按对应方式帮你完成。",
                 font=FONT_MID, fg=C_SUB, bg=C_BG).pack(anchor="w", pady=(0, 20))

        # ---- 上面两个选项（并排）----
        row = tk.Frame(wrap, bg=C_BG)
        row.pack(fill="both", expand=True)

        self._mk_option(
            row, "🥤",
            "设计一个简单的 3D 模型或单一构件",
            "例如一个杯子、一颗螺母、一根轴——上传照片/画草图/写描述，"
            "AI 直接生成 SolidWorks 文件",
            enabled=True, cmd=self.choose_cad,
            badge="可用").pack(side="left", fill="both", expand=True,
                               padx=(0, 10))

        self._mk_option(
            row, "🧩",
            "有多个现成的部件模型，我要组装！",
            "上传多个 SolidWorks / STEP / STL 文件，在 3D 界面里拖拽摆放",
            enabled=True, cmd=self.choose_assembly,
            badge="可用").pack(side="left", fill="both", expand=True,
                               padx=(10, 0))

        # ---- 底部长条：手把手教你 CAD ----
        self._mk_wide_option(
            wrap, "🎓",
            "手把手教你 CAD",
            "从零开始，一步步教你用 SolidWorks 画零件、出图纸（敬请期待）"
        ).pack(fill="x", pady=(16, 0))

    def _mk_option(self, parent, icon, title, desc, enabled=True, cmd=None,
                   badge=None):
        bg = C_CARD if enabled else C_DISABLED
        fg_title = C_TEXT if enabled else C_SUB
        card = tk.Frame(parent, bg=bg, highlightbackground=C_BORDER,
                        highlightthickness=1, cursor="hand2" if enabled else "")
        inner = tk.Frame(card, bg=bg)
        inner.pack(fill="both", expand=True, padx=24, pady=24)

        # 顶部：图标 + 角标
        head = tk.Frame(inner, bg=bg)
        head.pack(fill="x")
        tk.Label(head, text=icon, font=("Segoe UI Emoji", 28), bg=bg,
                 fg=C_TEXT).pack(side="left")
        if badge:
            tk.Label(head, text=badge, font=("Microsoft YaHei UI", 8),
                     fg="#FFFFFF", bg=C_OK, padx=8, pady=2).pack(
                side="right")

        tk.Label(inner, text=title, font=FONT_LG, fg=fg_title, bg=bg,
                 wraplength=330, justify="left").pack(anchor="w", pady=(12, 8))
        tk.Label(inner, text=desc, font=FONT_SM, fg=C_SUB, bg=bg,
                 wraplength=330, justify="left").pack(anchor="w")

        if enabled and cmd:
            btn = tk.Button(inner, text="选择这个  →", command=cmd,
                            font=FONT_MAIN, bg=C_PRIMARY, fg="#FFFFFF",
                            activebackground=C_PRIMARY_D, activeforeground="#FFFFFF",
                            relief="flat", bd=0, cursor="hand2",
                            padx=18, pady=8)
            btn.pack(anchor="w", pady=(18, 0))
            card.bind("<Enter>", lambda e: card.config(highlightbackground=C_PRIMARY))
            card.bind("<Leave>", lambda e: card.config(highlightbackground=C_BORDER))
        else:
            tk.Label(inner, text="敬请期待", font=FONT_SM, fg=C_SUB,
                     bg=bg).pack(anchor="w", pady=(18, 0))

        return card

    def _mk_wide_option(self, parent, icon, title, desc):
        """横向长条卡片（整行宽度）"""
        bg = C_DISABLED
        card = tk.Frame(parent, bg=bg, highlightbackground=C_BORDER,
                        highlightthickness=1)
        inner = tk.Frame(card, bg=bg)
        inner.pack(fill="x", padx=24, pady=16)

        left = tk.Frame(inner, bg=bg)
        left.pack(side="left")
        tk.Label(left, text=icon, font=("Segoe UI Emoji", 24), bg=bg,
                 fg=C_TEXT).pack(side="left", padx=(0, 14))

        mid = tk.Frame(left, bg=bg)
        mid.pack(side="left")
        tk.Label(mid, text=title, font=FONT_LG, fg=C_SUB, bg=bg).pack(anchor="w")
        tk.Label(mid, text=desc, font=FONT_SM, fg=C_SUB, bg=bg).pack(anchor="w",
                                                                      pady=(4, 0))

        tk.Label(inner, text="敬请期待", font=FONT_SM, fg=C_SUB,
                 bg=bg).pack(side="right")
        return card

    def choose_cad(self):
        self.app.check_key_and_go()

    def choose_assembly(self):
        """进入组装页（不需要 API Key）"""
        if "assembly" not in self.app.pages:
            messagebox.showerror(
                "功能不可用",
                "组装模块加载失败，请检查 src/assembly.py 是否完整。")
            return
        self.app.show_page("assembly")


# ==================== 范例窗口 ====================
EXAMPLES = [
    {
        "icon": "🔩",
        "title": "六角螺母 M10",
        "tag": "标准件",
        "text": "一个 M10 六角螺母，对边宽度 16mm，厚度 8mm，"
                "中心是 M10 螺纹孔（底孔 8.5mm），六条棱边倒角 C1。",
    },
    {
        "icon": "🥤",
        "title": "带把手水杯",
        "tag": "回转体",
        "text": "一个塑料水杯，杯口外径 92mm，杯底外径 52mm，高 80mm，"
                "壁厚 2.5mm，侧面有一个环形把手，把手上有直径 22mm 的握孔。",
    },
    {
        "icon": "⚙",
        "title": "阶梯轴",
        "tag": "回转体",
        "text": "一个阶梯轴，小端直径 25mm 长 50mm，大端直径 40mm 长 30mm，"
                "总长 80mm，台阶处圆角 R2，两端倒角 C1.5。",
    },
    {
        "icon": "🔵",
        "title": "法兰盘",
        "tag": "盘类",
        "text": "一个法兰盘，外径 120mm，内孔 40mm，厚度 15mm，"
                "沿圆周均匀分布 6 个直径 10mm 的通孔，分布圆直径 90mm。",
    },
    {
        "icon": "■",
        "title": "带孔方块",
        "tag": "基础",
        "text": "一个立方的方块，边长 60mm，中心有一个直径 20mm 的通孔贯穿。",
    },
    {
        "icon": "⭕",
        "title": "垫圈",
        "tag": "标准件",
        "text": "一个平垫圈，外径 20mm，内径 10.5mm，厚度 2mm，边缘倒圆角 R0.3。",
    },
    {
        "icon": "🍽",
        "title": "圆盘 / 碗",
        "tag": "回转体",
        "text": "一个浅圆盘，上口直径 160mm，底部直径 100mm，高 30mm，"
                "壁厚 3mm，底部圆角 R5。",
    },
    {
        "icon": "🔘",
        "title": "圆柱销",
        "tag": "基础",
        "text": "一个圆柱销，直径 8mm，长度 40mm，两端倒角 C1。",
    },
    {
        "icon": "🔧",
        "title": "轴承座",
        "tag": "组合",
        "text": "一个简单的轴承座：方形底座 80×80mm 厚 12mm，"
                "中心有一个外径 50mm 高 30mm 的圆柱凸台，"
                "底部有直径 30mm 的通孔贯穿到底。",
    },
]


class ExampleDialog(tk.Toplevel):
    """零件范例窗口：点击示例即可填入描述框"""

    def __init__(self, parent, design_page):
        super().__init__(parent)
        self.design_page = design_page

        self.title("零件范例")
        self.configure(bg=C_BG)
        self.resizable(False, False)
        self.transient(parent)

        W, H = 660, 620
        try:
            parent.update_idletasks()
            px = parent.winfo_rootx() + (parent.winfo_width() - W) // 2
            py = parent.winfo_rooty() + (parent.winfo_height() - H) // 2
            self.geometry(f"{W}x{H}+{max(0, px)}+{max(0, py)}")
        except Exception:
            self.geometry(f"{W}x{H}")

        self._build()
        self.grab_set()
        self.focus_force()

    def _build(self):
        # 标题
        head = tk.Frame(self, bg=C_CARD, height=70)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Frame(head, bg=C_BORDER, height=1).pack(side="bottom", fill="x")

        hl = tk.Frame(head, bg=C_CARD)
        hl.pack(side="left", padx=20, pady=12)
        tk.Label(hl, text="📖", font=("Segoe UI Emoji", 14),
                 bg=C_CARD, fg=C_TEXT).pack(side="left")
        tk.Label(hl, text="零件范例", font=("Microsoft YaHei UI", 13, "bold"),
                 fg=C_TEXT, bg=C_CARD).pack(side="left", padx=(8, 0))
        tk.Label(hl, text="点击任意一个，填入描述框", font=("Microsoft YaHei UI", 9),
                 fg=C_SUB, bg=C_CARD).pack(side="left", padx=(10, 0))

        # 列表区（可滚动）
        wrap = tk.Frame(self, bg=C_BG)
        wrap.pack(fill="both", expand=True, padx=16, pady=12)

        canvas = tk.Canvas(wrap, bg=C_BG, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=C_BG)

        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw", width=600)
        canvas.configure(yscrollcommand=sb.set)

        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        for ex in EXAMPLES:
            self._card(inner, ex)

        # 底部
        foot = tk.Frame(self, bg=C_CARD)
        foot.pack(fill="x", side="bottom")
        tk.Frame(foot, bg=C_BORDER, height=1).pack(fill="x")
        fin = tk.Frame(foot, bg=C_CARD)
        fin.pack(fill="x", padx=18, pady=10)
        tk.Label(fin, text="提示：可以基于范例改尺寸，也可以上传图片代替文字",
                 font=("Microsoft YaHei UI", 8), fg=C_SUB,
                 bg=C_CARD).pack(side="left")

        cls_btn = tk.Button(fin, text="关闭", font=("Microsoft YaHei UI", 9),
                            command=self.close,
                            bg=C_CARD, fg=C_TEXT,
                            activebackground=C_HOVER, relief="flat", bd=0,
                            cursor="hand2", padx=18, pady=5,
                            highlightbackground=C_BORDER, highlightthickness=1)
        cls_btn.pack(side="right")

        self.bind("<Escape>", lambda e: self.close())

    def _card(self, parent, ex):
        """一个范例卡片"""
        card = tk.Frame(parent, bg=C_CARD, highlightbackground=C_BORDER,
                        highlightthickness=1, cursor="hand2")
        card.pack(fill="x", pady=4)

        body = tk.Frame(card, bg=C_CARD)
        body.pack(fill="x", padx=14, pady=10)

        # 第一行：图标 + 标题 + 标签
        r1 = tk.Frame(body, bg=C_CARD)
        r1.pack(fill="x")

        tk.Label(r1, text=ex["icon"], font=("Segoe UI Emoji", 13),
                 bg=C_CARD, fg=C_TEXT).pack(side="left", padx=(0, 8))
        tk.Label(r1, text=ex["title"], font=("Microsoft YaHei UI", 10, "bold"),
                 fg=C_TEXT, bg=C_CARD).pack(side="left")

        # 分类标签
        tag = tk.Label(r1, text=ex["tag"], font=("Microsoft YaHei UI", 7),
                       fg=C_PRIMARY, bg=C_TAG_BG, padx=7, pady=1)
        tag.pack(side="left", padx=(8, 0))

        # 使用按钮
        use = tk.Button(r1, text="使用 →", font=("Microsoft YaHei UI", 8),
                        command=lambda t=ex["text"]: self._use(t),
                        bg=C_PRIMARY, fg="#FFFFFF",
                        activebackground=C_PRIMARY_D, activeforeground="#FFFFFF",
                        relief="flat", bd=0, cursor="hand2",
                        padx=10, pady=2)
        use.pack(side="right")

        # 描述文字
        desc = tk.Label(body, text=ex["text"], font=("Microsoft YaHei UI", 9),
                        fg=C_SUB, bg=C_CARD, justify="left",
                        wraplength=560, anchor="w")
        desc.pack(fill="x", pady=(6, 0))

        # 点击卡片任意位置都能用
        for w in (card, body, r1, desc):
            w.bind("<Button-1>", lambda e, t=ex["text"]: self._use(t))

    def _use(self, text):
        """把范例文字填入设计页"""
        self.design_page.set_desc(text)
        self.destroy()

    def close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


# ==================== 页面3：零件设计 ====================
class DesignPage(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=C_BG)
        self.app = app
        self.image_path = None
        self.image_paths = []
        self.image_is_sketch = False
        self.image_is_three_view = False

        # 顶部
        top = tk.Frame(self, bg=C_BG)
        top.pack(fill="x", padx=36, pady=(22, 0))
        self.app._mk_btn(top, "← 返回", lambda: app.show_page("choice"),
                         kind="ghost").pack(side="left")

        tk.Label(self, text="输入你想构建的零件的样子", font=FONT_XL,
                 fg=C_TEXT, bg=C_BG).pack(anchor="w", padx=36, pady=(14, 4))
        tk.Label(self, text="可以上传一张图片，或者用文字描述。两者可以同时使用。",
                 font=FONT_SM, fg=C_SUB, bg=C_BG).pack(anchor="w", padx=36,
                                                       pady=(0, 16))

        # 主体左右分栏
        body = tk.Frame(self, bg=C_BG)
        body.pack(fill="both", expand=True, padx=36, pady=(0, 22))

        # 左：输入区
        left = RoundedFrame(body, bg=C_CARD)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        li = tk.Frame(left, bg=C_CARD)
        li.pack(fill="both", expand=True, padx=18, pady=12)

        # --- 图片区 ---
        tk.Label(li, text="① 上传零件图片（可选）", font=FONT_MAIN,
                 fg=C_TEXT, bg=C_CARD).pack(anchor="w")

        self.img_box = tk.Frame(li, bg=C_INPUT_BG, height=105,
                                highlightbackground=C_BORDER, highlightthickness=1)
        self.img_box.pack(fill="x", pady=(6, 4))
        self.img_box.pack_propagate(False)

        self.img_placeholder = tk.Label(
            self.img_box,
            text="点击这里选择图片　或　把图片文件拖进来\n支持 JPG / PNG / WebP",
            font=FONT_SM, fg=C_SUB, bg=C_INPUT_BG, cursor="hand2", justify="center")
        self.img_placeholder.pack(expand=True)
        self.img_placeholder.bind("<Button-1>", lambda e: self.pick_image())
        self.img_box.bind("<Button-1>", lambda e: self.pick_image())

        # 启用文件拖放（Windows WM_DROPFILES）
        self._setup_drop()

        # 多图预览容器（一行卡片）
        self.preview_row = tk.Frame(self.img_box, bg=C_INPUT_BG)

        # 手绘按钮
        sketch_row = tk.Frame(li, bg=C_CARD)
        sketch_row.pack(fill="x", pady=(2, 0))
        self.btn_sketch = tk.Button(
            sketch_row,
            text="✏  手绘一个3D草图，尽情绘制吧",
            font=FONT_SM, bg=C_CARD, fg=C_PRIMARY,
            activebackground=C_HOVER, activeforeground=C_PRIMARY,
            relief="flat", bd=0, cursor="hand2", padx=14, pady=7,
            highlightbackground=C_BORDER, highlightthickness=1,
            command=self.open_sketchpad)
        self.btn_sketch.pack(fill="x")
        tk.Label(sketch_row, text="PS：简单零件手绘，复杂的另说",
                 font=("Microsoft YaHei UI", 8), fg=C_SUB,
                 bg=C_CARD).pack(anchor="w", pady=(2, 0))

        self.img_row = tk.Frame(li, bg=C_CARD)
        self.img_row.pack(fill="x")
        self.lbl_img_name = tk.Label(self.img_row, text="", font=FONT_SM,
                                     fg=C_SUB, bg=C_CARD)
        self.lbl_img_name.pack(side="left")
        self.btn_clear_img = self.app._mk_btn(self.img_row, "清除", self.clear_image,
                                              small=True, kind="ghost")

        # --- 文字区 ---
        # 标题行（左侧标题 + 右侧「查看范例」按钮）
        desc_head = tk.Frame(li, bg=C_CARD)
        desc_head.pack(fill="x", pady=(8, 0))
        tk.Label(desc_head, text="② 用文字描述（可选）", font=FONT_MAIN,
                 fg=C_TEXT, bg=C_CARD).pack(side="left")

        btn_ex = tk.Button(desc_head, text="📖 查看范例", font=FONT_SM,
                           command=self.open_examples,
                           bg=C_CARD, fg=C_PRIMARY,
                           activebackground=C_HOVER, activeforeground=C_PRIMARY,
                           relief="flat", bd=0, cursor="hand2",
                           padx=12, pady=4,
                           highlightbackground=C_BORDER, highlightthickness=1)
        btn_ex.pack(side="right")
        btn_ex.bind("<Enter>", lambda e: btn_ex.config(bg=C_HOVER))
        btn_ex.bind("<Leave>", lambda e: btn_ex.config(bg=C_CARD))

        # 文本框（固定高度，不会被按钮挤压）
        txt_wrap = tk.Frame(li, bg=C_INPUT_BG, highlightbackground=C_BORDER,
                            highlightthickness=1, height=74)
        txt_wrap.pack(fill="x", pady=(6, 0))
        txt_wrap.pack_propagate(False)
        self.txt_desc = tk.Text(txt_wrap, font=FONT_MAIN, bg=C_INPUT_BG,
                                fg=C_TEXT, relief="flat", wrap="word",
                                insertbackground=C_TEXT, height=4,
                                highlightthickness=0, bd=0)
        self.txt_desc.pack(fill="both", expand=True, padx=10, pady=8)
        # 默认留空，用占位提示
        self.desc_placeholder = "在这里描述你想要的零件（也可以先上传图片，或点右上角「📖 查看范例」）"
        self._desc_empty = True
        self.txt_desc.insert("1.0", self.desc_placeholder)
        self.txt_desc.config(fg=C_PLACEHOLDER)
        self.txt_desc.bind("<FocusIn>", self._desc_on_focus)
        self.txt_desc.bind("<FocusOut>", self._desc_on_blur)
        # 实时刷新「预备输入」清单
        self.txt_desc.bind("<KeyRelease>", lambda e: self._refresh_input_list())

        # 底部按钮区（用 side="bottom" 保证优先占位，不会被挤压）
        btn_row = tk.Frame(li, bg=C_CARD, height=46)
        btn_row.pack(side="bottom", fill="x", pady=(6, 0))
        btn_row.pack_propagate(False)

        self.btn_gen = tk.Button(btn_row, text="✦  开始设计", font=FONT_MAIN,
                                 command=self.start_design, bg=C_PRIMARY,
                                 fg="#FFFFFF", activebackground=C_PRIMARY_D,
                                 activeforeground="#FFFFFF", relief="flat", bd=0,
                                 cursor="hand2", padx=24, pady=8)
        self.btn_gen.pack(side="left", pady=4)

        # 右：状态/结果区
        right = RoundedFrame(body, bg=C_CARD, width=380)
        right.pack(side="right", fill="both", padx=(10, 0))
        right.pack_propagate(False)
        ri = tk.Frame(right, bg=C_CARD)
        ri.pack(fill="both", expand=True, padx=20, pady=18)

        # ============ 模型文件保存路径（可点击）============
        self.btn_path = tk.Button(
            ri, text="📁  模型文件保存路径", font=FONT_MAIN,
            command=self.app.open_path_dialog,
            bg=C_INPUT_BG, fg=C_TEXT,
            activebackground=C_HOVER, activeforeground=C_TEXT,
            relief="flat", bd=0, cursor="hand2", pady=8,
            highlightbackground=C_BORDER, highlightthickness=1)
        self.btn_path.pack(fill="x", pady=(0, 12))
        self.btn_path.bind("<Enter>",
                           lambda e: self.btn_path.config(bg=C_HOVER))
        self.btn_path.bind("<Leave>",
                           lambda e: self.btn_path.config(bg=C_INPUT_BG))

        tk.Label(ri, text="设计状态", font=FONT_MAIN, fg=C_TEXT,
                 bg=C_CARD).pack(anchor="w")

        # 状态文字
        self.lbl_state = tk.Label(ri, text="等待开始", font=FONT_SM,
                                  fg=C_SUB, bg=C_CARD, anchor="w")
        self.lbl_state.pack(fill="x", pady=(6, 8))

        self.progress = ttk.Progressbar(ri, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 10))

        # ============ 预备输入清单 ============
        self.input_frame = tk.Frame(ri, bg=C_PANEL,
                                    highlightbackground=C_BORDER,
                                    highlightthickness=1)
        self.input_frame.pack(fill="x", pady=(0, 10))

        self.input_inner = tk.Frame(self.input_frame, bg=C_PANEL)
        self.input_inner.pack(fill="x", padx=10, pady=8)

        head = tk.Frame(self.input_inner, bg=C_PANEL)
        head.pack(fill="x")
        tk.Label(head, text="📋 预备输入", font=("Microsoft YaHei UI", 9, "bold"),
                 fg=C_TEXT, bg=C_PANEL).pack(side="left")
        self.lbl_input_count = tk.Label(
            head, text="无", font=("Microsoft YaHei UI", 8),
            fg=C_SUB, bg=C_PANEL)
        self.lbl_input_count.pack(side="right")

        # 清单内容容器
        self.input_list = tk.Frame(self.input_inner, bg=C_PANEL)
        self.input_list.pack(fill="x", pady=(6, 0))

        # 导出 3D 打印按钮（默认禁用）
        self.btn_print = tk.Button(
            ri, text="🖨  导出3D打印文件", font=FONT_MAIN,
            command=self.export_print_file,
            bg=C_DISABLED, fg=C_SUB,
            activebackground=C_DISABLED, activeforeground=C_SUB,
            relief="flat", bd=0, cursor="", padx=16, pady=9,
            state="disabled")
        self.btn_print.pack(fill="x", pady=(0, 12))
        self._print_enabled = False

        # 日志
        log_wrap = tk.Frame(ri, bg=C_INPUT_BG, highlightbackground=C_BORDER,
                            highlightthickness=1)
        log_wrap.pack(fill="both", expand=True)
        self.txt_log = tk.Text(log_wrap, font=("Consolas", 9), bg=C_INPUT_BG,
                               fg=C_SUB, relief="flat", wrap="word",
                               state="disabled")
        self.txt_log.pack(fill="both", expand=True, padx=8, pady=6)

        # 结果区
        self.result_frame = tk.Frame(ri, bg=C_CARD)

    # ---------- 交互 ----------
    def on_show(self):
        self.lbl_state.config(text="等待开始", fg=C_SUB)
        self._log_clear()

    # ---------- 拖放 ----------
    def _setup_drop(self):
        """给图片框启用 Windows 文件拖放"""
        self._dropper = None
        try:
            from filedrop import FileDropTarget
        except Exception as e:
            print(f"[拖放] 模块导入失败: {e}")
            return

        def on_drop(paths):
            self._on_files_dropped(paths)

        try:
            self._dropper = FileDropTarget(
                self.img_box,
                on_drop=on_drop,
                accept_exts=[".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"])
            if getattr(self._dropper, "enabled", False):
                print("[拖放] 已启用")
        except Exception as e:
            print(f"[拖放] 初始化失败: {e}")

    _IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")

    # ==================== 图片列表统一管理 ====================
    def _add_images(self, paths, append=True):
        """
        添加图片（统一入口）。

        参数：
            append: True=追加到现有列表；False=替换
        """
        valid = []
        for p in paths:
            if not os.path.isfile(p):
                continue
            if not p.lower().endswith(self._IMG_EXTS):
                continue
            try:
                if os.path.getsize(p) > 30 * 1024 * 1024:
                    continue
            except Exception:
                continue
            valid.append(p)

        if not valid:
            if paths:
                messagebox.showwarning("没有可用的图片",
                                       "文件不是有效的图片格式。")
            return

        if append:
            cur = list(getattr(self, "image_paths", []) or [])
            for p in valid:
                if p not in cur:      # 去重
                    cur.append(p)
            self.image_paths = cur[:3]     # 最多 3 张
        else:
            self.image_paths = valid[:3]

        self.image_path = self.image_paths[0] if self.image_paths else None
        self.image_is_sketch = False
        self._refresh_images()

    def _remove_image(self, index):
        """删除第 index 张图片"""
        paths = list(getattr(self, "image_paths", []) or [])
        if 0 <= index < len(paths):
            paths.pop(index)
        self.image_paths = paths
        self.image_path = paths[0] if paths else None
        if not paths:
            self.image_is_sketch = False
            self.image_is_three_view = False
        self._refresh_images()

    def _refresh_images(self):
        """按当前 image_paths 刷新预览和清单"""
        paths = list(getattr(self, "image_paths", []) or [])
        self.image_paths = paths
        self.image_path = paths[0] if paths else None
        self.image_is_three_view = (len(paths) >= 3)

        if not paths:
            self._clear_preview()
        else:
            labels = None
            if len(paths) >= 3:
                labels = ["主视图", "侧视图", "俯视图"]
            elif self.image_is_sketch:
                labels = ["手绘草图"] if len(paths) == 1 else None
            self.show_preview(paths, labels=labels)

        self._refresh_input_list()

    def _refresh_input_list(self):
        """刷新右侧「预备输入」清单"""
        for w in self.input_list.winfo_children():
            w.destroy()

        paths = list(getattr(self, "image_paths", []) or [])
        three = getattr(self, "image_is_three_view", False)
        is_sketch = getattr(self, "image_is_sketch", False)

        # 文字描述
        desc = ""
        try:
            desc = self.get_desc()
        except Exception:
            pass

        rows = 0

        # --- 图片项 ---
        if paths:
            names = ["主视图", "侧视图", "俯视图"]
            for i, p in enumerate(paths):
                if three:
                    tag = names[i] if i < len(names) else f"图{i+1}"
                elif is_sketch:
                    tag = "手绘"
                else:
                    tag = f"图{i+1}"
                self._input_row(self.input_list, "🖼",
                                f"{tag}：{os.path.basename(p)}", C_TEXT)
                rows += 1

        # --- 文字项 ---
        if desc:
            short = desc.replace("\n", " ")
            if len(short) > 40:
                short = short[:40] + "…"
            self._input_row(self.input_list, "✏", f"文字：{short}", C_TEXT)
            rows += 1

        # --- 汇总 ---
        if rows == 0:
            tk.Label(self.input_list, text="还没有输入任何内容",
                     font=("Microsoft YaHei UI", 8), fg=C_PLACEHOLDER,
                     bg=C_PANEL, anchor="w").pack(fill="x")
            self.lbl_input_count.config(text="无", fg=C_SUB)
        else:
            n_img = len(paths)
            parts = []
            if n_img:
                parts.append(f"{n_img} 张图")
            if desc:
                parts.append("1 段文字")
            self.lbl_input_count.config(text=" + ".join(parts), fg=C_PRIMARY)

            # 发送模式说明
            mode = ""
            if three:
                mode = "将按三视图发送给 AI"
            elif n_img == 1:
                mode = "将发送 1 张图给 AI"
            elif n_img == 2:
                mode = "将发送 2 张图给 AI"

            if mode:
                tk.Label(self.input_list, text="▸ " + mode,
                         font=("Microsoft YaHei UI", 8), fg=C_PRIMARY,
                         bg=C_PANEL, anchor="w").pack(fill="x", pady=(4, 0))

    def _input_row(self, parent, icon, text, color):
        """清单里的一行"""
        row = tk.Frame(parent, bg=C_PANEL)
        row.pack(fill="x", pady=1)
        tk.Label(row, text=icon, font=("Segoe UI Emoji", 8),
                 fg=color, bg=C_PANEL).pack(side="left")
        tk.Label(row, text=text, font=("Microsoft YaHei UI", 8),
                 fg=color, bg=C_PANEL, anchor="w").pack(side="left", padx=(4, 0))
        return row

    def _on_files_dropped(self, paths):
        """处理拖进来的文件（追加模式）"""
        if not paths:
            return
        before = len(getattr(self, "image_paths", []) or [])
        self._add_images(paths, append=True)
        after = len(getattr(self, "image_paths", []) or [])
        added = after - before
        if added > 0:
            self._log(f"✓ 已添加 {added} 张图片（共 {after} 张）")
        elif after > 0:
            self._log("这些图片已经添加过了")

    def pick_image(self):
        p = filedialog.askopenfilename(
            title="选择零件图片",
            filetypes=[("图片", "*.jpg *.jpeg *.png *.webp *.bmp *.gif"),
                       ("所有文件", "*.*")])
        if not p:
            return
        self._add_images([p], append=True)

    def open_sketchpad(self):
        """打开手绘画布窗口"""
        try:
            from sketchpad import SketchPad
        except Exception as e:
            messagebox.showerror("无法打开画布", f"缺少绘图模块：{e}")
            return

        def on_done(result):
            # result 可能是单个路径（自由模式）或路径列表（三视图模式）
            if isinstance(result, (list, tuple)):
                self.image_paths = list(result)
                self.image_path = result[0]
                self.image_is_sketch = True
                self._refresh_images()
                names = ["主视图", "侧视图", "俯视图"]
                self._log(f"✓ 已接收三视图草图（{len(result)} 张）："
                          + "、".join(names[:len(result)]))
            else:
                self.image_paths = [result]
                self.image_path = result
                self.image_is_sketch = True
                self._refresh_images()
                self._log(f"✓ 已接收手绘草图：{os.path.basename(result)}")

        SketchPad(self.app, on_done=on_done)

    # ---------------- 多图预览 ----------------
    def show_preview(self, paths, labels=None):
        """
        显示预览图。每张图带「×」删除按钮。

        参数：
            paths:  路径字符串 或 路径列表
            labels: 每张图的标签列表，如 ["主视图","侧视图","俯视图"]
        """
        if isinstance(paths, str):
            paths = [paths]
        paths = [p for p in paths if p]
        if not paths:
            self._clear_preview()
            return

        try:
            from PIL import Image, ImageTk
        except Exception as e:
            self.lbl_img_name.config(text=f"预览失败：{e}", fg=C_ERR)
            return

        # 清掉旧卡片
        for w in self.preview_row.winfo_children():
            w.destroy()
        self._photos = []

        self.img_placeholder.pack_forget()

        n = len(paths)
        # 单张给大一点，多张缩小以便并排
        if n == 1:
            max_w, max_h = 290, 86
        elif n == 2:
            max_w, max_h = 180, 86
        else:
            max_w, max_h = 130, 86

        for i, p in enumerate(paths):
            cap = labels[i] if labels and i < len(labels) else f"图{i + 1}"
            card = tk.Frame(self.preview_row, bg=C_INPUT_BG)
            card.pack(side="left", padx=5, pady=4)

            # 图片 + 右上角删除按钮的容器
            thumb_wrap = tk.Frame(card, bg=C_INPUT_BG,
                                  highlightbackground=C_BORDER,
                                  highlightthickness=1)
            thumb_wrap.pack()

            try:
                img = Image.open(p)
                img.thumbnail((max_w, max_h))
                photo = ImageTk.PhotoImage(img)
                self._photos.append(photo)   # 保持引用
                lbl = tk.Label(thumb_wrap, image=photo, bg=C_INPUT_BG)
                lbl.pack()
            except Exception:
                tk.Label(thumb_wrap, text="×", font=FONT_MAIN, fg=C_ERR,
                         bg=C_INPUT_BG, width=6, height=3).pack()

            # 删除按钮（浮在右上角）
            del_btn = tk.Label(thumb_wrap, text="×",
                               font=("Microsoft YaHei UI", 9, "bold"),
                               fg="#FFFFFF", bg="#E02B2B",
                               cursor="hand2", padx=4, pady=0)
            del_btn.place(relx=1.0, rely=0.0, anchor="ne")
            del_btn.bind("<Button-1>",
                         lambda e, idx=i: self._remove_image(idx))
            del_btn.bind("<Enter>", lambda e, b=del_btn: b.config(bg="#C01F1F"))
            del_btn.bind("<Leave>", lambda e, b=del_btn: b.config(bg="#E02B2B"))

            # 标签
            tk.Label(card, text=cap, font=("Microsoft YaHei UI", 8),
                     fg=C_SUB, bg=C_INPUT_BG).pack(pady=(2, 0))

        self.preview_row.pack(expand=True)

        # 底部说明
        is_sketch = getattr(self, "image_is_sketch", False)
        three = getattr(self, "image_is_three_view", False)

        if three and n >= 3:
            text = f"[三视图] 主视图 · 侧视图 · 俯视图（共 {n} 张）"
        elif is_sketch:
            text = f"[手绘草图] {os.path.basename(paths[0])}"
        elif n > 1:
            text = f"[图片] 共 {n} 张（点 × 可删除）"
        else:
            text = f"[图片] {os.path.basename(paths[0])}"

        self.lbl_img_name.config(text=text, fg=C_TEXT)
        self.btn_clear_img.pack(side="right")

    def _clear_preview(self):
        """只清预览界面（不清数据）"""
        self._photos = []
        for w in self.preview_row.winfo_children():
            w.destroy()
        self.preview_row.pack_forget()
        self.img_placeholder.pack(expand=True)
        self.lbl_img_name.config(text="")
        self.btn_clear_img.pack_forget()

    def clear_image(self):
        """清空图片状态和预览（等待下一轮输入）"""
        self.image_path = None
        self.image_paths = []
        self.image_is_sketch = False
        self.image_is_three_view = False
        self._photos = []
        self._clear_preview()
        self._refresh_input_list()

    def _desc_on_focus(self, event=None):
        """文本框获得焦点：清掉占位符"""
        if self._desc_empty:
            self.txt_desc.delete("1.0", "end")
            self.txt_desc.config(fg=C_TEXT)
            self._desc_empty = False

    def _desc_on_blur(self, event=None):
        """文本框失去焦点：如果为空则恢复占位符"""
        if not self.txt_desc.get("1.0", "end").strip():
            self._desc_empty = True
            self.txt_desc.delete("1.0", "end")
            self.txt_desc.insert("1.0", self.desc_placeholder)
            self.txt_desc.config(fg=C_PLACEHOLDER)
        # 文字变化也要刷新清单
        self._refresh_input_list()

    def get_desc(self):
        """取用户输入的文字（占位符状态返回空）"""
        if self._desc_empty:
            return ""
        return self.txt_desc.get("1.0", "end").strip()

    def set_desc(self, text):
        """设置文字内容（用于范例填充）"""
        self.txt_desc.delete("1.0", "end")
        self.txt_desc.insert("1.0", text)
        self.txt_desc.config(fg=C_TEXT)
        self._desc_empty = False

    def open_examples(self):
        """打开范例窗口"""
        ExampleDialog(self.app, self)

    def fill_example(self):
        """兼容旧调用：填入一个示例"""
        self.set_desc("一个 M10 六角螺母，对边宽度 16mm，厚度 8mm，"
                      "中心是 M10 螺纹孔（底孔 8.5mm），六条棱边倒角 C1。")

    def _log(self, msg, color=None):
        self.txt_log.config(state="normal")
        self.txt_log.insert("end", msg + "\n")
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")

    def _log_clear(self):
        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.config(state="disabled")

    # ---------- 主流程 ----------
    def start_design(self):
        if self.app._busy:
            return
        desc = self.get_desc()
        if not desc and not self.image_path:
            messagebox.showwarning("缺少信息",
                                   "请至少上传一张图片，或填写文字描述。")
            return

        # 取当前服务商
        pid = self.app.get_active_provider()
        info = cfg.get_provider_info(pid)
        key = cfg.get_api_key(pid)

        if not key:
            messagebox.showwarning(
                "需要 API Key",
                f"当前使用的 AI 服务是「{info['name']}」，但还没填写它的 Key。\n"
                f"请在右上角填入后点「存」。")
            self.app.show_page("home")
            return

        if not cfg.is_key_verified(pid):
            ok, msg = api_client.verify_key(key, pid)
            if not ok:
                cfg.clear_verification(pid)
                messagebox.showerror(f"{info['name']} API Key 无效", msg)
                self.app.show_page("home")
                return
            cfg.mark_verified(pid)
            self.app._refresh_key_status()

        self.app._busy = True
        self.btn_gen.config(state="disabled", text="设计中…")
        self._set_print_enabled(False)
        self.progress.start(12)
        self.lbl_state.config(text=f"{info['name']} 正在思考…", fg=C_PRIMARY)
        self._log_clear()
        self.result_frame.pack_forget()

        is_sketch = bool(getattr(self, "image_is_sketch", False))
        is_three = bool(getattr(self, "image_is_three_view", False))
        paths = list(getattr(self, "image_paths", []) or [])
        t = threading.Thread(target=self._worker,
                             args=(desc, self.image_path, is_sketch, pid,
                                   paths, is_three),
                             daemon=True)
        t.start()

    def _worker(self, desc, image_path, is_sketch=False, provider="deepseek",
                image_paths=None, is_three_view=False):
        pythoncom_ready = False
        try:
            # 子线程必须初始化 COM（SolidWorks 建模用）
            import pythoncom
            pythoncom.CoInitialize()
            pythoncom_ready = True

            # 1. AI 分析
            pname = cfg.get_provider_info(provider)["name"]
            n_img = len(image_paths) if image_paths else (1 if image_path else 0)
            if is_three_view and n_img >= 3:
                self._ui(lambda: self._log(
                    f"▸ 正在请求 {pname} 分析三视图（主/侧/俯）…"))
            else:
                self._ui(lambda: self._log(f"▸ 正在请求 {pname} 分析零件…"))

            spec = api_client.analyze_part(
                cfg.get_api_key(provider), desc,
                image_path,
                is_sketch=is_sketch,
                provider=provider,
                image_paths=image_paths,
                is_three_view=is_three_view)
            self._last_spec = spec
            self._ui(lambda: self._log(f"✓ {pname} 给出方案：{spec.get('part_name','未命名')}"))

            # 2. 建模
            self._ui(lambda: (
                self._log("▸ 正在启动 SolidWorks 建模…"),
                self.lbl_state.config(text="正在建模…", fg=C_PRIMARY)))

            from sw_builder import SolidWorksBuilder, BuildError
            builder = SolidWorksBuilder(log_func=lambda m: self._ui(lambda: self._log(m)))
            name_en = spec.get("part_name_en", "part")
            name_en = "".join(c for c in name_en if c.isalnum() or c == "_") or "part"
            base_name = f"{spec.get('part_name','零件')}_{name_en}"
            # 用用户设置的保存路径
            dl = cfg.get_model_dir()
            os.makedirs(dl, exist_ok=True)
            save_path = os.path.join(dl, base_name + ".SLDPRT")

            result = builder.build(spec, save_path)
            self._last_result = result

            self._ui(lambda: self._done_ok(spec, result))

        except Exception as e:
            err = str(e)
            tb = traceback.format_exc()
            self._ui(lambda: self._done_err(err, tb))
        finally:
            if pythoncom_ready:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    def _ui(self, fn):
        """
        从后台线程安全地更新界面。

        ★ 保护：如果本页面已被销毁（比如切换主题重建了界面），
          就丢弃这次更新，避免抛 TclError 或写坏已销毁的控件。
        """
        try:
            # 页面已被销毁 → 直接丢弃
            if not self.winfo_exists():
                return
            self.after(0, self._ui_safe(fn))
        except Exception:
            # 任何异常都不应该让后台线程崩掉
            pass

    def _ui_safe(self, fn):
        """包一层，回调时再检查一次页面是否还在"""
        def wrapper():
            try:
                if not self.winfo_exists():
                    return
                fn()
            except Exception:
                # 控件已销毁时静默忽略
                pass
        return wrapper

    def _done_ok(self, spec, result):
        self.app._busy = False
        self.btn_gen.config(state="normal", text="✦  开始设计")
        self.progress.stop()
        self.lbl_state.config(text="✓ 完成", fg=C_OK)

        self._log("✓ 建模完成")
        for s in result.get("steps", []):
            self._log(f"   · {s}")
        self._log(f"✓ 已保存到：{result['path']}")

        # 建模成功后启用 3D 打印导出
        self._set_print_enabled(True)

        self._show_result(spec, result)

        # ★ 一轮绘制完成 → 清空图片预览和文字，等待下一轮输入
        self._reset_inputs()

    def _reset_inputs(self):
        """一轮绘制完成后重置输入区，等待下一轮"""
        try:
            self.clear_image()
        except Exception:
            pass
        try:
            self.txt_desc.delete("1.0", "end")
            self.txt_desc.insert("1.0", self.desc_placeholder)
            self.txt_desc.config(fg=C_PLACEHOLDER)
            self._desc_empty = True
        except Exception:
            pass
        # 刷新预备输入清单（应该显示「无」）
        try:
            self._refresh_input_list()
        except Exception:
            pass

    def _set_print_enabled(self, enabled):
        """启用/禁用 3D 打印导出按钮"""
        self._print_enabled = enabled
        if enabled:
            self.btn_print.config(
                state="normal", bg=C_PRIMARY, fg="#FFFFFF",
                activebackground=C_PRIMARY_D, activeforeground="#FFFFFF",
                cursor="hand2")
        else:
            self.btn_print.config(
                state="disabled", bg=C_DISABLED, fg=C_SUB,
                activebackground=C_DISABLED, activeforeground=C_SUB,
                cursor="")

    def export_print_file(self):
        """导出 STL 给 3D 打印"""
        if not self._print_enabled or not self._last_result:
            return
        if self.app._busy:
            return

        part_path = self._last_result["path"]
        # STL 放在用户设置的 3D 打印目录（文件名跟零件一致）
        stl_dir = cfg.get_print_dir()
        try:
            os.makedirs(stl_dir, exist_ok=True)
        except Exception:
            stl_dir = os.path.dirname(part_path)
        stl_path = os.path.join(
            stl_dir, os.path.splitext(os.path.basename(part_path))[0] + ".stl")

        self.app._busy = True
        self.btn_print.config(state="disabled", text="导出中…")
        self.lbl_state.config(text="正在导出 3D 打印文件…", fg=C_PRIMARY)
        self.progress.start(12)

        def work():
            pythoncom_ready = False
            try:
                # 子线程必须初始化 COM，否则报「尚未调用 CoInitialize」
                import pythoncom
                pythoncom.CoInitialize()
                pythoncom_ready = True

                from sw_builder import SolidWorksBuilder
                b = SolidWorksBuilder(
                    log_func=lambda m: self._ui(lambda: self._log(m)))
                b.connect()
                # 重新打开刚才的零件
                b.sw.OpenDoc(part_path, 1)
                import time as _t
                _t.sleep(1)
                b.doc = b.mod.IModelDoc2(b.sw.ActiveDoc._oleobj_)
                r = b.export_stl(stl_path, quality="fine")
                self._ui(lambda: ok(r))
            except Exception as e:
                err = str(e)
                self._ui(lambda: fail(err))
            finally:
                if pythoncom_ready:
                    try:
                        pythoncom.CoUninitialize()
                    except Exception:
                        pass

        def ok(r):
            self.app._busy = False
            self.progress.stop()
            self.btn_print.config(state="normal", text="🖨  重新导出3D打印文件")
            self.lbl_state.config(text="✓ 打印文件已导出", fg=C_OK)
            self._log(f"✓ STL 已导出：{r['path']}  ({r['size_mb']:.2f} MB)")
            messagebox.showinfo(
                "3D 打印文件已生成",
                f"已保存到与零件相同的目录：\n\n{r['path']}\n\n"
                f"文件大小：{r['size_mb']:.2f} MB\n\n"
                f"可以直接拖进切片软件（Cura、PrusaSlicer、Bambu Studio 等）打印。")
            self._open_folder(r["path"])

        def fail(err):
            self.app._busy = False
            self.progress.stop()
            self.btn_print.config(state="normal", text="🖨  导出3D打印文件")
            self.lbl_state.config(text="✗ 导出失败", fg=C_ERR)
            self._log(f"✗ STL 导出失败：{err}")
            messagebox.showerror("导出失败", err)

        threading.Thread(target=work, daemon=True).start()

    def _done_err(self, err, tb):
        self.app._busy = False
        self.btn_gen.config(state="normal", text="✦  开始设计")
        self.progress.stop()
        self.lbl_state.config(text="✗ 失败", fg=C_ERR)
        self._log(f"✗ 失败：{err}")
        self._log("")
        self._log(tb[-800:])
        messagebox.showerror("设计失败", err)

    def _show_result(self, spec, result):
        self.result_frame.pack(fill="x", pady=(12, 0))
        for w in self.result_frame.winfo_children():
            w.destroy()

        tk.Frame(self.result_frame, bg=C_BORDER, height=1).pack(fill="x", pady=(0, 10))
        tk.Label(self.result_frame, text="✓ 零件已生成", font=FONT_MAIN,
                 fg=C_OK, bg=C_CARD).pack(anchor="w")

        rows = [
            ("名称", spec.get("part_name", "-")),
            ("材料", spec.get("material", "-")),
            ("体积", f"{result['volume_mm3']:.1f} mm³"),
            ("面/边", f"{result['faces']} / {result['edges']}"),
        ]
        for k, v in rows:
            r = tk.Frame(self.result_frame, bg=C_CARD)
            r.pack(fill="x", pady=1)
            tk.Label(r, text=k, font=FONT_SM, fg=C_SUB, bg=C_CARD,
                     width=6, anchor="w").pack(side="left")
            tk.Label(r, text=str(v), font=FONT_SM, fg=C_TEXT, bg=C_CARD,
                     anchor="w").pack(side="left")

        btn = self.app._mk_btn(self.result_frame, "打开所在文件夹",
                               lambda: self._open_folder(result["path"]),
                               kind="ghost", small=True)
        btn.pack(anchor="w", pady=(8, 0))

    def _open_folder(self, path):
        try:
            os.startfile(os.path.dirname(path))
        except Exception as e:
            messagebox.showerror("无法打开", str(e))


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
