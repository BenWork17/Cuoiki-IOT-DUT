"""Bộ giữ trạng thái 3 tín hiệu (presence, phone, identity) kèm tuổi & hạn dùng hộp mặt."""

from __future__ import annotations

import math
from typing import Any, Callable

IDENTITY_MATCH = "MATCH"
IDENTITY_MISMATCH = "MISMATCH"
IDENTITY_UNKNOWN = "UNKNOWN"

STATE_NO_DATA = "chua_co_du_lieu"
PHONE_STATE_NONE = "khong_dung"
PHONE_STATE_USE = "dung"

PRESENCE_AGE_LIMIT_S = 3.0
PHONE_AGE_LIMIT_S = 3.0
IDENTITY_AGE_LIMIT_S = 10.0
FACE_BOX_MAX_AGE_S = 6.0


class SignalBoard:
    """Quản lý trạng thái tươi/hết hạn của các tín hiệu học tập và hộp khuôn mặt."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self.presence: dict[str, Any] = {"state": STATE_NO_DATA, "updated_at": None}
        self.phone: dict[str, Any] = {"state": STATE_NO_DATA, "updated_at": None}
        self.identity: dict[str, Any] = {
            "state": IDENTITY_UNKNOWN,
            "name": None,
            "reason": "Chưa có dữ liệu nhận diện.",
            "updated_at": None,
        }
        self.face_box: dict[str, Any] = {"box": None, "updated_at": None}

    def update_presence_phone(
        self,
        *,
        presence: str | None = None,
        phone: str | None = None,
        moment: float,
    ) -> None:
        if presence is not None:
            self.presence = {"state": str(presence), "updated_at": moment}
        if phone is not None:
            self.phone = {"state": str(phone), "updated_at": moment}

    def set_identity(
        self, *, state: str, name: str | None, reason: str, moment: float
    ) -> None:
        self.identity = {
            "state": state,
            "name": name,
            "reason": reason,
            "updated_at": moment,
        }

    def clear_face_box(self) -> None:
        self.face_box = {"box": None, "updated_at": None}

    def set_face_box(self, values: tuple[float, float, float, float], moment: float) -> None:
        self.face_box = {"box": values, "updated_at": moment}

    def latest_face_box(self, moment: float) -> tuple[float, float, float, float] | None:
        box = self.face_box.get("box")
        updated = self.face_box.get("updated_at")
        if box is None or updated is None:
            return None
        age = moment - float(updated)
        if not math.isfinite(age) or age < 0 or age > FACE_BOX_MAX_AGE_S:
            return None
        return (float(box[0]), float(box[1]), float(box[2]), float(box[3]))

    def snapshot(self) -> dict[str, Any]:
        now = float(self._clock())
        presence = self._entry(self.presence, PRESENCE_AGE_LIMIT_S, now)
        phone = self._entry(self.phone, PHONE_AGE_LIMIT_S, now)
        identity = self._entry(self.identity, IDENTITY_AGE_LIMIT_S, now)
        identity["name"] = self.identity.get("name")
        identity["reason"] = self.identity.get("reason")
        return {"presence": presence, "phone": phone, "identity": identity}

    @staticmethod
    def _entry(record: dict[str, Any], limit: float, now: float) -> dict[str, Any]:
        updated = record.get("updated_at")
        age: float | None = None
        if updated is not None:
            age = max(0.0, now - float(updated))
        return {
            "state": record.get("state", STATE_NO_DATA),
            "age_s": age,
            "age_limit_s": float(limit),
            "fresh": age is not None and age <= limit,
        }
