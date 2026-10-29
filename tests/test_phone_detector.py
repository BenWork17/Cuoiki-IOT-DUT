"""Kiểm thử ``phone_detector.py`` — model dò điện thoại + bộ lọc thời gian.

Không cần trọng số thật, không cần GPU, không cần camera: model ultralytics
được thay bằng đối tượng giả trả kết quả COCO dựng tay, đúng kiểu
``tests/test_pose.py``. Đồng hồ của :class:`PhoneSignal` là tham số ``now``
tiêm từ ngoài, nên không có ``sleep`` và kết quả tất định.

Ma trận mutation tương ứng (xem báo cáo):

- đổi ``PHONE_CLASS_ID`` → :func:`test_detect_filters_phone_class`.
- bỏ kiểm tra TTL → :func:`test_boxes_expire_after_ttl`.
- bỏ qua ``detect_every_n_frames`` → :func:`test_detect_runs_every_n_frames`.
- trả hộp trong hệ 320 → :func:`test_detect_returns_frame_pixel_coordinates`.
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

from posture_monitor.config import (  # noqa: E402
    Config,
    ConfigError,
    ModelConfig,
    PhoneConfig,
    load_config,
)
from posture_monitor.phone import PHONE_CLASS_ID  # noqa: E402
from posture_monitor.phone_detector import (  # noqa: E402
    PhoneDetector,
    PhoneDetectorError,
    PhoneSignal,
)

#: Lớp "person" trong COCO — không bao giờ được trả về như điện thoại.
PERSON_CLASS_ID = 0


# --------------------------------------------------------------------------
# Đối tượng giả mô phỏng output ultralytics
# --------------------------------------------------------------------------


class _FakeTensor:
    def __init__(self, array) -> None:
        self._array = np.asarray(array, dtype=np.float32)

    def cpu(self):
        return self

    def numpy(self):
        return self._array


class _FakeBoxes:
    def __init__(self, xyxy, cls) -> None:
        self.xyxy = _FakeTensor(xyxy)
        self.cls = None if cls is None else _FakeTensor(cls)

    def __len__(self) -> int:
        return len(self.xyxy._array)


class _FakeResult:
    def __init__(self, boxes) -> None:
        self.boxes = boxes


class _FakeModel:
    def __init__(self, results) -> None:
        self._results = results
        self.predict_calls = 0

    def predict(self, frame, **kwargs):
        self.predict_calls += 1
        return self._results


def _detector(monkeypatch, results, *, frame_scale=None) -> PhoneDetector:
    """``PhoneDetector`` gắn model giả qua backend ``pt``, không chạm ultralytics."""

    class _FakeYOLO:
        def __init__(self, source):
            self.source = source

        def export(self, **kwargs):  # pragma: no cover - nhánh export
            return "exported"

    monkeypatch.setattr(PhoneDetector, "_yolo", staticmethod(lambda: _FakeYOLO))
    detector = PhoneDetector("dummy.pt", model_format="pt")
    detector._model = _FakeModel(results)
    detector._backend = "pt"
    return detector


# --------------------------------------------------------------------------
# PhoneDetector.detect — lọc lớp, hệ toạ độ, hộp hỏng
# --------------------------------------------------------------------------


def test_detect_filters_phone_class(monkeypatch):
    """Chỉ hộp lớp 67 được trả; hộp 'person' (lớp 0) bị loại."""
    assert PHONE_CLASS_ID == 67, "hằng số lớp phải là 'cell phone' COCO"
    boxes = _FakeBoxes(
        xyxy=[
            [10.0, 20.0, 60.0, 120.0],  # person
            [200.0, 30.0, 240.0, 180.0],  # phone
        ],
        cls=[PERSON_CLASS_ID, PHONE_CLASS_ID],
    )
    detector = _detector(monkeypatch, [_FakeResult(boxes)])

    found = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8))

    assert found == [(200.0, 30.0, 240.0, 180.0)]


def test_detect_returns_frame_pixel_coordinates(monkeypatch):
    """Hộp trả về đúng hệ pixel khung (640×480), không bị co về 320."""
    boxes = _FakeBoxes(
        xyxy=[[100.0, 120.0, 180.0, 300.0]], cls=[PHONE_CLASS_ID]
    )
    detector = _detector(monkeypatch, [_FakeResult(boxes)])

    found = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8))

    # Nếu ai đó "quy về imgsz 320" thì toạ độ bị chia đôi và test này đỏ.
    assert found == [(100.0, 120.0, 180.0, 300.0)]


def test_detect_drops_nan_and_inverted_boxes(monkeypatch):
    """Hộp NaN/inf hoặc đảo cạnh bị bỏ, hộp lành vẫn được giữ."""
    boxes = _FakeBoxes(
        xyxy=[
            [float("nan"), 10.0, 50.0, 50.0],
            [10.0, 10.0, float("inf"), 50.0],
            [90.0, 90.0, 60.0, 60.0],  # đảo cạnh
            [300.0, 200.0, 340.0, 260.0],
        ],
        cls=[PHONE_CLASS_ID] * 4,
    )
    detector = _detector(monkeypatch, [_FakeResult(boxes)])

    found = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8))

    assert found == [(300.0, 200.0, 340.0, 260.0)]


def test_detect_without_class_labels_returns_nothing(monkeypatch):
    """Không có nhãn lớp thì không đoán: trả danh sách rỗng."""
    boxes = _FakeBoxes(xyxy=[[0.0, 0.0, 10.0, 10.0]], cls=None)
    detector = _detector(monkeypatch, [_FakeResult(boxes)])

    assert detector.detect(np.zeros((480, 640, 3), dtype=np.uint8)) == []


def test_detect_no_results_is_empty(monkeypatch):
    detector = _detector(monkeypatch, [])
    assert detector.detect(np.zeros((480, 640, 3), dtype=np.uint8)) == []


# --------------------------------------------------------------------------
# Nạp model lười và lỗi thiếu trọng số
# --------------------------------------------------------------------------


def test_constructor_does_not_load_model(monkeypatch):
    """Tạo đối tượng không được nạp model hay crash vì thiếu trọng số."""

    class _Boom:
        def __init__(self, source):
            raise AssertionError("constructor không được nạp model")

    monkeypatch.setattr(PhoneDetector, "_yolo", staticmethod(lambda: _Boom))
    detector = PhoneDetector("khong_ton_tai.pt", model_format="pt")
    assert detector.backend == "chưa nạp"


def test_missing_weights_raises_error_with_path(monkeypatch):
    """Thiếu trọng số → ``PhoneDetectorError`` có đường dẫn, không phải crash mờ."""

    class _Boom:
        def __init__(self, source):
            raise FileNotFoundError("không có file trọng số")

    monkeypatch.setattr(PhoneDetector, "_yolo", staticmethod(lambda: _Boom))
    missing = Path("khong_co_model_nay.pt")
    detector = PhoneDetector(missing, model_format="ncnn")

    with pytest.raises(PhoneDetectorError) as excinfo:
        detector.detect(np.zeros((480, 640, 3), dtype=np.uint8))

    message = str(excinfo.value)
    assert str(missing.resolve()) in message
    assert "khong_co_model_nay.pt" in message


def test_predict_failure_becomes_detector_error(monkeypatch):
    """Model lỗi lúc suy luận → ``PhoneDetectorError``, không lộ RuntimeError."""

    class _BoomModel:
        def predict(self, frame, **kwargs):
            raise RuntimeError("onnx session hỏng")

    detector = _detector(monkeypatch, [])
    detector._model = _BoomModel()

    with pytest.raises(PhoneDetectorError) as excinfo:
        detector.detect(np.zeros((480, 640, 3), dtype=np.uint8))
    assert "onnx session hỏng" in str(excinfo.value)


# --------------------------------------------------------------------------
# PhoneSignal — nhịp detect, TTL, tích luỹ thời gian
# --------------------------------------------------------------------------


class _CountingDetector:
    """Detector giả: trả hộp cố định và đếm số lần được gọi."""

    def __init__(self, boxes=None, error: Exception | None = None) -> None:
        self.boxes = [(200.0, 100.0, 260.0, 300.0)] if boxes is None else boxes
        self.error = error
        self.calls = 0

    def detect(self, frame):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.boxes)


def _keypoints(tay=(210.0, 150.0, 0.9)) -> np.ndarray:
    """Keypoint (17,3): cổ tay trái trong hộp điện thoại, cổ tay phải ẩn."""
    kp = np.zeros((17, 3), dtype=np.float32)
    kp[:, 0] = 10.0
    kp[:, 1] = 10.0
    kp[:, 2] = 0.9
    kp[9] = tay
    kp[10] = (0.0, 0.0, 0.0)
    return kp


def _signal(detector, **overrides) -> PhoneSignal:
    phone = PhoneConfig(**overrides)
    config = Config(
        phone=phone, model=ModelConfig(kp_conf_min=0.5, format="pt")
    )
    return PhoneSignal(config, detector=detector)


_FRAME = np.zeros((480, 640, 3), dtype=np.uint8)


def test_detect_runs_every_n_frames():
    """``detect_every_n_frames: 2`` → 6 khung gọi detect đúng 3 lần."""
    detector = _CountingDetector()
    signal = _signal(
        detector, detect_every_n_frames=2, box_ttl_s=100.0, hold_s=0.0
    )

    for index in range(6):
        signal.observe(_FRAME, _keypoints(), now=float(index))

    assert detector.calls == 3


def test_boxes_expire_after_ttl():
    """Hộp cũ hơn ``box_ttl_s`` bị bỏ, nên khung đó không xét được."""
    detector = _CountingDetector()
    signal = _signal(
        detector,
        detect_every_n_frames=100,
        box_ttl_s=0.5,
        hold_s=0.0,
    )

    first = signal.observe(_FRAME, _keypoints(), now=100.0)
    assert first is not None
    assert first.co_cham is True

    # Hộp đã 0,6 giây tuổi, quá box_ttl_s = 0,5; nhịp detect chưa tới.
    expired = signal.observe(_FRAME, _keypoints(), now=100.6)
    assert expired is None
    assert detector.calls == 1


def test_box_within_ttl_still_used():
    """Trong hạn TTL thì hộp của lần detect trước vẫn dùng được."""
    detector = _CountingDetector()
    signal = _signal(
        detector, detect_every_n_frames=100, box_ttl_s=0.5, hold_s=0.0
    )

    signal.observe(_FRAME, _keypoints(), now=100.0)
    still_valid = signal.observe(_FRAME, _keypoints(), now=100.4)

    assert still_valid is not None
    assert detector.calls == 1


def test_held_seconds_accumulate_and_reset():
    """``held_s`` cộng dồn khi chạm liên tục và về 0 khi rời tay."""
    detector = _CountingDetector()
    signal = _signal(
        detector, detect_every_n_frames=1, box_ttl_s=10.0, hold_s=2.0
    )

    signal.observe(_FRAME, _keypoints(), now=0.0)
    assert signal.held_s == pytest.approx(0.0)
    assert signal.in_use is False

    signal.observe(_FRAME, _keypoints(), now=1.0)
    assert signal.held_s == pytest.approx(1.0)
    assert signal.in_use is False

    signal.observe(_FRAME, _keypoints(), now=2.0)
    assert signal.held_s == pytest.approx(2.0)
    assert signal.in_use is True

    # Tay rời khỏi hộp: chuỗi chạm đứt.
    signal.observe(_FRAME, _keypoints(tay=(600.0, 450.0, 0.9)), now=3.0)
    assert signal.held_s == pytest.approx(0.0)
    assert signal.in_use is False


def test_no_detect_without_usable_wrist():
    """Cả hai cổ tay dưới ngưỡng conf → không chạy detect, trả ``None``."""
    detector = _CountingDetector()
    signal = _signal(detector, detect_every_n_frames=1, box_ttl_s=10.0)

    kp = _keypoints(tay=(210.0, 150.0, 0.1))
    assert signal.observe(_FRAME, kp, now=0.0) is None
    assert detector.calls == 0


def test_disabled_signal_never_detects():
    """``enabled: false`` tắt sạch: không detect, không kết quả."""
    detector = _CountingDetector()
    signal = _signal(detector, enabled=False, detect_every_n_frames=1)

    assert signal.observe(_FRAME, _keypoints(), now=0.0) is None
    assert signal.observe(_FRAME, _keypoints(), now=1.0) is None
    assert detector.calls == 0
    assert signal.enabled is False


def test_detector_error_disables_signal_without_crashing():
    """Lỗi model được nuốt: tắt tính năng, vòng lặp chính vẫn chạy."""
    detector = _CountingDetector(
        error=PhoneDetectorError("thiếu trọng số yolo11n.pt")
    )
    signal = _signal(detector, detect_every_n_frames=1, box_ttl_s=10.0)

    assert signal.observe(_FRAME, _keypoints(), now=0.0) is None
    assert signal.enabled is False
    # Đã tắt thì không gọi detect lần nữa.
    assert signal.observe(_FRAME, _keypoints(), now=1.0) is None
    assert detector.calls == 1


def test_observe_rejects_non_finite_now():
    detector = _CountingDetector()
    signal = _signal(detector, detect_every_n_frames=1, box_ttl_s=10.0)
    assert signal.observe(_FRAME, _keypoints(), now=float("nan")) is None
    assert detector.calls == 0


# --------------------------------------------------------------------------
# PhoneConfig
# --------------------------------------------------------------------------


def _config_file(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_phone_config_loads(tmp_path):
    path = _config_file(
        tmp_path,
        """
phone:
  enabled: true
  detect_model: yolo11n
  detect_every_n_frames: 3
  imgsz: 416
  conf_threshold: 0.4
  box_ttl_s: 0.75
  hold_s: 4.5
  touching_slack_px: 6
""",
    )

    config = load_config(path)

    assert isinstance(config.phone, PhoneConfig)
    assert config.phone.enabled is True
    assert config.phone.detect_every_n_frames == 3
    assert config.phone.imgsz == 416
    assert config.phone.conf_threshold == pytest.approx(0.4)
    assert config.phone.box_ttl_s == pytest.approx(0.75)
    assert config.phone.hold_s == pytest.approx(4.5)
    assert config.phone.touching_slack_px == pytest.approx(6.0)


def test_phone_config_defaults_when_section_missing(tmp_path):
    config = load_config(_config_file(tmp_path, "camera:\n  source: usb:0\n"))
    assert config.phone.enabled is True
    assert config.phone.detect_model == "yolo11n"
    assert config.phone.detect_weights == ""
    assert config.phone.detect_every_n_frames == 2
    assert config.phone.imgsz == 320
    assert config.phone.hold_s == pytest.approx(2.0)
    assert config.phone.touching_slack_px == pytest.approx(0.0)


@pytest.mark.parametrize(
    "body, key",
    [
        ("phone:\n  detect_every_n_frames: hai\n", "phone.detect_every_n_frames"),
        ("phone:\n  detect_every_n_frames: 0\n", "phone.detect_every_n_frames"),
        ("phone:\n  enabled: co\n", "phone.enabled"),
        ("phone:\n  imgsz: 0\n", "phone.imgsz"),
        ("phone:\n  conf_threshold: 2.0\n", "phone.conf_threshold"),
        ("phone:\n  box_ttl_s: -1\n", "phone.box_ttl_s"),
        ("phone:\n  hold_s: -2\n", "phone.hold_s"),
        ("phone:\n  touching_slack_px: -3\n", "phone.touching_slack_px"),
        ("phone: 5\n", "phone"),
    ],
)
def test_phone_config_type_errors_name_key(tmp_path, body, key):
    with pytest.raises(ConfigError) as excinfo:
        load_config(_config_file(tmp_path, body))
    assert key in str(excinfo.value)


def test_disabled_phone_config_turns_everything_off(tmp_path):
    path = _config_file(
        tmp_path,
        "phone:\n  enabled: false\n  detect_model: yolo11n\n",
    )
    config = load_config(path)
    assert config.phone.enabled is False

    detector = _CountingDetector()
    signal = PhoneSignal(config, detector=detector)
    assert signal.observe(_FRAME, _keypoints(), now=0.0) is None
    assert detector.calls == 0
    assert signal.enabled is False
