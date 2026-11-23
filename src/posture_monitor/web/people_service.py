"""Hợp đồng dịch vụ người học (Protocol) mà tầng Web yêu cầu."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.enrollment import ENROLL_STEPS, PeopleServiceError


@runtime_checkable
class PeopleService(Protocol):
    """Giao diện dịch vụ người học được tiêm vào :func:`create_app`."""

    def list_people(self) -> list[dict]: ...

    def start_enroll(self, name: str) -> dict: ...

    def enroll_status(self, enroll_id: str) -> dict: ...

    def cancel_enroll(self, enroll_id: str) -> bool: ...

    def delete_person(self, person_id: str) -> bool: ...

    def select_person(self, person_id: str | None) -> bool: ...

    def selected_person(self) -> str | None: ...

    def signals(self) -> dict: ...

    def get_schedule(self) -> dict: ...

    def put_schedule(self, payload: dict) -> dict: ...


__all__ = ["ENROLL_STEPS", "PeopleService", "PeopleServiceError"]
