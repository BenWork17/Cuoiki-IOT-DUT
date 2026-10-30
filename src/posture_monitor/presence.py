"""Phát hiện người ngồi trong khung hình và trạng thái vắng mặt có trễ.

Module này trả lời một câu hỏi hẹp hơn :mod:`posture_monitor.state`: *người
học còn ngồi trước bàn không*, tách hẳn khỏi việc chấm tư thế. Nó **không**
thay thế nhãn ``ABSENT`` của ``classifier`` (nhãn đó nói "khung này không đủ
dữ kiện để chấm tư thế") và không đụng tới cơ chế nhả track ``_mark_absent``
trong ``pose.py`` (cơ chế đó chỉ để chọn đúng người đang theo dõi). Ba khái
niệm là khác nhau:

- ``classifier.ABSENT``: không chấm được tư thế ở khung này.
- ``pose._mark_absent``: mất track, có thể chọn người khác sau
  ``timing.absent_reset_s``.
- :class:`PresenceTracker` (module này): người đã rời khung **đủ lâu** để
  đáng báo "vắng mặt".

Vì sao đếm keypoint thay vì dựa vào ``bbox``
--------------------------------------------

Khung bao do model trả về là **suy đoán** của bộ dò: nó vẫn tồn tại khi người
cúi gập xuống bàn, và có thể còn sót lại vài khung sau khi người đã đứng dậy.
Dựa vào diện tích khung bao sẽ báo "còn người" cho một cái ghế trống hoặc báo
"mất người" ngay khi người cúi xuống. Ngược lại, keypoint có độ tin cậy riêng
từng điểm; đếm số điểm **thân trên** đủ tin cậy là bằng chứng trực tiếp hơn
rằng thân người đang nằm trong khung (spec v2 §5.3, §11.4: không đoán).

Chọn vùng đầu + vai (mũi, hai mắt, hai tai, hai vai — 7 điểm COCO) thay vì
toàn bộ 17 điểm vì hông/gối/ cổ chân thường bị bàn che và bị model bỏ qua khi
ngồi; đòi hỏi chúng sẽ báo vắng mặt sai. Yêu cầu tối thiểu
:data:`DEFAULT_MIN_UPPER_KEYPOINTS` = 2 điểm: một mình cái mũi có thể là nhiễu,
nhưng hai vai vẫn đủ để nói "người còn đó" kể cả khi cúi gập đầu xuống bàn —
đây chính là ca biên quan trọng nhất của module.

Bộ lọc thời gian
----------------

Một khung lỡ mất người không có nghĩa là người đã đi. Trạng thái chỉ chuyển
sang vắng mặt khi chuỗi vắng **liên tục** dài tối thiểu ``absent_hold_s``.
Mọi mốc thời gian lấy từ ``clock`` tiêm từ ngoài (mặc định
``time.monotonic``), nhờ vậy test tất định và không cần ``sleep``. Không đọc
``config`` toàn cục: ngưỡng là tham số constructor do tầng gọi truyền vào.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Callable, NamedTuple

import numpy as np

from .logging_setup import get_logger

logger = get_logger(__name__)

#: Trạng thái trả ra (chuỗi tiếng Việt không dấu để ổn định trong log/API).
STATE_PRESENT = "co_mat"
STATE_ABSENT = "vang_mat"

# Chỉ số keypoint COCO vùng thân trên (xem ``features.py``).
_UPPER_BODY_KEYPOINTS = (0, 1, 2, 3, 4, 5, 6)  # mũi, 2 mắt, 2 tai, 2 vai

#: Ngưỡng tin cậy mặc định, khớp ``features.DEFAULT_KP_CONF_MIN``.
DEFAULT_KP_CONF_MIN = 0.5

#: Số keypoint thân trên tối thiểu để coi là còn người trong khung.
#: Bằng 2 vì hai vai đủ chứng minh thân người còn đó dù đầu đã cúi khuất.
DEFAULT_MIN_UPPER_KEYPOINTS = 2

#: Thời gian vắng liên tục mặc định trước khi báo vắng mặt (giây).
DEFAULT_ABSENT_HOLD_S = 3.0


class PresenceResult(NamedTuple):
    """Kết quả một lần cập nhật trạng thái hiện diện.

    Attributes:
        present: ``True`` khi còn người (kể cả đang trong khoảng chờ
            ``absent_hold_s``), ``False`` khi đã vắng đủ lâu.
        visible: bằng chứng của **riêng khung này** — có thấy người hay
            không, chưa qua bộ lọc thời gian. Khác ``present`` giúp tầng
            trên phân biệt "mất một khung" với "đã vắng thật".
        upper_keypoints: số keypoint thân trên đủ tin cậy ở khung này.
        absent_for_s: số giây vắng liên tục tính tới lúc cập nhật; ``0.0``
            khi ``visible`` là ``True``.
    """

    present: bool
    visible: bool
    upper_keypoints: int
    absent_for_s: float

    @property
    def state(self) -> str:
        """``"co_mat"`` hoặc ``"vang_mat"``."""
        return STATE_PRESENT if self.present else STATE_ABSENT


def count_upper_keypoints(pose: Any, kp_conf_min: float) -> int:
    """Đếm keypoint thân trên có độ tin cậy ``>= kp_conf_min``.

    Hàm thuần, không I/O, không bao giờ ném lỗi với dữ liệu hỏng: ``pose``
    là ``None``, thiếu thuộc tính, mảng rỗng, sai shape, chứa NaN hoặc conf
    toàn 0 đều trả ``0`` (tức "không có bằng chứng có người"), tuyệt đối
    không đoán (spec v2 §11.4).

    Args:
        pose: :class:`~posture_monitor.pose.PoseResult` (hoặc ``None``).
        kp_conf_min: ngưỡng tin cậy; điểm có ``conf`` **đúng bằng** ngưỡng
            vẫn được đếm (cùng quy ước với ``features.extract``).

    Returns:
        Số điểm trong ``[0, 7]``.
    """
    if pose is None:
        return 0

    conf = getattr(pose, "conf", None)
    if conf is None:
        return 0
    try:
        conf_array = np.asarray(conf, dtype=float).reshape(-1)
    except (TypeError, ValueError, OverflowError):
        return 0

    if conf_array.size < len(_UPPER_BODY_KEYPOINTS):
        return 0
    if not np.isfinite(conf_array).all():
        return 0

    try:
        threshold = float(kp_conf_min)
    except (TypeError, ValueError, OverflowError):
        return 0
    if not math.isfinite(threshold):
        return 0

    # So sánh trên Python float / ndarray float, không so numpy scalar với
    # None và không dùng "is None" cho số.
    usable = conf_array[np.asarray(_UPPER_BODY_KEYPOINTS)] >= threshold
    return int(np.count_nonzero(usable))


class PresenceTracker:
    """Theo dõi người còn trong khung hay đã vắng đủ lâu.

    Args:
        absent_hold_s: số giây vắng **liên tục** tối thiểu trước khi báo
            vắng mặt. ``0`` nghĩa là báo ngay ở khung đầu tiên không thấy
            người.
        kp_conf_min: ngưỡng tin cậy keypoint.
        min_upper_keypoints: số keypoint thân trên tối thiểu để coi là còn
            người.
        clock: hàm trả thời gian (giây). Tiêm để test tất định; mặc định
            ``time.monotonic``.

    Raises:
        ValueError: khi một tham số số không hữu hạn hoặc âm, hoặc
            ``min_upper_keypoints`` vượt số điểm thân trên.
    """

    def __init__(
        self,
        absent_hold_s: float = DEFAULT_ABSENT_HOLD_S,
        *,
        kp_conf_min: float = DEFAULT_KP_CONF_MIN,
        min_upper_keypoints: int = DEFAULT_MIN_UPPER_KEYPOINTS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._absent_hold_s = _finite_non_negative(absent_hold_s, "absent_hold_s")
        self._kp_conf_min = _finite_non_negative(kp_conf_min, "kp_conf_min")
        if not 0 <= int(min_upper_keypoints) <= len(_UPPER_BODY_KEYPOINTS):
            raise ValueError(
                "min_upper_keypoints phải trong "
                f"[0, {len(_UPPER_BODY_KEYPOINTS)}], nhận được "
                f"{min_upper_keypoints!r}."
            )
        self._min_upper_keypoints = int(min_upper_keypoints)
        self._clock = clock

        #: Mốc bắt đầu chuỗi vắng hiện tại; ``None`` khi đang thấy người.
        self._absent_since: float | None = None
        #: Trạng thái lần trước, chỉ để log lúc chuyển trạng thái.
        self._present = True

    @property
    def absent_hold_s(self) -> float:
        return self._absent_hold_s

    def reset(self) -> None:
        """Quên chuỗi vắng hiện tại, coi như vừa thấy người.

        Dùng khi bắt đầu một phiên học mới: ``absent_for_s`` đo khoảng
        **liên tục** không thấy người, nên giữ mốc cũ qua một khoảng nghỉ dài
        sẽ khiến khung đầu tiên của phiên mới đã "vắng đủ lâu" và báo oan
        ngay cả khi người đang ngồi đó.
        """
        self._absent_since = None
        self._present = True

    def update(self, pose: Any) -> PresenceResult:
        """Cập nhật bằng pose của khung hiện tại.

        Args:
            pose: :class:`~posture_monitor.pose.PoseResult` hoặc ``None``.

        Returns:
            :class:`PresenceResult`. Không ném lỗi với dữ liệu hỏng.
        """
        keypoints = count_upper_keypoints(pose, self._kp_conf_min)
        visible = keypoints >= self._min_upper_keypoints
        now = float(self._clock())

        if visible:
            self._absent_since = None
            absent_for_s = 0.0
            present = True
        else:
            if self._absent_since is None:
                self._absent_since = now
            absent_for_s = max(0.0, now - self._absent_since)
            present = absent_for_s < self._absent_hold_s

        self._log_transition(present, absent_for_s)
        self._present = present
        return PresenceResult(
            present=present,
            visible=visible,
            upper_keypoints=keypoints,
            absent_for_s=absent_for_s,
        )

    def _log_transition(self, present: bool, absent_for_s: float) -> None:
        """Chỉ log khi đổi trạng thái; không ghi dữ liệu cá nhân."""
        if present == self._present:
            return
        if present:
            logger.info(
                "Thấy người trở lại trong khung sau %.1f giây vắng.",
                absent_for_s,
            )
        else:
            logger.info(
                "Không thấy người trong khung liên tục %.1f giây; báo vắng mặt.",
                absent_for_s,
            )


def _finite_non_negative(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} phải là số hữu hạn không âm, nhận được {value!r}.")
    return number
