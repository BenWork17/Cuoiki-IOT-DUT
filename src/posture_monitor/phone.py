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

Đo trên camera Tiandy thật (RTSP 704x576) cho thấy hai cách trên đều **không**
đủ: cổ tay COCO dừng ở **112–138 px** cách hộp điện thoại thật, tức
**0,70–0,86 lần bề rộng vai** (vai đo được 148,8–171,3 px). Một ngưỡng pixel
cố định không co theo khoảng cách người–camera, còn ``max(w, h)`` của hộp
điện thoại lại quá nhỏ. Vì vậy ngưỡng thực tế nên lấy theo **bề rộng vai**:

3. **Theo bề rộng vai** (dùng trong dự án): ``proximity_px ≈
   ratio_vai * shoulder_width_px(...)``, ``ratio_vai`` khoảng 0,9–1,0 theo
   phép đo trên. :func:`shoulder_width_px` trả ``None`` khi vai không đủ tin
   cậy — khi đó caller **không** được đoán, cứ coi như không chạm.

Lọc hộp "đeo kính"
------------------
Ở cùng phép đo, model COCO cho **hộp giả lớp 67** quanh gọng kính/khung mặt
với conf 0,023–0,068 — thấp hơn hộp thật (tối đa 0,236) nhưng không tách được
bằng ngưỡng conf vì hai dải chồng nhau. Chúng tách được bằng hình học: hộp giả
**phủ lên mũi và cao cỡ khoảng cách mũi→vai**. :func:`is_head_like_box` là
đúng phép thử đó; đo được nó bỏ **0** hộp điện thoại thật và giữ **0** hộp
kính qua (xem test ``tests/test_phone.py``).

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

#: Hai keypoint COCO dùng làm mốc thân trên: 5 = vai trái, 6 = vai phải.
SHOULDER_KEYPOINTS: tuple[int, int] = (5, 6)

#: Keypoint mũi COCO — mốc để nhận ra hộp "đeo kính" giả.
NOSE_KEYPOINT = 0


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


def shoulder_width_px(keypoints: object, *, min_kp_conf: float) -> float | None:
    """Bề rộng vai (pixel) — mốc co giãn cho ngưỡng "chạm".

    Args:
        keypoints: mảng ``(17, >=3)`` ``[x, y, conf]`` như của
            :func:`hand_phone_contact`.
        min_kp_conf: ngưỡng ``conf`` tối thiểu; **cả hai** vai phải đạt ngưỡng
            thì mới có bề rộng, ngược lại trả ``None``.

    Returns:
        Khoảng cách Euclid giữa hai vai, hoặc ``None`` khi không đủ dữ liệu
        (sai hình dạng, thiếu vai, ``conf`` dưới ngưỡng, toạ độ không hữu
        hạn). Caller **không** được thay bằng một con số mặc định: vai không
        đọc được nghĩa là không có mốc co giãn, và đoán ở đây chính là báo
        động giả.

    Raises:
        ValueError: ``min_kp_conf`` ngoài ``[0, 1]`` hoặc không hữu hạn.
    """
    if not math.isfinite(min_kp_conf) or not 0.0 <= min_kp_conf <= 1.0:
        raise ValueError("min_kp_conf phải nằm trong [0, 1]")

    arr = _doc_keypoints(keypoints)
    if arr is None:
        return None

    points: list[tuple[float, float]] = []
    for index in SHOULDER_KEYPOINTS:
        x, y, conf = (float(v) for v in arr[index, :3])
        if not math.isfinite(conf) or conf < min_kp_conf:
            return None
        if not (math.isfinite(x) and math.isfinite(y)):
            return None
        points.append((x, y))

    (x1, y1), (x2, y2) = points
    width = math.hypot(x2 - x1, y2 - y1)
    # Hai vai trùng điểm (model trả một điểm rác cho cả hai) → không có mốc.
    if not math.isfinite(width) or width <= 0.0:
        return None
    return width


def is_head_like_box(
    box: tuple[float, float, float, float],
    keypoints: object,
    *,
    min_kp_conf: float,
    span_ratio: float = 1.0,
    oversize_ratio: float = 2.25,
) -> bool:
    """Hộp này có phải hộp **giả** phủ vùng đầu (gọng kính, khung mặt) không.

    Model COCO trên camera thật trả lớp 67 cho gọng kính với conf **0,023–0,068**
    và cho điện thoại thật tới **0,236** — hai dải chồng nhau, nên không lọc
    được bằng ``conf_threshold``. Nhưng vị trí thì tách hẳn: hộp giả **phủ lên
    điểm mũi** và **cao cỡ khoảng cách mũi→vai**; hộp điện thoại thật nằm dưới
    vai và thấp hơn nhiều.

    Đo trên 50 khung RTSP thật: bỏ đúng **0** hộp điện thoại thật, giữ đúng
    **0** hộp kính.

    Args:
        box: ``(x1, y1, x2, y2)`` pixel cùng hệ với ``keypoints``.
        keypoints: mảng ``(17, >=3)`` như của :func:`hand_phone_contact`.
        min_kp_conf: ngưỡng ``conf`` của mũi và hai vai; dưới ngưỡng thì
            **không** kết luận là hộp đầu (trả ``False``) — thà để lọt hộp giả
            còn hơn bỏ mất hộp thật chỉ vì pose yếu.
        span_ratio: hộp phải cao ít nhất ``span_ratio`` lần khoảng cách
            mũi→vai mới bị coi là hộp đầu. Mặc định 1,0 theo phép đo.
        oversize_ratio: **van an toàn cho trường hợp điện thoại giơ lên
            trước mặt.** Hộp có cạnh dài vượt ``oversize_ratio`` lần bề rộng
            vai thì **không** bị coi là hộp đầu, dù nó phủ mũi và cao hơn
            khoảng mũi→vai. Đo trên ``frame.jpg`` (điện thoại che mặt, 704x576):
            hộp thật ``(281, 1, 421, 318)`` cao 317 px = **2,83** lần bề rộng
            vai 112 px. Đặt ``0`` để tắt van này.

            **Vì sao 2,25 mà không phải một số nhỏ hơn.** Bề rộng vai đo được
            **co lại khi người quay chéo** — trên ``frame.jpg`` chỉ 112 px thay
            vì 171–317 px như các ảnh khác. Đo lại hộp gọng kính thật
            ``(282, 123, 322, 275)`` với bề rộng vai 112 px cho tỉ lệ **1,35**,
            và hộp giả rộng ``(151, 2, 328, 190)`` cho **1,67**. Một mốc 1,2 vì
            thế **mở đường cho báo động giả** đúng ở tư thế quay chéo — đã đo
            được, không phải giả định. Quét mốc trên 8 ca (3 hộp thật + 5 hộp
            giả, gồm cả hai ca vai hẹp) cho dải không sai ca nào là
            **1,8–2,8**; 2,25 nằm giữa. Mốc 3,0 bắt đầu bỏ hộp thật.

    Returns:
        ``True`` khi hộp phủ mũi, phủ mũi theo trục x, cao ít nhất
        ``span_ratio * (y_vai - y_mũi)`` **và** không vượt ``oversize_ratio``
        lần bề rộng vai. ``False`` khi thiếu dữ liệu hoặc khi hộp không thoả.

    Raises:
        ValueError: tham số vô lý (``min_kp_conf`` ngoài ``[0, 1]``,
            ``span_ratio`` không hữu hạn hoặc âm, ``oversize_ratio`` âm).
    """
    if not math.isfinite(min_kp_conf) or not 0.0 <= min_kp_conf <= 1.0:
        raise ValueError("min_kp_conf phải nằm trong [0, 1]")
    if not math.isfinite(span_ratio) or span_ratio < 0.0:
        raise ValueError("span_ratio phải là số hữu hạn không âm")
    if not math.isfinite(oversize_ratio) or oversize_ratio < 0.0:
        raise ValueError("oversize_ratio phải là số hữu hạn không âm")

    hop = _doc_hop(box)
    if hop is None:
        return False
    arr = _doc_keypoints(keypoints)
    if arr is None:
        return False

    x1, y1, x2, y2 = hop
    nose = arr[NOSE_KEYPOINT, :3]
    if not all(math.isfinite(float(v)) for v in nose):
        return False
    if float(nose[2]) < min_kp_conf:
        return False
    nose_x, nose_y = float(nose[0]), float(nose[1])

    shoulder_ys: list[float] = []
    for index in SHOULDER_KEYPOINTS:
        x, y, conf = (float(v) for v in arr[index, :3])
        if not math.isfinite(conf) or conf < min_kp_conf:
            return False
        if not (math.isfinite(x) and math.isfinite(y)):
            return False
        shoulder_ys.append(y)
    shoulder_y = sum(shoulder_ys) / len(shoulder_ys)

    span = shoulder_y - nose_y
    if not math.isfinite(span) or span <= 0.0:
        return False
    box_h = y2 - y1
    covers_nose = y1 <= nose_y <= y2 and x1 <= nose_x <= x2
    if not (covers_nose and box_h >= span_ratio * span):
        return False
    if oversize_ratio > 0.0:
        width = shoulder_width_px(arr, min_kp_conf=min_kp_conf)
        if width is not None:
            longest_side = max(x2 - x1, box_h)
            if longest_side > oversize_ratio * width:
                # Quá to để là gọng kính: điện thoại giơ lên che mặt.
                return False
    return True


def is_plausible_phone_box(
    box: tuple[float, float, float, float],
    keypoints: object,
    *,
    min_kp_conf: float,
    min_size_ratio: float = 0.45,
    max_above_shoulder_px: float = 10.0,
    oversize_ratio: float = 2.25,
) -> bool:
    """Hộp này có nằm đúng chỗ một chiếc điện thoại đang được cầm không.

    Vì sao cần phép thử này — đo trên camera Tiandy thật
    ----------------------------------------------------
    Khi người đưa tay lên cằm/mặt, model COCO trả lớp 67 cho **gọng kính** với
    conf tới **0,699**, còn điện thoại thật chỉ **0,347**. Hộp giả **cao hơn**
    hộp thật, nên **không** ngưỡng conf nào tách được hai lớp này. Tách được
    chỉ bằng vị trí, và vị trí tách rất sạch:

    =======================  ==========================  ====================
    Tập đo                   ``cy - y_vai``              ``cạnh_dài / bề_vai``
    =======================  ==========================  ====================
    8 hộp thật (3 ảnh)       **-2 … +13 px**             **0,515 … 1,061**
    24 hộp giả (14 ảnh)      **-68 … -293 px**           **0,179 … 0,845**
    6 hộp "tay lên cằm"      **-118 … -129 px**          **0,15 … 0,57**
    =======================  ==========================  ====================

    Bảng trên chỉ là **cận trên** của từng vế: không vế nào tự tách sạch.
    Tám hộp giả có ``cạnh_dài/vai >= 0,45`` (tới 0,845) nhưng **cả tám** đều
    nằm trên ``y_vai - 10``. Hai hộp giả nằm dưới đường vai có
    ``cạnh_dài/vai 0,310`` và ``0,382``. Vì vậy thứ tự hai vế có ý nghĩa: vế
    đường vai chạy trước và cắt 22/24 hộp giả; chỉ hai hộp còn lại mới bị vế
    kích thước quyết định. Dải để chọn ngưỡng kích thước vì thế là
    **0,382 … 0,515** — mốc 0,45 nằm giữa, cách mỗi mép ~0,07.

    Dùng cạnh dài ``max(w, h)`` chứ **không** phải bề rộng: điện thoại cầm
    dọc có bề rộng nhỏ, nên bề rộng sẽ loại oan chính trường hợp phổ biến
    nhất. Đo trên cùng dữ liệu, bề rộng cho dải 0,145 … 0,515, cạnh dài cho
    dải rộng hơn và đối xứng hơn quanh mốc chọn.

    Kết quả đo của cả phép thử: giữ **8/8** hộp thật (xuống tới conf 0,022) và
    loại **0/24** hộp giả, kể cả cả 6 hộp ``phone_hit_*`` conf 0,501–0,699.

    Giới hạn của con số: đo trên **một người, một phiên, một khoảng cách
    camera**. Hai ngưỡng vì thế là khóa cấu hình (``phone.min_size_ratio``,
    ``phone.max_above_shoulder_px``), không phải hằng số chôn trong code.

    Giới hạn của cả hai vế trên — và van ``oversize_ratio``
    -------------------------------------------------------
    Toàn bộ bảng trên đo trên điện thoại cầm **trước ngực**. Tư thế dùng
    điện thoại rõ ràng nhất — **giơ lên che mặt** — nằm ngoài bảng đó: hộp
    phủ mũi, tâm cao hơn vai hơn 200 px và cạnh dài 2,83 lần bề rộng vai, nên
    **cả hai** vế đều loại đúng hộp thật. Đo trên ``frame.jpg``: hai bộ lọc
    cùng bỏ ``(281, 1, 421, 318)``. Vì vậy có thêm van ``oversize_ratio``:
    hộp **quá to để là gọng kính** thì được giữ bất kể hai vế trên.

    Chọn mốc cho van này phải tính tới việc **bề rộng vai co lại khi người
    quay chéo** (112 px trên ``frame.jpg`` so với 171–317 px ở các ảnh khác):
    hộp gọng kính thật đạt 1,35 và hộp giả rộng đạt 1,67 ở bề rộng vai 112 px.
    Quét mốc trên 8 ca cho dải an toàn **1,8–2,8**; mặc định 2,25.

    Vì sao thiếu vai lại trả ``True`` (giữ hộp)
    -------------------------------------------
    Hàm này trả ``False`` **chỉ khi** đo được vai và hộp vi phạm rõ ràng. Vai
    không đọc được thì không có mốc co giãn, và lúc đó
    :meth:`PhoneSignal._proximity` cũng chỉ còn ``touching_slack_px`` (mặc
    định **0**): muốn báo "chạm" thì cổ tay phải **nằm trong** hộp. Giữ hộp
    khi đó không tạo được báo động giả, còn loại hộp thì có thể làm tính năng
    im lặng tắt hẳn mỗi lần pose yếu — đúng kiểu "chưa hoạt động" cần tránh.
    Đây là cùng hướng an toàn với :func:`is_head_like_box`.

    Args:
        box: ``(x1, y1, x2, y2)`` pixel cùng hệ với ``keypoints``.
        keypoints: mảng ``(17, >=3)`` như của :func:`hand_phone_contact`.
        min_kp_conf: ngưỡng ``conf`` của **cả hai** vai; dưới ngưỡng thì
            không có mốc và hàm trả ``True`` (xem trên).
        min_size_ratio: cạnh dài của hộp tối thiểu theo bề rộng vai. Dùng
            **cạnh dài** (``max(w, h)``) chứ không phải bề rộng: điện thoại
            cầm dọc có bề rộng nhỏ. Dải đo được để chọn mốc là 0,382 … 0,515;
            0,45 nằm giữa.
        max_above_shoulder_px: hộp được phép cao hơn đường vai bao nhiêu
            pixel. Đo được hộp thật cao nhất là 13 px **dưới** vai; 10 px là
            mốc chặt hơn một chút về phía an toàn.
        oversize_ratio: **van an toàn cho điện thoại giơ lên trước mặt.** Hộp
            có cạnh dài vượt ``oversize_ratio`` lần bề rộng vai thì **luôn**
            được giữ, bỏ qua cả vế đường vai lẫn vế kích thước. Lý do: hai vế
            dưới được đo trên điện thoại cầm **trước ngực**, còn tư thế dùng
            điện thoại rõ ràng nhất — giơ lên che mặt — cho hộp phủ mũi, tâm
            cao hơn vai hơn 200 px và cạnh dài 2,8 lần bề rộng vai. Không có
            van này thì bộ lọc bỏ đúng trường hợp thật (đo trên ``frame.jpg``).
            Đặt ``0`` để tắt van này.

            **Vì sao 2,25.** Không được chọn mốc thấp: **bề rộng vai co lại
            khi người quay chéo** (112 px trên ``frame.jpg``). Với vai 112 px,
            hộp gọng kính thật đạt **1,35** và hộp giả rộng đạt **1,67** —
            mốc 1,2 vì thế mở đường cho báo động giả (đã đo, không phải giả
            định). Quét mốc trên 8 ca (3 hộp thật, 5 hộp giả, gồm hai ca vai
            hẹp): dải không sai ca nào là **1,8–2,8**, và 3,0 bắt đầu bỏ hộp
            thật. 2,25 nằm giữa dải.

    Returns:
        ``True`` khi hộp to hơn ``oversize_ratio`` lần bề rộng vai, hoặc khi
        hộp thoả cả hai vế, hoặc khi thiếu dữ liệu để kết luận (hình dạng sai,
        hộp hỏng, vai yếu/trùng điểm). ``False`` khi đo được vai **và** hộp
        không to vượt van **và** (tâm hộp cao hơn đường vai quá
        ``max_above_shoulder_px`` **hoặc** cạnh dài hộp dưới ``min_size_ratio``
        lần bề rộng vai).

    Raises:
        ValueError: tham số vô lý (``min_kp_conf`` ngoài ``[0, 1]``,
            ``min_size_ratio``, ``max_above_shoulder_px`` hoặc
            ``oversize_ratio`` âm/không hữu hạn).
    """
    if not math.isfinite(min_kp_conf) or not 0.0 <= min_kp_conf <= 1.0:
        raise ValueError("min_kp_conf phải nằm trong [0, 1]")
    if not math.isfinite(min_size_ratio) or min_size_ratio < 0.0:
        raise ValueError("min_size_ratio phải là số hữu hạn không âm")
    if not math.isfinite(max_above_shoulder_px) or max_above_shoulder_px < 0.0:
        raise ValueError("max_above_shoulder_px phải là số hữu hạn không âm")
    if not math.isfinite(oversize_ratio) or oversize_ratio < 0.0:
        raise ValueError("oversize_ratio phải là số hữu hạn không âm")

    hop = _doc_hop(box)
    if hop is None:
        return True
    arr = _doc_keypoints(keypoints)
    if arr is None:
        return True

    width = shoulder_width_px(arr, min_kp_conf=min_kp_conf)
    if width is None:
        # Không có mốc co giãn: không kết luận. Xem "Vì sao thiếu vai…".
        return True

    shoulder_ys: list[float] = []
    for index in SHOULDER_KEYPOINTS:
        shoulder_ys.append(float(arr[index, 1]))
    shoulder_y = sum(shoulder_ys) / len(shoulder_ys)

    x1, y1, x2, y2 = hop
    longest_side = max(x2 - x1, y2 - y1)
    if oversize_ratio > 0.0 and longest_side > oversize_ratio * width:
        # Quá to để là gọng kính: điện thoại giơ lên che mặt. Xem docstring.
        return True
    center_y = (y1 + y2) / 2.0
    if center_y < shoulder_y - max_above_shoulder_px:
        return False
    return longest_side >= min_size_ratio * width
