"""Chuyển đầu ra máy trạng thái thành cảnh báo vật lý GPIO (spec v2 §5.7).

Tầng này chọn trạng thái phần cứng cho mỗi khung, bỏ qua các khung lặp lại cùng
trạng thái, và đẩy lời gọi phần cứng ra luồng nền có hàng đợi kích thước cố định
để không bao giờ chặn vòng lặp camera chính.
"""

from __future__ import annotations

import inspect
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..core.labels import EVENT_BREAK, EVENT_ESCALATE, STATE_BAD
from ..core.logging_setup import get_logger
from ..hardware.base import HW_BREAK, STATES, Hardware

if TYPE_CHECKING:
    from ..domain.state import StateUpdate

logger = get_logger(__name__)

#: Số mục tối đa trong hàng đợi. Hai mục đủ để giữ một sự kiện ép buộc đang
#: chờ (ví dụ BREAK) cộng trạng thái mới nhất; nhiều hơn thì chỉ là khung cũ.
QUEUE_SIZE = 2

#: Thời gian tối đa chờ luồng phần cứng thoát khi :meth:`AlertDispatcher.close`.
CLOSE_JOIN_S = 5.0


def _accepts_alert_keyword(hardware) -> bool:
    """``True`` nếu ``hardware.set_state`` nhận được ``alert=...``."""
    try:
        signature = inspect.signature(hardware.set_state)
    except (TypeError, ValueError):  # pragma: no cover - chữ ký không đọc được
        return True
    for parameter in signature.parameters.values():
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            return True
        if parameter.name == "alert" and parameter.kind in (
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            return True
    return False


@dataclass(frozen=True)
class _Request:
    """Một lần đặt trạng thái đang chờ luồng phần cứng thực hiện."""

    state: str
    force: bool


class AlertDispatcher:
    """Biến :class:`~posture_monitor.domain.state.StateUpdate` thành lời gọi phần cứng.

    Args:
        hardware: bất kỳ triển khai :class:`~posture_monitor.hardware.base.Hardware`.
        alerts: ``config.alerts`` (``AlertsConfig``).
        queue_size: số mục tối đa trong hàng đợi (tối thiểu 1).

    Raises:
        ValueError: khi ``queue_size < 1``.
    """

    def __init__(
        self,
        hardware: Hardware,
        alerts=None,
        *,
        queue_size: int = QUEUE_SIZE,
    ) -> None:
        if queue_size < 1:
            raise ValueError(
                f"queue_size phải >= 1, nhận được {queue_size!r}."
            )
        self._hardware = hardware
        self.alerts = alerts
        self._queue_size = int(queue_size)
        self._supports_alert = _accepts_alert_keyword(hardware)

        self._cond = threading.Condition()
        self._pending: list[_Request] = []
        self._busy = False
        self._closed = False
        self._worker: threading.Thread | None = None

        self._requested: str | None = None
        self._last_sent: str | None = None

    # ------------------------------------------------------------------
    # Vòng đời
    # ------------------------------------------------------------------
    def __enter__(self) -> "AlertDispatcher":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def requested_state(self) -> str | None:
        """Trạng thái gần nhất đã được xếp vào hàng đợi."""
        return self._requested

    @property
    def last_sent_state(self) -> str | None:
        """Trạng thái gần nhất phần cứng đã nhận (do luồng nền đặt)."""
        return self._last_sent

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """Dừng luồng nền sau khi xử lý nốt mục đang chờ."""
        with self._cond:
            if self._closed:
                return
            self._closed = True
            worker = self._worker
            self._cond.notify_all()
        if worker is not None:
            worker.join(CLOSE_JOIN_S)
            if worker.is_alive():  # pragma: no cover - chỉ khi phần cứng treo
                logger.warning(
                    "Luồng cảnh báo chưa thoát sau %.1f s; bỏ mặc (daemon).",
                    CLOSE_JOIN_S,
                )

    # ------------------------------------------------------------------
    # Nạp cập nhật
    # ------------------------------------------------------------------
    def dispatch(self, update: StateUpdate) -> str | None:
        """Xếp trạng thái của ``update`` vào hàng đợi nếu cần."""
        target = self._target(update)
        if target is None:
            return None
        state, force = target

        with self._cond:
            if self._closed:
                logger.debug(
                    "Dispatcher đã đóng; bỏ qua trạng thái %s.", state
                )
                return None
            if not force and (
                state == self._requested
                or any(request.state == state for request in self._pending)
            ):
                return None

            if not self._enqueue(_Request(state=state, force=force)):
                return None
            self._ensure_worker()
            self._requested = state
            return state

    def flush(self, timeout: float = 2.0) -> bool:
        """Chờ tới khi hàng đợi trống và lời gọi hiện tại chạy xong."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._cond:
            while self._pending or self._busy:
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return False
                self._cond.wait(remaining)
            return True

    # ------------------------------------------------------------------
    # Nội bộ
    # ------------------------------------------------------------------
    @staticmethod
    def _target(update: StateUpdate) -> tuple[str, bool] | None:
        """Chọn ``(trạng thái phần cứng, ép buộc)`` cho một khung."""
        if any(event.type == EVENT_BREAK for event in update.alerts):
            return HW_BREAK, True
        if any(event.type == EVENT_ESCALATE for event in update.alerts):
            return STATE_BAD, True
        if update.state not in STATES:
            logger.warning(
                "Trạng thái tư thế không hợp lệ %r; bỏ qua khung.", update.state
            )
            return None
        return update.state, bool(update.alerts)

    def _ensure_worker(self) -> None:
        """Dựng luồng nền ở lần xếp hàng đầu tiên (gọi khi đã giữ ``_cond``)."""
        if self._worker is not None:
            return
        self._worker = threading.Thread(
            target=self._run,
            name="alert-dispatcher",
            daemon=True,
        )
        self._worker.start()

    def _enqueue(self, request: _Request) -> bool:
        """Thêm mục, bỏ bớt khi đầy (gọi khi đã giữ ``_cond``)."""
        if len(self._pending) >= self._queue_size:
            drop = next(
                (
                    index
                    for index, item in enumerate(self._pending)
                    if not item.force
                ),
                None,
            )
            if drop is None and request.force:
                drop = 0
            if drop is None:
                logger.debug(
                    "Hàng đợi đầy mục ép buộc; bỏ trạng thái %s.",
                    request.state,
                )
                return False
            dropped = self._pending.pop(drop)
            logger.debug(
                "Hàng đợi cảnh báo đầy; bỏ trạng thái %s để nhận %s.",
                dropped.state,
                request.state,
            )
        self._pending.append(request)
        self._cond.notify_all()
        return True

    def _run(self) -> None:
        """Vòng lặp luồng nền: lấy mục, gọi phần cứng, báo hàng đợi rảnh."""
        while True:
            with self._cond:
                while not self._pending and not self._closed:
                    self._cond.wait()
                if not self._pending:
                    return
                request = self._pending.pop(0)
                self._busy = True
            try:
                if self._supports_alert:
                    self._hardware.set_state(request.state, alert=request.force)
                else:
                    self._hardware.set_state(request.state)
            except Exception:  # noqa: BLE001 - spec §11.4: không chết vì GPIO
                logger.warning(
                    "Lỗi phần cứng khi đặt trạng thái %s; bỏ qua và chạy tiếp.",
                    request.state,
                    exc_info=True,
                )
            with self._cond:
                self._last_sent = request.state
                self._busy = False
                self._cond.notify_all()


__all__ = [
    "AlertDispatcher",
    "CLOSE_JOIN_S",
    "HW_BREAK",
    "QUEUE_SIZE",
]
