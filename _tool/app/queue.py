# -*- coding: utf-8 -*-
"""下载/入库队列：线程池并发 3、状态机、暂停/取消/恢复、SSE 广播、落盘恢复。

状态：pending / running / paused / done / failed / skipped / canceled
"""
import json
import os
import queue as _queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from . import config, downloader, ingest, meta, sources
from . import log as logmod
from .model import Result, Task


class QueueManager:
    def __init__(self):
        self.tasks = {}
        self.order = []
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=config.CONCURRENCY)
        self._subscribers = []
        self._sub_lock = threading.Lock()
        self._cancel = set()
        self._intent = {}
        self._last_save = 0.0
        self.load()

    # ------------------------------------------------------------ 持久化
    def load(self):
        if not os.path.isfile(config.QUEUE_FILE):
            return
        try:
            with open(config.QUEUE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:          # noqa: BLE001
            return
        for d in data.get("tasks", []):
            t = Task.from_dict(d)
            if t.status == "running":
                t.status = "pending"
            self.tasks[t.id] = t
            self.order.append(t.id)

    def save(self):
        with self.lock:
            data = {"tasks": [self.tasks[i].to_dict() for i in self.order if i in self.tasks]}
        os.makedirs(os.path.dirname(config.QUEUE_FILE), exist_ok=True)
        tmp = config.QUEUE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, config.QUEUE_FILE)

    def _save_throttled(self):
        if time.time() - self._last_save >= 1.0:
            self._last_save = time.time()
            self.save()

    # ------------------------------------------------------------ 广播
    def subscribe(self):
        q = _queue.Queue(maxsize=200)
        with self._sub_lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self._sub_lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _notify(self, task):
        payload = {"type": "task", "task": task.to_dict()}
        with self._sub_lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(payload)
            except _queue.Full:
                pass

    def emit(self, result):
        """记录一条入库结果（写日志 + 广播）。"""
        record = logmod.append(result)
        with self._sub_lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait({"type": "result", "result": record})
            except _queue.Full:
                pass
        return record

    # ------------------------------------------------------------ 任务
    def snapshot(self):
        with self.lock:
            return [self.tasks[i].to_dict() for i in self.order if i in self.tasks]

    def _update(self, task_id, do_save=True, **kw):
        t = self.tasks.get(task_id)
        if not t:
            return
        for k, v in kw.items():
            setattr(t, k, v)
        self._notify(t)
        if do_save:
            self._save_throttled()

    def add(self, query, candidate, meta_=None, auto_start=True):
        t = Task(id=uuid.uuid4().hex[:12], query=query or "",
                 candidate=candidate or {}, meta=meta_ or {},
                 status="pending", created=time.time())
        with self.lock:
            self.tasks[t.id] = t
            self.order.append(t.id)
        self.save()
        self._notify(t)
        if auto_start:
            self.executor.submit(self._run, t.id)
        return t.id

    def action(self, task_id, action):
        t = self.tasks.get(task_id)
        if not t:
            return False, "任务不存在"
        if action == "pause":
            self._intent[task_id] = "pause"
            self._cancel.add(task_id)
            if t.status == "pending":
                self._update(task_id, status="paused", msg="已暂停")
        elif action == "cancel":
            self._intent[task_id] = "cancel"
            self._cancel.add(task_id)
            if t.status == "pending":
                self._update(task_id, status="canceled", msg="已取消")
        elif action == "resume":
            self._cancel.discard(task_id)
            self._intent.pop(task_id, None)
            if t.status in ("paused", "canceled", "failed"):
                self._update(task_id, status="pending", percent=0.0, speed="", msg="")
                self.executor.submit(self._run, task_id)
            else:
                return False, "当前状态不可恢复"
        else:
            return False, "未知操作"
        self.save()
        return True, ""

    # ------------------------------------------------------------ 执行
    def _run(self, task_id):
        t = self.tasks.get(task_id)
        if not t or t.status in ("canceled", "done", "skipped", "failed"):
            return
        self._update(task_id, status="running", percent=0.0, speed="", msg="准备中")

        candidate = dict(t.candidate or {})
        temp_dest = None
        last_pct = [-1]
        try:
            ext = (candidate.get("format") or "").lower()
            if ext in ("mflac", "mgg", "ncm", "kgm", "qmc"):
                raise RuntimeError("加密格式 %s，已拒绝（请换源）" % ext)

            sid = candidate.get("sid")
            if sid == "LocalFile":
                local = candidate.get("uid") or ""
                if not os.path.isfile(local):
                    raise RuntimeError("本地文件不存在：%s" % local)
            else:
                info = sources.resolve(candidate)
                if not info or not info.get("url"):
                    raise RuntimeError("候选直链已过期，请重新搜索后重试")
                ext = info.get("ext") or ext or "bin"
                temp_dest = os.path.join(config.DOWNLOAD_DIR,
                                         "%s.%s" % (task_id, ext))
                self._update(task_id, msg="下载中", do_save=False)

                def _prog(pct, msg, speed):
                    if int(pct) != last_pct[0]:
                        last_pct[0] = int(pct)
                        self._update(task_id, percent=round(pct, 1), speed=speed,
                                     msg=msg, do_save=False)

                local = downloader.download(
                    info["url"], temp_dest,
                    headers=info.get("headers"), cookies=info.get("cookies"),
                    progress=_prog,
                    cancel=lambda: task_id in self._cancel,
                )

            if task_id in self._cancel:
                raise downloader.DownloadCanceled()

            self._update(task_id, msg="匹配元数据", do_save=False)
            try:
                matched = meta.match(candidate.get("title") or "",
                                     candidate.get("artist") or "")
            except Exception:      # noqa: BLE001
                matched = {}
            merged = {
                "title": candidate.get("title") or matched.get("title") or "",
                "artist": candidate.get("artist") or matched.get("artist") or "",
                "album": matched.get("album") or candidate.get("album") or "",
                "year": matched.get("year") or "",
                "genre": matched.get("genre") or "",
                "tracknumber": matched.get("tracknumber") or 0,
                "tracktotal": matched.get("tracktotal") or 0,
                "cover_path": matched.get("cover_path") or "",
            }
            merged.update({k: v for k, v in (t.meta or {}).items() if v})

            self._update(task_id, msg="写入曲库", do_save=False)
            result = ingest.ingest(local, candidate, merged)
        except downloader.DownloadCanceled:
            intent = self._intent.get(task_id, "cancel")
            self._update(task_id, status=("paused" if intent == "pause" else "canceled"),
                         speed="", msg=("已暂停" if intent == "pause" else "已取消"))
            return
        except Exception as e:      # noqa: BLE001
            result = Result(song=candidate.get("title") or t.query, status="失败",
                            reason=str(e))
        finally:
            if temp_dest and os.path.isfile(temp_dest):
                try:
                    os.remove(temp_dest)
                except OSError:
                    pass

        status_map = {"成功": "done", "重复": "skipped", "失败": "failed", "跳过": "skipped"}
        final_status = status_map.get(result.status, "failed")
        self._update(task_id, status=final_status, percent=100.0 if final_status == "done" else t.percent,
                     speed="", msg=result.reason or result.status, path=result.path or "")
        self.emit(result)


manager = QueueManager()
