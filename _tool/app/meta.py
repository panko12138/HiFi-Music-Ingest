# -*- coding: utf-8 -*-
"""QQ 音乐元数据匹配 + 封面获取（非阻断：任何失败都降级为缺省值）。"""
import difflib
import os
import re

import requests

from . import config

_ILLEGAL_ESCAPE = re.compile(r"[\s\-_/（()）\[\]【】,，.。!！?？]+")


def _norm(s):
    return _ILLEGAL_ESCAPE.sub("", (s or "").lower())


def _similarity(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _fetch_song_list(keyword):
    """调 QQ 音乐搜索接口，返回 song.list（失败抛异常）。"""
    params = {"p": 1, "n": config.QQ_CANDIDATE_LIMIT, "w": keyword,
              "format": "json", "new_json": 1}
    headers = {"Referer": config.QQ_REFERER, "User-Agent": config.USER_AGENT}
    last_err = None
    for _ in range(max(config.RETRY, 1)):
        try:
            r = requests.get(config.QQ_SEARCH_URL, params=params,
                             headers=headers, timeout=config.TIMEOUT)
            r.raise_for_status()
            data = r.json()
            return ((data.get("data") or {}).get("song") or {}).get("list") or []
        except Exception as e:      # noqa: BLE001
            last_err = e
    raise last_err


def _pick_best(song_list, title, artist):
    best, best_score = None, -1.0
    for item in song_list:
        name = item.get("title") or item.get("name") or ""
        singers = item.get("singer") or []
        singer_name = "、".join(s.get("name", "") for s in singers if s.get("name"))
        album = (item.get("album") or {})
        album_name = album.get("name") or album.get("title") or ""
        score = _similarity(name, title) * 60 + _similarity(singer_name, artist) * 35
        if _norm(name) == _norm(title):
            score += 20
        if _norm(singer_name) == _norm(artist):
            score += 10
        if score > best_score:
            best, best_score = item, score
    return best, best_score


def _download_cover(album_mid):
    """下载封面到缓存目录，返回本地路径（失败返回 ""）。"""
    if not album_mid:
        return ""
    os.makedirs(config.COVER_CACHE_DIR, exist_ok=True)
    path = os.path.join(config.COVER_CACHE_DIR, "%s.jpg" % album_mid)
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path
    url = config.QQ_COVER_URL.format(album_mid=album_mid)
    headers = {"Referer": config.QQ_REFERER, "User-Agent": config.USER_AGENT}
    try:
        r = requests.get(url, headers=headers, timeout=config.TIMEOUT)
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)
        return path
    except Exception:      # noqa: BLE001
        return ""


def match(title, artist=""):
    """按歌名/歌手匹配 QQ 元数据。

    返回 dict：title/artist/album/year/genre/tracknumber/tracktotal/
             album_mid/cover_path/score。任何失败均降级返回缺省。
    """
    fallback = {
        "title": title or "", "artist": artist or "", "album": "",
        "year": "", "genre": "", "tracknumber": 0, "tracktotal": 0,
        "album_mid": "", "cover_path": "", "score": 0,
    }
    if not title:
        return fallback
    try:
        song_list = _fetch_song_list("%s %s" % (artist, title) if artist else title)
        if not song_list:
            song_list = _fetch_song_list(title)
        best, score = _pick_best(song_list, title, artist)
    except Exception:      # noqa: BLE001
        return fallback
    if not best or score < 45:
        return fallback

    meta = dict(fallback)
    meta["score"] = round(score, 1)
    meta["title"] = best.get("title") or best.get("name") or title
    singers = best.get("singer") or []
    meta["artist"] = "、".join(s.get("name", "") for s in singers if s.get("name")) or artist
    album = (best.get("album") or {})
    meta["album"] = album.get("name") or album.get("title") or ""
    meta["album_mid"] = album.get("mid") or ""
    meta["cover_path"] = _download_cover(meta["album_mid"])
    return meta
