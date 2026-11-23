"""Cấu hình chung cho toàn bộ bộ kiểm thử tự động ``tests/``.

- Đảm bảo ``src/`` và ``tests/`` luôn có trong ``sys.path`` và xuất hằng số
  ``REPO_ROOT`` dùng chung cho mọi thư mục con trong ``tests/``.
- ``_isolate_app_env`` gỡ ``POSTURE_CAMERA_SOURCE`` và ``POSTURE_ONVIF_PASSWORD``
  trước mỗi bài test để môi trường máy phát triển không ghi đè cấu hình mẫu.
- ``_restore_project_logger_state`` trả lại handler/level/propagate cho logger
  gốc ``posture_monitor`` sau mỗi bài test để thứ tự chạy không ảnh hưởng ``caplog``.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = REPO_ROOT / "src"
for _entry in (str(_SRC), str(REPO_ROOT / "tests")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from posture_monitor.core.config import CAMERA_SOURCE_ENV, ONVIF_PASSWORD_ENV  # noqa: E402
from posture_monitor.core.logging_setup import ROOT_LOGGER_NAME  # noqa: E402

_APP_ENV_VARS = (CAMERA_SOURCE_ENV, ONVIF_PASSWORD_ENV)


@pytest.fixture(autouse=True)
def _isolate_app_env(monkeypatch):
    """Gỡ biến môi trường của app đang có trên máy trước mỗi test."""
    for name in _APP_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _restore_project_logger_state():
    """Khôi phục handler, propagate và level của logger gốc sau mỗi test."""
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    before_handlers = list(logger.handlers)
    before_propagate = logger.propagate
    before_level = logger.level

    yield

    logger.handlers[:] = before_handlers
    logger.propagate = before_propagate
    logger.setLevel(before_level)
