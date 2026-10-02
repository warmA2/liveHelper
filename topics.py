"""热门元素库：游戏 / 梗 / 番剧 / 音乐 / 圈内术语词条。

词库落在 data/topics.json：
  - 首次运行会把内置种子写入该文件；
  - 之后以文件内容为准，你可以直接编辑增删词条，保存即生效（无需重启、无需改代码）。
每条词条：name 主名称、category 分类、desc 一句话说明（悬浮提示用）、aliases 触发别名。
"""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from config import BASE_DIR
from topics_data import ALL_TOPICS

TOPICS_PATH = BASE_DIR / "data" / "topics.json"

CATEGORIES = [
    {"key": "game", "label": "游戏", "color": "#5b9dff"},
    {"key": "game_char", "label": "游戏角色", "color": "#7fb4ff"},
    {"key": "game_term", "label": "游戏术语", "color": "#4a7dd1"},
    {"key": "meme", "label": "梗", "color": "#f2c14e"},
    {"key": "jargon", "label": "直播间术语", "color": "#fb7299"},
    {"key": "anime", "label": "番剧", "color": "#b28dff"},
    {"key": "anime_char", "label": "番剧角色", "color": "#c9adff"},
    {"key": "anime_term", "label": "番剧术语", "color": "#9670e0"},
    {"key": "tv", "label": "电视剧", "color": "#ff9f68"},
    {"key": "movie", "label": "电影", "color": "#ffb37a"},
    {"key": "music", "label": "音乐", "color": "#3ecf8e"},
    {"key": "travel", "label": "地名旅游", "color": "#66d9e8"},
    {"key": "hobby", "label": "兴趣爱好", "color": "#a0e57c"},
]

DEFAULT_TOPICS: List[Dict[str, Any]] = [
    # ---------------------------------------------------------- 游戏
    {"name": "原神", "category": "game", "desc": "米哈游开放世界冒险游戏，以元素反应和七国地图为核心", "aliases": ["原神", "genshin"]},
    {"name": "崩坏：星穹铁道", "category": "game", "desc": "米哈游回合制 RPG，简称崩铁 / 星铁", "aliases": ["星穹铁道", "崩铁", "星铁"]},
    {"name": "绝区零", "category": "game", "desc": "米哈游都市动作游戏，主打高速连招战斗", "aliases": ["绝区零", "zzz"]},
    {"name": "鸣潮", "category": "game", "desc": "库洛开放世界动作游戏，常与原神对比", "aliases": ["鸣潮"]},
    {"name": "王者荣耀", "category": "game", "desc": "腾讯 5v5 手游 MOBA，国内用户量最大", "aliases": ["王者荣耀", "王者"]},
    {"name": "英雄联盟", "category": "game", "desc": "拳头 5v5 MOBA 端游，赛事简称 LPL / S 赛", "aliases": ["英雄联盟", "lol", "lpl", "云顶"]},
    {"name": "永劫无间", "category": "game", "desc": "国产武侠吃鸡类动作游戏，主打拼刀", "aliases": ["永劫无间", "永劫"]},
    {"name": "黑神话：悟空", "category": "game", "desc": "2024 年国产单机动作游戏，以西游为题材", "aliases": ["黑神话", "黑猴"]},
    {"name": "反恐精英", "category": "game", "desc": "经典战术射击游戏，指 CS2 / CSGO", "aliases": ["csgo", "cs2", "反恐精英"]},
    {"name": "无畏契约", "category": "game", "desc": "拳头 5v5 战术射击，国服叫无畏契约，俗称瓦", "aliases": ["无畏契约", "瓦罗兰特", "valorant"]},
    {"name": "和平精英", "category": "game", "desc": "腾讯战术竞技手游，俗称吃鸡 / PUBG", "aliases": ["和平精英", "吃鸡", "pubg", "绝地求生"]},
    {"name": "蛋仔派对", "category": "game", "desc": "网易休闲派对游戏，画风可爱、地图多样", "aliases": ["蛋仔派对", "蛋仔"]},
    {"name": "我的世界", "category": "game", "desc": "沙盒建造游戏，玩家常聊红石与模组", "aliases": ["我的世界", "minecraft"]},
    {"name": "第五人格", "category": "game", "desc": "网易 1v4 非对称对抗游戏，俗称屠夫与求生者", "aliases": ["第五人格"]},
    {"name": "金铲铲之战", "category": "game", "desc": "腾讯自走棋手游，对应端游云顶之弈", "aliases": ["金铲铲", "云顶之弈"]},
    {"name": "DOTA2", "category": "game", "desc": "V 社 MOBA 端游，赛事最高为 TI 国际邀请赛", "aliases": ["dota2", "dota"]},
    {"name": "艾尔登法环", "category": "game", "desc": "宫崎英高魂系开放世界，俗称老头环", "aliases": ["艾尔登法环", "老头环", "魂系"]},
    {"name": "幻兽帕鲁", "category": "game", "desc": "2024 年爆火的抓宠生存建造游戏", "aliases": ["幻兽帕鲁", "帕鲁"]},
    {"name": "泰拉瑞亚", "category": "game", "desc": "2D 沙盒冒险游戏，主打探索与打 Boss", "aliases": ["泰拉瑞亚"]},
    {"name": "明日方舟", "category": "game", "desc": "鹰角塔防养成手游，衍生作有终末地", "aliases": ["明日方舟", "方舟", "终末地"]},
    {"name": "碧蓝航线", "category": "game", "desc": "舰娘题材弹幕养成手游", "aliases": ["碧蓝航线"]},
    {"name": "蔚蓝档案", "category": "game", "desc": "日服养成 RPG，玩家自称老师", "aliases": ["蔚蓝档案", "碧蓝档案"]},
    {"name": "三角洲行动", "category": "game", "desc": "腾讯战术撤离射击游戏", "aliases": ["三角洲行动"]},
    {"name": "逃离塔科夫", "category": "game", "desc": "硬核撤离类射击游戏，俗称塔科夫", "aliases": ["逃离塔科夫", "塔科夫"]},
    {"name": "塞尔达传说", "category": "game", "desc": "任天堂开放世界冒险，代表作旷野之息 / 王国之泪", "aliases": ["塞尔达", "旷野之息", "王国之泪"]},
    {"name": "动物森友会", "category": "game", "desc": "任天堂慢节奏岛屿生活游戏，俗称动森", "aliases": ["动森", "动物森友会"]},
    {"name": "双人成行", "category": "game", "desc": "主打双人合作通关的冒险游戏", "aliases": ["双人成行"]},

    # ---------------------------------------------------------- 梗
    {"name": "破防", "category": "meme", "desc": "指被戳到痛处、情绪绷不住了", "aliases": ["破防"]},
    {"name": "绷不住了", "category": "meme", "desc": "忍不住笑或绷不住情绪，谐音「蚌埠住了」", "aliases": ["蚌埠住了", "绷不住了"]},
    {"name": "yyds", "category": "meme", "desc": "「永远的神」拼音缩写，用来夸人或事物", "aliases": ["yyds"]},
    {"name": "退钱", "category": "meme", "desc": "源自国足采访，现泛指「不值、快退钱」的吐槽", "aliases": ["退钱"]},
    {"name": "寄了", "category": "meme", "desc": "「GG 了」的谐音，表示完蛋 / 没救了", "aliases": ["寄了"]},
    {"name": "抽象", "category": "meme", "desc": "形容内容离谱、看不懂的行为艺术式搞笑", "aliases": ["抽象"]},
    {"name": "整活", "category": "meme", "desc": "指刻意制造节目效果、搞事情", "aliases": ["整活"]},
    {"name": "遥遥领先", "category": "meme", "desc": "发布会金句，现多用于反讽式吹捧", "aliases": ["遥遥领先"]},
    {"name": "栓Q", "category": "meme", "desc": "「thank you」的谐音，表达无奈或无语", "aliases": ["栓q"]},
    {"name": "已老实", "category": "meme", "desc": "表示认怂、服气了", "aliases": ["已老实", "老实了"]},
    {"name": "下饭", "category": "meme", "desc": "形容操作太菜，配上吃饭看很助消化", "aliases": ["下饭"]},
    {"name": "干饭", "category": "meme", "desc": "吃饭的意思，多带急切语气", "aliases": ["干饭"]},
    {"name": "emo", "category": "meme", "desc": "情绪低落、伤感的状态", "aliases": ["emo"]},
    {"name": "典中典", "category": "meme", "desc": "「经典中的经典」，多用于嘲讽套路化发言", "aliases": ["典中典"]},
    {"name": "急急急", "category": "meme", "desc": "调侃对方着急上火的连发句式", "aliases": ["急急急"]},
    {"name": "汗流浃背", "category": "meme", "desc": "形容紧张、慌得不行的状态", "aliases": ["汗流浃背"]},
    {"name": "city不city", "category": "meme", "desc": "2024 年热梗，意为洋气不洋气", "aliases": ["city不city"]},
    {"name": "情绪价值", "category": "meme", "desc": "指能提供好心情、让人舒服的陪伴感", "aliases": ["情绪价值"]},

    # ---------------------------------------------------------- 番剧
    {"name": "火影忍者", "category": "anime", "desc": "岸本齐史热血忍者漫画 / 动画", "aliases": ["火影忍者", "火影"]},
    {"name": "海贼王", "category": "anime", "desc": "尾田荣一郎长连载冒险漫画 / 动画", "aliases": ["海贼王", "one piece"]},
    {"name": "名侦探柯南", "category": "anime", "desc": "青山刚昌推理漫画 / 动画，主角江户川柯南", "aliases": ["名侦探柯南", "柯南"]},
    {"name": "咒术回战", "category": "anime", "desc": "芥见下下战斗漫画 / 动画，五条悟人气极高", "aliases": ["咒术回战", "咒术"]},
    {"name": "鬼灭之刃", "category": "anime", "desc": "吾峠呼世晴战斗漫画 / 动画，ufotable 制作", "aliases": ["鬼灭之刃", "鬼灭"]},
    {"name": "进击的巨人", "category": "anime", "desc": "谏山创暗黑奇幻漫画 / 动画", "aliases": ["进击的巨人", "巨人"]},
    {"name": "间谍过家家", "category": "anime", "desc": "远藤达哉家庭喜剧漫画 / 动画，主角阿尼亚", "aliases": ["间谍过家家", "阿尼亚"]},
    {"name": "孤独摇滚", "category": "anime", "desc": "后藤一里（波奇酱）为主角的乐队题材动画", "aliases": ["孤独摇滚", "波奇"]},
    {"name": "排球少年", "category": "anime", "desc": "古馆春一热血排球漫画 / 动画", "aliases": ["排球少年"]},
    {"name": "灌篮高手", "category": "anime", "desc": "井上雄彦篮球漫画 / 动画，主角樱木花道", "aliases": ["灌篮高手", "樱木"]},
    {"name": "七龙珠", "category": "anime", "desc": "鸟山明经典热血漫画 / 动画", "aliases": ["七龙珠", "龙珠"]},
    {"name": "死神", "category": "anime", "desc": "久保带人漫画 / 动画，全名 BLEACH", "aliases": ["bleach"]},
    {"name": "高达", "category": "anime", "desc": "日升机器人系列动画，机体俗称高达", "aliases": ["高达"]},
    {"name": "初音未来", "category": "anime", "desc": "Crypton 虚拟歌手，VOCALOID 代表角色", "aliases": ["初音未来", "初音", "miku"]},
    {"name": "你的名字", "category": "anime", "desc": "新海诚动画电影，2016 年现象级作品", "aliases": ["你的名字"]},
    {"name": "天气之子", "category": "anime", "desc": "新海诚动画电影，2019 年上映", "aliases": ["天气之子"]},
    {"name": "赛马娘", "category": "anime", "desc": "以赛马拟人化为题材的动画与手游", "aliases": ["赛马娘"]},

    # ---------------------------------------------------------- 音乐
    {"name": "周杰伦", "category": "music", "desc": "华语流行歌手，代表作《晴天》《稻香》", "aliases": ["周杰伦", "杰伦"]},
    {"name": "林俊杰", "category": "music", "desc": "华语流行歌手，代表作《江南》《修炼爱情》", "aliases": ["林俊杰", "jj"]},
    {"name": "陈奕迅", "category": "music", "desc": "香港歌手，代表作《十年》《浮夸》", "aliases": ["陈奕迅", "eason"]},
    {"name": "邓紫棋", "category": "music", "desc": "香港歌手，代表作《光年之外》《泡沫》", "aliases": ["邓紫棋"]},
    {"name": "薛之谦", "category": "music", "desc": "内地歌手，代表作《演员》《丑八怪》", "aliases": ["薛之谦"]},
    {"name": "五月天", "category": "music", "desc": "台湾摇滚乐队，代表作《倔强》《突然好想你》", "aliases": ["五月天"]},
    {"name": "华晨宇", "category": "music", "desc": "内地歌手，以高音与舞台表现力著称", "aliases": ["华晨宇"]},
    {"name": "毛不易", "category": "music", "desc": "内地创作歌手，代表作《消愁》《像我这样的人》", "aliases": ["毛不易"]},
    {"name": "周深", "category": "music", "desc": "内地歌手，以空灵音色与多语种翻唱著称", "aliases": ["周深"]},
    {"name": "许嵩", "category": "music", "desc": "内地创作歌手，代表作《有何不可》《素颜》", "aliases": ["许嵩"]},
    {"name": "汪苏泷", "category": "music", "desc": "内地歌手，代表作《一笑倾城》《万有引力》", "aliases": ["汪苏泷"]},
    {"name": "说唱", "category": "music", "desc": "Rap 曲风，常讨论 flow 与押韵", "aliases": ["说唱", "rap"]},
    {"name": "摇滚", "category": "music", "desc": "Rock 曲风，强调吉他失真与现场感", "aliases": ["摇滚"]},
    {"name": "民谣", "category": "music", "desc": "以叙事和木吉他为主的抒情曲风", "aliases": ["民谣"]},
    {"name": "古风", "category": "music", "desc": "融合传统乐器与文言意象的国风曲风", "aliases": ["古风", "国风"]},
    {"name": "电音", "category": "music", "desc": "电子舞曲，含 House / EDM 等子风格", "aliases": ["电音", "edm"]},

    # ---------------------------------------------------------- 圈内术语
    {"name": "上舰", "category": "jargon", "desc": "开通直播间大航海，按价格分舰长 / 提督 / 总督", "aliases": ["上舰", "大航海"]},
    {"name": "舰长", "category": "jargon", "desc": "大航海最低档，月费 138 元", "aliases": ["舰长"]},
    {"name": "提督", "category": "jargon", "desc": "大航海第二档，月费 1998 元", "aliases": ["提督"]},
    {"name": "总督", "category": "jargon", "desc": "大航海最高档，月费 19998 元", "aliases": ["总督"]},
    {"name": "粉丝牌", "category": "jargon", "desc": "佩戴后可累积亲密度升级的灯牌，代表长期消费", "aliases": ["粉丝牌", "灯牌", "牌子"]},
    {"name": "恰饭", "category": "jargon", "desc": "指接广告商单赚钱", "aliases": ["恰饭"]},
    {"name": "白嫖", "category": "jargon", "desc": "只看不消费、不投币不打赏的行为", "aliases": ["白嫖"]},
    {"name": "一键三连", "category": "jargon", "desc": "B 站的点赞、投币、收藏三连支持", "aliases": ["一键三连", "三连"]},
    {"name": "空降", "category": "jargon", "desc": "跳过前面内容直接跳到精彩片段", "aliases": ["空降"]},
    {"name": "名场面", "category": "jargon", "desc": "指极其经典、值得反复回看的一幕", "aliases": ["名场面"]},
    {"name": "二创", "category": "jargon", "desc": "粉丝基于原作的二次创作", "aliases": ["二创"]},
    {"name": "鬼畜", "category": "jargon", "desc": "B 站特有的高重复剪切搞笑剪辑形式", "aliases": ["鬼畜"]},
    {"name": "超管", "category": "jargon", "desc": "平台超管，负责巡查违规直播间", "aliases": ["超管"]},
    {"name": "醒目留言", "category": "jargon", "desc": "SC / SuperChat，付费置顶的弹幕", "aliases": ["醒目留言", "sc", "superchat"]},
]

# 内置种子 = 核心词条 + topics_data 下按领域拆分的扩展词库（游戏 / 番剧 / 影视 / 生活）。
SEED_TOPICS: List[Dict[str, Any]] = DEFAULT_TOPICS + ALL_TOPICS


_ASCII_ALIAS = re.compile(r"^[A-Za-z0-9_]+$")


def _alias_pattern(alias: str) -> str:
    """纯英文别名加词边界，避免 sc 命中 discord、lol 命中 lollipop。

    中日文别名不加边界——JS / Python 的 \\b 只认 ASCII，加了对中文反而匹配不上。
    """
    escaped = re.escape(alias)
    if _ASCII_ALIAS.match(alias):
        return rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
    return escaped


class TopicLibrary:
    """热门元素库：加载 topics.json、做关键词匹配、汇总命中次数。"""

    def __init__(self, path: Path = TOPICS_PATH):
        self.path = path
        self._mtime: float = -1
        self._categories: List[dict] = list(CATEGORIES)
        self._topics: List[dict] = []
        self._by_name: Dict[str, dict] = {}
        self._map: Dict[str, dict] = {}
        self._regex = None

    # ------------------------------------------------------------------
    def _read(self) -> Dict[str, Any]:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(
                    {"categories": CATEGORIES, "topics": SEED_TOPICS},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[topics] topics.json 解析失败({exc})，改用内置词库")
            return {"categories": CATEGORIES, "topics": SEED_TOPICS}

    def reload_if_changed(self):
        """文件被编辑过就重新加载，省得改词条还要重启服务。"""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            mtime = -1
        if mtime == self._mtime and self._topics:
            return
        self._mtime = mtime
        self._build(self._read())

    def _build(self, data: Dict[str, Any]):
        self._categories = data.get("categories") or list(CATEGORIES)
        cat_map = {c.get("key"): c for c in self._categories}
        topics: List[dict] = []
        seen_names = set()
        for raw in data.get("topics") or []:
            name = str(raw.get("name") or "").strip()
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            key = str(raw.get("category") or "other")
            cat = cat_map.get(key) or {"label": key, "color": "#8b93a7"}
            aliases = [str(a).strip() for a in (raw.get("aliases") or []) if str(a).strip()]
            if name not in aliases:
                aliases.insert(0, name)
            topics.append(
                {
                    "name": name,
                    "category": key,
                    "category_label": cat.get("label", key),
                    "color": cat.get("color", "#8b93a7"),
                    "desc": str(raw.get("desc") or ""),
                    "aliases": aliases,
                }
            )
        self._topics = topics
        self._by_name = {t["name"]: t for t in topics}
        # 长别名排在前面，避免短词抢先命中（如「原」抢「原神」）
        pairs = sorted(
            ((a, t) for t in topics for a in t["aliases"]),
            key=lambda p: len(p[0]),
            reverse=True,
        )
        # 同一别名被多个词条占用时，先出现者（核心词条优先）胜出，保证匹配结果稳定
        self._map = {}
        patterns: List[str] = []
        for alias, topic in pairs:
            low = alias.lower()
            if low in self._map:
                continue
            self._map[low] = topic
            patterns.append(_alias_pattern(alias))
        self._regex = re.compile("|".join(patterns)) if patterns else None

    # ------------------------------------------------------------------
    def match(self, text: str) -> List[dict]:
        """返回一段文本里命中的元素（同一条里重复提到只算一次）。"""
        if not text or not self._regex:
            return []
        found: List[dict] = []
        seen = set()
        for m in self._regex.finditer(text):
            topic = self._map.get(m.group(0).lower())
            if topic and topic["name"] not in seen:
                seen.add(topic["name"])
                found.append(topic)
        return found

    def match_counts(self, texts: List[str], limit: int = 24) -> List[Dict[str, Any]]:
        """汇总一组发言里的命中元素，按提及条数排序。"""
        self.reload_if_changed()
        counter: Counter = Counter()
        for text in texts:
            if text:
                counter.update(t["name"] for t in self.match(text))
        return [
            {
                "名称": name,
                "分类": self._by_name[name]["category_label"],
                "颜色": self._by_name[name]["color"],
                "次数": count,
                "说明": self._by_name[name]["desc"],
            }
            for name, count in counter.most_common(limit)
        ]

    def as_payload(self) -> Dict[str, Any]:
        """给前端做弹幕高亮用的词库快照。"""
        self.reload_if_changed()
        return {"categories": self._categories, "topics": self._topics}


TOPICS = TopicLibrary()
