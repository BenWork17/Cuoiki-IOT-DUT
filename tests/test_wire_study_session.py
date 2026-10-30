"""Nối cổng phiên học vào ``_monitor_loop`` (nút Bắt đầu / Dừng trên web).

Yêu cầu của đề tài: **bấm Bắt đầu học thì model AI mới chạy**. Test ở đây chạy
vòng lặp thật với camera/estimator/người học giả, còn
:class:`~posture_monitor.study_session.StudySession` là bản thật. Nhờ vậy nó
bắt được đúng lỗi cần bắt: một vòng lặp vẫn gọi ``estimator.detect`` mỗi khung
dù chưa ai bấm nút.

Ba điều phải đúng **đồng thời** khi ngoài phiên:

1. ``estimator.detect`` **không** được gọi (đó là model nặng nhất).
2. Khung vẫn tới dashboard (``state.set_frame``) — người dùng cần thấy mình
   ngồi đúng khung trước khi bấm.
3. ``people.observe`` vẫn được gọi — nhận diện khuôn mặt là ngoại lệ có chủ ý.

Và khi trong phiên: mọi thứ chạy như cũ, không mất cảnh báo nào.
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

from posture_monitor.config import Config, PresenceConfig  # noqa: E402
from posture_monitor.pose import PoseResult  # noqa: E402
from posture_monitor.state import STATE_ABSENT, STATE_PAUSED  # noqa: E402
from posture_monitor.study_session import (  # noqa: E402
    FINISHED_MESSAGE,
    StudySession,
)

_PRESENT_CONF = np.array([0.9] * 7 + [0.0] * 10, dtype=np.float32)


def _pose() -> PoseResult:
    xy = np.full((17, 2), 100.0, dtype=np.float32)
    bbox = np.array([10.0, 10.0, 200.0, 300.0], dtype=np.float32)
    return PoseResult(xy=xy, conf=_PRESENT_CONF, bbox=bbox)


class _Clock:
    """Đồng hồ đơn điệu giả, tự nhích sau mỗi lần đọc.

    Vòng lặp đọc ``time.monotonic`` cho cả nhịp khung lẫn ``alert_clock``, nên
    nhích đều giữ hai bên nhất quán và tránh ``StateMachine`` từ chối ``now``
    giảm.
    """

    def __init__(self, start: float = 0.0, step: float = 0.06) -> None:
        self.now = float(start)
        self._step = float(step)

    def __call__(self) -> float:
        value = self.now
        self.now += self._step
        return value

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class _CountingEstimator:
    """Đếm số lần ``detect`` — chính là thứ cổng phiên học phải chặn."""

    backend = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def detect(self, _frame):
        self.calls += 1
        return _pose()


class _Source:
    backend = "fake"

    def __init__(self, frames: int) -> None:
        self.frames_left = int(frames)

    def read(self):
        if self.frames_left <= 0:
            return None
        self.frames_left -= 1
        return np.zeros((48, 64, 3), dtype=np.uint8)

    def close(self) -> None:
        pass


class _State:
    """``DashboardState`` giả: ghi lại mọi bản cập nhật và JPEG."""

    def __init__(self) -> None:
        self.updates: list[dict] = []
        self.frames: list[bytes] = []
        self.muted = False

    def update(self, status=None, **fields) -> None:
        merged = dict(status or {})
        merged.update(fields)
        self.updates.append(merged)

    def set_frame(self, data: bytes) -> None:
        self.frames.append(data)

    def consume_calibration_request(self) -> bool:
        return False


class _People:
    """``PeopleService`` giả: đếm ``observe``/``update_signals``."""

    def __init__(self) -> None:
        self.observed = 0
        self.signal_updates = 0

    def observe(self, _frame, _now) -> None:
        self.observed += 1

    def update_signals(self, presence=None, phone=None, now=None) -> None:
        self.signal_updates += 1

    def signals(self) -> dict:
        return {}

    def selected_person(self):
        return None

    def latest_face_box(self):
        return None

    def note_phone(self, _state, now=None) -> None:
        pass


class _Logger:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.warnings: list[str] = []

    def info(self, fmt, *args) -> None:
        self.infos.append(fmt % args if args else str(fmt))

    def warning(self, fmt, *args) -> None:
        self.warnings.append(fmt % args if args else str(fmt))

    def error(self, *args, **kwargs) -> None:
        pass

    def exception(self, *args, **kwargs) -> None:
        pass


class _WallClock:
    def __init__(self, start: datetime) -> None:
        self.current = start

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value


def _run(
    monkeypatch,
    *,
    frames: int = 6,
    study_session=None,
    people=None,
    state=None,
    clock=None,
):
    import posture_monitor.__main__ as cli
    import posture_monitor.calibration as calibration_mod
    from posture_monitor.calibration import Baseline
    from posture_monitor.features import ALL_NAMES

    baseline = Baseline(
        values={name: None for name in ALL_NAMES},
        view="front",
        width=640,
        height=480,
        created_at="",
        frames=0,
    )
    monkeypatch.setattr(calibration_mod, "load", lambda _p: baseline)
    # Không mở cửa sổ: máy chỉ xem qua dashboard.
    monkeypatch.setattr(cli.cv2, "namedWindow", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "imshow", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "destroyAllWindows", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "getWindowProperty", lambda *a, **k: 1.0)
    monkeypatch.setattr(cli.cv2, "waitKey", lambda *a, **k: -1)

    config = Config()
    config.presence = PresenceConfig(absent_grace_s=3.0)
    # Tắt phần cứng/loa: bài này chỉ nói về cổng model.
    config.alerts.gpio_alert_enabled = False

    estimator = _CountingEstimator()
    exit_code = cli._monitor_loop(
        estimator,
        _Source(frames),
        config,
        _Logger(),
        state=state,
        storage=None,
        sensor=None,
        dispatcher=None,
        stream_enabled=True,
        people=people,
        speaker=None,
        show_preview=False,
        study_session=study_session,
        clock=clock or _Clock(),
        wall_clock=_WallClock(datetime(2026, 10, 28, 19, 30)),
    )
    return exit_code, estimator


# ---------------------------------------------------------------------------
# Ngoài phiên: model không chạy, camera và khuôn mặt vẫn chạy
# ---------------------------------------------------------------------------


def test_ngoai_phien_khong_goi_pose(monkeypatch):
    session = StudySession(clock=_Clock(step=1.0))
    exit_code, estimator = _run(monkeypatch, frames=6, study_session=session)

    assert exit_code == 1, "hết khung là đường thoát bình thường (mã 1)"
    assert estimator.calls == 0, (
        "ngoài phiên mà vẫn gọi estimator.detect: yêu cầu 'bấm Bắt đầu mới "
        "dùng model AI' không được thực hiện"
    )


def test_ngoai_phien_van_day_khung_len_dashboard(monkeypatch):
    state = _State()
    session = StudySession(clock=_Clock(step=1.0))
    _run(monkeypatch, frames=6, study_session=session, state=state)

    assert len(state.frames) == 6, "vẫn phải thấy camera trước khi bấm Bắt đầu"
    assert all(frame.startswith(b"\xff\xd8") for frame in state.frames), (
        "khung phải là JPEG hợp lệ để /stream hiển thị được"
    )


def test_ngoai_phien_van_nhan_dien_khuon_mat(monkeypatch):
    people = _People()
    session = StudySession(clock=_Clock(step=1.0))
    _run(monkeypatch, frames=6, study_session=session, people=people)

    assert people.observed == 6, (
        "nhận diện khuôn mặt phải chạy ngoài phiên để dashboard biết ai đang ngồi"
    )
    assert people.signal_updates == 0, (
        "ngoài phiên hệ thống không đo presence; đẩy tín hiệu sẽ là đoán"
    )


def test_ngoai_phien_bao_trang_thai_paused(monkeypatch):
    state = _State()
    session = StudySession(clock=_Clock(step=1.0))
    _run(monkeypatch, frames=6, study_session=session, state=state)

    assert state.updates, "vòng lặp phải cập nhật trạng thái mỗi khung"
    last = state.updates[-1]
    assert last["state"] == STATE_PAUSED
    assert last["labels"] == []
    assert last["alert"] is None
    assert last["message"], "phải nói rõ vì sao chưa có số liệu"


def test_khong_tiem_phien_thi_chay_nhu_cu(monkeypatch):
    """``study_session=None`` (bản cũ) phải hành xử y như trước khi có tính năng."""
    state = _State()
    exit_code, estimator = _run(monkeypatch, frames=4, study_session=None, state=state)

    assert exit_code == 1
    assert estimator.calls == 4
    assert state.updates[-1]["state"] != STATE_PAUSED


# ---------------------------------------------------------------------------
# Trong phiên: mọi thứ chạy như cũ
# ---------------------------------------------------------------------------


def test_trong_phien_chay_pose(monkeypatch):
    clock = _Clock(step=1.0)
    session = StudySession(10, clock=clock)
    session.start()

    _exit_code, estimator = _run(
        monkeypatch, frames=5, study_session=session, clock=clock
    )
    assert estimator.calls == 5


def test_trong_phien_day_tin_hieu_presence(monkeypatch):
    clock = _Clock(step=1.0)
    session = StudySession(10, clock=clock)
    session.start()
    people = _People()

    _run(monkeypatch, frames=4, study_session=session, people=people, clock=clock)
    assert people.signal_updates == 4


def test_bat_dau_giua_chung_thi_model_chay_tu_khung_do(monkeypatch):
    """Phiên bắt đầu ở khung thứ 3: hai khung đầu không detect, phần còn lại có."""
    clock = _Clock(step=1.0)
    session = StudySession(10, clock=clock)

    original_read = None
    calls_at = []

    class _Src(_Source):
        def read(self):
            frame = super().read()
            if frame is not None:
                calls_at.append(len(calls_at))
                if len(calls_at) == 3:
                    session.start()
            return frame

    import posture_monitor.__main__ as cli
    import posture_monitor.calibration as calibration_mod
    from posture_monitor.calibration import Baseline
    from posture_monitor.features import ALL_NAMES

    baseline = Baseline(
        values={name: None for name in ALL_NAMES},
        view="front",
        width=640,
        height=480,
        created_at="",
        frames=0,
    )
    monkeypatch.setattr(calibration_mod, "load", lambda _p: baseline)
    monkeypatch.setattr(cli.cv2, "namedWindow", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "imshow", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "destroyAllWindows", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "waitKey", lambda *a, **k: 1.0)

    config = Config()
    config.presence = PresenceConfig(absent_grace_s=3.0)
    config.alerts.gpio_alert_enabled = False

    estimator = _CountingEstimator()
    cli._monitor_loop(
        estimator,
        _Src(6),
        config,
        _Logger(),
        state=_State(),
        storage=None,
        sensor=None,
        dispatcher=None,
        stream_enabled=True,
        people=None,
        speaker=None,
        show_preview=False,
        study_session=session,
        clock=clock,
        wall_clock=_WallClock(datetime(2026, 10, 28, 19, 30)),
    )

    # Hai khung đầu ngoài phiên, bốn khung sau trong phiên.
    assert estimator.calls == 4


def test_het_gio_giua_chung_thi_tat_model(monkeypatch):
    clock = _Clock(step=1.0)
    session = StudySession(1, clock=clock)
    session.start()

    class _Src(_Source):
        def __init__(self, frames):
            super().__init__(frames)
            self.reads = 0

        def read(self):
            frame = super().read()
            if frame is not None:
                self.reads += 1
                # Nhảy qua mốc 1 phút **trước khi đọc khung thứ hai**: khung
                # đầu còn trong phiên, các khung sau thì không.
                if self.reads == 2:
                    clock.advance(90)
            return frame

    import posture_monitor.__main__ as cli
    import posture_monitor.calibration as calibration_mod
    from posture_monitor.calibration import Baseline
    from posture_monitor.features import ALL_NAMES

    baseline = Baseline(
        values={name: None for name in ALL_NAMES},
        view="front",
        width=640,
        height=480,
        created_at="",
        frames=0,
    )
    monkeypatch.setattr(calibration_mod, "load", lambda _p: baseline)
    monkeypatch.setattr(cli.cv2, "namedWindow", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "imshow", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "destroyAllWindows", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "waitKey", lambda *a, **k: 1.0)

    config = Config()
    config.presence = PresenceConfig(absent_grace_s=3.0)
    config.alerts.gpio_alert_enabled = False

    estimator = _CountingEstimator()
    logged = _Logger()
    cli._monitor_loop(
        estimator,
        _Src(5),
        config,
        logged,
        state=_State(),
        storage=None,
        sensor=None,
        dispatcher=None,
        stream_enabled=True,
        people=None,
        speaker=None,
        show_preview=False,
        study_session=session,
        clock=clock,
        wall_clock=_WallClock(datetime(2026, 10, 28, 19, 30)),
    )

    assert estimator.calls == 1, "hết giờ là tự dừng: các khung sau không detect"
    assert sum(FINISHED_MESSAGE in line for line in logged.infos) == 1, (
        "câu 'hết giờ' phải được ghi log đúng một lần"
    )
    assert session.state == "finished"


def test_nhan_tu_the_sau_khi_bam_dung(monkeypatch):
    """Bấm Dừng: model tắt ngay, dashboard quay về trạng thái tạm nghỉ."""
    clock = _Clock(step=1.0)
    session = StudySession(60, clock=clock)
    session.start()
    state = _State()

    class _Src(_Source):
        def read(self):
            frame = super().read()
            # ``read`` giảm ``frames_left`` trước khi trả khung, nên lúc này
            # ``2`` nghĩa là vừa đọc xong khung thứ ba: hai khung đầu đã được
            # detect, khung thứ ba trở đi thì không.
            if frame is not None and self.frames_left == 2:
                session.stop()
            return frame

    import posture_monitor.__main__ as cli
    import posture_monitor.calibration as calibration_mod
    from posture_monitor.calibration import Baseline
    from posture_monitor.features import ALL_NAMES

    baseline = Baseline(
        values={name: None for name in ALL_NAMES},
        view="front",
        width=640,
        height=480,
        created_at="",
        frames=0,
    )
    monkeypatch.setattr(calibration_mod, "load", lambda _p: baseline)
    monkeypatch.setattr(cli.cv2, "namedWindow", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "imshow", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "destroyAllWindows", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "waitKey", lambda *a, **k: 1.0)
    monkeypatch.setattr(cli.cv2, "getWindowProperty", lambda *a, **k: 1.0)

    config = Config()
    config.presence = PresenceConfig(absent_grace_s=3.0)
    config.alerts.gpio_alert_enabled = False

    estimator = _CountingEstimator()
    cli._monitor_loop(
        estimator,
        _Src(5),
        config,
        _Logger(),
        state=state,
        storage=None,
        sensor=None,
        dispatcher=None,
        stream_enabled=True,
        people=None,
        speaker=None,
        show_preview=False,
        study_session=session,
        clock=clock,
        wall_clock=_WallClock(datetime(2026, 10, 28, 19, 30)),
    )

    assert estimator.calls == 2, "chỉ hai khung trước khi bấm Dừng được detect"
    assert state.updates[-1]["state"] == STATE_PAUSED
    assert session.state == "idle"


def test_loi_doc_phien_khong_giet_vong_lap(monkeypatch):
    """``StudySession`` hỏng: chạy như bản cũ, không tắt model cả buổi."""

    class _BrokenSession:
        default_minutes = 60

        def tick(self):
            raise RuntimeError("hỏng")

        @property
        def is_running(self):
            raise RuntimeError("hỏng")

    exit_code, estimator = _run(monkeypatch, frames=3, study_session=_BrokenSession())
    assert exit_code == 1
    assert estimator.calls == 3, "lỗi đọc phiên không được làm tắt model"


def test_absents_khi_ngoai_phien_khong_bi_coi_la_vang_that(monkeypatch):
    """Trạng thái ngoài phiên phải khác ``ABSENT``: người dùng đang ngồi đó."""
    state = _State()
    session = StudySession(clock=_Clock(step=1.0))
    _run(monkeypatch, frames=3, study_session=session, state=state)
    assert state.updates[-1]["state"] != STATE_ABSENT
    assert state.updates[-1]["state"] == STATE_PAUSED
