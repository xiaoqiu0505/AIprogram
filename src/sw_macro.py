# -*- coding: utf-8 -*-
"""
sw_macro.py — 生成 SolidWorks 宏（.swp）
========================================
面向**没有安装 SolidWorks 的用户**：不能靠程序调 COM 自动建模，
所以让 AI 生成 VBA 宏代码，用户拿到 .swp 文件后在任意装了 SolidWorks
的电脑上双击运行，就能自动建出装配体。

这个模块负责：
  1. 提供「让 AI 生成宏代码」的提示词
  2. 把 AI 返回的 VBA 代码包成合法的 .swp 文件
  3. 生成配套的中文图文操作步骤
"""
import os
import re
import textwrap
import time


# ==================== AI 提示词 ====================
MACRO_PROMPT = """你是一个 SolidWorks 二次开发专家。

用户已经在一个 3D 界面里把几个零件摆好了位置，导出了「组装图纸」。
你的任务是**生成一段 SolidWorks VBA 宏代码**，用户运行这个宏就能
自动创建出对应的装配体（.SLDASM）。

★★★ 重要背景 ★★★
用户可能**没有安装 SolidWorks**，所以不能依赖外部程序调 COM。
你生成的宏必须是**自包含的 VBA 代码**，用户拿到 .swp 文件后：
  · 在 SolidWorks 里：工具 → 宏 → 运行
  · 或直接双击 .swp 文件
就能自动建出装配体。

★★★ 图纸格式 ★★★
  · "unit": "mm"，所有长度毫米
  · "coordinate_system": 右手系，Y 轴朝上
  · "parts": 零件清单（index / file / path / size_mm 原始尺寸）
  · "instances": 每个零件实例
      - "part_index"：对应 parts 里哪一项
      - "position_mm": [x, y, z] 平移位置
      - "scale"：等比缩放系数（1.0 = 原始大小）
      - "scaled"：是否被用户改过大小
  · "modifications": 被缩放的零件明细

★★★ 宏代码要求 ★★★
1. 用 `Dim swApp As Object` / `Set swApp = Application.SldWorks`
   这种**后期绑定**写法（不需要引用类型库，兼容所有 SW 版本）
2. 开头定义零件路径常量数组 `PART_PATHS`，用户改成自己电脑上的路径
3. 对每个需要缩放的零件：
   · 先 OpenDoc6 打开零件
   · 用 `InsertScale` 或 `FeatureManager.InsertScale` 做**等比缩放**
     （统一缩放，不能变形）
   · 保存并关闭
4. 新建装配体：`swApp.NewDocument(template, 0, 0, 0)`
5. 插入每个零件：`AssemblyDoc.AddComponent5(path, 0, "", False, "", x, y, z)`
   （位置用图纸里的 position_mm，注意 SW 内部单位是**米**，要除 1000）
6. 添加配合：优先用 `AddMate5` 的重合 / 同心
7. 全程 `swApp.CommandInProgress = True` 提速，末尾 False
8. 保存装配体：`swModel.SaveAs3(savePath, 0, 1)`
9. 代码里**所有字符串用双引号**，注释用单引号
10. 最后弹一个 MsgBox 告诉用户成功了

★★★ 输出格式（严格 JSON，不要任何多余文字）★★★
{
  "assembly_name": "立柱支撑架",
  "assembly_name_en": "PillarSupport",
  "summary": "一句话说明这个装配体是什么",
  "macro_code": "完整的 VBA 代码字符串，用 \\n 换行",
  "part_paths": ["C:\\\\Users\\\\xxx\\\\底板.SLDPRT", "..."],
  "steps": [
    {"title": "1. 准备零件", "detail": "把下面这些零件放到同一个文件夹：..."},
    {"title": "2. 修改宏里的路径", "detail": "用记事本打开 .swp 文件，找到 PART_PATHS，改成你自己的路径"},
    {"title": "3. 运行宏", "detail": "在 SolidWorks 里点 工具 → 宏 → 运行，选中这个文件"}
  ],
  "notes": ["注意事项1", "注意事项2"]
}

★ macro_code 里**不能有真正的换行符**，必须用 \\n 转义（JSON 字符串标准）。
★ 如果某个零件不需要缩放，跳过缩放步骤。
★ 宏代码要能在没有打开任何文档的情况下运行。
"""


# ==================== 宏文件封装 ====================
def _clean_vba(code):
    """清理 AI 返回的 VBA 代码（去掉 markdown 代码块标记）"""
    code = code or ""
    # 去掉 ```vba / ```vb / ``` 包裹
    code = re.sub(r"^\s*```(?:vba|vb|visualbasic)?\s*\n", "", code,
                  flags=re.IGNORECASE)
    code = re.sub(r"\n\s*```\s*$", "", code)
    code = code.strip("\n")
    return code


def wrap_vba_as_swp(vba):
    """
    把纯 VBA 代码包装成 SolidWorks 可识别的 .swp 文件。

    SolidWorks 的 .swp 文件是 OLE 复合文档（Compound File Binary），
    里面装着 VBA 工程。真正的 VBA 工程需要 Microsoft VBA 库才能生成。

    ★ 实际做法：生成一个「能被 SolidWorks 宏编辑器识别」的文本式宏。
      SolidWorks 支持导出/导入 .swb（VBA 文本）和 .swp（二进制）。
      为了不需要 VBA 库，我们生成 **.swb 纯文本宏**，
      并用 .swp 作为扩展名的兼容写法：内容为规范的 VBA 源码。

    注意：SolidWorks「工具 → 宏 → 新建」后粘贴代码也能用，
    这是最稳妥的路径，见 steps 里的说明。
    """
    lines = []
    lines.append("' ============================================")
    lines.append("'  SolidWorks 组装宏 —— 由 AI 零件生成器自动生成")
    lines.append(f"'  生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("' ============================================")
    lines.append("' 用法：")
    lines.append("'   1. 打开 SolidWorks")
    lines.append("'   2. 工具 → 宏 → 新建，保存为 xxx.swp")
    lines.append("'   3. 把下面的代码全部粘贴进去，覆盖原内容")
    lines.append("'   4. 按 F5 运行")
    lines.append("' ============================================")
    lines.append("")
    lines.append(vba)
    lines.append("")
    return "\r\n".join(lines)


def save_macro(vba, out_dir, base_name="组装宏"):
    """
    保存宏文件。

    返回 (swp_path, swb_path, txt_path)
      · .swp —— 主文件（内容为 VBA 源码，可直接粘贴使用）
      · .swb —— SolidWorks 文本宏（部分版本可直接导入）
      · .txt —— 纯文本备份，防止编码问题
    """
    os.makedirs(out_dir, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', "_", base_name or "组装宏")
    ts = time.strftime("%Y%m%d_%H%M%S")

    content = wrap_vba_as_swp(vba)

    swb_path = os.path.join(out_dir, f"{safe}_{ts}.swb")
    txt_path = os.path.join(out_dir, f"{safe}_{ts}.txt")
    swp_path = os.path.join(out_dir, f"{safe}_{ts}.swp")

    # .swb / .txt 用 utf-8-sig（记事本友好）
    for p in (swb_path, txt_path):
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            f.write(content)

    # .swp：SolidWorks 期望二进制 VBA 工程，这里写成文本兼容形式，
    # 实际使用走「新建宏后粘贴」，见操作步骤说明。
    with open(swp_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(content)

    return swp_path, swb_path, txt_path


def build_steps_markdown(spec, out_dir):
    """
    把 AI 返回的操作步骤整理成一份中文 Markdown 说明书。
    """
    lines = []
    name = spec.get("assembly_name") or "装配体"
    lines.append(f"# {name} —— 组装操作说明")
    lines.append("")
    lines.append(f"> 自动生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    summary = spec.get("summary")
    if summary:
        lines.append(f"**说明**：{summary}")
        lines.append("")

    parts = spec.get("part_paths") or []
    if parts:
        lines.append("## 用到的零件")
        lines.append("")
        for i, p in enumerate(parts, 1):
            lines.append(f"{i}. `{os.path.basename(p)}`")
        lines.append("")

    steps = spec.get("steps") or []
    if steps:
        lines.append("## 操作步骤")
        lines.append("")
        for s in steps:
            if isinstance(s, dict):
                title = s.get("title") or ""
                detail = s.get("detail") or ""
                if title:
                    lines.append(f"### {title}")
                if detail:
                    lines.append("")
                    lines.append(detail)
                lines.append("")
            else:
                lines.append(f"- {s}")
        lines.append("")

    notes = spec.get("notes") or []
    if notes:
        lines.append("## 注意事项")
        lines.append("")
        for n in notes:
            lines.append(f"- {n}")
        lines.append("")

    lines.append("## 文件说明")
    lines.append("")
    lines.append("- `*.swp` —— 宏文件（用记事本打开，复制里面的代码）")
    lines.append("- `*.swb` —— SolidWorks 文本宏（部分版本可直接导入）")
    lines.append("- `*.txt` —— 纯文本备份")
    lines.append("")

    lib_lines = []
    lib_lines.append("=" * 60)
    lib_lines.append(f"  {name} —— 快速上手")
    lib_lines.append("=" * 60)
    lib_lines.append("")
    lib_lines.append("  第 1 步：准备零件")
    lib_lines.append("    把用到的零件文件放到同一个文件夹")
    lib_lines.append("")
    lib_lines.append("  第 2 步：建宏")
    lib_lines.append("    打开 SolidWorks → 工具 → 宏 → 新建")
    lib_lines.append("    保存为 xxx.swp")
    lib_lines.append("")
    lib_lines.append("  第 3 步：粘贴代码")
    lib_lines.append("    用记事本打开本目录下的 .swp 文件")
    lib_lines.append("    全选复制 → 粘贴到 SolidWorks 宏编辑器")
    lib_lines.append("    把顶部的 PART_PATHS 改成你自己的零件路径")
    lib_lines.append("")
    lib_lines.append("  第 4 步：运行")
    lib_lines.append("    按 F5，或 工具 → 宏 → 运行")
    lib_lines.append("")

    md = "\n".join(lines)
    txt = "\n".join(lib_lines)
    return md, txt
