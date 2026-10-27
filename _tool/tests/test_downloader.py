# -*- coding: utf-8 -*-
"""下载器的特征测试：Range 续传、服务器不支持续传时重下、取消、重试。"""
import pytest

from app import downloader

CONTENT = bytes(range(256)) * 8  # 2048 字节，便于分片校验


def test_download_writes_full_content(tmp_path, http_server):
    _srv, url = http_server(CONTENT)
    dest = tmp_path / "a.wav"

    downloader.download(url, str(dest))

    assert dest.read_bytes() == CONTENT


def test_download_resumes_with_range(tmp_path, http_server):
    srv, url = http_server(CONTENT, support_range=True)
    dest = tmp_path / "b.wav"
    dest.write_bytes(CONTENT[:900])

    downloader.download(url, str(dest))

    assert srv.ranges == ["bytes=900-"]
    assert dest.read_bytes() == CONTENT


def test_download_restarts_when_server_ignores_range(tmp_path, http_server):
    _srv, url = http_server(CONTENT, support_range=False)
    dest = tmp_path / "c.wav"
    dest.write_bytes(b"\x00" * 900)

    downloader.download(url, str(dest))

    assert dest.read_bytes() == CONTENT  # 200 响应 → 清空重写，不能追加出重复内容


def test_download_cancel_raises_and_keeps_partial(tmp_path, http_server):
    _srv, url = http_server(CONTENT)
    dest = tmp_path / "d.wav"

    with pytest.raises(downloader.DownloadCanceled):
        downloader.download(url, str(dest), cancel=lambda: True)

    assert dest.exists() and dest.stat().st_size < len(CONTENT)


def test_download_retries_then_succeeds(tmp_path, http_server):
    srv, url = http_server(CONTENT, fail_first=2)
    dest = tmp_path / "e.wav"

    downloader.download(url, str(dest), retry=3)

    assert srv.requests == 3
    assert dest.read_bytes() == CONTENT


def test_download_raises_after_retries_exhausted(tmp_path, http_server):
    srv, url = http_server(CONTENT, fail_first=5)
    dest = tmp_path / "f.wav"

    with pytest.raises(downloader.DownloadError):
        downloader.download(url, str(dest), retry=2)

    assert srv.requests == 2


def test_referer_only_added_for_known_hosts():
    assert downloader._fallback_referer("https://m801.music.126.net/x.mp3") == "https://music.163.com/"
    assert downloader._fallback_referer("https://example.com/x.mp3") is None
    headers = downloader._with_referer("https://example.com/x.mp3", {})
    assert "Referer" not in headers
    headers = downloader._with_referer("https://m801.music.126.net/x.mp3", {"referer": "custom"})
    assert headers["referer"] == "custom" and "Referer" not in headers
