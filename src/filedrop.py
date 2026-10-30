# -*- coding: utf-8 -*-
"""
filedrop.py — 让 Tkinter 控件支持 Windows 文件拖拽
====================================================
Tkinter 原生不支持把文件从资源管理器拖进窗口。
Windows 提供 WM_DROPFILES 消息，做法是：

  1. DragAcceptFiles(hwnd, True)   声明窗口接受拖放
  2. 子类化窗口过程（SetWindowLongPtr 换 WndProc）
  3. 在 WndProc 里拦截 WM_DROPFILES，
     用 DragQueryFile 取出文件路径，交给回调
  4. 处理完调用 DragFinish

注意：
  · 必须保留原 WndProc，用 CallWindowProc 转回去
  · Windows 10/11 需要 ChangeWindowMessageFilterEx 才能收到
    从「更高权限进程」拖来的文件
"""
import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

# ---------------- 常量 ----------------
WM_DROPFILES = 0x0233
WM_COPYDATA = 0x004A
WM_COPYGLOBALDATA = 0x0049
MSGFLT_ALLOW = 1

GWL_WNDPROC = -4

# ---------------- 类型声明 ----------------
WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    wintypes.HWND,
    ctypes.c_uint,
    wintypes.WPARAM,
    wintypes.LPARAM,
)

user32.SetWindowLongPtrW = getattr(
    user32, "SetWindowLongPtrW", user32.SetWindowLongW)
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int,
                                     ctypes.c_void_p]
user32.SetWindowLongPtrW.restype = ctypes.c_void_p

user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND,
                                   ctypes.c_uint, wintypes.WPARAM,
                                   wintypes.LPARAM]
user32.CallWindowProcW.restype = ctypes.c_long

shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                   wintypes.LPWSTR, wintypes.UINT]
shell32.DragQueryFileW.restype = wintypes.UINT

shell32.DragFinish.argtypes = [wintypes.HANDLE]
shell32.DragFinish.restype = None

# DragAcceptFiles 在 shell32 里（不在 user32）
_shell_DragAcceptFiles = shell32.DragAcceptFiles
_shell_DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
_shell_DragAcceptFiles.restype = None


def _drag_accept(hwnd, accept=True):
    """声明窗口接受拖放"""
    try:
        _shell_DragAcceptFiles(wintypes.HWND(hwnd), wintypes.BOOL(1 if accept else 0))
    except Exception as e:
        print(f"[FileDropTarget] DragAcceptFiles 失败: {e}")


class FileDropTarget:
    """
    给一个 Tk 控件挂上文件拖拽支持。

    用法：
        dropper = FileDropTarget(widget, on_drop=callback)
        # callback(paths)  paths 是文件路径列表
    """

    def __init__(self, widget, on_drop=None, accept_exts=None):
        """
        widget:     Tk 控件（推荐用 Frame 或 Label）
        on_drop:    回调，收到 list[str]
        accept_exts: 允许的扩展名（小写，带点），None = 全接收
        """
        self.widget = widget
        self.on_drop = on_drop
        self.accept_exts = [e.lower() for e in accept_exts] if accept_exts else None

        self._hwnd = self._get_hwnd(widget)
        self._old_proc = None
        self._new_proc = None      # 必须保存引用，否则会被 GC 回收
        self._ok = False

        if not self._hwnd:
            return

        try:
            # 1. 允许接收文件拖放
            _drag_accept(self._hwnd, True)

            # 2. 让消息过滤器放行（Windows 10/11 需要）
            self._allow_message(WM_DROPFILES)
            self._allow_message(WM_COPYDATA)
            self._allow_message(WM_COPYGLOBALDATA)

            # 3. 子类化窗口过程
            self._new_proc = WNDPROC(self._wndproc)
            self._old_proc = user32.SetWindowLongPtrW(
                self._hwnd, GWL_WNDPROC,
                ctypes.cast(self._new_proc, ctypes.c_void_p))
            self._ok = bool(self._old_proc)
        except Exception as e:
            print(f"[FileDropTarget] 初始化失败: {e}")

    @property
    def enabled(self):
        return self._ok

    @staticmethod
    def _get_hwnd(widget):
        """取得 Tk 控件的 Windows 窗口句柄"""
        try:
            widget.update_idletasks()
            return int(widget.winfo_id())
        except Exception:
            return 0

    def _allow_message(self, msg):
        """放行特定 Windows 消息（避免被 UIPI 拦截）"""
        try:
            class CHANGEFILTERSTRUCT(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD),
                            ("ExtStatus", wintypes.DWORD)]
            cfs = CHANGEFILTERSTRUCT()
            cfs.cbSize = ctypes.sizeof(CHANGEFILTERSTRUCT)
            fn = getattr(user32, "ChangeWindowMessageFilterEx", None)
            if fn:
                fn(wintypes.HWND(self._hwnd), wintypes.UINT(msg),
                   wintypes.DWORD(MSGFLT_ALLOW), ctypes.byref(cfs))
        except Exception:
            pass

    def _wndproc(self, hwnd, msg, wparam, lparam):
        """窗口过程：拦到 WM_DROPFILES 就处理"""
        if msg == WM_DROPFILES:
            try:
                self._handle_drop(wparam)
            except Exception as e:
                print(f"[FileDropTarget] 处理拖放失败: {e}")
            return 0

        # 其余的转给原来的窗口过程
        return user32.CallWindowProcW(self._old_proc, hwnd, msg,
                                      wparam, lparam)

    def _handle_drop(self, hdrop):
        """解析拖进来的文件列表"""
        paths = []
        try:
            count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
            for i in range(count):
                # 先问长度，再取内容
                ln = shell32.DragQueryFileW(hdrop, i, None, 0)
                if ln <= 0:
                    continue
                buf = ctypes.create_unicode_buffer(ln + 1)
                shell32.DragQueryFileW(hdrop, i, buf, ln + 1)
                p = buf.value
                if p:
                    paths.append(p)
        finally:
            shell32.DragFinish(hdrop)

        # 过滤扩展名
        if self.accept_exts:
            paths = [p for p in paths
                     if any(p.lower().endswith(e) for e in self.accept_exts)]

        if paths and self.on_drop:
            # 用 after 回到 Tk 主线程，避免在窗口过程里直接操作界面
            try:
                self.widget.after(10, lambda ps=list(paths): self.on_drop(ps))
            except Exception:
                self.on_drop(paths)

    def destroy(self):
        """解除绑定"""
        try:
            if self._hwnd and self._old_proc:
                user32.SetWindowLongPtrW(self._hwnd, GWL_WNDPROC,
                                         self._old_proc)
                _drag_accept(self._hwnd, False)
        except Exception:
            pass
        self._ok = False
