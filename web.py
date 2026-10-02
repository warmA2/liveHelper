"""Web 控制台：REST 接口 + SSE 实时推送 + 静态页面。"""

import asyncio
import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set

from aiohttp import web

from analyzer import Analyzer
from config import BASE_DIR, save_config
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
                web.get("/api/events", self.api_events),
                web.get("/api/density", self.api_density),
                web.get("/api/topics", self.api_topics),
                web.get("/api/timeline", self.api_timeline),
                web.get("/api/sessions", self.api_sessions),
                web.get("/api/stream", self.api_stream),
                web.get("/api/config", self.api_get_config),
                web.post("/api/config", self.api_set_config),
                web.post("/api/reconnect", self.api_reconnect),
                web.static("/static", STATIC_DIR),
            ]
        )
        app.on_cleanup.append(self._cleanup)
        return app

    async def _cleanup(self, app):
        for task in list(self._tasks):
            task.cancel()
        await self.analyzer.close()

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
        events = self.store.get_events(
            uid=uid, limit=limit, offset=offset, types=types, session_id=session_id
        )
        total = self.store.count_events_filtered(
            uid=uid, types=types, session_id=session_id
        )
        # 指标基于完整弹幕样本，不受分页影响
        danmaku = self.store.get_events(uid=uid, limit=500, types=["danmaku"])
        metrics = self.analyzer.build_metrics(viewer, danmaku)
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

    async def api_set_config(self, request):
        body = await request.json()
        changed_room = False
        changed_cookie = False
        if "room_id" in body:
            new_room = int(body["room_id"])
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
