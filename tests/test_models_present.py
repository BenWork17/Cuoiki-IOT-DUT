"""Chống tái phát: hai mô hình khuôn mặt phải MỞ ĐƯỢC bằng chính OpenCV.

Bối cảnh: nhánh ``r3-faces-wire`` cấu hình ``face.detector: yunet.onnx`` và
``face.recognizer: sface.onnx``, code ``faces.py`` đã xong và test xanh — nhưng
cả hai tệp không tồn tại trên bất kỳ máy nào. Tính năng không chạy được dù cây
test toàn màu xanh, vì test cũ dùng mô hình giả.

Tệp mô hình KHÔNG được commit (37 MB, xem ``docs/MODELS.md``). Vì vậy bài này
**bỏ qua** khi máy thiếu tệp — theo đúng pattern của
``tests/test_benchmark.py`` cho ``yolo11n-pose.pt``. Khi tệp CÓ MẶT, bài này
khẳng định OpenCV thật sự mở được chúng; một tệp rác đặt đúng tên sẽ làm bài
này ĐỎ chứ không bị bỏ qua.
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

# Đường dẫn tương đối trong config của ``r3-faces-wire`` là gốc repo.
_YUNET = _REPO_ROOT / "yunet.onnx"
_SFACE = _REPO_ROOT / "sface.onnx"


@pytest.mark.skipif(
    not _YUNET.is_file(),
    reason="Máy không có yunet.onnx; bỏ qua bài mở mô hình phát hiện khuôn mặt.",
)
def test_yunet_mo_duoc_va_chay_tren_khung_tong_hop() -> None:
    """YuNet mở được và chạy được detect trên khung đen tổng hợp."""
    import cv2

    detector = cv2.FaceDetectorYN_create(str(_YUNET), "", (320, 320), 0.9, 0.3, 5000)
    detector.setInputSize((640, 480))

    retval, faces = detector.detect(np.zeros((480, 640, 3), np.uint8))

    # ĐO ĐƯỢC trên cv2 4.13: retval là cờ thành công (luôn 1), KHÔNG phải số
    # khuôn mặt. Không có mặt nào thì faces là None.
    assert int(retval) == 1
    assert faces is None or len(faces) == 0


@pytest.mark.skipif(
    not _SFACE.is_file(),
    reason="Máy không có sface.onnx; bỏ qua bài mở mô hình đặc trưng khuôn mặt.",
)
def test_sface_mo_duoc_va_tra_vector_128_chieu() -> None:
    """SFace mở được và trả vector 128 chiều (spec §4.2)."""
    import cv2

    recognizer = cv2.FaceRecognizerSF_create(str(_SFACE), "")

    # Không dùng ảnh người thật: một tensor 112x112 tổng hợp là đủ để đọc
    # số chiều. Giá trị không mang ý nghĩa nhận dạng nào.
    feature = recognizer.feature(np.zeros((112, 112, 3), np.uint8))

    assert np.asarray(feature).reshape(-1).shape[0] == 128


@pytest.mark.skipif(
    not (_YUNET.is_file() and _SFACE.is_file()),
    reason="Máy thiếu yunet.onnx hoặc sface.onnx; bỏ qua bài ghép cặp mô hình.",
)
def test_hai_mo_hinh_dung_chung_duoc_mot_luot() -> None:
    """Cả hai mô hình cùng mở trong một tiến trình, không xung đột."""
    import cv2

    detector = cv2.FaceDetectorYN_create(str(_YUNET), "", (320, 320), 0.9, 0.3, 5000)
    recognizer = cv2.FaceRecognizerSF_create(str(_SFACE), "")

    assert detector is not None
    assert recognizer is not None
