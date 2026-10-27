# -*- coding: utf-8 -*-
"""数据类：Candidate（检索候选）/ Task（队列任务）/ Result（入库结果）。"""
from dataclasses import dataclass, field, asdict, fields


@dataclass
class Candidate:
    """一个可下载的候选（来自某个来源适配器）。"""
    source: str = ""          # 来源站（中文展示名，如 网易云 / QQ音乐）
    sid: str = ""             # 来源站原始标识（musicdl client 类名 / ManualSource / LocalFile）
    uid: str = ""             # 来源内唯一标识（用于 resolve 回查直链）
    title: str = ""           # 歌名
    artist: str = ""          # 歌手
    album: str = ""           # 专辑
    format: str = ""          # flac / wav / mp3 等
    size: int = 0             # 字节（未知为 0）
    bitrate: int = 0          # 码率 kbps（未知为 0）
    bit_depth: int = 0        # 位深（未知为 0）
    url: str = ""             # 下载直链（可能为空，由 resolve 补）
    note: str = ""            # 附加说明（如“无损/需VIP/疑似加密”）
    quality_score: int = 0    # 质量分，用于排序

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in names})

    def key(self):
        """用于去重的唯一键。"""
        return (self.source, self.title, self.artist, self.format)


@dataclass
class Task:
    """下载/入库队列中的一个任务。"""
    id: str = ""
    query: str = ""
    candidate: dict = field(default_factory=dict)   # 选中的 Candidate（dict）
    meta: dict = field(default_factory=dict)        # 选定的元数据
    status: str = "pending"   # pending/running/paused/done/failed/skipped/canceled
    percent: float = 0.0
    speed: str = ""           # 人类可读速度
    msg: str = ""
    path: str = ""
    created: float = 0.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in names})


@dataclass
class Result:
    """一次入库的逐首结果（用于日志展示）。"""
    song: str = ""       # 「歌手 - 歌名」
    status: str = ""     # 成功/失败/重复/跳过
    reason: str = ""
    path: str = ""
    time: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in names})
