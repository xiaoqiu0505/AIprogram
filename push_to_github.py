# -*- coding: utf-8 -*-
"""
push_to_github.py — 一键同步到 GitHub
=====================================
把本地改动提交并推送到 https://github.com/xiaoqiu0505/AIprogram

用法（在 D:\\New Program 目录下）：
    python push_to_github.py

如果网络不通，脚本会提示你用什么办法解决。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
REMOTE = "https://github.com/xiaoqiu0505/AIprogram.git"


def run(cmd, check=True):
    """执行命令，返回 (返回码, 输出)"""
    print(f"  $ {cmd}")
    p = subprocess.run(cmd, shell=True, cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    if out.strip():
        for line in out.strip().splitlines():
            print(f"    {line}")
    return p.returncode, out


def main():
    print("=" * 66)
    print("  同步到 GitHub")
    print("=" * 66)

    # 0. 检查仓库
    if not os.path.isdir(os.path.join(ROOT, ".git")):
        print("\n[!] 这个目录不是 git 仓库")
        return 1

    # 1. 确保 remote 地址正确
    print("\n[1/5] 检查远程地址")
    rc, out = run("git remote get-url origin", check=False)
    if rc != 0:
        run(f'git remote add origin "{REMOTE}"')
    elif REMOTE not in out:
        print(f"  -> 修正为 {REMOTE}")
        run(f'git remote set-url origin "{REMOTE}"')
    else:
        print("  OK")

    # 2. 安全扫描（关键！）
    print("\n[2/5] 扫描是否有 API Key 泄漏")
    rc, out = run("python check_no_keys.py", check=False)
    if rc != 0:
        print("\n[!] 扫描发现问题，已中止推送")
        return 1

    # 3. 提交本地改动
    print("\n[3/5] 提交本地改动")
    rc, out = run("git add -A", check=False)
    rc, out = run("git status --porcelain", check=False)
    if out.strip():
        msg = input("  提交说明（直接回车用默认）: ").strip()
        if not msg:
            msg = "更新"
        run(f'git commit -m "{msg}"', check=False)
    else:
        print("  没有新改动需要提交")

    # 4. 推送
    print("\n[4/5] 推送到 GitHub")
    rc, out = run("git push -u origin main", check=False)

    if rc != 0:
        print("\n" + "=" * 66)
        print("  [!] 推送失败")
        print("=" * 66)
        low = out.lower()
        if "connection was reset" in low or "could not resolve" in low \
                or "timed out" in low or "failed to connect" in low:
            print("""
  原因：连不上 github.com（国内网络常见）

  解决办法（任选一个）：
    1. 开代理/VPN，然后重试这个脚本
    2. 用网页上传（https://github.com/xiaoqiu0505/AIprogram/upload/main）
       注意：网页单文件限制 25 MB，exe 传不上去
    3. 换用 SSH 方式（需要先配置 SSH key）
""")
        elif "authentication failed" in low or "403" in low or "401" in low:
            print("""
  原因：身份认证失败

  解决办法：
    1. 去 https://github.com/settings/tokens 生成 Personal Access Token
       （勾选 repo 权限）
    2. 推送时用户名填你的 GitHub 用户名，密码粘这个 Token
""")
        elif "rejected" in low or "non-fast-forward" in low:
            print("""
  原因：远程有你本地没有的提交（可能是网页上传产生的）

  解决办法：
    git pull origin main --allow-unrelated-histories
    python push_to_github.py
""")
        else:
            print("  完整错误见上方输出")
        return 1

    # 5. 完成
    print("\n[5/5] 完成")
    print("\n" + "=" * 66)
    print("  [OK] 推送成功！")
    print("=" * 66)
    print(f"""
  查看仓库: https://github.com/xiaoqiu0505/AIprogram

  提示：33 MB 的 exe 第一次推送会比较慢（几分钟），耐心等。
        之后只传改动过的文件，会快很多。
""")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n已取消")
        sys.exit(1)
