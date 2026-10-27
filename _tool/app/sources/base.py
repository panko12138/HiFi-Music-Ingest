# -*- coding: utf-8 -*-
"""来源适配器抽象基类。

契约：
    search(query) -> list[Candidate]      关键词检索（不支持检索的源返回空表）
    resolve(candidate) -> dict | None     把候选解析为可下载信息
                                          {"url","headers","cookies","protocol","ext"}
    handles(sid) -> bool                  是否负责该 sid 的候选
"""


class SourceAdapter:
    name = "base"        # 适配器标识
    label = "基础"        # 中文展示名
    searchable = True    # 是否参与关键词检索

    def search(self, query):
        return []

    def resolve(self, candidate):
        return None

    def handles(self, sid):
        return False

    def available(self):
        """返回 (是否可用, 说明)。"""
        return True, ""
