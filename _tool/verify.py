# -*- coding: utf-8 -*-
"""全库一致性校验（CLI）。

用法：
    python _tool/verify.py

以 `_work/_整理清单.csv` 为权威基准，校验：
    - 文件是否存在、大小是否一致
    - 命名规范 `歌手 - 歌名.ext`、目录规范 `歌手/专辑/`
    - 音频标签（INFO/ID3 或 FLAC Vorbis）与清单是否一致
    - 封面：音频内嵌封面 + 专辑目录 cover.jpg / folder.jpg
并报告库中不在清单内的多余文件。
"""
import csv
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from app import config, tags

errors = []
warnings = []


def _eq(a, b):
    """空值归一化比较：None 与 "" 视为相等（新入库曲目可能缺年份/流派）。"""
    return (a or "") == (b or "")


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def split_track(s):
    """'01/12' -> (1, 12)；'01' -> (1, None)"""
    s = (s or "").strip()
    if not s:
        return None, None
    if "/" in s:
        a, b = s.split("/", 1)
        return int(a), int(b)
    return int(s), None


def load_rows():
    with open(config.LIST_FILE, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def run():
    """执行校验，返回 (errors, warnings, 清单条数)。"""
    del errors[:]
    del warnings[:]
    rows = load_rows()
    listed = set()

    for i, r in enumerate(rows, start=2):  # 第 2 行起是数据
        artist = (r.get("歌手") or "").strip()
        album = (r.get("专辑") or "").strip()
        song = (r.get("歌名") or "").strip()
        genre = (r.get("流派") or "").strip()
        year = (r.get("年份") or "").strip()
        rel = (r.get("新路径") or "").strip()
        want_size = (r.get("新大小") or "").strip()
        track, total = split_track(r.get("曲序"))

        if not rel:
            err("第%d行 缺少 新路径：%s - %s" % (i, artist, song))
            continue
        listed.add(rel.replace("/", "\\").lower())

        path = os.path.join(config.LIBRARY_ROOT, rel)
        if not os.path.isfile(path):
            err("第%d行 文件缺失：%s" % (i, rel))
            continue

        # 目录 / 命名（以清单「新路径」为基准；「专辑」字段可能为半角?，与全角？目录不符）
        rel_norm = os.path.normpath(rel)
        want_dir = os.path.dirname(rel_norm)
        got_dir = os.path.relpath(os.path.dirname(path), config.LIBRARY_ROOT)
        if got_dir != want_dir:
            err("目录不符：期望 %s 实为 %s" % (want_dir, got_dir))
        want_name = os.path.basename(rel_norm)
        if os.path.basename(path) != want_name:
            err("命名不符：期望 %s 实为 %s" % (want_name, os.path.basename(path)))
        ext = os.path.splitext(path)[1].lower()

        # 大小：清单口径与当前不一致（历史遗留），仅在文件变小（疑似截断）时报错
        if want_size and want_size.isdigit():
            real = os.path.getsize(path)
            if real < int(want_size):
                err("文件小于清单（疑似截断）：%s（清单 %s 实际 %d）"
                    % (rel, want_size, real))

        # 标签 + 封面
        try:
            rb = tags.read_back(path)
        except Exception as e:
            err("读取标签失败：%s（%s）" % (rel, e))
            continue

        if ext == ".wav":
            info = rb["info"]
            id3 = rb["id3"]
            checks = [
                ("INAM/TIT2 歌名", info.get("INAM"), id3.get("TIT2"), song),
                ("IART/TPE1 歌手", info.get("IART"), id3.get("TPE1"), artist),
                ("IPRD/TALB 专辑", info.get("IPRD"), id3.get("TALB"), album),
                ("ICRD/TYER 年份", info.get("ICRD"), id3.get("TYER"), year),
                ("IGNR/TCON 流派", info.get("IGNR"), id3.get("TCON"), genre),
            ]
            for label, a, b, want in checks:
                if not _eq(a, want) or not _eq(b, want):
                    err("标签 %s 不符：INFO=%r ID3=%r 应为 %r（%s）"
                        % (label, a, b, want, rel))
            if track is not None and not _eq(info.get("ITRK"), "%02d" % track):
                err("INFO曲序不符：%r 应为 %02d（%s）" % (info.get("ITRK"), track, rel))
            if track is not None:
                want_trck = "%02d/%02d" % (track, total) if total else "%02d" % track
                if not _eq(id3.get("TRCK"), want_trck):
                    err("ID3曲序不符：%r 应为 %s（%s）" % (id3.get("TRCK"), want_trck, rel))
            if not rb["cover_bytes"]:
                warn("缺少内嵌封面（ID3 APIC）：%s" % rel)
        else:  # flac
            t = rb["tags"]
            checks = [
                ("title 歌名", "title", song), ("artist 歌手", "artist", artist),
                ("album 专辑", "album", album), ("date 年份", "date", year),
                ("genre 流派", "genre", genre),
            ]
            for label, key, want in checks:
                if not _eq(t.get(key), want):
                    err("标签 %s 不符：%r 应为 %r（%s）" % (label, t.get(key), want, rel))
            if track is not None and not _eq(t.get("tracknumber"), "%02d" % track):
                err("曲序不符：%r 应为 %02d（%s）" % (t.get("tracknumber"), track, rel))
            if total is not None and not _eq(t.get("tracktotal"), "%02d" % total):
                warn("曲目总数不符：%r 应为 %02d（%s）"
                     % (t.get("tracktotal"), total, rel))
            if not rb["cover_count"]:
                warn("缺少内嵌封面：%s" % rel)

        # 目录封面文件
        adir = os.path.dirname(path)
        for fn in ("cover.jpg", "folder.jpg"):
            if not os.path.isfile(os.path.join(adir, fn)):
                warn("缺少 %s：%s" % (fn, os.path.relpath(adir, config.LIBRARY_ROOT)))

    # 多余音频文件
    for p in glob.glob(os.path.join(config.LIBRARY_ROOT, "**", "*.wav"),
                       recursive=True) + \
             glob.glob(os.path.join(config.LIBRARY_ROOT, "**", "*.flac"),
                       recursive=True):
        rel = os.path.relpath(p, config.LIBRARY_ROOT).lower()
        if "_work" in rel.split(os.sep):
            continue
        if rel not in listed:
            warn("多余文件（不在清单中）：%s" % rel)

    return errors, warnings, len(rows)


def main():
    errs, warns, total = run()
    print("=" * 56)
    print("清单记录：%d 条" % total)
    print("错误：%d    警告：%d" % (len(errs), len(warns)))
    print("=" * 56)
    for m in errs:
        print("[错误] " + m)
    for m in warns:
        print("[警告] " + m)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
