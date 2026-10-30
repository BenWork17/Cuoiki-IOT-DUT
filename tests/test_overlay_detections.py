"""Hộp điện thoại và hộp khuôn mặt phải **thật sự** được vẽ lên khung.

Bối cảnh: người dùng nhớ có lần thấy hộp điện thoại và khung mặt trên hình
camera. Ảnh đó là sản phẩm của một script đo tay, không phải của chương
trình — ``overlay.py`` khi đó chỉ có ``draw_pose``. Ba tầng đã được thêm:

1. ``overlay.draw_detections`` vẽ hộp.
2. ``PhoneSignal.boxes(now)`` và ``PeopleService.latest_face_box()`` công bố
   toạ độ (trước đây ``_boxes`` là trường riêng, còn ``processor`` chỉ trả
   embedding nên không lớp hiển thị nào biết hộp mặt ở đâu).
3. Vòng lặp vẽ **sau** khi cả hai lần detect đã chạy và **trước**
   ``imencode``, nên cửa sổ xem trước và dashboard web thấy cùng một hình.

Test ở đây khoá đúng những điểm đó bằng đếm pixel, không bằng cách đọc code.
Đột biến để kiểm chứng: xoá lời gọi ``cv2.rectangle`` của hộp điện thoại
trong ``draw_detections`` → :func:`test_ve_hop_dien_thoai` đỏ; tương tự cho
hộp mặt với :func:`test_ve_hop_khuon_mat`; đổi ``copy=True`` thành ``False``
trong vòng lặp → :func:`test_vong_lap_khong_ve_len_khung_goc` đỏ.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.overlay import (  # noqa: E402
    FACE_BOX_COLOR,
    PHONE_BOX_COLOR,
    draw_detections,
)


def _blank(width: int = 320, height: int = 240) -> np.ndarray:
    return np.zeros((height, width, 3), dtype=np.uint8)


def _count_color(frame: np.ndarray, color) -> int:
    """Số pixel đúng bằng ``color`` trên cả ba kênh."""
    mask = np.all(frame == np.array(color, dtype=np.uint8), axis=2)
    return int(mask.sum())


def test_ve_hop_dien_thoai():
    """Hộp điện thoại để lại pixel màu :data:`PHONE_BOX_COLOR`."""
    frame = _blank()

    drawn = draw_detections(frame, phone_boxes=[(40.0, 40.0, 120.0, 100.0)])

    assert _count_color(drawn, PHONE_BOX_COLOR) > 0
    assert _count_color(drawn, FACE_BOX_COLOR) == 0


def test_ve_hop_khuon_mat():
    """Hộp khuôn mặt ``(x, y, w, h)`` để lại pixel màu :data:`FACE_BOX_COLOR`."""
    frame = _blank()

    drawn = draw_detections(frame, face_box=(30.0, 20.0, 60.0, 60.0))

    assert _count_color(drawn, FACE_BOX_COLOR) > 0
    assert _count_color(drawn, PHONE_BOX_COLOR) == 0


def test_hai_hop_ve_cung_luc():
    """Có cả hai hộp thì cả hai màu đều xuất hiện."""
    frame = _blank()

    drawn = draw_detections(
        frame, phone_boxes=[(10.0, 10.0, 80.0, 60.0)], face_box=(100.0, 20.0, 50.0, 50.0)
    )

    assert _count_color(drawn, PHONE_BOX_COLOR) > 0
    assert _count_color(drawn, FACE_BOX_COLOR) > 0


def test_khong_hop_thi_khung_khong_doi():
    """Không có hộp nào → không pixel nào bị vẽ."""
    frame = _blank()

    drawn = draw_detections(frame)

    assert np.array_equal(frame, drawn)


def test_hop_nan_va_suy_bien_bi_bo():
    """Toạ độ NaN/inf hoặc hộp 0 px bị bỏ, không vẽ rác khắp khung."""
    frame = _blank()

    drawn = draw_detections(
        frame,
        phone_boxes=[
            (float("nan"), 10.0, 50.0, 50.0),
            (float("inf"), 10.0, 50.0, 50.0),
            (40.0, 40.0, 40.0, 40.0),  # rộng/cao 0 sau khi kẹp
            (10.0, 10.0, 20.0, 20.0),  # hộp hợp lệ duy nhất
        ],
        face_box=(10.0, 10.0, float("nan"), 20.0),
    )

    assert _count_color(drawn, FACE_BOX_COLOR) == 0
    # Hộp hợp lệ vẫn được vẽ — hàm bỏ hộp hỏng chứ không bỏ cả khung.
    assert _count_color(drawn, PHONE_BOX_COLOR) > 0


def test_copy_true_khong_sua_khung_goc():
    """``copy=True`` để khung truyền vào nguyên vẹn."""
    frame = _blank()
    before = frame.copy()

    drawn = draw_detections(
        frame, phone_boxes=[(10.0, 10.0, 60.0, 60.0)], copy=True
    )

    assert np.array_equal(frame, before)
    assert _count_color(drawn, PHONE_BOX_COLOR) > 0


def test_hop_ngoai_khung_duoc_kep():
    """Hộp tràn ra ngoài vẫn vẽ được, không ném."""
    frame = _blank()

    drawn = draw_detections(
        frame, phone_boxes=[(-500.0, -500.0, 5000.0, 5000.0)]
    )

    assert drawn.shape == frame.shape
    assert _count_color(drawn, PHONE_BOX_COLOR) > 0
