# -*- coding: utf-8 -*-
"""musicdl 引擎封装（主来源）。

- 懒加载 musicdl.MusicClient（musicdl 依赖较重，首次检索时才导入）。
- search() 自行并发派发各源，并设整体墙钟上限：超时的源直接放弃，只返回已完成源的候选，
  避免被单个慢源拖到数十秒。
- search() 把各源 SongInfo 映射为 Candidate，并缓存 SongInfo 供 resolve 回查直链。
- resolve() 返回 {url,headers,cookies,protocol,ext}。
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed, wait, FIRST_COMPLETED

from .. import config
from ..model import Candidate
from .base import SourceAdapter

_lock = threading.Lock()
_patch_lock = threading.Lock()
_client = None
_cache = {}          # "sid::uid" -> SongInfo
_parse_patched = False


def _uid_of(song_info, sid, index):
    ident = getattr(song_info, "identifier", None)
    if ident:
        return str(ident)
    return "idx%d" % index


class _NullLogger:
    """替代 musicdl 默认日志句柄。musicdl 在 disable_print 分支下每次解析失败都以
    追加方式写日志文件，属不必要的磁盘 IO（并发解析时还会互相争用），此处直接丢弃。"""

    @staticmethod
    def debug(message, disable_print=False):
        pass

    @staticmethod
    def info(message, disable_print=False):
        pass

    @staticmethod
    def warning(message, disable_print=False):
        pass

    @staticmethod
    def error(message, disable_print=False):
        pass


def _extract_parser_names(orig):
    """从 musicdl 各源 _parsewiththirdpartapis 的源码中抽取第三方解析器的调用顺序
    （含形如 [...] [:n] 的优先级截断）。"""
    import inspect
    import re
    try:
        src = inspect.getsource(orig)
    except (OSError, TypeError):
        return []
    names = []
    for line in src.splitlines():
        line = line.strip()
        if not re.match(r"^l\d+_parser_funcs\s*=\s*\[", line):
            continue
        body = line.split("[", 1)[1]
        keep = None
        m = re.search(r"\]\s*\[\s*:(\d+)\s*\]", body)
        if m:
            keep = int(m.group(1))
        body = body.split("]", 1)[0]
        line_names = [t.strip()[5:] for t in body.split(",") if t.strip().startswith("self.")]
        if keep is not None:
            line_names = line_names[:keep]
        names.extend(line_names)
    return names


def _install_parallel_parsers(client):
    """把各源 _parsewiththirdpartapis 的串行解析链替换为「滑动窗口并发竞争」版本。

    musicdl 原本对每首歌串行逐个尝试十几个第三方解析接口（每个 timeout=10s），
    单个慢/失效接口即可把整源耗时拖到数十秒，超过检索墙钟上限后整源被丢弃。
    这里仅在「并发方式」上做改动：按原优先级顺序滑动提交，取下标最小的有效结果；
    无有效结果时返回最后一个结果——与原实现完全一致，只是不再被单个慢接口拖累。
    幂等：重复调用只生效一次。
    """
    global _parse_patched
    with _patch_lock:
        if _parse_patched:
            return
        from musicdl.modules.utils.data import SongInfo
        from musicdl.modules.utils import AudioLinkTester
        from musicdl.modules.utils.neteaseutils import DEFAULT_COOKIES as _netease_default_cookies
        window = max(1, int(getattr(config, "MUSICDL_PARSE_WINDOW", 6)))

        def make(orig, names, window):
            def patched(self, search_result, request_overrides=None):
                overrides = request_overrides or {}
                cookies = self.default_cookies or overrides.get("cookies")
                # 用户配置了真实 cookie（网易云内置账号除外）时，行为交给原实现（含其早退语义）
                if cookies and not (self.source == "NeteaseMusicClient" and cookies is _netease_default_cookies):
                    return orig(self, search_result, request_overrides)
                funcs = [getattr(self, n) for n in names if hasattr(self, n)]
                if not funcs:
                    return SongInfo(source=self.source)

                def safe(fn):
                    try:
                        return fn(search_result, request_overrides)
                    except Exception:      # noqa: BLE001
                        return None

                def valid(si):
                    return si is not None and si.with_valid_download_url and si.ext in AudioLinkTester.VALID_AUDIO_EXTS

                completed, nxt, n = {}, 0, len(funcs)
                pool = ThreadPoolExecutor(max_workers=min(window, n))
                try:
                    pending = {}
                    while nxt < n and len(pending) < window:
                        pending[pool.submit(safe, funcs[nxt])] = nxt
                        nxt += 1
                    while pending:
                        done, _ = wait(list(pending), return_when=FIRST_COMPLETED)
                        for fut in done:
                            idx = pending.pop(fut)
                            completed[idx] = fut.result()
                            if nxt < n:
                                pending[pool.submit(safe, funcs[nxt])] = nxt
                                nxt += 1
                        # 比「最小未完成下标」更小的结果都已定局 → 可判定胜者
                        min_pending = min(pending.values()) if pending else n
                        for idx in sorted(k for k in completed if k < min_pending):
                            if valid(completed[idx]):
                                pool.shutdown(wait=False, cancel_futures=True)
                                return completed[idx]
                    last = completed.get(n - 1)
                    return last if last is not None else SongInfo(source=self.source)
                finally:
                    pool.shutdown(wait=False, cancel_futures=True)
            return patched

        for sid in config.MUSICDL_SOURCES:
            cli = client.music_clients.get(sid)
            if cli is None:
                continue
            cls = type(cli)
            orig = getattr(cls, "_parsewiththirdpartapis", None)
            names = _extract_parser_names(orig) if orig else []
            if not names:
                continue
            cls._parsewiththirdpartapis = make(orig, names, window)
        _parse_patched = True


def _get_client():
    """构造（或复用）musicdl 客户端。"""
    global _client
    with _lock:
        if _client is not None:
            return _client
        from musicdl import musicdl  # 延迟导入
        base_cfg = {
            "work_dir": config.MUSICDL_WORK_DIR,
            "search_size_per_source": config.MUSICDL_SEARCH_SIZE,
            "disable_print": True,
            "max_retries": config.MUSICDL_MAX_RETRIES,
            # 复用 HTTP 会话/连接池：避免每次请求重建 Session（解析链并发后收益更明显）
            "maintain_session": True,
        }
        if getattr(config, "MUSICDL_SILENT_LOG", True):
            base_cfg["logger_handle"] = _NullLogger
        cfg = {src: dict(base_cfg) for src in config.MUSICDL_SOURCES}
        _client = musicdl.MusicClient(
            music_sources=list(config.MUSICDL_SOURCES),
            init_music_clients_cfg=cfg,
        )
        _install_parallel_parsers(_client)
        return _client


def _score(song_info, sid):
    """候选质量分：无损 > 码率 > 体积 > 大平台优先。"""
    ext = (song_info.ext or "").lstrip(".").lower()
    score = 0
    if ext in config.LOSSLESS_QUALITY:
        score += 100
    score += min(int(song_info.bitrate or 0), 1000) // 10
    size = int(song_info.file_size_bytes or 0)
    score += min(size, 100 * 1024 * 1024) // (1024 * 1024) if size else -5
    if sid in ("NeteaseMusicClient", "QQMusicClient", "KugouMusicClient",
               "KuwoMusicClient", "MiguMusicClient", "QianqianMusicClient"):
        score += 20
    return score


class MusicdlAdapter(SourceAdapter):
    name = "musicdl"
    label = "musicdl 聚合"
    searchable = True

    def __init__(self):
        # 上一次 search 的补充说明（如「部分来源超时未返回」），供上层提示
        self.last_note = ""

    def handles(self, sid):
        return sid in config.MUSICDL_SOURCES or sid in config.SOURCE_LABELS

    def available(self):
        try:
            import musicdl  # noqa: F401
            return True, "musicdl %s" % getattr(musicdl, "__version__", "")
        except Exception as e:
            return False, "musicdl 不可用：%s" % e

    def _search_source(self, client, sid, query):
        """检索单个源；返回 (sid, [SongInfo], 耗时秒)。"""
        t0 = time.time()
        try:
            items = client.music_clients[sid].search(keyword=query)
        except Exception:      # noqa: BLE001
            items = []
        return sid, items or [], time.time() - t0

    def search(self, query):
        client = _get_client()
        srcs = [s for s in config.MUSICDL_SOURCES if s in client.music_clients]
        results, timed_out = {}, []
        pool = ThreadPoolExecutor(max_workers=len(srcs) or 1)
        try:
            futures = [pool.submit(self._search_source, client, s, query) for s in srcs]
            try:
                for fut in as_completed(futures, timeout=config.MUSICDL_SEARCH_TIMEOUT):
                    sid, items, _dt = fut.result()
                    results[sid] = items
            except FuturesTimeout:
                done = {s for s, _items, _dt in (f.result() for f in futures if f.done())}
                timed_out = [s for s in srcs if s not in done]
        finally:
            pool.shutdown(wait=False)   # 未完成的源后台自然结束，不再等待

        self.last_note = ""
        if timed_out:
            labels = "、".join(config.SOURCE_LABELS.get(s, s) for s in timed_out)
            self.last_note = "%s 响应超时（>%ds），本次未纳入候选" % (labels, config.MUSICDL_SEARCH_TIMEOUT)

        out = []
        for sid, items in results.items():
            for index, song_info in enumerate(items or []):
                try:
                    if getattr(song_info, "episodes", None):
                        continue  # 跳过 FM/播客聚合条目
                    if not song_info.with_valid_download_url:
                        continue
                except Exception:
                    continue
                ext = (song_info.ext or "").lstrip(".").lower()
                uid = _uid_of(song_info, sid, index)
                _cache["%s::%s" % (sid, uid)] = song_info
                note = "无损" if ext in config.LOSSLESS_QUALITY else "有损"
                if ext in ("mflac", "mgg", "ncm", "kgm", "qmc"):
                    note = "疑似加密"
                out.append(Candidate(
                    source=config.SOURCE_LABELS.get(sid, sid),
                    sid=sid, uid=uid,
                    title=song_info.song_name or "",
                    artist=song_info.singers or "",
                    album=song_info.album or "",
                    format=ext,
                    size=int(song_info.file_size_bytes or 0),
                    bitrate=int(song_info.bitrate or 0),
                    url=song_info.download_url if isinstance(song_info.download_url, str) else "",
                    note=note,
                    quality_score=_score(song_info, sid),
                ))
        return out

    def resolve(self, candidate):
        song_info = _cache.get("%s::%s" % (candidate.get("sid"), candidate.get("uid")))
        if song_info is None:
            return None
        url = song_info.download_url if isinstance(song_info.download_url, str) else ""
        if not url:
            return None
        return {
            "url": url,
            "headers": dict(song_info.default_download_headers or {}),
            "cookies": dict(song_info.default_download_cookies or {}),
            "protocol": (song_info.protocol or "HTTP").upper(),
            "ext": (song_info.ext or "").lstrip(".").lower(),
        }
