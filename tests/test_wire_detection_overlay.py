"""Hộp phát hiện phải tới được vòng lặp: điện thoại (``PhoneSignal``) và
khuôn mặt (``PeopleService``), và phải vẽ lên khung **trước khi** mã hoá JPEG
cho dashboard.

Đây là chỗ dễ hỏng im lặng nhất: cả ba mảnh (vẽ, công bố toạ độ, gọi trong
vòng lặp) đều có test riêng và đều xanh, trong khi chương trình thật vẫn
không hiện hộp nào — vì ``imencode`` chạy trước chỗ vẽ, nên web thấy khung
trần; hoặc vì ``drawn`` bị vẽ chồng lên ``frame`` đang được luồng nhận diện
đọc. Vì vậy test ở đây chạy ``_monitor_loop`` **thật** với các seam giả và
quan sát đúng hai thứ người dùng thấy: ảnh đưa vào ``imshow`` và ảnh đưa vào
``DashboardState.set_frame``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import posture_monitor.__main__ as cli  # noqa: E402
from posture_monitor.calibration import Baseline  # noqa: E402
from posture_monitor.config import Config  # noqa: E402
from posture_monitor.features import ALL_NAMES  # noqa: E402
from posture_monitor.overlay import FACE_BOX_COLOR, PHONE_BOX_COLOR  # noqa: E402

_FRAMES = 3
_WIDTH, _HEIGHT = 160, 120
#: Hộp điện thoại và hộp mặt nằm hai góc khác nhau, không chồng nhau, để đếm
#: màu của hộp này không bị hộp kia che.
_PHONE_BOX = (10.0, 10.0, 60.0, 50.0)
_FACE_BOX = (90.0, 60.0, 50.0, 50.0)


class _Logger:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def warning(self, fmt, *args) -> None:
        self.warnings.append(fmt % args if args else str(fmt))

    def info(self, fmt, *args) -> None:
        self.infos.append(fmt % args if args else str(fmt))

    def error(self, fmt, *args) -> None:
        pass

    def exception(self, *args, **kwargs) -> None:
        pass


class _Source:
    backend = "fake"

    def __init__(self, frames: int) -> None:
        self.frames_left = frames

    def read(self):
        if self.frames_left <= 0:
            return None
        self.frames_left -= 1
        return np.zeros((_HEIGHT, _WIDTH, 3), dtype=np.uint8)

    def close(self) -> None:
        pass


class _Estimator:
    backend = "fake"

    def detect(self, _frame):
        return None

    @property
    def last_person_count(self) -> int:
        return 0


class _PhoneSignal:
    """Giả ``PhoneSignal`` đã cắt hộp: chỉ trả hộp, không detect."""

    instances: list["_PhoneSignal"] = []

    def __init__(self, _config) -> None:
        self._this_round_boxes = ()
        self._asked_with: list[float] = []
        _PhoneSignal.instances.append(self)

    @property
    def held_s(self) -> float:
        return 0.0

    @property
    def in_use(self) -> bool:
        return False

    def observe(self, _frame, _keypoints, now):
        self._this_round_boxes = (_PHONE_BOX,)
        return None

    def boxes(self, now):
        self._asked_with.append(float(now))
        return self._this_round_boxes


class _People:
    """Giả ``PeopleService``: chỉ có những phương thức vòng lặp gọi."""

    def __init__(self) -> None:
        self.observe_calls = 0
        self.box_asked = 0
        self._face_box = _FACE_BOX

    def update_signals(self, presence=None, phone=None, now=None) -> None:
        pass

    def observe(self, _frame, _now) -> None:
        self.observe_calls += 1

    def note_phone(self, _state, now=None) -> None:
        pass

    def signals(self) -> dict:
        return {}

    def selected_person(self):
        return None

    def latest_face_box(self, now=None):
        self.box_asked += 1
        return self._face_box


class _State:
    """``DashboardState`` giả: giữ JPEG cuối cùng đưa cho dashboard."""

    muted = False

    def __init__(self) -> None:
        self.frames: list[bytes] = []

    def update(self, **_kwargs) -> None:
        pass

    def set_frame(self, data: bytes) -> None:
        self.frames.append(data)

    def consume_calibration_request(self) -> bool:
        return False


def _baseline() -> Baseline:
    return Baseline(
        values={name: None for name in ALL_NAMES},
        view="front",
        width=640,
        height=480,
        created_at="",
        frames=0,
    )


def _run(monkeypatch, *, people=None, phone_signal_cls=_PhoneSignal):
    """Chạy vòng lặp thật, trả ``(ảnh imshow cuối, state, people)``."""
    import posture_monitor.calibration as calibration_mod
    import posture_monitor.phone_detector as phone_mod

    monkeypatch.setattr(calibration_mod, "load", lambda _p: _baseline())
    monkeypatch.setattr(phone_mod, "PhoneSignal", phone_signal_cls)

    shown: list[np.ndarray] = []

    def imshow(_name, image):
        shown.append(np.array(image, copy=True))

    monkeypatch.setattr(cli.cv2, "namedWindow", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "destroyAllWindows", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "imshow", imshow)
    monkeypatch.setattr(cli.cv2, "getWindowProperty", lambda *a, **k: 1.0)
    keys = [0] * (_FRAMES - 1) + [ord("q")]
    monkeypatch.setattr(
        cli.cv2, "waitKey", lambda *a, **k: keys.pop(0) if keys else ord("q")
    )

    state = _State()
    cli._monitor_loop(
        _Estimator(),
        _Source(_FRAMES),
        Config(),
        _Logger(),
        state=state,
        storage=None,
        sensor=None,
        dispatcher=None,
        stream_enabled=True,
        people=people,
    )
    return shown, state


def _count_color(image: np.ndarray, color) -> int:
    mask = np.all(image == np.array(color, dtype=np.uint8), axis=2)
    return int(mask.sum())


def test_vong_lap_ve_hop_dien_thoai_len_cua_so(monkeypatch):
    """Hộp từ ``PhoneSignal.boxes`` phải hiện trên ảnh đưa vào ``imshow``."""
    shown, _state = _run(monkeypatch)

    assert shown, "vòng lặp không gọi imshow lần nào"
    assert _count_color(shown[-1], PHONE_BOX_COLOR) > 0, (
        "không thấy hộp điện thoại trên khung xem trước: bước vẽ hộp chưa "
        "được nối vào vòng lặp, hoặc chạy trước lần detect"
    )


def test_vong_lap_ve_hop_khuon_mat_len_cua_so(monkeypatch):
    """Hộp từ ``PeopleService.latest_face_box`` phải hiện trên khung."""
    people = _People()
    shown, _state = _run(monkeypatch, people=people)

    assert people.box_asked > 0, "vòng lặp chưa hỏi hộp khuôn mặt lần nào"
    assert _count_color(shown[-1], FACE_BOX_COLOR) > 0


def test_dashboard_nhan_khung_da_ve(monkeypatch):
    """JPEG đưa cho dashboard phải có hộp, không phải khung trần.

    Đây là lỗi đã có trong code trước khi sửa: ``cv2.imencode`` được gọi ở
    khối ``state.update`` phía trên, tức **trước** cả hai lần detect, nên web
    luôn thấy khung không hộp dù cửa sổ xem trước (được vẽ sau) có.
    """
    import cv2

    _shown, state = _run(monkeypatch)

    assert state.frames, "không có khung nào được đẩy lên dashboard"
    decoded = cv2.imdecode(
        np.frombuffer(state.frames[-1], dtype=np.uint8), cv2.IMREAD_COLOR
    )
    assert decoded is not None
    # JPEG là nén có mất mát: đòi hỏi đúng màu tuyệt đối sẽ hỏng oan. Chỉ cần
    # phía hộp điện thoại (cam, BGR = 0/165/255) có kênh đỏ trội so với nền đen.
    top = decoded[8:20, 8:70]
    assert int(top[:, :, 2].max()) > 100, (
        "khung đẩy lên dashboard không có nét cam của hộp điện thoại; "
        "imencode đang chạy trước bước vẽ hộp"
    )


def test_vong_lap_khong_ve_len_khung_goc(monkeypatch):
    """Khung gốc phải nguyên vẹn: nó đang được luồng nhận diện giữ tham chiếu."""
    held: list[np.ndarray] = []

    class _RetainingPeople(_People):
        def observe(self, frame, _now) -> None:
            held.append(frame)  # giữ đúng tham chiếu như PeopleService thật
            super().observe(frame, _now)

    shown, _state = _run(monkeypatch, people=_RetainingPeople())

    assert shown, "vòng lặp không gọi imshow lần nào"
    for frame in held:
        assert _count_color(frame, PHONE_BOX_COLOR) == 0, (
            "vẽ hộp trực tiếp lên khung đang được luồng nhận diện đọc"
        )
        assert _count_color(frame, FACE_BOX_COLOR) == 0
