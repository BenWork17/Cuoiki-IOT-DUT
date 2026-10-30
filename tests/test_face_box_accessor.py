"""Hai hàm công bố toạ độ cho lớp vẽ, chạy trên **đối tượng thật**.

``tests/test_wire_detection_overlay.py`` chạy vòng lặp thật nhưng thay
``PhoneSignal``/``PeopleService`` bằng bản giả, nên phần thân của
``PhoneSignal.boxes`` và ``PeopleService.latest_face_box`` không được chạm.
Hai hàm đó là chỗ dễ sai nhất: trả hộp **đã hết hạn** thì hình vẽ một khung
chữ nhật đứng yên ở chỗ không còn gì, còn luôn trả ``None`` thì không hộp nào
hiện ra dù dây nối đúng.

Đột biến để kiểm chứng: bỏ ``_boxes_expired`` trong ``PhoneSignal.boxes`` →
:func:`test_phone_signal_boxes_het_han_tra_rong` đỏ; đổi
``age > FACE_BOX_MAX_AGE_S`` thành ``>=`` hoặc xoá cả điều kiện →
:func:`test_hop_mat_cu_thi_bien_mat` đỏ.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.people_service import (  # noqa: E402
    FACE_BOX_MAX_AGE_S,
    PeopleService,
)
from posture_monitor.phone_detector import PhoneSignal  # noqa: E402


class _PhoneCfg(SimpleNamespace):
    """``config.phone`` tối thiểu mà ``PhoneSignal`` đọc trong constructor."""

    enabled = True
    detect_every_n_frames = 2
    box_ttl_s = 0.5
    hold_s = 2.0
    touching_slack_px = 0.0
    shoulder_ratio = 1.0
    head_filter = False
    phone_like_filter = False
    min_size_ratio = 0.45
    max_above_shoulder_px = 10.0
    oversize_ratio = 2.25
    miss_tolerance_frames = 4
    wrist_conf_min = 0.25
    conf_threshold = 0.06
    imgsz = 320
    detect_weights = ""
    detect_model = "yolo11n"


class _Detector:
    """Trả đúng một hộp; ``PhoneSignal`` lọc theo cấu hình rồi tự lưu."""

    def __init__(self, box) -> None:
        self._box = box
        self.calls = 0

    def detect(self, _frame):
        self.calls += 1
        return [self._box]


def _signal(box=(10.0, 10.0, 60.0, 60.0)) -> PhoneSignal:
    config = SimpleNamespace(phone=_PhoneCfg(), model=SimpleNamespace(format="ncnn"))
    return PhoneSignal(config, detector=_Detector(box))


_FRAME = np.zeros((120, 160, 3), dtype=np.uint8)
#: Keypoint đủ tin cậy cho cổ tay (cổ tay 9/10) để ``observe`` không thoát sớm.
_KEYPOINTS = np.zeros((17, 3), dtype=np.float64)
_KEYPOINTS[:, 0] = 80.0
_KEYPOINTS[:, 1] = 60.0
_KEYPOINTS[:, 2] = 0.9


def test_phone_signal_boxes_con_han_tra_hop():
    """Ngay sau lượt detect đầu, ``boxes(now)`` trả đúng hộp vừa tìm được."""
    signal = _signal()

    signal.observe(_FRAME, _KEYPOINTS, 0.0)

    assert signal.boxes(0.0) == ((10.0, 10.0, 60.0, 60.0),)


def test_phone_signal_boxes_het_han_tra_rong():
    """Quá ``box_ttl_s`` thì không trả hộp nữa — không vẽ hộp ma."""
    signal = _signal()
    signal.observe(_FRAME, _KEYPOINTS, 0.0)

    assert signal.boxes(0.0) != ()
    assert signal.boxes(_PhoneCfg.box_ttl_s + 0.01) == ()


def test_phone_signal_boxes_khong_cham_vao_trang_thai():
    """Gọi ``boxes`` không được làm thay đổi chuỗi chạm (``held_s``/``in_use``)."""
    signal = _signal()
    signal.observe(_FRAME, _KEYPOINTS, 0.0)
    before = (signal.held_s, signal.in_use)

    signal.boxes(0.0)

    assert (signal.held_s, signal.in_use) == before


class _Store:
    def pairs(self):
        return []


class _Recognizer:
    def embed_largest(self, _frame):
        return None


def test_hop_mat_moi_duoc_tra_ve():
    """``note_face_box`` rồi ``latest_face_box`` trả đúng hộp ``(x, y, w, h)``."""
    clock = SimpleNamespace(now=100.0)
    service = PeopleService(
        _Store(), _Recognizer(), clock=lambda: clock.now, threshold=None
    )
    try:
        service.note_face_box((12.0, 34.0, 56.0, 78.0))
        assert service.latest_face_box() == (12.0, 34.0, 56.0, 78.0)
    finally:
        service.close()


def test_hop_mat_cu_thi_bien_mat():
    """Quá :data:`FACE_BOX_MAX_AGE_S` thì trả ``None`` (luồng nhận diện đã chết)."""
    clock = SimpleNamespace(now=0.0)
    service = PeopleService(
        _Store(), _Recognizer(), clock=lambda: clock.now, threshold=None
    )
    try:
        service.note_face_box((12.0, 34.0, 56.0, 78.0))
        clock.now = FACE_BOX_MAX_AGE_S + 0.1
        assert service.latest_face_box() is None
    finally:
        service.close()


def test_hop_mat_hong_bi_bo_qua_im_lang():
    """Hộp sai kiểu/NaN không được ném: hàm chạy trong luồng nhận diện."""
    clock = SimpleNamespace(now=0.0)
    service = PeopleService(
        _Store(), _Recognizer(), clock=lambda: clock.now, threshold=None
    )
    try:
        for bad in (None, (), (1.0, 2.0), (1.0, float("nan"), 3.0, 4.0), "abcd"):
            service.note_face_box(bad)
        assert service.latest_face_box() is None
    finally:
        service.close()


def test_hop_mat_bi_xoa_khi_luot_do_ket_luan_khong_co_mat():
    """Lượt nhận diện kết luận "không thấy mặt" thì xoá hộp cũ ngay.

    Không xoá thì hộp của lượt trước nằm lại tới ``FACE_BOX_MAX_AGE_S`` giây,
    chỉ vào một chỗ đã trống — người xem tưởng mô hình vẫn đang thấy mặt.
    """
    clock = SimpleNamespace(now=0.0)
    service = PeopleService(
        _Store(), _Recognizer(), clock=lambda: clock.now, threshold=None
    )
    try:
        service.note_face_box((12.0, 34.0, 56.0, 78.0))
        assert service.latest_face_box() is not None

        service.process_frame(_FRAME, now=0.0)  # recognizer trả None

        assert service.latest_face_box() is None
    finally:
        service.close()
