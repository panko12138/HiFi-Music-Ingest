# -*- coding: utf-8 -*-
"""测试公共设施：把 _tool 加入 import 路径、构造最小合法 WAV、起本地 HTTP 服务。"""
import os
import struct
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

TOOL_DIR = Path(__file__).resolve().parents[1]
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))


def pack_chunk(cid, body):
    """按 RIFF 规则打包 chunk（奇数长度补 1 字节）。"""
    chunk = cid + struct.pack("<I", len(body)) + body
    if len(body) & 1:
        chunk += b"\x00"
    return chunk


def build_wav(audio=b"\x80" * 101, extra_chunks=()):
    """构造一个带 fmt/data 的最小 WAV；audio 默认奇数字节，用于校验对齐补位。"""
    fmt_body = struct.pack("<HHIIHH", 1, 1, 8000, 8000, 1, 8)  # PCM 单声道 8kHz 8bit
    chunks = [pack_chunk(b"fmt ", fmt_body)]
    for cid, body in extra_chunks:
        chunks.append(pack_chunk(cid, body))
    chunks.append(pack_chunk(b"data", audio))
    body = b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE" + body


@pytest.fixture
def make_wav():
    return build_wav


@pytest.fixture
def library_dir(tmp_path, monkeypatch):
    """把 config 的曲库根与清单指向临时目录，保证测试不碰真实曲库。"""
    from app import config

    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setattr(config, "LIBRARY_ROOT", str(root))
    monkeypatch.setattr(config, "LIST_FILE", str(tmp_path / "清单.csv"))
    monkeypatch.setattr(config, "COVER_CACHE_DIR", str(tmp_path / "cover"))
    return root


class _Server:
    def __init__(self, content, support_range, fail_first):
        self.content = content
        self.support_range = support_range
        self.fail_first = fail_first
        self.ranges = []
        self.requests = 0
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)

    def _handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests += 1
                if outer.fail_first > 0:
                    outer.fail_first -= 1
                    self.send_error(500)
                    return
                rng = self.headers.get("Range")
                outer.ranges.append(rng)
                if rng and outer.support_range:
                    offset = int(rng.split("=", 1)[1].split("-")[0])
                    body = outer.content[offset:]
                    self.send_response(206)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Content-Range", "bytes %d-%d/%d"
                                     % (offset, len(outer.content) - 1, len(outer.content)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(outer.content)))
                self.end_headers()
                self.wfile.write(outer.content)

            def log_message(self, *args):  # 静默访问日志
                pass

        return Handler

    def start(self):
        self._thread.start()
        host, port = self._srv.server_address
        return "http://%s:%d/file.wav" % (host, port)

    def stop(self):
        self._srv.shutdown()
        self._srv.server_close()


@pytest.fixture
def http_server(monkeypatch):
    """起一个可控的本地 HTTP 服务，可选是否支持 Range、前 N 次返回 500。"""
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    servers = []

    def start(content, support_range=True, fail_first=0):
        srv = _Server(content, support_range, fail_first)
        servers.append(srv)
        return srv, srv.start()

    yield start
    for srv in servers:
        srv.stop()
