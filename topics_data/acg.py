"""热门 ACG 词库：主流番剧、番剧角色与圈内术语，供弹幕高亮与归类使用。"""

TOPICS = [
    {"name": "火影忍者", "category": "anime", "desc": "岸本齐史热血忍者漫画与动画，讲鸣人立志成为火影", "aliases": ["火影忍者", "火影", "naruto"]},
    {"name": "漩涡鸣人", "category": "anime_char", "desc": "《火影忍者》主角，九尾人柱力，口头禅是说到做到", "aliases": ["漩涡鸣人", "鸣人"]},
    {"name": "宇智波佐助", "category": "anime_char", "desc": "《火影忍者》男二，宇智波一族天才忍者，擅长千鸟", "aliases": ["宇智波佐助", "佐助"]},
    {"name": "旗木卡卡西", "category": "anime_char", "desc": "《火影忍者》第七班老师，外号拷贝忍者卡卡西", "aliases": ["旗木卡卡西", "卡卡西"]},
    {"name": "写轮眼", "category": "anime_term", "desc": "《火影忍者》宇智波一族的瞳术，可复制忍术并施幻术", "aliases": ["写轮眼"]},

    {"name": "海贼王", "category": "anime", "desc": "尾田荣一郎冒险漫画，讲路飞率草帽团寻找大秘宝", "aliases": ["海贼王", "one piece"]},
    {"name": "路飞", "category": "anime_char", "desc": "《海贼王》主角，橡胶果实能力者，目标是海贼王", "aliases": ["路飞", "luffy"]},
    {"name": "索隆", "category": "anime_char", "desc": "《海贼王》草帽团剑士，三刀流，立志成为世界第一大剑豪", "aliases": ["索隆", "zoro"]},
    {"name": "娜美", "category": "anime_char", "desc": "《海贼王》草帽团航海士，梦想绘制全世界海图", "aliases": ["娜美", "nami"]},
    {"name": "恶魔果实", "category": "anime_term", "desc": "《海贼王》设定，吃下可获超能力但被大海厌弃", "aliases": ["恶魔果实"]},

    {"name": "名侦探柯南", "category": "anime", "desc": "青山刚昌推理漫画，高中生侦探变小后破案", "aliases": ["名侦探柯南", "柯南", "conan"]},
    {"name": "工藤新一", "category": "anime_char", "desc": "《名侦探柯南》主角，高中生名侦探，变小成柯南", "aliases": ["工藤新一", "新一"]},
    {"name": "毛利兰", "category": "anime_char", "desc": "《名侦探柯南》女主，新一青梅竹马，空手道高手", "aliases": ["毛利兰", "小兰"]},
    {"name": "黑衣组织", "category": "anime_term", "desc": "《名侦探柯南》里的神秘犯罪集团，代号琴酒等酒名", "aliases": ["黑衣组织"]},
    {"name": "安室透", "category": "anime_char", "desc": "《名侦探柯南》人气角色，组织卧底，咖啡厅店员", "aliases": ["安室透"]},

    {"name": "咒术回战", "category": "anime", "desc": "芥见下下战斗漫画，讲咒术师祓除咒灵的故事", "aliases": ["咒术回战", "咒术"]},
    {"name": "五条悟", "category": "anime_char", "desc": "《咒术回战》最强咒术师，白发蓝眼、人气极高", "aliases": ["五条悟", "五条"]},
    {"name": "虎杖悠仁", "category": "anime_char", "desc": "《咒术回战》主角，身体被宿傩寄宿的少年", "aliases": ["虎杖悠仁", "虎杖"]},
    {"name": "宿傩", "category": "anime_char", "desc": "《咒术回战》最强咒灵，寄宿在虎杖体内的诅咒之王", "aliases": ["宿傩", "两面宿傩"]},
    {"name": "领域展开", "category": "anime_term", "desc": "《咒术回战》把自身术式铺开成领域的终极技能", "aliases": ["领域展开"]},

    {"name": "鬼灭之刃", "category": "anime", "desc": "吾峠呼世晴战斗漫画，ufotable 制作，讲炭治郎灭鬼", "aliases": ["鬼灭之刃", "鬼灭"]},
    {"name": "灶门炭治郎", "category": "anime_char", "desc": "《鬼灭之刃》主角，为救变鬼的妹妹加入鬼杀队", "aliases": ["灶门炭治郎", "炭治郎"]},
    {"name": "祢豆子", "category": "anime_char", "desc": "《鬼灭之刃》炭治郎之妹，被鬼化后咬着竹筒", "aliases": ["祢豆子"]},
    {"name": "我妻善逸", "category": "anime_char", "desc": "《鬼灭之刃》胆小剑士，睡着后使雷之呼吸", "aliases": ["我妻善逸", "善逸"]},
    {"name": "富冈义勇", "category": "anime_char", "desc": "《鬼灭之刃》水柱，沉默寡言，救了炭治郎兄妹", "aliases": ["富冈义勇", "义勇"]},
    {"name": "呼吸法", "category": "anime_term", "desc": "《鬼灭之刃》剑士借呼吸强化身体与刀法的战斗术", "aliases": ["呼吸法", "全集中呼吸"]},

    {"name": "进击的巨人", "category": "anime", "desc": "谏山创暗黑奇幻漫画，讲人类对抗巨人与真相", "aliases": ["进击的巨人", "attack on titan"]},
    {"name": "艾伦", "category": "anime_char", "desc": "《进击的巨人》主角，誓要驱逐所有巨人的少年", "aliases": ["艾伦", "艾伦耶格尔"]},
    {"name": "三笠", "category": "anime_char", "desc": "《进击的巨人》女主，战斗力超强的阿克曼一族", "aliases": ["三笠"]},
    {"name": "利威尔", "category": "anime_char", "desc": "《进击的巨人》人类最强士兵，调查兵团兵长", "aliases": ["利威尔", "兵长"]},
    {"name": "调查兵团", "category": "anime_term", "desc": "《进击的巨人》墙外作战的军队，标志为自由之翼", "aliases": ["调查兵团"]},
    {"name": "地鸣", "category": "anime_term", "desc": "《进击的巨人》里唤醒墙内超大型巨人踏平世界", "aliases": ["地鸣"]},

    {"name": "间谍过家家", "category": "anime", "desc": "远藤达哉家庭喜剧漫画，间谍与杀手组建家庭", "aliases": ["间谍过家家", "spy family"]},
    {"name": "阿尼亚", "category": "anime_char", "desc": "《间谍过家家》会读心的超能力小女孩，超可爱", "aliases": ["阿尼亚", "anya"]},
    {"name": "劳埃德·福杰", "category": "anime_char", "desc": "《间谍过家家》男主，代号黄昏的顶尖间谍", "aliases": ["劳埃德·福杰", "劳埃德"]},
    {"name": "约尔", "category": "anime_char", "desc": "《间谍过家家》女主，代号睡美人的职业杀手", "aliases": ["约尔"]},

    {"name": "孤独摇滚", "category": "anime", "desc": "讲社恐少女后藤一里加入乐队后成长的音乐动画", "aliases": ["孤独摇滚"]},
    {"name": "后藤一里", "category": "anime_char", "desc": "《孤独摇滚》主角，社恐吉他手，外号波奇酱", "aliases": ["后藤一里", "波奇", "波奇酱"]},
    {"name": "结束乐队", "category": "anime_term", "desc": "《孤独摇滚》中主角们组建的四人女子乐队", "aliases": ["结束乐队"]},

    {"name": "排球少年", "category": "anime", "desc": "古馆春一热血排球漫画，讲乌野高中排球队", "aliases": ["排球少年"]},
    {"name": "日向翔阳", "category": "anime_char", "desc": "《排球少年》主角，个子矮却弹跳惊人的副攻", "aliases": ["日向翔阳", "日向"]},
    {"name": "影山飞雄", "category": "anime_char", "desc": "《排球少年》天才二传手，与日向组成怪人快攻", "aliases": ["影山飞雄", "影山"]},

    {"name": "灌篮高手", "category": "anime", "desc": "井上雄彦篮球漫画，讲湘北高中篮球队的热血故事", "aliases": ["灌篮高手"]},
    {"name": "樱木花道", "category": "anime_char", "desc": "《灌篮高手》主角，红发新人，天才篮板王", "aliases": ["樱木花道", "樱木"]},
    {"name": "流川枫", "category": "anime_char", "desc": "《灌篮高手》王牌球员，冷酷寡言的得分机器", "aliases": ["流川枫", "流川"]},

    {"name": "七龙珠", "category": "anime", "desc": "鸟山明经典热血漫画，讲悟空收集龙珠与战斗", "aliases": ["七龙珠", "龙珠"]},
    {"name": "孙悟空", "category": "anime_char", "desc": "《七龙珠》主角，赛亚人，不断突破极限变强", "aliases": ["孙悟空"]},
    {"name": "超级赛亚人", "category": "anime_term", "desc": "《七龙珠》赛亚人的变身形态，头发金黄气焰冲天", "aliases": ["超级赛亚人", "赛亚人"]},
    {"name": "贝吉塔", "category": "anime_char", "desc": "《七龙珠》赛亚人王子，悟空亦敌亦友的劲敌", "aliases": ["贝吉塔"]},

    {"name": "死神", "category": "anime", "desc": "久保带人漫画，讲黑崎一护成为死神斩虚的故事", "aliases": ["死神", "bleach"]},
    {"name": "黑崎一护", "category": "anime_char", "desc": "《死神》主角，橙发高中生，持斩魄刀斩虚", "aliases": ["黑崎一护", "一护"]},
    {"name": "斩魄刀", "category": "anime_term", "desc": "《死神》中死神的佩刀，可解放为卍解施展能力", "aliases": ["斩魄刀", "卍解"]},

    {"name": "机动战士高达", "category": "anime", "desc": "日升机器人动画系列，标志性机体与战争题材", "aliases": ["机动战士高达", "高达"]},
    {"name": "阿姆罗", "category": "anime_char", "desc": "《机动战士高达》初代主角，传奇新人类机师", "aliases": ["阿姆罗"]},
    {"name": "夏亚", "category": "anime_char", "desc": "《机动战士高达》人气角色，红色机体与复仇者", "aliases": ["夏亚"]},

    {"name": "新世纪福音战士", "category": "anime", "desc": "庵野秀明机战动画，讲少年少女驾驶 EVA 战斗", "aliases": ["新世纪福音战士", "eva"]},
    {"name": "绫波丽", "category": "anime_char", "desc": "《新世纪福音战士》驾驶员，沉默神秘的蓝发少女", "aliases": ["绫波丽", "绫波"]},
    {"name": "明日香", "category": "anime_char", "desc": "《新世纪福音战士》驾驶员，傲娇好胜的红发少女", "aliases": ["明日香"]},

    {"name": "命运石之门", "category": "anime", "desc": "科幻悬疑动画，讲冈部用电话微波炉改变世界线", "aliases": ["命运石之门", "石头门", "steins gate"]},
    {"name": "冈部伦太郎", "category": "anime_char", "desc": "《命运石之门》主角，自称凤凰院凶真的科学家", "aliases": ["冈部伦太郎", "冈部"]},
    {"name": "世界线", "category": "anime_term", "desc": "《命运石之门》里时间分支的设定，变动会有收束", "aliases": ["世界线"]},

    {"name": "Re:从零开始的异世界生活", "category": "anime", "desc": "长月达平轻小说改编，主角死亡后会回到存档点", "aliases": ["从零开始的异世界生活", "re:zero", "re0"]},
    {"name": "蕾姆", "category": "anime_char", "desc": "《Re:从零开始》人气女仆角色，蓝发，忠于昴", "aliases": ["蕾姆", "rem"]},
    {"name": "艾米莉娅", "category": "anime_char", "desc": "《Re:从零开始》女主，银发半精灵，王选候选人", "aliases": ["艾米莉娅", "爱蜜莉雅"]},

    {"name": "刀剑神域", "category": "anime", "desc": "川原砾轻小说改编，玩家被困 VR 游戏里通关求生", "aliases": ["刀剑神域", "sao"]},
    {"name": "桐人", "category": "anime_char", "desc": "《刀剑神域》主角，黑衣剑士，通关死亡游戏", "aliases": ["桐人", "桐谷和人"]},
    {"name": "亚丝娜", "category": "anime_char", "desc": "《刀剑神域》女主，细剑使，人称闪光的亚丝娜", "aliases": ["亚丝娜"]},

    {"name": "Fate", "category": "anime", "desc": "型月世界观系列，围绕圣杯战争与英灵召唤展开", "aliases": ["fate", "命运之夜"]},
    {"name": "Saber", "category": "anime_char", "desc": "《Fate》系列代表英灵，阿尔托莉雅，持誓约之剑", "aliases": ["saber", "阿尔托莉雅"]},
    {"name": "圣杯战争", "category": "anime_term", "desc": "《Fate》设定，英灵互斗争夺能实现愿望的圣杯", "aliases": ["圣杯战争"]},

    {"name": "一拳超人", "category": "anime", "desc": "ONE 原作漫画，讲光头英雄埼玉一拳解决敌人", "aliases": ["一拳超人"]},
    {"name": "埼玉", "category": "anime_char", "desc": "《一拳超人》主角，光头，任何敌人都能一拳解决", "aliases": ["埼玉"]},
    {"name": "杰诺斯", "category": "anime_char", "desc": "《一拳超人》改造人，埼玉的弟子，火力全开", "aliases": ["杰诺斯"]},

    {"name": "电锯人", "category": "anime", "desc": "藤本树暗黑战斗漫画，讲少年电次与恶魔猎人", "aliases": ["电锯人", "chainsaw man"]},
    {"name": "电次", "category": "anime_char", "desc": "《电锯人》主角，心脏与电锯恶魔融合的少年", "aliases": ["电次"]},
    {"name": "玛奇玛", "category": "anime_char", "desc": "《电锯人》里的神秘女上司，公安对魔特异课", "aliases": ["玛奇玛"]},
    {"name": "帕瓦", "category": "anime_char", "desc": "《电锯人》血之魔人，自称天才的粉色头发少女", "aliases": ["帕瓦"]},

    {"name": "赛马娘", "category": "anime", "desc": "以赛马拟人化为题材的动画与养成手游", "aliases": ["赛马娘"]},
    {"name": "特别周", "category": "anime_char", "desc": "《赛马娘》主角，来自北海道的元气赛马娘", "aliases": ["特别周"]},
    {"name": "无声铃鹿", "category": "anime_char", "desc": "《赛马娘》里擅长领跑的大逃马娘，命运悲情", "aliases": ["无声铃鹿"]},

    {"name": "蓝色监狱", "category": "anime", "desc": "足球漫画，讲三百名前锋封闭训练争夺最强", "aliases": ["蓝色监狱", "blue lock"]},
    {"name": "洁世一", "category": "anime_char", "desc": "《蓝色监狱》主角，以自我为中心的进球型前锋", "aliases": ["洁世一"]},
    {"name": "凪诚士郎", "category": "anime_char", "desc": "《蓝色监狱》天才前锋，慵懒却拥有惊人球感", "aliases": ["凪诚士郎"]},

    {"name": "我推的孩子", "category": "anime", "desc": "赤坂明漫画，讲转生为偶像之子的复仇与演艺圈", "aliases": ["我推的孩子"]},
    {"name": "星野爱", "category": "anime_char", "desc": "《我推的孩子》传奇偶像，B 小町成员，双胞胎之母", "aliases": ["星野爱"]},
    {"name": "阿库亚", "category": "anime_char", "desc": "《我推的孩子》男主，为调查母亲之死进入演艺圈", "aliases": ["阿库亚"]},
    {"name": "露比", "category": "anime_char", "desc": "《我推的孩子》女主，爱的女儿，立志当偶像", "aliases": ["露比"]},

    {"name": "葬送的芙莉莲", "category": "anime", "desc": "2023 年奇幻动画，讲长生精灵芙莉莲重走冒险之路", "aliases": ["葬送的芙莉莲", "芙莉莲"]},
    {"name": "菲伦", "category": "anime_char", "desc": "《葬送的芙莉莲》女主，芙莉莲的弟子，魔法使", "aliases": ["菲伦"]},
    {"name": "修塔尔克", "category": "anime_char", "desc": "《葬送的芙莉莲》战士，胆小却实力超群的少年", "aliases": ["修塔尔克"]},
    {"name": "辛美尔", "category": "anime_char", "desc": "《葬送的芙莉莲》勇者，已故却贯穿全作的白月光", "aliases": ["辛美尔"]},

    {"name": "药屋少女的呢喃", "category": "anime", "desc": "后宫题材推理小说改编，讲药师猫猫破解谜案", "aliases": ["药屋少女的呢喃", "药屋少女"]},
    {"name": "猫猫", "category": "anime_char", "desc": "《药屋少女的呢喃》女主，懂药理的宫中试毒少女", "aliases": ["猫猫"]},
    {"name": "壬氏", "category": "anime_char", "desc": "《药屋少女的呢喃》男主，美貌宦官，实为皇弟", "aliases": ["壬氏"]},

    {"name": "赛博朋克：边缘行者", "category": "anime", "desc": "扳机社制作的赛博朋克动画，讲大卫一家的悲剧", "aliases": ["赛博朋克：边缘行者", "赛博朋克边缘行者", "边缘行者", "cyberpunk edgerunners"]},
    {"name": "露西", "category": "anime_char", "desc": "《赛博朋克：边缘行者》女主，想上月球的女黑客", "aliases": ["露西"]},
    {"name": "大卫·马丁内斯", "category": "anime_char", "desc": "《赛博朋克：边缘行者》主角，装义体的边缘行者", "aliases": ["大卫·马丁内斯"]},

    {"name": "我的英雄学院", "category": "anime", "desc": "堀越耕平漫画，讲超能力社会里绿谷成为英雄", "aliases": ["我的英雄学院", "我英"]},
    {"name": "绿谷出久", "category": "anime_char", "desc": "《我的英雄学院》主角，无个性却继承最强之力", "aliases": ["绿谷出久", "绿谷"]},
    {"name": "爆豪胜己", "category": "anime_char", "desc": "《我的英雄学院》主角劲敌，爆炸个性，脾气火爆", "aliases": ["爆豪胜己", "爆豪"]},

    {"name": "JOJO的奇妙冒险", "category": "anime", "desc": "荒木飞吕彦漫画，以替身战斗和家族血统为主线", "aliases": ["jojo", "jojo的奇妙冒险"]},
    {"name": "空条承太郎", "category": "anime_char", "desc": "《JOJO》第三部主角，白金之星使用者，无敌气场", "aliases": ["空条承太郎", "承太郎"]},
    {"name": "替身", "category": "anime_term", "desc": "《JOJO》里精神力量具现化的战斗伙伴与能力", "aliases": ["替身"]},
    {"name": "欧拉欧拉", "category": "anime_term", "desc": "《JOJO》承太郎替身连打的招牌战吼，木大木大同理", "aliases": ["欧拉欧拉", "木大木大"]},

    {"name": "银魂", "category": "anime", "desc": "空知英秋搞笑漫画，讲万事屋与江户的吐槽日常", "aliases": ["银魂"]},
    {"name": "坂田银时", "category": "anime_char", "desc": "《银魂》主角，万事屋老板，爱甜食的废柴武士", "aliases": ["坂田银时", "银时"]},
    {"name": "志村新八", "category": "anime_char", "desc": "《银魂》万事屋成员，吐槽担当，眼镜本体", "aliases": ["志村新八", "新八"]},
    {"name": "神乐", "category": "anime_char", "desc": "《银魂》万事屋成员，夜兔族少女，力大爱吃醋昆布", "aliases": ["神乐"]},

    {"name": "夏目友人帐", "category": "anime", "desc": "绿川幸漫画，讲能看到妖怪的夏目归还名字的故事", "aliases": ["夏目友人帐"]},
    {"name": "夏目贵志", "category": "anime_char", "desc": "《夏目友人帐》主角，能看见妖怪的温柔少年", "aliases": ["夏目贵志", "夏目"]},
    {"name": "猫咪老师", "category": "anime_char", "desc": "《夏目友人帐》里的招财猫妖怪，真身是斑", "aliases": ["猫咪老师", "娘口三三"]},

    {"name": "轻音少女", "category": "anime", "desc": "京都动画音乐日常番，讲轻音部少女们的校园生活", "aliases": ["轻音少女", "轻音"]},
    {"name": "平泽唯", "category": "anime_char", "desc": "《轻音少女》主角，天然呆吉他手，绰号唯", "aliases": ["平泽唯"]},
    {"name": "中野梓", "category": "anime_char", "desc": "《轻音少女》后辈吉他手，外号梓喵，认真可爱", "aliases": ["中野梓", "梓喵"]},
    {"name": "秋山澪", "category": "anime_char", "desc": "《轻音少女》贝斯手，胆小易羞，人气很高", "aliases": ["秋山澪"]},

    {"name": "辉夜大小姐想让我告白", "category": "anime", "desc": "恋爱头脑战喜剧，讲学生会正副会长互相算计", "aliases": ["辉夜大小姐想让我告白", "辉夜大小姐"]},
    {"name": "四宫辉夜", "category": "anime_char", "desc": "《辉夜大小姐》女主，四宫家千金，傲娇学生会长", "aliases": ["四宫辉夜"]},
    {"name": "白银御行", "category": "anime_char", "desc": "《辉夜大小姐》男主，平民出身的学生会长学霸", "aliases": ["白银御行", "白银"]},
    {"name": "藤原千花", "category": "anime_char", "desc": "《辉夜大小姐》书记，天真爱搞事，想当首相", "aliases": ["藤原千花", "千花"]},

    {"name": "五等分的新娘", "category": "anime", "desc": "恋爱喜剧漫画，讲五胞胎姐妹与家庭教师的恋情", "aliases": ["五等分的新娘", "五等分"]},
    {"name": "中野三玖", "category": "anime_char", "desc": "《五等分的新娘》三女，爱战国史，早期人气最高", "aliases": ["中野三玖", "三玖"]},
    {"name": "中野四叶", "category": "anime_char", "desc": "《五等分的新娘》四女，元气运动系，最终赢家", "aliases": ["中野四叶", "四叶"]},

    {"name": "擅长捉弄的高木同学", "category": "anime", "desc": "校园恋爱漫画，讲高木同学总爱捉弄西片", "aliases": ["擅长捉弄的高木同学", "高木同学"]},
    {"name": "西片", "category": "anime_char", "desc": "《擅长捉弄的高木同学》男主，总被高木捉弄", "aliases": ["西片"]},

    {"name": "pop子和pipi美的日常", "category": "anime", "desc": "大川bkub 漫画改编，无厘头搞笑玩梗动画", "aliases": ["pop子和pipi美的日常", "pop子pipi美"]},
    {"name": "pop子", "category": "anime_char", "desc": "动漫里的主角之一，脾气火爆却总在吐槽", "aliases": ["pop子"]},
    {"name": "pipi美", "category": "anime_char", "desc": "动漫里的主角之一，冷静温和的搞笑担当", "aliases": ["pipi美"]},

    {"name": "碧蓝之海", "category": "anime", "desc": "井上坚二漫画，讲大学生潜水部与醉酒爆笑日常", "aliases": ["碧蓝之海"]},
    {"name": "北原伊织", "category": "anime_char", "desc": "《碧蓝之海》主角，被拉进潜水部的新生，酒量惊人", "aliases": ["北原伊织", "伊织"]},

    {"name": "齐木楠雄的灾难", "category": "anime", "desc": "麻生周一搞笑漫画，讲超能力者楠雄的日常烦恼", "aliases": ["齐木楠雄的灾难"]},
    {"name": "齐木楠雄", "category": "anime_char", "desc": "《齐木楠雄的灾难》主角，拥有几乎无所不能的超能力", "aliases": ["齐木楠雄"]},

    {"name": "为美好的世界献上祝福", "category": "anime", "desc": "轻小说改编异世界喜剧，讲宅男转生后组队冒险", "aliases": ["为美好的世界献上祝福", "konosuba"]},
    {"name": "阿库娅", "category": "anime_char", "desc": "《为美好世界献上祝福》水之女神，常被吐槽为废物", "aliases": ["阿库娅", "aqua"]},
    {"name": "惠惠", "category": "anime_char", "desc": "《为美好世界献上祝福》红魔族少女，只会爆裂魔法", "aliases": ["惠惠"]},
    {"name": "达克妮丝", "category": "anime_char", "desc": "《为美好世界献上祝福》女骑士，防御力惊人却爱受虐", "aliases": ["达克妮丝"]},

    {"name": "overlord", "category": "anime", "desc": "讲玩家穿越游戏成为骷髅法师统治异世界的动画", "aliases": ["overlord", "不死者之王"]},
    {"name": "安兹乌尔恭", "category": "anime_char", "desc": "《overlord》主角，公会会长转生后的不死者之王", "aliases": ["安兹乌尔恭", "安兹", "骨傲天"]},
    {"name": "雅儿贝德", "category": "anime_char", "desc": "《overlord》纳萨力克总管，对安兹一心一意忠诚", "aliases": ["雅儿贝德"]},

    {"name": "夏日重现", "category": "anime", "desc": "田中靖规漫画，讲慎平在小岛上对抗影子的循环", "aliases": ["夏日重现", "summertime render"]},
    {"name": "网代慎平", "category": "anime_char", "desc": "《夏日重现》主角，为妹妹之死回到岛上调查", "aliases": ["网代慎平", "慎平"]},

    {"name": "冰雪奇缘", "category": "anime", "desc": "迪士尼动画电影，讲艾莎与安娜姐妹的冰雪奇缘", "aliases": ["冰雪奇缘", "frozen"]},
    {"name": "艾莎", "category": "anime_char", "desc": "《冰雪奇缘》女主，能操控冰雪的女王，人气极高", "aliases": ["艾莎", "elsa"]},

    {"name": "斗罗大陆", "category": "anime", "desc": "唐家三少小说改编国漫，讲唐三修炼武魂的故事", "aliases": ["斗罗大陆"]},
    {"name": "唐三", "category": "anime_char", "desc": "《斗罗大陆》主角，双生武魂，从唐门穿越而来", "aliases": ["唐三"]},
    {"name": "小舞", "category": "anime_char", "desc": "《斗罗大陆》女主，十万年柔骨兔魂兽化形", "aliases": ["小舞"]},

    {"name": "秦时明月", "category": "anime", "desc": "国产武侠动画，讲荆天明在秦末乱世成长的故事", "aliases": ["秦时明月"]},
    {"name": "荆天明", "category": "anime_char", "desc": "《秦时明月》主角，荆轲之子，顽劣又重情义", "aliases": ["荆天明", "天明"]},
    {"name": "盖聂", "category": "anime_char", "desc": "《秦时明月》剑圣，荆天明的监护人，剑术登峰造极", "aliases": ["盖聂"]},

    {"name": "雾山五行", "category": "anime", "desc": "国产水墨风奇幻动画，讲雾山五行封印妖兽", "aliases": ["雾山五行"]},

    {"name": "时光代理人", "category": "anime", "desc": "国产悬疑动画，讲两人进入照片改变他人过去", "aliases": ["时光代理人"]},
    {"name": "程小时", "category": "anime_char", "desc": "《时光代理人》主角，能进入照片操控拍照者", "aliases": ["程小时"]},
    {"name": "陆光", "category": "anime_char", "desc": "《时光代理人》主角，能预见照片后十二小时", "aliases": ["陆光"]},

    {"name": "罗小黑战记", "category": "anime", "desc": "木头执导国产动画，讲妖灵罗小黑的冒险", "aliases": ["罗小黑战记"]},
    {"name": "罗小黑", "category": "anime_char", "desc": "《罗小黑战记》主角，能变身的小黑猫妖灵", "aliases": ["罗小黑"]},

    {"name": "一人之下", "category": "anime", "desc": "米二漫画改编国漫，讲异人世界与炁的修炼", "aliases": ["一人之下"]},
    {"name": "张楚岚", "category": "anime_char", "desc": "《一人之下》主角，炁体源流传人，痞气又机灵", "aliases": ["张楚岚"]},
    {"name": "冯宝宝", "category": "anime_char", "desc": "《一人之下》女主，不老不死，武力值爆表", "aliases": ["冯宝宝"]},

    {"name": "天官赐福", "category": "anime", "desc": "墨香铜臭小说改编国漫，讲谢怜与花城的仙侠情缘", "aliases": ["天官赐福"]},
    {"name": "谢怜", "category": "anime_char", "desc": "《天官赐福》主角，三次飞升的太子，温柔坚韧", "aliases": ["谢怜"]},
    {"name": "花城", "category": "anime_char", "desc": "《天官赐福》男主，鬼王，痴情守护谢怜八百年", "aliases": ["花城"]},

    {"name": "魔道祖师", "category": "anime", "desc": "墨香铜臭小说改编国漫，讲魏无羡重生后查真相", "aliases": ["魔道祖师"]},
    {"name": "魏无羡", "category": "anime_char", "desc": "《魔道祖师》主角，夷陵老祖，乐观不羁的修士", "aliases": ["魏无羡"]},
    {"name": "蓝忘机", "category": "anime_char", "desc": "《魔道祖师》男主，含光君，清冷守规的琴修", "aliases": ["蓝忘机"]},

    {"name": "厨", "category": "anime_term", "desc": "二次元圈里指对某角色作品极度狂热的人，含贬义", "aliases": ["厨"]},
    {"name": "单推", "category": "anime_term", "desc": "只专一喜欢一个角色或偶像，不动摇不花心", "aliases": ["单推"]},
    {"name": "嗑", "category": "anime_term", "desc": "指喜欢把两人凑成一对并享受其互动，嗑 CP", "aliases": ["嗑", "嗑cp"]},
    {"name": "本命", "category": "anime_term", "desc": "指自己最爱、最支持的那个角色或偶像", "aliases": ["本命"]},
    {"name": "圣地", "category": "anime_term", "desc": "指作品取景地或粉丝必去的朝圣场所", "aliases": ["圣地"]},
    {"name": "痛包", "category": "anime_term", "desc": "挂着大量角色徽章挂件的应援包，展示厨力", "aliases": ["痛包"]},
    {"name": "谷子", "category": "anime_term", "desc": "goods 的音译，指动漫周边的徽章立牌等小物", "aliases": ["谷子"]},
    {"name": "手办", "category": "anime_term", "desc": "指以角色为原型制作的收藏用立体模型", "aliases": ["手办"]},
    {"name": "粘土人", "category": "anime_term", "desc": "GSC 出品的 Q 版可动手办系列，俗称黏土人", "aliases": ["粘土人", "黏土人"]},
    {"name": "声优", "category": "anime_term", "desc": "指动画角色的配音演员，日本也叫 CV 声优", "aliases": ["声优", "cv"]},
    {"name": "白学", "category": "anime_term", "desc": "源自白色相簿 2，指研究三角恋站队的戏谑说法", "aliases": ["白学"]},
    {"name": "新番", "category": "anime_term", "desc": "指每季新播出的动画，通常按季度划分", "aliases": ["新番"]},
    {"name": "追番", "category": "anime_term", "desc": "指跟着更新一集一集地看当季动画", "aliases": ["追番"]},
    {"name": "入坑", "category": "anime_term", "desc": "指开始接触并喜欢上某个作品或圈子", "aliases": ["入坑"]},
    {"name": "补番", "category": "anime_term", "desc": "指把以前没看过或错过的旧番补看回来", "aliases": ["补番"]},
    {"name": "完结撒花", "category": "anime_term", "desc": "庆祝一部作品连载或播出完结时刷的弹幕", "aliases": ["完结撒花"]},
    {"name": "催更", "category": "anime_term", "desc": "观众催促作者或UP主尽快更新后续内容的说法", "aliases": ["催更"]},
]
