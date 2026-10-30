# -*- coding: utf-8 -*-
"""
config.py — 配置与 API Key 管理（五家服务商 · 国内/国外分组）
================================================================
国内：
  · DeepSeek  (deepseek)  默认，国产，多模态 + 深度思考
  · 通义千问  (qwen)      阿里云百炼 DashScope
  · Kimi      (kimi)      月之暗面 Moonshot

国外：
  · ChatGPT   (chatgpt)   OpenAI
  · Claude    (claude)    Anthropic

配置保存在 %APPDATA%\\SolidWorksPartGen\\config.json

Key 校验策略：
  · 每家独立校验、独立存储
  · 同一个 Key 校验通过后不再重复校验
  · Key 变了才重新校验
"""
import os
import json
import hashlib

APP_NAME = "SolidWorksPartGen"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

API_TIMEOUT = 180   # 秒

# ==================== 服务商定义 ====================
# api_type: "openai" = OpenAI 兼容接口 / "anthropic" = Anthropic Messages API
PROVIDERS = {
    # ---------------- 国内 ----------------
    "deepseek": {
        "name": "DeepSeek",
        "label": "DS",
        "region": "cn",
        "api_type": "openai",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "vision": True,
        "reasoning": True,
        "key_prefix": "sk-",
        "key_hint": "sk-...",
        "color": "#4D6BFE",
        "doc": "platform.deepseek.com",
        "note": "推荐，性价比高",
    },
    "qwen": {
        "name": "通义千问",
        "label": "QW",
        "region": "cn",
        "api_type": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-vl-max",
        "vision": True,
        "reasoning": False,
        "key_prefix": "sk-",
        "key_hint": "sk-...",
        "color": "#615CED",
        "doc": "bailian.console.aliyun.com",
        "note": "阿里云百炼",
    },
    "kimi": {
        "name": "Kimi",
        "label": "KM",
        "region": "cn",
        "api_type": "openai",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k-vision-preview",
        "vision": True,
        "reasoning": False,
        "key_prefix": "sk-",
        "key_hint": "sk-...",
        "color": "#1F2937",
        "doc": "platform.moonshot.cn",
        "note": "月之暗面",
    },
    "glm": {
        "name": "GLM",
        "label": "GLM",
        "region": "cn",
        "api_type": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4v-plus",
        "vision": True,
        "reasoning": False,
        "key_prefix": "",
        "key_hint": "xxxxx.xxxxx",
        "color": "#2E5CFF",
        "doc": "bigmodel.cn",
        "note": "智谱",
    },
    # ---------------- 国外 ----------------
    "chatgpt": {
        "name": "ChatGPT",
        "label": "GPT",
        "region": "intl",
        "api_type": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "vision": True,
        "reasoning": False,
        "key_prefix": "sk-",
        "key_hint": "sk-...",
        "color": "#10A37F",
        "doc": "platform.openai.com",
        "note": "需网络代理",
    },
    "claude": {
        "name": "Claude",
        "label": "CL",
        "region": "intl",
        "api_type": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-5-20250929",
        "vision": True,
        "reasoning": False,
        "key_prefix": "sk-ant-",
        "key_hint": "sk-ant-...",
        "color": "#D97757",
        "doc": "console.anthropic.com",
        "note": "需网络代理",
    },
}

# 分组顺序（界面按此显示）
REGIONS = {
    "cn": {"name": "国内", "providers": ["deepseek", "qwen", "kimi", "glm"]},
    "intl": {"name": "国外", "providers": ["chatgpt", "claude"]},
}

# 默认服务商（按优先级找第一个有 key 的）
PROVIDER_ORDER = ["deepseek", "qwen", "kimi", "glm", "chatgpt", "claude"]
DEFAULT_PROVIDER = "deepseek"


# ==================== Key 指纹 ====================
def key_fingerprint(api_key: str) -> str:
    if not api_key:
        return ""
    return hashlib.sha256(api_key.strip().encode("utf-8")).hexdigest()[:16]


# ==================== 读写配置 ====================
def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _keys_dict(cfg: dict) -> dict:
    """取所有服务商的 key 字典（兼容旧版单 key 格式）"""
    d = cfg.get("keys", {})
    if not d and cfg.get("api_key"):
        d = {"deepseek": {
            "api_key": cfg["api_key"],
            "fingerprint": key_fingerprint(cfg["api_key"]),
            "verified": cfg.get("verified", False),
            "verified_fingerprint": cfg.get("verified_fingerprint", ""),
        }}
    return d


# ==================== 各服务商的 Key 操作 ====================
def get_api_key(provider: str = DEFAULT_PROVIDER) -> str:
    return _keys_dict(load_config()).get(provider, {}).get("api_key", "")


def set_api_key(api_key: str, provider: str = DEFAULT_PROVIDER,
                verified: bool = False) -> None:
    cfg = load_config()
    keys = _keys_dict(cfg)
    api_key = (api_key or "").strip()
    new_fp = key_fingerprint(api_key)

    old = keys.get(provider, {})
    old_fp = old.get("fingerprint", "")

    entry = {
        "api_key": api_key,
        "fingerprint": new_fp,
        "verified": False,
        "verified_fingerprint": "",
    }
    # Key 没变且原本已验证 → 保留验证状态
    if api_key and new_fp == old_fp and old.get("verified"):
        entry["verified"] = True
        entry["verified_fingerprint"] = new_fp
    elif verified:
        entry["verified"] = True
        entry["verified_fingerprint"] = new_fp

    keys[provider] = entry
    cfg["keys"] = keys
    for k in ("api_key", "verified", "verified_fingerprint", "key_fingerprint"):
        cfg.pop(k, None)
    save_config(cfg)


def is_key_verified(provider: str = DEFAULT_PROVIDER) -> bool:
    e = _keys_dict(load_config()).get(provider, {})
    key = e.get("api_key", "")
    if not key:
        return False
    return bool(e.get("verified")) and e.get("verified_fingerprint", "") == key_fingerprint(key)


def mark_verified(provider: str = DEFAULT_PROVIDER) -> None:
    cfg = load_config()
    keys = _keys_dict(cfg)
    e = keys.get(provider, {})
    key = e.get("api_key", "")
    if not key:
        return
    e["verified"] = True
    e["verified_fingerprint"] = key_fingerprint(key)
    keys[provider] = e
    cfg["keys"] = keys
    save_config(cfg)


def clear_verification(provider: str = DEFAULT_PROVIDER) -> None:
    cfg = load_config()
    keys = _keys_dict(cfg)
    e = keys.get(provider, {})
    e["verified"] = False
    e["verified_fingerprint"] = ""
    keys[provider] = e
    cfg["keys"] = keys
    save_config(cfg)


def has_any_key() -> bool:
    keys = _keys_dict(load_config())
    return any(v.get("api_key") for v in keys.values())


def get_configured_providers() -> list:
    """返回所有已配置 Key 的服务商 id"""
    keys = _keys_dict(load_config())
    return [p for p in PROVIDER_ORDER if keys.get(p, {}).get("api_key")]


# ==================== 当前使用的服务商 ====================
def get_active_provider() -> str:
    cfg = load_config()
    p = cfg.get("active_provider", "")
    if p in PROVIDERS and get_api_key(p):
        return p
    # 找第一个有 key 的
    for name in PROVIDER_ORDER:
        if get_api_key(name):
            return name
    return DEFAULT_PROVIDER


def set_active_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        return
    cfg = load_config()
    cfg["active_provider"] = provider
    save_config(cfg)


def get_provider_info(provider: str) -> dict:
    return PROVIDERS.get(provider, PROVIDERS[DEFAULT_PROVIDER])


# ==================== 下载目录 ====================
def get_downloads_dir() -> str:
    """获取用户下载文件夹（优先注册表真实路径）"""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        ) as k:
            val, _ = winreg.QueryValueEx(k, "{374DE290-123F-4565-9164-39C4925E467B}")
            val = os.path.expandvars(val)
            if os.path.isdir(val):
                return val
    except Exception:
        pass

    d = os.path.join(os.path.expanduser("~"), "Downloads")
    if os.path.isdir(d):
        return d
    d2 = os.path.join(os.path.expanduser("~"), "下载")
    if os.path.isdir(d2):
        return d2
    return os.path.expanduser("~")
