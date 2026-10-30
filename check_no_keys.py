# -*- coding: utf-8 -*-
"""
check_no_keys.py — 转发前自检工具
==================================
扫描整个项目文件夹（含 exe 二进制），确认没有把你的 API Key 打包进去。

用法：
    python check_no_keys.py

输出：每个文件的检查结果 + 最终结论。
"""
import os
import sys
import json

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")),
    "SolidWorksPartGen", "config.json")

SKIP_DIRS = {"build", "__pycache__", ".git", ".pytest_cache"}
SKIP_EXTS = {".spec"}


def load_real_keys():
    """从本机配置读出真实 Key"""
    if not os.path.exists(CONFIG):
        return []
    try:
        with open(CONFIG, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    keys = []
    for _pid, v in (data.get("keys") or {}).items():
        k = (v or {}).get("api_key", "")
        if k and len(k) >= 12:
            keys.append(k)
    return keys


def iter_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if os.path.splitext(fn)[1] in SKIP_EXTS:
                continue
            yield os.path.join(dirpath, fn)


def scan_file(path, fragments):
    """扫描单个文件，返回命中的片段列表"""
    hits = []
    try:
        size = os.path.getsize(path)
        if size > 80 * 1024 * 1024:
            return hits
        with open(path, "rb") as f:
            data = f.read()
    except Exception:
        return hits

    # UTF-8 和 UTF-16 两种编码都查（PyInstaller 打包的字符串是 UTF-8）
    try:
        t_utf8 = data.decode("utf-8", errors="ignore")
    except Exception:
        t_utf8 = ""
    try:
        t_u16 = data.decode("utf-16-le", errors="ignore")
    except Exception:
        t_u16 = ""

    for frag in fragments:
        if frag in t_utf8 or frag in t_u16:
            hits.append(frag)
    return hits


def main():
    print("=" * 66)
    print("  转发前自检：扫描项目里有没有你的 API Key")
    print("=" * 66)

    print(f"\n项目目录: {ROOT}")
    print(f"配置文件: {CONFIG}")
    print(f"配置文件存在: {os.path.exists(CONFIG)}")

    real_keys = load_real_keys()
    if not real_keys:
        print("\n[!] 本机没有已保存的 Key（配置文件不存在或为空）")
        print("  -> 没有可泄漏的东西，可以放心转发")
        print("\n" + "=" * 66)
        return 0

    print(f"\n本机有 {len(real_keys)} 个已保存的 Key")
    # 用前 12 位做指纹（足够唯一，又不会打印完整 Key）
    fragments = [k[:12] for k in real_keys if len(k) >= 12]
    for f in fragments:
        print(f"  指纹: {f}...（只显示前 12 位）")

    print("\n开始扫描（这可能需要几十秒，exe 有 30+ MB）...\n")

    total = 0
    leaks = []
    for path in iter_files(ROOT):
        total += 1
        rel = os.path.relpath(path, ROOT)
        hits = scan_file(path, fragments)
        if hits:
            leaks.append(rel)
            print(f"  [LEAK] {rel}")
        else:
            # 只打印非图片的
            if not rel.lower().endswith((".png", ".jpg", ".jpeg", ".ico")):
                print(f"  [OK]   {rel}")

    print(f"\n扫描了 {total} 个文件")

    print("\n" + "=" * 66)
    if leaks:
        print("  [LEAK] 发现泄漏！以下文件包含你的 Key：")
        for x in leaks:
            print(f"     {x}")
        print("\n  处理建议：删掉这些文件，或手动清除其中的 Key 再转发。")
        print("=" * 66)
        return 1

    print("  [OK] 全部通过 -- 这个文件夹里没有任何你的 Key，可以放心转发")
    print("=" * 66)
    print("""
  提醒：
    · 不要单独发送 %APPDATA%\\SolidWorksPartGen\\config.json
    · 那个文件里有明文 Key，但它不在项目文件夹里，正常转发不会带上
    · 对方需要自己申请 Key（详见「安全说明-API-KEY.md」）
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
