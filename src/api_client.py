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

    # ★ 自动重试（最多 3 次）：偶发 content 为空 / JSON 解析失败
    last_err = None
    for attempt in range(1, 4):
        try:
            res = _analyze_request_once(
                provider, api_key, user_text, imgs, info, attempt)
            if res is not None:
                return res
        except APIError as e:
            last_err = e
            if e.status_code in (401, 403, 429):
                raise
            if attempt >= 3:
                raise
        except Exception as e:
            last_err = APIError(f"{info['name']} 请求异常：{e}",
                                provider=provider)
            if attempt >= 3:
                raise last_err

        if attempt < 3:
            import time as _t
            _t.sleep(1.5)

    if last_err:
        raise last_err
    raise APIError(f"{info['name']} 建模失败，请重试", provider=provider)


def _analyze_request_once(provider, api_key, user_text, imgs, info,
                          attempt=1):
    """发一次建模请求；内容为空/解析失败返回 None（触发重试）"""
    url, headers, payload = _build_analyze_request(
        provider, api_key, user_text, imgs)

    if attempt >= 2:
        # 重试时关掉深度思考，避免 token 被 reasoning 吃完
        payload.pop("thinking", None)
        payload.pop("reasoning_effort", None)

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=API_TIMEOUT)
    except requests.exceptions.Timeout:
        raise APIError(f"{info['name']} 请求超时（超过 5 分钟），请简化需求后重试",
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
        return None      # 内容为空 → 重试

    spec = _extract_json(answer)
    if spec is None:
        return None      # 解析失败 → 重试

    spec["_reasoning"] = reasoning
    spec["_raw"] = answer
    spec["_provider"] = provider
    return spec


# ==================== 组装图纸 → AI ====================
ASSEMBLY_PROMPT = """你是一个 SolidWorks 二次开发专家。

用户已经在一个 3D 界面里把几个零件摆好了位置，导出了「组装图纸」。
你的任务是**生成一段 SolidWorks VBA 宏代码**，用户运行这个宏就能
自动创建出对应的装配体（.SLDASM）。

★★★ 极其重要：用户可能没有安装 SolidWorks ★★★
所以不能依赖外部程序调 COM。你生成的宏必须是**自包含的 VBA 代码**，
用户拿到 .swp 文件后：
  · 在 SolidWorks 里：工具 → 宏 → 运行
  · 或者双击 .swp 文件
就能自动建出装配体。

★★★ 图纸格式说明 ★★★
  · "unit": "mm"，所有长度毫米
  · "coordinate_system": 右手系，Y 轴朝上
  · "parts": 零件清单（index / file / path / size_mm 原始尺寸）
  · "instances": 每个零件实例
      - "part_index"：对应 parts 里哪一项
      - "position_mm": [x, y, z] 平移位置
      - "scale"：等比缩放系数（1.0 = 原始大小）
      - "scaled"：是否被用户改过大小
      - "size_mm"：缩放后的实际尺寸
  · "modifications": ★ 被缩放的零件明细（original_scale / new_scale）

★★★ 宏代码要求（必须严格遵守）★★★
1. 用**后期绑定**：Dim swApp As Object / Set swApp = Application.SldWorks
   （不需要引用类型库，兼容 SW 2010 到 2025 所有版本）
2. 开头定义零件路径常量数组：
       Dim PART_PATHS(0 To N) As String
       PART_PATHS(0) = "C:\\零件\\底板.SLDPRT"
   并加注释提醒用户改成自己的路径
3. 对需要缩放的零件（modifications 里的）：
       swApp.OpenDoc6 path, 1, 0, "", 0, 0
       Set swModel = swApp.ActiveDoc
       ' 插入缩放特征
       swModel.Extension.SelectByID2 "零件实体名", "SOLIDBODY", 0,0,0, False, 0, Nothing, 0
       swModel.InsertScale 1, False, True, scaleValue, False, False, False, False, 0
       ' 参数：1=统一缩放(True), scaleValue 是倍数
       swModel.Save
       swApp.CloseDoc title
   注意 InsertScale 参数顺序，统一缩放一定要 True（不能变形！）
4. 新建装配体：
       Dim asmTpl As String
       asmTpl = swApp.GetUserPreferenceStringValue(9)   ' swDefaultTemplateAssembly
       Set swAsm = swApp.NewDocument(asmTpl, 0, 0, 0)
5. 插入零件（★ 位置单位是**米**，图纸是毫米，要 /1000）：
       Set swAssy = swAsm
       Set comp = swAssy.AddComponent5(path, 0, "", False, "", x/1000, y/1000, z/1000)
6. 添加配合（可选，至少给同心/重合）：
       boolstatus = swAsm.Extension.SelectByID2("零件名-1@装配体名", "COMPONENT", 0,0,0, True, 1, Nothing, 0)
   简化起见：可以先只摆位置不加配合，在注释里说明
7. 提速：swApp.CommandInProgress = True  ... 末尾 = False
8. 保存：swAsm.SaveAs3 savePath, 0, 1
9. 末尾 MsgBox "装配完成！", vbInformation, "AI 零件生成器"
10. 所有变量都要 Dim，VBA 要求显式声明（建议加 Option Explicit 注释掉也行）

★★★ 输出格式（严格 JSON，不能有任何多余文字）★★★
{
  "assembly_name": "立柱支撑架",
  "assembly_name_en": "PillarSupport",
  "summary": "一句话说明这是什么产品",
  "macro_code": "完整 VBA 代码，换行用 \\n 转义",
  "part_paths": ["C:\\Users\\xxx\\底板.SLDPRT"],
  "steps": [
    {"title": "1. 准备零件", "detail": "把所有零件放到同一个文件夹，记下路径"},
    {"title": "2. 新建宏", "detail": "打开 SolidWorks → 工具 → 宏 → 新建，保存为 组装.swp"},
    {"title": "3. 粘贴代码", "detail": "用记事本打开生成的 .swp，全选复制，粘贴到宏编辑器"},
    {"title": "4. 改路径", "detail": "把代码顶部 PART_PATHS 数组改成你自己的零件路径"},
    {"title": "5. 运行", "detail": "按 F5 或 工具 → 宏 → 运行"}
  ],
  "notes": ["注意事项"]
}

★ macro_code 里**绝对不能有真正的换行符**，必须用 \\n 转义（JSON 字符串标准）。
★ 不需要缩放的零件跳过缩放步骤。
★ 宏必须能在「没打开任何文档」的状态下直接运行。
★ 生成的代码要能在 SolidWorks 2020+ 上跑通，加完整的 On Error 处理。
"""



def _build_assembly_text(blueprint_text: str, part_list=None,
                         preview_images=None) -> str:
    """组装请求的文字部分"""
    t = "这是用户组装好的零件图纸，请据此生成 SolidWorks 装配体方案。\n\n"
    t += "=" * 50 + "\n"
    t += blueprint_text
    t += "\n" + "=" * 50
    t += "\n\n【附带的零件文件】\n"
    if part_list:
        for i, p in enumerate(part_list):
            sz = p.get("size_mm")
            szs = (f"{sz[0]:.1f}×{sz[1]:.1f}×{sz[2]:.1f} mm"
                   if sz else "未知")
            t += f"  [{i}] {p.get('file', '?')}　原始尺寸 {szs}\n"
    t += ("\n（下面的图片是各零件的 3D 预览，可用来判断零件形状、"
          "识别哪些面该配合）\n")
    return t


def analyze_assembly(api_key: str, blueprint_data: dict,
                     part_paths=None, preview_images=None,
                     provider: str = "deepseek") -> dict:
    """
    让 AI 分析组装图纸，返回装配方案。

    参数：
        api_key:        API Key
        blueprint_data: blueprint.build_blueprint() 生成的字典
        part_paths:     零件文件路径列表（用于提示中列出材料）
        preview_images: 零件预览图路径列表（可选，让 AI 看图）
        provider:       服务商
    """
    import blueprint as bp

    provider = provider if provider in cfg.PROVIDERS else "deepseek"
    info = cfg.get_provider_info(provider)

    # 图纸转文本
    try:
        bp_text = bp.blueprint_to_prompt(blueprint_data)
    except Exception:
        bp_text = json.dumps(blueprint_data, ensure_ascii=False, indent=2)

    part_list = blueprint_data.get("parts", [])
    user_text = _build_assembly_text(bp_text, part_list)

    # 图片：优先用预览图
    imgs = [p for p in (preview_images or []) if p and os.path.exists(p)]

    # ★ 自动重试（最多 3 次）
    # 偶发情况：深度思考把 token 全用在 reasoning 上，content 为空。
    # 这类失败重试一次通常就好了。
    last_err = None
    for attempt in range(1, 4):
        try:
            result = _assembly_request_once(
                provider, api_key, user_text, imgs, info, attempt)
            if result is not None:
                return result
        except APIError as e:
            last_err = e
            # Key 无效 / 额度不足 不重试
            if e.status_code in (401, 403, 429):
                raise
            if attempt >= 3:
                raise
        except Exception as e:
            last_err = APIError(f"{info['name']} 请求异常：{e}",
                                provider=provider)
            if attempt >= 3:
                raise last_err

        # 重试前等一下
        if attempt < 3:
            import time as _t
            _t.sleep(1.5)

    if last_err:
        raise last_err
    raise APIError(f"{info['name']} 组装失败，请重试", provider=provider)


def _assembly_request_once(provider, api_key, user_text, imgs, info,
                           attempt=1):
    """
    发一次组装请求。

    返回 spec dict，或在「内容为空」时返回 None（让外层重试）。
    其他错误抛 APIError。
    """
    # 重试时降低 max_tokens 里留给思考的比例，提高出结果概率
    url, headers, payload = _build_custom_request(
        provider, api_key, user_text, imgs, ASSEMBLY_PROMPT)

    if attempt >= 2:
        # 第二次开始：关掉深度思考，避免内容为空
        payload.pop("thinking", None)
        payload.pop("reasoning_effort", None)

    try:
        r = requests.post(url, headers=headers, json=payload,
                          timeout=API_TIMEOUT)
    except requests.exceptions.Timeout:
        raise APIError(f"{info['name']} 请求超时（超过 5 分钟），"
                       f"可能是零件太多，试试减少零件数量",
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
            raise APIError(f"{info['name']} 请求过于频繁或额度不足",
                           r.status_code, provider)
        raise APIError(f"{info['name']} 请求失败（HTTP {r.status_code}）：{msg}",
                       r.status_code, provider)

    try:
        data = r.json()
    except Exception:
        raise APIError(f"{info['name']} 返回的不是有效 JSON", provider=provider)

    # ★ 检查是否因 token 用尽被截断
    finish = ""
    try:
        finish = data["choices"][0].get("finish_reason") or ""
    except Exception:
        pass

    try:
        answer, reasoning = _extract_answer(provider, data)
    except Exception as e:
        raise APIError(f"{info['name']} 返回格式异常：{e}", provider=provider)

    if not answer:
        # 内容为空 → 返回 None 让外层重试
        if finish == "length":
            # 明确告知：思考把预算吃光了
            raise APIError(
                f"{info['name']} 思考用完了输出长度（{len(reasoning)} 字思考，"
                f"正文 0 字）。\n\n"
                f"建议换一个模型，或减少零件数量后重试。",
                provider=provider)
        return None

    spec = _extract_json(answer)
    if spec is None:
        # JSON 解析失败 → 也重试
        return None

    spec["_reasoning"] = reasoning
    spec["_raw"] = answer
    spec["_provider"] = provider
    return spec


def _build_custom_request(provider, api_key, user_text, image_paths,
                          system_prompt):
    """通用的请求构造（自定义 system prompt）"""
    info = cfg.get_provider_info(provider)
    imgs = image_paths or []

    if info.get("api_type") == "anthropic":
        url = f"{info['base_url']}/v1/messages"
        headers = {
            "x-api-key": api_key.strip(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        content = []
        for p in imgs:
            b64, mime = _encode_image(p)
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mime, "data": b64},
            })
        content.append({"type": "text", "text": user_text})
        payload = {
            "model": info["model"],
            "max_tokens": 8000,
            "system": system_prompt,
            "messages": [{"role": "user", "content": content}],
        }
        return url, headers, payload

    url = f"{info['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    content = []
    for p in imgs:
        b64, mime = _encode_image(p)
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
        })
    content.append({"type": "text", "text": user_text})

    payload = {
        "model": info["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        # ★ 生成 VBA 宏代码很长，需要足够的输出空间
        "max_tokens": 16000,
    }
    # ★ 这里**不开深度思考**：实测 DeepSeek 生成宏时思考会吃掉全部
    #   token 预算（reasoning 22436 字符 / 8000 token），导致 content 为空。
    #   生成代码这类任务不需要长推理，直接输出更可靠。
    return url, headers, payload


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
