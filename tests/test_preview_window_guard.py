"""Cửa sổ xem trước hỏng **không** được giết vòng lặp giám sát (spec §11.3).

Đo trên Pi thật, qua xrdp: Qt không tạo được ``guiReceiver`` (thiếu
thư mục font) nên ``cv2.imshow``/``cv2.waitKey``/``cv2.getWindowProperty`` ném
``cv2.error`` (-27:Null pointer). Trước khi có bảo vệ, ngoại lệ này thoát khỏi
``_monitor_loop`` và bị bộ bắt lỗi cấp cao nhất biến thành "thoát cả tiến
trình". Các test dưới đây khoá hành vi mới: vẫn đọc khung, vẫn chạy pose,
vẫn ghi DB, chỉ mất cửa sổ xem trước.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import posture_monitor.__main__ as cli  # noqa: E402
from posture_monitor.calibration import Baseline  # noqa: E402
from posture_monitor.config import Config  # noqa: E402
from posture_monitor.features import ALL_NAMES  # noqa: E402

_FRAMES = 4


class RecordingLogger:
    """Ghi lại log để đếm cảnh báo (test không cần handler thật)."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.infos: list[str] = []
        self.errors: list[str] = []

    def warning(self, fmt, *args) -> None:
        self.warnings.append(fmt % args if args else str(fmt))

    def info(self, fmt, *args) -> None:
        self.infos.append(fmt % args if args else str(fmt))

    def error(self, fmt, *args) -> None:
        self.errors.append(fmt % args if args else str(fmt))


class CountingSource:
    """Trả ``frames`` khung rồi ``None`` — đường thoát bình thường của vòng lặp."""

    backend = "fake"

    def __init__(self, frames: int = _FRAMES) -> None:
        self.frames_left = frames
        self.reads = 0

    def read(self):
        self.reads += 1
        if self.frames_left <= 0:
            return None
        self.frames_left -= 1
        return np.zeros((48, 64, 3), dtype=np.uint8)

    def close(self) -> None:
        pass


class FakeEstimator:
    backend = "fake"

    def detect(self, frame):
        return None

    @property
    def last_person_count(self) -> int:
        return 0


class RecordingStorage:
    def __init__(self) -> None:
        self.records: list[object] = []

    def record(self, update, distance_cm=None) -> None:
        self.records.append(update)


class Boom:
    """Callable luôn ném đúng lỗi Qt đo được trên Pi; đếm số lần bị gọi."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise cv2.error(
            "OpenCV(5.0.0) error: (-27:Null pointer) NULL guiReceiver "
            "(please create a window) in function 'cvGetPropVisible_QT'"
        )


def _neutral_baseline() -> Baseline:
    return Baseline(
        values={name: None for name in ALL_NAMES},
        view="front",
        width=640,
        height=480,
        created_at="",
        frames=0,
    )


def _run(monkeypatch, *, logger, keys=(), frames=_FRAMES, **window):
    """Chạy ``_monitor_loop`` vô hạn phụ thuộc; ``window`` thay từng hàm cv2."""
    import posture_monitor.calibration as calibration_mod

    monkeypatch.setattr(calibration_mod, "load", lambda path: _neutral_baseline())
    monkeypatch.setattr(cli.cv2, "namedWindow", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "destroyAllWindows", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "imshow", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "waitKey", lambda *a, **k: -1)
    monkeypatch.setattr(cli.cv2, "getWindowProperty", lambda *a, **k: 1.0)
    for name, fake in window.items():
        monkeypatch.setattr(cli.cv2, name, fake)

    pending = list(keys)
    if pending:
        monkeypatch.setattr(
            cli.cv2,
            "waitKey",
            lambda *a, **k: pending.pop(0) if pending else -1,
        )

    source = CountingSource(frames)
    storage = RecordingStorage()
    exit_code = cli._monitor_loop(
        FakeEstimator(),
        source,
        Config(),
        logger,
        state=None,
        storage=storage,
        sensor=None,
        dispatcher=None,
    )
    return exit_code, source, storage


# ---------------------------------------------------------------------------
# Cửa sổ hỏng: vòng lặp vẫn sống, chỉ mất cửa sổ xem trước
# ---------------------------------------------------------------------------
def test_window_property_error_does_not_kill_loop(monkeypatch):
    """``getWindowProperty`` ném lỗi: vòng lặp vẫn xử lý hết khung."""
    logger = RecordingLogger()
    boom = Boom()

    exit_code, source, storage = _run(
        monkeypatch, logger=logger, getWindowProperty=boom
    )

    # Thoát bằng đường bình thường (hết khung → 1), không phải bằng ngoại lệ.
    assert exit_code == 1
    assert source.reads == _FRAMES + 1
    assert len(storage.records) == _FRAMES
    assert logger.errors, "phải log lý do hết khung như cũ"


def test_imshow_error_does_not_kill_loop(monkeypatch):
    """``imshow`` ném lỗi: vòng lặp vẫn xử lý hết khung."""
    logger = RecordingLogger()
    boom = Boom()

    exit_code, source, storage = _run(monkeypatch, logger=logger, imshow=boom)

    assert exit_code == 1
    assert source.reads == _FRAMES + 1
    assert len(storage.records) == _FRAMES


def test_wait_key_error_does_not_kill_loop(monkeypatch):
    """``waitKey`` ném cùng lỗi Qt: vòng lặp vẫn xử lý hết khung."""
    logger = RecordingLogger()
    boom = Boom()

    exit_code, source, storage = _run(monkeypatch, logger=logger, waitKey=boom)

    assert exit_code == 1
    assert source.reads == _FRAMES + 1
    assert len(storage.records) == _FRAMES


def test_named_window_error_does_not_kill_loop(monkeypatch):
    """``namedWindow`` ném lỗi ngay đầu: vẫn giám sát, chỉ thiếu xem trước."""
    logger = RecordingLogger()
    boom = Boom()

    exit_code, source, storage = _run(monkeypatch, logger=logger, namedWindow=boom)

    assert exit_code == 1
    assert len(storage.records) == _FRAMES
    assert len(logger.warnings) == 1


def test_window_failure_warns_exactly_once(monkeypatch):
    """Hỏng lặp qua nhiều khung: đúng một cảnh báo, không thử lại cửa sổ."""
    logger = RecordingLogger()
    boom = Boom()

    exit_code, _source, storage = _run(
        monkeypatch, logger=logger, frames=6, getWindowProperty=boom
    )

    assert exit_code == 1
    assert len(storage.records) == 6
    assert len(logger.warnings) == 1, logger.warnings
    assert boom.calls == 1, "hỏng một lần là thôi thử lại, tránh spam 5 FPS"
    message = logger.warnings[0].lower()
    assert "cửa sổ xem trước" in message
    assert "giám sát" in message
    assert "dashboard" in message


# ---------------------------------------------------------------------------
# Đường lành: giữ nguyên q/Esc và bấm X
# ---------------------------------------------------------------------------
def test_healthy_window_quits_on_q(monkeypatch):
    """Cửa sổ lành: phím ``q`` vẫn thoát với mã 0 như trước."""
    logger = RecordingLogger()

    exit_code, source, _storage = _run(
        monkeypatch, logger=logger, keys=[-1, ord("q")], frames=6
    )

    assert exit_code == 0
    assert source.reads == 2, "phải dừng ngay sau phím q"
    assert logger.warnings == []
    assert any("phím thoát" in info for info in logger.infos)


def test_healthy_window_closing_quits(monkeypatch):
    """Cửa sổ lành: bấm nút X (visible < 1) vẫn thoát với mã 0."""
    logger = RecordingLogger()
    hidden = {"seen": 0}

    def visible(*args, **kwargs):
        hidden["seen"] += 1
        return 0.0 if hidden["seen"] >= 2 else 1.0

    exit_code, source, _storage = _run(
        monkeypatch, logger=logger, getWindowProperty=visible, frames=6
    )

    assert exit_code == 0
    assert source.reads == 2
    assert logger.warnings == []
    assert any("đã đóng" in info for info in logger.infos)


# ---------------------------------------------------------------------------
# --no-preview: tắt cửa sổ vì người dùng chỉ xem qua web
# ---------------------------------------------------------------------------
def _run_no_preview(monkeypatch, *, logger, frames=_FRAMES, window=None):
    """Chạy vòng lặp với ``show_preview=False`` và các hàm cửa sổ ghi lại lời gọi."""
    import posture_monitor.calibration as calibration_mod

    calls = {"namedWindow": 0, "imshow": 0, "waitKey": 0, "destroyAllWindows": 0}

    def counted(name, result=0):
        def _fake(*_args, **_kwargs):
            calls[name] += 1
            return result

        return _fake

    monkeypatch.setattr(calibration_mod, "load", lambda path: _neutral_baseline())
    monkeypatch.setattr(cli.cv2, "namedWindow", counted("namedWindow"))
    monkeypatch.setattr(cli.cv2, "imshow", counted("imshow"))
    monkeypatch.setattr(cli.cv2, "waitKey", counted("waitKey", -1))
    monkeypatch.setattr(cli.cv2, "destroyAllWindows", counted("destroyAllWindows"))
    monkeypatch.setattr(cli.cv2, "getWindowProperty", lambda *a, **k: 1.0)
    for name, fake in (window or {}).items():
        monkeypatch.setattr(cli.cv2, name, fake)

    storage = RecordingStorage()
    exit_code = cli._monitor_loop(
        FakeEstimator(),
        CountingSource(frames),
        Config(),
        logger,
        state=None,
        storage=storage,
        sensor=None,
        dispatcher=None,
        show_preview=False,
    )
    return exit_code, storage, calls


def test_no_preview_khong_mo_cua_so_nao(monkeypatch):
    """``show_preview=False``: không ``namedWindow``/``imshow``/``waitKey``/``destroy``.

    Người dùng chạy máy chỉ có web nên cửa sổ OpenCV là việc vô ích: mỗi khung
    vẫn phải vẽ và xử lý sự kiện cửa sổ, và trên máy không có màn hình nó còn
    ném lỗi Qt. Bài này khoá rằng cả bốn lời gọi đều bằng 0 — không chỉ là
    "không hiện ảnh" mà không đụng tới nền tảng giao diện.
    """
    logger = RecordingLogger()

    exit_code, storage, calls = _run_no_preview(monkeypatch, logger=logger)

    assert exit_code == 1, "hết khung là đường thoát bình thường"
    assert len(storage.records) == _FRAMES, "vẫn phải xử lý mọi khung"
    assert calls == {
        "namedWindow": 0,
        "imshow": 0,
        "waitKey": 0,
        "destroyAllWindows": 0,
    }, calls
    assert logger.warnings == [], "tắt theo yêu cầu không phải lỗi"
    assert any("cửa sổ xem trước" in info for info in logger.infos), logger.infos


def test_no_preview_khong_thu_lai_khi_cua_so_hong(monkeypatch):
    """Tắt xem trước thì cửa sổ hỏng cũng không thành cảnh báo hay log lỗi."""
    logger = RecordingLogger()

    exit_code, storage, calls = _run_no_preview(
        monkeypatch, logger=logger, window={"imshow": Boom()}
    )

    assert exit_code == 1
    assert len(storage.records) == _FRAMES
    assert calls["imshow"] == 0, "không được gọi imshow dù nó sẽ ném lỗi"
    assert logger.warnings == []


def test_no_preview_la_mac_dinh_cua_lenh_run():
    """``run`` **mặc định** không mở cửa sổ; ``--preview`` mới bật.

    Yêu cầu của người dùng là "chạy code cũng không cần hiện process camera,
    tôi sẽ lên web để xem". Mặc định phải là không có cửa sổ, nếu không họ
    vẫn phải nhớ thêm một cờ mỗi lần chạy — và quên thì cửa sổ lại hiện.
    """
    args = cli.build_parser().parse_args(["run"])
    assert args.preview is False, "mặc định KHÔNG được mở cửa sổ"

    args_bat = cli.build_parser().parse_args(["run", "--preview"])
    assert args_bat.preview is True

    # ``--no-preview`` vẫn phải nhận để lệnh cũ không gãy.
    args_cu = cli.build_parser().parse_args(["run", "--no-preview"])
    assert args_cu.no_preview is True
    assert args_cu.preview is False


def _status_text(monkeypatch, *, show_preview: bool) -> str:
    """Gọi ``_print_status`` và trả toàn bộ văn bản nó in."""
    captured: list[str] = []

    def fake_print(*args, **_kwargs):
        captured.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr(cli, "print", fake_print, raising=False)

    class _Hardware:
        state = "GOOD"

    cli._print_status(Config(), _Hardware(), None, "front", "onnx", show_preview)
    return "\n".join(captured)


def test_banner_khong_noi_bam_q_khi_khong_mo_cua_so(monkeypatch):
    """Khi mặc định không có cửa sổ, banner không được dặn "bấm q".

    Chỉ dẫn sai kiểu này khiến người dùng ngồi chờ một cửa sổ không bao giờ
    hiện (và tưởng chương trình hỏng).
    """
    text = _status_text(monkeypatch, show_preview=False)

    assert "bấm q" not in text, text
    assert "dashboard web" in text, text
    assert "Ctrl+C" in text, text
    assert "--preview" in text, text


def test_banner_van_dan_bam_q_khi_bat_preview(monkeypatch):
    """Bật ``--preview`` thì banner phải nói đúng cách thoát cửa sổ."""
    text = _status_text(monkeypatch, show_preview=True)

    assert "bấm q" in text, text
    assert "Ctrl+C" not in text, text
