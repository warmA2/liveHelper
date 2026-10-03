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
6. 除弹幕外，还会收到【醒目留言原文】【消费与上舰明细】【光顾与作息】等补充数据，
   请综合它们判断该观众的付费诉求、消费习惯、跨场次忠诚度与作息规律；这些数据同样不得编造或过度解读。
7. 只输出 JSON，不要任何解释文字或 markdown 代码块。

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

SESSION_PROMPT = """你是资深直播间运营分析师。你会收到某场 B 站直播的完整聚合数据（观众、弹幕、进场、礼物、上舰、人气、操作记录与场次时段分布）。
请输出这场直播的复盘分析，帮助主播看懂"这一场播得怎么样、哪里出了问题、下播后该调整什么"。

硬性要求：
1. 只依据给定数据推断，绝不编造数据里没有的事实；没有的数据不要硬编。
2. 结合「操作记录」对比不同环节（唱歌 / PK / 杂谈 …）对人气与互动的影响，指出哪些环节有效、哪些拖了后腿。
3. 结论要具体、可执行，给出主播下播后能立刻照做的动作，不要空话套话。
4. 用中文输出纯文本（不要 markdown 代码块、不要 JSON），可以用简短小标题与换行分条，控制在 500 字以内。

建议覆盖：本场概况、亮点、问题、与观众结构/消费的关联、下一步改进建议。"""

CAREER_PROMPT = """你是资深直播间运营分析师。你会收到某位主播「生涯」口径的累计数据（跨全部场次：场次时长、观众、弹幕、上舰、流水、消费趋势、忠实观众、操作类型统计、全量时段分布）。
请输出一份阶段性的生涯经营分析，帮助主播判断长期走势与投入方向。

硬性要求：
1. 只依据给定数据推断，绝不编造数据里没有的事实；没有的数据不要硬编。
2. 关注长期趋势：流水/观众随时间的变化、核心观众是否稳定、上下舰结构、开播时段规律。
3. 结论要具体、可执行，给出下一步可持续经营的建议，不要空话套话。
4. 用中文输出纯文本（不要 markdown 代码块、不要 JSON），可以用简短小标题与换行分条，控制在 600 字以内。

建议覆盖：整体走势、核心资产（忠实观众/大额支持者）、内容偏好、风险点、下阶段建议。"""

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
    def build_metrics(
        self, viewer: Dict[str, Any], messages: List[dict],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = context or {}
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

        # 发言时段：优先用全量历史直方图。analyze 只取最近 60 条弹幕，命中时段会明显失真。
        all_hours = context.get("all_msg_hours") or {}
        hour_hist = Counter()
        if all_hours:
            for hour, count in all_hours.items():
                hour_hist[int(hour)] += int(count)
        else:
            for m in messages:
                hour_hist[time.localtime((m.get("ts") or 0) / 1000).tm_hour] += 1

        avg_len = round(sum(len(t) for t in texts) / len(texts), 1) if texts else 0

        # 潜水指数：发言数 / 进场次数，越低越「只看不说」
        enter_count = viewer.get("enter_count") or 0
        if enter_count > 0:
            ratio = round(msg_count / enter_count, 2)
            dive_label = "低" if ratio >= 1 else ("中" if ratio >= 0.3 else "高")
            dive_index = f"{ratio}（发言/进场，{dive_label}潜水）"
        else:
            dive_index = "无进场记录"

        now_ms = int(time.time() * 1000)

        # 消费明细摘要（规则层）：只统计付费礼物金额，银瓜子等免费礼物不计流水
        gift_summary = [
            f"{g['name']}×{g['count']}" + (f"（¥{g['amount']:g}）" if g.get("amount") else "")
            for g in (context.get("gift_summary") or [])[:5]
        ]
        guard_summary = [
            f"{GUARD_NAMES.get(g['level'], '舰队')}×{g['count']}"
            + (f"（¥{g['amount']:g}）" if g.get("amount") else "")
            for g in (context.get("guard_summary") or [])
        ]
        sc_lines = [
            f"¥{sc['value']:g} {sc['content']}".strip()
            for sc in (context.get("superchats") or [])[:10]
        ]

        return {
            "uid": viewer.get("uid"),
            "昵称": viewer.get("uname"),
            "首次出现": _fmt_time(first_seen),
            "最近出现": _fmt_time(last_seen),
            "最近出现距今": _humanize_delta(now_ms - last_seen) if last_seen else "-",
            "关注时长": _humanize_delta(span),
            "光顾场次数": int(context.get("visit_sessions") or 0),
            "累计弹幕数": msg_count,
            "本场弹幕数": len(messages),
            "进场次数": viewer.get("enter_count") or 0,
            "潜水指数": dive_index,
            # B 站只在「本次开播期间发生关注」时才推 follow 事件，早就关注的老观众收不到，
            # 所以单看 follow_count 会把绝大多数已关注的人误判成未关注。
            # 粉丝牌 / 大航海都必须先关注主播才有，用它们补齐这个判断；
            # 两者都没有时只能说「未知」，不能断言没关注。
            "关注过主播": (
                "是"
                if (viewer.get("follow_count") or medal_level or viewer.get("guard_level"))
                else "未知"
            ),
            "点赞次数": viewer.get("like_count") or 0,
            "付费次数": viewer.get("spend_count") or 0,
            "累计消费(元)": round(value, 2),
            "舰长等级": GUARD_NAMES.get(viewer.get("guard_level") or 0, "无"),
            "粉丝牌等级": medal_level,
            "粉丝牌名称": viewer.get("medal_name") or "",
            "粉丝牌折算消费(估)": _medal_spend_estimate(medal_level),
            "身份标记": viewer.get("role") or "",
            "礼物概览(规则)": gift_summary,
            "上舰记录(规则)": guard_summary,
            "醒目留言(规则)": sc_lines,
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
        if metrics.get("身份标记"):
            tags.append(metrics["身份标记"])
        tags.extend(interests[:2])
        named = metrics.get("提及内容(规则)") or {}
        visits = metrics.get("光顾场次数") or 0
        return {
            "nickname_hint": (metrics.get("高频词(规则)") or ["常驻观众"])[0] + "观众",
            "tags": tags[:6],
            "persona": f"{metrics.get('活跃度(规则)')}活跃度观众，"
                       f"光顾过 {visits} 场直播，"
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
    async def _call_llm(
        self, metrics: Dict[str, Any], messages: List[dict],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = context or {}
        llm = self.cfg["llm"]
        url = llm["base_url"].rstrip("/") + "/chat/completions"
        recent = [
            {"时间": _fmt_time(m.get("ts")), "发言": m.get("content")}
            for m in messages[: self.cfg["analyze"]["recent_msg_limit"]]
        ]
        sections = [
            "【行为指标】\n" + json.dumps(metrics, ensure_ascii=False, indent=2),
            "【近期发言样本(新→旧)】\n" + json.dumps(recent, ensure_ascii=False, indent=2),
        ]
        # 醒目留言原文：付费诉求与情绪的直接证据
        superchats = context.get("superchats") or []
        if superchats:
            sections.append(
                "【醒目留言原文(新→旧)】\n"
                + json.dumps(
                    [
                        {"时间": _fmt_time(s["ts"]), "金额(元)": s["value"], "内容": s["content"]}
                        for s in superchats
                    ],
                    ensure_ascii=False, indent=2,
                )
            )
        # 礼物 / 上舰明细：判断消费习惯与支持的持续性
        gifts = context.get("gifts") or []
        if gifts:
            detail = []
            for g in gifts:
                if g["type"] == "guard":
                    label = f"上舰 {GUARD_NAMES.get(g['guard_level'], '舰队')}"
                else:
                    label = f"礼物 {g.get('name') or g.get('content')} x{g.get('num') or 1}"
                detail.append({
                    "时间": _fmt_time(g["ts"]),
                    "行为": label,
                    "金额(元)": g["value"],
                    "付费": g["paid"],
                })
            sections.append(
                "【消费与上舰明细(新→旧)】\n"
                + json.dumps(detail, ensure_ascii=False, indent=2)
            )
        # 光顾与作息：跨场次忠诚度与全量发言时段
        sections.append(
            "【光顾与作息】\n"
            + json.dumps(
                {
                    "光顾场次数": context.get("visit_sessions") or 0,
                    "首次出现": _fmt_time(context.get("first_visit_ts")),
                    "最近出现": _fmt_time(context.get("last_visit_ts")),
                    "全量发言时段分布": context.get("all_msg_hours") or {},
                },
                ensure_ascii=False, indent=2,
            )
        )
        user_content = "\n\n".join(sections)
        content = await self._chat(
            SYSTEM_PROMPT, user_content, max_tokens=4000, json_mode=True
        )
        profile = self._parse_json(content)
        profile["_source"] = "llm"
        profile["_model_used"] = llm["model"]
        return profile

    async def _chat(
        self, system_prompt: str, user_content: str,
        max_tokens: int = 4000, json_mode: bool = True,
    ) -> str:
        """通用大模型对话，返回纯文本内容；部分服务不支持 response_format 时自动降级。"""
        llm = self.cfg["llm"]
        url = llm["base_url"].rstrip("/") + "/chat/completions"
        body: Dict[str, Any] = {
            "model": llm["model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": llm.get("temperature", 0.4),
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
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
            if json_mode and ("response_format" in str(exc) or "HTTP 400" in str(exc)):
                body.pop("response_format", None)
                data = await _post(body)
            else:
                raise
        return data["choices"][0]["message"]["content"]

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
        context = self.store.viewer_context(uid)
        metrics = self.build_metrics(viewer, messages, context)

        if not self.enabled:
            profile = self.rule_profile(metrics)
            profile["_note"] = "未配置大模型 API Key，当前为本地规则画像"
            self.store.save_profile(uid, profile, model="rule")
            return profile

        self.store.set_profile_status(uid, "running")
        try:
            async with self._get_semaphore():
                profile = await self._call_llm(metrics, messages, context)
            self.store.save_profile(uid, profile, model=profile.get("_model_used", ""))
            return profile
        except Exception as exc:
            self.store.set_profile_status(uid, "error", str(exc)[:300])
            raise

    # ------------------------------------------------------------------
    # 本场直播 / 生涯 的 AI 分析
    # ------------------------------------------------------------------
    @staticmethod
    def _session_rule_text(d: Dict[str, Any]) -> str:
        lines = ["【本场直播小结（未配置大模型，当前为本地规则）】"]
        lines.append(
            f"时长 {_humanize_delta(d['duration_ms'])}，观众 {d['people']} 人"
            f"（新增 {d['new_viewers']}），弹幕 {d['danmaku']} 条，进场 {d['enter']} 次。"
        )
        lines.append(
            f"礼物 {d['gift']} 次、上舰 {d['guard']} 次、醒目留言 {d['superchat']} 条，"
            f"本场流水 ¥{d['income']:g}。"
        )
        pop = d.get("popularity") or {}
        if pop.get("max") is not None:
            lines.append(f"人气峰值 {pop['max']}，均值 {pop['avg']}。")
        top = d.get("top_speakers") or []
        if top:
            lines.append(
                "发言最多：" + "、".join(
                    f"{t['uname'] or t['uid']}({t['count']})" for t in top[:5]
                )
            )
        spenders = d.get("top_spenders") or []
        if spenders:
            lines.append(
                "消费最多：" + "、".join(
                    f"{t['uname'] or t['uid']}(¥{t['amount']:g})" for t in spenders[:5]
                )
            )
        hours = d.get("hour_hist") or {}
        if hours:
            peak = max(hours.items(), key=lambda kv: kv[1])
            lines.append(f"弹幕最活跃时段：{peak[0]}（{peak[1]} 条）。")
        summary = d.get("action_summary") or []
        if summary:
            lines.append("各环节表现（每分钟）：")
            for g in summary[:8]:
                lines.append(
                    f"· {g['label']}×{g['count']}：弹幕 {g['danmaku_per_min']}、"
                    f"进场 {g['enter_per_min']}、礼物 {g['gift_per_min']}、流水 {g['income_per_min']}"
                )
        else:
            lines.append("本场暂无操作记录，无法对比各环节效果（可在时间轴记录唱歌/PK/杂谈等）。")
        lines.append("提示：在「设置」中配置大模型 API Key 后可获得更深入的复盘与改进建议。")
        return "\n".join(lines)

    @staticmethod
    def _career_rule_text(d: Dict[str, Any]) -> str:
        lines = ["【生涯小结（未配置大模型，当前为本地规则）】"]
        lines.append(
            f"累计 {d['sessions']} 场 / {d['days']} 天，累计开播 "
            f"{_humanize_delta(d['duration_ms'])}，首次记录 {_fmt_time(d['first_ts'])}。"
        )
        lines.append(
            f"观众库 {d['total_viewers']} 人，互动 {d['active_viewers']} 人，"
            f"累计弹幕 {d['danmaku']} 条，上舰 {d['guards']} 次。"
        )
        lines.append(f"累计流水 ¥{d['income']:g}，付费人数 {d['payers']} 人。")
        spenders = d.get("top_spenders") or []
        if spenders:
            lines.append(
                "核心支持者：" + "、".join(
                    f"{t['uname'] or t['uid']}(¥{t['amount']:g})" for t in spenders[:5]
                )
            )
        speakers = d.get("top_speakers") or []
        if speakers:
            lines.append(
                "活跃观众：" + "、".join(
                    f"{t['uname'] or t['uid']}({t['count']})" for t in speakers[:5]
                )
            )
        daily = d.get("daily_income") or []
        if len(daily) >= 2:
            half = max(1, len(daily) // 2)
            early = sum(x["amount"] for x in daily[:half])
            late = sum(x["amount"] for x in daily[half:])
            trend = "上升" if late > early else ("下降" if late < early else "持平")
            lines.append(f"近期流水走势：{trend}（前半段 ¥{early:g} → 后半段 ¥{late:g}）。")
        hours = d.get("hour_hist") or {}
        if hours:
            peak = max(hours.items(), key=lambda kv: kv[1])
            lines.append(f"最活跃开播时段：{peak[0]}（累计弹幕 {peak[1]} 条）。")
        kinds = d.get("action_kinds") or []
        if kinds:
            lines.append(
                "操作类型统计：" + "、".join(
                    f"{k['kind']}×{k['count']}" for k in kinds[:8]
                )
            )
        lines.append("提示：在「设置」中配置大模型 API Key 后可获得更深入的生涯经营分析。")
        return "\n".join(lines)

    async def analyze_session(self) -> Dict[str, Any]:
        insights = self.store.session_insights()
        if not insights:
            raise ValueError("当前没有进行中的直播场次")
        key = f"session:{insights['session_id']}"
        if not self.enabled:
            content, model = self._session_rule_text(insights), "rule"
        else:
            async with self._get_semaphore():
                content = await self._chat(
                    SESSION_PROMPT,
                    "【本场直播数据】\n" + json.dumps(insights, ensure_ascii=False, indent=2),
                    # 该模型会先输出 reasoning_content，预留足够 token 免得正文被挤空
                    max_tokens=4000, json_mode=False,
                )
            content, model = content.strip(), self.cfg["llm"]["model"]
            # 大模型偶发返回空内容，退回规则文本，避免存下空白分析
            if not content:
                content, model = self._session_rule_text(insights), "rule"
        self.store.save_analysis(key, content, model=model)
        return {"kind": "session", "key": key, "content": content, "model": model}

    async def analyze_career(self) -> Dict[str, Any]:
        insights = self.store.career_insights()
        if not self.enabled:
            content, model = self._career_rule_text(insights), "rule"
        else:
            async with self._get_semaphore():
                content = await self._chat(
                    CAREER_PROMPT,
                    "【生涯累计数据】\n" + json.dumps(insights, ensure_ascii=False, indent=2),
                    max_tokens=4000, json_mode=False,
                )
            content, model = content.strip(), self.cfg["llm"]["model"]
            # 大模型偶发返回空内容，退回规则文本，避免存下空白分析
            if not content:
                content, model = self._career_rule_text(insights), "rule"
        self.store.save_analysis("career", content, model=model)
        return {"kind": "career", "key": "career", "content": content, "model": model}
