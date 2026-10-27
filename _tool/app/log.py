# -*- coding: utf-8 -*-
"""入库日志读写（JSONL）。

每行一条处理结果：{"song","status","reason","path","time"}
"""
import json
import os
import time

from . import config
from .model import Result


def append(result, path=None):
    """追加一条结果。result 可为 Result 或 dict。"""
    record = result.to_dict() if isinstance(result, Result) else dict(result)
    if not record.get("time"):
        record["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)
    with open(config.LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_log(limit=100):
    """返回最近 limit 条记录（时间正序的尾部）。"""
    if not os.path.isfile(config.LOG_FILE):
        return []
    rows = []
    with open(config.LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:] if limit else rows
