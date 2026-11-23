"""Gói nghiệp vụ ``domain``: StateMachine, Presence, Schedule, StudySession & PeopleService."""

from __future__ import annotations

import importlib

_EXPORTS: dict[str, tuple[str, str]] = {
    "ENROLL_STEPS": (".enrollment", "ENROLL_STEPS"),
    "PeopleServiceError": (".enrollment", "PeopleServiceError"),
    "derive_threshold": (".enrollment", "derive_threshold"),
    "IDENTITY_MATCH": (".people_service", "IDENTITY_MATCH"),
    "IDENTITY_MISMATCH": (".people_service", "IDENTITY_MISMATCH"),
    "IDENTITY_UNKNOWN": (".people_service", "IDENTITY_UNKNOWN"),
    "OBSERVATION_SKIPPED": (".people_service", "OBSERVATION_SKIPPED"),
    "PHONE_STATE_NONE": (".people_service", "PHONE_STATE_NONE"),
    "PHONE_STATE_USE": (".people_service", "PHONE_STATE_USE"),
    "PeopleService": (".people_service", "PeopleService"),
    "PresenceResult": (".presence", "PresenceResult"),
    "PresenceTracker": (".presence", "PresenceTracker"),
    "count_upper_keypoints": (".presence", "count_upper_keypoints"),
    "ALERT_KINDS": (".schedule", "ALERT_KINDS"),
    "AlertDecision": (".schedule", "AlertDecision"),
    "KindSettings": (".schedule", "KindSettings"),
    "ScheduleConfig": (".schedule", "ScheduleConfig"),
    "ScheduleError": (".schedule", "ScheduleError"),
    "TimeWindow": (".schedule", "TimeWindow"),
    "is_active": (".schedule", "is_active"),
    "should_alert": (".schedule", "should_alert"),
    "Event": (".state", "Event"),
    "Smoother": (".state", "Smoother"),
    "StateMachine": (".state", "StateMachine"),
    "StateUpdate": (".state", "StateUpdate"),
    "SessionSnapshot": (".study_session", "SessionSnapshot"),
    "StudySession": (".study_session", "StudySession"),
    "StudySessionError": (".study_session", "StudySessionError"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} không có thuộc tính {name!r}")
    mod_name, attr_name = target
    module = importlib.import_module(mod_name, __name__)
    return getattr(module, attr_name)
