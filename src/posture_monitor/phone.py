"""Phát hiện "đang dùng điện thoại" bằng quan hệ bàn tay ↔ hộp điện thoại.

Spec v2 §5 (phát hiện hành vi) chỉ được thoả nếu *có* một phép đo hình học
đơn giản, giải thích được, giữ nguyên toàn bộ phần còn lại của pipeline. Module
này là đúng phần đó và **không** đụng tới ``pose.py``, ``config.py`` hay
``web/``.

Vì sao cần model thứ hai
------------------------
``yolo11n-pose`` (model hiện tại) chỉ có **một** lớp ``person``; nó không bao
giờ trả về hộp điện thoại. Muốn có hộp đó phải chạy thêm một model detect
COCO, ví dụ ``yolo11n``, và lấy lớp ``cell phone`` = :data:`PHONE_CLASS_ID`
(index 67).

**Về con số 98,6 ms.** Trên Pi 4, ``yolo11n`` ncnn @320 đo được 98,6 ms cho
**một lần suy luận**, trên một khung **tổng hợp** 640x480 (20 vòng). Con số
này **không** gồm thời gian đọc khung và **không** phải khung camera thật.
Nó **không** được dùng để khẳng định FPS nào: chi phí detect *trong pipeline
thật* chưa từng được đo. Ghép nó vào phép đo pipeline thật duy nhất của dự
án (pose-only, 199,25 ms → 5,02 FPS) cho 4,02 FPS ở nhịp 1/2 khung — tức
**chưa đạt** 5 FPS. Muốn có số thật thì chạy
``python -m posture_monitor benchmark --profile pose_phone``
(SPEC_V3 §4.3, §14 bước G).

Vì vậy module này cố ý **không** tự chạy detect và không tự đặt nhịp: nó chỉ
là hàm thuần. Người gọi quyết định chạy detect mỗi N khung, ở độ phân giải
nào, và truyền hộp đã quy về pixel của khung pose.

Hệ toạ độ
---------
``keypoints`` và ``phone_boxes`` **phải cùng hệ pixel** (cùng khung, cùng phép
co giãn). Nếu caller detect điện thoại ở 320×320 rồi truyền thẳng vào đây
trong khi pose chạy ở 1280×720 thì mọi khoảng cách đều sai — module không thể
tự phát hiện điều đó, nên đây là trách nhiệm của caller.

Định nghĩa "chạm" và cách quy đổi ngưỡng pixel
---------------------------------------------
"Chạm" **không** phải khoảng cách tâm-tâm. Ta lấy khoảng cách Euclid từ
**điểm** cổ tay đến **hình chữ nhật** hộp điện thoại (cạnh gần nhất); điểm nằm
trong hộp → 0. Cổ tay nằm trong hộp điện thoại, hoặc cách mép hộp không quá
``proximity_px``, được coi là đang dùng điện thoại.

``proximity_px`` là **tham số bắt buộc**, không có giá trị mặc định, vì nó phụ
thuộc độ phân giải và độ rung của model — hardcode một con số là sai ngầm ở
mọi độ phân giải khác. Hai cách quy đổi dùng được:

1. **Theo kích thước hộp điện thoại** (khuyến nghị, tự co theo phép đo):
   ``proximity_px ≈ ratio * max(w, h)`` của hộp điện thoại, ``ratio`` khoảng
   0.15–0.30. Trực giác: cổ tay nằm trong vòng "một bàn tay" quanh mép hộp.
   Ưu điểm: hộp điện thoại to khi người ở gần, nhỏ khi ở xa, ngưỡng co theo.
2. **Theo bề rộng khung**: ``proximity_px ≈ ratio_frame * frame_width``, với
   ``ratio_frame`` khoảng 0.01–0.02 (≈ một lòng bàn tay ở 1280 px là 13–26 px).
   Đơn giản nhưng không co theo khoảng cách người–camera.

Đánh đổi: ngưỡng quá nhỏ → bỏ sót lúc cổ tay thật sự chạm nhưng keypoint rung;
quá lớn → báo động giả khi tay chỉ ở gần. Vì vậy caller nên giữ thêm một quy
tắc thời gian (N khung liên tiếp) bên ngoài module: hàm này **không trạng
thái**, mỗi lần gọi độc lập.

Bàn tay dùng để xét là **cổ tay** COCO: index 9 (trái) và 10 (phải)
(:data:`WRIST_KEYPOINTS`). Cổ tay có ``conf`` dưới ``min_kp_conf`` bị **bỏ
qua** — đó là điều kiện chống báo động giả khi tay bị che: model pose vẫn trả
một điểm nhưng độ tin cậy sụp, và điểm đó thường nhảy lung tung.

Module không ghi log, không giữ dữ liệu cá nhân: chỉ trả kết quả cho caller.
"""

from __future__ import annotations

import math
from typing import NamedTuple, Sequence

import numpy as np

#: Index lớp ``cell phone`` trong bộ COCO 80 lớp mà ``yolo11n`` trả về.
PHONE_CLASS_ID = 67

#: Hai keypoint COCO dùng làm "bàn tay": 9 = cổ tay trái, 10 = cổ tay phải.
WRIST_KEYPOINTS: tuple[int, ...] = (9, 10)


class HandPhoneResult(NamedTuple):
    """Kết quả một lần xét bàn tay ↔ điện thoại, cùng chi tiết để debug.

    Attributes:
        co_cham: ``True`` khi có ít nhất một cổ tay hợp lệ nằm cách hộp điện
            thoại không quá ``proximity_px`` (nằm trong hộp tính là 0).
        khoang_cach_nho_nhat: khoảng cách pixel nhỏ nhất tìm được, hoặc
            ``None`` khi không có cặp (cổ tay hợp lệ, hộp hợp lệ) nào.
        khoang_cach_theo_tay: ``((index_cổ_tay, khoảng_cách), ...)`` cho từng
            cổ tay đã dùng, theo thứ tự :data:`WRIST_KEYPOINTS`; cổ tay bị bỏ
            qua không xuất hiện. Đây là phần debug, không phải hợp đồng.
        hop_gan_nhat: index trong ``phone_boxes`` của hộp gần nhất, hoặc
            ``None``.
        hop_le: ``False`` khi dữ liệu vào sai hình dạng tới mức không thể xét
            (khi đó mọi trường khác ở trạng thái an toàn "không chạm").
        ly_do: ghi chú ngắn vì sao không xét được gì, ``None`` khi bình thường.
    """

    co_cham: bool
    khoang_cach_nho_nhat: float | None
    khoang_cach_theo_tay: tuple[tuple[int, float], ...] = ()
    hop_gan_nhat: int | None = None
    hop_le: bool = True
    ly_do: str | None = None


def _khong_cham(ly_do: str | None = None) -> HandPhoneResult:
    """Kết quả an toàn: không chạm, không khoảng cách."""
    return HandPhoneResult(
        co_cham=False,
        khoang_cach_nho_nhat=None,
        ly_do=ly_do,
        hop_le=ly_do is None,
    )


def _doc_keypoints(keypoints: object) -> np.ndarray | None:
    """Ép ``keypoints`` về ``float`` shape ``(N, >=3)``; ``None`` nếu sai dạng."""
    try:
        arr = np.asarray(keypoints, dtype=float)
    except (TypeError, ValueError):
        return None
    if arr.ndim != 2 or arr.shape[1] < 3:
        return None
    if arr.shape[0] <= max(WRIST_KEYPOINTS):
        return None
    return arr


def _doc_hop(hop: Sequence[float]) -> tuple[float, float, float, float] | None:
    """Chuẩn hoá một hộp về ``x1 <= x2``, ``y1 <= y2``; ``None`` nếu không dùng được."""
    try:
        x1, y1, x2, y2 = (float(v) for v in hop)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
        return None
    if x1 > x2:
        x1, x2 = x2, x1
    if y1 > y2:
        y1, y2 = y2, y1
    return x1, y1, x2, y2


def khoang_cach_diem_hop(
    px: float, py: float, hop: tuple[float, float, float, float]
) -> float:
    """Khoảng cách Euclid từ điểm ``(px, py)`` đến hình chữ nhật; trong hộp → 0.

    Không dùng khoảng cách tới tâm hộp: một điểm ở góc hộp có cùng "khoảng cách
    tâm" với một điểm ngoài hộp phía trên, nhưng nghiệp vụ khác hẳn nhau.
    """
    x1, y1, x2, y2 = hop
    dx = max(x1 - px, 0.0, px - x2)
    dy = max(y1 - py, 0.0, py - y2)
    return math.hypot(dx, dy)


def hand_phone_contact(
    keypoints: object,
    phone_boxes: object,
    *,
    proximity_px: float,
    min_kp_conf: float,
) -> HandPhoneResult:
    """Xét cổ tay có chạm điện thoại không.

    Args:
        keypoints: mảng ``(17, 3)`` ``[x, y, conf]`` từ ``PoseResult`` (đã ghép
            ``xy`` và ``conf``), pixel cùng hệ với ``phone_boxes``. Chấp nhận
            ``list`` lồng nhau; mọi hình dạng khác trả kết quả an toàn.
        phone_boxes: dãy ``(x1, y1, x2, y2)`` pixel, ví dụ hộp lớp 67 của
            ``yolo11n``. Mục hỏng (không đủ 4 số, ``NaN``, ``inf``) bị bỏ qua;
            hộp bị đảo cạnh được chuẩn hoá.
        proximity_px: ngưỡng "dính" tính bằng pixel, **bắt buộc truyền**. Xem
            docstring module để biết cách quy đổi theo kích thước hộp điện
            thoại hoặc theo bề rộng khung.
        min_kp_conf: ngưỡng ``conf`` tối thiểu của cổ tay; cổ tay yếu hơn bị bỏ
            qua hoàn toàn (không được coi là "cách rất xa" cũng không phải
            "chạm").

    Returns:
        :class:`HandPhoneResult`. Không bao giờ ném lỗi vì dữ liệu vào; chỉ ném
        ``ValueError`` khi **tham số** vô lý (ngưỡng âm hoặc ngoài ``[0, 1]``),
        vì đó là lỗi lập trình của caller chứ không phải dữ liệu khung hình.

    Raises:
        ValueError: ``proximity_px`` âm hoặc không hữu hạn, ``min_kp_conf``
            ngoài ``[0, 1]``.
    """
    if not math.isfinite(proximity_px) or proximity_px < 0:
        raise ValueError("proximity_px phải là số hữu hạn không âm")
    if not math.isfinite(min_kp_conf) or not 0.0 <= min_kp_conf <= 1.0:
        raise ValueError("min_kp_conf phải nằm trong [0, 1]")

    arr = _doc_keypoints(keypoints)
    if arr is None:
        return _khong_cham("keypoints sai hình dạng")

    if phone_boxes is None:
        return _khong_cham("không có hộp điện thoại")
    try:
        danh_sach_hop = list(phone_boxes)
    except TypeError:
        return _khong_cham("phone_boxes không phải dãy")

    hop_hop_le: list[tuple[int, tuple[float, float, float, float]]] = []
    for i, hop in enumerate(danh_sach_hop):
        da_chuan = _doc_hop(hop)
        if da_chuan is not None:
            hop_hop_le.append((i, da_chuan))
    if not hop_hop_le:
        return _khong_cham("không có hộp điện thoại hợp lệ")

    khoang_cach_theo_tay: list[tuple[int, float]] = []
    gan_nhat: float | None = None
    hop_gan_nhat: int | None = None
    for idx in WRIST_KEYPOINTS:
        x, y, conf = (float(v) for v in arr[idx, :3])
        if not math.isfinite(conf) or conf < min_kp_conf:
            # Cổ tay bị che hoặc nhiễu: bỏ qua, đây là chống báo động giả.
            continue
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        gan_nhat_cua_tay = math.inf
        for vi_tri_goc, hop in hop_hop_le:
            d = khoang_cach_diem_hop(x, y, hop)
            if d < gan_nhat_cua_tay:
                gan_nhat_cua_tay = d
            if gan_nhat is None or d < gan_nhat:
                gan_nhat = d
                hop_gan_nhat = vi_tri_goc
        khoang_cach_theo_tay.append((idx, gan_nhat_cua_tay))

    if gan_nhat is None:
        return HandPhoneResult(
            co_cham=False,
            khoang_cach_nho_nhat=None,
            ly_do="không có cổ tay đủ tin cậy",
        )

    return HandPhoneResult(
        co_cham=gan_nhat <= proximity_px,
        khoang_cach_nho_nhat=gan_nhat,
        khoang_cach_theo_tay=tuple(khoang_cach_theo_tay),
        hop_gan_nhat=hop_gan_nhat,
    )
