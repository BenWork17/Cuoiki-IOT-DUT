"""Cấu hình logging dùng chung cho CLI và các module.

Một chỗ duy nhất quyết định định dạng log và mức log, để log từ ``capture``,
``hardware`` và ``__main__`` có cùng hình thức. Ghi log ra stderr; nếu người
dùng truyền ``log_file`` thì ghi thêm ra file (xoay vòng theo dung lượng để
không làm mòn thẻ nhớ trên Pi).

Ngoài stderr/file, module này còn gắn một
:class:`~posture_monitor.log_buffer.LogBuffer` **dùng chung** trong RAM để web
và app đọc được qua ``GET /api/logs``. Buffer đó tạo lười ở lần gọi đầu và
**không bao giờ** bị thay bằng instance khác — xem :func:`get_log_buffer`.
"""

from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - chỉ cho type checker
    from .log_buffer import LogBuffer

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)-28s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Logger gốc của dự án; mọi module con đặt dưới tên này.
ROOT_LOGGER_NAME = "posture_monitor"

#: Buffer dùng chung. Tạo lười trong :func:`get_log_buffer`; khoá bảo vệ việc
#: tạo để hai luồng gọi lần đầu cùng lúc không sinh ra hai buffer.
_buffer: "LogBuffer | None" = None
_buffer_lock = threading.Lock()


def get_log_buffer() -> "LogBuffer":
    """Trả :class:`LogBuffer` dùng chung, tạo ở lần gọi đầu tiên.

    Vì sao tạo lười thay vì tạo lúc import: module này được import từ cả CLI
    lẫn web. Tạo buffer ngay lúc import sẽ cấp phát deque trong mọi tiến trình
    — kể cả lệnh chỉ in ``--help``. Tạo lười giữ chi phí bằng 0 cho tới khi
    thật sự cần.

    Vì sao **không** tạo mới mỗi lần: route ``/api/logs`` và
    ``setup_logging`` phải nói về **cùng một** deque. Tạo mới ở mỗi lần gọi thì
    handler gắn vào logger sẽ ghi vào một buffer, còn route đọc một buffer rỗng
    khác — log luôn trống và rất khó phát hiện.

    Vì sao import ``log_buffer`` **bên trong hàm**: ``log_buffer`` cần
    ``config.redact_camera_source``, mà ``config`` kéo theo ``faces``, và
    ``faces`` lại import ``get_logger`` từ chính module này. Import ở đầu tệp
    tạo vòng tròn ``logging_setup → log_buffer → config → faces →
    logging_setup`` và nổ ``ImportError: cannot import name 'get_logger' from
    partially initialized module``. Import muộn cắt đúng vòng đó: lúc hàm này
    chạy, module đã nạp xong.

    Returns:
        Instance dùng chung; gọi nhiều lần trả **cùng một** đối tượng.
    """
    global _buffer
    if _buffer is not None:
        return _buffer
    with _buffer_lock:
        # Kiểm tra lại trong khoá: luồng khác có thể vừa tạo xong.
        if _buffer is None:
            from .log_buffer import LogBuffer  # noqa: PLC0415 - cắt vòng import

            _buffer = LogBuffer()
        return _buffer


def reset_log_buffer() -> None:
    """Xoá nội dung buffer dùng chung, **giữ nguyên instance**.

    Dành cho test và cho lệnh chẩn đoán cần mốc sạch. Không tạo instance mới:
    handler đã gắn vào logger vẫn phải trỏ tới đúng buffer đó.
    """
    get_log_buffer().clear()


def setup_logging(
    level: str | int = "INFO",
    log_file: str | Path | None = None,
    *,
    with_buffer: bool = True,
) -> logging.Logger:
    """Khởi tạo logger gốc của dự án và trả về nó.

    Args:
        level: Tên mức log (``DEBUG``, ``INFO``, ...) hoặc hằng số của
            :mod:`logging`.
        log_file: Nếu có, ghi thêm log ra file này. Thư mục cha được tạo nếu
            chưa có.
        with_buffer: Gắn :class:`LogBuffer` dùng chung vào logger để web/app
            đọc được qua ``GET /api/logs``. Mặc định ``True``; đặt ``False``
            cho lệnh chỉ cần in ra màn hình. Tham số keyword-only để lời gọi
            cũ không phải đổi.

    Returns:
        Logger tên ``posture_monitor``. Gọi nhiều lần không nhân đôi handler và
        không tạo buffer thứ hai.
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

    if with_buffer:
        # ``get_log_buffer`` trả **instance dùng chung**, nên dù
        # ``logger.handlers.clear()`` ở trên có gỡ handler cũ thì buffer và
        # nội dung của nó vẫn còn nguyên — chỉ tham chiếu handler được gắn lại.
        # Nhờ vậy gọi ``setup_logging`` nhiều lần không làm mất log đã ghi và
        # không sinh buffer thứ hai.
        buffer_handler = get_log_buffer()
        buffer_handler.setLevel(numeric_level)
        logger.addHandler(buffer_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Lấy logger con dưới ``posture_monitor``.

    ``get_logger(__name__)`` với ``__name__ = "posture_monitor.capture"`` trả
    về đúng logger đó.
    """
    if name == ROOT_LOGGER_NAME or name.startswith(ROOT_LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")
