"""Nối ``held`` (presence + phone) vào ``schedule.should_alert`` trong vòng lặp.

Ba mảnh đã có từ trước — ``PresenceTracker``, ``PhoneSignal`` và
``schedule.should_alert`` — nhưng chưa mảnh nào được gọi từ ``src/``: presence
chỉ xuất hiện trong ``tests/``, phone chỉ trong ``benchmark.py``, còn
``should_alert`` chỉ có ``def`` của chính nó. File này khoá phần nối dây đó
ở đúng mức quan sát được: mỗi khung, ``held`` được tính lại từ đầu rồi đưa qua
``should_alert``, và quyết định duy nhất được đưa ra loa.

Vì sao phải chạy ``_monitor_loop`` thật thay vì gọi ``should_alert`` trực tiếp:
một test gọi thẳng ``should_alert`` sẽ xanh kể cả khi vòng lặp không bao giờ
gọi nó. Ở đây vòng lặp thật chạy với camera/estimator/loa giả, còn
``PresenceTracker`` và ``should_alert`` là bản thật. Chỉ hai chỗ đổi:
``PhoneSignal`` (để điều khiển ``observe`` trả ``None``) và ``SpeakerAlerter``
(để đếm lần phát mà không cần loa).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor import schedule as schedule_mod  # noqa: E402
from posture_monitor import state as state_mod  # noqa: E402
from posture_monitor.classifier import HEAD_DOWN  # noqa: E402
from posture_monitor.config import (  # noqa: E402
    AlertsConfig,
    Config,
    PresenceConfig,
    TimingConfig,
)
from posture_monitor.pose import PoseResult  # noqa: E402
from posture_monitor.schedule import (  # noqa: E402
    DAY_NAMES,
    KindSettings,
    ScheduleConfig,
    TimeWindow,
)

#: Keypoint thân trên đủ tin cậy: presence cần >= 2 điểm trong 7 điểm đầu.
_PRESENT_CONF = np.array(
    [0.9] * 7 + [0.0] * 10, dtype=np.float32
)
_ABSENT_CONF = np.zeros(17, dtype=np.float32)


def _pose(present: bool) -> PoseResult | None:
    if not present:
        return None
    xy = np.full((17, 2), 100.0, dtype=np.float32)
    bbox = np.array([10.0, 10.0, 200.0, 300.0], dtype=np.float32)
    return PoseResult(xy=xy, conf=_PRESENT_CONF, bbox=bbox)


class _FakeSource:
    backend = "fake"

    def __init__(self, frames: int) -> None:
        self.frames_left = frames

    def read(self):
        if self.frames_left <= 0:
            return None
        self.frames_left -= 1
        return np.zeros((48, 64, 3), dtype=np.uint8)

    def close(self) -> None:
        pass


class _ScriptedEstimator:
    """Trả lần lượt các kết quả trong ``script`` (``PoseResult`` hoặc ``None``)."""

    backend = "fake"

    def __init__(self, script) -> None:
        self._script = list(script)
        self._index = 0

    def detect(self, _frame):
        result = self._script[min(self._index, len(self._script) - 1)]
        self._index += 1
        return result


class _QueueClock:
    """Đồng hồ đơn điệu: mỗi lần gọi lấy giá trị kế tiếp, hết thì lặp lại cuối."""

    def __init__(self, values) -> None:
        self._values = list(values)
        self._index = 0

    def __call__(self) -> float:
        value = self._values[min(self._index, len(self._values) - 1)]
        self._index += 1
        return value


class _StepWallClock:
    """Đồng hồ thời gian thực: mỗi lần gọi cộng thêm ``step_s``."""

    def __init__(self, start: datetime, step_s: float = 1.0) -> None:
        self._current = start
        self._step = timedelta(seconds=step_s)

    def __call__(self) -> datetime:
        value = self._current
        self._current = self._current + self._step
        return value


class _RecordingAlerter:
    """Loa giả: ghi lại loại cảnh báo thay vì phát ra loa."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, float | None]] = []

    @property
    def available(self) -> bool:
        return False

    def prepare(self) -> None:
        pass

    def alert(self, kind, *, now=None):
        self.calls.append((kind, now))
        return None

    @classmethod
    def from_config(cls, _config, **_kwargs):
        return _AlerterHolder.instance


class _AlerterHolder:
    instance: _RecordingAlerter


class _RecordingDispatcher:
    """Bộ đẩy phần cứng giả: ghi lại đúng ``StateUpdate`` mà vòng lặp đẩy đi.

    Cần quan sát ``StateUpdate`` **sau** khi vòng lặp đã quyết định nội dung
    ``labels``/``alerts`` — nhờ vậy test bắt được các bước biến đổi nằm giữa
    ``classify`` và tầng cảnh báo, chứ không chỉ kiểm một hàm phụ.
    """

    def __init__(self) -> None:
        self.updates: list = []

    def dispatch(self, update) -> None:
        self.updates.append(update)

    def close(self) -> None:
        pass


def _make_phone_signal_fake(script):
    """``PhoneSignal`` giả: mỗi lần ``observe`` tiêu một mục của ``script``.

    Mỗi mục là ``(kết_quả, held_s)``. ``held_s`` đứng yên ở giá trị của lần
    quan sát gần nhất — đúng hành vi thật của ``phone_detector.py`` khi
    ``observe`` trả ``None`` trước ``_update_contact``.
    """

    class _FakePhoneSignal:
        last_instance = None

        def __init__(self, _config) -> None:
            self._script = list(script)
            self._calls = 0
            self._held = 0.0
            _FakePhoneSignal.last_instance = self

        @property
        def held_s(self) -> float:
            return self._held

        def observe(self, _frame, _keypoints, _now):
            index = min(self._calls, len(self._script) - 1)
            self._calls += 1
            result, held = self._script[index]
            if result is not None:
                self._held = held
            return result

    return _FakePhoneSignal


def _schedule(inside: bool, phone_enabled: bool = True) -> ScheduleConfig:
    """Lịch dạy học mà ``_WALL_TIME`` hoặc nằm trong hoặc nằm ngoài."""
    day = DAY_NAMES[_WALL_TIME.weekday()]
    other_day = DAY_NAMES[(_WALL_TIME.weekday() + 1) % 7]
    window_day = day if inside else other_day
    return ScheduleConfig(
        enabled=True,
        windows=(
            TimeWindow(
                days=(window_day,),
                start=datetime.strptime("19:00", "%H:%M").time(),
                end=datetime.strptime("21:30", "%H:%M").time(),
            ),
        ),
        kinds={
            "leave_frame": KindSettings(enabled=True, cooldown_s=60.0, hold_s=5.0),
            "phone": KindSettings(
                enabled=phone_enabled, cooldown_s=120.0, hold_s=5.0
            ),
            "stranger": KindSettings(enabled=True, cooldown_s=300.0, hold_s=5.0),
        },
    )


#: Thời điểm cố định nằm trong khung 19:00–21:30 (thứ nào cũng dựng được khung).
_WALL_TIME = datetime(2026, 10, 28, 19, 30)  # thứ Tư


def _run(monkeypatch, tmp_path, *, estimator, frames, clock, wall_clock, config,
         phone_script, people=None, logger=None, baseline=None, dispatcher=None,
         state=None):
    """Chạy ``_monitor_loop`` thật với các seam đã thay, trả kết quả quan sát.

    ``baseline`` mặc định là baseline rỗng (mọi đặc trưng ``None``) để các bài
    cũ không bị ảnh hưởng; bài mới truyền baseline thật khi cần ``classify``
    sinh ra nhãn tư thế. ``dispatcher``/``state`` chuyển thẳng vào vòng lặp để
    quan sát bản ``StateUpdate`` mà nó thật sự đẩy đi.
    """
    import posture_monitor.__main__ as cli
    import posture_monitor.calibration as calibration_mod
    import posture_monitor.phone_detector as phone_mod
    import posture_monitor.speaker_alert as speaker_mod
    from posture_monitor.calibration import Baseline
    from posture_monitor.features import ALL_NAMES

    if baseline is None:
        baseline = Baseline(
            values={name: None for name in ALL_NAMES},
            view="front",
            width=640,
            height=480,
            created_at="",
            frames=0,
        )
    monkeypatch.setattr(calibration_mod, "load", lambda _path: baseline)
    monkeypatch.setattr(cli.cv2, "namedWindow", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "imshow", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "destroyAllWindows", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "getWindowProperty", lambda *a, **k: 1.0)
    keys = [0] * (frames - 1) + [ord("q")]
    monkeypatch.setattr(
        cli.cv2, "waitKey", lambda *a, **k: keys.pop(0) if keys else ord("q")
    )

    monkeypatch.setattr(
        phone_mod, "PhoneSignal", _make_phone_signal_fake(phone_script)
    )
    alerter = _RecordingAlerter()
    _AlerterHolder.instance = alerter
    monkeypatch.setattr(speaker_mod, "SpeakerAlerter", _RecordingAlerter)

    # Bọc ``should_alert`` thật để ghi lại ``held`` mà vòng lặp truyền vào.
    observed: list[dict[str, float]] = []
    real_should_alert = schedule_mod.should_alert

    def _spy(schedule, now, *, held, last_alert_at=None, kinds=None):
        observed.append(dict(held))
        return real_should_alert(
            schedule, now, held=held, last_alert_at=last_alert_at, kinds=kinds
        )

    monkeypatch.setattr(schedule_mod, "should_alert", _spy)

    exit_code = cli._monitor_loop(
        estimator,
        _FakeSource(frames),
        config,
        logger if logger is not None else _QuietLogger(),
        people=people,
        state=state,
        dispatcher=dispatcher,
        clock=clock,
        wall_clock=wall_clock,
    )
    return exit_code, observed, alerter


class _QuietLogger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def info(self, *a, **k) -> None:
        pass

    def warning(self, fmt, *args) -> None:
        self.warnings.append(fmt % args if args else str(fmt))

    def error(self, *args, **kwargs) -> None:
        pass

    def exception(self, *args, **kwargs) -> None:
        pass


def _config(schedule: ScheduleConfig) -> Config:
    config = Config()
    config.schedule = schedule
    config.presence = PresenceConfig(absent_grace_s=3.0)
    return config


def test_roi_khung_qua_grace_va_hold_thi_co_quyet_dinh(monkeypatch, tmp_path):
    """Người rời khung quá ``absent_grace_s`` → ``held`` vượt ``hold_s`` → có quyết định.

    Đo bằng số: khung 4 vắng liên tục 6 s (>= ``leave_frame.hold_s`` = 5).
    ``held["leave_frame"]`` phải đúng bằng 6.0 ở khung đó — gán cứng ``0.0``
    (mutation a) làm cả chuỗi không còn quyết định nào.
    """
    frames = 6
    # Hai giá trị mỗi khung: một cho ``alert_now``, một cho đồng hồ của
    # PresenceTracker. Cùng giá trị để đọc dễ.
    clock = _QueueClock([0, 0, 0, 0, 10, 10, 12, 12, 16, 16, 20, 20])
    estimator = _ScriptedEstimator(
        [_pose(True), _pose(True), None, None, None, None]
    )
    config = _config(_schedule(inside=True))

    exit_code, observed, alerter = _run(
        monkeypatch,
        tmp_path,
        estimator=estimator,
        frames=frames,
        clock=clock,
        wall_clock=_StepWallClock(_WALL_TIME),
        config=config,
        phone_script=[(None, 0.0)],
    )

    assert exit_code == 0
    assert observed, "vòng lặp phải gọi should_alert"
    assert 6.0 in [held.get("leave_frame") for held in observed], observed
    assert [kind for kind, _ in alerter.calls] == ["leave_frame"], alerter.calls


def test_ngoai_gio_hoc_khong_co_quyet_dinh(monkeypatch, tmp_path):
    """Ngoài khung giờ: ``held`` vẫn lớn nhưng ``should_alert`` trả ``None``."""
    frames = 6
    clock = _QueueClock([0, 0, 0, 0, 10, 10, 12, 12, 16, 16, 20, 20])
    estimator = _ScriptedEstimator(
        [_pose(True), _pose(True), None, None, None, None]
    )
    # Cùng ``held`` như bài trên, nhưng lịch chỉ áp cho ngày khác.
    config = _config(_schedule(inside=False))

    exit_code, observed, alerter = _run(
        monkeypatch,
        tmp_path,
        estimator=estimator,
        frames=frames,
        clock=clock,
        wall_clock=_StepWallClock(_WALL_TIME),
        config=config,
        phone_script=[(None, 0.0)],
    )

    assert exit_code == 0
    assert 6.0 in [held.get("leave_frame") for held in observed], observed
    assert alerter.calls == [], "ngoài giờ học không được phát cảnh báo"


def test_phone_result_none_thi_held_bang_khong(monkeypatch, tmp_path):
    """``observe`` trả ``None`` → ``held["phone"]`` phải là 0.0, không phải giá trị cũ.

    ``phone_detector.py`` trả ``None`` **trước** ``_update_contact`` khi
    keypoint không dùng được, nên ``held_s`` đứng yên ở giá trị cũ (ở đây giả
    lập là 50 s từ khung đầu). Đọc thẳng ``held_s`` (mutation c) khiến người
    vừa quay lưng bị coi là "đã chạm 50 giây" và cảnh báo điện thoại bắn ra ở
    mọi khung — trong khi khung đó hoàn toàn không xét được.
    """
    frames = 5
    clock = _QueueClock([0, 0, 1, 1, 2, 2, 3, 3, 4, 4])

    class _PhoneResult:
        co_cham = True

    # Khung 0 có kết quả nên ``held_s`` thành 50.0; khung 1-4 trả ``None`` và
    # ``_held_s`` đứng yên đúng 50.0 — giá trị cũ mà code đúng không được tin.
    phone_script = [
        (_PhoneResult(), 50.0),
        (None, 50.0),
        (None, 50.0),
        (None, 50.0),
        (None, 50.0),
    ]
    estimator = _ScriptedEstimator([_pose(True)] * frames)
    schedule = _schedule(inside=True)
    # Nâng ``hold_s`` của phone để khung 0 (held 50) không tự thành cảnh báo;
    # bài này chỉ kiểm đúng việc ``None`` phải cho 0.0.
    schedule.kinds["phone"] = KindSettings(
        enabled=True, cooldown_s=120.0, hold_s=100.0
    )
    config = _config(schedule)

    exit_code, observed, alerter = _run(
        monkeypatch,
        tmp_path,
        estimator=estimator,
        frames=frames,
        clock=clock,
        wall_clock=_StepWallClock(_WALL_TIME),
        config=config,
        phone_script=phone_script,
    )

    assert exit_code == 0
    assert len(observed) == frames, observed
    # Khung 0 có kết quả nên giữ đúng 50.0…
    assert observed[0]["phone"] == pytest.approx(50.0), observed[0]
    # …các khung ``None`` phải là 0.0, không phải 50.0 đứng yên.
    assert all(held["phone"] == 0.0 for held in observed[1:]), observed[1:]
    assert alerter.calls == [], "giá trị held_s cũ không được thành cảnh báo"


def test_cooldown_chi_mot_canh_bao_cho_hai_khung_lien_tiep(monkeypatch, tmp_path):
    """Hai khung liên tiếp cùng vượt ngưỡng → **một** cảnh báo, nhờ ``last_alert_at``.

    Bỏ dòng ``last_alert_at[kind] = ...`` (mutation b) thì ``should_alert``
    không có mốc cooldown nào và bắn ở mọi khung từ đó về sau.
    """
    frames = 6
    # absents: khung 0-1 có người, khung 2-5 vắng; 16 s và 20 s đều > 5.
    clock = _QueueClock([0, 0, 0, 0, 10, 10, 12, 12, 16, 16, 20, 20])
    estimator = _ScriptedEstimator(
        [_pose(True), _pose(True), None, None, None, None]
    )
    config = _config(_schedule(inside=True))

    exit_code, observed, alerter = _run(
        monkeypatch,
        tmp_path,
        estimator=estimator,
        frames=frames,
        clock=clock,
        # Bước 1 s/lần gọi: khoảng cách giữa hai khung nhỏ hơn cooldown 60 s.
        wall_clock=_StepWallClock(_WALL_TIME, step_s=1.0),
        config=config,
        phone_script=[(None, 0.0)],
    )

    assert exit_code == 0
    # Hai khung cuối đều đã vượt hold_s; chỉ khung đầu tiên được phát.
    over_threshold = [
        held for held in observed if held.get("leave_frame", 0.0) >= 5.0
    ]
    assert len(over_threshold) >= 2, observed
    assert len(alerter.calls) == 1, alerter.calls


# ---------------------------------------------------------------------------
# Bộ lọc nhãn tư thế và công tắc GPIO: hai bước biến đổi nằm **trong** vòng
# lặp, giữa ``classify`` và tầng cảnh báo. Hai hàm phụ (``_loc_nhan_tu_the``,
# ``AlertsConfig.gpio_alert_enabled``) đều đã có test riêng, nhưng test riêng
# của chúng vẫn xanh khi vòng lặp **quên gọi**. Hai bài dưới đây chạy vòng
# lặp thật và quan sát đúng ``StateUpdate`` mà nó đẩy cho ``dispatcher``.
# ---------------------------------------------------------------------------

#: Baseline "đầu rất cao": ``head_height`` chuẩn là 1.0, nên khung nào có
#: ``head_height`` thấp hơn 0.70 đều vượt ``thresholds.head_down_ratio`` và
#: ``classify`` sinh đúng nhãn ``HEAD_DOWN``. ``shoulder_width``/
#: ``shoulder_mid_x`` là bắt buộc để ``extract`` tính được ``closeness``/
#: ``lean_x`` (nếu thiếu, ``Baseline`` ném ``CalibrationError``).
_BASE_HEAD_HEIGHT = 1.0


def _baseline_dau_thap():
    """Baseline front làm ``HEAD_DOWN`` bắn ra chắc chắn ở mọi khung."""
    from posture_monitor.calibration import Baseline
    from posture_monitor.features import ALL_NAMES

    values = {name: None for name in ALL_NAMES}
    values.update(
        {
            "shoulder_width": 100.0,
            "shoulder_mid_x": 100.0,
            "head_height": _BASE_HEAD_HEIGHT,
            "shoulder_tilt_deg": 0.0,
            "head_tilt_deg": 0.0,
            "head_yaw": 0.0,
            "lean_x": 0.0,
        }
    )
    return Baseline(
        values=values, view="front", width=640, height=480, created_at="", frames=0
    )


def _pose_head_down() -> PoseResult:
    """Người ngồi với đầu cúi thấp: vai ngang, mũi thấp hơn vai rõ rệt.

    ``shoulder_width`` = 100 px nên ``head_height`` = (mid_y - nose_y) / 100.
    Đặt mũi **dưới** vai (``nose_y > mid_y``) cho ``head_height`` âm — nhỏ
    hơn hẳn ``1.0 * 0.70`` nên ``HEAD_DOWN`` luôn bật.
    """
    xy = np.full((17, 2), 100.0, dtype=np.float32)
    xy[5] = (50.0, 100.0)   # vai trái
    xy[6] = (150.0, 100.0)  # vai phải → mid_y = 100, width = 100
    xy[0] = (100.0, 200.0)  # mũi thấp hơn vai 100 px → head_height = -1.0
    conf = np.zeros(17, dtype=np.float32)
    conf[[0, 5, 6]] = 0.9
    bbox = np.array([10.0, 10.0, 200.0, 300.0], dtype=np.float32)
    return PoseResult(xy=xy, conf=conf, bbox=bbox)


def _run_voi_dispatch(monkeypatch, tmp_path, *, config, frames=6,
                      estimator=None, baseline=None, state=None):
    """Chạy vòng lặp thật với dispatcher ghi lại; trả ``(exit, updates)``."""
    dispatcher = _RecordingDispatcher()
    if estimator is None:
        estimator = _ScriptedEstimator([_pose_head_down()] * frames)
    if baseline is None:
        baseline = _baseline_dau_thap()
    exit_code, _observed, _alerter = _run(
        monkeypatch,
        tmp_path,
        estimator=estimator,
        frames=frames,
        clock=_QueueClock([float(i) for i in range(2 * frames)]),
        wall_clock=_StepWallClock(_WALL_TIME),
        config=config,
        phone_script=[(None, 0.0)],
        baseline=baseline,
        dispatcher=dispatcher,
        state=state,
    )
    return exit_code, dispatcher.updates


def test_vong_lap_ap_dung_bo_loc_nhan_tu_the(monkeypatch, tmp_path):
    """``_monitor_loop`` phải gọi ``_loc_nhan_tu_the``; cả hai chiều trong một bài.

    Xoá dòng ``labels = _loc_nhan_tu_the(labels, config.posture_labels_enabled)``
    khỏi vòng lặp thì mọi test khác vẫn xanh (chúng kiểm hàm phụ, không kiểm
    việc gọi). Ở đây vòng lặp thật chạy với pose "đầu cúi" nên ``classify``
    sinh ``HEAD_DOWN``:

    - ``posture_labels_enabled = False`` (mặc định) → nhãn **không** được lọt
      tới ``dispatcher``;
    - ``posture_labels_enabled = True`` → nhãn **phải** còn trong bản đẩy đi.

    Hai vế trong cùng một bài để nó không thể xanh bằng cách luôn lọc hoặc
    luôn không lọc.
    """
    frames = 6

    # Vế 1: mặc định — nhãn tư thế bị lọc.
    tat = _config(_schedule(inside=True))
    tat.posture_labels_enabled = False
    exit_tat, updates_tat = _run_voi_dispatch(
        monkeypatch, tmp_path, config=tat, frames=frames
    )

    assert exit_tat == 0
    assert updates_tat, "vòng lặp phải đẩy ít nhất một StateUpdate cho dispatcher"
    labels_tat = [label for update in updates_tat for label in update.labels]
    assert HEAD_DOWN not in labels_tat, (
        "posture_labels_enabled=False nhưng HEAD_DOWN vẫn tới dispatcher: "
        f"{sorted(set(labels_tat))} — vòng lặp không áp dụng bộ lọc nhãn tư thế."
    )

    # Vế 2: bật lên — cùng pose, cùng baseline, nhãn phải được giữ.
    bat = _config(_schedule(inside=True))
    bat.posture_labels_enabled = True
    exit_bat, updates_bat = _run_voi_dispatch(
        monkeypatch, tmp_path, config=bat, frames=frames
    )

    assert exit_bat == 0
    assert updates_bat, "vòng lặp phải đẩy ít nhất một StateUpdate cho dispatcher"
    labels_bat = [label for update in updates_bat for label in update.labels]
    assert HEAD_DOWN in labels_bat, (
        "posture_labels_enabled=True nhưng HEAD_DOWN không tới dispatcher: "
        f"{sorted(set(labels_bat))} — bộ lọc đang lọc quá tay."
    )


def test_vong_lap_chan_gpio_khi_tat(monkeypatch, tmp_path):
    """``alerts.gpio_alert_enabled`` phải chặn ``alerts`` **trong** vòng lặp.

    Bỏ mệnh đề ``or not config.alerts.gpio_alert_enabled`` khỏi điều kiện
    quanh ``dispatcher.dispatch`` thì suite vẫn xanh. Ở đây dùng
    ``break_after_min = 0`` để máy trạng thái sinh ``EVENT_BREAK`` —
    ``alert=True`` — ngay khung đầu, nên ``update.alerts`` **không rỗng** nếu
    không bị chặn. Cần vậy để phép kiểm ``alerts == ()`` có nội dung: nếu
    ``update.alerts`` vốn đã rỗng thì bài này xanh mà chẳng chứng minh gì.
    """
    frames = 3

    def _config_break(gpio: bool) -> Config:
        config = _config(_schedule(inside=True))
        # ``break_after_min = 0``: ngồi 0 phút đã tới hạn → ``EVENT_BREAK``
        # ngay khung đầu, kèm ``alert=True``.
        timing = TimingConfig()
        timing.break_after_min = 0.0
        config.timing = timing
        config.alerts = AlertsConfig(
            gpio_alert_enabled=gpio, buzzer_enabled=True, vibration_enabled=True
        )
        return config

    # Vế 1: công tắc tắt — ``alerts`` bị xoá, dù máy trạng thái có sinh alert.
    tat = _config_break(gpio=False)
    exit_tat, updates_tat = _run_voi_dispatch(
        monkeypatch, tmp_path, config=tat, frames=frames
    )

    assert exit_tat == 0
    assert updates_tat, "vòng lặp phải đẩy StateUpdate cho dispatcher"
    # Nội dung phải có: ``EVENT_BREAK`` xuất hiện trong sự kiện của update.
    loai_su_kien = [
        event.type for update in updates_tat for event in update.events
    ]
    assert state_mod.EVENT_BREAK in loai_su_kien, (
        "máy trạng thái không sinh EVENT_BREAK nên bài này không chứng minh "
        f"được gì: {loai_su_kien}"
    )
    assert all(update.alerts == () for update in updates_tat), (
        "gpio_alert_enabled=False nhưng dispatcher vẫn nhận alerts khác rỗng: "
        f"{[u.alerts for u in updates_tat if u.alerts]} — công tắc GPIO không "
        "chặn được trong vòng lặp."
    )

    # Vế 2: công tắc bật — ``alerts`` không bị xoá.
    bat = _config_break(gpio=True)
    exit_bat, updates_bat = _run_voi_dispatch(
        monkeypatch, tmp_path, config=bat, frames=frames
    )

    assert exit_bat == 0
    assert updates_bat, "vòng lặp phải đẩy StateUpdate cho dispatcher"
    co_alert = [update for update in updates_bat if update.alerts]
    assert co_alert, (
        "gpio_alert_enabled=True nhưng không update nào có alerts: "
        f"{[u.events for u in updates_bat]} — công tắc đang chặn cả khi bật."
    )
    # Và sự kiện bị chặn phải đúng là ``EVENT_BREAK`` đã sinh ở trên.
    assert any(
        event.type == state_mod.EVENT_BREAK
        for update in co_alert
        for event in update.alerts
    ), "alert còn lại không phải EVENT_BREAK đã sinh"


def test_presence_config_duoc_nap_va_anh_xa_vao_tracker():
    """``presence.absent_grace_s`` trong YAML phải tới được ``PresenceTracker``.

    Khoá YAML không được nối vào ``Config(...)`` là khoá chết: không lỗi,
    không cảnh báo, và giá trị trong file bị bỏ qua im lặng.
    """
    from posture_monitor.config import load_config

    path = _REPO_ROOT / "config.yaml"
    config = load_config(path)
    assert config.presence.absent_grace_s == pytest.approx(3.0)

    # Và giá trị không mặc định cũng phải đi qua, không chỉ con số trùng mặc định.
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        custom = Path(tmp) / "config.yaml"
        custom.write_text(
            path.read_text(encoding="utf-8").replace(
                "absent_grace_s: 3.0", "absent_grace_s: 4.5"
            ),
            encoding="utf-8",
        )
        assert load_config(custom).presence.absent_grace_s == pytest.approx(4.5)

class _FakePeople:
    """``PeopleService`` giả: chỉ trả tín hiệu danh tính, không chạy model.

    ``update_signals`` và ``observe`` của bản thật chỉ cất dữ liệu rồi trả về
    ngay (xem docstring ``PeopleService``), nên ở đây chúng không làm gì.
    ``signals()`` trả đúng ``identity`` mà bài test muốn — kể cả ``fresh`` —
    để khoá việc vòng lặp **có đọc** trường đó.
    """

    def __init__(self, *, state: str, fresh: bool, selected: str | None):
        self._identity = {
            "state": state,
            "age_s": 0.0 if fresh else 99.0,
            "age_limit_s": 10.0,
            "fresh": fresh,
            "name": None,
            "reason": "kịch bản test",
        }
        self._selected = selected
        self.observe_calls = 0
        self.signals_calls = 0

    def update_signals(self, **_kwargs) -> None:
        pass

    def observe(self, _frame, _now) -> None:
        self.observe_calls += 1

    def selected_person(self) -> str | None:
        return self._selected

    def signals(self) -> dict:
        self.signals_calls += 1
        no_data = {
            "state": "NO_DATA",
            "age_s": None,
            "age_limit_s": 3.0,
            "fresh": False,
        }
        return {
            "presence": dict(no_data),
            "phone": dict(no_data),
            "identity": dict(self._identity),
        }


def _schedule_chi_stranger() -> ScheduleConfig:
    """Lịch trong giờ nhưng nâng ``hold_s`` của leave_frame/phone lên rất cao.

    Nhờ vậy khung nào cũng chỉ có thể phát cảnh báo ``stranger``; nếu loại
    khác lọt vào thì ``alerter.calls`` sẽ lộ ra ngay.
    """
    schedule = _schedule(inside=True)
    schedule.kinds["leave_frame"] = KindSettings(
        enabled=True, cooldown_s=60.0, hold_s=1000.0
    )
    schedule.kinds["phone"] = KindSettings(
        enabled=True, cooldown_s=120.0, hold_s=1000.0
    )
    schedule.kinds["stranger"] = KindSettings(
        enabled=True, cooldown_s=300.0, hold_s=5.0
    )
    return schedule


def test_mismatch_giu_du_lau_thi_co_quyet_dinh_stranger(monkeypatch, tmp_path):
    """``MISMATCH`` + ``fresh: True`` + đã chọn người → ``held["stranger"]`` tích lũy.

    Bốn khung ở ``alert_now`` = 0, 2, 4, 6 s. Mismatch bắt đầu từ khung 0 nên
    khung cuối có ``held["stranger"] == 6.0 >= hold_s 5.0`` và loa nhận đúng
    loại ``stranger``.

    Mutation: bỏ dòng gán ``held["stranger"]`` thì khung cuối không còn khoá
    này (assert nói rõ ``stranger``), và loa không kêu.
    """
    frames = 4
    # Mỗi khung đọc ``alert_now`` một lần và PresenceTracker đọc thêm một lần.
    clock = _QueueClock([0, 0, 2, 2, 4, 4, 6, 6])
    people = _FakePeople(state="MISMATCH", fresh=True, selected="an")
    config = _config(_schedule_chi_stranger())

    exit_code, observed, alerter = _run(
        monkeypatch,
        tmp_path,
        estimator=_ScriptedEstimator([_pose(True)] * frames),
        frames=frames,
        clock=clock,
        wall_clock=_StepWallClock(_WALL_TIME, step_s=1.0),
        config=config,
        phone_script=[(None, 0.0)],
        people=people,
    )

    assert exit_code == 0
    assert len(observed) == frames, observed
    assert people.signals_calls >= frames, (
        "vòng lặp phải đọc signals() mỗi khung để tích lũy thời gian giữ"
    )
    last_held = observed[-1]
    assert last_held.get("stranger", 0.0) >= 5.0, (
        f"held['stranger'] phải tích lũy đủ hold_s; nhận {last_held!r}"
    )
    assert [kind for kind, _ in alerter.calls] == ["stranger"], alerter.calls


def test_identity_cu_thi_khong_tich_luy_stranger(monkeypatch, tmp_path):
    """``fresh: False`` nghĩa là hết dữ liệu → **không** được coi là mismatch.

    Cùng bộ cảnh với bài trên, chỉ đổi ``fresh`` thành ``False``. Nếu bỏ điều
    kiện ``fresh`` thì ``state`` cũ bị đọc như kết luận hiện tại và
    ``held["stranger"]`` lớn dần tới ngưỡng — đúng cái bẫy trong docstring
    ``PeopleService.signals``.
    """
    frames = 4
    clock = _QueueClock([0, 0, 2, 2, 4, 4, 6, 6])
    people = _FakePeople(state="MISMATCH", fresh=False, selected="an")
    config = _config(_schedule_chi_stranger())

    exit_code, observed, alerter = _run(
        monkeypatch,
        tmp_path,
        estimator=_ScriptedEstimator([_pose(True)] * frames),
        frames=frames,
        clock=clock,
        wall_clock=_StepWallClock(_WALL_TIME, step_s=1.0),
        config=config,
        phone_script=[(None, 0.0)],
        people=people,
    )

    assert exit_code == 0
    assert len(observed) == frames, observed
    assert all(held.get("stranger", 0.0) == 0.0 for held in observed), (
        f"tín hiệu cũ không được tích lũy thành held['stranger']: {observed!r}"
    )
    assert alerter.calls == [], "tín hiệu cũ không được sinh cảnh báo"


def test_mismatch_khi_chua_chon_nguoi_thi_khong_bao(monkeypatch, tmp_path):
    """``MISMATCH`` lúc **chưa chọn** người đang học → không cảnh báo.

    Đây là quyết định ở mục 6 của brief: ``_classify`` trả ``MISMATCH`` khi
    ``_selected is None`` nghĩa là "khuôn mặt không khớp ai trong kho" — xảy
    ra cả khi kho rỗng hoặc đang hiệu chỉnh. Đề tài yêu cầu báo "người khác
    vào học hộ", tức phải có một người đang học để bị thay thế; báo lúc chưa
    chọn là báo nhầm. Bài này khoá lựa chọn đó.
    """
    frames = 4
    clock = _QueueClock([0, 0, 2, 2, 4, 4, 6, 6])
    people = _FakePeople(state="MISMATCH", fresh=True, selected=None)
    config = _config(_schedule_chi_stranger())

    exit_code, observed, alerter = _run(
        monkeypatch,
        tmp_path,
        estimator=_ScriptedEstimator([_pose(True)] * frames),
        frames=frames,
        clock=clock,
        wall_clock=_StepWallClock(_WALL_TIME, step_s=1.0),
        config=config,
        phone_script=[(None, 0.0)],
        people=people,
    )

    assert exit_code == 0
    assert len(observed) == frames, observed
    assert all(held.get("stranger", 0.0) == 0.0 for held in observed), observed
    assert alerter.calls == [], "chưa chọn người học thì chưa thể có ai học hộ"


def test_khong_co_dich_vu_nguoi_hoc_thi_khong_co_stranger(monkeypatch, tmp_path):
    """``people is None`` (``face.enabled: false``) → không có ``stranger``, không lỗi.

    Mặc định của ``config.yaml`` là tắt nhận diện khuôn mặt. Khối cảnh báo
    vẫn chạy cho leave_frame/phone, nhưng ``held`` không được có khoá
    ``stranger`` và không được ném lỗi (không có cảnh báo ``alert_errors``).
    """
    frames = 3
    clock = _QueueClock([0, 0, 1, 1, 2, 2])
    logger = _QuietLogger()
    config = _config(_schedule(inside=True))

    exit_code, observed, alerter = _run(
        monkeypatch,
        tmp_path,
        estimator=_ScriptedEstimator([_pose(True)] * frames),
        frames=frames,
        clock=clock,
        wall_clock=_StepWallClock(_WALL_TIME, step_s=1.0),
        config=config,
        phone_script=[(None, 0.0)],
        people=None,
        logger=logger,
    )

    assert exit_code == 0
    assert len(observed) == frames, observed
    assert all("stranger" not in held for held in observed), observed
    assert alerter.calls == [], alerter.calls
    assert logger.warnings == [], logger.warnings
