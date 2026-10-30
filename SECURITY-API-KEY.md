# 🔒 安全说明：API Key 存在哪里？

> **一句话总结：转发这个文件夹给别人，你的 API Key 不会跟着走。**
> Key 存在你自己电脑的 `%APPDATA%` 里，不在这份代码里。

---

## 你的 Key 实际存在哪里？

```
C:\Users\<你的用户名>\AppData\Roaming\SolidWorksPartGen\config.json
```

这个路径是**每台电脑自己的**。别人拿到你的 `D:\New Program` 文件夹后，
他们电脑上 **没有** 这个文件，所以是空的。

程序第一次运行时，会在**他们自己的电脑上**创建一个新的空配置，
需要他们自己填 Key。

---

## 为什么"每次打开 Key 都在"？

因为**在你自己电脑上**，这个配置文件一直存在，程序启动时自动读回来填进输入框。

这是正常的设计：不是把 Key 存在程序里，而是存在用户的系统配置目录。

```
程序启动
   ↓
读 %APPDATA%\SolidWorksPartGen\config.json
   ↓
有 Key → 自动填到输入框（所以你看到"Key 都在"）
没 Key → 输入框是空的（别人第一次用就是这样）
```

---

## 已验证：代码里没有任何 Key

对以下文件做了全字节扫描（包括 33MB 的 exe）：

| 检查项 | 结果 |
|---|---|
| 源码 `.py` 文件里有无硬编码 Key | ✅ 无 |
| `README.md` / `使用说明.md` 里有无真实 Key | ✅ 无（只有 `sk-...` 占位符） |
| `dist\SolidWorks零件生成器.exe` 二进制里有无 Key | ✅ 无 |
| 打包过程是否把 config.json 打进去 | ✅ 没有（`build.py` 只打包 `gen_py`） |

扫描是拿**真实 Key 的前 10 个字符**去字节流里搜的（UTF-8 和 UTF-16 两种编码都查），
21 个文件全部通过。

---

## 那什么情况下会有风险？

### ⚠️ 唯一需要小心的情况

**不要把 `C:\Users\你的用户名\AppData\Roaming\SolidWorksPartGen\config.json` 发给别人。**

如果有人专门要这个文件（比如"帮我看下配置为什么不对"），
那里面就有明文 Key。这个文件**不属于**项目文件夹，正常转发不会带上。

### ✅ 可以放心发的

- `src\` 整个目录（源代码）
- `dist\SolidWorks零件生成器.exe`
- `README.md`、`docs\`
- `build.py`

---

## 给转发对象的使用步骤

别人拿到文件夹后：

1. 双击 `dist\SolidWorks零件生成器.exe`
2. 点右上角「🔑 填写你的 API Key」
3. **填他们自己的 Key**（去 [platform.deepseek.com](https://platform.deepseek.com) 免费申请）
4. 点「保存」，验证通过即可用

他们的 Key 会存在**他们自己电脑**的 `%APPDATA%` 里，跟你互不影响。

---

## 额外的保险措施

`config.py` 里已经做了：

- **不加密存储**（因为要能跨重启读取），但**只存本机**
- **指纹机制**：记录 Key 的哈希指纹，判断是否换过 Key
  （存的是哈希，不是原文，不会反向泄露）
- 支持随时清空：打开 Key 设置窗口，清空输入框保存即可

### 如果你还是不放心

转发之前，可以手动删掉自己的配置（**只影响你自己这台电脑**）：

```powershell
Remove-Item "$env:APPDATA\SolidWorksPartGen\config.json"
```

删掉后重新打开程序，输入框就是空的 —— 你可以确认这一点之后，
再把文件夹发给别人。（下次填 Key 时它会重新生成。）

---

## 一句话给对方的说明

> 这是我自己写的 SolidWorks 零件生成工具，需要你自己的 AI API Key 才能用。
> Key 去 platform.deepseek.com 免费申请，填进程序右上角就行。
> 程序不会上传你的 Key 到任何地方，只用来直接调用 AI 接口。
