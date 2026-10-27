# -*- coding: utf-8 -*-
"""批量：解析 txt/csv（每行「歌手 - 歌名」）→ 逐条检索并入队。

单条失败（无候选/链接失效）不影响其余条目。
音乐源对模糊关键词会返回无关结果，故入队前做「候选 vs 输入」相似度校验：
歌名需强匹配、歌手需匹配；不通过则记为「失败」，不下载。
"""
import csv
import difflib
import re

from . import config, search
from .model import Result

_HEADER_RE = re.compile(r"^(歌手|artist|song|歌曲)\b", re.I)
_ILLEGAL = re.compile(r"[\s\-_/（()）\[\]【】,，.。!！?？]+")
_SPLIT_RE = re.compile(r"\s*[-–—]\s*")


def _norm(s):
    return _ILLEGAL.sub("", (s or "").lower())


def _ratio(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _split(query):
    """把「歌手 - 歌名」拆成 (歌手, 歌名)；无分隔符时歌手为空。"""
    parts = _SPLIT_RE.split(query, 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", query.strip()


def _matches(query, cand):
    """候选是否与输入匹配。返回 (bool, 原因)。"""
    want_artist, want_title = _split(query)
    c_title, c_artist = _norm(cand.get("title")), _norm(cand.get("artist"))
    want_title_n = _norm(want_title)
    if not want_title_n:
        return False, "输入为空"
    title_ok = (want_title_n in c_title or c_title in want_title_n or
                _ratio(want_title, c_title) >= config.BATCH_TITLE_SIM)
    if not title_ok:
        return False, "歌名不匹配"
    if not want_artist:
        return True, ""
    if _ratio(want_artist, c_artist) < config.BATCH_ARTIST_SIM:
        return False, "歌手不匹配"
    return True, ""


def parse(content):
    """把上传内容解析为「歌手 - 歌名」查询列表。"""
    queries = []
    for raw in (content or "").splitlines():
        line = raw.strip()
        if not line or _HEADER_RE.match(line):
            continue
        if "," in line or "\t" in line:
            cells = next(csv.reader([line.replace("\t", ",")]))
            cells = [c.strip() for c in cells if c.strip()]
            if len(cells) >= 2:
                line = "%s - %s" % (cells[0], cells[1])
            elif cells:
                line = cells[0]
        queries.append(line)
    return queries


def run(content, manager, only_lossless=True):
    """逐条检索并入队，返回 task_id 列表。"""
    task_ids = []
    for query in parse(content):
        pick, reason = None, "未找到匹配的无损候选"
        try:
            for c in search.search(query):
                if only_lossless and c.get("format") not in ("flac", "wav"):
                    continue
                ok, why = _matches(query, c)
                if ok:
                    pick = c
                    break
                reason = "候选「%s - %s」与输入不匹配（%s）" % (
                    c.get("artist") or "", c.get("title") or "", why)
        except Exception:      # noqa: BLE001
            pick, reason = None, "检索失败"
        if pick:
            task_ids.append(manager.add(query, pick))
        else:
            task_id = manager.add(query, {}, auto_start=False)
            manager._update(task_id, status="failed", msg=reason)
            manager.emit(Result(song=query, status="失败", reason=reason))
            task_ids.append(task_id)
    return task_ids
