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
    is_head_like_box,
    is_plausible_phone_box,
    khoang_cach_diem_hop,
    shoulder_width_px,
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
    assert khoang_cach_diem_hop(500.0, 500.0, HOP) == pytest.approx(10.0 * np.sqrt(2.0))


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
        kq = hand_phone_contact(kp, hop_trong, proximity_px=10.0, min_kp_conf=0.3)
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
        np.zeros((17, 2)),  # thiếu cột conf
        np.zeros((17,)),  # 1 chiều
        np.zeros(3),  # mảng phẳng
        np.zeros((2, 3)),  # quá ít keypoint (không có cổ tay)
        "khong phai mang",
        [[0.0, 0.0], [1.0]],  # list lồng lẻo
    ],
)
def test_keypoints_sai_hinh_dang_tra_an_toan(kp_sai):
    kq = hand_phone_contact(kp_sai, [HOP], proximity_px=10.0, min_kp_conf=0.3)

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


# --------------------------------------------------------------------------
# Bề rộng vai — mốc co giãn cho ngưỡng "chạm"
# --------------------------------------------------------------------------


def _than_tren(vai_trai=(500.0, 400.0, 0.9), vai_phai=(660.0, 400.0, 0.9)):
    """Keypoint có hai vai đặt được; mặc định cách nhau 160 px."""
    kp = _keypoints(tay_trai=(*TAY_TRONG_HOP, 0.9))
    kp[5] = vai_trai
    kp[6] = vai_phai
    return kp


def test_be_rong_vai_la_khoang_cach_euclid_hai_vai():
    assert shoulder_width_px(_than_tren(), min_kp_conf=0.3) == pytest.approx(160.0)


def test_be_rong_vai_co_theo_huong_nghieng():
    """Vai lệch nhau theo cả x và y vẫn phải ra khoảng cách thật, không chỉ dx."""
    kp = _than_tren(vai_trai=(500.0, 400.0, 0.9), vai_phai=(500.0, 500.0, 0.9))
    assert shoulder_width_px(kp, min_kp_conf=0.3) == pytest.approx(100.0)


def test_be_rong_vai_duoi_nguong_tra_none():
    """Một vai yếu là **không có mốc**: cấm đoán, cấm lấy vai còn lại."""
    kp = _than_tren(vai_phai=(660.0, 400.0, 0.2))
    assert shoulder_width_px(kp, min_kp_conf=0.3) is None


def test_be_rong_vai_sai_hinh_dang_tra_none():
    assert shoulder_width_px(np.zeros((5, 3)), min_kp_conf=0.3) is None
    assert shoulder_width_px("khong phai mang", min_kp_conf=0.3) is None


def test_be_rong_vai_hai_diem_trung_nhau_tra_none():
    """Hai vai cùng một điểm là output rác, không phải mốc co giãn."""
    kp = _than_tren(vai_trai=(500.0, 400.0, 0.9), vai_phai=(500.0, 400.0, 0.9))
    assert shoulder_width_px(kp, min_kp_conf=0.3) is None


@pytest.mark.parametrize("min_kp_conf", [-0.1, 1.1, float("nan")])
def test_be_rong_vai_nguong_vo_ly_thi_nem(min_kp_conf):
    with pytest.raises(ValueError):
        shoulder_width_px(_than_tren(), min_kp_conf=min_kp_conf)


# --------------------------------------------------------------------------
# Lọc hộp "đeo kính" giả
# --------------------------------------------------------------------------

#: Vai ở y=400, mũi ở y=250 → khoảng cách mũi→vai 150 px.
HOP_KINH = (600.0, 240.0, 700.0, 410.0)  # cao 170 px, phủ mũi (640, 250)


def _dau():
    kp = _than_tren()
    kp[0] = (640.0, 250.0, 0.9)  # mũi
    return kp


def test_hop_phu_mui_va_cao_bang_mui_toi_vai_la_hop_dau():
    assert is_head_like_box(HOP_KINH, _dau(), min_kp_conf=0.3) is True


def test_hop_dien_thoai_that_khong_bi_coi_la_hop_dau():
    """Hộp thật nằm dưới vai, thấp hơn khoảng mũi→vai: không được lọc."""
    assert is_head_like_box(HOP, _dau(), min_kp_conf=0.3) is False


def test_hop_phu_mui_nhung_thap_thi_khong_bi_loc():
    """Hộp phủ mũi mà thấp (điện thoại giơ ngang mặt) không phải hộp kính."""
    thap = (600.0, 240.0, 700.0, 300.0)  # cao 60 < 150
    assert is_head_like_box(thap, _dau(), min_kp_conf=0.3) is False


def test_hop_cao_nhung_khong_phu_mui_khong_bi_loc():
    lech = (50.0, 100.0, 150.0, 400.0)  # cao nhưng xa mũi
    assert is_head_like_box(lech, _dau(), min_kp_conf=0.3) is False


def test_mui_duoi_nguong_thi_khong_loc_gi():
    """Pose yếu → không kết luận; thà lọt hộp giả còn hơn bỏ hộp thật."""
    kp = _dau()
    kp[0] = (640.0, 250.0, 0.1)
    assert is_head_like_box(HOP_KINH, kp, min_kp_conf=0.3) is False


def test_hop_dau_tham_so_vo_ly_thi_nem():
    with pytest.raises(ValueError):
        is_head_like_box(HOP_KINH, _dau(), min_kp_conf=1.5)
    with pytest.raises(ValueError):
        is_head_like_box(HOP_KINH, _dau(), min_kp_conf=0.3, span_ratio=-1.0)


# --------------------------------------------------------------------------
# Vị trí hộp điện thoại — sửa lỗi "báo đang dùng điện thoại" khi không có
# --------------------------------------------------------------------------
# Số liệu dưới đây **không** dựng tay: hộp và hai vai là toạ độ model thật
# trả về trên khung RTSP 704x576 (yolo11n-pose + yolo11n ncnn @320), chép
# nguyên từ phép đo. Nhờ vậy test khẳng định đúng ranh giới đã đo, không
# phải một hình dựng tiện tay.

#: ``rt_ph_00.jpg``, conf 0,3467 — điện thoại thật cầm trước ngực.
HOP_THAT = (318.3, 303.1, 439.0, 374.3)
VAI_THAT = ((289.4, 339.6), (118.0, 337.3))  # bề rộng 171,4 px

#: ``phone_hit_3.jpg``, conf **0,6986** — không có điện thoại, hộp nằm trên
#: gọng kính. Đây là hộp từng thắng cả ngưỡng conf 0,65.
HOP_GONG_KINH = (282.0, 123.3, 321.7, 275.0)
VAI_GONG_KINH = ((462.7, 343.6), (202.1, 298.1))  # bề rộng 264,6 px

#: ``negs/neg_11_f31.jpg``, conf 0,0644 — đủ rộng (0,610 lần vai) nên lọt vế
#: bề rộng, chỉ vế đường vai loại được (tâm cao hơn vai 158 px).
HOP_GIA_RONG = (151.3, 2.1, 328.4, 189.7)
VAI_GIA_RONG = ((370.1, 255.6), (79.6, 252.1))  # bề rộng 290,4 px

#: ``negs/neg_02_f22.jpg``, conf 0,1308 — nằm *dưới* vai nên lọt vế đường vai,
#: chỉ vế bề rộng loại được (0,145 lần vai).
HOP_GIA_HEP = (276.3, 391.6, 322.2, 512.2)
VAI_GIA_HEP = ((370.8, 309.6), (58.2, 256.4))  # bề rộng 317,2 px


def _voi_vai(vai, tay_trai=None, mui=None):
    """Keypoint (17,3) với hai vai (và mũi nếu truyền) đặt đúng toạ độ đo."""
    kp = _keypoints(tay_trai=tay_trai)
    kp[5] = (*vai[0], 0.9)
    kp[6] = (*vai[1], 0.9)
    if mui is not None:
        kp[0] = (*mui, 0.9)
    return kp


def _hop_hop_le(hop, vai, mui=None, **kwargs):
    return is_plausible_phone_box(
        hop, _voi_vai(vai, mui=mui), min_kp_conf=0.3, **kwargs
    )


def test_hop_dien_thoai_that_qua_bo_loc():
    """Hộp thật đo được (conf 0,3467) phải được giữ nguyên."""
    assert _hop_hop_le(HOP_THAT, VAI_THAT) is True


def test_hop_gong_kinh_conf_cao_bi_loai():
    """Hộp conf 0,6986 trên gọng kính — cao hơn cả hộp thật — phải bị loại.

    Đây là lý do tồn tại của bộ lọc: không ngưỡng conf nào loại được hộp
    này, vì nó tin cậy **hơn** điện thoại thật 2 lần.
    """
    assert _hop_hop_le(HOP_GONG_KINH, VAI_GONG_KINH) is False


def test_hop_gia_rong_nhung_cao_bi_loai():
    """Hộp đủ lớn (0,648 lần vai) nên lọt vế kích thước; chỉ vế đường vai
    loại được (tâm cao hơn vai 158 px).

    Test này giữ vế ``max_above_shoulder_px``: bỏ vế đó, hộp này lọt (xem
    ``test_nguong_hop_dien_thoai_co_the_chinh``).
    """
    assert _hop_hop_le(HOP_GIA_RONG, VAI_GIA_RONG) is False


def test_hop_gia_duoi_vai_nhung_nho_bi_loai():
    """Hộp nằm dưới vai lọt vế đường vai; chỉ vế kích thước loại được
    (cạnh dài 0,382 lần vai, dưới mốc 0,45).

    Test này giữ vế ``min_size_ratio``: bỏ vế đó, hộp này lọt.
    """
    assert _hop_hop_le(HOP_GIA_HEP, VAI_GIA_HEP) is False


def test_dien_thoai_cam_doc_van_qua_bo_loc():
    """Hộp hẹp mà **cao** là điện thoại cầm dọc — phải được giữ.

    Đây là lý do bộ lọc dùng cạnh dài chứ không dùng bề rộng: hộp 34 px rộng
    trên vai 171 px là 0,20 lần vai, lọt xuống dưới mọi mốc bề rộng hợp lý,
    nhưng cạnh dài 150 px là 0,88 lần vai — đúng một chiếc điện thoại.
    """
    hop_doc = (300.0, 260.0, 334.0, 410.0)  # 34 x 150, tâm ngang đường vai
    assert _hop_hop_le(hop_doc, VAI_THAT) is True


def test_vai_khong_do_duoc_thi_giu_hop():
    """Không có mốc co giãn → không kết luận, giữ hộp.

    Hướng an toàn: lúc đó ``PhoneSignal._proximity`` cũng chỉ còn
    ``touching_slack_px`` (mặc định 0), nên muốn báo chạm thì cổ tay phải
    nằm *trong* hộp — giữ hộp không sinh báo động giả, còn loại hộp thì có
    thể tắt tính năng im lặng mỗi lần pose yếu.
    """
    kp = _voi_vai(VAI_GONG_KINH)
    kp[5] = (kp[5][0], kp[5][1], 0.1)  # vai trái dưới ngưỡng
    assert is_plausible_phone_box(HOP_GONG_KINH, kp, min_kp_conf=0.3) is True


def test_vai_trung_diem_thi_giu_hop():
    """Hai vai cùng một điểm là output rác, không phải mốc → giữ hộp."""
    kp = _voi_vai(VAI_GONG_KINH)
    kp[6] = kp[5]
    assert is_plausible_phone_box(HOP_GONG_KINH, kp, min_kp_conf=0.3) is True


def test_hop_hong_thi_giu_hop():
    """Hộp hỏng không kết luận được — không loại oan."""
    assert (
        is_plausible_phone_box(
            (float("nan"), 1.0, 2.0, 3.0), _voi_vai(VAI_THAT), min_kp_conf=0.3
        )
        is True
    )


def test_nguong_hop_dien_thoai_co_the_chinh():
    """Hai ngưỡng là khóa cấu hình và đều có tác dụng thật.

    Nới ``max_above_shoulder_px`` lên rất lớn thì hộp giả to lọt lại —
    chứng minh vế đường vai đang làm việc, không phải vế kích thước gánh hết.
    """
    assert _hop_hop_le(HOP_GIA_RONG, VAI_GIA_RONG, max_above_shoulder_px=1000.0) is True
    # Còn hộp thật vẫn qua dù đặt ngưỡng mặc định — bộ lọc không ăn hộp thật.
    assert _hop_hop_le(HOP_THAT, VAI_THAT, max_above_shoulder_px=10.0) is True


# --------------------------------------------------------------------------
# Van an toàn cho điện thoại GIƠ LÊN CHE MẶT
# --------------------------------------------------------------------------
# Số liệu dưới đây chép nguyên từ phép đo trên ``frame.jpg`` (704x576): người
# giơ điện thoại dọc che mặt. Pose ``yolo11n-pose`` cho mũi (378, 222) và hai
# vai (415, 383), (304, 367). Hộp thật do ``yolo11x`` tìm được là
# ``(281, 1, 421, 318)``, IoU 0,86 với vùng điện thoại.

#: Mũi và hai vai đo được trên ``frame.jpg``.
MUI_GIO_MAT = (378.0, 222.0)
VAI_GIO_MAT = ((415.0, 383.0), (304.2, 366.6))  # bề rộng 112,0 px

#: Hộp điện thoại giơ che mặt — chính là hộp hai bộ lọc từng bỏ oan.
HOP_GIO_MAT = (281.0, 1.0, 421.0, 318.0)  # cạnh dài 317 = 2,83 lần vai


def _kp_gio_mat():
    return _voi_vai(VAI_GIO_MAT, mui=MUI_GIO_MAT)


def test_dien_thoai_gio_che_mat_khong_bi_coi_la_hop_dau():
    """Hộp thật giơ che mặt phủ mũi và cao gấp 2,1 lần khoảng mũi→vai.

    Không có van ``oversize_ratio`` thì hàm này trả ``True`` (bỏ hộp) — đúng
    lỗi làm tính năng im lặng ở tư thế dùng điện thoại rõ ràng nhất.
    """
    assert is_head_like_box(HOP_GIO_MAT, _kp_gio_mat(), min_kp_conf=0.25) is False
    # Tắt van → quay lại hành vi cũ (bỏ hộp), chứng minh van đang gánh.
    assert (
        is_head_like_box(
            HOP_GIO_MAT, _kp_gio_mat(), min_kp_conf=0.25, oversize_ratio=0.0
        )
        is True
    )


def test_dien_thoai_gio_che_mat_qua_bo_loc_vi_tri():
    """Cùng hộp đó: tâm cao hơn vai 215 px, cạnh dài 2,83 lần vai.

    Cả hai vế thường đều loại nó, nên chỉ van ``oversize_ratio`` cứu được.
    """
    assert _hop_hop_le(HOP_GIO_MAT, VAI_GIO_MAT) is True
    # Tắt van → hai vế thường loại hộp.
    assert _hop_hop_le(HOP_GIO_MAT, VAI_GIO_MAT, oversize_ratio=0.0) is False


def test_van_an_toan_khong_mo_duong_cho_hop_gong_kinh():
    """Hộp giả to nhất đo được ở vai **rộng** vẫn bị loại.

    Đây là vế giữ cho van không phá lỗi báo động giả mà bộ lọc sinh ra để sửa.
    """
    assert _hop_hop_le(HOP_GONG_KINH, VAI_GONG_KINH) is False
    # Hộp giả "rộng" cũng không được hưởng van.
    assert _hop_hop_le(HOP_GIA_RONG, VAI_GIA_RONG) is False


def test_van_an_toan_khong_mo_duong_khi_vai_bi_do_hep():
    """**Ca đã bắt được lỗi thật:** cùng hộp gọng kính, nhưng người quay chéo.

    Bề rộng vai co từ 264,6 px xuống 112 px (đúng số đo trên ``frame.jpg``),
    nên ``cạnh_dài/vai`` của hộp gọng kính nhảy từ 0,57 lên **1,35**, và của
    hộp giả rộng lên **1,67**. Một mốc ``oversize_ratio`` 1,2 sẽ giữ cả hai —
    tức bản sửa tự sinh ra báo động giả. Mốc 2,25 phải loại được cả hai.

    Test này khoá lại bài học đó: mọi mốc dưới 1,8 đều sai ở ca này.
    """
    assert _hop_hop_le(HOP_GONG_KINH, VAI_GIO_MAT, mui=MUI_GIO_MAT) is False
    assert _hop_hop_le(HOP_GIA_RONG, VAI_GIO_MAT, mui=MUI_GIO_MAT) is False
    # Chứng minh đây thật sự là ca biên: hạ mốc xuống 1,2 là lọt.
    assert (
        _hop_hop_le(HOP_GONG_KINH, VAI_GIO_MAT, mui=MUI_GIO_MAT, oversize_ratio=1.2)
        is True
    )
    assert (
        _hop_hop_le(HOP_GIA_RONG, VAI_GIO_MAT, mui=MUI_GIO_MAT, oversize_ratio=1.2)
        is True
    )
    # Và hộp thật giơ che mặt vẫn phải qua ở mốc mặc định.
    assert is_plausible_phone_box(HOP_GIO_MAT, _kp_gio_mat(), min_kp_conf=0.25) is True


def test_van_an_toan_co_the_tat_bang_0():
    """``oversize_ratio: 0`` là công tắc tắt van, không phải giá trị vô nghĩa."""
    kp = _kp_gio_mat()
    assert (
        is_head_like_box(HOP_GIO_MAT, kp, min_kp_conf=0.25, oversize_ratio=0.0) is True
    )
    assert _hop_hop_le(HOP_GIO_MAT, VAI_GIO_MAT, oversize_ratio=0.0) is False


@pytest.mark.parametrize("min_kp_conf", [-0.1, 1.1, float("nan")])
def test_hop_dien_thoai_nguong_conf_vo_ly_thi_nem(min_kp_conf):
    with pytest.raises(ValueError):
        is_plausible_phone_box(HOP_THAT, _voi_vai(VAI_THAT), min_kp_conf=min_kp_conf)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_size_ratio": -0.1},
        {"max_above_shoulder_px": -1.0},
        {"min_size_ratio": float("inf")},
        {"max_above_shoulder_px": float("nan")},
        {"oversize_ratio": -0.1},
        {"oversize_ratio": float("nan")},
    ],
)
def test_hop_dien_thoai_tham_so_vo_ly_thi_nem(kwargs):
    with pytest.raises(ValueError):
        is_plausible_phone_box(HOP_THAT, _voi_vai(VAI_THAT), min_kp_conf=0.3, **kwargs)
