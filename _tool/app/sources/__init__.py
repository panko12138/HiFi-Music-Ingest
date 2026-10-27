# -*- coding: utf-8 -*-
"""来源适配器注册表。"""
from .base import SourceAdapter
from .musicdl_adapter import MusicdlAdapter
from .manual import ManualAdapter


def get_adapters():
    """返回全部适配器实例。"""
    return [MusicdlAdapter(), ManualAdapter()]


def searchable_adapters():
    return [a for a in get_adapters() if a.searchable]


def resolve(candidate):
    """按候选的 sid 找到负责的适配器并解析直链。"""
    sid = (candidate or {}).get("sid", "")
    for adapter in get_adapters():
        if adapter.handles(sid):
            return adapter.resolve(candidate)
    return None
