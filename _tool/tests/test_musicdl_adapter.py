# -*- coding: utf-8 -*-
"""musicdl 适配器检索超时分支的特征测试：已完成源的候选不能被丢弃。"""
import time
from concurrent.futures import TimeoutError as FuturesTimeout

from app import config
from app.sources import musicdl_adapter


class _Song:
    episodes = None
    with_valid_download_url = True
    ext = "flac"
    song_name = "歌"
    singers = "手"
    album = "辑"
    file_size_bytes = 1024
    bitrate = 999
    download_url = "https://example.com/a.flac"
    identifier = "id1"
    protocol = "HTTP"
    default_download_headers = {}
    default_download_cookies = {}


class _MusicClient:
    def search(self, keyword):
        return [_Song()]


class _Client:
    music_clients = {"QQMusicClient": _MusicClient(), "KuwoMusicClient": _MusicClient()}


def test_timeout_keeps_candidates_from_completed_sources(monkeypatch):
    monkeypatch.setattr(config, "MUSICDL_SOURCES", ["QQMusicClient", "KuwoMusicClient"])
    monkeypatch.setattr(musicdl_adapter, "_get_client", lambda: _Client())

    def fake_as_completed(fs, timeout=None):
        time.sleep(0.2)            # 让两个源都在超时判定前完成
        raise FuturesTimeout("simulated")
        yield                      # pragma: no cover  —— 使函数成为生成器

    monkeypatch.setattr(musicdl_adapter, "as_completed", fake_as_completed)

    adapter = musicdl_adapter.MusicdlAdapter()
    out = adapter.search("歌")

    assert len(out) == 2
    assert adapter.last_note == ""
