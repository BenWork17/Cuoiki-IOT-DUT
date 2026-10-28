"""Cấu hình logging dùng chung cho CLI và các module.

Một chỗ duy nhất quyết định định dạng log và mức log, để log từ ``capture``,
``hardware`` và ``__main__`` có cùng hình thức. Ghi log ra stderr; nếu người
dùng truyền ``log_file`` thì ghi thêm ra file (xoay vòng theo dung lượng để
không làm mòn thẻ nhớ trên Pi).
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)-28s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Logger gốc của dự án; mọi module con đặt dưới tên này.
ROOT_LOGGER_NAME = "posture_monitor"


def setup_logging(
    level: str | int = "INFO",
    log_file: str | Path | None = None,
) -> logging.Logger:
    """Khởi tạo logger gốc của dự án và trả về nó.

    Args:
        level: Tên mức log (``DEBUG``, ``INFO``, ...) hoặc hằng số của
            :mod:`logging`.
        log_file: Nếu có, ghi thêm log ra file này. Thư mục cha được tạo nếu
            chưa có.

    Returns:
        Logger tên ``posture_monitor``. Gọi nhiều lần không nhân đôi handler.
    """
    if isinstance(level, int):
        numeric_level = level
    else:
        numeric_level = logging.getLevelName(str(level).upper())
        if not isinstance(numeric_level, int):
            numeric_level = logging.INFO

    logger = logging.getLogger(ROOT_LOGGER_NAME)
    logger.setLevel(numeric_level)
    # Tránh cộng dồn handler khi hàm được gọi lại trong test.
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    console = logging.StreamHandler(stream=sys.stderr)
    console.setFormatter(formatter)
    logger.addHandler(console)

    if log_file is not None:
        target = Path(log_file)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # 1 MB x 3 file: đủ để tra sự cố, không ghi liên tục làm mòn thẻ.
            file_handler = RotatingFileHandler(
                target, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError as exc:
            logger.warning("Không mở được file log '%s': %s", target, exc)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Lấy logger con dưới ``posture_monitor``.

    ``get_logger(__name__)`` với ``__name__ = "posture_monitor.capture"`` trả
    về đúng logger đó.
    """
    if name == ROOT_LOGGER_NAME or name.startswith(ROOT_LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")
