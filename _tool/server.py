# -*- coding: utf-8 -*-
"""本地服务入口（仅监听 127.0.0.1）。

用法：
    python _tool/server.py
浏览器访问 http://127.0.0.1:8756
"""
import json
import os
import queue as _queue
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from flask import Flask, jsonify, request, Response, send_from_directory

import verify
from app import batch, config, search, sources
from app.log import read_log
from app.queue import manager

app = Flask(__name__, static_folder=None)


# ------------------------------------------------------------------ 页面

@app.get("/")
def index():
    index_file = os.path.join(config.WEB_DIR, "index.html")
    if os.path.isfile(index_file):
        return send_from_directory(config.WEB_DIR, "index.html")
    return Response("<h1>无损音乐检索与自动入库工具</h1>", mimetype="text/html")


@app.get("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(config.WEB_DIR, filename)


# ------------------------------------------------------------------ API

@app.post("/api/search")
def api_search():
    query = (request.json or {}).get("query", "") if request.is_json else ""
    try:
        candidates = search.search(query)
    except Exception as e:      # noqa: BLE001
        return jsonify({"query": query, "candidates": [],
                        "error": "检索失败：%s" % e}), 200
    ok, msg = sources.MusicdlAdapter().available()
    return jsonify({"query": query, "candidates": candidates,
                    "source_ok": ok, "source_msg": msg,
                    "errors": list(search.last_errors)})


@app.post("/api/download")
def api_download():
    body = request.json or {}
    candidate = body.get("candidate") or {}
    if not candidate:
        return jsonify({"task_id": None, "msg": "缺少 candidate"}), 400
    query = "%s - %s" % (candidate.get("artist") or "", candidate.get("title") or "")
    task_id = manager.add(query.strip(" -"), candidate, body.get("meta") or {})
    return jsonify({"task_id": task_id, "msg": ""})


@app.post("/api/manual")
def api_manual():
    body = request.json or {}
    candidates = []
    if body.get("url"):
        c = sources.manual.from_url(body["url"].strip())
        if c is None:
            return jsonify({"candidates": [], "msg": "直链需以 http/https 开头"}), 200
        candidates.append(c)
    elif body.get("local_path"):
        path = body["local_path"].strip().strip('"')
        if not os.path.isfile(path):
            return jsonify({"candidates": [], "msg": "本地文件不存在：%s" % path}), 200
        candidates.append(sources.manual.from_local(path))
    else:
        return jsonify({"candidates": [], "msg": "请提供 url 或 local_path"}), 400
    return jsonify({"candidates": [c.to_dict() for c in candidates], "msg": ""})


@app.get("/api/queue")
def api_queue():
    return jsonify({"tasks": manager.snapshot()})


@app.get("/api/queue/stream")
def api_queue_stream():
    def gen():
        sub = manager.subscribe()
        try:
            yield "event: ping\ndata: {}\n\n"
            while True:
                try:
                    item = sub.get(timeout=15)
                except _queue.Empty:
                    yield "event: ping\ndata: {}\n\n"
                    continue
                yield "data: %s\n\n" % json.dumps(item, ensure_ascii=False)
        finally:
            manager.unsubscribe(sub)
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/queue/action")
def api_queue_action():
    body = request.json or {}
    ok, msg = manager.action(body.get("task_id", ""), body.get("action", ""))
    return jsonify({"ok": ok, "msg": msg})


@app.post("/api/batch")
def api_batch():
    file = request.files.get("file")
    if file is None:
        return jsonify({"task_ids": [], "msg": "缺少上传文件"}), 400
    content = file.read().decode("utf-8-sig", "replace")
    task_ids = batch.run(content, manager, only_lossless=True)
    return jsonify({"task_ids": task_ids, "msg": "已入队 %d 首" % len(task_ids)})


@app.get("/api/log")
def api_log():
    limit = request.args.get("limit", type=int) or 100
    return jsonify({"results": read_log(limit)})


@app.post("/api/verify")
def api_verify():
    errs, warns, total = verify.run()
    return jsonify({"ok": not errs, "total": total,
                    "errors": errs, "warnings": warns})


def main():
    print("无损音乐检索与自动入库工具")
    print("库根目录：%s" % config.LIBRARY_ROOT)
    ok, msg = sources.MusicdlAdapter().available()
    print("检索引擎：%s" % (msg if ok else "不可用（%s）" % msg))
    print("监听：http://%s:%d" % (config.HOST, config.PORT))
    app.run(host=config.HOST, port=config.PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
