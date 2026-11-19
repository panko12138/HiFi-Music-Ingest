# -*- coding: utf-8 -*-
"""入库的特征测试：目录/命名规范、格式准入、去重、清单追加、封面落盘。"""
import csv

from app import config, ingest


def _rows():
    with open(config.LIST_FILE, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _ingest(tmp_path, make_wav, name="src.wav", candidate=None, meta=None):
    src = tmp_path / name
    src.write_bytes(make_wav(b"\x33" * 40))
    return ingest.ingest(
        str(src),
        candidate or {"artist": "周杰伦", "title": "晴天", "format": "wav"},
        meta or {"title": "晴天", "artist": "周杰伦", "album": "叶惠美",
                 "year": "2003", "genre": "华语流行", "tracknumber": 1, "tracktotal": 11},
    )


def test_ingest_writes_expected_path_and_csv(tmp_path, make_wav, library_dir):
    result = _ingest(tmp_path, make_wav)

    assert result.status == "成功"
    target = library_dir / "周杰伦" / "叶惠美" / "周杰伦 - 晴天.wav"
    assert target.is_file() and result.path == "周杰伦/叶惠美/周杰伦 - 晴天.wav"
    rows = _rows()
    assert rows[0]["歌手"] == "周杰伦" and rows[0]["曲序"] == "01/11"
    assert rows[0]["新路径"] == result.path


def test_ingest_rejects_duplicate_without_touching_file(tmp_path, make_wav, library_dir):
    _ingest(tmp_path, make_wav)
    target = library_dir / "周杰伦" / "叶惠美" / "周杰伦 - 晴天.wav"
    before = target.read_bytes()

    again = _ingest(tmp_path, make_wav, name="another.wav")

    assert again.status == "重复"
    assert target.read_bytes() == before
    assert len(_rows()) == 1


def test_ingest_detects_duplicate_from_csv_even_if_file_missing(tmp_path, make_wav, library_dir):
    _ingest(tmp_path, make_wav)
    target = library_dir / "周杰伦" / "叶惠美" / "周杰伦 - 晴天.wav"
    target.unlink()

    result = _ingest(tmp_path, make_wav, name="yet-another.wav")

    assert result.status == "重复"
    assert not target.exists()


def test_ingest_rejects_lossy_and_encrypted(tmp_path, library_dir):
    for name, ext in (("x.mp3", ".mp3"), ("y.mflac", ".mflac")):
        src = tmp_path / name
        src.write_bytes(b"\x00" * 16)
        result = ingest.ingest(str(src), {"artist": "A", "title": "T"}, {})
        assert result.status == "失败"
        assert ext in result.reason


def test_ingest_sanitizes_illegal_chars_in_path(tmp_path, make_wav, library_dir):
    result = _ingest(
        tmp_path, make_wav,
        candidate={"artist": "A/B", "title": "T:C?"},
        meta={"title": "T:C?", "artist": "A/B", "album": "D?E"},
    )

    assert result.status == "成功"
    assert "／" in result.path and "：" in result.path and "？" in result.path
    assert (library_dir / "A／B" / "D？E" / "A／B - T：C？.wav").is_file()


def test_ingest_writes_album_cover_files(tmp_path, make_wav, library_dir):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\xff\xd8" + b"jpeg" * 10)

    _ingest(tmp_path, make_wav, meta={"title": "晴天", "artist": "周杰伦",
                                      "album": "叶惠美", "cover_path": str(cover)})

    album_dir = library_dir / "周杰伦" / "叶惠美"
    assert (album_dir / "cover.jpg").read_bytes() == cover.read_bytes()
    assert (album_dir / "folder.jpg").read_bytes() == cover.read_bytes()


def test_ingest_rolls_back_copied_file_when_tag_write_fails(tmp_path, make_wav, library_dir, monkeypatch):
    def boom(path, meta_):
        raise RuntimeError("坏标签")

    monkeypatch.setattr(ingest.tags, "write", boom)

    result = _ingest(tmp_path, make_wav)

    assert result.status == "失败"
    target = library_dir / "周杰伦" / "叶惠美" / "周杰伦 - 晴天.wav"
    assert not target.exists()


def test_concurrent_ingest_same_song_records_once(tmp_path, make_wav, library_dir):
    from concurrent.futures import ThreadPoolExecutor

    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    a.write_bytes(make_wav(b"\x11" * 16))
    b.write_bytes(make_wav(b"\x22" * 16))
    candidate = {"artist": "周杰伦", "title": "晴天"}
    meta = {"title": "晴天", "artist": "周杰伦", "album": "叶惠美"}

    with ThreadPoolExecutor(max_workers=2) as ex:
        results = list(ex.map(lambda p: ingest.ingest(str(p), candidate, meta), [a, b]))

    assert sorted(r.status for r in results) == ["成功", "重复"]
    assert len(_rows()) == 1
