# -*- coding: utf-8 -*-
"""
api_client.py — 多服务商 AI 客户端
====================================
统一封装三家大模型，接口风格保持一致：

  · DeepSeek  — https://api-docs.deepseek.com  （国产，多模态 + 深度思考）
  · Claude    — https://docs.anthropic.com      （Anthropic Messages API）
  · ChatGPT   — https://platform.openai.com     （OpenAI Chat Completions）

对外统一提供：
  verify_key(api_key, provider)           → (ok, message)
  analyze_part(api_key, text, image, ...) → dict（建模 JSON）
"""
import base64
import json
import os
import re

import requests

import config as cfg

API_TIMEOUT = cfg.API_TIMEOUT


class APIError(Exception):
    """API 调用异常"""
    def __init__(self, message, status_code=None, provider=None):
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider


# ==================== 通用工具 ====================
def _encode_image(image_path: str):
    """把图片编码成 (base64_data, media_type)"""
    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif",
        ".webp": "image/webp", ".bmp": "image/png",
    }
    mime = mime_map.get(ext, "image/jpeg")

    with open(image_path, "rb") as f:
        raw = f.read()

    if len(raw) > 32 * 1024 * 1024:
        raise APIError("图片文件过大（超过 32MB），请压缩后再试")

    return base64.b64encode(raw).decode("utf-8"), mime


def _short_err(r, provider: str) -> str:
    """从响应中提取简洁的错误信息"""
    try:
        j = r.json()
    except Exception:
        return (r.text or "")[:200]

    # 各家错误结构不同
    if isinstance(j, dict):
        e = j.get("error")
        if isinstance(e, dict):
            return e.get("message") or e.get("type") or str(e)[:200]
        if isinstance(e, str):
            return e
        if "message" in j:
            return str(j["message"])[:200]
    return str(j)[:200]


# ==================== 各家请求构造 ====================
def _build_verify_request(provider: str, api_key: str):
    """构造校验 Key 的最小请求：返回 (url, headers, payload)"""
    info = cfg.get_provider_info(provider)

    if info.get("api_type") == "anthropic":
        # Anthropic Messages API（Claude）
        url = f"{info['base_url']}/v1/messages"
        headers = {
            "x-api-key": api_key.strip(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": info["model"],
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
        }
        return url, headers, payload

    # OpenAI 兼容（DeepSeek / Qwen / Kimi / ChatGPT）
    url = f"{info['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": info["model"],
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }
    # DeepSeek 支持关闭思考以加快校验
    if info.get("reasoning") and provider == "deepseek":
        payload["thinking"] = {"type": "disabled"}
    return url, headers, payload


def verify_key(api_key: str, provider: str = "deepseek"):
    """
    校验指定服务商的 API Key。
    返回 (ok: bool, message: str)
    """
    provider = provider if provider in cfg.PROVIDERS else "deepseek"
    info = cfg.get_provider_info(provider)

    if not api_key or not api_key.strip():
        return False, f"请输入 {info['name']} 的 API Key"

    url, headers, payload = _build_verify_request(provider, api_key)
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=40)
    except requests.exceptions.Timeout:
        return False, f"连接 {info['name']} 超时，请检查网络"
    except requests.exceptions.ConnectionError:
        return False, f"无法连接 {info['name']} 服务器，请检查网络或代理"
    except Exception as e:
        return False, f"网络异常：{e}"

    if r.status_code == 200:
        return True, f"{info['name']} API Key 有效"

    msg = _short_err(r, provider)

    if r.status_code in (401, 403):
        prefix = f"（{info['name']} Key 应以 {info['key_prefix']} 开头）" \
            if info.get("key_prefix") else ""
        return False, f"{info['name']} API Key 无效或已过期{prefix}"
    if r.status_code == 402:
        return False, f"{info['name']} 账户余额不足，请前往 {info['doc']} 充值"
    if r.status_code == 429:
        return False, f"{info['name']} 请求过于频繁或额度已用完，请稍后再试"
    if r.status_code == 404:
        return False, f"{info['name']} 模型不可用（{info['model']}），可能需要开通权限"
    return False, f"{info['name']} 校验失败（HTTP {r.status_code}）：{msg}"


# ==================== 零件分析 ====================
SYSTEM_PROMPT = """你是一个 SolidWorks 零件编写专家。

你的任务：根据用户提供的图片或文字描述，设计一个可以在 SolidWorks 中自动建模的零件。

你必须只输出一个 JSON 对象（不要输出任何其他文字、不要用 markdown 代码块），格式如下：

{
  "part_name": "零件的中文名称",
  "part_name_en": "EnglishNameForFile",
  "summary": "一句话说明这个零件是什么、用途",
  "material": "推荐材料（如 45钢、304不锈钢、ABS）",
  "features": [ ... ],
  "dimensions": [ {"name":"总长","value":100,"unit":"mm"} ],
  "notes": "设计说明"
}

支持的特征类型（type）：

★★★ 坐标系约定（必须严格遵守）★★★

草图平面都在 Z=0 平面（前视基准面），X 向右、Y 向上、Z 指向观察者。

**凸台拉伸默认"两侧对称"**（centered=true 是默认值）：
  · 拉伸 depth=100 → 实体在 Z 方向范围是 -50 ~ +50（居中于原点）
  · 所以：**零件中心在原点，各方向范围是 ±尺寸/2**

举例：边长 100 的立方体
  · extrude rectangle width=100,height=100, center_x=0, center_y=0, depth=100
  · 实际坐标范围：X: -50~+50, Y: -50~+50, Z: -50~+50
  · 六个面的位置：X=+50(右面), X=-50(左面), Y=+50(顶面), Y=-50(底面),
                  Z=+50(前面), Z=-50(后面)

**在面上挖坑的正确写法**：
  · 在顶面(Y=+50)挖坑 → 草图用 plane="top"（上视基准面，即 Y=0 平面），
    圆/矩形 center_x=0, center_y=0（草图的 y 对应 Z 轴位置），
    direction="blind", depth=15
  · 在前表面(Z=+50)挖坑 → 草图用 plane="front"（Z=0 平面），
    direction="blind", depth=15
  · 在右面(X=+50)挖坑 → 草图用 plane="right"（右视基准面，即 X=0 平面），
    direction="blind", depth=15

**重要**：挖坑草图的 center_x / center_y 是相对**该草图平面原点**的偏移，
不是在零件上的绝对坐标。因为草图平面都通过原点，所以 center=0 就是零件中心线上。

1. "extrude" 拉伸凸台
   sketch.shape: "rectangle" (width,height,center_x,center_y)
               | "circle" (radius,center_x,center_y)
               | "polygon" (sides, circumradius 或 across_flats, start_angle)
   depth: 深度 mm
   centered: true（默认，两侧对称居中）| false（单向）
   direction: "blind" | "through_all"
   flip: 可选，反向

2. "cut" 拉伸切除（参数同 extrude）
   direction: "blind"（盲孔，depth 指定深度）| "through_all"（完全贯穿）
   挖坑时一般用 blind + depth

3. "revolve" 旋转特征（回转体：杯子、瓶子、盘子、圆锥、圆柱、轮子、轴）
   profile: [[x,y],...]  剖面点（mm），x=半径（>=0），y=高度，绕 Y 轴旋转
   angle: 旋转角度（默认 360）
   示例 - 实心圆锥台: [[0,0],[60,0],[10,100],[0,100]]
   示例 - 直圆柱:     [[0,0],[50,0],[50,100],[0,100]]
   注意：revolve 的 y=0 是底面，向上生长；如需居中可后续调整

4. "shell" 抽壳（把实体挖空成薄壁）
   thickness: 壁厚 mm
   outward: false
   remove_faces: "top"(顶部开口，做杯子) | "bottom" | "none" | "largest"

5. "fillet" 圆角
   radius: mm
   target: "vertical_edges" | "top_edges" | "all_edges"

6. "chamfer" 倒角
   distance: mm, angle: 角度(默认45)
   target: 同上

★ 形状选择指南
- 回转体（杯/碗/瓶/盘/圆锥/圆柱/轮/轴）→ "revolve"
- 带内腔的容器（杯子/盒子）→ "revolve" + "shell"
- 方形板件、六角螺母 → "extrude"
- 法兰盘 → "revolve" + "cut"

坐标系：X 向右、Y 向上、Z 向外。剖面草图用 x=半径、y=高度。
所有尺寸单位是毫米（mm）。零件要符合工程常识，尽量遵守国家标准（GB）。
features 数组按建模顺序排列。如果给了图片，仔细识别形状、比例、特征。
如果是标准件（螺母、螺栓、垫圈），使用国标尺寸。

典型示例 - 杯子：
{
  "part_name": "带手柄塑料杯", "part_name_en": "PlasticCup",
  "summary": "圆锥台杯身 + 环形把手的塑料水杯",
  "material": "PP",
  "features": [
    {"type":"revolve","desc":"圆锥杯身","angle":360,
     "profile":[[0,0],[26,0],[46,80],[0,80]]},
    {"type":"shell","desc":"抽壳2.5mm顶部开口","thickness":2.5,
     "outward":false,"remove_faces":"top"},
    {"type":"extrude","desc":"把手基板",
     "sketch":{"plane":"front","shape":"rectangle",
               "params":{"width":38,"height":38,"center_x":-70,"center_y":45}},
     "depth":12,"direction":"blind"},
    {"type":"cut","desc":"把手握孔",
     "sketch":{"plane":"front","shape":"circle",
               "params":{"radius":11,"center_x":-70,"center_y":45}},
     "direction":"through_all"}
  ],
  "dimensions":[{"name":"杯口外径","value":92,"unit":"mm"},
                {"name":"杯底外径","value":52,"unit":"mm"},
                {"name":"总高","value":80,"unit":"mm"}]
}

典型示例 - 六角螺母：
{
  "part_name": "六角螺母M10", "part_name_en": "HexNutM10",
  "summary": "GB/T 6170 M10 六角螺母", "material": "8级碳钢",
  "features": [
    {"type":"extrude","desc":"六棱柱",
     "sketch":{"plane":"front","shape":"polygon",
               "params":{"sides":6,"across_flats":16}},
     "depth":8,"direction":"blind"},
    {"type":"chamfer","desc":"棱边倒角","distance":1,"target":"vertical_edges"},
    {"type":"cut","desc":"中心通孔",
     "sketch":{"plane":"top","shape":"circle","params":{"radius":4.25}},
     "direction":"through_all"}
  ],
  "dimensions":[{"name":"对边宽度","value":16,"unit":"mm"},
                {"name":"厚度","value":8,"unit":"mm"}]
}
"""


def _build_analyze_text(text_desc: str, has_image: bool, is_sketch: bool,
                        is_three_view: bool = False) -> str:
    """组装给模型的文字提示"""
    if is_three_view:
        t = ("这是一个用户手绘的零件**三视图**，共三张图，顺序是：\n"
             "  第 1 张 = 主视图（正视图，从正面看）\n"
             "  第 2 张 = 侧视图（从左侧看）\n"
             "  第 3 张 = 俯视图（从上方看）\n"
             "**每张图的右下角都有文字标注（如「主视图」），可直接据此识别。**\n\n"
             "★ **颜色约定（非常重要）**：\n"
             "  · **红色线条 = 贯穿特征**（孔、槽等通透的部分），"
             "建模时必须用 direction=\"through_all\"\n"
             "  · **黑色线条 = 普通轮廓**（外形边界、非贯穿的坑槽）\n"
             "  · **蓝色 / 绿色 = 辅助说明线或标注**，通常不是实体轮廓\n\n"
             "请根据这三个视图综合推断零件的三维形状，生成 solidworks 文件。")
        if text_desc.strip():
            t += f"\n\n用户补充说明：{text_desc.strip()}"
        t += ("\n\n【推断方法】\n"
              "1. 主视图给出 X（长）和 Y（高）\n"
              "2. 俯视图给出 X（长）和 Z（宽/深）\n"
              "3. 侧视图给出 Z（宽）和 Y（高）\n"
              "4. 三视图必须满足「长对正、高平齐、宽相等」\n\n"
              "【识别要点】\n"
              "· 视图中画成**圆**的封闭曲线 → 大概率是孔或圆柱特征\n"
              "· 视图中画成**正方形/多边形**的 → 是方形/多边形凹槽或凸台\n"
              "· 主视图是矩形、俯视图也是矩形 → 基本形体是长方体\n"
              "· 三个视图都是圆 → 球体或圆柱\n"
              "· 主视图是圆、侧视图和俯视图是矩形 → 圆柱（轴线沿 X）\n\n"
              "【尺寸处理】\n"
              "· 手绘线条不精确，请按工程常识取整（如 2、5、10 的倍数）\n"
              "· 先确定整体外形尺寸（如 100×100×100 立方体）\n"
              "· 再确定各特征的位置和大小\n"
              "· **必须在系统提示词的坐标系约定下工作**（零件居中于原点，"
              "各方向范围 ±尺寸/2）\n\n"
              "【重要】\n"
              "如果三个视图显示的是「在一个立方体/长方体上，不同面挖了不同的坑」，"
              "请按以下方式建模：\n"
              "1. 先 extrude 建主体（用 centered=true 居中）\n"
              "2. 每个坑用 cut + 对应基准面（top/front/right）+ blind 深度建模\n"
              "3. 坑的位置用草图的 center_x / center_y 指定（相对草图平面中心）")
        return t

    if is_sketch:
        t = "这是一个用户手绘的 3D 草图，依据它来生成 solidworks 文件。"
        if text_desc.strip():
            t += f"\n\n用户补充说明：{text_desc.strip()}"
        t += ("\n\n注意：手绘线条可能不精确，请根据常见的工程零件形状合理推断尺寸，"
              "给出符合工程常识的建模方案。")
        return t

    t = "请设计这个零件。"
    if text_desc.strip():
        t = f"用户描述：{text_desc.strip()}"
    if has_image:
        t += "\n（用户还提供了一张零件图片，请据此识别零件形状并设计）"
    return t


def _build_analyze_request(provider: str, api_key: str, user_text: str,
                           image_paths):
    """
    构造分析请求：返回 (url, headers, payload)

    image_paths: 图片路径列表（支持多张，用于三视图）
    """
    info = cfg.get_provider_info(provider)

    # 统一成列表
    if not image_paths:
        image_paths = []
    elif isinstance(image_paths, str):
        image_paths = [image_paths]

    if info.get("api_type") == "anthropic":
        # ---- Anthropic Messages API（Claude）----
        url = f"{info['base_url']}/v1/messages"
        headers = {
            "x-api-key": api_key.strip(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        content = []
        for p in image_paths:
            b64, mime = _encode_image(p)
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mime, "data": b64},
            })
        content.append({"type": "text", "text": user_text})

        payload = {
            "model": info["model"],
            "max_tokens": 8000,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": content}],
        }
        return url, headers, payload

    # ---- OpenAI 兼容（DeepSeek / Qwen / Kimi / GLM / ChatGPT）----
    url = f"{info['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }

    content = []
    for p in image_paths:
        b64, mime = _encode_image(p)
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
        })
    content.append({"type": "text", "text": user_text})

    payload = {
        "model": info["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        "max_tokens": 8000,
    }
    # DeepSeek 支持深度思考
    if provider == "deepseek":
        payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = "high"

    return url, headers, payload


def _extract_answer(provider: str, data: dict):
    """从各家响应中取出 text 和 reasoning"""
    info = cfg.get_provider_info(provider)

    if info.get("api_type") == "anthropic":
        blocks = data.get("content") or []
        texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
        answer = "\n".join(texts).strip()
        thinking = "\n".join(
            b.get("thinking", "") for b in blocks if b.get("type") == "thinking")
        return answer, thinking

    # OpenAI 兼容
    msg = data["choices"][0]["message"]
    answer = msg.get("content") or ""
    if isinstance(answer, list):
        answer = "\n".join(
            c.get("text", "") for c in answer if isinstance(c, dict))
    reasoning = msg.get("reasoning_content") or ""
    return answer.strip(), reasoning


def analyze_part(api_key: str, text_desc: str = "", image_path: str = None,
                 is_sketch: bool = False, provider: str = "deepseek",
                 image_paths=None, is_three_view: bool = False) -> dict:
    """
    分析零件需求，返回建模 JSON。

    参数：
        api_key:       API Key
        text_desc:     文字描述
        image_path:    单张图片路径（兼容旧调用）
        is_sketch:     图片是否为手绘草图
        provider:      服务商 id
        image_paths:   多张图片路径列表（三视图模式，优先于 image_path）
        is_three_view: 是否为三视图模式（主/侧/俯）
    """
    provider = provider if provider in cfg.PROVIDERS else "deepseek"
    info = cfg.get_provider_info(provider)

    # 统一图片列表
    imgs = []
    if image_paths:
        imgs = [p for p in image_paths if p]
    elif image_path:
        imgs = [image_path]

    if not text_desc.strip() and not imgs:
        raise APIError("请至少提供文字描述或图片")

    user_text = _build_analyze_text(text_desc, bool(imgs), is_sketch,
                                    is_three_view)
    url, headers, payload = _build_analyze_request(
        provider, api_key, user_text, imgs)

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=API_TIMEOUT)
    except requests.exceptions.Timeout:
        raise APIError(f"{info['name']} 思考超时（超过 3 分钟），请简化需求后重试",
                       provider=provider)
    except requests.exceptions.ConnectionError:
        raise APIError(f"无法连接 {info['name']} 服务器，请检查网络或代理",
                       provider=provider)
    except Exception as e:
        raise APIError(f"网络异常：{e}", provider=provider)

    if r.status_code != 200:
        msg = _short_err(r, provider)
        if r.status_code in (401, 403):
            raise APIError(f"{info['name']} API Key 无效，请重新填写",
                           r.status_code, provider)
        if r.status_code == 429:
            raise APIError(f"{info['name']} 请求过于频繁或额度不足，请稍后再试",
                           r.status_code, provider)
        raise APIError(f"{info['name']} 请求失败（HTTP {r.status_code}）：{msg}",
                       r.status_code, provider)

    try:
        data = r.json()
    except Exception:
        raise APIError(f"{info['name']} 返回的不是有效 JSON", provider=provider)

    try:
        answer, reasoning = _extract_answer(provider, data)
    except Exception as e:
        raise APIError(f"{info['name']} 返回格式异常：{e}", provider=provider)

    if not answer:
        raise APIError(f"{info['name']} 没有返回内容，请重试", provider=provider)

    spec = _extract_json(answer)
    if spec is None:
        raise APIError(f"{info['name']} 返回的内容不是有效的建模描述，请换个说法重试",
                       provider=provider)

    spec["_reasoning"] = reasoning
    spec["_raw"] = answer
    spec["_provider"] = provider
    return spec


def _extract_json(text: str):
    """从 AI 回复中提取 JSON"""
    text = (text or "").strip()

    # 去掉 markdown 代码块
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    # 找第一个平衡的 { ... }
    start = text.find("{")
    if start >= 0:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except Exception:
                        break
    return None
