"""Kiểm thử nguồn ảnh và phát hiện thiết bị (spec v2 §5.1).

Test chạy được trên PC, không phụ thuộc camera thật: video giả được tạo bằng
``cv2.VideoWriter`` trong ``tmp_path``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

# Cho phép chạy `pytest tests/` từ gốc repo mà không cần cài gói.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor import capture  # noqa: E402
from posture_monitor.capture import (  # noqa: E402
    CameraError,
    FileSource,
    OpenCVSource,
    capture_from_config,
    list_capture_devices,
    probe_cameras,
)
from posture_monitor.config import Config  # noqa: E402


def _make_video(path: Path, frames: int = 12, size: tuple[int, int] = (64, 48)) -> Path:
    """Tạo video giả lập nhỏ bằng VideoWriter; trả đường dẫn."""
    width, height = size
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(str(path), fourcc, 10.0, (width, height))
    if not writer.isOpened():
        pytest.skip("OpenCV không ghi được MJPG trên máy này.")
    try:
        for i in range(frames):
            # Màu thay đổi theo khung để dễ phân biệt khung đầu/cuối.
            frame = np.full((height, width, 3), (i * 10) % 255, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()
    return path


# --------------------------------------------------------------------------
# FileSource
# --------------------------------------------------------------------------


def test_file_source_reads_frames(tmp_path: Path) -> None:
    video = _make_video(tmp_path / "sample.avi", frames=10)
    source = FileSource(video, loop=False)
    try:
        frame = source.read()
        assert frame is not None
        assert isinstance(frame, np.ndarray)
        assert frame.dtype == np.uint8
        assert frame.shape == (48, 64, 3)
        assert source.backend == "file"
    finally:
        source.close()


def test_file_source_loops_when_enabled(tmp_path: Path) -> None:
    video = _make_video(tmp_path / "loop.avi", frames=5)
    source = FileSource(video, loop=True)
    try:
        # Đọc quá số khung của video: phải quay lại đầu chứ không trả None.
        frames = [source.read() for _ in range(12)]
        assert all(frame is not None for frame in frames)
    finally:
        source.close()


def test_file_source_close_is_idempotent(tmp_path: Path) -> None:
    video = _make_video(tmp_path / "close.avi", frames=3)
    source = FileSource(video)
    source.close()
    source.close()  # không được raise
    assert source.read() is None


def test_file_source_missing_path_raises_camera_error(tmp_path: Path) -> None:
    with pytest.raises(CameraError):
        FileSource(tmp_path / "khong_ton_tai.mp4")


# --------------------------------------------------------------------------
# Phát hiện thiết bị
# --------------------------------------------------------------------------


def test_probe_cameras_returns_expected_structure() -> None:
    result = probe_cameras()

    assert isinstance(result, dict)
    assert set(result) == {"picamera", "usb"}

    picamera = result["picamera"]
    assert isinstance(picamera, dict)
    assert set(picamera) == {"available", "reason"}
    assert isinstance(picamera["available"], bool)
    assert isinstance(picamera["reason"], str)
    assert picamera["reason"], "phải có lý do cụ thể, kể cả khi không có camera"

    usb = result["usb"]
    assert isinstance(usb, list)
    for item in usb:
        assert set(item) == {"index", "name", "available"}
        assert isinstance(item["index"], int)
        assert isinstance(item["name"], str)
        assert isinstance(item["available"], bool)


def test_probe_cameras_does_not_raise_without_hardware() -> None:
    # Không có camera trên máy test: hàm phải trả available=False, không raise.
    result = probe_cameras()
    if not result["usb"] and not result["picamera"]["available"]:
        assert result["picamera"]["available"] is False
        assert result["picamera"]["reason"]


def test_list_capture_devices_excludes_soc_codec_nodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Node bcm2835-codec/bcm2835-isp/rpi-hevc-dec phải bị đánh dấu không capture.

    Dựng sysfs và /dev giả trong ``tmp_path`` để kiểm tra logic lọc mà không
    cần phần cứng Pi. Việc đọc symlink driver được thay bằng bảng tra cứu vì
    Windows không cho tạo symlink khi thiếu quyền quản trị.
    """
    dev_dir = tmp_path / "dev"
    sysfs = tmp_path / "sysfs"
    sysfs.mkdir(parents=True)

    entries = {
        0: ("uvcvideo", "USB Camera"),
        10: ("bcm2835-codec", "bcm2835-codec-decode"),
        11: ("bcm2835-isp", "bcm2835-isp"),
        12: ("rpi-hevc-dec", "rpi-hevc-dec"),
    }
    dev_dir.mkdir(parents=True)
    for index, (_driver, card) in entries.items():
        node = sysfs / f"video{index}"
        node.mkdir()
        (node / "name").write_text(card + "\n", encoding="utf-8")
        (dev_dir / f"video{index}").touch()

    drivers = {index: driver for index, (driver, _card) in entries.items()}

    monkeypatch.setattr(capture, "SYSFS_VIDEO4LINUX", sysfs)
    monkeypatch.setattr(capture, "DEV_DIR", dev_dir)
    monkeypatch.setattr(
        capture, "_driver_name_for", lambda index: drivers.get(index, "")
    )
    # Không thật sự mở thiết bị trong test: coi node không bị loại là capture.
    monkeypatch.setattr(capture, "_can_open_capture", lambda _index: True)

    devices = list_capture_devices(probe_opencv=True)
    by_index = {device.index: device for device in devices}

    assert by_index[0].is_capture is True
    assert by_index[0].driver_name == "uvcvideo"
    assert by_index[0].card_name == "USB Camera"
    assert by_index[10].is_capture is False
    assert by_index[11].is_capture is False
    assert by_index[12].is_capture is False


def test_driver_name_for_missing_path_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Không đọc được sysfs (node ảo) thì trả chuỗi rỗng, không raise."""
    node = tmp_path / "video99"
    node.mkdir()
    (node / "name").write_text("some device\n", encoding="utf-8")

    monkeypatch.setattr(capture, "SYSFS_VIDEO4LINUX", tmp_path)
    assert capture._driver_name_for(99) == ""


def test_excluded_drivers_match_by_substring() -> None:
    """Tên card chứa chuỗi driver của SoC cũng bị loại."""
    assert capture._is_excluded("bcm2835-codec", "bcm2835-codec-decode")
    assert capture._is_excluded("", "bcm2835-isp")
    assert capture._is_excluded("", "rpi-hevc-dec")
    assert not capture._is_excluded("uvcvideo", "USB Camera")


# --------------------------------------------------------------------------
# capture_from_config — không crash khi thiếu phần cứng
# --------------------------------------------------------------------------


def test_capture_from_config_missing_file_returns_none() -> None:
    config = Config()
    config.camera.source = "file:khong/co/video_nay.mp4"

    # Không raise; trả None và ghi log lý do.
    result = capture_from_config(config)
    assert result is None


def test_capture_from_config_picamera_on_pc_returns_none() -> None:
    config = Config()
    config.camera.source = "picamera"

    # Trên PC không có picamera2/Pi Camera: phải trả None thay vì crash.
    result = capture_from_config(config)
    assert result is None


def test_capture_from_config_usb_failure_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Khi mở USB thất bại, capture_from_config nuốt lỗi và trả None."""

    def _fail(*_args, **_kwargs):
        raise CameraError("giả lập: không có camera USB")

    monkeypatch.setattr(capture, "OpenCVSource", _fail)

    config = Config()
    config.camera.source = "usb:9"
    result = capture_from_config(config)
    assert result is None


def test_capture_from_config_opens_file_source(tmp_path: Path) -> None:
    video = _make_video(tmp_path / "ok.avi", frames=4)
    config = Config()
    config.camera.source = f"file:{video}"

    source = capture_from_config(config)
    try:
        assert source is not None
        assert source.backend == "file"
        assert source.read() is not None
    finally:
        if source is not None:
            source.close()


# --------------------------------------------------------------------------
# Giao diện FrameSource
# --------------------------------------------------------------------------


def test_opencv_source_exposes_backend() -> None:
    # Chỉ kiểm tra lớp học trừu tượng; không mở thiết bị thật.
    assert issubclass(OpenCVSource, capture.FrameSource)
    assert issubclass(FileSource, capture.FrameSource)


# --------------------------------------------------------------------------
# PiCameraSource — kiểm tra bằng picamera2 giả
# --------------------------------------------------------------------------


class _FakePicamera2:
    """Bản giả tối thiểu của ``picamera2.Picamera2``."""

    def __init__(self) -> None:
        self.config = None
        self.started = False
        self.stopped = False
        self.closed = False

    def create_video_configuration(self, main=None):
        return {"main": main}

    def configure(self, config) -> None:
        self.config = config

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True

    def capture_array(self, stream: str = "main"):
        return np.full((480, 640, 3), 42, dtype=np.uint8)


def test_picamera_source_uses_rgb888_main_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phải cấu hình ``main`` với RGB888 để khung có byte [B, G, R] = BGR.

    KHÔNG được "sửa lại cho đúng tên" thành BGR888: tên format của picamera2
    ngược với thứ tự byte thật. Theo picamera2 manual RP-008156-DS-7
    (Appendix A, đúng bản 0.3.37 đang dùng), ``BGR888`` cho ``[R,G,B]`` còn
    ``RGB888`` cho ``[B,G,R]``; source ``picamera2/request.py`` cũng ánh xạ
    ``"BGR888"`` → ``"RGB"`` cho simplejpeg. Chọn BGR888 sẽ làm khung bị đảo
    kênh đỏ/xanh một cách âm thầm, vì ``FrameSource.read()`` quy ước trả BGR và
    repo không có ``cv2.cvtColor`` dự phòng.
    """
    from posture_monitor.capture import PiCameraSource

    created: list[_FakePicamera2] = []

    def fake_cls():
        camera = _FakePicamera2()
        created.append(camera)
        return camera

    # ``_load_picamera2`` thật import thư viện rồi gán ``self._picamera2_cls``;
    # bản giả làm đúng việc đó với lớp thay thế (không đụng tới apt/pip).
    def fake_load(self) -> None:
        self._picamera2_cls = fake_cls

    monkeypatch.setattr(PiCameraSource, "_load_picamera2", fake_load)

    source = PiCameraSource(640, 480)
    try:
        assert len(created) == 1, "phải khởi tạo đúng một đối tượng camera"
        camera = created[0]

        assert camera.started is True
        assert camera.config == {
            "main": {"size": (640, 480), "format": "RGB888"}
        }
        assert source.backend == "picamera"

        frame = source.read()
        assert frame is not None
        assert frame.shape == (480, 640, 3)
        assert frame[0, 0, 0] == 42
    finally:
        source.close()

    assert camera.closed is True
    assert camera.stopped is True


def test_picamera_source_reports_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Không có picamera2: phải ném CameraError, và capture_from_config nuốt lỗi."""
    from posture_monitor.capture import PiCameraSource

    def _raise(self) -> None:
        raise CameraError("giả lập: không có picamera2")

    monkeypatch.setattr(PiCameraSource, "_load_picamera2", _raise)

    with pytest.raises(CameraError):
        PiCameraSource(640, 480)

    config = Config()
    config.camera.source = "picamera"
    assert capture_from_config(config) is None


# --------------------------------------------------------------------------
# OpenCVSource — số lần thử có giới hạn, có backoff (spec §5.1)
# --------------------------------------------------------------------------


class _FailingCapture:
    """``cv2.VideoCapture`` giả: luôn không mở được."""

    def __init__(self, *args, **kwargs) -> None:
        self.released = False

    def isOpened(self) -> bool:
        return False

    def release(self) -> None:
        self.released = True


def test_opencv_source_stops_after_open_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Không mở được thì thử đúng OPEN_ATTEMPTS lần rồi ném CameraError."""
    attempts: list[float] = []

    def fake_video_capture(*args, **kwargs):
        attempts.append(1.0)
        return _FailingCapture()

    monkeypatch.setattr(capture.cv2, "VideoCapture", fake_video_capture)
    monkeypatch.setattr(capture, "_sleep", lambda _seconds: None)

    with pytest.raises(CameraError) as excinfo:
        OpenCVSource(index=7, width=640, height=480, max_attempts=3)

    assert len(attempts) == 3
    assert "7" in str(excinfo.value)


def test_opencv_source_backs_off_between_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Giữa các lần thử phải có thời gian chờ tăng dần, không thử dồn dập."""
    delays: list[float] = []

    monkeypatch.setattr(
        capture.cv2, "VideoCapture", lambda *a, **k: _FailingCapture()
    )
    monkeypatch.setattr(capture, "_sleep", delays.append)

    with pytest.raises(CameraError):
        OpenCVSource(index=7, max_attempts=3)

    # Không ngủ sau lần thử cuối; các lần trước ngủ tăng dần.
    assert len(delays) == 2
    assert delays[0] <= delays[1]


def test_opencv_source_open_returns_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    """Đường thành công: mở được thì đọc ra khung và backend là 'opencv'."""
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    class _OkCapture(_FailingCapture):
        def isOpened(self) -> bool:
            return True

        def set(self, *_args) -> bool:
            return True

        def read(self):
            return True, frame

    monkeypatch.setattr(capture.cv2, "VideoCapture", lambda *a, **k: _OkCapture())
    monkeypatch.setattr(capture, "_sleep", lambda _seconds: None)

    source = OpenCVSource(index=0)
    try:
        assert source.backend == "opencv"
        result = source.read()
        assert result is not None
        assert result.shape == (480, 640, 3)
    finally:
        source.close()


def test_opencv_source_read_returns_none_after_failed_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mất kết nối không nối lại được: ``read()`` trả None, không raise."""
    state = {"opened": True}

    class _FlakyCapture(_FailingCapture):
        def isOpened(self) -> bool:
            return state["opened"]

        def set(self, *_args) -> bool:
            return True

        def read(self):
            return False, None

    monkeypatch.setattr(
        capture.cv2, "VideoCapture", lambda *a, **k: _FlakyCapture()
    )
    monkeypatch.setattr(capture, "_sleep", lambda _seconds: None)

    source = OpenCVSource(index=0)
    try:
        state["opened"] = False  # camera bị rút
        assert source.read() is None
        assert source.read() is None  # vẫn None, không treo/raise
    finally:
        source.close()


def test_opencv_source_gives_up_after_reconnect_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sau khi camera mất, chỉ thử mở lại tối đa OPEN_ATTEMPTS lần rồi bỏ."""
    open_calls: list[int] = []

    class _FlakyCapture(_FailingCapture):
        def __init__(self, *args, **kwargs) -> None:
            open_calls.append(1)

        def isOpened(self) -> bool:
            # Chỉ lần mở đầu tiên thành công; sau đó luôn thất bại.
            return len(open_calls) == 1

        def set(self, *_args) -> bool:
            return True

        def read(self):
            return False, None

    monkeypatch.setattr(
        capture.cv2, "VideoCapture", lambda *a, **k: _FlakyCapture()
    )
    monkeypatch.setattr(capture, "_sleep", lambda _seconds: None)

    source = OpenCVSource(index=0, max_attempts=3)
    try:
        # Đọc vài lần: mỗi read() tốn tối đa một lần mở lại, và ngân sách có hạn.
        for _ in range(15):
            assert source.read() is None

        # 1 lần mở ban đầu + tối đa 3 lần mở lại; không được vô hạn.
        assert len(open_calls) <= 1 + 3
        assert source._gave_up is True
    finally:
        source.close()
