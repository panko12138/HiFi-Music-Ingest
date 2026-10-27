# -*- coding: utf-8 -*-
"""写标签的特征测试：WAV 音频字节保真、标签可读、重复写入幂等。

这些测试锁定 tags.write 的现有可观察行为，防止后续重构静默破坏用户曲库文件。
"""
import struct

import pytest

from app import tags


def _chunks(data):
    """独立于被测代码的 chunk 解析，避免「用被测实现验证被测实现」。"""
    pos, out = 12, []
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        out.append((cid, data[pos + 8:pos + 8 + size]))
        pos += 8 + size + (size & 1)
    return out


def _audio(data):
    return [body for cid, body in _chunks(data) if cid == b"data"][0]


META = {
    "title": "测试歌名",
    "artist": "测试歌手",
    "album": "测试专辑",
    "albumartist": "测试歌手",
    "tracknumber": 3,
    "tracktotal": 12,
    "year": "2020",
    "genre": "华语流行",
}


def test_write_wav_preserves_audio_bytes_and_aligns_chunks(tmp_path, make_wav):
    audio = bytes(range(101))  # 奇数字节：必须保留对齐补位，否则后续 chunk 错位
    path = tmp_path / "a.wav"
    path.write_bytes(make_wav(audio, extra_chunks=[(b"JUNK", b"oddbod")]))

    tags.write_wav(str(path), META)

    data = path.read_bytes()
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    assert struct.unpack("<I", data[4:8])[0] == len(data) - 8
    assert _audio(data) == audio
    ids = [cid for cid, _ in _chunks(data)]
    assert b"fmt " in ids and b"JUNK" in ids
    assert ids.count(b"LIST") == 1 and ids.count(b"id3 ") == 1


def test_write_wav_replaces_existing_list_and_id3(tmp_path, make_wav):
    path = tmp_path / "b.wav"
    path.write_bytes(make_wav(
        b"\x00" * 20,
        extra_chunks=[(b"LIST", b"INFOXXXX"), (b"id3 ", b"old-tag")],
    ))

    tags.write_wav(str(path), META)

    assert [cid for cid, _ in _chunks(path.read_bytes())].count(b"LIST") == 1


def test_write_wav_is_idempotent(tmp_path, make_wav):
    path = tmp_path / "c.wav"
    path.write_bytes(make_wav(b"\x11" * 64))

    tags.write_wav(str(path), META)
    first = path.read_bytes()
    tags.write_wav(str(path), META)

    assert path.read_bytes() == first


def test_read_back_matches_written_tags(tmp_path, make_wav):
    path = tmp_path / "d.wav"
    path.write_bytes(make_wav(b"\x22" * 30))

    tags.write_wav(str(path), dict(META, cover_bytes=b"\xff\xd8fakejpeg"))

    rb = tags.read_back(str(path))
    assert rb["info"]["INAM"] == "测试歌名"
    assert rb["info"]["IART"] == "测试歌手"
    assert rb["info"]["ITRK"] == "03"
    assert rb["id3"]["TIT2"] == "测试歌名"
    assert rb["id3"]["TPE1"] == "测试歌手"
    assert rb["id3"]["TRCK"] == "03/12"
    assert rb["cover_bytes"] > 0


def test_write_rejects_unsupported_format(tmp_path):
    path = tmp_path / "e.mp3"
    path.write_bytes(b"\x00" * 8)
    with pytest.raises(ValueError):
        tags.write(str(path), META)
