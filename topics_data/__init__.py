"""热门元素库的种子数据，按领域拆分维护。

每个模块导出 TOPICS: List[dict]，字段与 topics.py 的说明一致：
  name 主名称 / category 分类键 / desc 一句话说明 / aliases 触发别名
"""

from .acg import TOPICS as ACG_TOPICS
from .games import TOPICS as GAME_TOPICS
from .life import TOPICS as LIFE_TOPICS
from .screen import TOPICS as SCREEN_TOPICS

ALL_TOPICS = [*GAME_TOPICS, *ACG_TOPICS, *SCREEN_TOPICS, *LIFE_TOPICS]

__all__ = ["ALL_TOPICS"]
