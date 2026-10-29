"""Kiểm thử ``phone.py`` — phát hiện "đang dùng điện thoại".

Test chạy trên PC, không cần mạng, không cần trọng số: toàn bộ dữ liệu là toạ
độ dựng tay. Đây là thứ duy nhất có thể khẳng định ở đây — độ chính xác thật
cần ảnh có người cầm điện thoại, chưa có trong repo.

Hình dựng chung: khung 1280×720, cổ tay trái (index 9) và phải (index 10) đặt
ở ``(400, 300)`` mặc định; hộp điện thoại 100×200 đặt ở gốc ``(390, 290)`` sao
cho cổ tay nằm gọn bên trong.
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

from posture_monitor.phone import (  # noqa: E402
    PHONE_CLASS_ID,
    WRIST_KEYPOINTS,
    hand_phone_contact,
    khoang_cach_diem_hop,
)

# Hộp điện thoại mặc định: 100 rộng × 200 cao, chứa điểm (400, 300).
HOP = (390.0, 290.0, 490.0, 490.0)
TAY_TRONG_HOP = (400.0, 300.0)


def _keypoints(
    tay_trai: tuple[float, float, float | None] | None = None,
    tay_phai: tuple[float, float, float | None] | None = None,
) -> np.ndarray:
    """Dựng mảng ``(17, 3)``; cổ tay không truyền thì conf 0 (bị bỏ qua)."""
    kp = np.zeros((17, 3), dtype=np.float32)
    # Điền vài keypoint khác để chắc module không đọc nhầm index.
    kp[:, 0] = 640.0
    kp[:, 1] = 360.0
    kp[:, 2] = 0.9
    if tay_trai is None:
        kp[9] = (0.0, 0.0, 0.0)
    else:
        kp[9] = tay_trai
    if tay_phai is None:
        kp[10] = (0.0, 0.0, 0.0)
    else:
        kp[10] = tay_phai
    return kp


def _goi(kp, hop=None, *, proximity_px=10.0, min_kp_conf=0.3):
    hop = [HOP] if hop is None else hop
    return hand_phone_contact(
        kp, hop, proximity_px=proximity_px, min_kp_conf=min_kp_conf
    )


# --------------------------------------------------------------------------
# Hằng số hợp đồng với model detect thứ hai
# --------------------------------------------------------------------------

def test_phone_class_id_la_67_va_co_tay_la_9_10():
    """Index lớp và index keypoint là hợp đồng với COCO, không được trôi."""
    assert PHONE_CLASS_ID == 67
    assert WRIST_KEYPOINTS == (9, 10)


# --------------------------------------------------------------------------
# Hình học cơ bản
# --------------------------------------------------------------------------

def test_khoang_cach_diem_trong_hop_bang_0():
    assert khoang_cach_diem_hop(*TAY_TRONG_HOP, HOP) == 0.0


def test_khoang_cach_diem_ngoai_hop_la_canh_gan_nhat():
    # Điểm cách mép phải 30 px, ngang hàng giữa hộp.
    assert khoang_cach_diem_hop(520.0, 300.0, HOP) == pytest.approx(30.0)
    # Điểm chéo góc dưới-phải: dx=10, dy=10.
    assert khoang_cach_diem_hop(500.0, 500.0, HOP) == pytest.approx(
        10.0 * np.sqrt(2.0)
    )


def test_khoang_cach_theo_hop_chu_khong_theo_tam():
    """Điểm sát mép nhưng xa tâm phải cho khoảng cách 0, không phải ~bán kính."""
    sat_mep = (391.0, 291.0)
    assert khoang_cach_diem_hop(*sat_mep, HOP) == 0.0
    assert hand_phone_contact(
        _keypoints(tay_trai=(*sat_mep, 0.9)),
        [HOP],
        proximity_px=1.0,
        min_kp_conf=0.3,
    ).co_cham


# --------------------------------------------------------------------------
# Các ca bắt buộc theo brief
# --------------------------------------------------------------------------

def test_co_tay_nam_trong_hop_thi_cham_va_khoang_cach_0():
    kq = _goi(_keypoints(tay_trai=(*TAY_TRONG_HOP, 0.9)))

    assert kq.co_cham is True
    assert kq.khoang_cach_nho_nhat == 0.0
    assert kq.hop_le is True
    assert kq.hop_gan_nhat == 0


def test_co_tay_ngoai_hop_nhung_gan_thi_dung_nguong():
    """Ngưỡng là tham số: cùng dữ liệu, hai ngưỡng khác nhau, hai kết luận."""
    kp = _keypoints(tay_trai=(495.0, 300.0, 0.9))  # cách mép 5 px

    sat_nguong = _goi(kp, proximity_px=5.0)
    duoi_nguong = _goi(kp, proximity_px=4.9)

    assert sat_nguong.khoang_cach_nho_nhat == pytest.approx(5.0)
    assert sat_nguong.co_cham is True  # <= là dính
    assert duoi_nguong.co_cham is False


def test_co_tay_o_xa_thi_khong_cham():
    kp = _keypoints(tay_trai=(800.0, 600.0, 0.9))
    kq = _goi(kp, proximity_px=10.0)

    assert kq.co_cham is False
    assert kq.khoang_cach_nho_nhat == pytest.approx(
        np.hypot(800.0 - 490.0, 600.0 - 490.0)
    )


def test_nguong_0_chi_dung_khi_diem_nam_trong_hop():
    """Không có nới lỏng ngầm nào: ngưỡng 0 nghĩa là phải nằm hẳn trong hộp."""
    trong = _goi(_keypoints(tay_trai=(*TAY_TRONG_HOP, 0.9)), proximity_px=0.0)
    ngoai = _goi(_keypoints(tay_trai=(494.0, 300.0, 0.9)), proximity_px=0.0)

    assert trong.co_cham is True
    assert ngoai.co_cham is False


def test_khong_co_dien_thoai_thi_khong_cham_va_khong_crash():
    kp = _keypoints(tay_trai=(*TAY_TRONG_HOP, 0.9))

    for hop_trong in ([], None):
        kq = hand_phone_contact(
            kp, hop_trong, proximity_px=10.0, min_kp_conf=0.3
        )
        assert kq.co_cham is False
        assert kq.khoang_cach_nho_nhat is None
        assert kq.ly_do


def test_co_tay_conf_thap_bi_bo_qua():
    """Tay bị che: pose vẫn trả điểm nằm trong hộp nhưng conf sụp.

    Đây là ca biên quan trọng nhất — nếu bỏ kiểm tra conf thì test này đỏ vì
    module sẽ báo "đang dùng điện thoại" trên một keypoint rác.
    """
    kp = _keypoints(tay_trai=(*TAY_TRONG_HOP, 0.1), tay_phai=(700.0, 100.0, 0.9))
    kq = _goi(kp, proximity_px=10.0, min_kp_conf=0.3)

    assert kq.co_cham is False
    # Cổ tay trái không xuất hiện trong chi tiết; chỉ tay phải được xét.
    assert [idx for idx, _ in kq.khoang_cach_theo_tay] == [10]
    assert kq.khoang_cach_nho_nhat == pytest.approx(
        np.hypot(700.0 - 490.0, 100.0 - 290.0)
    )


def test_ca_hai_co_tay_deu_conf_thap_thi_khong_co_khoang_cach():
    kp = _keypoints(tay_trai=(*TAY_TRONG_HOP, 0.0), tay_phai=(400.0, 300.0, 0.2))
    kq = _goi(kp, proximity_px=10.0, min_kp_conf=0.3)

    assert kq.co_cham is False
    assert kq.khoang_cach_nho_nhat is None
    assert kq.khoang_cach_theo_tay == ()
    assert kq.ly_do


def test_conf_bang_dung_nguong_duoc_tinh():
    """``>=`` ở conf, đối xứng với ``<=`` ở khoảng cách."""
    kp = _keypoints(tay_trai=(*TAY_TRONG_HOP, 0.3))
    kq = _goi(kp, proximity_px=10.0, min_kp_conf=0.3)

    assert kq.co_cham is True
    assert kq.khoang_cach_nho_nhat == 0.0


def test_nhieu_dien_thoai_thi_lay_hop_gan_nhat():
    xa = (1000.0, 600.0, 1100.0, 700.0)
    gan = (395.0, 295.0, 405.0, 305.0)
    kp = _keypoints(tay_trai=(*TAY_TRONG_HOP, 0.9))
    kq = _goi(kp, [xa, gan], proximity_px=1.0)

    assert kq.co_cham is True
    assert kq.khoang_cach_nho_nhat == 0.0
    assert kq.hop_gan_nhat == 1


# --------------------------------------------------------------------------
# Dữ liệu sai hình dạng: không crash, kết quả an toàn
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "kp_sai",
    [
        None,
        [],
        np.zeros((17, 2)),          # thiếu cột conf
        np.zeros((17,)),            # 1 chiều
        np.zeros(3),                # mảng phẳng
        np.zeros((2, 3)),           # quá ít keypoint (không có cổ tay)
        "khong phai mang",
        [[0.0, 0.0], [1.0]],        # list lồng lẻo
    ],
)
def test_keypoints_sai_hinh_dang_tra_an_toan(kp_sai):
    kq = hand_phone_contact(
        kp_sai, [HOP], proximity_px=10.0, min_kp_conf=0.3
    )

    assert kq.co_cham is False
    assert kq.khoang_cach_nho_nhat is None
    assert kq.ly_do


def test_hop_sai_hinh_dang_bi_bo_qua():
    kp = _keypoints(tay_trai=(*TAY_TRONG_HOP, 0.9))
    kq = _goi(kp, [(1.0, 2.0), "abc", None, (float("nan"), 0, 1, 2)])

    assert kq.co_cham is False
    assert kq.khoang_cach_nho_nhat is None
    assert kq.ly_do


def test_hop_dao_canh_duoc_chuan_hoa():
    kp = _keypoints(tay_trai=(*TAY_TRONG_HOP, 0.9))
    kq = _goi(kp, [(490.0, 490.0, 390.0, 290.0)], proximity_px=0.0)

    assert kq.co_cham is True
    assert kq.khoang_cach_nho_nhat == 0.0


def test_co_tay_nan_khong_lam_crash():
    kp = _keypoints(tay_trai=(float("nan"), float("nan"), 0.9))
    kq = _goi(kp, proximity_px=10.0)

    assert kq.co_cham is False
    assert kq.khoang_cach_nho_nhat is None


# --------------------------------------------------------------------------
# Tham số vô lý là lỗi caller, không phải lỗi dữ liệu => phải ném
# --------------------------------------------------------------------------

@pytest.mark.parametrize("proximity_px", [-1.0, float("nan"), float("inf")])
def test_proximity_vo_ly_thi_nem_valueerror(proximity_px):
    with pytest.raises(ValueError):
        hand_phone_contact(
            _keypoints(tay_trai=(*TAY_TRONG_HOP, 0.9)),
            [HOP],
            proximity_px=proximity_px,
            min_kp_conf=0.3,
        )


@pytest.mark.parametrize("min_kp_conf", [-0.1, 1.1, float("nan")])
def test_min_kp_conf_vo_ly_thi_nem_valueerror(min_kp_conf):
    with pytest.raises(ValueError):
        hand_phone_contact(
            _keypoints(tay_trai=(*TAY_TRONG_HOP, 0.9)),
            [HOP],
            proximity_px=10.0,
            min_kp_conf=min_kp_conf,
        )


def test_proximity_va_min_conf_la_bat_buoc():
    """Không có mặc định ngầm: caller phải nêu cả hai ngưỡng."""
    with pytest.raises(TypeError):
        hand_phone_contact(_keypoints(), [HOP])
