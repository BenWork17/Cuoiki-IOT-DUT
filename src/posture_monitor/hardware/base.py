"""Giao diện phần cứng chung.

Mọi thứ liên quan tới LED/buzzer/rung đi qua đây, để phần còn lại của hệ
thống không biết mình đang chạy trên GPIO thật hay giả lập.

Trạng thái theo spec v2 §5.7: ``GOOD | WARN | BAD | ABSENT`` (và ``BREAK`` khi
nhắc nghỉ). Một lớp triển khai có thể bỏ qua trạng thái không hỗ trợ nhưng
phải ghi log, không được crash.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..logging_setup import get_logger

logger = get_logger(__name__)

#: Các trạng thái mà tầng cảnh báo có thể đặt.
STATES = ("GOOD", "WARN", "BAD", "ABSENT", "BREAK")


class Hardware(ABC):
    """Giao diện điều khiển phần cứng cảnh báo."""

    @abstractmethod
    def set_state(self, state: str, *, alert: bool = True) -> None:
        """Chuyển phần cứng sang ``state`` (một giá trị trong :data:`STATES`).

        ``alert`` tách "đổi đèn" khỏi "kêu": trạng thái luôn được phản ánh
        bằng LED, nhưng tiếng buzzer/rung chỉ phát khi ``alert=True``. Tầng
        :mod:`posture_monitor.alerts` truyền ``False`` khi sự kiện bị cooldown
        chặn — đèn vẫn đúng tư thế, người dùng vẫn được yên (spec §5.7).

        Mặc định ``True`` để mọi lời gọi một tham số cũ giữ nguyên hành vi.
        """

    @abstractmethod
    def close(self) -> None:
        """Tắt hết và giải phóng chân GPIO."""

    def __enter__(self) -> "Hardware":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class NullHardware(Hardware):
    """Không làm gì cả.

    Dùng khi không khởi tạo được ngay cả phần cứng giả lập (ví dụ thiếu
    ``gpiozero`` trên PC). Hệ thống vẫn chạy, chỉ mất phần cảnh báo vật lý.
    """

    def set_state(self, state: str, *, alert: bool = True) -> None:
        logger.debug(
            "NullHardware bỏ qua trạng thái %s (alert=%s).", state, alert
        )

    def close(self) -> None:
        pass
