"""Cấu hình chung cho toàn bộ test.

``setup_logging`` (dùng bởi ``__main__`` và ``benchmark.main``) cấu hình logger
gốc của dự án một lần cho cả tiến trình: xóa handler cũ và đặt
``propagate = False`` để log không bị nhân đôi lên root. Đó là hành vi đúng
cho chương trình thật, nhưng không thể đảo ngược trong tiến trình test: mọi test
chạy sau đó mà dùng ``caplog`` sẽ không bắt được record của ``posture_monitor.*``.

Fixture ``_restore_project_logger_state`` trả lại trạng thái logger sau mỗi test
để thứ tự chạy không còn ảnh hưởng kết quả (ví dụ ``test_benchmark.py`` chạy
trước ``test_storage.py``).

Fixture ``_isolate_app_env`` gỡ các biến môi trường của **chương trình đang
chạy** trước mỗi test. Trên máy phát triển, ``POSTURE_CAMERA_SOURCE`` thường
được đặt sẵn để trỏ tới camera IP thật; để nguyên thì nó ghi đè
``camera.source`` trong mọi lần ``load_config()`` và làm sáu test cấu hình đỏ
dù mã nguồn đúng (``test_load_valid_config`` đọc ra URL RTSP thay vì
``usb:0``). Test nào cần biến đó thì tự đặt bằng ``monkeypatch.setenv``, nên
gỡ ở đây không che mất hành vi nào. ``monkeypatch`` của fixture và của test là
cùng một thực thể, nên giá trị gốc vẫn được trả lại sau mỗi test.
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

from posture_monitor.config import CAMERA_SOURCE_ENV, ONVIF_PASSWORD_ENV  # noqa: E402
from posture_monitor.logging_setup import ROOT_LOGGER_NAME  # noqa: E402

#: Biến môi trường mà ``load_config`` đọc để ghi đè cấu hình. Máy phát triển
#: thường đặt sẵn ``POSTURE_CAMERA_SOURCE`` cho camera IP thật.
_APP_ENV_VARS = (CAMERA_SOURCE_ENV, ONVIF_PASSWORD_ENV)


@pytest.fixture(autouse=True)
def _isolate_app_env(monkeypatch):
    """Gỡ biến môi trường của app đang có trên máy trước mỗi test.

    ``load_config`` cố ý cho ``POSTURE_CAMERA_SOURCE`` ghi đè
    ``camera.source``. Đó là hành vi đúng của chương trình, nhưng khi chạy
    test trên máy đã đặt biến đó thì mọi test nạp cấu hình đều nhìn thấy URL
    RTSP thay vì giá trị trong file, và sáu bài kiểm cấu hình đỏ oan. Test nào
    cần biến thì tự đặt bằng ``monkeypatch.setenv``; ``monkeypatch`` ở đây là
    cùng một thực thể với của test nên giá trị gốc vẫn được trả lại.
    """
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
