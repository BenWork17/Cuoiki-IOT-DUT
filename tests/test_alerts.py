"""Unit test cho ``alerts.py`` (spec v2 §5.7).

Điểm cần khoá: tầng này **không** đếm cooldown lần nữa, không lặp lời gọi
phần cứng cho cùng một trạng thái, và không chặn vòng lặp chính khi
``set_state("BAD")`` ngủ đồng bộ. Đồng hồ thật được dùng ở đây (không có
đồng hồ giả như ``test_state.py``) vì đối tượng cần kiểm là thời gian chờ
của luồng, nhưng mọi chờ đều có ``timeout`` nhỏ để test không treo.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.alerts import HW_BREAK, AlertDispatcher  # noqa: E402
from posture_monitor.config import AlertsConfig  # noqa: E402
from posture_monitor.state import (  # noqa: E402
    EVENT_ALERT_START,
    EVENT_BREAK,
    EVENT_ESCALATE,
    STATE_ABSENT,
    STATE_BAD,
    STATE_GOOD,
    STATE_WARN,
    Event,
    StateUpdate,
)

#: Thời gian ``GpioRealHardware.set_state("BAD")`` ngủ đồng bộ thật:
#: ``_beep(2)`` = 2 × (0,3 s bật + 0,3 s nghỉ) = 1,2 s, cộng 0,3 s rung.
BAD_BLOCKING_S = 1.5

#: Chu kỳ khung ở ``target_fps: 5``.
FRAME_PERIOD_S = 0.2


class RecordingHardware:
    """Ghi lại mọi lời gọi ``set_state`` kèm cờ ``alert``; không đụng GPIO."""

    def __init__(self, delay_s: float = 0.0, fail_on: str | None = None):
        self.calls: list[str] = []
        self.alerts: list[bool] = []
        self.delay_s = delay_s
        self.fail_on = fail_on
        self._lock = threading.Lock()
        #: Bật ngay khi luồng nền **bắt đầu** một lời gọi, trước cả ``delay_s``.
        #: Nhờ nó test đo được trạng thái "phần cứng đang bận" mà không phải
        #: ngủ mù: ``calls`` chỉ được ghi sau khi ``delay_s`` trôi qua.
        self.started = threading.Event()

    def set_state(self, state: str, *, alert: bool = True) -> None:
        if self.delay_s:
            self.started.set()
            time.sleep(self.delay_s)
        with self._lock:
            self.calls.append(state)
            self.alerts.append(alert)
        if state == self.fail_on:
            raise RuntimeError("phần cứng hỏng")

    def wait_started(self, timeout: float = 2.0) -> None:
        """Chờ tới khi luồng nền thật sự chạm phần cứng."""
        if not self.started.wait(timeout):
            raise AssertionError(
                f"Chờ phần cứng bắt đầu nhưng chỉ thấy {self.calls!r}."
            )

    def close(self) -> None:
        pass


def update(
    state: str,
    *,
    events: tuple[Event, ...] = (),
    alerts: tuple[Event, ...] | None = None,
) -> StateUpdate:
    """Dựng ``StateUpdate`` tối thiểu cho test."""
    if alerts is None:
        alerts = tuple(event for event in events if event.alert)
    return StateUpdate(
        now=0.0,
        state=state,
        labels=frozenset(),
        score=50.0,
        sitting_s=0.0,
        events=events,
        alerts=alerts,
    )


def alert_event(event_type: str = EVENT_ALERT_START, *, alert: bool = True) -> Event:
    return Event(
        ts=0.0,
        type=event_type,
        label="HEAD_DOWN",
        duration_s=5.0,
        level=1,
        alert=alert,
    )


def make_dispatcher(hardware, **kwargs):
    return AlertDispatcher(hardware, AlertsConfig(), **kwargs)


def wait_for_calls(hardware, count: int, timeout: float = 2.0) -> None:
    """Chờ tới khi ``hardware`` nhận đủ ``count`` lời gọi (test không sleep mù)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(hardware.calls) >= count:
            return
        time.sleep(0.01)
    raise AssertionError(
        f"Chờ {count} lời gọi nhưng chỉ thấy {hardware.calls!r}."
    )


# ---------------------------------------------------------------------------
# Ánh xạ trạng thái
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "state", [STATE_GOOD, STATE_WARN, STATE_BAD, STATE_ABSENT]
)
def test_each_posture_state_is_forwarded(state):
    hardware = RecordingHardware()
    dispatcher = make_dispatcher(hardware)
    try:
        assert dispatcher.dispatch(update(state)) == state
        assert dispatcher.flush()
        assert hardware.calls == [state]
    finally:
        dispatcher.close()


def test_break_event_maps_to_break_state():
    hardware = RecordingHardware()
    dispatcher = make_dispatcher(hardware)
    try:
        event = Event(ts=0.0, type=EVENT_BREAK, label=None, alert=True)
        assert dispatcher.dispatch(update(STATE_GOOD, events=(event,))) == HW_BREAK
        assert dispatcher.flush()
        assert hardware.calls == [HW_BREAK]
    finally:
        dispatcher.close()


def test_break_wins_over_posture_state_in_same_update():
    hardware = RecordingHardware()
    dispatcher = make_dispatcher(hardware)
    try:
        event = Event(ts=0.0, type=EVENT_BREAK, label=None, alert=True)
        dispatcher.dispatch(update(STATE_BAD, events=(event,)))
        assert dispatcher.flush()
        assert hardware.calls == [HW_BREAK]
    finally:
        dispatcher.close()


def test_unknown_state_is_ignored_without_raising():
    hardware = RecordingHardware()
    dispatcher = make_dispatcher(hardware)
    try:
        assert dispatcher.dispatch(update("KHONG_TON_TAI")) is None
        assert dispatcher.flush()
        assert hardware.calls == []
    finally:
        dispatcher.close()


# ---------------------------------------------------------------------------
# Không lặp lời gọi cho cùng trạng thái
# ---------------------------------------------------------------------------

def test_same_state_is_sent_only_once_across_frames():
    hardware = RecordingHardware()
    dispatcher = make_dispatcher(hardware)
    try:
        for _ in range(20):
            dispatcher.dispatch(update(STATE_GOOD))
        assert dispatcher.flush()
        assert hardware.calls == [STATE_GOOD]
    finally:
        dispatcher.close()


def test_state_change_is_forwarded_again():
    """Đổi trạng thái thì phải gửi lại, dù khung trước trùng trạng thái cũ.

    Chờ hàng đợi rỗng giữa các bước để test chỉ đo luật "đổi thì gửi", không
    phụ thuộc việc luồng nền kịp lấy mục hay không (gộp trạng thái có test
    riêng bên dưới).
    """
    hardware = RecordingHardware()
    dispatcher = make_dispatcher(hardware)
    try:
        for state in (STATE_GOOD, STATE_WARN, STATE_WARN, STATE_BAD):
            dispatcher.dispatch(update(state))
            assert dispatcher.flush()
        assert hardware.calls == [STATE_GOOD, STATE_WARN, STATE_BAD]
    finally:
        dispatcher.close()


def test_intermediate_states_may_be_coalesced_when_hardware_is_busy():
    """Khi hàng đợi đầy, trạng thái trung gian bị gộp — trạng thái cuối vẫn tới.

    Đây là chủ ý, không phải lỗi: ``GOOD`` bị ``WARN`` vượt qua trong lúc
    buzzer còn kêu thì việc bật đèn xanh rồi vàng trong 1,5 s là vô nghĩa.

    Phải chờ ``GOOD`` **thật sự chạy** trước khi xếp hai mục sau. Nếu không,
    ba lời gọi ``dispatch`` liền nhau có thể vào hàng đợi trước khi luồng nền
    kịp lấy mục đầu; khi đó hàng đợi giữ ``GOOD`` và ``WARN``, và chính
    ``GOOD`` (mục không ép buộc đầu tiên) bị đẩy ra, làm phép khẳng định
    ``calls[0] == GOOD`` đỏ ngẫu nhiên trên máy đang tải nặng.
    """
    hardware = RecordingHardware(delay_s=0.4)
    dispatcher = make_dispatcher(hardware, queue_size=2)
    try:
        dispatcher.dispatch(update(STATE_GOOD))   # đang chạy
        hardware.wait_started()
        dispatcher.dispatch(update(STATE_WARN))   # vào hàng đợi
        dispatcher.dispatch(update(STATE_BAD))    # đẩy WARN ra (hàng đợi đầy)
        assert dispatcher.flush(timeout=3.0)
        assert hardware.calls[0] == STATE_GOOD
        assert hardware.calls[-1] == STATE_BAD
    finally:
        dispatcher.close()


def test_same_state_with_alert_event_is_forced():
    """Sự kiện ``alert=True`` phải kích lại dù trạng thái không đổi."""
    hardware = RecordingHardware()
    dispatcher = make_dispatcher(hardware)
    try:
        dispatcher.dispatch(update(STATE_BAD))
        assert dispatcher.flush()
        dispatcher.dispatch(update(STATE_BAD, events=(alert_event(),)))
        assert dispatcher.flush()
        assert hardware.calls == [STATE_BAD, STATE_BAD]
    finally:
        dispatcher.close()


def test_event_with_alert_false_does_not_force_hardware():
    """Cooldown đã do ``state.py`` áp; ``alert=False`` nghĩa là im lặng."""
    hardware = RecordingHardware()
    dispatcher = make_dispatcher(hardware)
    try:
        dispatcher.dispatch(update(STATE_BAD))
        assert dispatcher.flush()
        # Cùng trạng thái + sự kiện bị cooldown → không gọi lại lần nào.
        dispatcher.dispatch(
            update(STATE_BAD, events=(alert_event(alert=False),))
        )
        assert dispatcher.flush()
        assert hardware.calls == [STATE_BAD]
    finally:
        dispatcher.close()


def test_alert_false_still_forwards_a_state_change():
    """``alert=False`` vẫn đổi LED — chỉ tiếng là phải im.

    Đổi đèn và kêu là hai việc khác nhau: trạng thái luôn được chuyển xuống
    phần cứng, còn cờ ``alert=False`` bảo nó đừng phát buzzer/rung.
    """
    hardware = RecordingHardware()
    dispatcher = make_dispatcher(hardware)
    try:
        dispatcher.dispatch(update(STATE_GOOD))
        dispatcher.dispatch(
            update(STATE_WARN, events=(alert_event(alert=False),))
        )
        assert dispatcher.flush()
        assert hardware.calls == [STATE_GOOD, STATE_WARN]
        assert hardware.alerts == [False, False]
    finally:
        dispatcher.close()


def test_state_change_to_bad_without_alert_changes_led_silently():
    """Đổi sang BAD nhưng sự kiện bị cooldown: đèn đỏ, không tiếng."""
    hardware = RecordingHardware()
    dispatcher = make_dispatcher(hardware)
    try:
        dispatcher.dispatch(update(STATE_WARN))
        assert dispatcher.flush()
        # ``alert_start`` sinh ra nhưng ``state.py`` đã đặt ``alert=False``.
        dispatcher.dispatch(
            update(STATE_BAD, events=(alert_event(alert=False),))
        )
        assert dispatcher.flush()
        assert hardware.calls == [STATE_WARN, STATE_BAD]
        assert hardware.alerts == [False, False]
    finally:
        dispatcher.close()


def test_state_change_to_bad_with_alert_sounds():
    """Đổi sang BAD kèm sự kiện được phép: tiếng phải phát."""
    hardware = RecordingHardware()
    dispatcher = make_dispatcher(hardware)
    try:
        dispatcher.dispatch(update(STATE_WARN))
        assert dispatcher.flush()
        dispatcher.dispatch(update(STATE_BAD, events=(alert_event(),)))
        assert dispatcher.flush()
        assert hardware.calls == [STATE_WARN, STATE_BAD]
        assert hardware.alerts == [False, True]
    finally:
        dispatcher.close()


def test_break_is_always_sounded():
    hardware = RecordingHardware()
    dispatcher = make_dispatcher(hardware)
    try:
        event = Event(ts=0.0, type=EVENT_BREAK, label=None, alert=True)
        dispatcher.dispatch(update(STATE_GOOD, events=(event,)))
        assert dispatcher.flush()
        assert hardware.calls == [HW_BREAK]
        assert hardware.alerts == [True]
    finally:
        dispatcher.close()


def test_hardware_without_alert_keyword_still_gets_state():
    """Triển khai ``Hardware`` cũ (một tham số) không được làm chết luồng."""
    calls: list[str] = []

    class LegacyHardware:
        def set_state(self, state):
            calls.append(state)

        def close(self):
            pass

    dispatcher = AlertDispatcher(LegacyHardware(), AlertsConfig())
    try:
        dispatcher.dispatch(update(STATE_GOOD))
        assert dispatcher.flush()
        dispatcher.dispatch(update(STATE_BAD, events=(alert_event(),)))
        assert dispatcher.flush()
        assert calls == [STATE_GOOD, STATE_BAD]
    finally:
        dispatcher.close()


def test_true_type_error_inside_set_state_is_not_retried():
    """Lỗi thật trong ``set_state`` chỉ được gọi một lần, không chạy lại."""
    calls: list[str] = []

    class ExplodingHardware:
        def set_state(self, state, *, alert=True):
            calls.append(state)
            raise TypeError("lỗi thật bên trong, không phải sai chữ ký")

        def close(self):
            pass

    dispatcher = AlertDispatcher(ExplodingHardware(), AlertsConfig())
    try:
        dispatcher.dispatch(update(STATE_BAD, events=(alert_event(),)))
        assert dispatcher.flush()
        assert calls == [STATE_BAD]
    finally:
        dispatcher.close()


# ---------------------------------------------------------------------------
# Leo thang (ESCALATE)
# ---------------------------------------------------------------------------

def escalate_event(*, alert: bool) -> Event:
    """Sự kiện leo thang như ``state.py`` sinh ra: ``level=2``, ``alert`` theo cooldown."""
    return Event(
        ts=0.0,
        type=EVENT_ESCALATE,
        label="HEAD_DOWN",
        duration_s=60.0,
        level=2,
        alert=alert,
    )


def test_escalate_with_alert_true_repeats_bad_alert():
    """Leo thang khi đã ở BAD phải kêu lại (đèn đỏ + buzzer), không bị nuốt."""
    hardware = RecordingHardware()
    dispatcher = make_dispatcher(hardware)
    try:
        dispatcher.dispatch(update(STATE_BAD))
        assert dispatcher.flush()
        dispatcher.dispatch(update(STATE_BAD, events=(escalate_event(alert=True),)))
        assert dispatcher.flush()
        assert hardware.calls == [STATE_BAD, STATE_BAD]
    finally:
        dispatcher.close()


def test_escalate_with_alert_false_stays_silent():
    """``state.py`` đặt ``alert=allowed``; escalate bị cooldown thì không kêu."""
    hardware = RecordingHardware()
    dispatcher = make_dispatcher(hardware)
    try:
        dispatcher.dispatch(update(STATE_BAD))
        assert dispatcher.flush()
        dispatcher.dispatch(
            update(STATE_BAD, events=(escalate_event(alert=False),))
        )
        assert dispatcher.flush()
        assert hardware.calls == [STATE_BAD]
    finally:
        dispatcher.close()


def test_escalate_alert_false_does_not_force_break_or_other_state():
    hardware = RecordingHardware()
    dispatcher = make_dispatcher(hardware)
    try:
        dispatcher.dispatch(update(STATE_GOOD))
        assert dispatcher.flush()
        dispatcher.dispatch(
            update(STATE_GOOD, events=(escalate_event(alert=False),))
        )
        assert dispatcher.flush()
        assert hardware.calls == [STATE_GOOD]
    finally:
        dispatcher.close()


# ---------------------------------------------------------------------------
# Không chặn vòng lặp chính
# ---------------------------------------------------------------------------

def test_dispatch_returns_before_slow_hardware_finishes():
    """``set_state("BAD")`` ngủ đồng bộ; ``dispatch`` phải trả về ngay."""
    hardware = RecordingHardware(delay_s=0.6)
    dispatcher = make_dispatcher(hardware)
    try:
        started = time.monotonic()
        dispatcher.dispatch(update(STATE_BAD))
        elapsed = time.monotonic() - started
        # Ngưỡng rộng rãi: chỉ cần chứng minh KHÔNG chờ hết 0,6 s.
        assert elapsed < 0.3, f"dispatch chặn {elapsed:.2f} s"
        assert dispatcher.flush(timeout=3.0)
        assert hardware.calls == [STATE_BAD]
    finally:
        dispatcher.close()


def test_dispatch_is_not_blocked_by_real_bad_blocking_time():
    """Mô phỏng đúng 1,5 s ngủ đồng bộ của ``set_state("BAD")`` thật.

    Đây là bằng chứng cho handoff: 1,5 s gấp ~7,5 lần chu kỳ khung 0,2 s, nên
    nếu ``dispatch`` gọi thẳng phần cứng thì vòng lặp chính sẽ trễ ngay khi
    cảnh báo nổ. Test đo thời gian ``dispatch`` trả về trên phần cứng chậm
    đúng bằng thời gian thật.
    """
    hardware = RecordingHardware(delay_s=BAD_BLOCKING_S)
    dispatcher = make_dispatcher(hardware)
    try:
        started = time.monotonic()
        dispatcher.dispatch(update(STATE_BAD))
        elapsed = time.monotonic() - started
        assert elapsed < FRAME_PERIOD_S, (
            f"dispatch chặn {elapsed:.3f} s, vượt chu kỳ khung "
            f"{FRAME_PERIOD_S} s"
        )

        # Vòng lặp chính vẫn chạy tiếp trong lúc phần cứng đang bận kêu.
        frame_times: list[float] = []
        for state in (STATE_WARN, STATE_GOOD, STATE_WARN, STATE_GOOD):
            tick = time.monotonic()
            dispatcher.dispatch(update(state))
            frame_times.append(time.monotonic() - tick)
        assert max(frame_times) < FRAME_PERIOD_S

        assert dispatcher.flush(timeout=BAD_BLOCKING_S + 5.0)
        assert hardware.calls[-1] == STATE_GOOD
    finally:
        dispatcher.close()


def test_frames_keep_flowing_while_hardware_is_busy():
    hardware = RecordingHardware(delay_s=0.3)
    dispatcher = make_dispatcher(hardware)
    try:
        dispatcher.dispatch(update(STATE_BAD))
        started = time.monotonic()
        for _ in range(10):
            dispatcher.dispatch(update(STATE_WARN))
        assert time.monotonic() - started < 0.2
        assert dispatcher.flush(timeout=3.0)
        # Chỉ trạng thái cuối còn ý nghĩa; các khung WARN lặp bị gộp.
        assert hardware.calls[-1] == STATE_WARN
    finally:
        dispatcher.close()


# ---------------------------------------------------------------------------
# Hàng đợi có giới hạn
# ---------------------------------------------------------------------------

def test_queue_is_bounded_and_keeps_latest_state():
    hardware = RecordingHardware(delay_s=0.2)
    dispatcher = make_dispatcher(hardware, queue_size=1)
    try:
        dispatcher.dispatch(update(STATE_GOOD))
        # Đẩy nhiều trạng thái khác nhau trong lúc luồng đang bận.
        for state in (STATE_WARN, STATE_BAD, STATE_ABSENT, STATE_GOOD):
            dispatcher.dispatch(update(state))
        assert dispatcher.flush(timeout=3.0)
        assert hardware.calls[-1] == STATE_GOOD
        # 1 lời gọi đang chạy + tối đa 1 mục chờ, không dồn 5 lời gọi.
        assert len(hardware.calls) <= 3
    finally:
        dispatcher.close()


def test_pending_alert_event_survives_queue_pressure():
    """Khung tư thế bình thường không được đè mất một cảnh báo đang chờ."""
    hardware = RecordingHardware(delay_s=0.2)
    dispatcher = make_dispatcher(hardware, queue_size=1)
    try:
        dispatcher.dispatch(update(STATE_GOOD))
        dispatcher.dispatch(update(STATE_BAD, events=(alert_event(),)))
        dispatcher.dispatch(update(STATE_GOOD))
        assert dispatcher.flush(timeout=3.0)
        assert STATE_BAD in hardware.calls
    finally:
        dispatcher.close()


def test_invalid_queue_size_is_rejected():
    with pytest.raises(ValueError):
        AlertDispatcher(RecordingHardware(), queue_size=0)


# ---------------------------------------------------------------------------
# Lỗi phần cứng và vòng đời
# ---------------------------------------------------------------------------

def test_hardware_exception_never_escapes():
    hardware = RecordingHardware(fail_on=STATE_BAD)
    dispatcher = make_dispatcher(hardware)
    try:
        dispatcher.dispatch(update(STATE_BAD))
        assert dispatcher.flush()
        # Luồng vẫn sống và xử lý được trạng thái tiếp theo.
        dispatcher.dispatch(update(STATE_GOOD))
        assert dispatcher.flush()
        assert hardware.calls == [STATE_BAD, STATE_GOOD]
    finally:
        dispatcher.close()


def test_close_is_idempotent_and_stops_dispatch():
    hardware = RecordingHardware()
    dispatcher = make_dispatcher(hardware)
    dispatcher.dispatch(update(STATE_GOOD))
    assert dispatcher.flush()
    dispatcher.close()
    dispatcher.close()
    assert dispatcher.closed is True
    assert dispatcher.dispatch(update(STATE_BAD)) is None
    assert hardware.calls == [STATE_GOOD]


def test_close_drains_pending_state_before_stopping():
    """Đóng dispatcher không được nuốt trạng thái cuối đang chờ trong hàng đợi."""
    hardware = RecordingHardware(delay_s=0.2)
    dispatcher = make_dispatcher(hardware)
    dispatcher.dispatch(update(STATE_GOOD))
    dispatcher.dispatch(update(STATE_WARN))
    dispatcher.close()
    assert hardware.calls == [STATE_GOOD, STATE_WARN]


def test_dispatcher_does_not_close_owned_hardware():
    """Dispatcher chỉ mượn ``Hardware``; đóng nó là việc của bên tạo."""
    closed: list[bool] = []

    class HardwareWithClose(RecordingHardware):
        def close(self) -> None:
            closed.append(True)

    hardware = HardwareWithClose()
    dispatcher = make_dispatcher(hardware)
    dispatcher.close()
    assert closed == []


def test_context_manager_closes_worker():
    hardware = RecordingHardware()
    with make_dispatcher(hardware) as dispatcher:
        dispatcher.dispatch(update(STATE_GOOD))
        assert dispatcher.flush()
    assert dispatcher.closed is True


# ---------------------------------------------------------------------------
# Hồi quy với máy trạng thái thật: cooldown phải chặn *tiếng*, không chặn đèn
# ---------------------------------------------------------------------------

def test_cooldown_blocks_sound_but_not_led_with_real_state_machine():
    """Kịch bản Lead tái hiện: BAD lần hai trong cooldown 30 s.

    Pipeline thật ``StateMachine`` → ``AlertDispatcher`` → hardware ghi lại,
    dùng ``config.yaml`` mặc định (``bad_hold_s=5``, ``good_hold_s=2``,
    ``alert_cooldown_s=30``). Ở ``t=20`` máy trạng thái sinh ``alert_start``
    với ``alert=False``; khi đó:
    """
    from posture_monitor.classifier import HEAD_DOWN
    from posture_monitor.config import load_config
    from posture_monitor.state import StateMachine

    config = load_config(_REPO_ROOT / "config.yaml")
    state_machine = StateMachine(config.timing)
    hardware = RecordingHardware()
    dispatcher = AlertDispatcher(hardware, config.alerts)

    # (thời điểm, nhãn) — đúng chuỗi Lead đã chạy: nhãn xấu rời đi ở t=11,
    # ``good_hold_s=2`` nên sự kiện đóng ở t=13.
    steps = [
        (0.0, [HEAD_DOWN]),    # WARN
        (5.0, [HEAD_DOWN]),    # BAD, alert_start alert=True  → cảnh báo #1
        (11.0, []),            # nhãn xấu vắng, bắt đầu đếm good_hold
        (13.0, []),            # GOOD, alert_end
        (15.0, [HEAD_DOWN]),   # WARN
        (20.0, [HEAD_DOWN]),   # BAD, alert_start alert=False (còn cooldown)
    ]
    try:
        for now, labels in steps:
            result = state_machine.update(now, labels, 50.0)
            dispatcher.dispatch(result)
            assert dispatcher.flush()

        # Đèn vẫn theo tư thế: mỗi lần đổi trạng thái đều tới phần cứng.
        assert hardware.calls == [
            STATE_WARN, STATE_BAD, STATE_GOOD, STATE_WARN, STATE_BAD,
        ]
        # Nhưng chỉ đúng một lần BAD được phép kêu — lần thứ hai bị cooldown.
        bad_sounds = [
            alert
            for state, alert in zip(hardware.calls, hardware.alerts)
            if state == STATE_BAD
        ]
        assert bad_sounds == [True, False]
        assert sum(hardware.alerts) == 1
    finally:
        dispatcher.close()
