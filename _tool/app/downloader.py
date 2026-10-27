# -*- coding: utf-8 -*-
"""下载器：流式下载 + Range 断点续传 + 有限重试 + 进度回调。

仅处理来源适配器解析出的直链（HTTP）。加密格式与 HLS 由调用方在更早阶段拦截。
"""
import os
import time
from urllib.parse import urlsplit

import requests

from . import config

# 防盗链兜底：仅对已知音乐平台直链注入 Referer；未知域名不动，
# 避免给任意 URL（如手动来源）带上错误 Referer。
_REFERER_RULES = (
    ("kuwo.cn", "https://www.kuwo.cn/"),
    ("qq.com", "https://y.qq.com/"),
    ("kugou.com", "https://www.kugou.com/"),
    ("kglcdn.com", "https://www.kugou.com/"),
    ("126.net", "https://music.163.com/"),
    ("music.163.com", "https://music.163.com/"),
    ("migu.cn", "https://music.migu.cn/"),
    ("91q.com", "https://music.91q.com/"),
)


def _fallback_referer(url):
    """按直链域名给出兜底 Referer；未知域名返回 None。"""
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return None
    for suffix, referer in _REFERER_RULES:
        if host == suffix or host.endswith("." + suffix):
            return referer
    return None


def _with_referer(url, headers):
    """缺 Referer 时按域名补一个兜底值；已有 Referer（任意大小写）则不覆盖。"""
    if any(k.lower() == "referer" for k in headers):
        return headers
    referer = _fallback_referer(url)
    if referer:
        headers["Referer"] = referer
    return headers


class DownloadCanceled(Exception):
    """用户取消下载。"""


class DownloadError(Exception):
    """下载失败（重试耗尽）。"""


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f%s" % (n, unit)
        n /= 1024
    return "%.1fGB" % n


def human_speed(bps):
    return "%s/s" % human_size(bps)


def download(url, dest, headers=None, cookies=None, progress=None,
             cancel=None, timeout=None, retry=None):
    """把 url 下载到 dest；返回 dest。

    progress(percent, msg, speed) 可为 None；cancel() 返回 True 时抛 DownloadCanceled。
    """
    timeout = timeout or config.TIMEOUT
    retry = max(int(retry or config.RETRY), 1)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    last_err = None

    for _attempt in range(retry):
        try:
            existing = os.path.getsize(dest) if os.path.isfile(dest) else 0
            req_headers = _with_referer(url, dict(headers or {}))
            if existing:
                req_headers["Range"] = "bytes=%d-" % existing

            resp = requests.get(url, headers=req_headers, cookies=cookies or {},
                                stream=True, timeout=timeout)
            if existing and resp.status_code == 200:
                existing, mode = 0, "wb"          # 服务器不支持续传 → 重下
            elif existing and resp.status_code == 206:
                mode = "ab"
            else:
                resp.raise_for_status()
                existing, mode = 0, "wb"

            total = int(resp.headers.get("Content-Length") or 0) + existing
            done, base, start = existing, existing, time.time()
            with open(dest, mode) as f:
                for chunk in resp.iter_content(config.CHUNK_SIZE):
                    if cancel and cancel():
                        raise DownloadCanceled()
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        elapsed = max(time.time() - start, 1e-6)
                        pct = (done / total * 100.0) if total else 0.0
                        progress(pct, human_size(done) if total else "",
                                 human_speed((done - base) / elapsed))
            return dest
        except DownloadCanceled:
            raise
        except Exception as e:      # noqa: BLE001
            last_err = e
            continue

    raise DownloadError(str(last_err) if last_err else "未知下载错误")
