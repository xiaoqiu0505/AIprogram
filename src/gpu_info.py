# -*- coding: utf-8 -*-
"""
gpu_info.py — 显卡检测
=======================
检测本机显卡，判断是核显（集成显卡）还是独显（独立显卡）。

检测方式（按可靠性排序）：
  1. PowerShell Get-CimInstance Win32_VideoController（最可靠）
  2. wmic（老系统）
  3. 注册表兜底

判断逻辑：
  · 名字里带 NVIDIA GeForce / RTX / GTX / Quadro  → 独显
  · 带 Radeon RX / Radeon Pro                     → 独显
  · 带 Intel Arc / Arc A/B                       → 独显
  · 带 Intel UHD / HD Graphics / Iris            → 核显
  · 带 AMD Radeon(TM) xxxM / Vega x / 680M 等    → 核显
  · 带 Virtual Display / Basic Render 等         → 忽略（虚拟显卡）
"""
import subprocess
import sys


# 独显关键字（命中则判为独显）
DISCRETE_KEYWORDS = [
    "nvidia", "geforce", "rtx", "gtx", "quadro", "tesla",
    "radeon rx", "radeon pro", "rx 6", "rx 7", "rx 5",
    "intel arc", "arc a", "arc b",
    "gpu", "discrete",
]

# 核显关键字（命中则判为核显）
INTEGRATED_KEYWORDS = [
    "intel(r) uhd", "intel uhd", "intel(r) hd graphics", "hd graphics",
    "iris", "uhd graphics",
    "radeon(tm)", "radeon graphics", "vega", "680m", "660m", "780m", "760m",
    "radeon 610m", "radeon 710m", "radeon 840m", "radeon 880m",
    "microsoft basic display", "microsoft basic render",
]

# 虚拟显卡（直接忽略）
VIRTUAL_KEYWORDS = [
    "virtual", "todesk", "parsec", "spacedesk", "vmware", "virtualbox",
    "citrix", "remote", "mirror", "idd",
]


def _run_ps(cmd, timeout=20):
    """执行 PowerShell 命令"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=timeout,
            creationflags=0x08000000)   # CREATE_NO_WINDOW
        return (r.stdout or "").strip()
    except Exception:
        return ""


def get_gpus():
    """
    获取所有显卡名称。

    返回：list[str]
    """
    names = []

    # 方法1：PowerShell CIM
    out = _run_ps(
        "Get-CimInstance Win32_VideoController | "
        "ForEach-Object { $_.Name }")
    if out:
        names = [ln.strip() for ln in out.splitlines() if ln.strip()]

    # 方法2：wmic 兜底
    if not names:
        try:
            r = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "name"],
                capture_output=True, text=True, timeout=15,
                creationflags=0x08000000)
            for ln in (r.stdout or "").splitlines():
                ln = ln.strip()
                if ln and ln.lower() != "name":
                    names.append(ln)
        except Exception:
            pass

    # 去重 + 过滤空
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

    for k in VIRTUAL_KEYWORDS:
        if k in low:
            return "virtual"

    # 先判独显（优先级高，避免 "Radeon RX" 被当成 "Radeon"）
    for k in DISCRETE_KEYWORDS:
        if k in low:
            # 特例：Intel UHD 里没有独显词，不会误判
            # 特例：AMD "Radeon(TM) Graphics" 不算独显
            if k == "radeon rx":
                return "discrete"
            if k in ("nvidia", "geforce", "rtx", "gtx", "quadro", "tesla"):
                return "discrete"
            if k in ("radeon pro", "intel arc", "arc a", "arc b"):
                return "discrete"
            if k.startswith("rx "):
                return "discrete"

    for k in INTEGRATED_KEYWORDS:
        if k in low:
            return "integrated"

    return "unknown"


def detect():
    """
    检测本机显卡情况。

    返回 dict：
        {
          "all": ["AMD Radeon(TM) 610M", "NVIDIA GeForce RTX 5070 Ti Laptop GPU"],
          "discrete": ["NVIDIA ..."],      独显列表
          "integrated": ["AMD Radeon 610M"], 核显列表
          "active": "NVIDIA ...",           推荐使用的显卡（独显优先）
          "is_integrated_only": False,     是否只有核显
          "warn": "" or "警告文本",
          "display": "要显示在界面上的文字",
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

    # 没有明确独显时，unknown 里的也可能算独显（保守起见列为 unknown）
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
                "检测到当前只有核显（集成显卡），3D 组装界面可能会卡顿。\n"
                "建议在显卡控制面板里为程序指定独立显卡。")
    elif unknown:
        active = unknown[0]
        display = active
        warn = ""
    else:
        active = "未知"
        display = "未检测到显卡"
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
    info = detect()
    print(json.dumps(info, ensure_ascii=False, indent=2))
