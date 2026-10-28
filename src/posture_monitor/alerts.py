"""Chuyển đầu ra máy trạng thái thành cảnh báo vật lý (spec v2 §5.7).

Tầng này cố ý mỏng, vì hai tầng dưới đã lo phần khó:

- ``state.py`` áp cooldown và đánh dấu ``Event.alert`` — nơi đây **không**
  đếm cooldown lần nữa, chỉ kích phần cứng khi ``Event.alert is True``.
- ``hardware/gpio_real.py`` và ``gpio_mock.py`` đã ánh xạ trạng thái sang
  LED/buzzer/rung kèm tôn trọng ``alerts.buzzer_enabled``/``vibration_enabled``.

Còn lại ba việc: chọn trạng thái phần cứng cho mỗi khung, bỏ qua các khung
lặp lại cùng trạng thái, và đẩy lời gọi phần cứng ra khỏi vòng lặp chính.

**Vì sao phải có luồng riêng.** ``GpioRealHardware.set_state`` ngủ đồng bộ
khi phát tiếng, mỗi nhịp ``on(); sleep(0.3); off(); sleep(0.3)`` là 0,6 s:

- ``BAD``: ``_beep(2)`` = 1,2 s + rung 0,3 s ≈ **1,5 s**
- ``BREAK``: ``_beep(3)`` ≈ **1,8 s**

Với ``target_fps = 5``, chu kỳ khung chỉ 0,2 s; một lời gọi BAD chặn gấp
~7,5 lần chu kỳ, và mọi khung đến trong lúc bấm tiếng đều bị trễ theo. Hàng
đợi ở đây có kích thước cố định và gộp trạng thái mới nhất, nên phần cứng
chậm hơn tốc độ khung cũng chỉ tốn một lần đặt trạng thái cuối, không bao
giờ phình bộ nhớ.

**``ESCALATE`` và cờ ``alert``.** ``state.py`` đặt ``alert=allowed`` (đã trừ
cooldown) cho cả ``ALERT_START`` lẫn ``ESCALATE``; tầng này chỉ đọc cờ đó,
không đếm lại. Escalate được chuyển thành một lời gọi ``BAD`` **ép buộc**,
tức là đèn đỏ + 2 tiếng buzzer phát lại — ``Hardware`` không có trạng thái
riêng cho "buzzer dài hơn" và module này không được sửa tầng phần cứng, nên
dùng lại BAD là mức gần nhất với spec §5.6. Khi ``alert=False`` (cooldown),
escalate không kích tiếng.

**Đổi đèn khác với kêu.** Một khung có thể đổi trạng thái (``GOOD → WARN →
BAD``) trong khi sự kiện sinh ra đã bị cooldown chặn (``alert_start`` với
``alert=False``). Lúc đó LED **phải** đổi theo tư thế, còn buzzer/rung phải
im — nếu không thì ``alert_cooldown_s`` chỉ chặn được trường hợp lặp lại
cùng trạng thái, đúng thứ người dùng nghe thấy là "vẫn bị làm ồn". Vì vậy
mỗi mục trong hàng đợi mang theo cờ ``alert`` và được truyền xuống
``Hardware.set_state(state, alert=...)``.

Trạng thái ``BREAK`` (nhắc nghỉ, 3 tiếng buzzer) không nằm trong bốn trạng
thái tư thế; nó được chọn khi có ``EVENT_BREAK`` với ``alert=True`` và được
ưu tiên hơn trạng thái tư thế trong cùng khung. Khung kế tiếp sẽ đặt lại
trạng thái tư thế bình thường vì ``BREAK`` khác nó.
"""

from __future__ import annotations

import inspect
import threading
import time
from dataclasses import dataclass

from .hardware.base import STATES, Hardware
from .logging_setup import get_logger
from .state import EVENT_BREAK, EVENT_ESCALATE, STATE_BAD, StateUpdate

logger = get_logger(__name__)

#: Trạng thái phần cứng cho sự kiện nhắc nghỉ (không phải trạng thái tư thế).
HW_BREAK = "BREAK"

#: Số mục tối đa trong hàng đợi. Hai mục đủ để giữ một sự kiện ép buộc đang
#: chờ (ví dụ BREAK) cộng trạng thái mới nhất; nhiều hơn thì chỉ là khung cũ.
QUEUE_SIZE = 2

#: Thời gian tối đa chờ luồng phần cứng thoát khi :meth:`AlertDispatcher.close`.
CLOSE_JOIN_S = 5.0


def _accepts_alert_keyword(hardware) -> bool:
    """``True`` nếu ``hardware.set_state`` nhận được ``alert=...``.

    Dùng để giữ tương thích với triển khai ``Hardware`` cũ (một tham số).
    Không dò được chữ ký (C extension, ``__signature__`` lạ) thì giả định là
    có — giao diện hiện tại của dự án đều có.
    """
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
    #: ``True`` khi có sự kiện ``alert=True``: vừa phải chạy dù trạng thái
    #: trùng (nên không dùng làm khoá chống lặp), vừa cho phép phát tiếng.
    #: ``False`` = đổi trạng thái nhưng im lặng — sự kiện bị cooldown chặn.
    force: bool


class AlertDispatcher:
    """Biến :class:`~posture_monitor.state.StateUpdate` thành lời gọi phần cứng.

    Args:
        hardware: bất kỳ triển khai :class:`~posture_monitor.hardware.base.Hardware`.
        alerts: ``config.alerts`` (``AlertsConfig``). Được giữ lại để truy vấn;
            việc tôn trọng ``buzzer_enabled``/``vibration_enabled`` do tầng
            phần cứng quyết định.
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

        #: Triển khai ``Hardware`` cũ chỉ nhận ``set_state(state)``. Dò một
        #: lần lúc khởi tạo thay vì thử ``TypeError`` mỗi lần gọi: một
        #: ``TypeError`` thật bên trong ``set_state`` sẽ bị hiểu nhầm thành
        #: "sai chữ ký" và chạy lại thao tác phần cứng hai lần.
        self._supports_alert = _accepts_alert_keyword(hardware)

        self._cond = threading.Condition()
        self._pending: list[_Request] = []
        self._busy = False
        self._closed = False
        self._worker: threading.Thread | None = None

        #: Trạng thái đã xếp vào hàng đợi gần nhất (kể cả khi chưa chạy).
        #: Chỉ cập nhật khi mục thực sự được nhận, nên trạng thái bị hàng đợi
        #: đầy loại bỏ sẽ được khung sau gửi lại.
        self._requested: str | None = None
        #: Trạng thái lời gọi phần cứng đã hoàn tất gần nhất.
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
        """Dừng luồng nền sau khi xử lý nốt mục đang chờ.

        Không gọi ``hardware.close()``: đối tượng phần cứng do bên tạo ra sở
        hữu, và luồng này chỉ mượn nó để đặt trạng thái.
        """
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
        """Xếp trạng thái của ``update`` vào hàng đợi nếu cần.

        Không chặn vòng lặp chính và không bao giờ raise vì lỗi phần cứng
        (spec §11.4). Lời gọi ``hardware.set_state`` thật sự chạy ở luồng nền.

        Returns:
            Trạng thái phần cứng vừa được xếp, hoặc ``None`` nếu không cần
            làm gì (trùng trạng thái trước, hoặc dispatcher đã đóng).
        """
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
                # Cùng trạng thái: bật lại LED/kêu lại buzzer mỗi khung là
                # điều tệ nhất có thể làm với người đang ngồi học.
                return None

            # Xếp hàng trước rồi mới dựng luồng: nếu mục bị loại vì hàng đợi
            # đầy thì không để lại một luồng nền ngồi chờ vô ích.
            if not self._enqueue(_Request(state=state, force=force)):
                return None
            self._ensure_worker()
            self._requested = state
            return state

    def flush(self, timeout: float = 2.0) -> bool:
        """Chờ tới khi hàng đợi trống và lời gọi hiện tại chạy xong.

        Dùng khi thoát chương trình (để LED/buzzer kịp về trạng thái cuối) và
        trong test. Trả ``False`` nếu hết ``timeout``.
        """
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
        """Chọn ``(trạng thái phần cứng, ép buộc)`` cho một khung.

        ``force`` lấy thẳng từ ``update.alerts`` — tức là máy trạng thái đã
        áp cooldown; ở đây không đếm lại (spec §5.6, §5.7). Chỉ những sự kiện
        đã lọt cooldown mới nằm trong ``update.alerts``, nên ``ESCALATE`` bị
        chặn cooldown tự động im lặng, đúng như ``alert=allowed`` của
        ``state.py``.

        ``update.alerts`` chỉ chứa sự kiện ``alert=True``, nên mọi thứ đọc
        được ở đây đều phải kích phần cứng:

        - ``BREAK`` thắng tất cả: đó là nhắc nghỉ, âm thanh khác hẳn cảnh báo.
        - ``ESCALATE`` ánh xạ sang ``BAD``: phần cứng không có trạng thái
          "nặng hơn BAD", nên leo thang phát lại đèn đỏ + 2 tiếng buzzer.
        - Còn lại dùng ``update.state``.
        """
        if any(event.type == EVENT_BREAK for event in update.alerts):
            return HW_BREAK, True
        if any(event.type == EVENT_ESCALATE for event in update.alerts):
            return STATE_BAD, True
        if update.state not in STATES:
            # Phòng thủ: StateUpdate.state chỉ nên là GOOD/WARN/BAD/ABSENT.
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
        """Thêm mục, bỏ bớt khi đầy (gọi khi đã giữ ``_cond``).

        Ưu tiên bỏ mục không ép buộc: một tiếng buzzer cảnh báo/nhắc nghỉ đã
        chờ thì không nên bị khung tư thế bình thường đè mất. Nếu mọi mục
        đang chờ đều ép buộc thì bỏ mục cũ nhất (mới nhất là mục liên quan
        nhất). Mục mới không ép buộc mà không có chỗ thì bị bỏ chính nó —
        trạng thái tư thế bình thường luôn có khung sau để gửi lại.

        Returns:
            ``True`` nếu mục được nhận, ``False`` nếu bị bỏ.
        """
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
