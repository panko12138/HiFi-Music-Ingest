# -*- coding: utf-8 -*-
"""手动兜底源：直链 / 本地文件。

当 musicdl 的站点失效时，用户仍可通过本源完成入库：
    - 粘贴直链（http/https）→ 生成候选 → 走下载+入库
    - 选择本地文件 → 跳过下载，直接入库
"""
import os
import re

from .. import config
from ..model import Candidate
from .base import SourceAdapter

_SPLIT_RE = re.compile(r"\s*[-–—]\s*")


def from_url(url):
    """由直链生成候选。"""
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    clean = url.split("?", 1)[0].split("#", 1)[0]
    ext = os.path.splitext(clean)[1].lstrip(".").lower()
    return Candidate(
        source=config.SOURCE_LABELS.get("ManualSource", "手动"),
        sid="ManualSource", uid=url, title="", artist="", album="",
        format=ext, url=url, note="手动直链",
        quality_score=0,
    )


def from_local(path):
    """由本地文件生成候选（跳过下载）。

    文件名若为「歌手 - 歌名」，则解析出歌手/歌名，便于入库去重与命名。
    """
    path = os.path.abspath(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    parts = _SPLIT_RE.split(stem, 1)
    if len(parts) == 2:
        artist, title = parts[0].strip(), parts[1].strip()
    else:
        artist, title = "", stem.strip()
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    return Candidate(
        source=config.SOURCE_LABELS.get("LocalFile", "本地"),
        sid="LocalFile", uid=path,
        title=title, artist=artist, album="", format=ext, url="", note="本地文件",
        quality_score=0,
    )


class ManualAdapter(SourceAdapter):
    name = "manual"
    label = "手动"
    searchable = False

    def handles(self, sid):
        return sid in ("ManualSource", "LocalFile")

    def resolve(self, candidate):
        if candidate.get("sid") == "LocalFile":
            return None  # 本地文件无需下载，由队列直接入库
        url = candidate.get("url")
        if not url:
            return None
        return {
            "url": url, "headers": {}, "cookies": {},
            "protocol": "HTTP", "ext": candidate.get("format") or "",
        }
