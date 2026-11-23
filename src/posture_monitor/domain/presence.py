"""Phát hiện người ngồi trong khung hình bằng keypoint thân trên và bộ lọc trễ thời gian."""

from __future__ import annotations

import math
import time
from typing import Any, Callable, NamedTuple

import numpy as np

from ..core.logging_setup import get_logger

logger = get_logger("posture_monitor.domain.presence")

STATE_PRESENT = "co_mat"
STATE_ABSENT = "vang_mat"

_UPPER_BODY_KEYPOINTS = (0, 1, 2, 3, 4, 5, 6)
DEFAULT_KP_CONF_MIN = 0.5
DEFAULT_MIN_UPPER_KEYPOINTS = 2
DEFAULT_ABSENT_HOLD_S = 3.0


class PresenceResult(NamedTuple):
    """Kết quả một lần cập nhật trạng thái hiện diện."""

    present: bool
    visible: bool
    upper_keypoints: int
    absent_for_s: float

    @property
    def state(self) -> str:
        return STATE_PRESENT if self.present else STATE_ABSENT


def count_upper_keypoints(pose: Any, kp_conf_min: float) -> int:
    """Đếm keypoint thân trên có độ tin cậy ``>= kp_conf_min`` (không bao giờ ném lỗi)."""
    if pose is None:
        return 0

    conf = getattr(pose, "conf", None)
    if conf is None:
        return 0
    try:
        conf_array = np.asarray(conf, dtype=float).reshape(-1)
    except (TypeError, ValueError, OverflowError):
        return 0

    if conf_array.size < len(_UPPER_BODY_KEYPOINTS) or not np.isfinite(conf_array).all():
        return 0

    try:
        threshold = float(kp_conf_min)
    except (TypeError, ValueError, OverflowError):
        return 0
    if not math.isfinite(threshold):
        return 0

    usable = conf_array[np.asarray(_UPPER_BODY_KEYPOINTS)] >= threshold
    return int(np.count_nonzero(usable))


class PresenceTracker:
    """Theo dõi người còn trong khung hay đã vắng liên tục đủ ``absent_hold_s``."""

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
                f"min_upper_keypoints phải trong [0, {len(_UPPER_BODY_KEYPOINTS)}], "
                f"nhận được {min_upper_keypoints!r}."
            )
        self._min_upper_keypoints = int(min_upper_keypoints)
        self._clock = clock
        self._absent_since: float | None = None
        self._present = True

    @property
    def absent_hold_s(self) -> float:
        return self._absent_hold_s

    def reset(self) -> None:
        self._absent_since = None
        self._present = True

    def update(self, pose: Any) -> PresenceResult:
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
        if present == self._present:
            return
        if present:
            logger.info(
                "Thấy người trở lại trong khung sau %.1f giây vắng.", absent_for_s
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
