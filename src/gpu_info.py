# -*- coding: utf-8 -*-
"""
gpu_info.py — 显卡检测
=======================
检测本机显卡，判断是核显（集成显卡）还是独显（独立显卡）。

★ 重要：优先用 **注册表** 读取，不依赖子进程。
   原因：程序打包成 --windowed 后，用 subprocess 调 PowerShell
   在部分环境下拿不到输出（管道被限制），会卡在「检测中…」。

读取顺序：
  1. 注册表 HKLM\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968...}
     （显示适配器类，每个显卡一个子键，值 DriverDesc 就是显卡名）
  2. PowerShell（注册表失败时兜底）
  3. wmic（老系统兜底）

判断逻辑：
  · NVIDIA GeForce / RTX / GTX / Quadro  → 独显
  · AMD Radeon RX / Radeon Pro            → 独显
  · Intel Arc                             → 独显
  · Intel UHD / HD Graphics / Iris        → 核显
  · AMD Radeon(TM) / Vega / 610M 等       → 核显
  · Virtual / Todesk / Parsec 等          → 虚拟显卡（忽略）
"""
import os
import subprocess
import sys


# 独显关键字
DISCRETE_KEYWORDS = [
    "nvidia", "geforce", "rtx", "gtx", "quadro", "tesla",
    "radeon rx", "radeon pro",
    "intel arc",
]

# 核显关键字
INTEGRATED_KEYWORDS = [
    "intel(r) uhd", "intel uhd", "uhd graphics",
    "intel(r) hd graphics", "hd graphics", "iris",
    "radeon(tm)", "radeon graphics", "vega",
    "radeon 610m", "radeon 710m", "radeon 760m", "radeon 780m",
    "radeon 840m", "radeon 880m",
    "microsoft basic display", "microsoft basic render",
]

# 虚拟显卡（直接忽略）
VIRTUAL_KEYWORDS = [
    "virtual", "todesk", "parsec", "spacedesk", "vmware", "virtualbox",
    "citrix", "remote", "mirror", "idd", "indirect display",
]


def _read_registry_gpus():
    """
    从注册表读显卡名（最快、最可靠、不需要子进程）。

    路径：
      HKLM\\SYSTEM\\CurrentControlSet\\Control\\Class\\
        {4d36e968-e325-11ce-bfc1-08002be10318}\\0000, 0001, ...
    每个子键的 DriverDesc 值就是显卡名称。
    """
    names = []
    try:
        import winreg
        base = (r"SYSTEM\CurrentControlSet\Control\Class"
                r"\{4d36e968-e325-11ce-bfc1-08002be10318}")
        try:
            hkey = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base,
                                  0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        except Exception:
            hkey = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base, 0,
                                  winreg.KEY_READ)

        i = 0
        while True:
            try:
                sub_name = winreg.EnumKey(hkey, i)
            except OSError:
                break
            i += 1

            # 只处理 0000 / 0001 这种编号子键
            if not sub_name.isdigit():
                continue

            try:
                sub = winreg.OpenKey(hkey, sub_name, 0, winreg.KEY_READ)
            except Exception:
                continue

            # 尝试几个可能的键名
            for val_name in ("DriverDesc", "HardwareInformation.AdapterString",
                             "Device Description"):
                try:
                    v, _ = winreg.QueryValueEx(sub, val_name)
                    if v:
                        if isinstance(v, bytes):
                            v = v.decode("utf-16-le", errors="ignore").strip("\x00")
                        if v and v not in names:
                            names.append(str(v))
                        break
                except Exception:
                    continue
            try:
                winreg.CloseKey(sub)
            except Exception:
                pass

        try:
            winreg.CloseKey(hkey)
        except Exception:
            pass
    except Exception:
        pass
    return names


def _run_ps(cmd, timeout=15):
    """执行 PowerShell（兜底用）"""
    try:
        # 不再用 capture_output（避免管道问题），改成写临时文件
        import tempfile
        out_file = os.path.join(tempfile.gettempdir(),
                                f"_gpu_{os.getpid()}.txt")
        full = f"{cmd} | Out-File -FilePath '{out_file}' -Encoding UTF8"
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", full],
            capture_output=False, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=timeout,
            creationflags=0x08000000)
        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8-sig", errors="ignore") as f:
                txt = f.read()
            try:
                os.remove(out_file)
            except Exception:
                pass
            return txt.strip()
    except Exception:
        pass
    return ""


def get_gpus():
    """
    获取所有显卡名称。

    优先注册表，失败后用 PowerShell / wmic 兜底。
    """
    names = _read_registry_gpus()

    if not names:
        out = _run_ps(
            "Get-CimInstance Win32_VideoController | "
            "ForEach-Object { $_.Name }")
        if out:
            names = [ln.strip() for ln in out.splitlines() if ln.strip()]

    if not names:
        try:
            import tempfile
            out_file = os.path.join(tempfile.gettempdir(),
                                    f"_gpu2_{os.getpid()}.txt")
            subprocess.run(
                ["cmd", "/c", f"wmic path win32_VideoController get name > "
                              f"\"{out_file}\""],
                capture_output=False, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=12,
                creationflags=0x08000000)
            if os.path.exists(out_file):
                with open(out_file, "r", encoding="utf-8", errors="ignore") as f:
                    for ln in f:
                        ln = ln.strip()
                        if ln and ln.lower() != "name":
                            names.append(ln)
                os.remove(out_file)
        except Exception:
            pass

    # 去重
    seen = set()
    uniq = []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq


def classify(name):
    """
    判断一张显卡是核显还是独显。

    返回："discrete" | "integrated" | "virtual" | "unknown"
    """
    low = (name or "").lower()
    if not low:
        return "unknown"

    # 虚拟显卡优先排除
    for k in VIRTUAL_KEYWORDS:
        if k in low:
            return "virtual"

    # 独显优先（避免 "Radeon RX" 被 "radeon" 误判成核显）
    for k in DISCRETE_KEYWORDS:
        if k in low:
            return "discrete"

    # 核显
    for k in INTEGRATED_KEYWORDS:
        if k in low:
            return "integrated"

    return "unknown"


def detect():
    """
    检测本机显卡情况。

    返回 dict：
        {
          "all": [...], "discrete": [...], "integrated": [...],
          "virtual": [...], "unknown": [...],
          "active": "...", "display": "...",
          "is_integrated_only": bool,
          "has_warning": bool, "warning_text": "...",
        }
    """
    gpus = get_gpus()

    discrete = []
    integrated = []
    virtual = []
    unknown = []

    for g in gpus:
        c = classify(g)
        if c == "discrete":
            discrete.append(g)
        elif c == "integrated":
            integrated.append(g)
        elif c == "virtual":
            virtual.append(g)
        else:
            unknown.append(g)

    is_integrated_only = (len(discrete) == 0)

    if discrete:
        active = discrete[0]
        display = active
        if integrated:
            display = f"{active}（另有核显 {integrated[0]}）"
        warn = ""
    elif integrated:
        active = integrated[0]
        display = active
        warn = ("推荐使用独立显卡\n\n"
                "检测到当前只有核显（集成显卡），3D 组装界面可能会卡顿。\n\n"
                "建议：\n"
                "  1. 打开 NVIDIA 控制面板 / AMD 显卡设置\n"
                "  2. 找到「程序设置」，把本程序添加进去\n"
                "  3. 指定使用「高性能独立显卡」")
    elif unknown:
        active = unknown[0]
        display = active
        warn = ""
    else:
        active = "未知"
        display = "未检测到显卡（可能是虚拟机）"
        warn = ""

    return {
        "all": gpus,
        "discrete": discrete,
        "integrated": integrated,
        "virtual": virtual,
        "unknown": unknown,
        "active": active,
        "is_integrated_only": is_integrated_only,
        "has_warning": bool(warn),
        "warning_text": warn,
        "display": display,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(detect(), ensure_ascii=False, indent=2))
