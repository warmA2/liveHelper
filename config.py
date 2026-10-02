"""配置加载与持久化。

首次运行会在项目根目录生成 config.json，之后所有设置都从该文件读取。
"""

import copy
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

# 敏感项可以用环境变量注入，这样 config.json 里可以只留空值，
# 不会把 Cookie / API Key 跟着仓库提交到 Git。
ENV_COOKIE = "BILI_COOKIE"
ENV_API_KEY = "LLM_API_KEY"

DEFAULTS = {
    "room_id": 0,
    "host": "127.0.0.1",
    "port": 8765,
    "open_browser": True,
    "cookie": "",
    "llm": {
        "enabled": True,
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-chat",
        "timeout": 60,
        "temperature": 0.4,
    },
    "analyze": {
        "min_messages": 3,
        "auto": True,
        "auto_interval_sec": 600,
        "recent_msg_limit": 40,
        "trigger_after_messages": 5,
    },
    "storage": {
        "db_path": "data/live.db",
        "keep_days": 0,
    },
}


def _deep_merge(base, override):
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _apply_env_overrides(cfg):
    """环境变量优先于 config.json，便于把密钥放在仓库之外。"""
    cookie = os.environ.get(ENV_COOKIE, "").strip()
    if cookie:
        cfg["cookie"] = cookie
    api_key = os.environ.get(ENV_API_KEY, "").strip()
    if api_key:
        cfg["llm"]["api_key"] = api_key
    return cfg


def load_config():
    """读取 config.json，缺失时用默认值创建。"""
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(
            json.dumps(DEFAULTS, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return _apply_env_overrides(copy.deepcopy(DEFAULTS))

    try:
        user_cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[config] config.json 解析失败({exc})，使用默认配置")
        return _apply_env_overrides(copy.deepcopy(DEFAULTS))
    return _apply_env_overrides(_deep_merge(DEFAULTS, user_cfg))


def save_config(cfg):
    """写回 config.json。

    来自环境变量的 Cookie / API Key 不落盘，避免明文写进文件（也就不会误提交）。
    """
    data = copy.deepcopy(cfg)
    if data.get("cookie") and data["cookie"] == os.environ.get(ENV_COOKIE, "").strip():
        data["cookie"] = ""
    llm = data.get("llm") or {}
    if llm.get("api_key") and llm["api_key"] == os.environ.get(ENV_API_KEY, "").strip():
        llm["api_key"] = ""
    CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def db_file(cfg):
    path = Path(cfg["storage"]["db_path"])
    if not path.is_absolute():
        path = BASE_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
