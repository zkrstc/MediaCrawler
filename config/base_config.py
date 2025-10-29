# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

# 基础配置
PLATFORM = "xhs"  # 平台，xhs | dy | ks | bili | wb | tieba | zhihu
KEYWORDS = "纸尿裤推荐,纸尿裤避雷,babycare airpro,babycare狮子王国,babycare山茶花,babycare纸尿裤"  # 关键词搜索配置，以英文逗号分隔
LOGIN_TYPE = "qrcode"  # qrcode or phone or cookie
COOKIES = ""
CRAWLER_TYPE = (
    "search"  # 爬取类型，search(关键词搜索) | detail(帖子详情)| creator(创作者主页数据)
)
# 是否开启 IP 代理（需要购买代理服务才能使用）
# 注意：IP代理只在出错时切换，不会主动轮换
ENABLE_IP_PROXY = False
# 代理IP池数量
IP_PROXY_POOL_COUNT = 2

# 代理IP提供商名称
IP_PROXY_PROVIDER_NAME = "kuaidaili"  # kuaidaili | wandouhttp

# 设置为True不会打开浏览器（无头浏览器）
# 设置False会打开一个浏览器
# 小红书如果一直扫码登录不通过，打开浏览器手动过一下滑动验证码
# 抖音如果一直提示失败，打开浏览器看下是否扫码登录之后出现了手机号验证，如果出现了手动过一下再试。
HEADLESS = False  # 已设置为False，可以看到浏览器

# 是否保存登录状态
SAVE_LOGIN_STATE = True

# ==================== CDP (Chrome DevTools Protocol) 配置 ====================
# 是否启用CDP模式 - 使用用户现有的Chrome/Edge浏览器进行爬取，提供更好的反检测能力
# 启用后将自动检测并启动用户的Chrome/Edge浏览器，通过CDP协议进行控制
# 这种方式使用真实的浏览器环境，包括用户的扩展、Cookie和设置，大大降低被检测的风险
# 建议：如果频繁遇到验证码，可以尝试开启CDP模式
ENABLE_CDP_MODE = False  # 可选：改为True启用CDP模式

# CDP调试端口，用于与浏览器通信
# 如果端口被占用，系统会自动尝试下一个可用端口
CDP_DEBUG_PORT = 9222

# 自定义浏览器路径（可选）
# 如果为空，系统会自动检测Chrome/Edge的安装路径
# Windows示例: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
# macOS示例: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CUSTOM_BROWSER_PATH = ""

# CDP模式下是否启用无头模式
# 注意：即使设置为True，某些反检测功能在无头模式下可能效果不佳
CDP_HEADLESS = False

# 浏览器启动超时时间（秒）
BROWSER_LAUNCH_TIMEOUT = 30

# 是否在程序结束时自动关闭浏览器
# 设置为False可以保持浏览器运行，便于调试
AUTO_CLOSE_BROWSER = True

# 数据保存类型选项配置,支持四种类型：csv、db、json、sqlite, 最好保存到DB，有排重的功能。
SAVE_DATA_OPTION = "csv"  # csv or db or json or sqlite

# 用户浏览器缓存的浏览器文件配置
USER_DATA_DIR = "%s_user_data_dir"  # %s will be replaced by platform name

# 爬取开始页数 默认从第一页开始
START_PAGE = 1

# 是否启用断点续爬功能（基于已保存的CSV记录跳过已爬取的内容）
ENABLE_RESUME_CRAWL = True

# 是否自动清理不完整的评论（评论数量 < CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES 的笔记）
# 开启后，启动时会自动删除不完整的评论，并重新爬取和截图
# 建议：设置为False，避免误删有完整截图的评论，让截图完整性检查机制来处理
ENABLE_AUTO_CLEAN_INCOMPLETE_COMMENTS = False

# 爬取视频/帖子的数量控制
CRAWLER_MAX_NOTES_COUNT = 10

# 并发爬虫数量控制
MAX_CONCURRENCY_NUM = 3  # 提升到3个并发，加快爬取速度

# 是否开启爬媒体模式（包含图片或视频资源），默认不开启爬媒体
ENABLE_GET_MEIDAS = False

# 是否开启爬评论模式, 默认开启爬评论
ENABLE_GET_COMMENTS = True

# 是否开启评论截图模式（对一级评论和二级评论进行截图）
ENABLE_GET_COMMENTS_SCREENSHOT = False

# 评论截图配置
# 截图包含的一级评论数量（层数），0表示截取所有加载的评论
# 例如：20表示截取前20条一级评论（及其展开的二级评论）
#      30表示截取前30条一级评论（及其展开的二级评论）
SCREENSHOT_COMMENTS_COUNT = 20  # 可以设置为10、20、30或其他数值

# 爬取一级评论的数量控制(单视频/帖子)
CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = 20

# 是否开启爬二级评论模式, 默认不开启爬二级评论
# 老版本项目使用了 db, 则需参考 schema/tables.sql line 287 增加表字段
ENABLE_GET_SUB_COMMENTS = True

# 爬取二级评论的数量控制(单个一级评论下)
# 0 表示不限制，会爬取所有二级评论
# 注意：小红书第一次点击"展开回复"的规则是：
#   - 如果二级评论总数 > 6条，会显示 6条（原本1条 + 新显示5条）
#   - 如果二级评论总数 ≤ 6条，会显示全部
# 因此设置为6可以获取"第一次点击展开"后的所有评论
CRAWLER_MAX_SUB_COMMENTS_COUNT_PER_COMMENT = 6

# 词云相关
# 是否开启生成评论词云图
ENABLE_GET_WORDCLOUD = False
# 自定义词语及其分组
# 添加规则：xx:yy 其中xx为自定义添加的词组，yy为将xx该词组分到的组名。
CUSTOM_WORDS = {
    "零几": "年份",  # 将"零几"识别为一个整体
    "高频词": "专业术语",  # 示例自定义词
}

# 停用(禁用)词文件路径
STOP_WORDS_FILE = "./docs/hit_stopwords.txt"

# 中文字体文件路径
FONT_PATH = "./docs/STZHONGS.TTF"

# 爬取间隔时间（建议15-20秒，避免触发验证码）
# 如果频繁出现验证码，可以增加到25-30秒
CRAWLER_MAX_SLEEP_SEC = 5  # 降低到5秒，配合并发提升速度

# Cookie自动刷新配置
# 是否启用Cookie自动刷新（防止长时间运行时Cookie过期）
ENABLE_COOKIE_AUTO_REFRESH = True
# Cookie刷新间隔时间（秒），默认30分钟
COOKIE_REFRESH_INTERVAL = 1800

# Cookie池配置（用于处理Cookie被封的情况）
# 是否启用Cookie池（多账号轮换）
ENABLE_COOKIE_POOL = False
# Cookie池最大失败次数，超过后标记为无效
COOKIE_POOL_MAX_FAIL_COUNT = 3
# 是否启用Cookie自动切换（检测到封禁时自动切换）
ENABLE_COOKIE_AUTO_SWITCH = True

# Cookie和IP轮换配置（主动轮换，充分利用资源）
# Cookie轮换间隔（每爬取多少个笔记后轮换Cookie）
# 建议：2个Cookie配置为5-10，让每个Cookie使用一段时间
COOKIE_ROTATION_INTERVAL = 8  # 每8个笔记轮换一次Cookie

# IP轮换间隔（每爬取多少个笔记后轮换IP）
# 建议：3个IP配置为2-3，频繁轮换降低风险
IP_ROTATION_INTERVAL = 2  # 每2个笔记轮换一次IP

from .bilibili_config import *
from .xhs_config import *
from .dy_config import *
from .ks_config import *
from .weibo_config import *
from .tieba_config import *
from .zhihu_config import *

