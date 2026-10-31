# -*- coding: utf-8 -*-
"""
blueprint.py — 组装图纸（Assembly Blueprint）
===============================================
这个 .swbp 文件（JSON 格式）是「组装结果」的完整描述，给 AI 大模型读。

设计目标：
  · 人可读：就是 JSON，打开就能看懂
  · AI 友好：字段名自解释，注释里写清坐标系和单位
  · 完整：包含用了哪些零件、每个零件的位置/缩放、哪些被改过尺寸

文件结构：
{
  "format": "SWPG-Assembly-Blueprint",
  "version": "1.0",
  "created_at": "2026-10-31 16:00:00",
  "unit": "mm",                       ← 所有长度单位
  "coordinate_system": {
     "description": "右手系，Y 轴朝上",
     "axis": {"X": "右", "Y": "上", "Z": "朝向观察者"}
  },

  "parts": [                          ← 用到的所有零件文件
     {
       "index": 0,
       "file": "底板.SLDPRT",          ← 原始文件名
       "path": "C:/Users/.../底板.SLDPRT",
       "format": ".sldprt",
       "size_mm": [90, 10, 80],       ← 原始包围盒
       "volume_mm3": 72000,
       "faces": 6,
       "triangles": 12,
       "mesh_file": "mesh_0.stl"      ← 可选：附带网格
     }
  ],

  "assembly": {
     "part_count": 3,
     "description": "用户组装了哪些零件、放在什么位置"
  },

  "instances": [                      ← 每个零件在场景里的实例
     {
       "id": "inst_0",
       "part_index": 0,
       "name": "底板",
       "position_mm": [0, 0, 0],      ← 平移（相对世界原点）
       "rotation_deg": [0, 0, 0],     ← 旋转（当前版本都是 0）
       "scale": 1.0,                  ← 等比缩放系数（1.0 = 原始大小）
       "scaled": false,               ← 是否被用户改过大小
       "size_mm": [90, 10, 80],       ← 缩放后的包围盒
       "note": ""
     }
  ],

  "modifications": [                  ← ★ 哪些零件被改过尺寸（关键）
     {
       "instance_id": "inst_1",
       "part": "立柱",
       "original_scale": 1.0,
       "new_scale": 1.5,
       "change_percent": 150,
       "original_size_mm": [18, 70, 18],
       "new_size_mm": [27, 105, 27],
       "note": "用户把立柱放大了 1.5 倍（等比缩放，形状不变）"
     }
  ],

  "task": {                           ← 给 AI 的任务说明
     "goal": "把上面这些零件按图纸的位置和大小组装成一个完整的 SolidWorks 装配体",
     "output": "生成 .SLDASM 装配体文件（或按零件分别建模再装配）",
     "constraints": [...]
  }
}
"""
import os
import json
import time


FORMAT_NAME = "SWPG-Assembly-Blueprint"
FORMAT_VERSION = "1.0"


def build_blueprint(instances, parts_meta):
    """
    根据组装场景生成图纸数据。

    参数：
        instances: Viewer3D.items 列表，每项是
            {"name", "part", "pos", "scale", "bbox", "color"}
        parts_meta: 上传时的 parts 列表（含 path / part 信息）

    返回：dict（可直接 json.dump）
    """
    # 按路径索引零件元数据
    meta_by_path = {}
    for it in parts_meta:
        p = it.get("path") or (it.get("part") or {}).get("path")
        if p:
            meta_by_path[os.path.normcase(p)] = it

    parts_out = []
    part_index_by_path = {}     # 路径 → parts_out 索引

    def _get_part_index(inst):
        part = inst.get("part") or {}
        path = part.get("path") or ""
        key = os.path.normcase(path) if path else f"__{id(part)}"
        if key in part_index_by_path:
            return part_index_by_path[key]

        idx = len(parts_out)
        part_index_by_path[key] = idx
        bbox = part.get("bbox")
        parts_out.append({
            "index": idx,
            "file": part.get("name") or inst.get("name", "part"),
            "path": path,
            "format": part.get("ext") or os.path.splitext(path)[1].lower(),
            "size_mm": [round(v, 3) for v in bbox] if bbox else None,
            "volume_mm3": round(float(part.get("volume_mm3") or 0), 2),
            "faces": int(part.get("faces") or 0),
            "triangles": len(part.get("triangles") or []),
        })
        return idx

    instances_out = []
    modifications = []

    for i, inst in enumerate(instances):
        part = inst.get("part") or {}
        pidx = _get_part_index(inst)
        scale = float(inst.get("scale", 1.0))
        pos = inst.get("pos") or (0, 0, 0)
        bbox = part.get("bbox")
        scaled_bbox = ([round(v * scale, 3) for v in bbox] if bbox else None)

        inst_id = f"inst_{i}"
        scaled = abs(scale - 1.0) > 1e-6

        instances_out.append({
            "id": inst_id,
            "part_index": pidx,
            "part_file": parts_out[pidx]["file"],
            "position_mm": [round(float(v), 3) for v in pos],
            "rotation_deg": [0, 0, 0],
            "scale": round(scale, 6),
            "scaled": scaled,
            "size_mm": scaled_bbox,
        })

        if scaled:
            modifications.append({
                "instance_id": inst_id,
                "part": parts_out[pidx]["file"],
                "original_scale": 1.0,
                "new_scale": round(scale, 6),
                "change_percent": round(scale * 100, 1),
                "original_size_mm": [round(v, 3) for v in bbox] if bbox else None,
                "new_size_mm": scaled_bbox,
                "note": f"用户把「{parts_out[pidx]['file']}」"
                        f"等比缩放到 {scale * 100:.0f}%（形状比例不变，只是整体变大/变小）",
            })

    # 场景整体包围盒
    scene_box = None
    if instances:
        xs, ys, zs = [], [], []
        for inst in instances:
            part = inst.get("part") or {}
            bbox = part.get("bbox")
            if not bbox:
                continue
            s = float(inst.get("scale", 1.0))
            px, py, pz = inst.get("pos") or (0, 0, 0)
            xs += [px - bbox[0] * s / 2, px + bbox[0] * s / 2]
            ys += [py - bbox[1] * s / 2, py + bbox[1] * s / 2]
            zs += [pz - bbox[2] * s / 2, pz + bbox[2] * s / 2]
        if xs:
            scene_box = [round(max(xs) - min(xs), 2),
                         round(max(ys) - min(ys), 2),
                         round(max(zs) - min(zs), 2)]

    scaled_n = len(modifications)
    desc = f"用户把 {len(instances_out)} 个零件摆放成这个组装形态"
    if scaled_n:
        desc += f"，其中 {scaled_n} 个零件被等比缩放过"

    data = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "unit": "mm",
        "coordinate_system": {
            "handedness": "右手系",
            "axis": {"X": "向右", "Y": "向上", "Z": "朝向观察者"},
            "note": "所有 position_mm / size_mm 都基于这个坐标系，单位毫米",
        },
        "assembly": {
            "part_count": len(parts_out),
            "instance_count": len(instances_out),
            "scaled_count": scaled_n,
            "scene_size_mm": scene_box,
            "description": desc,
        },
        "parts": parts_out,
        "instances": instances_out,
        "modifications": modifications,
        "task": {
            "goal": "根据这份图纸，在 SolidWorks 里把下面这些零件装配成一个完整的装配体",
            "how": [
                "1. 每个 parts 条目对应一个源零件文件，按 path 打开（或用同名文件）",
                "2. instances 里每条描述一个零件实例的位置和缩放",
                "3. 缩放是「等比缩放」——只改变整体大小，形状比例保持不变",
                "4. modifications 明确列出哪些零件被缩放过、从多少变到多少",
                "5. 按 position_mm 摆放各零件，形成图纸描述的组装关系",
            ],
            "output": "生成 .SLDASM 装配体（存到用户设置的位置）",
            "important": [
                "缩放要用 SolidWorks 的「缩放特征」(Insert > Features > Scale)，"
                "选择「统一缩放」模式，避免变形",
                "装配时优先用「重合」「同心」「距离」等标准配合",
                "位置基于右手坐标系，Y 轴朝上",
            ],
        },
    }
    return data


def save_blueprint(data, path):
    """把图纸写成 .swbp 文件（JSON）"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def load_blueprint(path):
    """读取 .swbp 文件"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def blueprint_to_prompt(data):
    """
    把图纸转成给 AI 的提示文本（比原始 JSON 更好读）。
    """
    lines = []
    a = data.get("assembly", {})
    lines.append("【组装图纸】")
    lines.append(f"零件总数：{a.get('part_count', 0)} 个")
    lines.append(f"实例数：{a.get('instance_count', 0)} 个")
    if a.get("scene_size_mm"):
        s = a["scene_size_mm"]
        lines.append(f"整体尺寸：{s[0]} × {s[1]} × {s[2]} mm")
    lines.append("")

    lines.append("【零件清单】")
    for p in data.get("parts", []):
        sz = p.get("size_mm")
        szs = f"{sz[0]}×{sz[1]}×{sz[2]} mm" if sz else "未知"
        lines.append(f"  [{p['index']}] {p['file']}　原始尺寸 {szs}"
                     f"　面数 {p.get('faces', 0)}")
    lines.append("")

    lines.append("【摆放位置】")
    for inst in data.get("instances", []):
        pos = inst.get("position_mm", [0, 0, 0])
        sc = inst.get("scale", 1.0)
        sz = inst.get("size_mm")
        szs = f"{sz[0]}×{sz[1]}×{sz[2]} mm" if sz else "—"
        mark = "　★已缩放" if inst.get("scaled") else ""
        lines.append(
            f"  {inst['id']}　{inst['part_file']}　"
            f"位置 ({pos[0]}, {pos[1]}, {pos[2]})　"
            f"缩放 {sc:.3f}×　实际尺寸 {szs}{mark}")
    lines.append("")

    mods = data.get("modifications", [])
    if mods:
        lines.append("【★ 被缩放修改过的零件】")
        for m in mods:
            o = m.get("original_size_mm")
            n = m.get("new_size_mm")
            os_ = "×".join(str(x) for x in o) if o else "—"
            ns_ = "×".join(str(x) for x in n) if n else "—"
            lines.append(
                f"  {m['part']}：{m['original_scale']:.1f}× → "
                f"{m['new_scale']:.3f}×（{m['change_percent']}%）")
            lines.append(f"      尺寸 {os_} mm → {ns_} mm")
            lines.append(f"      说明：{m.get('note', '')}")
        lines.append("")
    else:
        lines.append("【缩放修改】无，所有零件都是原始大小")
        lines.append("")

    t = data.get("task", {})
    lines.append("【任务】")
    lines.append(t.get("goal", ""))
    for step in t.get("how", []):
        lines.append(f"  {step}")
    lines.append(f"  输出：{t.get('output', '')}")
    return "\n".join(lines)
