"""Lớp lọc quyền riêng tư chống rò rỉ vector sinh trắc học ra HTTP."""

from __future__ import annotations

from typing import Any, Mapping

from .constants import PUBLIC_PERSON_FIELDS

_BIOMETRIC_KEYS = ("embedding", "embeddings", "vector", "vectors", "feature")


def public_person(item: Mapping[str, Any]) -> dict[str, Any]:
    """Lọc bản ghi người học theo danh sách trắng 3 trường công khai."""
    return {key: item.get(key) for key in PUBLIC_PERSON_FIELDS}


def scrub_biometrics(value: Any) -> Any:
    """Loại bỏ đệ quy mọi khóa mang dữ liệu sinh trắc học trước khi trả JSON."""
    if isinstance(value, Mapping):
        return {
            key: scrub_biometrics(item)
            for key, item in value.items()
            if str(key).lower() not in _BIOMETRIC_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [scrub_biometrics(item) for item in value]
    return value
