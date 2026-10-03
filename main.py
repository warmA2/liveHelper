"""B 站直播辅助助手 —— 启动入口。

一条命令拉起两件事：
  1. 弹幕采集器：连接 B 站直播间，记录进场 / 发言 / 礼物等全部事件并落库
  2. Web 控制台：浏览器打开即可看实时弹幕流、观众列表和 AI 画像
"""

import asyncio
import sys
import time
import webbrowser
from typing import Optional

from aiohttp import web

from analyzer import Analyzer
from bili_live import BiliLiveClient
from config import load_config, prepare_db_file, save_config
from store import Store
from web import Dashboard

LIGHT_FIELDS = (
    "uid", "uname", "msg_count", "enter_count", "follow_count", "like_count",
    "spend_count", "gift_value", "guard_level", "medal_level", "medal_name",
    "last_seen", "profile_status",
)


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.store = Store(prepare_db_file(cfg))
        self.analyzer = Analyzer(self.store, cfg)
        self.client: Optional[BiliLiveClient] = None
        self.client_task: Optional[asyncio.Task] = None
        self.status = {"connected": False, "message": "等待启动", "popularity": 0}
        self._auto_queued = set()
        self._session_room = None
        self.dashboard = Dashboard(
            self.store,
            self.analyzer,
            cfg,
            on_room_change=self.restart_client,
            get_status=self.get_status,
        )

    # ------------------------------------------------------------------
    def get_status(self) -> dict:
        return {
            "connected": self.status.get("connected", False),
            "status_message": self.status.get("message", ""),
            "popularity": self.status.get("popularity", 0),
            "room_id": self.cfg["room_id"],
            # 顶栏「自动画像」常驻开关需要实时状态，跟着 stats 一起下发
            "auto": bool(self.cfg["analyze"].get("auto")),
        }

    async def on_status(self, message: str, meta: Optional[dict] = None):
        meta = meta or {}
        self.status["message"] = message
        if "connected" in meta:
            self.status["connected"] = bool(meta["connected"])
        elif "重连" in message or "断开" in message:
            self.status["connected"] = False
        print(f"[直播] {message}", flush=True)
        self.dashboard.broadcast({"type": "status", "message": message, **self.get_status()})

    async def on_event(self, event: dict):
        saved = self.store.record_event(event)
        if not saved:
            return
        # 用归一化后的 uid：打码弹幕的原始 uid 是合成负数，查不到真实观众
        uid = saved["uid"]
        viewer = self.store.get_viewer(uid)
        light = {k: viewer[k] for k in LIGHT_FIELDS if k in viewer} if viewer else None
        self.dashboard.broadcast(
            {"type": "event", "event": saved, "viewer": light}
        )
        if event["type"] in ("danmaku", "enter", "gift", "guard", "superchat", "follow"):
            self._maybe_autostart(uid, viewer)

    def _maybe_autostart(self, uid: int, viewer: Optional[dict]):
        # 未配置 API Key 时走本地规则画像，零成本，同样值得自动生成
        if not self.cfg["analyze"].get("auto"):
            return
        if not viewer or uid in self._auto_queued:
            return
        if viewer["profile_status"] != "none":
            return
        if viewer["msg_count"] < self.cfg["analyze"]["trigger_after_messages"]:
            return
        self._auto_queued.add(uid)
        print(f"[画像] 自动为 {viewer['uname'] or uid} 生成画像…", flush=True)
        self.dashboard.spawn(self._analyze_and_notify(uid))

    async def _analyze_and_notify(self, uid: int):
        try:
            profile = await self.analyzer.analyze(uid)
            self.dashboard.broadcast(
                {"type": "profile", "uid": uid, "profile": profile, "status": "done"}
            )
        except Exception as exc:
            self._auto_queued.discard(uid)
            self.dashboard.broadcast(
                {"type": "profile", "uid": uid, "status": "error", "error": str(exc)[:300]}
            )

    # ------------------------------------------------------------------
    async def start_client(self, room_id: int):
        if self.client_task:
            self.client_task.cancel()
            try:
                await self.client_task
            except (asyncio.CancelledError, Exception):
                pass
        self.client = BiliLiveClient(
            room_id, self.on_event, self.on_status, cookie=self.cfg.get("cookie", "")
        )
        self.client_task = asyncio.ensure_future(self.client.run_forever())

    async def restart_client(self, room_id: int):
        # 只有房间号真的变了才新开场次 / 换库。
        # 单纯点「重连」或更新 Cookie 时续用当前场次与当前库，
        # 否则时间轴会被切成一堆碎片、不同主播的数据也会串到一起。
        if self._session_room != room_id:
            # 先停掉旧连接，避免切换库期间旧房间的事件写进新库
            if self.client_task:
                self.client_task.cancel()
                try:
                    await self.client_task
                except (asyncio.CancelledError, Exception):
                    pass
                self.client_task = None
            self.store.end_session()
            # 一主播一库：切到目标房间对应的库（首次会自动迁移老库）
            self.store.reopen(prepare_db_file(self.cfg))
            self.store.start_session(room_id)
            self._session_room = room_id
        elif self.store.session_id is None:
            self.store.start_session(room_id)
        self._auto_queued.clear()
        await self.start_client(room_id)

    async def periodic_analysis(self):
        while True:
            interval = max(int(self.cfg["analyze"].get("auto_interval_sec", 600)), 60)
            await asyncio.sleep(interval)
            if not self.cfg["analyze"].get("auto"):
                continue
            try:
                pending = self.store.viewers_needing_analysis(limit=5)
            except Exception:
                continue
            for viewer in pending:
                if viewer["msg_count"] < self.cfg["analyze"]["min_messages"]:
                    continue
                await self._analyze_and_notify(viewer["uid"])
                await asyncio.sleep(1)

    async def popularity_ticker(self):
        while True:
            await asyncio.sleep(10)
            if self.client:
                pop = int(self.client.popularity or 0)
                self.status["popularity"] = pop
                # 人气值原本只活在内存里，落库采样后操作记录才能对比「这段操作涨没涨人气」
                try:
                    self.store.record_popularity(pop, self.store.session_id)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    async def run(self):
        cfg = self.cfg
        if not cfg["room_id"]:
            print("\n[!] config.json 里的 room_id 还是 0，请在网页右上角「设置」里填入你的直播间房间号。\n")

        self.store.start_session(cfg["room_id"])
        self._session_room = cfg["room_id"]
        app = self.dashboard.build_app()
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, cfg["host"], cfg["port"])
        await site.start()

        url = f"http://{cfg['host']}:{cfg['port']}/"
        print("=" * 62)
        print("  B站直播辅助助手 已启动")
        print(f"  控制台: {url}")
        print(f"  直播间: {cfg['room_id'] or '未设置'}")
        print(f"  AI画像: {'已开启 (' + cfg['llm']['model'] + ')' if self.analyzer.enabled else '未配置 API Key，降级为本地规则画像'}")
        print("  按 Ctrl+C 退出")
        print("=" * 62, flush=True)

        if cfg.get("open_browser"):
            try:
                webbrowser.open(url)
            except Exception:
                pass

        if cfg["room_id"]:
            await self.start_client(cfg["room_id"])
        tasks = [
            asyncio.ensure_future(self.periodic_analysis()),
            asyncio.ensure_future(self.popularity_ticker()),
        ]
        try:
            await asyncio.Event().wait()
        finally:
            for task in tasks:
                task.cancel()
            if self.client_task:
                self.client_task.cancel()
            self.store.end_session()
            await runner.cleanup()
            self.store.close()


def main():
    # Windows 控制台默认不是 UTF-8，这里锁定输出编码，避免中文提示变乱码
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    cfg = load_config()
    prepare_db_file(cfg)  # 首次启动时把老库迁移到 data/room_<room_id>.db
    save_config(cfg)  # 补齐新增的默认字段
    app = App(cfg)
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        print("\n已退出，数据已保存在 data/ 目录下当前房间的库文件中")
    except Exception as exc:
        print(f"启动失败：{exc!r}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
