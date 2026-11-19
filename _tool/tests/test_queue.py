# -*- coding: utf-8 -*-
"""队列恢复的特征测试：中断遗留的等待任务应在启动调度后继续执行。"""
import json
import time

from app import config
from app import queue as queue_mod


def _wait_until(pred, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_resume_pending_restarts_interrupted_task(tmp_path, monkeypatch):
    missing = tmp_path / "missing.wav"
    queue_file = tmp_path / "queue.json"
    queue_file.write_text(json.dumps({"tasks": [{
        "id": "t1", "query": "x", "status": "running",
        "candidate": {"sid": "LocalFile", "uid": str(missing)},
    }]}), encoding="utf-8")
    monkeypatch.setattr(config, "QUEUE_FILE", str(queue_file))
    monkeypatch.setattr(config, "LOG_FILE", str(tmp_path / "log.jsonl"))

    mgr = queue_mod.QueueManager()
    assert mgr.tasks["t1"].status == "pending"

    mgr.resume_pending()

    assert _wait_until(lambda: mgr.tasks["t1"].status == "failed")
    assert "本地文件不存在" in mgr.tasks["t1"].msg
