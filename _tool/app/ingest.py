# -*- coding: utf-8 -*-
"""入库：去重 → 构建路径 → 写标签 + 嵌封面 → 补唱片封面 → 追加清单。

目录/命名规范：`歌手/专辑/歌手 - 歌名.flac|wav`
仅接受无损扩展名；加密格式与有损格式一律拒绝（不改名、不转码）。
"""
import csv
import os
import shutil

from . import config, tags
from .model import Result

# 非法字符 → 全角（与既有曲库约定一致，如 `？` 全角）
_ILLEGAL_MAP = {"\\": "＼", "/": "／", ":": "：", "*": "＊",
                "?": "？", '"': "＂", "<": "＜", ">": "＞", "|": "｜"}

_LIST_HEADER = ["原文件名", "歌手", "专辑", "歌名", "曲序", "年份", "流派", "新路径", "新大小"]


def sanitize(name):
    name = (name or "").strip()
    for k, v in _ILLEGAL_MAP.items():
        name = name.replace(k, v)
    name = name.rstrip(" .")
    return name or "未知"


def _load_rows():
    if not os.path.isfile(config.LIST_FILE):
        return []
    with open(config.LIST_FILE, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _find_dup(artist, title):
    for r in _load_rows():
        if (r.get("歌手") or "").strip() == artist and (r.get("歌名") or "").strip() == title:
            return r
    return None


def _read_cover_bytes(meta):
    path = meta.get("cover_path") or meta.get("cover")
    if path and os.path.isfile(path):
        with open(path, "rb") as f:
            return f.read()
    return None


def _write_cover_files(album_dir, cover_bytes):
    if not cover_bytes:
        return
    for fn in ("cover.jpg", "folder.jpg"):
        dest = os.path.join(album_dir, fn)
        if not os.path.isfile(dest):
            with open(dest, "wb") as f:
                f.write(cover_bytes)


def _append_list(row):
    os.makedirs(os.path.dirname(config.LIST_FILE), exist_ok=True)
    need_header = not os.path.isfile(config.LIST_FILE)
    with open(config.LIST_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if need_header:
            writer.writerow(_LIST_HEADER)
        writer.writerow([row.get(k, "") for k in _LIST_HEADER])


def ingest(local_path, candidate, meta=None):
    """把已下载/本地的音频文件按规范入库，返回 Result。"""
    candidate = candidate or {}
    meta = meta or {}
    title = sanitize(meta.get("title") or candidate.get("title")
                     or os.path.splitext(os.path.basename(local_path))[0])
    artist = sanitize(meta.get("artist") or candidate.get("artist") or "未知歌手")
    album = sanitize(meta.get("album") or candidate.get("album") or "未知专辑")
    song = "%s - %s" % (artist, title)

    ext = os.path.splitext(local_path)[1].lower()
    if ext in config.ENCRYPTED_EXTS:
        return Result(song=song, status="失败", reason="加密格式 %s，已拒绝（请换源）" % ext)
    if ext not in config.LOSSLESS_EXTS:
        return Result(song=song, status="失败",
                      reason="非无损格式（%s），已拒绝（本工具仅入库 FLAC/WAV）" % (ext or "未知"))

    album_dir = os.path.join(config.LIBRARY_ROOT, artist, album)
    target = os.path.join(album_dir, "%s - %s%s" % (artist, title, ext))
    rel = os.path.relpath(target, config.LIBRARY_ROOT).replace("\\", "/")

    if _find_dup(artist, title) is not None or os.path.isfile(target):
        return Result(song=song, status="重复", reason="库中已存在，已跳过", path=rel)

    os.makedirs(album_dir, exist_ok=True)
    if os.path.abspath(local_path) != os.path.abspath(target):
        shutil.copy2(local_path, target)

    cover_bytes = _read_cover_bytes(meta)
    track = int(meta.get("tracknumber") or 0)
    total = int(meta.get("tracktotal") or 0)
    tag_meta = {
        "title": title, "artist": artist, "album": album,
        "albumartist": meta.get("albumartist") or artist,
        "tracknumber": track, "tracktotal": total,
        "year": meta.get("year") or "", "genre": meta.get("genre") or "",
        "cover_bytes": cover_bytes,
    }
    try:
        tags.write(target, tag_meta)
    except Exception as e:      # noqa: BLE001
        return Result(song=song, status="失败", reason="写标签失败：%s" % e, path=rel)

    _write_cover_files(album_dir, cover_bytes)
    _append_list({
        "原文件名": "%s - %s.%s" % (candidate.get("artist") or artist,
                                    candidate.get("title") or title,
                                    ext.lstrip(".")),
        "歌手": artist, "专辑": album, "歌名": title,
        "曲序": ("%02d/%02d" % (track, total)) if (track and total) else
                ("%02d" % track if track else ""),
        "年份": meta.get("year") or "", "流派": meta.get("genre") or "",
        "新路径": rel, "新大小": os.path.getsize(target),
    })
    return Result(song=song, status="成功", reason="", path=rel)
