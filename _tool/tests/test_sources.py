# -*- coding: utf-8 -*-
"""来源适配器分发的特征测试：手动/本地来源必须由 ManualAdapter 处理。"""
from app import sources
from app.sources.musicdl_adapter import MusicdlAdapter


def test_manual_direct_link_resolves_through_manual_adapter():
    candidate = {"sid": "ManualSource", "url": "https://example.com/a.flac", "format": "flac"}

    info = sources.resolve(candidate)

    assert info and info["url"] == candidate["url"]


def test_musicdl_adapter_does_not_claim_manual_and_local_sids():
    adapter = MusicdlAdapter()

    assert not adapter.handles("ManualSource")
    assert not adapter.handles("LocalFile")
    assert adapter.handles("QQMusicClient")
