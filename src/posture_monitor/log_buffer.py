"""Bộ đệm log lỗi trong RAM để web và app cùng đọc qua ``GET /api/logs``.

Vì sao cần module này
=====================
``logging_setup`` chỉ ghi log ra stderr và file xoay vòng. Trên Pi chạy không
người trực, muốn biết "hệ thống vừa báo lỗi gì, lúc nào" thì phải SSH vào xem
file. Người dùng yêu cầu một tab log trong app và trên web, nên cần một chỗ
**đọc được qua HTTP**.

Vì sao **không** dùng bảng ``events`` trong SQLite: bảng đó chứa *sự kiện cảnh
báo* (``leave_frame``/``phone``/``stranger``) do ``schedule`` sinh ra, không
phải log lỗi hệ thống. Trộn hai loại vào một chỗ sẽ làm hỏng cả hai nghĩa.

Vì sao dùng RAM chứ không phải DB
=================================
Log lỗi là dữ liệu **nhất thời**, chỉ cần xem gần đây để chẩn đoán. Ghi mỗi
dòng log xuống SQLite sẽ làm nặng thẻ nhớ trên Pi và biến việc chẩn đoán thành
nguồn gây sự cố. ``collections.deque(maxlen=N)`` tự bỏ bản ghi cũ nhất, không
cần dọn dẹp, không chạm đĩa.

Giữ MỌI mức, chỉ lọc lúc ĐỌC
============================
Bộ đệm nhận mọi mức (kể cả ``INFO``/``DEBUG``) vì khi cần chẩn đoán một sự cố
cụ thể — ví dụ "vì sao phiên học không bắt đầu" — thì log ``INFO`` mới là manh
mối; nếu chỉ giữ ``WARNING`` từ đầu thì không còn gì để xem. Việc lọc theo mức
xảy ra ở tầng đọc (:meth:`LogBuffer.snapshot`), nơi có thể đổi ngưỡng bất cứ
lúc nào mà không phải khởi động lại.

Che mật khẩu — bắt buộc
=======================
Log của dự án hay chứa URL camera dạng ``rtsp://admin:matkhau@host:554/1/2``.
Đưa nguyên văn lên web là **rò mật khẩu**. Module này dùng lại
:func:`posture_monitor.config.redact_camera_source` (bản duy nhất được phép xử
lý chuỗi đó trong toàn dự án) chứ không viết hàm che thứ hai — hai bản che sẽ
trôi lệch nhau và bản yếu hơn thành lỗ hổng.

Đa luồng
========
``logging`` được gọi từ vòng lặp camera, luồng Flask và luồng face worker.
``deque`` tự an toàn cho append/popleft đơn lẻ, nhưng ``snapshot`` phải đọc
nhiều phần tử và ``clear`` phải xoá cả loạt — dùng ``threading.Lock`` để không
ai thấy trạng thái nửa vời. ``logging.Handler`` cũng có khoá nội bộ, nhưng khoá
đó chỉ bảo vệ lời gọi ``emit``, không bảo vệ người đọc từ route Flask.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Any

from .config import redact_camera_source

#: Thứ tự mức log, dùng để so "mức này có đạt ngưỡng không".
#:
#: Không dùng ``logging.getLevelName`` để so: nó trả tên hoặc số tuỳ đầu vào,
#: và các mức tùy biến có thể chen vào giữa. Bảng tường minh này là nguồn sự
#: thật duy nhất cho phép so sánh ngưỡng trong module.
LEVEL_ORDER = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}

#: Số bản ghi giữ mặc định. 500 dòng đủ thấy diễn biến một sự cố gần đây mà
#: không tốn đáng kể RAM trên Pi (mỗi dict vài trăm byte).
DEFAULT_MAXLEN = 500

#: Mức mặc định khi lọc — chỉ lỗi, không đầy ``INFO``.
#:
#: Người dùng cần thấy **lỗi**, không cần thấy nhật ký hoạt động bình thường;
#: ``INFO`` sẽ làm ngập popup và che mất lỗi thật.
DEFAULT_MIN_LEVEL = "WARNING"

#: Tiền tố bị cắt khỏi ``record.name`` cho tên logger ngắn gọn trên UI.
#:
#: Đây là bản sao của ``logging_setup.ROOT_LOGGER_NAME``, cố ý **không** import:
#: ``logging_setup`` import ``LogBuffer`` từ module này, nên import ngược lại sẽ
#: tạo vòng tròn (``logging_setup`` → ``log_buffer`` → ``logging_setup``) và nổ
#: ``ImportError`` khi ``ROOT_LOGGER_NAME`` chưa kịp định nghĩa. Giá trị được
#: khoá bằng test ``test_short_logger_name_matches_root_logger_name`` để hai nơi
#: không trôi lệch nhau.
_ROOT_LOGGER_NAME = "posture_monitor"

_LOGGER_PREFIX = _ROOT_LOGGER_NAME + "."


def normalize_level(value: Any, default: str = DEFAULT_MIN_LEVEL) -> str | None:
    """Đổi một giá trị mức log thành tên chuẩn trong :data:`LEVEL_ORDER`.

    Args:
        value: tên mức (``"warning"``, ``"ERROR"``…), số mức (``30``), hoặc
            ``None``.
        default: mức dùng khi ``value`` là ``None`` hoặc chuỗi rỗng.

    Returns:
        Tên mức viết hoa, hoặc ``None`` khi giá trị **không hợp lệ** (tầng gọi
        cần phân biệt "không truyền" với "truyền sai" để trả 400).
    """
    if value is None:
        return default
    if isinstance(value, bool):  # bool là lớp con của int, phải loại riêng
        return None
    if isinstance(value, int):
        for name, number in LEVEL_ORDER.items():
            if number == value:
                return name
        return None
    text = str(value).strip().upper()
    if not text:
        return default
    return text if text in LEVEL_ORDER else None


def meets_level(level: str, min_level: str) -> bool:
    """``level`` có đạt ngưỡng ``min_level`` không (bằng hoặc cao hơn)."""
    return LEVEL_ORDER.get(level, 0) >= LEVEL_ORDER.get(min_level, 0)


def short_logger_name(name: str) -> str:
    """Bỏ tiền tố ``posture_monitor.`` để tên logger ngắn, dễ đọc trên UI."""
    if name == _ROOT_LOGGER_NAME:
        return name
    if name.startswith(_LOGGER_PREFIX):
        return name[len(_LOGGER_PREFIX) :]
    return name


class LogBuffer(logging.Handler):
    """Giữ ``maxlen`` bản ghi log gần nhất trong RAM, an toàn đa luồng.

    Dùng như một handler bình thường: ``logging.getLogger(...).addHandler(...)``.
    Bản ghi được chuyển thành dict gọn để route HTTP trả thẳng, không phải
    serialize đối tượng ``LogRecord`` (không JSON được, và chứa ``args`` có thể
    là đối tượng tuỳ ý).

    Args:
        maxlen: số bản ghi giữ tối đa. Bản ghi cũ nhất bị bỏ khi vượt.
        level: mức tối thiểu mà handler này nhận, như mọi handler khác.
            ``NOTSET`` (mặc định) nghĩa là nhận mọi thứ logger gửi xuống.

    Attributes:
        maxlen: số bản ghi giữ tối đa.
    """

    def __init__(
        self, maxlen: int = DEFAULT_MAXLEN, level: int = logging.NOTSET
    ) -> None:
        super().__init__(level=level)
        capacity = int(maxlen)
        if capacity <= 0:
            raise ValueError(f"maxlen phải là số dương, nhận được {maxlen!r}.")
        self.maxlen = capacity
        self._records: deque[dict[str, Any]] = deque(maxlen=capacity)
        #: Khoá bảo vệ ``_records``. ``logging.Handler`` đã có ``self.lock``
        #: nhưng khoá đó chỉ dùng trong ``handle``; route Flask đọc đồng thời
        #: nên cần khoá riêng, độc lập với khoá của logging.
        self._lock = threading.Lock()

    # -- logging.Handler -------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        """Chuyển ``record`` thành dict và thêm vào bộ đệm.

        Nhận **mọi mức** — lọc theo mức là việc của :meth:`snapshot`. Giữ tất
        cả ở đây để không mất manh mối ``INFO`` khi cần chẩn đoán sâu.

        Không bao giờ ném: lỗi khi format một bản ghi (chuỗi định dạng hỏng,
        ``__str__`` của đối tượng trong ``args`` ném) không được làm sập vòng
        lặp camera. Đó là quy ước của mọi ``logging.Handler``, và ở đây càng
        quan trọng vì handler chạy trong tiến trình thật trên Pi.
        """
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - handler không được ném
            message = "<không format được bản ghi>"
        # Che mật khẩu RTSP: log hay chứa URL camera có user/pass.
        message = redact_camera_source(message)
        entry = {
            "ts": float(record.created),
            "level": record.levelname,
            "logger": short_logger_name(record.name),
            "message": message,
        }
        with self._lock:
            self._records.append(entry)

    # -- đọc -------------------------------------------------------------

    def snapshot(
        self,
        limit: int | None = None,
        min_level: str | None = DEFAULT_MIN_LEVEL,
    ) -> list[dict[str, Any]]:
        """Trả bản sao các bản ghi, **mới nhất trước**.

        Bộ đệm giữ mọi mức; lọc chỉ xảy ra ở đây, tầng đọc.

        Mặc định lọc ``WARNING`` vì người dùng cần thấy lỗi, không cần thấy
        nhật ký hoạt động bình thường; ``INFO`` sẽ làm ngập popup và che mất
        lỗi thật. Truyền ``min_level="DEBUG"`` để lấy tất cả.

        Args:
            limit: số bản ghi tối đa trả về; ``None`` hoặc ``<= 0`` nghĩa là
                trả hết những gì đang có.
            min_level: tên mức tối thiểu (``"WARNING"`` trả WARNING, ERROR,
                CRITICAL). ``None`` nghĩa là **không lọc** — dùng khi thật sự
                cần toàn bộ, và phải nói rõ ở chỗ gọi.

        Returns:
            List các dict ``{ts, level, logger, message}`` mới nhất trước.
            Là **bản sao sâu một tầng**: cả list lẫn từng dict đều mới, nên
            người gọi sửa gì cũng không ảnh hưởng bộ đệm. ``list(deque)`` một
            mình chỉ sao chép *tham chiếu* tới dict, nên sửa ``snapshot[0]
            ["message"]`` sẽ làm hỏng bản ghi gốc — đúng lỗi mà bài
            ``test_snapshot_returns_copy_not_internal_state`` bắt được.
        """
        threshold = normalize_level(min_level) if min_level is not None else None
        with self._lock:
            items = [dict(entry) for entry in self._records]
        if threshold is not None:
            items = [
                item
                for item in items
                if meets_level(item["level"], threshold)
            ]
        items.reverse()
        if limit is not None and int(limit) > 0:
            items = items[: int(limit)]
        return items

    def clear(self) -> None:
        """Xoá toàn bộ bản ghi đang giữ."""
        with self._lock:
            self._records.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)
