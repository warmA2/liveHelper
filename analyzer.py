"""观众画像分析。

分两层：
  规则层  build_metrics() —— 从落库数据里算出客观行为指标（无需联网）。
  智能层  analyze()       —— 把指标 + 近期发言交给大模型，产出画像与应对建议。
大模型不可用时自动降级为规则层结论，保证功能始终可用。
"""

import json
import re
import time
from collections import Counter
from typing import Any, Dict, List, Optional

import aiohttp

from topics import TOPICS

SYSTEM_PROMPT = """你是资深直播间运营分析师。你会收到某位 B 站直播间观众的客观行为数据与近期发言。
请基于数据输出这个观众的画像，帮助主播快速"记住这个人"并知道怎么接话。

硬性要求：
1. 只依据给定数据（尤其是该观众自己发过的弹幕原文）推断，绝不编造数据里没有的事实。
2. 隐私类字段（常驻地点、感情/婚姻、孕育、子女、父母）——只有在该观众【本人明确说过】时才填写，
   否则一律留空字符串。严禁根据语气、昵称、粉丝牌、等级等弱信号去猜测这类敏感信息。
3. 具体偏好（游戏、音乐、动漫等）只写该观众真的提到过的具体名称，不要写泛泛的品类。
4. 面向主播使用，结论必须具体、可执行，不要空话套话。
5. sample_replies 必须是主播能直接照着念的中文口语，结合该观众的发言内容，不要通用模板。
6. 只输出 JSON，不要任何解释文字或 markdown 代码块。

JSON 结构：
{
  "nickname_hint": "方便主播记忆的称呼，如'爱聊打野的老哥'",
  "tags": ["3到6个短标签"],
  "persona": "一到两句话的人设概括",
  "interests": ["兴趣点，1到5个"],
  "activity_level": "高/中/低",
  "value_level": "高/中/低",
  "relationship": "新观众/路人/老粉/铁粉/舰长粉丝 之一",
  "mood_now": "当前情绪，如 热情/潜水/试探/抱怨/玩梗",
  "memory_hook": "一句话，主播记住这个人的关键点",
  "location": "常驻地点/城市，仅本人明确提到时填写，否则空字符串",
  "active_hours": "活跃时段归纳，如'深夜党 22点-2点'；无数据写'暂无明显规律'",
  "life_stage": {
    "marriage": "感情/婚姻状态，仅本人明确提到时填写（如 单身/有对象/已婚），否则空字符串",
    "pregnancy": "孕育相关，仅本人明确提到时填写，否则空字符串",
    "children": "子女情况，仅本人明确提到时填写，否则空字符串",
    "parents": "父母相关，仅本人明确提到时填写，否则空字符串"
  },
  "favorites": {
    "games": ["本人提到过的具体游戏名，没有则空数组"],
    "music": ["本人提到过的具体歌名/歌手/曲风，没有则空数组"],
    "anime": ["本人提到过的具体动漫/番剧/角色，没有则空数组"],
    "food": ["本人提到过的具体食物/口味，没有则空数组"],
    "hobbies": ["其它具体爱好，没有则空数组"]
  },
  "response_strategy": ["2到4条具体的应对方法"],
  "sample_replies": ["2到3条可直接照读的话术"],
  "risk_note": "需要注意的雷点，没有则空字符串"
}"""

INTEREST_KEYWORDS = {
    "游戏": ["游戏", "开黑", "上分", "排位", "打野", "中单", "上单", "adc", "辅助", "王者",
             "英雄联盟", "lol", "原神", "崩铁", "永劫", "csgo", "瓦罗兰特", "吃鸡", "蛋仔",
             "星铁", "绝区零", "steam", "主机", "手柄", "mod"],
    "音乐": ["音乐", "歌", "唱歌", "唱", "翻唱", "吉他", "钢琴", "伴奏", "点歌", "好听", "音色"],
    "舞蹈": ["跳舞", "舞蹈", "宅舞", "舞", "编舞"],
    "动画": ["动漫", "动画", "番剧", "新番", "追番", "漫画", "二次元", "手办", "谷子", "cos"],
    "美食": ["吃", "美食", "外卖", "夜宵", "螺蛳粉", "奶茶", "火锅", "烧烤", "做饭", "饿了"],
    "科技": ["电脑", "显卡", "配置", "装机", "手机", "键盘", "外设", "代码", "编程", "ai",
             "人工智能", "显卡", "cpu", "内存"],
    "情感": ["失恋", "单身", "对象", "女朋友", "男朋友", "分手", "emo", "孤独", "结婚", "相亲"],
    "颜值": ["好看", "漂亮", "可爱", "帅", "美女", "颜值", "妆", "穿搭"],
    "户外": ["户外", "旅行", "旅游", "爬山", "骑行", "露营", "钓鱼", "开车"],
    "影视": ["电影", "电视剧", "追剧", "综艺", "up主", "视频", "剪辑", "解说"],
    "体育": ["足球", "篮球", "nba", "cba", "世界杯", "比赛", "球赛", "健身", "跑步"],
    "鬼畜": ["鬼畜", "梗", "抽象", "名场面", "整活", "恶搞", "名梗"],
}
POSITIVE_WORDS = ["哈哈", "笑死", "好耶", "牛", "厉害", "喜欢", "爱了", "支持", "加油", "棒",
                  "可爱", "好看", "强", "6", "666", "赞", "绝了", "太强"]
NEGATIVE_WORDS = ["无聊", "拉胯", "菜", "失望", "退钱", "不行", "退订", "恶心", "烂", "烦",
                  "卡", "掉线", "难受", "emo", "麻了"]

GUARD_NAMES = {0: "无", 1: "总督", 2: "提督", 3: "舰长"}


def _fmt_time(ms: int) -> str:
    if not ms:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ms / 1000))


def _humanize_delta(ms: int) -> str:
    if ms <= 0:
        return "刚刚"
    sec = ms / 1000
    if sec < 60:
        return f"{int(sec)} 秒"
    if sec < 3600:
        return f"{int(sec / 60)} 分钟"
    if sec < 86400:
        return f"{sec / 3600:.1f} 小时"
    return f"{sec / 86400:.1f} 天"


def _extract_keywords(texts: List[str], top: int = 12) -> List[str]:
    """轻量关键词：中文 2-gram + 英文单词，过滤高频噪声。"""
    counter: Counter = Counter()
    for text in texts:
        clean = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
        for token in clean.split():
            if re.fullmatch(r"[a-zA-Z0-9]{2,}", token):
                counter[token.lower()] += 1
                continue
            chinese = re.sub(r"[^\u4e00-\u9fff]", "", token)
            for size in (2, 3):
                for i in range(len(chinese) - size + 1):
                    counter[chinese[i : i + size]] += 1
    stop = {"哈哈", "呵呵", "这个", "那个", "什么", "怎么", "可以", "就是", "不是", "没有"}
    return [w for w, c in counter.most_common(60) if c >= 2 and w not in stop][:top]


def _detect_interests(texts: List[str]) -> List[str]:
    blob = " ".join(texts).lower()
    hits = []
    for name, words in INTEREST_KEYWORDS.items():
        if sum(blob.count(w.lower()) for w in words) >= 2:
            hits.append(name)
    return hits


def _sentiment(texts: List[str]) -> str:
    blob = " ".join(texts)
    pos = sum(blob.count(w) for w in POSITIVE_WORDS)
    neg = sum(blob.count(w) for w in NEGATIVE_WORDS)
    if pos > neg * 2 and pos >= 2:
        return "积极友好"
    if neg > pos * 2 and neg >= 2:
        return "偏负面/有情绪"
    return "中性"


# 规则层能识别的「具体名称」词表（大模型不可用时兜底）
NAMED_ITEMS = {
    "games": ["王者荣耀", "英雄联盟", "lol", "原神", "崩坏", "星穹铁道", "崩铁", "永劫无间",
              "csgo", "cs2", "瓦罗兰特", "valorant", "吃鸡", "pubg", "和平精英", "蛋仔派对",
              "绝区零", "我的世界", "第五人格", "金铲铲", "dota", "塞尔达", "黑神话", "steam"],
    "music": ["周杰伦", "林俊杰", "陈奕迅", "邓紫棋", "薛之谦", "毛不易", "五月天", "华晨宇",
              "黄家驹", "beyond", "说唱", "摇滚", "民谣", "古风", "电音", "kpop", "爵士"],
    "anime": ["火影", "海贼王", "名侦探柯南", "柯南", "咒术回战", "鬼灭", "进击的巨人",
              "间谍过家家", "排球少年", "孤独摇滚", "宫崎骏", "你的名字", "天气之子", "高达",
              "初音", "东方", "死神", "灌篮高手", "龙珠"],
    "food": ["螺蛳粉", "奶茶", "火锅", "烧烤", "炸鸡", "麻辣烫", "咖啡", "汉堡", "蛋糕", "泡面"],
}


def _detect_named(texts: List[str]) -> Dict[str, List[str]]:
    """从发言里捞出观众真正点名提到过的具体游戏 / 歌手 / 番剧等。"""
    blob = " ".join(texts).lower()
    return {
        group: [name for name in names if name.lower() in blob]
        for group, names in NAMED_ITEMS.items()
    }


def _active_hours(metrics: Dict[str, Any]) -> str:
    """把发言时段分布归纳成一句人话，如「深夜党（22点-2点）」。"""
    hist = metrics.get("发言时段分布") or {}
    if not hist:
        return "暂无明显规律"
    pairs = [(int(str(k).replace("点", "")), v) for k, v in hist.items()]
    top = [h for h, _ in sorted(pairs, key=lambda x: -x[1])[:3]]
    lo, hi = min(top), max(top)
    if lo >= 22 or hi <= 5:
        label = "深夜党"
    elif lo >= 18:
        label = "晚间党"
    elif hi <= 11:
        label = "上午党"
    elif lo >= 12 and hi <= 14:
        label = "午间党"
    else:
        label = "白天党"
    return f"{label}（{lo}点-{hi}点）"


# 粉丝牌等级 -> 累计消费折算（粗估）。
# 依据 2025-09-08 改版后的 B 站粉丝牌规则：勋章统一为 1~120 级，
# 1 电池 = 1 亲密度、1 元 = 10 电池，即 0.1 元 = 1 亲密度。
# 官方未公开完整的「等级 ↔ 累计亲密度」对照表，这里按等级段给出粗略金额区间。
MEDAL_SPEND_TIERS = (
    (1, 5, 0, 5),
    (6, 10, 5, 30),
    (11, 15, 30, 150),
    (16, 20, 150, 800),
    (21, 25, 800, 5000),
    (26, 30, 5000, 30000),
    (31, 40, 30000, 300000),
    (41, 50, 300000, 3000000),
    (51, 70, 3000000, 30000000),
    (71, 90, 30000000, 300000000),
    (91, 120, 300000000, None),
)


def _fmt_cny(value: float) -> str:
    """把金额转成「X万 / X亿」的短写法。"""
    if value >= 10 ** 8:
        return f"{value / 10 ** 8:g}亿"
    if value >= 10 ** 4:
        return f"{value / 10 ** 4:g}万"
    return f"{value:g}"


def _medal_spend_estimate(level: int) -> str:
    """按粉丝牌等级粗略折算「若靠打赏达到该等级」的累计消费区间。"""
    if not level or level <= 0:
        return ""
    for lo, hi, low, high in MEDAL_SPEND_TIERS:
        if lo <= level <= hi:
            if high is None:
                return f"约 {_fmt_cny(low)} 元以上"
            return f"约 {_fmt_cny(low)}~{_fmt_cny(high)} 元"
    # 超过 120 级（理论上不会出现）：直接按最高档处理
    return f"约 {_fmt_cny(MEDAL_SPEND_TIERS[-1][2])} 元以上"


class Analyzer:
    def __init__(self, store, cfg: Dict[str, Any]):
        self.store = store
        self.cfg = cfg
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = None

    @property
    def enabled(self) -> bool:
        llm = self.cfg.get("llm") or {}
        return bool(llm.get("enabled") and llm.get("api_key"))

    def _get_semaphore(self):
        if self._semaphore is None:
            self._semaphore = __import__("asyncio").Semaphore(2)
        return self._semaphore

    async def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # 规则层
    # ------------------------------------------------------------------
    def build_metrics(self, viewer: Dict[str, Any], messages: List[dict]) -> Dict[str, Any]:
        texts = [m["content"] for m in messages if m.get("content")]
        msg_count = viewer.get("msg_count") or 0
        first_seen = viewer.get("first_seen") or 0
        last_seen = viewer.get("last_seen") or 0
        span = max(last_seen - first_seen, 0)

        if msg_count >= 20 or (msg_count >= 8 and span > 6 * 3600 * 1000):
            activity = "高"
        elif msg_count >= 5:
            activity = "中"
        else:
            activity = "低"

        value = float(viewer.get("gift_value") or 0)
        if value >= 100 or viewer.get("guard_level"):
            value_level = "高"
        elif value >= 10:
            value_level = "中"
        else:
            value_level = "低"

        medal_level = viewer.get("medal_level") or 0

        hour_hist = Counter()
        for m in messages:
            hour_hist[time.localtime((m.get("ts") or 0) / 1000).tm_hour] += 1

        avg_len = round(sum(len(t) for t in texts) / len(texts), 1) if texts else 0

        return {
            "uid": viewer.get("uid"),
            "昵称": viewer.get("uname"),
            "首次出现": _fmt_time(first_seen),
            "最近出现": _fmt_time(last_seen),
            "关注时长": _humanize_delta(span),
            "累计弹幕数": msg_count,
            "本场弹幕数": len(messages),
            "进场次数": viewer.get("enter_count") or 0,
            "关注过主播": bool(viewer.get("follow_count")),
            "点赞次数": viewer.get("like_count") or 0,
            "付费次数": viewer.get("spend_count") or 0,
            "累计消费(元)": round(value, 2),
            "舰长等级": GUARD_NAMES.get(viewer.get("guard_level") or 0, "无"),
            "粉丝牌等级": medal_level,
            "粉丝牌名称": viewer.get("medal_name") or "",
            "粉丝牌折算消费(估)": _medal_spend_estimate(medal_level),
            "发言平均字数": avg_len,
            "发言时段分布": {f"{h}点": c for h, c in sorted(hour_hist.items())},
            "活跃度(规则)": activity,
            "消费等级(规则)": value_level,
            "情绪倾向(规则)": _sentiment(texts),
            "兴趣方向(规则)": _detect_interests(texts),
            "提及内容(规则)": _detect_named(texts),
            "提及元素(规则)": TOPICS.match_counts(texts),
            "高频词(规则)": _extract_keywords(texts),
            "主播备注": viewer.get("note") or "",
        }

    def rule_profile(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        interests = metrics.get("兴趣方向(规则)") or []
        tags = [metrics.get("活跃度(规则)") + "活跃", metrics.get("消费等级(规则)") + "消费"]
        if metrics.get("舰长等级") and metrics["舰长等级"] != "无":
            tags.append(metrics["舰长等级"])
        if metrics.get("粉丝牌等级"):
            tags.append(f"粉丝牌Lv{metrics['粉丝牌等级']}")
        tags.extend(interests[:2])
        named = metrics.get("提及内容(规则)") or {}
        return {
            "nickname_hint": (metrics.get("高频词(规则)") or ["常驻观众"])[0] + "观众",
            "tags": tags[:6],
            "persona": f"{metrics.get('活跃度(规则)')}活跃度观众，"
                       f"{metrics.get('关注时长')}内发言 {metrics.get('累计弹幕数')} 条，"
                       f"情绪{metrics.get('情绪倾向(规则)')}。",
            "interests": interests,
            "activity_level": metrics.get("活跃度(规则)"),
            "value_level": metrics.get("消费等级(规则)"),
            "relationship": "舰长粉丝" if metrics.get("舰长等级") not in (None, "无")
                            else ("老粉" if metrics.get("累计弹幕数", 0) >= 20 else "新观众"),
            "mood_now": metrics.get("情绪倾向(规则)"),
            "memory_hook": f"兴趣：{'、'.join(interests) if interests else '暂无明显特征'}",
            # 以下隐私字段规则层无法判断，一律留空，等大模型在观众本人明说时再补
            "location": "",
            "active_hours": _active_hours(metrics),
            "life_stage": {"marriage": "", "pregnancy": "", "children": "", "parents": ""},
            "favorites": {
                "games": named.get("games") or [],
                "music": named.get("music") or [],
                "anime": named.get("anime") or [],
                "food": named.get("food") or [],
                "hobbies": interests,
            },
            "response_strategy": [
                "念一遍对方昵称再回应，让对方感到被记住",
                "结合其高频词" + ("、" + "、".join((metrics.get('高频词(规则)') or [])[:3])
                                if metrics.get("高频词(规则)") else "") + "展开话题",
                "若其发言带情绪，先共情再解释，不要硬顶",
            ],
            "sample_replies": [
                f"欢迎{metrics.get('昵称')}，好久不见～",
                "这个你熟，你怎么看？",
            ],
            "risk_note": "" if metrics.get("情绪倾向(规则)") != "偏负面/有情绪"
                         else "近期发言偏负面，避免被带节奏，先安抚情绪。",
            "_source": "rule",
        }

    # ------------------------------------------------------------------
    # 智能层
    # ------------------------------------------------------------------
    async def _call_llm(self, metrics: Dict[str, Any], messages: List[dict]) -> Dict[str, Any]:
        llm = self.cfg["llm"]
        url = llm["base_url"].rstrip("/") + "/chat/completions"
        recent = [
            {"时间": _fmt_time(m.get("ts")), "发言": m.get("content")}
            for m in messages[: self.cfg["analyze"]["recent_msg_limit"]]
        ]
        user_content = (
            "【行为指标】\n"
            + json.dumps(metrics, ensure_ascii=False, indent=2)
            + "\n\n【近期发言样本(新→旧)】\n"
            + json.dumps(recent, ensure_ascii=False, indent=2)
        )
        body = {
            "model": llm["model"],
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": llm.get("temperature", 0.4),
            "max_tokens": 3000,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {llm['api_key']}",
            "Content-Type": "application/json",
        }
        session = await self._session_get()
        timeout = aiohttp.ClientTimeout(total=llm.get("timeout", 60))

        async def _post(payload):
            async with session.post(url, json=payload, headers=headers, timeout=timeout) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}: {text[:300]}")
                return json.loads(text)

        try:
            data = await _post(body)
        except RuntimeError as exc:
            # 部分服务不支持 response_format，去掉后重试一次
            if "response_format" in str(exc) or "HTTP 400" in str(exc):
                body.pop("response_format", None)
                data = await _post(body)
            else:
                raise

        content = data["choices"][0]["message"]["content"]
        profile = self._parse_json(content)
        profile["_source"] = "llm"
        profile["_model_used"] = llm["model"]
        return profile

    @staticmethod
    def _parse_json(content: str) -> Dict[str, Any]:
        text = content.strip()
        fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
        if fence:
            text = fence.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
            raise

    async def analyze(self, uid: int, force_llm: bool = False) -> Dict[str, Any]:
        viewer = self.store.get_viewer(uid)
        if not viewer:
            raise ValueError(f"观众 {uid} 不存在")
        messages = self.store.viewer_messages(uid, limit=60)
        metrics = self.build_metrics(viewer, messages)

        if not self.enabled:
            profile = self.rule_profile(metrics)
            profile["_note"] = "未配置大模型 API Key，当前为本地规则画像"
            self.store.save_profile(uid, profile, model="rule")
            return profile

        self.store.set_profile_status(uid, "running")
        try:
            async with self._get_semaphore():
                profile = await self._call_llm(metrics, messages)
            self.store.save_profile(uid, profile, model=profile.get("_model_used", ""))
            return profile
        except Exception as exc:
            self.store.set_profile_status(uid, "error", str(exc)[:300])
            raise
