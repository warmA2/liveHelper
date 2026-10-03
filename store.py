"""SQLite 存储层：观众、事件、直播场次。"""

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id     INTEGER NOT NULL,
    started_at  INTEGER NOT NULL,
    ended_at    INTEGER
);

CREATE TABLE IF NOT EXISTS viewers (
    uid             INTEGER PRIMARY KEY,
    uname           TEXT    DEFAULT '',
    first_seen      INTEGER DEFAULT 0,
    last_seen       INTEGER DEFAULT 0,
    msg_count       INTEGER DEFAULT 0,
    enter_count     INTEGER DEFAULT 0,
    follow_count    INTEGER DEFAULT 0,
    like_count      INTEGER DEFAULT 0,
    spend_count     INTEGER DEFAULT 0,
    gift_value      REAL    DEFAULT 0,
    guard_level     INTEGER DEFAULT 0,
    user_level      INTEGER DEFAULT 0,
    medal_name      TEXT    DEFAULT '',
    medal_level     INTEGER DEFAULT 0,
    face            TEXT    DEFAULT '',
    role            TEXT    DEFAULT '',
    last_msg        TEXT    DEFAULT '',
    note            TEXT    DEFAULT '',
    profile_json    TEXT    DEFAULT '',
    profile_status  TEXT    DEFAULT 'none',
    profile_error   TEXT    DEFAULT '',
    profile_updated INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER,
    uid         INTEGER NOT NULL,
    uname       TEXT    DEFAULT '',
    type        TEXT    NOT NULL,
    content     TEXT    DEFAULT '',
    ts          INTEGER NOT NULL,
    extra       TEXT    DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_events_ts      ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_uid     ON events(uid, ts);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, ts);
CREATE INDEX IF NOT EXISTS idx_viewers_active ON viewers(last_seen);

CREATE TABLE IF NOT EXISTS actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER,
    kind        TEXT    NOT NULL,
    label       TEXT    DEFAULT '',
    color       TEXT    DEFAULT '',
    start_ts    INTEGER NOT NULL,
    end_ts      INTEGER NOT NULL,
    note        TEXT    DEFAULT '',
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_actions_end ON actions(end_ts);

CREATE TABLE IF NOT EXISTS metric_samples (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER,
    ts          INTEGER NOT NULL,
    popularity  INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_samples_ts ON metric_samples(ts);

CREATE TABLE IF NOT EXISTS analyses (
    kind        TEXT PRIMARY KEY,
    content     TEXT    DEFAULT '',
    model       TEXT    DEFAULT '',
    created_at  INTEGER DEFAULT 0
);
"""

SORT_COLUMNS = {
    "active": "msg_count DESC, last_seen DESC",
    "recent": "last_seen DESC",
    "value": "gift_value DESC, spend_count DESC",
    "new": "first_seen DESC",
    "enter": "enter_count DESC, last_seen DESC",
}

# 同一观众在该时间窗内的重复进场（ENTRY_EFFECT / INTERACT_WORD 双发、短暂离开又回来）
# 只算一次，避免进场次数虚高。
ENTER_DEDUP_MS = 15000

# 礼物类 / 互动类事件，多处聚合共用
GIFT_TYPES = ("gift", "guard", "superchat")
INTERACT_TYPES = ("follow", "special_follow", "mutual_follow", "share", "like")

# 人气采样间隔下限：断线重连时同一秒可能被写入多次，8 秒内只留一个点
POPULARITY_MIN_GAP_MS = 8000
# 人气采样保留天数
POPULARITY_KEEP_DAYS = 30


class Store:
    def __init__(self, db_path):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        with self._lock:
            self.conn.executescript(SCHEMA)
            self._migrate()
            self._backfill_masked()
            self.conn.commit()
        self.session_id: Optional[int] = None

    def reopen(self, db_path):
        """切换到另一个房间的数据库。

        关闭旧连接、打开新库并重放 schema。Analyzer / Dashboard 等模块持有的是
        同一个 Store 实例，库引用无需重接，会自动跟随。
        """
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = sqlite3.connect(str(path), check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.session_id = None
            self.conn.executescript(SCHEMA)
            self._migrate()
            self._backfill_masked()
            self.conn.commit()
        return path

    def _migrate(self):
        """老库补列：SQLite 的 CREATE TABLE IF NOT EXISTS 不会改动已存在的表。"""
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(viewers)")}
        if "face" not in cols:
            self.conn.execute("ALTER TABLE viewers ADD COLUMN face TEXT DEFAULT ''")
        if "role" not in cols:
            self.conn.execute("ALTER TABLE viewers ADD COLUMN role TEXT DEFAULT ''")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_viewers_face ON viewers(face)")

    # ------------------------------------------------------------------
    # 场次
    # ------------------------------------------------------------------
    def start_session(self, room_id: int) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO sessions(room_id, started_at) VALUES(?,?)",
                (int(room_id), int(time.time() * 1000)),
            )
            self.conn.commit()
            self.session_id = int(cur.lastrowid)
        # 每场开始时清理过期的人气采样，避免这张表无限增长
        self.prune_samples()
        return self.session_id

    def end_session(self):
        if not self.session_id:
            return
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET ended_at=? WHERE id=?",
                (int(time.time() * 1000), self.session_id),
            )
            self.conn.commit()

    # ------------------------------------------------------------------
    # 事件写入
    # ------------------------------------------------------------------
    def record_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        uid = event.get("uid")
        if not uid:
            return None
        uid = int(uid)
        uname = event.get("uname") or ""
        ts = int(event.get("ts") or time.time() * 1000)
        kind = event.get("type") or "unknown"
        content = event.get("content") or ""
        extra = event.get("extra") or {}

        with self._lock:
            face = str(extra.get("face") or "")

            # 匿名/隐私保护时 B 站会隐藏 uid 并把昵称打码成「某***」，两种办法认回真实身份：
            # 1) 头像对齐——进场特效与礼物报文都带头像地址，是最可靠的稳定身份键
            # 2) 昵称对齐——打码只保留首字，用它去匹配唯一的真实观众（不唯一就不猜）
            if face:
                row = self.conn.execute(
                    "SELECT uid FROM viewers WHERE face=? AND uid>0 LIMIT 1", (face,)
                ).fetchone()
                if row and uid < 0:
                    uid = int(row[0])
                if uid > 0:
                    syn = self.conn.execute(
                        "SELECT uid FROM viewers WHERE face=? AND uid<0 LIMIT 1", (face,)
                    ).fetchone()
                    if syn:
                        self._merge_into(uid, int(syn[0]))

            if uid < 0 and "***" in uname:
                real = self._resolve_masked_uname(uname)
                if real:
                    self._merge_into(real, uid)
                    uid = real

            # 进场去重：同一观众在 ENTER_DEDUP_MS 内的重复进场只记一次，
            # 避免 ENTRY_EFFECT / INTERACT_WORD 双发或短暂离开又回来导致进场次数虚高。
            if kind == "enter":
                dup = self.conn.execute(
                    "SELECT 1 FROM events WHERE session_id IS ? AND uid=? AND type='enter' "
                    "AND ts>=? LIMIT 1",
                    (self.session_id, uid, ts - ENTER_DEDUP_MS),
                ).fetchone()
                if dup:
                    return None

            # 先确保观众记录存在
            self.conn.execute(
                "INSERT INTO viewers(uid, uname, first_seen, last_seen) VALUES(?,?,?,?) "
                "ON CONFLICT(uid) DO NOTHING",
                (uid, uname, ts, ts),
            )

            # 反过来：刚认识一个真实观众时，把此前打码期间误建的合成条目并过来。
            # 必须放在上面 INSERT 之后，否则按首字查「唯一真实观众」时还查不到自己。
            if uid > 0 and uname and "***" not in uname:
                self._absorb_masked(uid, uname)
            # 打码昵称（某***）不覆盖已记录的真实昵称
            if "***" in uname:
                builder = [
                    "uname=CASE WHEN uname='' THEN ? ELSE uname END",
                    "last_seen=?",
                ]
            else:
                builder = ["uname=?", "last_seen=?"]
            params: List[Any] = [uname, ts]

            counter = {
                "danmaku": "msg_count",
                "enter": "enter_count",
                "follow": "follow_count",
                "special_follow": "follow_count",
                "mutual_follow": "follow_count",
                "like": "like_count",
            }.get(kind)
            if counter:
                builder.append(f"{counter}={counter}+1")

            if kind == "danmaku":
                builder.append("last_msg=?")
                params.append(content[:200])

            if kind in ("gift", "superchat", "guard"):
                value = float(extra.get("value") or 0)
                # 只有付费礼物（金瓜子）才算消费；银瓜子等免费礼物不计次数与流水。
                # 旧数据没有 paid 字段，按付费处理以保持兼容。
                if extra.get("paid") is not False:
                    builder.append("spend_count=spend_count+1")
                if value:
                    builder.append("gift_value=gift_value+?")
                    params.append(value)

            guard_level = extra.get("guard_level")
            if guard_level:
                builder.append("guard_level=MAX(guard_level, ?)")
                params.append(int(guard_level))

            medal_level = extra.get("medal_level")
            if medal_level:
                builder.append("medal_level=MAX(medal_level, ?)")
                params.append(int(medal_level))
            medal_name = extra.get("medal_name")
            if medal_name:
                builder.append("medal_name=?")
                params.append(medal_name)

            if face:
                builder.append("face=?")
                params.append(face)

            params.append(uid)
            self.conn.execute(
                f"UPDATE viewers SET {', '.join(builder)} WHERE uid=?", params
            )
            # 展示层统一：该观众若已识别出真实昵称，事件里就不再记打码昵称
            row = self.conn.execute(
                "SELECT uname FROM viewers WHERE uid=?", (uid,)
            ).fetchone()
            if row and row[0] and "***" not in row[0]:
                uname = row[0]
            cur = self.conn.execute(
                "INSERT INTO events(session_id, uid, uname, type, content, ts, extra) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    self.session_id,
                    uid,
                    uname,
                    kind,
                    content,
                    ts,
                    json.dumps(extra, ensure_ascii=False),
                ),
            )
            self.conn.commit()
            # 注意：**event 会覆盖上面的归一化结果，所以 uid/uname 必须写在后面，
            # 否则实时推送出去的仍是打码昵称与合成 uid（库里却是干净的）。
            return {
                "id": cur.lastrowid,
                "session_id": self.session_id,
                **event,
                "uid": uid,
                "uname": uname,
            }

    def _merge_into(self, real_uid: int, syn_uid: int):
        """把合成观众（负 uid）的事件与计数并到真实 uid 上。"""
        if real_uid <= 0 or syn_uid >= 0 or real_uid == syn_uid:
            return
        self.conn.execute(
            "INSERT INTO viewers(uid) VALUES(?) ON CONFLICT(uid) DO NOTHING",
            (real_uid,),
        )
        self.conn.execute("UPDATE events SET uid=? WHERE uid=?", (real_uid, syn_uid))
        self.conn.execute("DELETE FROM viewers WHERE uid=?", (syn_uid,))
        # 事件已改挂到真实 uid，据此重算行为聚合，避免合并后计数丢失
        stats = self.conn.execute(
            "SELECT SUM(type='danmaku'), SUM(type='enter'), "
            "SUM(type IN ('follow','special_follow','mutual_follow')), SUM(type='like'), "
            "SUM(CASE WHEN type IN ('gift','superchat','guard') "
            "AND COALESCE(json_extract(extra,'$.paid'),1)<>0 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN type IN ('gift','superchat','guard') "
            "THEN COALESCE(json_extract(extra,'$.value'),0) ELSE 0 END), "
            "MIN(ts), MAX(ts) FROM events WHERE uid=?",
            (real_uid,),
        ).fetchone()
        self.conn.execute(
            "UPDATE viewers SET msg_count=?, enter_count=?, follow_count=?, like_count=?, "
            "spend_count=?, gift_value=?, first_seen=?, last_seen=? WHERE uid=?",
            (
                stats[0] or 0,
                stats[1] or 0,
                stats[2] or 0,
                stats[3] or 0,
                stats[4] or 0,
                stats[5] or 0.0,
                stats[6] or 0,
                stats[7] or 0,
                real_uid,
            ),
        )

    def _resolve_masked_uname(self, uname: str) -> Optional[int]:
        """「初***」这类打码昵称只保留首字，用它匹配唯一的真实观众；不唯一就不猜。"""
        prefix = uname.split("***", 1)[0].strip()
        if not prefix:
            return None
        escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = self.conn.execute(
            "SELECT uid FROM viewers WHERE uid>0 AND uname NOT LIKE '%***%' "
            "AND uname LIKE ? ESCAPE '\\' LIMIT 2",
            (escaped + "%",),
        ).fetchall()
        return int(rows[0][0]) if len(rows) == 1 else None

    def _absorb_masked(self, uid: int, uname: str):
        """真实昵称已知时，把「首字+***」的合成观众并进来（前提是该首字只对应这一个真人）。"""
        prefix = uname[0]
        escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        reals = self.conn.execute(
            "SELECT uid FROM viewers WHERE uid>0 AND uname NOT LIKE '%***%' "
            "AND uname LIKE ? ESCAPE '\\' LIMIT 2",
            (escaped + "%",),
        ).fetchall()
        if len(reals) != 1:
            return
        syns = self.conn.execute(
            "SELECT uid FROM viewers WHERE uid<0 AND uname LIKE ? ESCAPE '\\'",
            (escaped + "***",),
        ).fetchall()
        for row in syns:
            self._merge_into(uid, int(row[0]))

    def _backfill_masked(self):
        """历史遗留修复：把此前打码期间误建的合成观众，按首字唯一匹配并到真实观众。
        幂等，可在每次启动时安全执行；首字不唯一的一律不动。"""
        rows = self.conn.execute(
            "SELECT uid, uname FROM viewers WHERE uid<0 AND uname LIKE '%***%'"
        ).fetchall()
        for row in rows:
            real = self._resolve_masked_uname(row["uname"])
            if real:
                self._merge_into(real, int(row["uid"]))
        # 已识别真实昵称的观众，其历史事件的打码昵称一并刷新为真实昵称
        self.conn.execute(
            "UPDATE events SET uname=("
            "  SELECT v.uname FROM viewers v WHERE v.uid=events.uid"
            ") WHERE uid>0 AND uname LIKE '%***%' AND EXISTS ("
            "  SELECT 1 FROM viewers v WHERE v.uid=events.uid "
            "  AND v.uname<>'' AND v.uname NOT LIKE '%***%'"
            ")"
        )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def _viewer_filters(
        self, keyword: str = "", session_only: bool = False, min_messages: int = 0
    ):
        where = ["1=1"]
        params: List[Any] = []
        if keyword:
            where.append("(uname LIKE ? OR CAST(uid AS TEXT) LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if min_messages:
            where.append("msg_count >= ?")
            params.append(int(min_messages))
        if session_only and self.session_id:
            where.append(
                "uid IN (SELECT DISTINCT uid FROM events WHERE session_id=?)"
            )
            params.append(self.session_id)
        return " AND ".join(where), params

    def list_viewers(
        self,
        sort: str = "active",
        limit: int = 200,
        offset: int = 0,
        keyword: str = "",
        session_only: bool = False,
        min_messages: int = 0,
    ) -> List[dict]:
        order = SORT_COLUMNS.get(sort, SORT_COLUMNS["active"])
        where, params = self._viewer_filters(keyword, session_only, min_messages)
        params.extend([int(limit), int(offset)])
        with self._lock:
            rows = self.conn.execute(
                f"SELECT * FROM viewers WHERE {where} "
                f"ORDER BY {order} LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._viewer_row(r) for r in rows]

    def count_viewers(
        self, keyword: str = "", session_only: bool = False, min_messages: int = 0
    ) -> int:
        where, params = self._viewer_filters(keyword, session_only, min_messages)
        with self._lock:
            return self.conn.execute(
                f"SELECT COUNT(*) FROM viewers WHERE {where}", params
            ).fetchone()[0]

    def get_viewer(self, uid: int) -> Optional[dict]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM viewers WHERE uid=?", (int(uid),)
            ).fetchone()
        return self._viewer_row(row) if row else None

    @staticmethod
    def _event_filters(
        uid: Optional[int] = None,
        session_id: Optional[int] = None,
        types: Optional[List[str]] = None,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        keyword: Optional[str] = None,
    ):
        """拼装事件查询的 WHERE 条件，供 get_events 与 count_events_filtered 复用。"""
        where = ["1=1"]
        params: List[Any] = []
        if uid:
            where.append("uid=?")
            params.append(int(uid))
        if session_id:
            where.append("session_id=?")
            params.append(int(session_id))
        if types:
            where.append(f"type IN ({','.join('?' * len(types))})")
            params.extend(types)
        if from_ts:
            where.append("ts>=?")
            params.append(int(from_ts))
        if to_ts:
            where.append("ts<=?")
            params.append(int(to_ts))
        if keyword:
            # 转义 LIKE 通配符，避免用户输入的 % _ 被当成通配
            escaped = (
                str(keyword)
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            where.append("content LIKE ? ESCAPE '\\'")
            params.append(f"%{escaped}%")
        return " AND ".join(where), params

    def get_events(
        self, uid: Optional[int] = None, limit: int = 100, offset: int = 0,
        types: Optional[List[str]] = None, session_id: Optional[int] = None,
        from_ts: Optional[int] = None, to_ts: Optional[int] = None,
        keyword: Optional[str] = None, order: str = "desc",
    ) -> List[dict]:
        where, params = self._event_filters(uid, session_id, types, from_ts, to_ts, keyword)
        direction = "ASC" if str(order).lower() == "asc" else "DESC"
        params.extend([int(limit), int(offset)])
        with self._lock:
            rows = self.conn.execute(
                f"SELECT * FROM events WHERE {where} "
                f"ORDER BY ts {direction}, id {direction} LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._event_row(r) for r in rows]

    def count_events_filtered(
        self, uid: Optional[int] = None, session_id: Optional[int] = None,
        types: Optional[List[str]] = None, from_ts: Optional[int] = None,
        to_ts: Optional[int] = None, keyword: Optional[str] = None,
    ) -> int:
        where, params = self._event_filters(uid, session_id, types, from_ts, to_ts, keyword)
        with self._lock:
            return self.conn.execute(
                f"SELECT COUNT(*) FROM events WHERE {where}", params
            ).fetchone()[0]

    def count_events_by_type(
        self, uid: Optional[int] = None, session_id: Optional[int] = None
    ) -> Dict[str, int]:
        """按事件类型汇总条数，供画像「行为」分类展示全局口径。"""
        where, params = self._event_filters(uid=uid, session_id=session_id)
        with self._lock:
            rows = self.conn.execute(
                f"SELECT type, COUNT(*) AS n FROM events WHERE {where} GROUP BY type",
                params,
            ).fetchall()
        return {row["type"]: row["n"] for row in rows}

    def event_density(
        self, uid: Optional[int] = None, session_id: Optional[int] = None,
        types: Optional[List[str]] = None, from_ts: Optional[int] = None,
        to_ts: Optional[int] = None, bucket_ms: int = 60000,
    ) -> Dict[str, Any]:
        """按固定时间桶聚合事件数量，供前端画密度曲线。

        ts 是毫秒且为整数，SQLite 的整数除法 (ts / ?) 即为下取整分桶。
        """
        bucket_ms = max(int(bucket_ms), 1000)
        where, params = self._event_filters(uid, session_id, types, from_ts, to_ts)
        with self._lock:
            rows = self.conn.execute(
                f"SELECT (ts / ?) * ? AS bucket, type, COUNT(*) AS n "
                f"FROM events WHERE {where} GROUP BY bucket, type ORDER BY bucket",
                [bucket_ms, bucket_ms, *params],
            ).fetchall()
        groups: Dict[str, List[List[int]]] = {}
        totals: Dict[str, int] = {}
        for row in rows:
            groups.setdefault(row["type"], []).append([row["bucket"], row["n"]])
            totals[row["type"]] = totals.get(row["type"], 0) + row["n"]
        return {
            "bucket_ms": bucket_ms,
            "from_ts": from_ts,
            "to_ts": to_ts,
            "groups": groups,
            "totals": totals,
            "total": sum(totals.values()),
        }

    # ------------------------------------------------------------------
    # 操作记录（唱歌 / PK / 杂谈 …）与指标采样
    # ------------------------------------------------------------------
    def record_action(
        self, kind: str, label: str, color: str, start_ts: int, end_ts: int, note: str = ""
    ) -> dict:
        now = int(time.time() * 1000)
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO actions(session_id, kind, label, color, start_ts, end_ts, note, created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (self.session_id, kind, label, color, int(start_ts), int(end_ts), note, now),
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT * FROM actions WHERE id=?", (cur.lastrowid,)
            ).fetchone()
        return dict(row)

    def list_actions(self, limit: int = 100, session_only: bool = False) -> List[dict]:
        where = "1=1"
        params: List[Any] = []
        if session_only and self.session_id:
            where += " AND session_id=?"
            params.append(self.session_id)
        params.append(int(limit))
        with self._lock:
            rows = self.conn.execute(
                f"SELECT * FROM actions WHERE {where} ORDER BY end_ts DESC, id DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_action(self, action_id: int) -> bool:
        with self._lock:
            cur = self.conn.execute("DELETE FROM actions WHERE id=?", (int(action_id),))
            self.conn.commit()
            return cur.rowcount > 0

    def record_popularity(self, popularity: int, session_id: Optional[int] = None) -> bool:
        """人气值采样。断线时上报的是 0，直接丢掉，免得污染均值。"""
        value = int(popularity or 0)
        if value <= 0:
            return False
        now = int(time.time() * 1000)
        with self._lock:
            last = self.conn.execute("SELECT MAX(ts) FROM metric_samples").fetchone()[0]
            if last and now - int(last) < POPULARITY_MIN_GAP_MS:
                return False
            self.conn.execute(
                "INSERT INTO metric_samples(session_id, ts, popularity) VALUES(?,?,?)",
                (session_id, now, value),
            )
            self.conn.commit()
        return True

    def prune_samples(self, days: int = POPULARITY_KEEP_DAYS):
        cutoff = int(time.time() * 1000) - int(days) * 86400 * 1000
        with self._lock:
            self.conn.execute("DELETE FROM metric_samples WHERE ts < ?", (cutoff,))
            self.conn.commit()

    def popularity_stats(self, from_ts: int, to_ts: int) -> dict:
        with self._lock:
            row = self.conn.execute(
                "SELECT AVG(popularity) AS avg, MAX(popularity) AS max, "
                "MIN(popularity) AS min, COUNT(*) AS n "
                "FROM metric_samples WHERE ts>=? AND ts<=?",
                (int(from_ts), int(to_ts)),
            ).fetchone()
        if not row["n"]:
            return {"avg": None, "max": None, "min": None, "n": 0}
        return {
            "avg": int(round(row["avg"])),
            "max": int(row["max"]),
            "min": int(row["min"]),
            "n": int(row["n"]),
        }

    def window_metrics(self, from_ts: int, to_ts: int) -> dict:
        """一个时间窗内的直播数据概览，供操作记录的效果分析使用。

        同时给出按分钟归一化的 per_min 值，方便不同时长的操作横向比较。
        """
        from_ts, to_ts = int(from_ts), int(to_ts)
        gift_ph = ",".join("?" * len(GIFT_TYPES))
        interact_ph = ",".join("?" * len(INTERACT_TYPES))
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) AS total, "
                "       COUNT(DISTINCT uid) AS people, "
                "       SUM(type='danmaku') AS danmaku, "
                "       SUM(type='enter') AS enter, "
                f"       SUM(type IN ({gift_ph})) AS gift, "
                f"       SUM(type IN ({interact_ph})) AS interact, "
                f"       COALESCE(SUM(CASE WHEN type IN ({gift_ph}) "
                "            THEN CAST(json_extract(extra,'$.value') AS REAL) END), 0) AS income "
                "FROM events WHERE ts>=? AND ts<=?",
                [*GIFT_TYPES, *INTERACT_TYPES, *GIFT_TYPES, from_ts, to_ts],
            ).fetchone()
        popularity = self.popularity_stats(from_ts, to_ts)
        minutes = max((to_ts - from_ts) / 60000.0, 0.0)
        divider = minutes if minutes > 0 else 1.0
        metrics = {
            "minutes": round(minutes, 1),
            "total": int(row["total"] or 0),
            "people": int(row["people"] or 0),
            "danmaku": int(row["danmaku"] or 0),
            "enter": int(row["enter"] or 0),
            "gift": int(row["gift"] or 0),
            "interact": int(row["interact"] or 0),
            "income": round(float(row["income"] or 0), 2),
            "popularity_avg": popularity["avg"],
            "popularity_max": popularity["max"],
            "popularity_n": popularity["n"],
        }
        for key in ("total", "people", "danmaku", "enter", "gift", "interact", "income"):
            metrics[f"{key}_per_min"] = round(metrics[key] / divider, 2)
        return metrics

    def actions_with_metrics(self, limit: int = 100, session_only: bool = False) -> List[dict]:
        items = self.list_actions(limit=limit, session_only=session_only)
        for item in items:
            item["metrics"] = self.window_metrics(item["start_ts"], item["end_ts"])
        return items

    @staticmethod
    def action_summary(items: List[dict]) -> List[dict]:
        """按操作类型汇总：平均每分钟的各项数据，用于横向对比。

        入参是 actions_with_metrics() 的返回值，避免重复查询。
        """
        groups: Dict[str, dict] = {}
        for item in items:
            metrics = item.get("metrics") or {}
            g = groups.setdefault(
                item["kind"],
                {
                    "kind": item["kind"],
                    "label": item.get("label") or item["kind"],
                    "color": item.get("color") or "",
                    "count": 0,
                    "minutes": 0.0,
                    "danmaku": 0.0,
                    "enter": 0.0,
                    "gift": 0.0,
                    "interact": 0.0,
                    "income": 0.0,
                    "popularity": [],
                },
            )
            g["count"] += 1
            g["minutes"] += float(metrics.get("minutes") or 0)
            for key in ("danmaku", "enter", "gift", "interact", "income"):
                g[key] += float(metrics.get(key) or 0)
            if metrics.get("popularity_avg") is not None:
                g["popularity"].append(metrics["popularity_avg"])
        summary: List[dict] = []
        for g in groups.values():
            span = g["minutes"] if g["minutes"] > 0 else 1.0
            pops = g["popularity"]
            summary.append(
                {
                    "kind": g["kind"],
                    "label": g["label"],
                    "color": g["color"],
                    "count": g["count"],
                    "minutes_avg": round(g["minutes"] / g["count"], 1),
                    "danmaku_per_min": round(g["danmaku"] / span, 2),
                    "enter_per_min": round(g["enter"] / span, 2),
                    "gift_per_min": round(g["gift"] / span, 2),
                    "interact_per_min": round(g["interact"] / span, 2),
                    "income_per_min": round(g["income"] / span, 2),
                    "popularity_avg": int(round(sum(pops) / len(pops))) if pops else None,
                }
            )
        summary.sort(key=lambda r: r["danmaku_per_min"], reverse=True)
        return summary

    def baseline_metrics(self) -> Optional[dict]:
        """本场全程的平均每分钟数据，作为对比表里的参照行。"""
        if not self.session_id:
            return None
        with self._lock:
            row = self.conn.execute(
                "SELECT started_at FROM sessions WHERE id=?", (self.session_id,)
            ).fetchone()
        if not row:
            return None
        return self.window_metrics(int(row["started_at"]), int(time.time() * 1000))

    def list_sessions(self, limit: int = 200) -> List[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT s.id, s.room_id, s.started_at, s.ended_at, "
                "  (SELECT COUNT(*) FROM events e WHERE e.session_id=s.id) AS events, "
                "  (SELECT COUNT(DISTINCT uid) FROM events e WHERE e.session_id=s.id) AS viewers "
                "FROM sessions s ORDER BY s.started_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(r) for r in rows]

    def timeline_buckets(self) -> List[dict]:
        """按「本地日期 + 小时」聚合事件，供前端时间轴回看使用。"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT strftime('%Y-%m-%d', ts/1000, 'unixepoch', 'localtime') AS day, "
                "       strftime('%H', ts/1000, 'unixepoch', 'localtime') AS hour, "
                "       COUNT(*) AS events, MIN(ts) AS first_ts, MAX(ts) AS last_ts "
                "FROM events GROUP BY day, hour ORDER BY day DESC, hour DESC"
            ).fetchall()
        buckets: List[dict] = []
        index: Dict[str, dict] = {}
        for row in rows:
            day = row["day"]
            bucket = index.get(day)
            if bucket is None:
                bucket = {"day": day, "events": 0, "hours": []}
                index[day] = bucket
                buckets.append(bucket)
            bucket["events"] += row["events"]
            bucket["hours"].append(
                {
                    "hour": row["hour"],
                    "events": row["events"],
                    "first_ts": row["first_ts"],
                    "last_ts": row["last_ts"],
                }
            )
        return buckets

    def viewer_messages(self, uid: int, limit: int = 40) -> List[dict]:
        return self.get_events(uid=uid, limit=limit, types=["danmaku"])

    def viewer_context(self, uid: int) -> Dict[str, Any]:
        """画像分析所需的「弹幕之外」补充数据。

        弹幕样本（viewer_messages）只覆盖最近若干条，这里补齐：
        - 跨场次光顾：光顾过多少场直播、首次 / 最近一次出现时间
        - 全量作息：全部历史弹幕按本地小时分布（Python 侧换算，避免 SQLite 时区误差）
        - 醒目留言原文、礼物 / 上舰明细及按名称汇总
        """
        uid = int(uid)
        with self._lock:
            visit = self.conn.execute(
                "SELECT COUNT(DISTINCT session_id) AS sessions, "
                "       MIN(ts) AS first_ts, MAX(ts) AS last_ts "
                "FROM events WHERE uid=?",
                (uid,),
            ).fetchone()
            msg_ts = [
                int(r[0])
                for r in self.conn.execute(
                    "SELECT ts FROM events WHERE uid=? AND type='danmaku'", (uid,)
                ).fetchall()
            ]
            sc_rows = self.conn.execute(
                "SELECT content, ts, extra FROM events "
                "WHERE uid=? AND type='superchat' ORDER BY ts DESC LIMIT 20",
                (uid,),
            ).fetchall()
            gift_rows = self.conn.execute(
                "SELECT type, content, ts, extra FROM events "
                "WHERE uid=? AND type IN ('gift','guard') ORDER BY ts DESC LIMIT 60",
                (uid,),
            ).fetchall()
            gift_sum = self.conn.execute(
                "SELECT COALESCE(json_extract(extra,'$.gift_name'), content) AS name, "
                "       COUNT(*) AS n, "
                "       COALESCE(SUM(CAST(json_extract(extra,'$.value') AS REAL)),0) AS amt "
                "FROM events WHERE uid=? AND type='gift' "
                "  AND COALESCE(json_extract(extra,'$.paid'),1)<>0 "
                "GROUP BY name ORDER BY amt DESC LIMIT 10",
                (uid,),
            ).fetchall()
            guard_sum = self.conn.execute(
                "SELECT COALESCE(json_extract(extra,'$.guard_level'),0) AS lv, "
                "       COUNT(*) AS n, "
                "       COALESCE(SUM(CAST(json_extract(extra,'$.value') AS REAL)),0) AS amt "
                "FROM events WHERE uid=? AND type='guard' GROUP BY lv ORDER BY lv",
                (uid,),
            ).fetchall()

        hours: Dict[int, int] = {}
        for ts in msg_ts:
            hour = time.localtime(ts / 1000).tm_hour
            hours[hour] = hours.get(hour, 0) + 1

        superchats = []
        for row in sc_rows:
            extra = self._load_extra(row["extra"])
            superchats.append({
                "ts": int(row["ts"]),
                "content": row["content"] or "",
                "value": round(float(extra.get("value") or 0), 2),
            })

        gifts = []
        for row in gift_rows:
            extra = self._load_extra(row["extra"])
            gifts.append({
                "ts": int(row["ts"]),
                "type": row["type"],
                "content": row["content"] or "",
                "name": extra.get("gift_name") or "",
                "num": int(extra.get("num") or 1),
                "value": round(float(extra.get("value") or 0), 2),
                "paid": extra.get("paid") is not False,
                "guard_level": int(extra.get("guard_level") or 0),
            })

        return {
            "visit_sessions": int(visit["sessions"] or 0),
            "first_visit_ts": int(visit["first_ts"] or 0),
            "last_visit_ts": int(visit["last_ts"] or 0),
            "all_msg_hours": {str(k): v for k, v in sorted(hours.items())},
            "all_msg_count": len(msg_ts),
            "superchats": superchats,
            "gifts": gifts,
            "gift_summary": [
                {"name": r["name"] or "礼物", "count": r["n"], "amount": round(float(r["amt"]), 2)}
                for r in gift_sum
            ],
            "guard_summary": [
                {"level": int(r["lv"] or 0), "count": r["n"], "amount": round(float(r["amt"]), 2)}
                for r in guard_sum
            ],
        }

    def session_stats(self) -> dict:
        with self._lock:
            total_viewers = self.conn.execute(
                "SELECT COUNT(*) FROM viewers"
            ).fetchone()[0]
            if self.session_id:
                row = self.conn.execute(
                    "SELECT COUNT(DISTINCT uid) AS people, COUNT(*) AS events "
                    "FROM events WHERE session_id=?",
                    (self.session_id,),
                ).fetchone()
                people, events = row["people"], row["events"]
                danmaku = self.conn.execute(
                    "SELECT COUNT(*) FROM events WHERE session_id=? AND type='danmaku'",
                    (self.session_id,),
                ).fetchone()[0]
                income = self.conn.execute(
                    "SELECT COALESCE(SUM(CAST(json_extract(extra,'$.value') AS REAL)),0) "
                    "FROM events WHERE session_id=? AND type IN ('gift','superchat','guard')",
                    (self.session_id,),
                ).fetchone()[0]
                guards = self.conn.execute(
                    "SELECT COUNT(*) FROM events WHERE session_id=? AND type='guard'",
                    (self.session_id,),
                ).fetchone()[0]
                started = self.conn.execute(
                    "SELECT started_at FROM sessions WHERE id=?", (self.session_id,)
                ).fetchone()[0]
            else:
                people = events = danmaku = income = guards = 0
                started = 0
        return {
            "session_id": self.session_id,
            "started_at": started,
            "session_viewers": people,
            "session_events": events,
            "session_danmaku": danmaku,
            "session_income": round(float(income), 2),
            "session_guards": guards,
            "total_viewers": total_viewers,
        }

    def career_stats(self) -> dict:
        """主播生涯口径：跨全部场次的累计统计（与 session_stats 的本场口径区分）。"""
        with self._lock:
            sessions = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            row = self.conn.execute(
                "SELECT COUNT(*) AS events, COUNT(DISTINCT uid) AS active, "
                "MIN(ts) AS first_ts, MAX(ts) AS last_ts FROM events"
            ).fetchone()
            danmaku = self.conn.execute(
                "SELECT COUNT(*) FROM events WHERE type='danmaku'"
            ).fetchone()[0]
            guards = self.conn.execute(
                "SELECT COUNT(*) FROM events WHERE type='guard'"
            ).fetchone()[0]
            income = self.conn.execute(
                "SELECT COALESCE(SUM(CAST(json_extract(extra,'$.value') AS REAL)),0) "
                "FROM events WHERE type IN ('gift','superchat','guard')"
            ).fetchone()[0]
            payers = self.conn.execute(
                "SELECT COUNT(DISTINCT uid) FROM events "
                "WHERE type IN ('gift','superchat','guard') "
                "AND COALESCE(json_extract(extra,'$.paid'),1)<>0"
            ).fetchone()[0]
            viewers = self.conn.execute("SELECT COUNT(*) FROM viewers").fetchone()[0]
            days = self.conn.execute(
                "SELECT COUNT(DISTINCT strftime('%Y-%m-%d', ts/1000, 'unixepoch', 'localtime')) "
                "FROM events"
            ).fetchone()[0]
            # 开播时长：优先取 ended_at；异常退出（未写结束时间）的场次用该场最后事件时间兜底
            spans = self.conn.execute(
                "SELECT s.started_at, "
                "  COALESCE(s.ended_at, "
                "           (SELECT MAX(ts) FROM events e WHERE e.session_id=s.id), "
                "           s.started_at) AS stopped_at "
                "FROM sessions s"
            ).fetchall()
        duration_ms = sum(
            max(0, int(r["stopped_at"] or 0) - int(r["started_at"] or 0)) for r in spans
        )
        return {
            "sessions": sessions,
            "days": days,
            "duration_ms": duration_ms,
            "first_ts": row["first_ts"] or 0,
            "last_ts": row["last_ts"] or 0,
            "events": row["events"] or 0,
            "total_viewers": viewers,
            "active_viewers": row["active"] or 0,
            "danmaku": danmaku,
            "guards": guards,
            "income": round(float(income), 2),
            "payers": payers,
        }

    # ------------------------------------------------------------------
    # AI 分析（本场直播 / 生涯）
    # ------------------------------------------------------------------
    def session_insights(self) -> Optional[Dict[str, Any]]:
        """本场直播的全量聚合，供 AI 生成本场分析。未开播返回 None。"""
        sid = self.session_id
        if not sid:
            return None
        gift_ph = ",".join("?" * len(GIFT_TYPES))
        with self._lock:
            sess = self.conn.execute(
                "SELECT started_at, ended_at FROM sessions WHERE id=?", (sid,)
            ).fetchone()
            if not sess:
                return None
            started = int(sess["started_at"])
            ended = int(sess["ended_at"] or time.time() * 1000)
            totals = self.conn.execute(
                "SELECT COUNT(*) AS events, COUNT(DISTINCT uid) AS people, "
                "  SUM(type='danmaku') AS danmaku, SUM(type='enter') AS enter, "
                f"  SUM(type IN ({gift_ph})) AS gift, SUM(type='guard') AS guard, "
                "  SUM(type='superchat') AS superchat, "
                "  COALESCE(SUM(CASE WHEN type IN ('gift','superchat','guard') "
                "    THEN CAST(json_extract(extra,'$.value') AS REAL) ELSE 0 END),0) AS income "
                "FROM events WHERE session_id=?",
                [*GIFT_TYPES, sid],
            ).fetchone()
            new_viewers = self.conn.execute(
                "SELECT COUNT(*) FROM viewers WHERE first_seen>=? AND first_seen<=?",
                (started, ended),
            ).fetchone()[0]
            top_speakers = self.conn.execute(
                "SELECT uid, uname, COUNT(*) AS n FROM events "
                "WHERE session_id=? AND type='danmaku' GROUP BY uid "
                "ORDER BY n DESC LIMIT 10",
                (sid,),
            ).fetchall()
            top_spenders = self.conn.execute(
                "SELECT uid, uname, COUNT(*) AS n, "
                "  COALESCE(SUM(CAST(json_extract(extra,'$.value') AS REAL)),0) AS amount "
                f"FROM events WHERE session_id=? AND type IN ({gift_ph}) "
                "GROUP BY uid ORDER BY amount DESC LIMIT 10",
                [sid, *GIFT_TYPES],
            ).fetchall()
            gift_sum = self.conn.execute(
                "SELECT COALESCE(json_extract(extra,'$.gift_name'), content) AS name, "
                "  COUNT(*) AS n, "
                "  COALESCE(SUM(CAST(json_extract(extra,'$.value') AS REAL)),0) AS amt "
                "FROM events WHERE session_id=? AND type='gift' "
                "  AND COALESCE(json_extract(extra,'$.paid'),1)<>0 "
                "GROUP BY name ORDER BY amt DESC LIMIT 10",
                (sid,),
            ).fetchall()
            guard_sum = self.conn.execute(
                "SELECT COALESCE(json_extract(extra,'$.guard_level'),0) AS lv, "
                "  COUNT(*) AS n, "
                "  COALESCE(SUM(CAST(json_extract(extra,'$.value') AS REAL)),0) AS amt "
                "FROM events WHERE session_id=? AND type='guard' GROUP BY lv ORDER BY lv",
                (sid,),
            ).fetchall()
            pop = self.conn.execute(
                "SELECT AVG(popularity) AS avg, MAX(popularity) AS max, COUNT(*) AS n "
                "FROM metric_samples WHERE session_id=?",
                (sid,),
            ).fetchone()
            hours = self.conn.execute(
                "SELECT strftime('%H', ts/1000, 'unixepoch', 'localtime') AS h, "
                "  COUNT(*) AS n FROM events "
                "WHERE session_id=? AND type='danmaku' GROUP BY h ORDER BY h",
                (sid,),
            ).fetchall()
        actions = self.actions_with_metrics(limit=100, session_only=True)
        return {
            "session_id": sid,
            "started_at": started,
            "ended_at": int(sess["ended_at"] or 0),
            "duration_ms": max(0, ended - started),
            "events": int(totals["events"] or 0),
            "people": int(totals["people"] or 0),
            "danmaku": int(totals["danmaku"] or 0),
            "enter": int(totals["enter"] or 0),
            "gift": int(totals["gift"] or 0),
            "guard": int(totals["guard"] or 0),
            "superchat": int(totals["superchat"] or 0),
            "income": round(float(totals["income"] or 0), 2),
            "new_viewers": int(new_viewers or 0),
            "top_speakers": [
                {"uid": r["uid"], "uname": r["uname"] or "", "count": r["n"]}
                for r in top_speakers
            ],
            "top_spenders": [
                {
                    "uid": r["uid"],
                    "uname": r["uname"] or "",
                    "count": r["n"],
                    "amount": round(float(r["amount"] or 0), 2),
                }
                for r in top_spenders
                if float(r["amount"] or 0) > 0
            ],
            "gift_summary": [
                {"name": r["name"] or "礼物", "count": r["n"], "amount": round(float(r["amt"]), 2)}
                for r in gift_sum
            ],
            "guard_summary": [
                {"level": int(r["lv"] or 0), "count": r["n"], "amount": round(float(r["amt"]), 2)}
                for r in guard_sum
            ],
            "popularity": {
                "avg": int(round(pop["avg"])) if pop["n"] else None,
                "max": int(pop["max"]) if pop["n"] else None,
                "n": int(pop["n"] or 0),
            },
            "hour_hist": {f"{r['h']}点": r["n"] for r in hours},
            "actions": actions,
            "action_summary": self.action_summary(actions),
        }

    def career_insights(self) -> Dict[str, Any]:
        """生涯全量聚合，供 AI 生成生涯分析。"""
        stats = self.career_stats()
        gift_ph = ",".join("?" * len(GIFT_TYPES))
        with self._lock:
            top_speakers = self.conn.execute(
                "SELECT uid, uname, COUNT(*) AS n FROM events WHERE type='danmaku' "
                "GROUP BY uid ORDER BY n DESC LIMIT 10"
            ).fetchall()
            top_spenders = self.conn.execute(
                "SELECT uid, uname, COUNT(*) AS n, "
                "  COALESCE(SUM(CAST(json_extract(extra,'$.value') AS REAL)),0) AS amount "
                f"FROM events WHERE type IN ({gift_ph}) "
                "GROUP BY uid ORDER BY amount DESC LIMIT 10",
                list(GIFT_TYPES),
            ).fetchall()
            gift_sum = self.conn.execute(
                "SELECT COALESCE(json_extract(extra,'$.gift_name'), content) AS name, "
                "  COUNT(*) AS n, "
                "  COALESCE(SUM(CAST(json_extract(extra,'$.value') AS REAL)),0) AS amt "
                "FROM events WHERE type='gift' "
                "  AND COALESCE(json_extract(extra,'$.paid'),1)<>0 "
                "GROUP BY name ORDER BY amt DESC LIMIT 10"
            ).fetchall()
            guard_dist = self.conn.execute(
                "SELECT COALESCE(json_extract(extra,'$.guard_level'),0) AS lv, "
                "  COUNT(*) AS n, "
                "  COALESCE(SUM(CAST(json_extract(extra,'$.value') AS REAL)),0) AS amt "
                "FROM events WHERE type='guard' GROUP BY lv ORDER BY lv"
            ).fetchall()
            hours = self.conn.execute(
                "SELECT strftime('%H', ts/1000, 'unixepoch', 'localtime') AS h, "
                "  COUNT(*) AS n FROM events WHERE type='danmaku' GROUP BY h ORDER BY h"
            ).fetchall()
            daily = self.conn.execute(
                "SELECT strftime('%Y-%m-%d', ts/1000, 'unixepoch', 'localtime') AS day, "
                "  COUNT(*) AS n, "
                "  COALESCE(SUM(CAST(json_extract(extra,'$.value') AS REAL)),0) AS amount "
                f"FROM events WHERE type IN ({gift_ph}) "
                "GROUP BY day ORDER BY day DESC LIMIT 30",
                list(GIFT_TYPES),
            ).fetchall()
            action_kinds = self.conn.execute(
                "SELECT kind, COUNT(*) AS n, "
                "  COALESCE(SUM(end_ts - start_ts),0) AS dur "
                "FROM actions GROUP BY kind ORDER BY n DESC"
            ).fetchall()
        return {
            **stats,
            "top_speakers": [
                {"uid": r["uid"], "uname": r["uname"] or "", "count": r["n"]}
                for r in top_speakers
            ],
            "top_spenders": [
                {
                    "uid": r["uid"],
                    "uname": r["uname"] or "",
                    "count": r["n"],
                    "amount": round(float(r["amount"] or 0), 2),
                }
                for r in top_spenders
                if float(r["amount"] or 0) > 0
            ],
            "gift_summary": [
                {"name": r["name"] or "礼物", "count": r["n"], "amount": round(float(r["amt"]), 2)}
                for r in gift_sum
            ],
            "guard_dist": [
                {"level": int(r["lv"] or 0), "count": r["n"], "amount": round(float(r["amt"]), 2)}
                for r in guard_dist
            ],
            "hour_hist": {f"{r['h']}点": r["n"] for r in hours},
            "daily_income": [
                {"day": r["day"], "count": r["n"], "amount": round(float(r["amount"] or 0), 2)}
                for r in reversed(daily)
            ],
            "action_kinds": [
                {"kind": r["kind"], "count": r["n"], "minutes": round(float(r["dur"] or 0) / 60000.0, 1)}
                for r in action_kinds
            ],
        }

    def save_analysis(self, kind: str, content: str, model: str = ""):
        with self._lock:
            self.conn.execute(
                "INSERT INTO analyses(kind, content, model, created_at) VALUES(?,?,?,?) "
                "ON CONFLICT(kind) DO UPDATE SET content=excluded.content, "
                "model=excluded.model, created_at=excluded.created_at",
                (str(kind), str(content), str(model), int(time.time() * 1000)),
            )
            self.conn.commit()

    def get_analysis(self, kind: str) -> Optional[dict]:
        with self._lock:
            row = self.conn.execute(
                "SELECT kind, content, model, created_at FROM analyses WHERE kind=?",
                (str(kind),),
            ).fetchone()
        return dict(row) if row else None

    def viewers_needing_analysis(self, limit: int = 20) -> List[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM viewers WHERE profile_status IN ('none','stale','error') "
                "AND msg_count >= 1 ORDER BY last_seen DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [self._viewer_row(r) for r in rows]

    def count_events(self, uid: int) -> int:
        with self._lock:
            return self.conn.execute(
                "SELECT COUNT(*) FROM events WHERE uid=?", (int(uid),)
            ).fetchone()[0]

    # ------------------------------------------------------------------
    # 画像 / 备注
    # ------------------------------------------------------------------
    def set_profile_status(self, uid: int, status: str, error: str = ""):
        with self._lock:
            self.conn.execute(
                "UPDATE viewers SET profile_status=?, profile_error=? WHERE uid=?",
                (status, error, int(uid)),
            )
            self.conn.commit()

    def save_profile(self, uid: int, profile: Dict[str, Any], model: str = ""):
        payload = dict(profile)
        payload["_model"] = model
        payload["_generated_at"] = int(time.time() * 1000)
        with self._lock:
            self.conn.execute(
                "UPDATE viewers SET profile_json=?, profile_status='done', "
                "profile_error='', profile_updated=? WHERE uid=?",
                (
                    json.dumps(payload, ensure_ascii=False),
                    int(time.time() * 1000),
                    int(uid),
                ),
            )
            self.conn.commit()

    def set_note(self, uid: int, note: str):
        with self._lock:
            self.conn.execute(
                "UPDATE viewers SET note=? WHERE uid=?", (note, int(uid))
            )
            self.conn.commit()

    def set_viewer_role(self, uid: int, role: str):
        """手动给观众指定身份（如「AI助手」「房管」）；传空串即清除标记。"""
        with self._lock:
            self.conn.execute(
                "UPDATE viewers SET role=? WHERE uid=?", (role, int(uid))
            )
            self.conn.commit()

    def list_roles(self) -> Dict[str, str]:
        """所有已标记身份的观众，供前端按 uid 快速取用（数量很少）。"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT uid, role FROM viewers WHERE role<>''"
            ).fetchall()
        return {str(r["uid"]): r["role"] for r in rows}

    # ------------------------------------------------------------------
    def close(self):
        with self._lock:
            self.conn.close()

    @staticmethod
    def _viewer_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        # user_level 列已废弃（历史数据把直播荣耀等级与财富等级混在一起，不可用），
        # 不再对外暴露，避免误用。
        data.pop("user_level", None)
        raw = data.pop("profile_json", "") or ""
        try:
            data["profile"] = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            data["profile"] = None
        data["gift_value"] = round(float(data.get("gift_value") or 0), 2)
        return data

    @staticmethod
    def _load_extra(raw: Any) -> dict:
        try:
            data = json.loads(raw or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _event_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["extra"] = Store._load_extra(data.pop("extra", "{}"))
        return data
