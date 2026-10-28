"""Cấu hình chung cho toàn bộ test.

``setup_logging`` (dùng bởi ``__main__`` và ``benchmark.main``) cấu hình logger
gốc của dự án một lần cho cả tiến trình: xóa handler cũ và đặt
``propagate = False`` để log không bị nhân đôi lên root. Đó là hành vi đúng
cho chương trình thật, nhưng không thể đảo ngược trong tiến trình test: mọi test
chạy sau đó mà dùng ``caplog`` sẽ không bắt được record của ``posture_monitor.*``.

Fixture dưới đây trả lại trạng thái logger sau mỗi test để thứ tự chạy không
còn ảnh hưởng kết quả (ví dụ ``test_benchmark.py`` chạy trước
``test_storage.py``).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.logging_setup import ROOT_LOGGER_NAME  # noqa: E402


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
