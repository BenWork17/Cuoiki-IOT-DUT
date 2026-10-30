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
    boxes = _FakeBoxes(xyxy=[[100.0, 120.0, 180.0, 300.0]], cls=[PHONE_CLASS_ID])
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
    config = Config(phone=phone, model=ModelConfig(kp_conf_min=0.5, format="pt"))
    return PhoneSignal(config, detector=detector)


_FRAME = np.zeros((480, 640, 3), dtype=np.uint8)


def test_detect_runs_every_n_frames():
    """``detect_every_n_frames: 2`` → 6 khung gọi detect đúng 3 lần."""
    detector = _CountingDetector()
    signal = _signal(detector, detect_every_n_frames=2, box_ttl_s=100.0, hold_s=0.0)

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
    signal = _signal(detector, detect_every_n_frames=100, box_ttl_s=0.5, hold_s=0.0)

    signal.observe(_FRAME, _keypoints(), now=100.0)
    still_valid = signal.observe(_FRAME, _keypoints(), now=100.4)

    assert still_valid is not None
    assert detector.calls == 1


def test_held_seconds_accumulate_and_reset():
    """``held_s`` cộng dồn khi chạm liên tục và về 0 khi rời tay."""
    detector = _CountingDetector()
    signal = _signal(detector, detect_every_n_frames=1, box_ttl_s=10.0, hold_s=2.0)

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


def test_reset_xoa_hop_va_chuoi_cham():
    """``reset()`` dùng khi bắt đầu phiên mới.

    Không reset thì ``held_s`` từ phiên trước đứng yên (``_register_miss``
    không đặt lại khi không có hộp), và khung đầu tiên của phiên mới đã
    "chạm đủ lâu" → báo dùng điện thoại oan ngay.
    """
    detector = _CountingDetector()
    signal = _signal(detector, detect_every_n_frames=1, box_ttl_s=10.0, hold_s=1.0)

    for now in (0.0, 1.0, 2.0):
        signal.observe(_FRAME, _keypoints(), now=now)
    assert signal.in_use is True

    signal.reset()
    assert signal.held_s == pytest.approx(0.0)
    assert signal.in_use is False
    assert signal.boxes(2.0) == (), "hộp cũ không được vẽ lại lên khung phiên mới"

    # Khung đầu tiên của phiên mới không được coi là đã chạm đủ 1 giây.
    signal.observe(_FRAME, _keypoints(), now=3.0)
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
    detector = _CountingDetector(error=PhoneDetectorError("thiếu trọng số yolo11n.pt"))
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


# --------------------------------------------------------------------------
# Cổ tay: ngưỡng riêng của đường điện thoại, không mượn của pose
# --------------------------------------------------------------------------


def test_co_tay_lay_nguong_rieng_khong_muon_kp_conf_min():
    """``model.kp_conf_min`` 0,5 không được làm hỏng đường điện thoại.

    Đo trên camera thật: cổ tay đang cầm điện thoại chỉ đạt 0,35-0,43. Lấy
    ngưỡng của pose (0,5) thì ``_usable_keypoints`` trả ``None`` và detect
    **không bao giờ chạy**.
    """
    detector = _CountingDetector()
    phone = PhoneConfig(wrist_conf_min=0.25, detect_every_n_frames=1, box_ttl_s=10.0)
    config = Config(phone=phone, model=ModelConfig(kp_conf_min=0.5, format="pt"))
    signal = PhoneSignal(config, detector=detector)

    kp = _keypoints(tay=(210.0, 150.0, 0.4))
    assert signal.observe(_FRAME, kp, now=0.0) is not None
    assert detector.calls == 1


def test_nguong_co_tay_rieng_van_chan_duoc_duoi_nguong():
    """Đổi ngưỡng không phải bỏ ngưỡng: 0,1 vẫn dưới ``wrist_conf_min`` 0,25."""
    detector = _CountingDetector()
    phone = PhoneConfig(wrist_conf_min=0.25, detect_every_n_frames=1)
    config = Config(phone=phone, model=ModelConfig(kp_conf_min=0.5, format="pt"))
    signal = PhoneSignal(config, detector=detector)

    kp = _keypoints(tay=(210.0, 150.0, 0.1))
    assert signal.observe(_FRAME, kp, now=0.0) is None
    assert detector.calls == 0


def test_min_kp_conf_tham_so_ghi_de_nguong_cau_hinh():
    detector = _CountingDetector()
    phone = PhoneConfig(wrist_conf_min=0.25, detect_every_n_frames=1)
    config = Config(phone=phone, model=ModelConfig(kp_conf_min=0.5, format="pt"))
    signal = PhoneSignal(config, detector=detector, min_kp_conf=0.9)

    kp = _keypoints(tay=(210.0, 150.0, 0.4))
    assert signal.observe(_FRAME, kp, now=0.0) is None
    assert detector.calls == 0


# --------------------------------------------------------------------------
# Ngưỡng "chạm" co theo bề rộng vai
# --------------------------------------------------------------------------


def _than(vai_trai, vai_phai, tay=(210.0, 150.0, 0.9)):
    """Keypoint (17,3) có hai vai đặt được; hộp giả là (200,100)-(260,300)."""
    kp = _keypoints(tay=tay)
    kp[0] = (230.0, 60.0, 0.9)  # mũi cao trên hộp
    kp[5] = vai_trai
    kp[6] = vai_phai
    return kp


def test_nguong_cham_co_theo_be_rong_vai():
    """Cổ tay cách hộp 100 px, vai rộng 160 px, ratio 1,0 → 160 px: chạm.

    Với ngưỡng pixel cố định 0 (cấu hình cũ) đúng khung này là **không chạm**
    — đó là lý do 0/40 khung trên camera thật không bao giờ báo.
    """
    detector = _CountingDetector(boxes=[(200.0, 100.0, 260.0, 300.0)])
    signal = _signal(
        detector,
        detect_every_n_frames=1,
        box_ttl_s=10.0,
        hold_s=0.0,
        shoulder_ratio=1.0,
        touching_slack_px=0,
    )
    kp = _than((0.0, 0.0, 0.9), (160.0, 0.0, 0.9), tay=(360.0, 300.0, 0.9))

    result = signal.observe(_FRAME, kp, now=0.0)

    assert result is not None
    assert result.khoang_cach_nho_nhat == pytest.approx(100.0)
    assert result.co_cham is True


def test_nguong_cham_khong_voi_toi_khi_vai_hep():
    """Cùng khoảng cách 100 px nhưng vai chỉ 60 px → ngưỡng 60 px: không chạm."""
    detector = _CountingDetector(boxes=[(200.0, 100.0, 260.0, 300.0)])
    signal = _signal(
        detector,
        detect_every_n_frames=1,
        box_ttl_s=10.0,
        hold_s=0.0,
        shoulder_ratio=1.0,
    )
    kp = _than((0.0, 0.0, 0.9), (60.0, 0.0, 0.9), tay=(360.0, 300.0, 0.9))

    result = signal.observe(_FRAME, kp, now=0.0)

    assert result is not None
    assert result.co_cham is False


def test_vai_khong_doc_duoc_thi_khong_noi_nguong():
    """Thiếu vai = không có mốc co giãn → chỉ còn ``touching_slack_px``.

    Thiếu dữ liệu phải làm ngưỡng **chặt lại**, không được nới ra: đó là
    hướng chống báo động giả.
    """
    detector = _CountingDetector(boxes=[(200.0, 100.0, 260.0, 300.0)])
    signal = _signal(
        detector,
        detect_every_n_frames=1,
        box_ttl_s=10.0,
        hold_s=0.0,
        shoulder_ratio=1.0,
        touching_slack_px=0,
    )
    kp = _than((0.0, 0.0, 0.1), (160.0, 0.0, 0.1), tay=(360.0, 300.0, 0.9))

    result = signal.observe(_FRAME, kp, now=0.0)

    assert result is not None
    assert result.co_cham is False


def test_slack_px_van_cong_them_vao_nguong_vai():
    detector = _CountingDetector(boxes=[(200.0, 100.0, 260.0, 300.0)])
    signal = _signal(
        detector,
        detect_every_n_frames=1,
        box_ttl_s=10.0,
        hold_s=0.0,
        shoulder_ratio=0.0,
        touching_slack_px=150,
    )
    kp = _than((0.0, 0.0, 0.9), (160.0, 0.0, 0.9), tay=(410.0, 300.0, 0.9))

    result = signal.observe(_FRAME, kp, now=0.0)

    assert result is not None
    assert result.co_cham is True


# --------------------------------------------------------------------------
# Lọc hộp phủ vùng đầu trước khi lưu
# --------------------------------------------------------------------------


def test_hop_phu_dau_bi_bo_truoc_khi_xet():
    """Hộp giả "gọng kính" bị loại; coi như khung đó không có điện thoại."""
    detector = _CountingDetector(boxes=[(600.0, 240.0, 700.0, 410.0)])
    signal = _signal(detector, detect_every_n_frames=1, box_ttl_s=10.0)
    kp = _than((500.0, 400.0, 0.9), (660.0, 400.0, 0.9))
    kp[0] = (640.0, 250.0, 0.9)

    assert signal.observe(_FRAME, kp, now=0.0) is None


def test_tat_head_filter_thi_hop_phu_dau_duoc_giu():
    """``head_filter: false`` thì hộp phủ đầu **không** bị bộ lọc đầu bỏ.

    Tắt cả ``phone_like_filter`` nữa để cô lập đúng bộ lọc đang xét: hộp này
    (tâm cao hơn vai 75 px) cũng vi phạm vế đường vai của bộ lọc vị trí, nên
    nếu để bộ lọc kia bật, test sẽ đo nhầm cái nó cần đo.
    """
    detector = _CountingDetector(boxes=[(600.0, 240.0, 700.0, 410.0)])
    signal = _signal(
        detector,
        detect_every_n_frames=1,
        box_ttl_s=10.0,
        head_filter=False,
        phone_like_filter=False,
    )
    kp = _than((500.0, 400.0, 0.9), (660.0, 400.0, 0.9))
    kp[0] = (640.0, 250.0, 0.9)

    assert signal.observe(_FRAME, kp, now=0.0) is not None


# --------------------------------------------------------------------------
# Khoan dung khung chạm hụt
# --------------------------------------------------------------------------


def _hop_va_tay():
    """Keypoint có cổ tay nằm trong hộp mặc định của ``_CountingDetector``.

    Vai đặt **ngay trên** hộp (y=180, tâm hộp y=200) để hộp đi qua được bộ
    lọc vị trí: tâm thấp hơn đường vai 20 px và cạnh dài 200 px = 1,25 lần
    bề rộng vai 160 px. Nếu để vai ở y=400 như các test ngưỡng "chạm", hộp
    sẽ nằm cao hơn vai 200 px — đúng hình dạng của hộp gọng kính giả, và bộ
    lọc sẽ loại nó trước khi test này kịp kiểm tra chuỗi chạm.
    """
    return _than((500.0, 180.0, 0.9), (660.0, 180.0, 0.9))


def test_miss_tolerance_0_dut_ngay():
    detector = _CountingDetector()
    signal = _signal(detector, detect_every_n_frames=1, box_ttl_s=10.0, hold_s=2.0)
    signal.observe(_FRAME, _hop_va_tay(), now=0.0)
    signal.observe(_FRAME, _hop_va_tay(), now=2.0)
    assert signal.held_s == pytest.approx(2.0)

    signal.observe(_FRAME, _keypoints(tay=(600.0, 450.0, 0.9)), now=2.2)
    assert signal.held_s == pytest.approx(0.0)


def test_miss_tolerance_giu_chuoi_qua_khung_hut():
    """4 khung hụt liên tiếp vẫn giữ chuỗi; khung thứ 5 mới đứt.

    Ở 5,2 FPS trên camera thật hộp detect chỉ sống ~1/3 số khung, nên đứt
    ngay khiến ``hold_s: 2.0`` không bao giờ đạt.
    """
    detector = _CountingDetector()
    signal = _signal(
        detector,
        detect_every_n_frames=1,
        box_ttl_s=10.0,
        hold_s=2.0,
        miss_tolerance_frames=4,
    )
    signal.observe(_FRAME, _hop_va_tay(), now=0.0)
    assert signal.held_s == pytest.approx(0.0)

    xa = _keypoints(tay=(600.0, 450.0, 0.9))
    for index in range(4):
        signal.observe(_FRAME, xa, now=0.2 * (index + 1))
        assert signal.held_s == pytest.approx(0.2 * (index + 1))

    signal.observe(_FRAME, xa, now=1.0)
    assert signal.held_s == pytest.approx(0.0)


def test_khong_co_hop_nao_thi_van_held_bang_0():
    """Không hộp từ đầu → không có chuỗi nào để giữ, ``held_s`` phải là 0."""
    detector = _CountingDetector(boxes=[])
    signal = _signal(
        detector,
        detect_every_n_frames=1,
        box_ttl_s=10.0,
        hold_s=2.0,
        miss_tolerance_frames=3,
    )
    assert signal.observe(_FRAME, _hop_va_tay(), now=0.0) is None
    assert signal.held_s == pytest.approx(0.0)


def test_hop_het_han_khong_dat_lai_chuoi_ngay():
    """Hộp hết TTL = khung hụt, không phải "đứt chuỗi tức thì"."""
    detector = _CountingDetector()
    signal = _signal(
        detector,
        detect_every_n_frames=100,
        box_ttl_s=0.5,
        hold_s=2.0,
        miss_tolerance_frames=3,
    )
    signal.observe(_FRAME, _hop_va_tay(), now=100.0)
    # 100,6: hộp đã hết hạn (0,6 > 0,5) và nhịp detect chưa tới.
    assert signal.observe(_FRAME, _hop_va_tay(), now=100.6) is None
    assert signal.held_s == pytest.approx(0.6)


def test_khung_cham_lai_lam_moi_chuoi_khoan_dung():
    detector = _CountingDetector()
    signal = _signal(
        detector,
        detect_every_n_frames=1,
        box_ttl_s=10.0,
        hold_s=2.0,
        miss_tolerance_frames=2,
    )
    signal.observe(_FRAME, _hop_va_tay(), now=0.0)
    xa = _keypoints(tay=(600.0, 450.0, 0.9))
    signal.observe(_FRAME, xa, now=0.2)
    signal.observe(_FRAME, xa, now=0.4)
    signal.observe(_FRAME, _hop_va_tay(), now=0.6)  # chạm lại, đếm hụt về 0
    assert signal.held_s == pytest.approx(0.6)

    signal.observe(_FRAME, xa, now=0.8)
    signal.observe(_FRAME, xa, now=1.0)
    assert signal.held_s == pytest.approx(1.0), "chưa quá khoan dung 2 khung"
    signal.observe(_FRAME, xa, now=1.2)
    assert signal.held_s == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Khóa cấu hình mới
# --------------------------------------------------------------------------


def test_phone_config_nap_cac_khoa_moi(tmp_path):
    path = _config_file(
        tmp_path,
        """
phone:
  conf_threshold: 0.07
  wrist_conf_min: 0.3
  shoulder_ratio: 0.95
  head_filter: false
  phone_like_filter: false
  min_size_ratio: 0.55
  max_above_shoulder_px: 25
  oversize_ratio: 2.5
  miss_tolerance_frames: 5
""",
    )

    config = load_config(path)

    assert config.phone.conf_threshold == pytest.approx(0.07)
    assert config.phone.wrist_conf_min == pytest.approx(0.3)
    assert config.phone.shoulder_ratio == pytest.approx(0.95)
    assert config.phone.head_filter is False
    assert config.phone.phone_like_filter is False
    assert config.phone.min_size_ratio == pytest.approx(0.55)
    assert config.phone.max_above_shoulder_px == pytest.approx(25.0)
    assert config.phone.oversize_ratio == pytest.approx(2.5)
    assert config.phone.miss_tolerance_frames == 5


def test_phone_config_mac_dinh_cac_khoa_moi(tmp_path):
    config = load_config(_config_file(tmp_path, "camera:\n  source: usb:0\n"))
    assert config.phone.conf_threshold == pytest.approx(0.06)
    assert config.phone.wrist_conf_min == pytest.approx(0.25)
    assert config.phone.shoulder_ratio == pytest.approx(1.0)
    assert config.phone.head_filter is True
    assert config.phone.phone_like_filter is True
    assert config.phone.min_size_ratio == pytest.approx(0.45)
    assert config.phone.max_above_shoulder_px == pytest.approx(10.0)
    assert config.phone.oversize_ratio == pytest.approx(2.25)
    assert config.phone.miss_tolerance_frames == 0


@pytest.mark.parametrize(
    "body, key",
    [
        ("phone:\n  wrist_conf_min: 0\n", "phone.wrist_conf_min"),
        ("phone:\n  wrist_conf_min: 2\n", "phone.wrist_conf_min"),
        ("phone:\n  shoulder_ratio: -0.5\n", "phone.shoulder_ratio"),
        ("phone:\n  head_filter: co\n", "phone.head_filter"),
        ("phone:\n  phone_like_filter: co\n", "phone.phone_like_filter"),
        ("phone:\n  min_size_ratio: -0.2\n", "phone.min_size_ratio"),
        (
            "phone:\n  max_above_shoulder_px: -5\n",
            "phone.max_above_shoulder_px",
        ),
        ("phone:\n  oversize_ratio: -0.5\n", "phone.oversize_ratio"),
        (
            "phone:\n  miss_tolerance_frames: -1\n",
            "phone.miss_tolerance_frames",
        ),
    ],
)
def test_phone_config_khoa_moi_sai_ten_key(tmp_path, body, key):
    with pytest.raises(ConfigError) as excinfo:
        load_config(_config_file(tmp_path, body))
    assert key in str(excinfo.value)


# --------------------------------------------------------------------------
# Bộ lọc vị trí hộp — chạy trong PhoneSignal
# --------------------------------------------------------------------------

#: Hộp gọng kính thật (``phone_hit_3.jpg``, conf 0,699) trong hệ khung 640x480
#: của test: tâm cao hơn đường vai một khoảng lớn và cạnh dài 151,7 px.
HOP_GONG_KINH_TEST = (282.0, 60.0, 321.7, 211.7)


def _vai_gong_kinh():
    """Vai của khung ``phone_hit_3`` (bề rộng thật 264,6 px), hạ vào khung test."""
    return _than((262.7, 343.6, 0.9), (2.1, 298.1, 0.9))


def test_hop_gong_kinh_bi_loai_truoc_khi_xet_cham():
    """Hộp conf cao trên gọng kính không được sinh ra kết quả "đang dùng".

    Đây là lỗi người dùng báo: web hiện "đang dùng điện thoại" khi không có
    điện thoại. Hộp này (conf 0,699) **cao hơn** điện thoại thật, nên chỉ
    bộ lọc vị trí mới chặn được.
    """
    detector = _CountingDetector(boxes=[HOP_GONG_KINH_TEST])
    signal = _signal(detector, detect_every_n_frames=1, box_ttl_s=10.0)

    assert signal.observe(_FRAME, _vai_gong_kinh(), now=0.0) is None


def test_hop_dien_thoai_that_van_sinh_ket_qua():
    """Hộp thật (``rt_ph_00``: tâm ngang đường vai, conf 0,347) vẫn chạy.

    Bộ lọc không được biến thành "tắt tính năng": đúng hộp thật thì
    ``observe`` phải trả kết quả và báo chạm.
    """
    hop_that = (318.3, 303.1, 439.0, 374.3)
    kp = _than((289.4, 339.6, 0.9), (118.0, 337.3, 0.9), tay=(370.0, 340.0, 0.9))
    detector = _CountingDetector(boxes=[hop_that])
    signal = _signal(detector, detect_every_n_frames=1, box_ttl_s=10.0, hold_s=0.0)

    result = signal.observe(_FRAME, kp, now=0.0)

    assert result is not None
    assert result.co_cham is True


# --------------------------------------------------------------------------
# Điện thoại giơ lên che mặt — tư thế dùng thật bị bỏ oan
# --------------------------------------------------------------------------
# Đo trên ``frame.jpg`` (704x576): người giơ điện thoại dọc che mặt. Pose cho
# mũi (378, 222), vai (415, 383) / (304.2, 366.6) — bề rộng vai chỉ 112 px vì
# người quay chéo. Hộp thật ``(281, 1, 421, 318)`` có cạnh dài 2,83 lần bề
# rộng vai và tâm cao hơn đường vai 215 px, nên **cả hai** bộ lọc đều bỏ nó.

HOP_GIO_CHE_MAT = (281.0, 1.0, 421.0, 318.0)


def _kp_gio_che_mat():
    """Mũi và hai vai đúng như pose trả trên ``frame.jpg``."""
    kp = _keypoints(tay=(310.0, 250.0, 0.9))
    kp[0] = (378.0, 222.0, 0.9)
    kp[5] = (415.0, 383.0, 0.9)
    kp[6] = (304.2, 366.6, 0.9)
    return kp


def test_dien_thoai_gio_che_mat_khong_bi_loc_bo():
    """Hộp thật giơ che mặt phải tới được bước xét "chạm".

    Trước khi có van ``oversize_ratio``, đúng khung này trả ``None`` — tính
    năng im lặng ở tư thế dùng điện thoại rõ ràng nhất. Cổ tay đặt trong hộp
    nên sau khi lọt lọc phải báo chạm.
    """
    detector = _CountingDetector(boxes=[HOP_GIO_CHE_MAT])
    signal = _signal(detector, detect_every_n_frames=1, box_ttl_s=10.0, hold_s=0.0)

    result = signal.observe(_FRAME, _kp_gio_che_mat(), now=0.0)

    assert result is not None
    assert result.co_cham is True


def test_van_gio_che_mat_doc_tu_cau_hinh():
    """``oversize_ratio`` là khóa cấu hình, không phải hằng số trong code."""
    detector = _CountingDetector(boxes=[HOP_GIO_CHE_MAT])
    signal = _signal(
        detector,
        detect_every_n_frames=1,
        box_ttl_s=10.0,
        hold_s=0.0,
        oversize_ratio=0.0,  # tắt van → quay lại hành vi bỏ hộp
    )

    assert signal.observe(_FRAME, _kp_gio_che_mat(), now=0.0) is None


def test_tat_bo_loc_vi_tri_thi_hop_gong_kinh_duoc_giu():
    """``phone_like_filter: false`` tắt đúng bộ lọc đó (công tắc có tác dụng)."""
    detector = _CountingDetector(boxes=[HOP_GONG_KINH_TEST])
    signal = _signal(
        detector,
        detect_every_n_frames=1,
        box_ttl_s=10.0,
        phone_like_filter=False,
    )

    assert signal.observe(_FRAME, _vai_gong_kinh(), now=0.0) is not None


def test_nguong_kich_thuoc_lay_tu_cau_hinh():
    """Đổi ``min_size_ratio`` đổi hành vi: nới lên 5,0 thì hộp thật bị loại.

    Chứng minh ``PhoneSignal`` đọc ngưỡng từ ``config.phone`` chứ không dùng
    hằng số trong ``phone.py``.
    """
    hop_that = (318.3, 303.1, 439.0, 374.3)
    kp = _than((289.4, 339.6, 0.9), (118.0, 337.3, 0.9), tay=(370.0, 340.0, 0.9))
    detector = _CountingDetector(boxes=[hop_that])
    signal = _signal(
        detector,
        detect_every_n_frames=1,
        box_ttl_s=10.0,
        min_size_ratio=5.0,
    )

    assert signal.observe(_FRAME, kp, now=0.0) is None
