# -*- coding: utf-8 -*-
"""音频标签读写（核心）。

- FLAC：mutagen 写 Vorbis Comment + 内嵌 JPEG 封面。
- WAV ：自研 RIFF 写入器。保留 `fmt `/`data` 等原有 chunk，仅重建
        `LIST`(INFO 子块，GBK 编码) 与 `id3 ` chunk(ID3v2.3，UTF-16)。
        绝不触碰音频数据。

对外接口：
    write(path, meta)      写标签 + 嵌封面
    read_back(path)        回读校验，返回 dict
"""
import os
import struct

from . import config

# ---------------------------------------------------------------- WAV 低位操作


def _syncsafe(n):
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def _iter_chunks(data):
    """依次产出 (chunk_id, raw_chunk, header_offset)，解析到文件尾。"""
    pos = 12
    n = len(data)
    while pos + 8 <= n:
        cid = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        end = pos + 8 + size
        yield cid, data[pos:end], pos
        pos = end + (size & 1)  # 奇数补 1 字节对齐


def _pack_chunk(cid, body):
    """按 RIFF 规则打包一个 chunk（必要时补对齐字节）。"""
    chunk = cid + struct.pack("<I", len(body)) + body
    if len(body) & 1:
        chunk += b"\x00"
    return chunk


def _info_sub(cid, text):
    # INFO 子块也是 RIFF chunk，需按字对齐（奇数长度补 1 字节）
    return _pack_chunk(cid, str(text).encode("gbk", "replace") + b"\x00")


def _build_list_info(meta):
    subs = b""
    if meta.get("title"):
        subs += _info_sub(b"INAM", meta["title"])
    if meta.get("artist"):
        subs += _info_sub(b"IART", meta["artist"])
    if meta.get("album"):
        subs += _info_sub(b"IPRD", meta["album"])
    if meta.get("tracknumber"):
        subs += _info_sub(b"ITRK", "%02d" % int(meta["tracknumber"]))
    if meta.get("year"):
        subs += _info_sub(b"ICRD", str(meta["year"]))
    if meta.get("genre"):
        subs += _info_sub(b"IGNR", meta["genre"])
    return b"INFO" + subs


def _text_frame(fid, text):
    """ID3v2.3 文本帧：编码 1 = UTF-16(含 BOM)，尾部双 0 终止。"""
    payload = b"\x01" + b"\xff\xfe" + str(text).encode("utf-16-le") + b"\x00\x00"
    return fid + struct.pack(">I", len(payload)) + b"\x00\x00" + payload


def _apic_frame(jpeg):
    """ID3v2.3 APIC 帧（封面，类型 3 = 封面）。"""
    payload = (b"\x01" + b"image/jpeg\x00" + b"\x03" +
               b"\xff\xfe\x00\x00" + jpeg)
    return b"APIC" + struct.pack(">I", len(payload)) + b"\x00\x00" + payload


def _build_id3(meta, cover_bytes):
    frames = b""
    tn = meta.get("tracknumber")
    tt = meta.get("tracktotal")
    if meta.get("title"):
        frames += _text_frame(b"TIT2", meta["title"])
    if meta.get("artist"):
        frames += _text_frame(b"TPE1", meta["artist"])
    if meta.get("album"):
        frames += _text_frame(b"TALB", meta["album"])
    if tn:
        trck = "%02d/%02d" % (int(tn), int(tt)) if tt else "%02d" % int(tn)
        frames += _text_frame(b"TRCK", trck)
    if meta.get("year"):
        frames += _text_frame(b"TYER", str(meta["year"]))
    if meta.get("genre"):
        frames += _text_frame(b"TCON", meta["genre"])
    if meta.get("albumartist"):
        frames += _text_frame(b"TPE2", meta["albumartist"])
    frames += _text_frame(b"TPOS", "1/1")
    if cover_bytes:
        frames += _apic_frame(cover_bytes)
    header = b"ID3" + b"\x03\x00" + b"\x00" + _syncsafe(len(frames))
    return header + frames


# ---------------------------------------------------------------- 公开接口


def _read_cover_bytes(meta):
    """从 meta['cover']（路径）或 meta['cover_bytes'] 取得 JPEG 数据。"""
    if meta.get("cover_bytes"):
        return meta["cover_bytes"]
    cp = meta.get("cover")
    if cp and os.path.isfile(cp):
        with open(cp, "rb") as f:
            return f.read()
    return None


def write_wav(path, meta):
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("不是合法的 WAV 文件：%s" % path)

    kept = []           # 保留的原始 chunk（raw）
    for cid, raw, _pos in _iter_chunks(data):
        low = cid.lower()
        if low in (b"list", b"id3 "):
            continue    # 由本次重建
        kept.append(raw)

    cover = _read_cover_bytes(meta)
    chunks = b"".join(kept)
    chunks += _pack_chunk(b"LIST", _build_list_info(meta))
    chunks += _pack_chunk(b"id3 ", _build_id3(meta, cover))

    total = 12 + len(chunks)
    out = b"RIFF" + struct.pack("<I", total - 8) + b"WAVE" + chunks

    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(out)
    os.replace(tmp, path)


def write_flac(path, meta):
    from mutagen.flac import FLAC, Picture

    f = FLAC(path)
    mapping = {
        "title": "title", "artist": "artist", "album": "album",
        "albumartist": "albumartist", "year": "date",
    }
    for src, dst in mapping.items():
        if meta.get(src):
            f[dst] = [str(meta[src])]
    if meta.get("tracknumber"):
        f["tracknumber"] = ["%02d" % int(meta["tracknumber"])]
    if meta.get("tracktotal"):
        f["tracktotal"] = ["%02d" % int(meta["tracktotal"])]
    if meta.get("genre"):
        f["genre"] = [meta["genre"]]

    cover = _read_cover_bytes(meta)
    if cover:
        pic = Picture()
        pic.type = 3
        pic.mime = "image/jpeg"
        pic.desc = "Cover"
        pic.data = cover
        f.clear_pictures()
        f.add_picture(pic)
    f.save()


def write(path, meta):
    """按扩展名分派写入。meta 见模块 docstring。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".wav":
        write_wav(path, meta)
    elif ext == ".flac":
        write_flac(path, meta)
    else:
        raise ValueError("不支持的写入格式：%s" % ext)


# ---------------------------------------------------------------- 回读校验


def read_back_wav(path):
    with open(path, "rb") as f:
        data = f.read()
    info, id3, cover_bytes = {}, {}, 0
    for cid, raw, _pos in _iter_chunks(data):
        low = cid.lower()
        if low == b"list":
            body = raw[8:]
            if body[:4] == b"INFO":
                sp = 4
                while sp + 8 <= len(body):
                    scid = body[sp:sp + 4]
                    ssz = struct.unpack("<I", body[sp + 4:sp + 8])[0]
                    val = body[sp + 8:sp + 8 + ssz].split(b"\x00", 1)[0]
                    try:
                        info[scid.decode("latin-1")] = val.decode("gbk")
                    except UnicodeDecodeError:
                        info[scid.decode("latin-1")] = val.decode("latin-1")
                    sp += 8 + ssz + (ssz & 1)
        elif low == b"id3 ":
            tag = raw[8:]
            size = ((tag[6] & 0x7F) << 21) | ((tag[7] & 0x7F) << 14) | \
                   ((tag[8] & 0x7F) << 7) | (tag[9] & 0x7F)
            body = tag[10:10 + size]
            p = 0
            while p + 10 <= len(body):
                fid = body[p:p + 4]
                if fid[:1] == b"\x00":
                    break
                fsz = struct.unpack(">I", body[p + 4:p + 8])[0]
                payload = body[p + 10:p + 10 + fsz]
                if fid == b"APIC":
                    cover_bytes = fsz
                elif fid[:1] == b"T":
                    enc = payload[:1]
                    txt = payload[1:]
                    try:
                        if enc in (b"\x01", b"\x02"):
                            id3[fid.decode()] = txt.decode("utf-16").rstrip("\x00")
                        elif enc == b"\x03":
                            id3[fid.decode()] = txt.decode("utf-8").rstrip("\x00")
                        else:
                            id3[fid.decode()] = txt.decode("latin-1").rstrip("\x00")
                    except UnicodeDecodeError:
                        id3[fid.decode()] = txt.decode("latin-1", "replace")
                p += 10 + fsz
    return {"info": info, "id3": id3, "cover_bytes": cover_bytes}


def read_back_flac(path):
    from mutagen.flac import FLAC
    f = FLAC(path)
    tags = {k: (v[0] if v else "") for k, v in f.tags.items()}
    return {
        "tags": tags,
        "cover_count": len(f.pictures),
        "cover_bytes": len(f.pictures[0].data) if f.pictures else 0,
    }


def read_back(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".wav":
        return read_back_wav(path)
    if ext == ".flac":
        return read_back_flac(path)
    raise ValueError("不支持的读取格式：%s" % ext)
