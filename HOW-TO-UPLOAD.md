# 上传到 GitHub 的步骤

> 项目已经初始化好 git 仓库并完成首次提交。
> 下面两条路任选一条。

---

## 先回答：压缩包发出去安全吗？

**安全。** 我用真实流程验证过：

1. 完整复制 `D:\New Program` → 226MB（当时还含一个 73MB 旧 zip 和 41MB build 缓存）
2. 检查副本里有没有 `config.json` → **没有**
3. 扫描副本所有文本文件 → **没有真实 Key**
4. 拿真实 Key 前 12 位去 23 个文件的字节流里搜（UTF-8 + UTF-16 双编码）→ **零命中**

**为什么你每次打开 Key 都在？**
因为 Key 存在 `C:\Users\86135\AppData\Roaming\SolidWorksPartGen\config.json`
（`%APPDATA%` 目录），**不在项目文件夹里**。
对方电脑上没有这个文件，对他们就是全新的空配置。

**唯一注意**：不要单独把那个 `config.json` 发出去（它不在项目里，正常打包不会带上）。

---

## 清理后的项目结构（35.1 MB）

```
D:\New Program\
├── .gitignore                    ← 防止误传敏感文件
├── README.md                     ← 主文档（34 KB）
├── 安全说明-API-KEY.md            ← Key 安全说明
├── build.py                      ← 打包脚本
├── check_no_keys.py              ← 转发前自检工具
├── src\                          ← 源代码（6 个文件，178 KB）
│   ├── app.py                    ← GUI 主程序
│   ├── api_client.py             ← 五家 AI 接口
│   ├── config.py                 ← 配置与 Key 管理
│   ├── sw_builder.py             ← SolidWorks 建模器
│   ├── sketchpad.py              ← 手绘画布
│   └── filedrop.py               ← 文件拖放
├── docs\                         ← 文档和截图（1.6 MB）
└── dist\                         ← 可执行文件（33.2 MB）
    └── SolidWorks零件生成器.exe
```

**删掉的**（都是垃圾，不用上传）：
- `CAD for everyone_v1.0.zip`（73 MB 旧打包）
- `CAD for everyone_v1.0\`（旧副本）
- `build\`（PyInstaller 中间文件 41.7 MB）
- `__pycache__\`、`*.spec`

---

## 方案一：网页上传（最简单，适合第一次）

### 1. 在 GitHub 创建仓库

打开 https://github.com/new

- **Repository name**：`solidworks-part-gen`（或你喜欢的名字）
- **Description**：AI 生成 SolidWorks 零件的桌面工具
- **Public / Private**：自己选
- ⚠️ **不要**勾选 "Add a README file"、"Add .gitignore"、"Choose a license"
  （因为本地已经有了，勾了会冲突）
- 点 **Create repository**

### 2. 上传文件

新仓库页面会显示命令提示。选 **"uploading an existing file"** 链接。

但网页上传有 **25 MB 单文件限制**，你的 exe 是 33 MB，**传不上去**。

所以网页方案只能传源码（不含 exe）：

1. 打开 https://github.com/你的用户名/仓库名/upload/main
2. 把 `src`、`docs`、`README.md`、`build.py`、`check_no_keys.py`、
   `安全说明-API-KEY.md`、`.gitignore` 拖进去
3. **不要**传 `dist\`
4. 提交

exe 用 **Releases** 发布：
- 仓库页面右侧 → **Releases** → **Create a new release**
- Tag 填 `v2.5`，标题填 `v2.5 首个版本`
- 把 `dist\SolidWorks零件生成器.exe` 拖到下面的附件区
- **Publish release**

---

## 方案二：命令行推送（推荐，能带 exe）

exe 33 MB 小于 GitHub 单文件 100 MB 限制，可以直接用 git 推上去。

### 1. GitHub 创建空仓库

同方案一第 1 步（同样不要勾任何初始化选项）。

### 2. 本地已经提交好了，直接推送

打开 PowerShell：

```powershell
cd "D:\New Program"

# 换成你自己的仓库地址
git remote add origin https://github.com/你的用户名/solidworks-part-gen.git

# 推上去
git branch -M main
git push -u origin main
```

第一次推送会弹出 GitHub 登录窗口，按提示授权即可。

> 如果提示需要密码，去 https://github.com/settings/tokens 生成一个
> Personal Access Token（勾 `repo` 权限），当作密码粘贴进去。

### 3. 如果 33MB 的 exe 推得很慢

可以用 Git LFS（大文件专用存储）：

```powershell
git lfs install
git lfs track "*.exe"
git add .gitattributes
git commit -m "用 LFS 管理 exe"
git push -u origin main
```

---

## 上传前最后检查一次

```powershell
cd "D:\New Program"
python check_no_keys.py
```

看到这个就放心：

```
[OK] 全部通过 -- 这个文件夹里没有任何你的 Key，可以放心转发
```

---

## 上传完成后

给别人分享：

- **代码**：`https://github.com/你的用户名/仓库名`
- **直接下载 exe**：仓库右侧 **Releases** 页面

对方下载 exe 后，双击运行，点右上角「🔑 填写你的 API Key」，
填**他自己的** Key 即可使用。

---

## 常见问题

**Q：以后改了代码怎么更新？**

```powershell
cd "D:\New Program"
git add -A
git commit -m "描述你改了什么"
git push
```

**Q：不想公开代码怎么办？**

创建仓库时选 **Private**。之后可以在 Settings → General → Danger Zone
→ Change visibility 改成 Public。

**Q：exe 想更新到 Release 怎么办？**

重新 `python build.py` 打包，然后到 Releases 页面新建一个 release
（比如 v2.6），把新 exe 传上去。

**Q：我担心把 Key 传上去了**

随时运行 `python check_no_keys.py` 检查。
如果真的传上去了（虽然不可能），立刻去 AI 平台后台**吊销那个 Key**，
然后重新申请一个。吊销是唯一彻底的补救方式。
