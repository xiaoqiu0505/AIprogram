# -*- coding: utf-8 -*-
"""
build.py — 打包成 .exe
========================
用法：python build.py
输出：dist/SolidWorks零件生成器.exe
"""
import os
import sys
import shutil
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
DIST = os.path.join(ROOT, "dist")
BUILD = os.path.join(ROOT, "build")
ICON = os.path.join(ROOT, "docs", "app.ico")

APP_NAME = "SolidWorks零件生成器"
MAIN = os.path.join(SRC, "app.py")


def clean():
    for d in (DIST, BUILD):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    for f in os.listdir(ROOT):
        if f.endswith(".spec"):
            os.remove(os.path.join(ROOT, f))


def build():
    print("=" * 60)
    print("  打包 SolidWorks 零件生成器")
    print("=" * 60)

    clean()

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",                       # 单文件 exe
        "--windowed",                      # 无黑框
        "--name", APP_NAME,
        "--distpath", DIST,
        "--workpath", BUILD,
        "--specpath", ROOT,
        "--paths", SRC,
        "--hidden-import", "win32com",
        "--hidden-import", "win32com.client",
        "--hidden-import", "pythoncom",
        "--hidden-import", "pywintypes",
        "--hidden-import", "requests",
        "--hidden-import", "PIL",
        "--hidden-import", "PIL.Image",
        "--hidden-import", "PIL.ImageTk",
        # ★ 项目内模块：都是运行时动态 import 的，PyInstaller 静态分析会漏掉
        "--hidden-import", "assembly",
        "--hidden-import", "blueprint",
        "--hidden-import", "gpu_info",
        "--hidden-import", "part_reader",
        "--hidden-import", "sketchpad",
        "--hidden-import", "filedrop",
        "--hidden-import", "sw_builder",
        "--hidden-import", "api_client",
        "--hidden-import", "config",
        "--collect-submodules", "win32com",
        MAIN,
    ]

    # PyInstaller 6 需要显式收集 gen_py 缓存
    import win32com
    gen_path = win32com.__gen_path__
    if os.path.isdir(gen_path):
        args += ["--add-data", f"{gen_path};gen_py"]
        print(f"  已包含 COM 绑定缓存: {gen_path}")

    if os.path.exists(ICON):
        args += ["--icon", ICON]

    print("  执行:", " ".join(args[:6]), "...")
    r = subprocess.run(args, cwd=ROOT)
    if r.returncode != 0:
        print("\n[FAIL] 打包失败")
        return False

    exe = os.path.join(DIST, APP_NAME + ".exe")
    if os.path.exists(exe):
        size_mb = os.path.getsize(exe) / 1024 / 1024
        print()
        print("=" * 60)
        print(f"  ✓ 打包成功")
        print(f"  {exe}")
        print(f"  大小: {size_mb:.1f} MB")
        print("=" * 60)
        return True
    else:
        print("\n[FAIL] 未找到输出文件")
        return False


if __name__ == "__main__":
    ok = build()
    sys.exit(0 if ok else 1)
