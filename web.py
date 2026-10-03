"""Web 控制台：REST 接口 + SSE 实时推送 + 静态页面。"""

import asyncio
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set

import aiohttp
from aiohttp import web

from actions import clamp_minutes, get_action, load_actions
from analyzer import Analyzer
from bili_live import (
    cookie_value,
    fetch_buvid,
    fetch_login_name,
    qrcode_generate,
    qrcode_poll,
)
from config import BASE_DIR, parse_room_id, save_config
from store import Store
from topics import TOPICS

STATIC_DIR = BASE_DIR / "static"


class Dashboard:
    def __init__(
        self,
        store: Store,
        analyzer: Analyzer,
        cfg: Dict[str, Any],
        on_room_change: Optional[Callable[[int], Any]] = None,
        get_status: Optional[Callable[[], dict]] = None,
    ):
        self.store = store
        self.analyzer = analyzer
        self.cfg = cfg
        self.on_room_change = on_room_change
        self.get_status = get_status or (lambda: {})
        self.subscribers: Set[asyncio.Queue] = set()
        self._tasks: Set[asyncio.Task] = set()
        self._http: Optional[aiohttp.ClientSession] = None  # 扫码登录用

    # ------------------------------------------------------------------
    # 实时推送
    # ------------------------------------------------------------------
    def broadcast(self, item: dict):
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                pass

    def spawn(self, coro):
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # ------------------------------------------------------------------
    # 路由
    # ------------------------------------------------------------------
    def build_app(self) -> web.Application:
        # 前端每次改动都要靠用户硬刷新才能生效，容易看到旧样式；
        # 给页面与静态资源加 no-cache，让浏览器每次都回源校验（命中 304 仍走缓存）。
        @web.middleware
        async def no_cache_frontend(request, handler):
            resp = await handler(request)
            if request.path == "/" or request.path.startswith("/static/"):
                resp.headers["Cache-Control"] = "no-cache"
            return resp

        app = web.Application(middlewares=[no_cache_frontend])
        app.add_routes(
            [
                web.get("/", self.index),
                web.get("/api/stats", self.api_stats),
                web.get("/api/viewers", self.api_viewers),
                web.get("/api/viewers/{uid}", self.api_viewer_detail),
                web.post("/api/viewers/{uid}/analyze", self.api_analyze),
                web.post("/api/viewers/{uid}/note", self.api_note),
                web.post("/api/viewers/{uid}/role", self.api_set_role),
                web.get("/api/roles", self.api_roles),
                web.get("/api/career", self.api_career),
                web.get("/api/analysis", self.api_analysis),
                web.post("/api/analysis", self.api_analysis_run),
                web.get("/api/events", self.api_events),
                web.get("/api/density", self.api_density),
                web.get("/api/topics", self.api_topics),
                web.get("/api/actions", self.api_actions),
                web.post("/api/actions", self.api_action_create),
                web.delete("/api/actions/{aid}", self.api_action_delete),
                web.get("/api/timeline", self.api_timeline),
                web.get("/api/sessions", self.api_sessions),
                web.get("/api/stream", self.api_stream),
                web.get("/api/config", self.api_get_config),
                web.post("/api/config", self.api_set_config),
                web.get("/api/rooms", self.api_rooms),
                web.get("/api/login/qrcode", self.api_login_qrcode),
                web.get("/api/login/poll", self.api_login_poll),
                web.post("/api/reconnect", self.api_reconnect),
                web.static("/static", STATIC_DIR),
            ]
        )
        app.on_cleanup.append(self._cleanup)
        return app

    async def _cleanup(self, app):
        for task in list(self._tasks):
            task.cancel()
        if self._http and not self._http.closed:
            await self._http.close()
        await self.analyzer.close()

    async def _http_session(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession()
        return self._http

    async def index(self, request):
        return web.FileResponse(STATIC_DIR / "index.html")

    # ------------------------------------------------------------------
    async def api_stats(self, request):
        data = self.store.session_stats()
        data.update(self.get_status())
        data["llm_enabled"] = self.analyzer.enabled
        return web.json_response(data)

    @staticmethod
    def _query_int(query, key: str, default: int = 0) -> int:
        try:
            return int(query.get(key, default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _query_types(query):
        raw = (query.get("types") or "").strip()
        return [t for t in raw.split(",") if t] or None

    async def api_viewers(self, request):
        query = request.query
        keyword = query.get("keyword", "").strip()
        session_only = query.get("session_only") == "1"
        min_messages = self._query_int(query, "min_messages", 0)
        viewers = self.store.list_viewers(
            sort=query.get("sort", "active"),
            limit=min(self._query_int(query, "limit", 200), 1000),
            offset=max(self._query_int(query, "offset", 0), 0),
            keyword=keyword,
            session_only=session_only,
            min_messages=min_messages,
        )
        total = self.store.count_viewers(keyword, session_only, min_messages)
        return web.json_response({"items": viewers, "total": total})

    async def api_viewer_detail(self, request):
        uid = int(request.match_info["uid"])
        viewer = self.store.get_viewer(uid)
        if not viewer:
            raise web.HTTPNotFound(text="viewer not found")
        query = request.query
        limit = min(self._query_int(query, "limit", 100), 500)
        offset = max(self._query_int(query, "offset", 0), 0)
        types = self._query_types(query)
        session_id = self._query_int(query, "session_id", 0) or None
        if query.get("session_only") == "1":
            session_id = self.store.session_id
        keyword = (query.get("keyword") or "").strip() or None
        order = "asc" if (query.get("order") or "").lower() == "asc" else "desc"
        events = self.store.get_events(
            uid=uid, limit=limit, offset=offset, types=types, session_id=session_id,
            keyword=keyword, order=order,
        )
        total = self.store.count_events_filtered(
            uid=uid, types=types, session_id=session_id, keyword=keyword
        )
        # 指标基于完整弹幕样本，不受分页影响
        danmaku = self.store.get_events(uid=uid, limit=500, types=["danmaku"])
        context = self.store.viewer_context(uid)
        metrics = self.analyzer.build_metrics(viewer, danmaku, context)
        # 各类型事件总数（全局口径），供「行为」分类汇总展示
        type_counts = self.store.count_events_by_type(uid=uid)
        return web.json_response(
            {
                "viewer": viewer,
                "events": events,
                "metrics": metrics,
                "total": total,
                "limit": limit,
                "offset": offset,
                "type_counts": type_counts,
            }
        )

    async def api_events(self, request):
        query = request.query
        limit = min(self._query_int(query, "limit", 200), 500)
        offset = max(self._query_int(query, "offset", 0), 0)
        filters = {
            "uid": self._query_int(query, "uid", 0) or None,
            "session_id": self._query_int(query, "session_id", 0) or None,
            "types": self._query_types(query),
            "from_ts": self._query_int(query, "from_ts", 0) or None,
            "to_ts": self._query_int(query, "to_ts", 0) or None,
        }
        items = self.store.get_events(limit=limit, offset=offset, **filters)
        total = self.store.count_events_filtered(**filters)
        return web.json_response(
            {"items": items, "total": total, "limit": limit, "offset": offset}
        )

    async def api_density(self, request):
        """按时间桶聚合事件数量，供前端画全局/个人密度曲线。"""
        query = request.query
        bucket = self._query_int(query, "bucket", 60)  # 秒
        bucket = min(max(bucket, 5), 86400)
        return web.json_response(
            self.store.event_density(
                uid=self._query_int(query, "uid", 0) or None,
                session_id=self._query_int(query, "session_id", 0) or None,
                types=self._query_types(query),
                from_ts=self._query_int(query, "from_ts", 0) or None,
                to_ts=self._query_int(query, "to_ts", 0) or None,
                bucket_ms=bucket * 1000,
            )
        )

    async def api_topics(self, request):
        """返回热门元素库（游戏/梗/番剧/音乐等），供前端弹幕高亮与画像归类。"""
        return web.json_response(TOPICS.as_payload())

    # ------------------------------------------------------------------
    # 操作记录（唱歌 / PK / 杂谈 …）
    # ------------------------------------------------------------------
    @staticmethod
    def _action_light(item: dict) -> dict:
        """时间轴色带只需要这几个字段，把历史列表里的多余列剥掉。"""
        return {
            "id": item["id"],
            "kind": item["kind"],
            "label": item.get("label") or "",
            "color": item.get("color") or "",
            "start_ts": item["start_ts"],
            "end_ts": item["end_ts"],
            "note": item.get("note") or "",
        }

    async def api_actions(self, request):
        """操作记录列表。

        默认只返回轻量字段——密度曲线每几秒刷新一次，不能顺带跑 100 条聚合；
        `?metrics=1` 时才附带每条窗口指标 + 汇总 + 本场基线，仅供打开面板时取。
        """
        query = request.query
        limit = min(self._query_int(query, "limit", 100), 500)
        session_only = query.get("session_only") == "1"
        if query.get("metrics") == "1":
            items = self.store.actions_with_metrics(limit=limit, session_only=session_only)
            return web.json_response(
                {
                    "items": items,
                    "kinds": load_actions(),
                    "summary": self.store.action_summary(items),
                    "baseline": self.store.baseline_metrics(),
                }
            )
        items = [
            self._action_light(it)
            for it in self.store.list_actions(limit=limit, session_only=session_only)
        ]
        return web.json_response({"items": items, "kinds": load_actions()})

    async def api_action_create(self, request):
        """记录一次刚结束的操作：锚点取 end_ts（缺省 now），往前推一个默认时长。"""
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            raise web.HTTPBadRequest(text="invalid json")
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="invalid json")
        kind = str(body.get("kind") or "").strip()
        item = get_action(kind)
        if not item:
            raise web.HTTPBadRequest(text=f"unknown action kind: {kind}")
        minutes = clamp_minutes(body.get("minutes"), item["minutes"])
        try:
            end_ts = int(body.get("end_ts") or 0)
        except (TypeError, ValueError):
            end_ts = 0
        if end_ts <= 0:
            end_ts = int(time.time() * 1000)
        start_ts = end_ts - minutes * 60000
        note = str(body.get("note") or "")[:200]
        saved = self.store.record_action(
            item["key"], item["label"], item["color"], start_ts, end_ts, note
        )
        self.broadcast({"type": "action"})
        return web.json_response({"ok": True, "item": self._action_light(saved)})

    async def api_action_delete(self, request):
        try:
            action_id = int(request.match_info["aid"])
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="invalid action id")
        if not self.store.delete_action(action_id):
            raise web.HTTPNotFound(text="action not found")
        self.broadcast({"type": "action"})
        return web.json_response({"ok": True})

    async def api_timeline(self, request):
        return web.json_response({"days": self.store.timeline_buckets()})

    async def api_sessions(self, request):
        return web.json_response({"items": self.store.list_sessions()})

    async def api_analyze(self, request):
        uid = int(request.match_info["uid"])
        if not self.store.get_viewer(uid):
            raise web.HTTPNotFound(text="viewer not found")
        self.broadcast({"type": "profile_status", "uid": uid, "status": "running"})
        self.store.set_profile_status(uid, "running")
        self.spawn(self._run_analysis(uid))
        return web.json_response({"ok": True, "queued": True})

    async def _run_analysis(self, uid: int):
        try:
            profile = await self.analyzer.analyze(uid)
            self.broadcast(
                {"type": "profile", "uid": uid, "profile": profile, "status": "done"}
            )
        except Exception as exc:
            self.broadcast(
                {
                    "type": "profile",
                    "uid": uid,
                    "status": "error",
                    "error": str(exc)[:300],
                }
            )

    async def api_note(self, request):
        uid = int(request.match_info["uid"])
        body = await request.json()
        self.store.set_note(uid, str(body.get("note", ""))[:1000])
        return web.json_response({"ok": True})

    async def api_set_role(self, request):
        """手动指定观众身份（AI助手 / 房管 / …），空串表示清除。"""
        uid = int(request.match_info["uid"])
        body = await request.json()
        self.store.set_viewer_role(uid, str(body.get("role", ""))[:20])
        return web.json_response({"ok": True})

    async def api_roles(self, request):
        """已标记身份的观众映射 {uid: role}，供弹幕流与列表快速取用。"""
        return web.json_response(self.store.list_roles())

    async def api_career(self, request):
        """主播生涯：跨全部场次的累计统计。"""
        return web.json_response(self.store.career_stats())

    # ------------------------------------------------------------------
    # AI 分析（本场直播 / 生涯）
    # ------------------------------------------------------------------
    def _analysis_key(self, kind: str) -> Optional[str]:
        if kind == "career":
            return "career"
        if kind == "session":
            return f"session:{self.store.session_id}" if self.store.session_id else None
        return None

    async def api_analysis(self, request):
        """读取已生成的分析文本（本场 / 生涯）。"""
        kind = (request.query.get("kind") or "session").strip()
        if kind not in ("session", "career"):
            raise web.HTTPBadRequest(text="unknown analysis kind")
        key = self._analysis_key(kind)
        record = self.store.get_analysis(key) if key else None
        return web.json_response(
            {
                "kind": kind,
                "session_id": self.store.session_id,
                "llm_enabled": self.analyzer.enabled,
                "content": record["content"] if record else "",
                "model": record["model"] if record else "",
                "created_at": record["created_at"] if record else 0,
            }
        )

    async def api_analysis_run(self, request):
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            body = {}
        kind = str((body or {}).get("kind") or "session").strip()
        if kind not in ("session", "career"):
            raise web.HTTPBadRequest(text="unknown analysis kind")
        self.broadcast({"type": "analysis", "kind": kind, "status": "running"})
        self.spawn(self._run_analysis_kind(kind))
        return web.json_response({"ok": True, "queued": True})

    async def _run_analysis_kind(self, kind: str):
        try:
            if kind == "career":
                result = await self.analyzer.analyze_career()
            else:
                result = await self.analyzer.analyze_session()
            self.broadcast(
                {
                    "type": "analysis",
                    "kind": result["kind"],
                    "status": "done",
                    "content": result["content"],
                    "model": result["model"],
                }
            )
        except Exception as exc:
            self.broadcast(
                {"type": "analysis", "kind": kind, "status": "error", "error": str(exc)[:300]}
            )

    async def api_get_config(self, request):
        llm = self.cfg["llm"]
        return web.json_response(
            {
                "room_id": self.cfg["room_id"],
                "llm_enabled": llm.get("enabled"),
                "base_url": llm.get("base_url"),
                "model": llm.get("model"),
                "api_key_set": bool(llm.get("api_key")),
                "cookie_set": bool(self.cfg.get("cookie")),
                "auto": self.cfg["analyze"].get("auto"),
            }
        )

    async def api_rooms(self, request):
        """已保存的房间列表：一个房间一个库文件，扫描 data/room_<id>.db 得到。"""
        data_dir = BASE_DIR / "data"
        current = int(self.cfg.get("room_id") or 0)
        rooms: Dict[int, dict] = {}
        for path in data_dir.glob("room_*.db"):
            match = re.match(r"room_(\d+)\.db$", path.name)
            if not match:
                continue
            rid = int(match.group(1))
            rooms[rid] = {
                "room_id": rid,
                "last_active": int(path.stat().st_mtime * 1000),
                "viewers": self._count_viewers(path),
            }
        # 当前配置的房间即使还没有库文件也列出来
        if current > 0 and current not in rooms:
            rooms[current] = {
                "room_id": current,
                "last_active": int(time.time() * 1000),
                "viewers": 0,
            }
        for item in rooms.values():
            item["current"] = item["room_id"] == current
        # 当前房间置顶，其余按最近使用排序
        items = sorted(
            rooms.values(),
            key=lambda r: (r["room_id"] != current, -r["last_active"]),
        )
        return web.json_response({"items": items, "current": current})

    @staticmethod
    def _count_viewers(path) -> int:
        """读库统计观众数，失败不影响列表展示。"""
        try:
            conn = sqlite3.connect(str(path), timeout=1)
            try:
                row = conn.execute("SELECT COUNT(*) FROM viewers").fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()
        except sqlite3.Error:
            return 0

    # ------------------------------------------------------------------
    # B 站扫码登录：自动获取完整 Cookie，省去手动复制
    # ------------------------------------------------------------------
    async def api_login_qrcode(self, request):
        session = await self._http_session()
        try:
            data = await qrcode_generate(session)
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=502)
        return web.json_response(
            {
                "ok": True,
                "qrcode_key": data.get("qrcode_key", ""),
                "url": data.get("url", ""),
            }
        )

    async def api_login_poll(self, request):
        key = (request.query.get("key") or "").strip()
        if not key:
            raise web.HTTPBadRequest(text="missing key")
        session = await self._http_session()
        try:
            result = await qrcode_poll(session, key)
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=502)

        status_code = result.get("status")
        if status_code != 0:
            mapping = {86038: "expired", 86090: "scanned", 86101: "pending"}
            return web.json_response(
                {
                    "ok": True,
                    "status": mapping.get(status_code, "pending"),
                    "message": result.get("message", ""),
                }
            )

        cookie = await self._compose_login_cookie(result.get("cookies") or {}, session)
        # 用 nav 接口复核登录态，顺便拿到昵称
        try:
            uname = await fetch_login_name(session, cookie)
        except Exception:
            uname = ""
        if not uname:
            return web.json_response(
                {"ok": False, "status": "error", "error": "扫码成功但校验登录态失败，请重试"}
            )
        self.cfg["cookie"] = cookie
        save_config(self.cfg)
        if self.on_room_change:
            await self.on_room_change(self.cfg["room_id"])
        self.broadcast({"type": "status", "message": f"扫码登录成功：{uname}"})
        return web.json_response({"ok": True, "status": "confirmed", "uname": uname})

    async def _compose_login_cookie(self, cookies: dict, session) -> str:
        text = "; ".join(f"{k}={v}" for k, v in cookies.items() if v)
        # 补齐 buvid，避免后续弹幕请求因缺设备指纹被风控
        if not cookie_value(text, "buvid3"):
            try:
                buvid = await fetch_buvid(session)
            except Exception:
                buvid = {}
            if buvid.get("b_3"):
                text += f"; buvid3={buvid['b_3']}"
            if buvid.get("b_4"):
                text += f"; buvid4={buvid['b_4']}"
        return text

    async def api_set_config(self, request):
        body = await request.json()
        changed_room = False
        changed_cookie = False
        if "room_id" in body:
            # 允许直接粘贴直播间链接（如 https://live.bilibili.com/1907444111），
            # 统一解析成房间号再保存。
            new_room = parse_room_id(body.get("room_id"))
            if new_room is None:
                raise web.HTTPBadRequest(
                    text="无法识别房间号，请填写数字或直播间链接"
                )
            if new_room != self.cfg["room_id"]:
                self.cfg["room_id"] = new_room
                changed_room = True
        # 留空表示不修改，避免误清空已保存的登录态
        if body.get("cookie"):
            new_cookie = str(body["cookie"]).strip()
            if new_cookie != self.cfg.get("cookie"):
                self.cfg["cookie"] = new_cookie
                changed_cookie = True
        llm = self.cfg["llm"]
        for key in ("base_url", "model"):
            if body.get(key):
                llm[key] = str(body[key]).strip()
        if body.get("api_key"):
            llm["api_key"] = str(body["api_key"]).strip()
        if "llm_enabled" in body:
            llm["enabled"] = bool(body["llm_enabled"])
        if "auto" in body:
            self.cfg["analyze"]["auto"] = bool(body["auto"])
        save_config(self.cfg)

        if (changed_room or changed_cookie) and self.on_room_change:
            result = self.on_room_change(self.cfg["room_id"])
            if asyncio.iscoroutine(result):
                self.spawn(result)
            if changed_room:
                message = f"已切换直播间 {self.cfg['room_id']}，正在重连…"
            else:
                message = "已更新登录 Cookie，正在重连以恢复正常昵称…"
            self.broadcast({"type": "status", "message": message})
        return web.json_response({"ok": True, "room_changed": changed_room})

    async def api_reconnect(self, request):
        if self.on_room_change:
            result = self.on_room_change(self.cfg["room_id"])
            if asyncio.iscoroutine(result):
                self.spawn(result)
        return web.json_response({"ok": True})

    # ------------------------------------------------------------------
    async def api_stream(self, request):
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream; charset=utf-8",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.subscribers.add(queue)
        try:
            await response.write(b": connected\n\n")
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    await response.write(b": ping\n\n")
                    continue
                payload = json.dumps(item, ensure_ascii=False)
                await response.write(f"data: {payload}\n\n".encode("utf-8"))
        except (asyncio.CancelledError, ConnectionResetError, RuntimeError):
            pass
        finally:
            self.subscribers.discard(queue)
        return response
