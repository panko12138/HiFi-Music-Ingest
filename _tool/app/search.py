# -*- coding: utf-8 -*-
"""多源聚合检索：并发调用已启用适配器 → 去重 → 按质量分排序。"""
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, sources

last_errors = []


def search(query):
    """返回候选 dict 列表（已排序，最多 config.MAX_CANDIDATES 条）。"""
    query = (query or "").strip()
    if not query:
        return []
    del last_errors[:]
    adapters = sources.searchable_adapters()
    results = []
    if adapters:
        with ThreadPoolExecutor(max_workers=len(adapters)) as ex:
            futures = {ex.submit(a.search, query): a for a in adapters}
            for fut in as_completed(futures):
                adapter = futures[fut]
                try:
                    results.extend(fut.result() or [])
                except Exception as e:      # noqa: BLE001
                    last_errors.append("%s 检索失败：%s" % (adapter.label, e))
                note = getattr(adapter, "last_note", "")
                if note:
                    last_errors.append(note)

    seen, uniq = set(), []
    for c in results:
        k = c.key()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(c)
    uniq.sort(key=lambda c: c.quality_score, reverse=True)
    return [c.to_dict() for c in uniq[:config.MAX_CANDIDATES]]
