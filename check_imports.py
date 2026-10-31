# -*- coding: utf-8 -*-
"""
check_imports.py — 检查「用了但没导入」的模块
==============================================
这类错误在源码里跑测试时容易漏掉（因为测试脚本可能自己 import 了），
但打包成 exe 后就会直接崩溃，比如 name 'json' is not defined。

用法：
    python check_imports.py

输出：每个文件的检查结果，有问题会列出具体位置。
"""
import os
import ast
import sys

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")

# 常见标准库 → 典型用法（用于判断"是否真的用了"）
COMMON_MODULES = {
    "json": ["json.dump", "json.load", "json.dumps", "json.loads"],
    "os": ["os.path", "os.environ", "os.makedirs", "os.remove",
           "os.startfile", "os.listdir", "os.walk", "os.stat",
           "os.getcwd", "os.chdir", "os.rename", "os.mkdir"],
    "sys": ["sys.executable", "sys.argv", "sys.path", "sys.exit",
            "sys.frozen", "sys.modules", "sys.platform", "sys.stderr"],
    "time": ["time.time", "time.strftime", "time.sleep", "time.strptime"],
    "math": ["math.sqrt", "math.cos", "math.sin", "math.atan",
             "math.radians", "math.degrees", "math.hypot", "math.pi"],
    "threading": ["threading.Thread", "threading.Lock"],
    "traceback": ["traceback.format_exc", "traceback.print_exc"],
    "struct": ["struct.unpack", "struct.pack"],
    "re": ["re.search", "re.match", "re.sub", "re.findall", "re.compile"],
    "base64": ["base64.b64encode", "base64.b64decode"],
    "hashlib": ["hashlib.md5", "hashlib.sha"],
    "tempfile": ["tempfile.gettempdir", "tempfile.mkstemp"],
    "subprocess": ["subprocess.run", "subprocess.Popen"],
    "shutil": ["shutil.copy", "shutil.rmtree", "shutil.move"],
    "random": ["random.random", "random.randint", "random.choice"],
}


def check_file(path):
    """检查单个文件，返回问题列表"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
    except Exception as e:
        return [f"读取失败：{e}"]

    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [f"语法错误：{e}"]

    # 收集已导入的顶层模块名
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                imported.add(a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            if n.module:
                imported.add(n.module.split(".")[0])
        # 函数内 import 也算
        elif isinstance(n, ast.Call):
            pass

    # ast 已经把嵌套 import 都遍历到了，再补一次显式扫描
    for line in src.splitlines():
        s = line.strip()
        if s.startswith("import "):
            mod = s[7:].split()[0].split(",")[0].strip()
            imported.add(mod.split(".")[0])
        elif s.startswith("from ") and " import " in s:
            mod = s[5:].split()[0].strip()
            if mod:
                imported.add(mod.split(".")[0])

    problems = []
    for mod, usages in COMMON_MODULES.items():
        if mod in imported:
            continue
        for u in usages:
            if u in src:
                problems.append(f"用了 `{u}` 但没 import {mod}")
                break

    return problems


def main():
    print("=" * 62)
    print("  检查「用了但没导入」的模块")
    print("=" * 62)
    print()

    files = sorted(f for f in os.listdir(SRC) if f.endswith(".py"))
    bad = 0

    for fn in files:
        path = os.path.join(SRC, fn)
        problems = check_file(path)
        if problems:
            bad += 1
            print(f"[X] {fn}")
            for p in problems:
                print(f"      {p}")
        else:
            print(f"[OK] {fn}")

    print()
    print("=" * 62)
    if bad:
        print(f"  发现 {bad} 个文件有缺失导入，会导致 exe 崩溃")
        print("=" * 62)
        return 1
    print("  所有文件导入完整")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
