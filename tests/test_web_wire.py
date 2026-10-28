"""Test nối dashboard web vào lệnh ``run`` (spec v2 §5.10, §9).

Kiểm tra **hợp đồng nối dây**, không kiểm tra lại Flask/Storage (đã có
``test_web.py``/``test_storage.py``):

- Nhánh chạy dài của ``run`` dựng dashboard và truyền **đúng** đối tượng
  ``state`` mà vòng lặp ghi vào ``create_app`` — web không mở camera, không
  nhận ``source``.
- ``run_server`` chạy trong luồng nền, không chặn vòng lặp giám sát.
- Nhánh ``--save-overlay`` không dựng dashboard/server.
- Cổng bận (``OSError``/``SystemExit``) chỉ là cảnh báo, chương trình vẫn chạy.
- Vòng lặp đẩy dữ liệu thật lên web, ghi DB, và tắt tiếng đúng cách.

Không cần camera, GPIO hay model: mọi phụ thuộc nặng được thay bằng bản giả.
"""

from __future__ import annotations

import sys
import threading
from argparse import Namespace
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import posture_monitor.__main__ as cli  # noqa: E402
from posture_monitor.calibration import Baseline  # noqa: E402
from posture_monitor.classifier import ABSENT  # noqa: E402
from posture_monitor.config import Config, SensorsConfig, StorageConfig  # noqa: E402
from posture_monitor.features import ALL_NAMES  # noqa: E402
from posture_monitor.state import STATE_ABSENT, StateUpdate  # noqa: E402


# ---------------------------------------------------------------------------
# Bản giả tối thiểu
# ---------------------------------------------------------------------------
class FakeLogger:
    """Ghi lại log thay vì dùng logging (test không cần handler)."""

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


class FakeSource:
    """Nguồn ảnh trả khung giả; ghi nhận việc đóng."""

    backend = "fake"

    def __init__(self, frames: int = 10) -> None:
        self.closed = False
        self.frames_left = frames

    def read(self):
        if self.frames_left <= 0:
            return None
        self.frames_left -= 1
        return np.zeros((48, 64, 3), dtype=np.uint8)

    def close(self) -> None:
        self.closed = True


class FakeHardware:
    state = "idle"

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeEstimator:
    backend = "fake"

    def detect(self, frame):
        return None

    @property
    def last_person_count(self) -> int:
        return 0


class FakeStorage:
    def __init__(self) -> None:
        self.records: list[tuple[StateUpdate, float | None]] = []
        self.closed = False

    def record(self, update, distance_cm=None) -> None:
        self.records.append((update, distance_cm))

    def close(self) -> None:
        self.closed = True


class FakeDispatcher:
    def __init__(self) -> None:
        self.updates: list[StateUpdate] = []
        self.closed = False

    def dispatch(self, update):
        self.updates.append(update)
        return None

    def close(self) -> None:
        self.closed = True


class FakeSensor:
    def __init__(self, distance_cm: float | None = 40.0) -> None:
        self.distance_cm = distance_cm
        self.closed = False

    def read(self):
        return self.distance_cm

    def close(self) -> None:
        self.closed = True


class FakeThread:
    """Luồng giả: ghi lại ``start``/``join`` và cờ daemon."""

    def __init__(self, target=None, args=(), name=None, daemon=None) -> None:
        self.target = target
        self.args = args
        self.name = name
        self.daemon = daemon
        self.started = False
        self.joined_with: float | None = None

    def start(self) -> None:
        self.started = True

    def join(self, timeout=None) -> None:
        self.joined_with = timeout


class FakeDashboard:
    """Bản giả của ``_Dashboard``: chỉ ghi nhận, không mở Flask/DB."""

    created: list["FakeDashboard"] = []

    def __init__(self, config, logger) -> None:
        self.config = config
        self.logger = logger
        self.state = object()
        self.storage = FakeStorage()
        self.app = object()
        self.thread = FakeThread(
            target=cli._serve_web, name="dashboard-web", daemon=True
        )
        FakeDashboard.created.append(self)

    def start(self) -> None:
        self.thread.start()


@pytest.fixture(autouse=True)
def _reset_fake_dashboard():
    FakeDashboard.created.clear()
    yield
    FakeDashboard.created.clear()


def _config(tmp_path: Path) -> Config:
    config = Config()
    config.storage = StorageConfig(db_path=str(tmp_path / "posture.db"))
    config.sensors = SensorsConfig(min_distance_cm=35.0)
    return config


def _run_args(save_overlay: str | None = None) -> Namespace:
    return Namespace(
        config="config.yaml",
        no_gpio=True,
        view=None,
        save_overlay=save_overlay,
        log_level="INFO",
    )


def _patch_run_dependencies(monkeypatch, config, source):
    """Thay mọi phụ thuộc nặng của ``cmd_run`` bằng bản giả."""
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "capture_from_config", lambda cfg: source)
    monkeypatch.setattr(cli, "_print_status", lambda *a, **k: None)

    import posture_monitor.pose as pose_mod

    monkeypatch.setattr(pose_mod, "PoseEstimator", lambda cfg: FakeEstimator())

    import posture_monitor.hardware as hardware_mod

    hardware = FakeHardware()
    monkeypatch.setattr(hardware_mod, "create_hardware", lambda *a, **k: hardware)

    sensor = FakeSensor()
    import posture_monitor.sensors as sensors_mod

    monkeypatch.setattr(sensors_mod, "create_sensor", lambda cfg: sensor)

    dispatcher_holder: list[FakeDispatcher] = []

    def make_dispatcher(hw, alerts):
        dispatcher_holder.append(FakeDispatcher())
        return dispatcher_holder[0]

    import posture_monitor.alerts as alerts_mod

    monkeypatch.setattr(alerts_mod, "AlertDispatcher", make_dispatcher)
    return hardware, sensor, dispatcher_holder


def _patch_cv2(monkeypatch, keys, imencode=None):
    """Thay cửa sổ OpenCV; ``keys`` là dãy mã phím trả cho từng lần ``waitKey``."""
    monkeypatch.setattr(cli.cv2, "namedWindow", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "imshow", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "destroyAllWindows", lambda *a, **k: None)
    monkeypatch.setattr(
        cli.cv2, "getWindowProperty", lambda *a, **k: 1.0
    )
    remaining = list(keys)
    monkeypatch.setattr(
        cli.cv2,
        "waitKey",
        lambda *a, **k: remaining.pop(0) if remaining else ord("q"),
    )
    if imencode is not None:
        monkeypatch.setattr(cli.cv2, "imencode", imencode)


def _neutral_baseline() -> Baseline:
    return Baseline(
        values={name: None for name in ALL_NAMES},
        view="front",
        width=640,
        height=480,
        created_at="",
        frames=0,
    )


# ---------------------------------------------------------------------------
# Bất biến 1 + 4: nhánh chạy dài dựng dashboard, không chặn vòng lặp
# ---------------------------------------------------------------------------
def test_run_long_branch_starts_web(monkeypatch, tmp_path):
    """Chạy ``run`` (không save-overlay) phải dựng dashboard và chạy nó."""
    config = _config(tmp_path)
    source = FakeSource()
    hardware, sensor, dispatchers = _patch_run_dependencies(
        monkeypatch, config, source
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(cli, "_Dashboard", FakeDashboard)

    def fake_loop(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(cli, "_monitor_loop", fake_loop)

    exit_code = cli.cmd_run(_run_args())

    assert exit_code == 0
    assert len(FakeDashboard.created) == 1, "nhánh chạy dài phải dựng _Dashboard"
    dashboard = FakeDashboard.created[0]
    assert dashboard.thread.started, "server web phải được start()"
    assert dashboard.thread.daemon is True
    # Vòng lặp nhận đúng state mà create_app dùng chung.
    assert captured["kwargs"]["state"] is dashboard.state
    assert captured["kwargs"]["storage"] is dashboard.storage
    # Dọn dẹp đúng thứ tự: storage đóng, luồng join có timeout.
    assert dashboard.storage.closed
    assert dashboard.thread.joined_with == 1.0
    assert dispatchers[0].closed
    assert sensor.closed
    assert source.closed
    assert hardware.closed


def test_run_server_does_not_block_loop(monkeypatch, tmp_path):
    """``run_server`` chạy ở luồng nền; web không nhận camera ``source``."""
    config = _config(tmp_path)
    captured: dict[str, object] = {}
    entered = threading.Event()

    import posture_monitor.web as web_mod

    real_create_app = web_mod.create_app
    app_holder: list[object] = []

    def spy_create_app(cfg, **kwargs):
        captured["create_app_config"] = cfg
        captured["create_app_kwargs"] = kwargs
        app = real_create_app(cfg, **kwargs)
        app_holder.append(app)
        return app

    def fake_run_server(app, cfg, **kwargs):
        captured["thread"] = threading.current_thread()
        captured["server_app"] = app
        captured["server_config"] = cfg
        captured["server_kwargs"] = kwargs
        entered.set()

    monkeypatch.setattr(web_mod, "create_app", spy_create_app)
    monkeypatch.setattr(web_mod, "run_server", fake_run_server)

    dashboard = cli._Dashboard(config, FakeLogger())
    dashboard.start()
    try:
        assert entered.wait(timeout=2.0), "run_server không được gọi"
        assert captured["thread"] is not threading.main_thread()
        assert captured["thread"].name == "dashboard-web"
        # Bất biến "web không mở camera": run_server chỉ nhận app + config,
        # không nhận source/estimator nào.
        assert captured["server_app"] is app_holder[0]
        assert captured["server_config"] is config
        assert captured["server_kwargs"] == {}
        # create_app nhận đúng state mà vòng lặp sẽ ghi vào.
        assert captured["create_app_kwargs"]["state"] is dashboard.state
        assert captured["create_app_kwargs"]["storage"] is dashboard.storage
        assert captured["create_app_config"] is config
    finally:
        dashboard.storage.close()


# ---------------------------------------------------------------------------
# Bất biến 2: --save-overlay không dựng server
# ---------------------------------------------------------------------------
def test_save_overlay_does_not_start_web(monkeypatch, tmp_path):
    """Nhánh ``--save-overlay`` return sớm, không dựng dashboard/server."""
    config = _config(tmp_path)
    source = FakeSource()

    def boom(*a, **k):
        raise AssertionError("--save-overlay không được dựng dashboard")

    monkeypatch.setattr(cli, "_Dashboard", boom)

    import posture_monitor.pose as pose_mod

    monkeypatch.setattr(pose_mod, "PoseEstimator", lambda cfg: FakeEstimator())
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "capture_from_config", lambda cfg: source)
    monkeypatch.setattr(cli, "_print_status", lambda *a, **k: None)

    import posture_monitor.hardware as hardware_mod

    hardware = FakeHardware()
    monkeypatch.setattr(hardware_mod, "create_hardware", lambda *a, **k: hardware)

    saved: dict[str, object] = {}

    def fake_save(estimator, src, cfg, target, logger):
        saved["target"] = target
        return 0

    monkeypatch.setattr(cli, "_save_one_overlay", fake_save)

    exit_code = cli.cmd_run(_run_args(save_overlay="frame.jpg"))

    assert exit_code == 0
    assert saved["target"] == Path("frame.jpg")
    assert FakeDashboard.created == []
    assert source.closed
    assert hardware.closed


# ---------------------------------------------------------------------------
# Bất biến 3: cổng bận vẫn giám sát
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("error", [OSError("cổng đã bị chiếm"), SystemExit(1)])
def test_busy_port_still_runs(monkeypatch, error):
    """``run_server`` lỗi cổng chỉ cảnh báo tiếng Việt, không ném ra ngoài."""
    import posture_monitor.web as web_mod

    def fake_run_server(app, cfg, **kwargs):
        raise error

    monkeypatch.setattr(web_mod, "run_server", fake_run_server)
    logger = FakeLogger()

    # Không raise = vòng lặp giám sát còn sống.
    cli._serve_web(object(), object(), logger)

    assert logger.warnings, "cổng bận phải ghi cảnh báo"
    assert "dashboard" in logger.warnings[0].lower()
    assert "giám sát" in logger.warnings[0].lower()


# ---------------------------------------------------------------------------
# Vòng lặp đẩy dữ liệu lên web / DB / phần cứng
# ---------------------------------------------------------------------------
def _run_loop_once(monkeypatch, *, muted=False, stream_enabled=False):
    """Chạy một khung của ``_monitor_loop`` với mọi phụ thuộc giả."""
    from posture_monitor.web import DashboardState

    state = DashboardState()
    if muted:
        state.set_muted(True)
    storage = FakeStorage()
    dispatcher = FakeDispatcher()
    sensor = FakeSensor(40.0)

    import posture_monitor.calibration as calibration_mod

    monkeypatch.setattr(
        calibration_mod, "load", lambda path: _neutral_baseline()
    )
    _patch_cv2(
        monkeypatch,
        keys=[ord("q")],
        imencode=lambda ext, img: (
            True,
            type("Buf", (), {"tobytes": lambda self: b"jpeg"})(),
        ),
    )

    exit_code = cli._monitor_loop(
        FakeEstimator(),
        FakeSource(frames=1),
        _config(Path(".")),
        FakeLogger(),
        state=state,
        storage=storage,
        sensor=sensor,
        dispatcher=dispatcher,
        stream_enabled=stream_enabled,
    )
    return exit_code, state, storage, dispatcher


def test_loop_pushes_state_to_dashboard(monkeypatch):
    """Mỗi khung phải cập nhật state, ghi DB và đẩy trạng thái phần cứng."""
    exit_code, state, storage, dispatcher = _run_loop_once(monkeypatch)

    assert exit_code == 0
    snapshot = state.snapshot()
    assert snapshot["state"] == STATE_ABSENT
    assert ABSENT in snapshot["labels"]
    assert snapshot["stale"] is False
    assert snapshot["distance_cm"] == 40.0
    assert len(storage.records) == 1
    assert storage.records[0][1] == 40.0
    assert storage.records[0][0].state == STATE_ABSENT
    assert len(dispatcher.updates) == 1
    # Stream tắt: không mã hoá JPEG chỉ để vứt đi.
    assert state.latest_frame() == (0, None)


def test_loop_streams_frame_only_when_enabled(monkeypatch):
    """``set_frame`` chỉ gọi khi ``web.stream_enabled`` bật."""
    exit_code, state, _storage, _dispatcher = _run_loop_once(
        monkeypatch, stream_enabled=True
    )

    assert exit_code == 0
    seq, frame = state.latest_frame()
    assert seq >= 1
    assert frame == b"jpeg"


def test_loop_mute_blocks_alert_sound(monkeypatch):
    """Đang tắt tiếng: dispatcher nhận bản sao có ``alerts=()``."""
    exit_code, _state, _storage, dispatcher = _run_loop_once(
        monkeypatch, muted=True
    )

    assert exit_code == 0
    assert len(dispatcher.updates) == 1
    assert dispatcher.updates[0].alerts == ()


def test_loop_survives_calibration_request(monkeypatch):
    """Yêu cầu hiệu chỉnh từ web chỉ log hướng dẫn, không tự chạy calibrate."""
    from posture_monitor.web import DashboardState

    state = DashboardState()
    state.request_calibration()

    import posture_monitor.calibration as calibration_mod

    monkeypatch.setattr(
        calibration_mod, "load", lambda path: _neutral_baseline()
    )
    _patch_cv2(monkeypatch, keys=[ord("q")])
    logger = FakeLogger()

    exit_code = cli._monitor_loop(
        FakeEstimator(),
        FakeSource(frames=1),
        _config(Path(".")),
        logger,
        state=state,
        storage=FakeStorage(),
        sensor=None,
        dispatcher=None,
        stream_enabled=False,
    )

    assert exit_code == 0
    assert state.consume_calibration_request() is False
    joined = " ".join(logger.infos)
    assert "calibrate" in joined
    assert "khởi động lại" in joined


def test_loop_timeout_none_does_not_block(monkeypatch):
    """Mọi phụ thuộc ``None``: vòng lặp vẫn chạy như bản xem trước cũ."""
    import posture_monitor.calibration as calibration_mod

    monkeypatch.setattr(
        calibration_mod, "load", lambda path: _neutral_baseline()
    )
    _patch_cv2(monkeypatch, keys=[ord("q")])

    exit_code = cli._monitor_loop(
        FakeEstimator(),
        FakeSource(frames=1),
        _config(Path(".")),
        FakeLogger(),
    )

    assert exit_code == 0
