"""B 站直播间弹幕接入层。

流程：
  1. room_init             短号 -> 真实房间号
  2. finger/spi            获取 buvid3 / buvid4（新版 getDanmuInfo 有风控校验）
  3. getDanmuInfo          拿到弹幕服务器地址与鉴权 token
  4. wss://<host>/sub      发送鉴权包 -> 30s 心跳 -> 收包解压 -> 解析 cmd

注意：这里直连 B 站公开弹幕协议，只读、不发送任何内容。
未登录也能跑，但连接约 5 分钟后 B 站会把弹幕发送者的昵称打码成 *，
填入 config.json 的 cookie 字段（浏览器登录后的 Cookie）即可拿到真实昵称。
"""

import asyncio
import base64
import json
import random
import re
import struct
import time
import zlib
from typing import Any, Callable, Dict, List, Optional

import aiohttp
import brotli

HEADER = struct.Struct(">IHHII")
HEADER_LEN = HEADER.size

OP_HEARTBEAT = 2
OP_HEARTBEAT_REPLY = 3
OP_MESSAGE = 5
OP_AUTH = 7
OP_AUTH_REPLY = 8

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
BASE_HEADERS = {
    "User-Agent": UA,
    "Referer": "https://live.bilibili.com/",
    "Origin": "https://live.bilibili.com",
    "Accept": "application/json, text/plain, */*",
}


# --------------------------------------------------------------------------
# 包编解码
# --------------------------------------------------------------------------
def encode_packet(operation: int, body: bytes, proto_ver: int = 1) -> bytes:
    header = HEADER.pack(
        HEADER_LEN + len(body), HEADER_LEN, proto_ver, operation, 1
    )
    return header + body


def _iter_packets(data: bytes):
    offset = 0
    total = len(data)
    while offset + HEADER_LEN <= total:
        pkt_len, hdr_len, proto_ver, operation, _ = HEADER.unpack_from(data, offset)
        if pkt_len < HEADER_LEN or offset + pkt_len > total:
            break
        yield proto_ver, operation, data[offset + hdr_len : offset + pkt_len]
        offset += pkt_len


def expand_packets(data: bytes) -> List[tuple]:
    """递归解开 zlib(2) / brotli(3) 压缩包，返回 [(proto_ver, op, body)]。"""
    result = []
    for proto_ver, operation, body in _iter_packets(data):
        if proto_ver == 2:
            try:
                result.extend(expand_packets(zlib.decompress(body)))
            except zlib.error:
                pass
        elif proto_ver == 3:
            try:
                result.extend(expand_packets(brotli.decompress(body)))
            except Exception:
                pass
        else:
            result.append((proto_ver, operation, body))
    return result


# --------------------------------------------------------------------------
# 极简 protobuf 解析（仅用于 INTERACT_WORD_V2 进场消息）
# --------------------------------------------------------------------------
def _read_varint(buf: bytes, pos: int):
    value = 0
    shift = 0
    while pos < len(buf):
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
        if shift > 63:
            break
    raise ValueError("varint overflow")


def _parse_protobuf(buf: bytes) -> Dict[int, List[tuple]]:
    fields: Dict[int, List[tuple]] = {}
    pos = 0
    while pos < len(buf):
        try:
            key, pos = _read_varint(buf, pos)
        except ValueError:
            break
        field_no, wire = key >> 3, key & 7
        try:
            if wire == 0:
                value, pos = _read_varint(buf, pos)
                fields.setdefault(field_no, []).append(("v", value))
            elif wire == 2:
                length, pos = _read_varint(buf, pos)
                fields.setdefault(field_no, []).append(("b", buf[pos : pos + length]))
                pos += length
            elif wire == 5:
                fields.setdefault(field_no, []).append(("f", buf[pos : pos + 4]))
                pos += 4
            elif wire == 1:
                fields.setdefault(field_no, []).append(("d", buf[pos : pos + 8]))
                pos += 8
            else:
                break
        except (ValueError, IndexError):
            break
    return fields


def _pb_int(fields: Dict[int, List[tuple]], field_no: int) -> int:
    for kind, value in fields.get(field_no, []):
        if kind == "v":
            return value
    return 0


def _pb_str(fields: Dict[int, List[tuple]], field_no: int) -> str:
    for kind, value in fields.get(field_no, []):
        if kind == "b":
            try:
                return value.decode("utf-8", "replace")
            except Exception:
                return ""
    return ""


def parse_interact_word_v2(pb_payload: Any) -> Optional[dict]:
    """INTERACT_WORD_V2 的 data.pb 是 base64 后的 protobuf。"""
    if isinstance(pb_payload, bytes):
        raw = pb_payload
    elif isinstance(pb_payload, str):
        try:
            raw = base64.b64decode(pb_payload)
        except Exception:
            return None
    else:
        return None

    fields = _parse_protobuf(raw)
    # 部分版本外面还包了一层 message（field 1 为 bytes）
    if 5 not in fields and 1 in fields and fields[1] and fields[1][0][0] == "b":
        inner = _parse_protobuf(fields[1][0][1])
        if 5 in inner or 1 in inner:
            fields = inner

    uid = _pb_int(fields, 1)
    if not uid:
        return None
    return {
        "uid": uid,
        "uname": _pb_str(fields, 2),
        "msg_type": _pb_int(fields, 5),
        "roomid": _pb_int(fields, 6),
        "timestamp": _pb_int(fields, 7) or int(time.time() * 1000),
    }


# --------------------------------------------------------------------------
# HTTP 接口
# --------------------------------------------------------------------------
async def _get_json(session: aiohttp.ClientSession, url: str, headers=None) -> dict:
    async with session.get(
        url, headers=headers or BASE_HEADERS, timeout=aiohttp.ClientTimeout(total=15)
    ) as resp:
        return await resp.json(content_type=None)


async def fetch_buvid(session: aiohttp.ClientSession) -> Dict[str, str]:
    try:
        payload = await _get_json(
            session, "https://api.bilibili.com/x/frontend/finger/spi"
        )
        data = payload.get("data") or {}
        if data.get("b_3"):
            return {"b_3": data.get("b_3", ""), "b_4": data.get("b_4", "")}
    except Exception:
        pass
    # 兜底：本地伪造一个未激活 buvid3，绝大多数情况下仍可获取弹幕配置
    fake = "".join(random.choice("0123456789ABCDEF") for _ in range(32)) + "infoc"
    return {"b_3": fake, "b_4": ""}


async def fetch_real_room_id(session: aiohttp.ClientSession, room_id: int) -> int:
    payload = await _get_json(
        session,
        f"https://api.live.bilibili.com/room/v1/Room/room_init?id={int(room_id)}",
    )
    if payload.get("code") != 0:
        raise RuntimeError(f"room_init 失败: {payload.get('message') or payload}")
    return int(payload["data"]["room_id"])


async def fetch_danmu_info(
    session: aiohttp.ClientSession,
    real_room_id: int,
    buvid: Dict[str, str],
    cookie: str = "",
) -> dict:
    parts = []
    if cookie:
        parts.append(cookie.strip().rstrip(";"))
    if buvid.get("b_3"):
        parts.append(f"buvid3={buvid['b_3']}")
    if buvid.get("b_4"):
        parts.append(f"buvid4={buvid['b_4']}")
    headers = {**BASE_HEADERS, "Cookie": "; ".join(parts)}
    payload = await _get_json(
        session,
        "https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo"
        f"?id={real_room_id}&type=0",
        headers=headers,
    )
    if payload.get("code") != 0:
        raise RuntimeError(
            f"getDanmuInfo 失败({payload.get('code')}): {payload.get('message')}"
        )
    return payload["data"]


async def fetch_danmu_conf(session: aiohttp.ClientSession, real_room_id: int) -> dict:
    """兼容接口：getDanmuInfo 被风控(-352)挡掉时的降级方案。

    返回结构与 getDanmuInfo 对齐：{"token": str, "host_list": [...]}。
    """
    payload = await _get_json(
        session,
        "https://api.live.bilibili.com/room/v1/Danmu/getConf"
        f"?room_id={real_room_id}&platform=pc&player=web",
    )
    if payload.get("code") != 0:
        raise RuntimeError(
            f"getConf 失败({payload.get('code')}): {payload.get('message')}"
        )
    data = payload["data"]
    host_list = []
    for item in data.get("host_server_list") or []:
        if not item.get("host"):
            continue
        host_list.append(
            {
                "host": item["host"],
                "wss_port": item.get("wss_port") or 443,
                "ws_port": item.get("ws_port") or 2244,
                "port": item.get("port") or 2243,
            }
        )
    if not host_list and data.get("host"):
        host_list.append(
            {
                "host": data["host"],
                "wss_port": 443,
                "ws_port": 2244,
                "port": data.get("port") or 2243,
            }
        )
    return {"token": data.get("token") or "", "host_list": host_list}


# --------------------------------------------------------------------------
# 事件解析
# --------------------------------------------------------------------------
def _now_ms() -> int:
    return int(time.time() * 1000)


def _meta_extra(meta: list) -> dict:
    """info[0][15] 里嵌了一个 JSON 字符串形式的 extra，含 user_hash 等字段。"""
    if len(meta) > 15 and isinstance(meta[15], dict):
        raw = meta[15].get("extra")
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {}
        if isinstance(raw, dict):
            return raw
    return {}


def parse_danmaku(data: dict) -> Optional[dict]:
    info = data.get("info") or []
    if not info:
        return None
    text = info[1] if len(info) > 1 and isinstance(info[1], str) else ""
    meta = info[0] if isinstance(info[0], list) else []
    ts = meta[4] if len(meta) > 4 and isinstance(meta[4], int) else _now_ms()

    user = info[2] if len(info) > 2 and isinstance(info[2], list) else []
    uid = user[0] if user and isinstance(user[0], int) else 0
    uname = user[1] if len(user) > 1 and isinstance(user[1], str) else ""

    medal = info[3] if len(info) > 3 and isinstance(info[3], list) else []
    guard_level = info[7] if len(info) > 7 and isinstance(info[7], int) else 0

    # 开了隐私保护的观众：uid 被置 0、昵称被打码。
    # 用 B 站下发的稳定 user_hash 造一个负数合成 ID，避免这些人被整条丢弃。
    anonymous = False
    if not uid:
        extra = _meta_extra(meta)
        seed = str(extra.get("user_hash") or "")
        if not seed and len(meta) > 7 and isinstance(meta[7], str):
            seed = meta[7]
        if not seed:
            return None
        uid = -((zlib.crc32(seed.encode("utf-8")) & 0x7FFFFFFF) + 1)
        anonymous = True
        if not uname:
            uname = "神秘观众"

    return {
        "type": "danmaku",
        "uid": int(uid),
        "uname": uname,
        "content": text,
        "ts": ts,
        "extra": {
            "guard_level": guard_level,
            "medal_level": medal[0] if medal and isinstance(medal[0], int) else 0,
            "medal_name": medal[1] if len(medal) > 1 and isinstance(medal[1], str) else "",
            "medal_anchor": medal[2] if len(medal) > 2 and isinstance(medal[2], str) else "",
            "is_admin": bool(user[2]) if len(user) > 2 else False,
            "anonymous": anonymous,
        },
    }


INTERACT_TYPES = {1: "enter", 2: "follow", 3: "share", 4: "special_follow", 5: "mutual_follow"}
INTERACT_LABELS = {
    "enter": "进入直播间",
    "follow": "关注了主播",
    "share": "分享了直播间",
    "special_follow": "特别关注",
    "mutual_follow": "互粉",
}


def parse_interact_word(data: dict, ts_fallback: int = 0) -> Optional[dict]:
    uid = data.get("uid")
    if not uid:
        return None
    msg_type = data.get("msg_type")
    kind = INTERACT_TYPES.get(msg_type, "enter")
    ts = data.get("timestamp")
    if not isinstance(ts, int) or ts <= 0:
        ts = ts_fallback or _now_ms()
    elif ts < 10 ** 12:
        # B站 INTERACT_WORD 的 timestamp 是秒级，统一成毫秒，否则时间轴会落到 1970 年
        ts *= 1000
    uname = data.get("uname") or data.get("uname_color") or ""
    return {
        "type": kind,
        "uid": int(uid),
        "uname": uname,
        "content": INTERACT_LABELS.get(kind, "互动"),
        "ts": ts,
        "extra": {
            "identities": data.get("identities") or [],
            "medal": data.get("fans_medal") or None,
            "face": ((data.get("uinfo") or {}).get("base") or {}).get("face") or "",
        },
    }


UINT64_MAX = (1 << 64) - 1


def _synthetic_uid(seed: str) -> int:
    """给拿不到真实 uid 的观众造一个稳定的负数合成 ID。"""
    return -((zlib.crc32(seed.encode("utf-8")) & 0x7FFFFFFF) + 1)


def parse_gift_v2(pb_payload: Any, ts_fallback: int = 0) -> Optional[dict]:
    """SEND_GIFT_V2 的 data.pb 是 base64 后的 protobuf（新协议已不再下发旧版 JSON 结构）。

    字段位置（经抓包核对）：
      顶层  1=uid(隐私保护时为 -1/缺省) 2=昵称 3=头像
      10    礼物信息：1=礼物 ID 2=礼物名 3=数量 5=单价(金瓜子) 8=币种 9=订单号 10=时间戳(秒)
    """
    if isinstance(pb_payload, bytes):
        raw = pb_payload
    elif isinstance(pb_payload, str) and pb_payload:
        try:
            raw = base64.b64decode(pb_payload + "=" * (-len(pb_payload) % 4))
        except Exception:
            return None
    else:
        return None

    fields = _parse_protobuf(raw)
    gift: Dict[int, List[tuple]] = {}
    for kind, value in fields.get(10, []):
        if kind == "b":
            gift = _parse_protobuf(value)
            break
    if not gift:
        return None

    # 开了隐私保护的观众 uid 会缺省或下发为 -1，退回用头像地址造稳定合成 ID。
    uid = _pb_int(fields, 1)
    if uid in (0, UINT64_MAX):
        seed = _pb_str(fields, 3) or _pb_str(fields, 2)
        uid = _synthetic_uid(seed) if seed else 0
    if not uid:
        return None

    num = _pb_int(gift, 3) or 1
    price = _pb_int(gift, 5) or 0
    coin_type = (_pb_str(gift, 8) or "gold").lower()
    # 只有金瓜子（gold）是付费礼物，1000 金瓜子 = 1 元；银瓜子（silver）是免费礼物，不计流水。
    paid = coin_type != "silver"
    total = (price * num) / 1000.0 if paid else 0.0
    name = _pb_str(gift, 2) or "礼物"
    ts = _pb_int(gift, 10)
    if ts and ts < 10 ** 12:
        ts *= 1000
    return {
        "type": "gift",
        "uid": int(uid),
        "uname": _pb_str(fields, 2) or "",
        "content": f"{name} x{num}",
        "ts": ts or ts_fallback or _now_ms(),
        "extra": {
            "gift_name": name,
            "gift_id": _pb_int(gift, 1),
            "num": num,
            "coin_type": coin_type,
            "paid": paid,
            "value": total,
            "tid": _pb_str(gift, 9),
            "face": _pb_str(fields, 3),
        },
    }


def parse_gift(data: dict, ts_fallback: int = 0) -> Optional[dict]:
    uid = data.get("uid")
    if not uid:
        return None
    num = data.get("num") or 1
    price = data.get("price") or 0
    coin_type = (data.get("coin_type") or "gold").lower()
    # 只有金瓜子（gold）是付费礼物，1000 金瓜子 = 1 元；银瓜子（silver）是免费礼物，不计流水。
    paid = coin_type != "silver"
    total = (price * num) / 1000.0 if paid else 0.0
    return {
        "type": "gift",
        "uid": int(uid),
        "uname": data.get("uname") or "",
        "content": f"{data.get('giftName', '礼物')} x{num}",
        "ts": data.get("timestamp") or ts_fallback or _now_ms(),
        "extra": {
            "gift_name": data.get("giftName"),
            "num": num,
            "coin_type": coin_type,
            "paid": paid,
            "value": total,
            "tid": str(data.get("tid") or ""),
        },
    }


def parse_super_chat(data: dict, ts_fallback: int = 0) -> Optional[dict]:
    uid = data.get("uid")
    if not uid:
        return None
    user_info = data.get("user_info") or {}
    return {
        "type": "superchat",
        "uid": int(uid),
        "uname": user_info.get("uname") or data.get("uname") or "",
        "content": data.get("message") or "",
        "ts": data.get("ts") or data.get("start_time") or ts_fallback or _now_ms(),
        "extra": {
            "price": data.get("price") or 0,
            "value": float(data.get("price") or 0),
            "time": data.get("time"),
        },
    }


GUARD_NAMES = {1: "总督", 2: "提督", 3: "舰长"}


def parse_guard_buy(data: dict, ts_fallback: int = 0) -> Optional[dict]:
    uid = data.get("uid")
    if not uid:
        return None
    level = data.get("guard_level") or 0
    num = data.get("num") or 1
    return {
        "type": "guard",
        "uid": int(uid),
        "uname": data.get("username") or data.get("uname") or "",
        "content": f"开通{GUARD_NAMES.get(level, '舰队')} x{num}",
        "ts": data.get("start_time") or ts_fallback or _now_ms(),
        "extra": {
            "guard_level": level,
            "num": num,
            "value": float(data.get("price") or 0) / 1000.0,
        },
    }


def parse_like(data: dict, ts_fallback: int = 0) -> Optional[dict]:
    uid = data.get("uid")
    if not uid:
        return None
    return {
        "type": "like",
        "uid": int(uid),
        "uname": data.get("uname") or "",
        "content": "点赞了直播间",
        "ts": ts_fallback or _now_ms(),
        "extra": {},
    }


def normalize_command(payload: dict) -> Optional[dict]:
    """把一条 cmd 消息归一化成统一的 event dict（无法识别返回 None）。"""
    cmd = payload.get("cmd") or ""
    base = cmd.split(":", 1)[0]
    data = payload.get("data")
    ts_fallback = payload.get("ts") and int(payload["ts"] * 1000) or 0

    if base == "DANMU_MSG":
        return parse_danmaku(payload)
    if base == "INTERACT_WORD":
        return parse_interact_word(data or {}, ts_fallback)
    if base == "INTERACT_WORD_V2":
        parsed = parse_interact_word_v2((data or {}).get("pb"))
        return parse_interact_word(parsed or {}, ts_fallback) if parsed else None
    if base == "ENTRY_EFFECT":
        if not isinstance(data, dict):
            return None
        uid = data.get("uid")
        if not uid:
            return None
        uinfo = data.get("uinfo") or {}
        uname = (uinfo.get("base") or {}).get("name") or ""
        if not uname:
            matched = re.search(r"<%(.+?)%>", data.get("copy_writing") or "")
            uname = matched.group(1) if matched else ""
        return {
            "type": "enter",
            "uid": int(uid),
            "uname": uname,
            "content": "进入直播间",
            "ts": ts_fallback or _now_ms(),
            "extra": {
                "effect": "entry_effect",
                "guard_level": data.get("privilege_type") or 0,
                "face": (uinfo.get("base") or {}).get("face") or "",
            },
        }
    if base == "SEND_GIFT_V2":
        return parse_gift_v2((data or {}).get("pb"), ts_fallback)
    if base == "SEND_GIFT":
        return parse_gift(data or {}, ts_fallback)
    if base == "SUPER_CHAT_MESSAGE":
        return parse_super_chat(data or {}, ts_fallback)
    if base == "GUARD_BUY":
        return parse_guard_buy(data or {}, ts_fallback)
    if base == "LIKE_INFO_V3_CLICK":
        return parse_like(data or {}, ts_fallback)
    return None


# --------------------------------------------------------------------------
# 客户端
# --------------------------------------------------------------------------
class BiliLiveClient:
    """自动重连的弹幕客户端。事件通过 on_event 回调抛出。"""

    def __init__(
        self,
        room_id: int,
        on_event: Callable[[dict], Any],
        on_status: Optional[Callable[[str, dict], Any]] = None,
        cookie: str = "",
    ):
        self.room_id = int(room_id)
        self.real_room_id = 0
        self.on_event = on_event
        self.on_status = on_status or (lambda _msg, _meta=None: None)
        # 带上登录 Cookie 后，B 站才会下发弹幕发送者的真实昵称。
        # 未登录连接约 5 分钟后，弹幕昵称会被服务端打码成 *。
        self.cookie = self._normalize_cookie(cookie)
        self._uid = self._uid_from_cookie(self.cookie)
        self._use_cookie = True
        self._authed = False
        self._token = ""
        self._buvid = ""
        self._buvid4 = ""
        self._hosts: List[dict] = []
        self.popularity = 0
        self.connected = False

    @staticmethod
    def _normalize_cookie(raw: str) -> str:
        """容错：用户常常只复制了 SESSDATA 的值（形如 xxx%2C时间戳%2Cxxx），
        少了 `SESSDATA=` 前缀。这里自动补上，否则 B 站认不到登录态。"""
        text = (raw or "").strip().strip(";").strip()
        if not text:
            return ""
        if "=" not in text:
            return f"SESSDATA={text}"
        return text

    @staticmethod
    def _uid_from_cookie(cookie: str) -> int:
        """从 Cookie 里的 DedeUserID 取登录 uid，取不到就按未登录(0)处理。"""
        matched = re.search(r"(?:^|;\s*)DedeUserID=(\d+)", cookie or "")
        return int(matched.group(1)) if matched else 0

    def _cookie_header(self) -> str:
        parts = []
        if self.cookie and self._use_cookie:
            parts.append(self.cookie.strip().rstrip(";"))
        if self._buvid:
            parts.append(f"buvid3={self._buvid}")
        if self._buvid4:
            parts.append(f"buvid4={self._buvid4}")
        return "; ".join(p for p in parts if p)

    async def _status(self, message: str, **meta):
        result = self.on_status(message, meta)
        if asyncio.iscoroutine(result):
            await result

    async def run_forever(self):
        backoff = 3
        while True:
            try:
                await self._run_once()
                # 带了 Cookie 却始终拿不到鉴权回复，多半是 Cookie 失效。
                # 这时退回匿名连接，至少保证弹幕继续采集（昵称会打码）。
                if self.cookie and not self._authed:
                    await self._status(
                        "登录 Cookie 可能已失效，改用匿名连接（弹幕昵称会被打码）"
                    )
                    await self._run_once(use_cookie=False)
                backoff = 3
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.connected = False
                await self._status(f"连接断开：{exc}；{backoff}s 后重连")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _run_once(self, use_cookie: bool = True):
        self._authed = False
        self._use_cookie = use_cookie
        async with aiohttp.ClientSession(headers=BASE_HEADERS) as session:
            await self._prepare(session)
            host = random.choice(self._hosts) if self._hosts else {
                "host": "broadcastlv.chat.bilibili.com",
                "wss_port": 443,
            }
            url = f"wss://{host['host']}:{host.get('wss_port', 443)}/sub"
            await self._status(f"正在连接弹幕服务器 {host['host']} …")

            async with session.ws_connect(
                url,
                heartbeat=None,
                timeout=30,
                max_msg_size=0,
                headers={"Cookie": self._cookie_header()},
            ) as ws:
                await ws.send_bytes(
                    encode_packet(
                        OP_AUTH,
                        json.dumps(
                            {
                                "uid": self._uid if use_cookie else 0,
                                "roomid": self.real_room_id,
                                "protover": 3,
                                "buvid": self._buvid,
                                "platform": "web",
                                "type": 2,
                                "key": self._token,
                            }
                        ).encode("utf-8"),
                        proto_ver=1,
                    )
                )
                heartbeat = asyncio.create_task(self._heartbeat_loop(ws))
                try:
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            await self._handle_binary(msg.data)
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.CLOSING,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break
                finally:
                    heartbeat.cancel()
                    self.connected = False

    async def _prepare(self, session: aiohttp.ClientSession):
        buvid = await fetch_buvid(session)
        self._buvid = buvid.get("b_3", "")
        self._buvid4 = buvid.get("b_4", "")
        self.real_room_id = await fetch_real_room_id(session, self.room_id)
        try:
            info = await fetch_danmu_info(
                session,
                self.real_room_id,
                buvid,
                self.cookie if self._use_cookie else "",
            )
        except Exception as exc:
            await self._status(f"getDanmuInfo 不可用（{exc}），改用兼容接口 getConf")
            info = await fetch_danmu_conf(session, self.real_room_id)
        self._token = info.get("token") or ""
        hosts = info.get("host_list") or []
        # 优先 wss 443 端口
        hosts.sort(key=lambda h: (h.get("wss_port") != 443, h.get("host", "")))
        self._hosts = hosts

    async def _heartbeat_loop(self, ws: aiohttp.ClientWebSocketResponse):
        while True:
            try:
                await ws.send_bytes(
                    encode_packet(OP_HEARTBEAT, b"[object Object]", proto_ver=1)
                )
            except Exception:
                return
            await asyncio.sleep(30)

    async def _handle_binary(self, data: bytes):
        for proto_ver, operation, body in expand_packets(data):
            if operation == OP_AUTH_REPLY:
                self._authed = True
                self.connected = True
                await self._status(
                    f"鉴权成功，已进入直播间 {self.real_room_id}", connected=True
                )
            elif operation == OP_HEARTBEAT_REPLY:
                if len(body) >= 4:
                    self.popularity = struct.unpack(">I", body[:4])[0]
            elif operation == OP_MESSAGE:
                try:
                    payload = json.loads(body.decode("utf-8", "replace"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                event = normalize_command(payload)
                if event:
                    result = self.on_event(event)
                    if asyncio.iscoroutine(result):
                        await result
