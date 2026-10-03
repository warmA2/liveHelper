"""配置加载与持久化。

首次运行会在项目根目录生成 config.json，之后所有设置都从该文件读取。
"""

import copy
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Optional

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
        "min_messages": 10,
        "auto": True,
        "auto_interval_sec": 600,
        "recent_msg_limit": 40,
        "trigger_after_messages": 20,
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
    """环境变量作为兜底：仅当 config.json 里该项为空时才生效。

    网页里「扫码登录 / 手动保存」得到的 Cookie 会写进 config.json，
    它属于用户的显式操作，必须优先于环境变量；否则每次启动都会被环境变量
    覆盖、并被 save_config 当作环境来源清空，导致登录永远不生效。
    """
    if not str(cfg.get("cookie") or "").strip():
        cookie = os.environ.get(ENV_COOKIE, "").strip()
        if cookie:
            cfg["cookie"] = cookie
    llm = cfg.get("llm") or {}
    if not str(llm.get("api_key") or "").strip():
        api_key = os.environ.get(ENV_API_KEY, "").strip()
        if api_key:
            llm["api_key"] = api_key
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


# 直播间链接里可能带 /blanc/ /h5/ /blackboard/ 等前缀，真正的房间号是一段数字
_ROOM_LINK_RE = re.compile(
    r"live\.bilibili\.com/(?:blanc/|h5/|blackboard/)?(\d+)", re.I
)


def parse_room_id(text) -> Optional[int]:
    """从用户输入中解析房间号。

    接受：纯数字（短号 / 真实房间号）、直播间链接
    （https://live.bilibili.com/1907444111，可带查询串、尾斜杠、/blanc/ /h5/ 等前缀）。
    无法解析时返回 None。
    """
    if text is None:
        return None
    if isinstance(text, bool):
        return None
    if isinstance(text, int):
        return text if text >= 0 else None
    raw = str(text).strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    match = _ROOM_LINK_RE.search(raw)
    if match:
        return int(match.group(1))
    # 兜底：整段文字里只要有一段较长的数字（如「房间号 1907444111」）也认
    match = re.search(r"(\d{3,})", raw)
    if match:
        return int(match.group(1))
    return None


def db_file(cfg):
    """按房间号派生数据库文件：一个主播一个库，数据完全隔离。

    room_id > 0 时用 data/room_<room_id>.db，否则回退到 storage.db_path
    （未设置房间号时仍用默认库）。
    """
    base = Path(cfg["storage"]["db_path"])
    if not base.is_absolute():
        base = BASE_DIR / base
    room_id = int(cfg.get("room_id") or 0)
    path = base.parent / f"room_{room_id}.db" if room_id > 0 else base
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def prepare_db_file(cfg):
    """取当前房间对应的库文件，并在首次切换时迁移老库。

    老版本所有数据都写在 data/live.db 里。启用「一主播一库」后第一次按新规则
    取库时，如果目标库还不存在、而老库存在，就把老库重命名为
    data/room_<room_id>.db（房间号以老库 sessions 表最近一条为准），避免历史数据丢失。
    """
    base = Path(cfg["storage"]["db_path"])
    if not base.is_absolute():
        base = BASE_DIR / base
    room_id = int(cfg.get("room_id") or 0)
    if room_id <= 0:
        # 未启用分库，直接用默认库
        base.parent.mkdir(parents=True, exist_ok=True)
        return base

    target = base.parent / f"room_{room_id}.db"
    if target.exists() or not base.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    # 老库存在且目标库不存在 —— 读老库真实房间号后迁移。
    # 老版本单库跨多个房间，这里以「事件最多的房间」为准（历史数据主要属于它），
    # 不能取最后一条场次：那样会把老数据错挂到后来新加的房间里。
    legacy_room = room_id
    try:
        conn = sqlite3.connect(str(base))
        try:
            row = conn.execute(
                "SELECT s.room_id, COUNT(e.id) c "
                "FROM sessions s LEFT JOIN events e ON e.session_id = s.id "
                "WHERE s.room_id > 0 GROUP BY s.room_id ORDER BY c DESC LIMIT 1"
            ).fetchone()
            if row and row[0]:
                legacy_room = int(row[0])
        finally:
            conn.close()
    except sqlite3.Error:
        pass
    if legacy_room != room_id and legacy_room > 0:
        # 老库记录的房间号与配置不一致时以老库为准，配置同步更正
        room_id = legacy_room
        cfg["room_id"] = legacy_room
        target = base.parent / f"room_{room_id}.db"
    if target.exists():
        return target

    base.replace(target)
    # WAL 模式可能还留有 -wal / -shm 附属文件，一并搬走
    for suffix in ("-wal", "-shm"):
        side = Path(str(base) + suffix)
        if side.exists():
            side.replace(Path(str(target) + suffix))
    print(f"[config] 已将老库 {base.name} 迁移为 {target.name}", flush=True)
    return target
