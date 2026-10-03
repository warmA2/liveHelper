"""直播操作类型库：唱歌 / PK / 杂谈 / 看视频 … 以及各自的默认时长。

配置落在 data/actions.json：
  - 首次运行会把内置默认写进该文件；
  - 之后以文件内容为准，可以直接编辑增删操作类型、改默认时长，保存即生效（无需重启）。
每条：key 唯一标识、label 按钮显示名、minutes 默认时长（分钟）、color 时间轴色带颜色。
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import BASE_DIR

ACTIONS_PATH = BASE_DIR / "data" / "actions.json"

DEFAULT_ACTIONS: List[Dict[str, Any]] = [
    {"key": "sing", "label": "唱歌", "minutes": 4, "color": "#fb7299"},
    {"key": "pk", "label": "PK", "minutes": 6, "color": "#f2c14e"},
    {"key": "chat", "label": "杂谈", "minutes": 10, "color": "#5b9dff"},
    {"key": "video", "label": "看视频", "minutes": 8, "color": "#b28dff"},
    {"key": "game", "label": "游戏", "minutes": 15, "color": "#3ecf8e"},
    {"key": "rest", "label": "休息", "minutes": 5, "color": "#8b93a7"},
]

MIN_MINUTES = 1
MAX_MINUTES = 180
FALLBACK_COLOR = "#8b93a7"

_mtime: float = -1.0
_actions: List[Dict[str, Any]] = []


def _read() -> List[Dict[str, Any]]:
    if not ACTIONS_PATH.exists():
        ACTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        ACTIONS_PATH.write_text(
            json.dumps({"actions": DEFAULT_ACTIONS}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    try:
        data = json.loads(ACTIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[actions] actions.json 解析失败({exc})，改用内置默认")
        return list(DEFAULT_ACTIONS)
    items = data.get("actions") if isinstance(data, dict) else data
    return list(items) if isinstance(items, list) else []


def _build(raw_items: List[Dict[str, Any]]):
    global _actions
    out: List[Dict[str, Any]] = []
    seen = set()
    for raw in raw_items or []:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        label = str(raw.get("label") or "").strip() or key
        try:
            minutes = int(raw.get("minutes") or 0)
        except (TypeError, ValueError):
            minutes = 0
        minutes = min(max(minutes, MIN_MINUTES), MAX_MINUTES)
        out.append(
            {
                "key": key,
                "label": label,
                "minutes": minutes,
                "color": str(raw.get("color") or "").strip() or FALLBACK_COLOR,
            }
        )
    _actions = out


def reload_if_changed():
    """文件被编辑过就重新加载，省得改操作类型还要重启服务。"""
    global _mtime
    try:
        mtime = ACTIONS_PATH.stat().st_mtime
    except OSError:
        mtime = -1.0
    if mtime == _mtime and _actions:
        return
    _mtime = mtime
    _build(_read())


def load_actions() -> List[Dict[str, Any]]:
    reload_if_changed()
    return list(_actions)


def get_action(key: str) -> Optional[Dict[str, Any]]:
    reload_if_changed()
    wanted = str(key or "").strip()
    for item in _actions:
        if item["key"] == wanted:
            return item
    return None


def clamp_minutes(minutes: Any, default: int) -> int:
    """分钟数夹在 1~180；非法值退回该类型的默认时长。"""
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        value = int(default)
    return min(max(value, MIN_MINUTES), MAX_MINUTES)
