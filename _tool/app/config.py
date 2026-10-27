# -*- coding: utf-8 -*-
"""应用配置常量（路径 / 并发 / 超时 / 开关）。"""
import os

# 项目根：即「无损」目录（本文件位于 _tool/app/config.py）
TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBRARY_ROOT = os.path.dirname(TOOL_DIR)

WORK_DIR = os.path.join(LIBRARY_ROOT, "_work")
DOWNLOAD_DIR = os.path.join(WORK_DIR, "downloads")
CACHE_DIR = os.path.join(WORK_DIR, "cache")
QQLRC_CACHE_DIR = os.path.join(CACHE_DIR, "qqlrc")
COVER_CACHE_DIR = os.path.join(CACHE_DIR, "cover")
QUEUE_FILE = os.path.join(WORK_DIR, "queue.json")
LOG_FILE = os.path.join(WORK_DIR, "入库日志.jsonl")
LIST_FILE = os.path.join(WORK_DIR, "_整理清单.csv")
COVER_MAP_FILE = os.path.join(WORK_DIR, "cover_map.json")

WEB_DIR = os.path.join(TOOL_DIR, "web")

# 服务
HOST = "127.0.0.1"
PORT = 8756

# 下载
CONCURRENCY = 3            # S-05：下载并发
TIMEOUT = 30               # 单次请求超时（秒）
RETRY = 3                  # S-01：失败重试次数
CHUNK_SIZE = 256 * 1024
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# 功能开关
SPECTRUM_CHECK = False     # S-04：频谱校验（P2，默认关闭）

# QQ 音乐
QQ_SEARCH_URL = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
QQ_COVER_URL = "https://y.gtimg.cn/music/photo_new/T002R800x800M000{album_mid}.jpg"
QQ_REFERER = "https://y.qq.com/"
QQ_CANDIDATE_LIMIT = 30    # 搜索候选条数

# musicdl 默认启用源（musicdl 的 client 类名）
MUSICDL_SOURCES = [
    "NeteaseMusicClient", "QQMusicClient", "KugouMusicClient",
    "KuwoMusicClient", "MiguMusicClient", "QianqianMusicClient",
]
# 每个源返回的候选条数（过大拖慢检索：每多一条都要跑一遍解析链）
MUSICDL_SEARCH_SIZE = 3
# 各源 HTTP 重试次数（1 表示不重试，加快失败源退出）
MUSICDL_MAX_RETRIES = 1
# 单次检索的整体墙钟上限（秒）：超时即放弃未完成的源，只返回已完成源的候选
MUSICDL_SEARCH_TIMEOUT = 20
# musicdl 工作目录（存放其搜索/下载中间产物）
MUSICDL_WORK_DIR = os.path.join(CACHE_DIR, "musicdl")
# 解析链并发「滑动窗口」大小：musicdl 每首歌都要依次尝试多个第三方解析接口（每个 timeout=10s），
# 原实现为串行，单个慢/失效接口即可把整源拖到数十秒。此处改为窗口内并发竞争，
# 仍按原优先级取「首个有效结果」，语义不变、耗时大幅下降。值越大越快、并发请求越多。
MUSICDL_PARSE_WINDOW = 6
# 是否静默 musicdl 的本地日志：其 disable_print 分支会在每次解析失败时以追加方式写日志文件，
# 属不必要的磁盘 IO（并发解析时还会互相争用），生产环境无需保留。
MUSICDL_SILENT_LOG = True

# 来源站中文名（用于界面展示）
SOURCE_LABELS = {
    "NeteaseMusicClient": "网易云",
    "QQMusicClient": "QQ音乐",
    "KugouMusicClient": "酷狗",
    "KuwoMusicClient": "酷我",
    "MiguMusicClient": "咪咕",
    "QianqianMusicClient": "千千",
    "BilibiliMusicClient": "B站",
    "GDStudioMusicClient": "GD音乐台",
    "FiveSongMusicClient": "5Song",
    "GequbaoMusicClient": "歌曲宝",
    "HeishanMusicClient": "黑山",
    "ManualSource": "手动",
    "LocalFile": "本地",
}

# 允许的无损扩展名（加密格式 .mflac/.ncm 一律拒绝）
LOSSLESS_EXTS = (".flac", ".wav")
# musicdl 侧认定的无损扩展名（用于候选打分）
LOSSLESS_QUALITY = ("flac", "wav", "alac", "ape", "wv", "tta", "dsf", "dff")
ENCRYPTED_EXTS = (".mflac", ".mgg", ".ncm", ".kgm", ".vpr", ".qmc")

# 单次检索返回候选上限
MAX_CANDIDATES = 60

# 批量模式：候选与输入的相似度阈值（低于则判为「失败」，避免模糊结果误入库）
BATCH_TITLE_SIM = 0.6
BATCH_ARTIST_SIM = 0.5

GENRES = ("民谣", "华语流行", "粤语流行", "摇滚")
