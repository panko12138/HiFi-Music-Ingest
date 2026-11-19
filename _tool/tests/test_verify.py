# -*- coding: utf-8 -*-
"""全库校验的边界测试：清单尚未创建时应视为空库而不是报错。"""
import verify
from app import config


def test_verify_treats_missing_list_as_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LIBRARY_ROOT", str(tmp_path))
    monkeypatch.setattr(config, "LIST_FILE", str(tmp_path / "none.csv"))

    assert verify.load_rows() == []
    assert verify.run() == ([], [], 0)
