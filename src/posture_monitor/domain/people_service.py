"""Dịch vụ điều phối người học: nhận diện chạy nền, đăng ký 5 bước, tín hiệu & lịch học."""

from __future__ import annotations

import math
import os
import threading
import time
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from ..core.logging_setup import get_logger
from ..vision.faces import (
    FaceStoreError,
    best_disqualified,
    cosine_similarity,
    normalise_embedding,
)
from .enrollment import (
    AUTO_THRESHOLD_MARGIN,
    AUTO_THRESHOLD_MAX,
    AUTO_THRESHOLD_MIN,
    DEFAULT_SAMPLES_NEEDED,
    DEFAULT_STEP_S,
    DEFAULT_STEPS,
    ENROLL_STEPS,
    STATE_CANCELLED,
    STATE_DONE,
    STATE_FAILED,
    STATE_RUNNING,
    THRESHOLD_FILENAME,
    THRESHOLD_VERSION,
    EnrollmentTracker,
    PeopleServiceError,
    ThresholdManager,
    build_threshold_payload,
    default_threshold_path,
    derive_threshold,
    parse_threshold_payload,
    write_threshold_file,
)
from .schedule import (
    ScheduleConfig,
    ScheduleError,
    parse_schedule_mapping,
    schedule_to_dict,
)
from .signal_board import (
    FACE_BOX_MAX_AGE_S,
    IDENTITY_AGE_LIMIT_S,
    IDENTITY_MATCH,
    IDENTITY_MISMATCH,
    IDENTITY_UNKNOWN,
    PHONE_AGE_LIMIT_S,
    PHONE_STATE_NONE,
    PHONE_STATE_USE,
    PRESENCE_AGE_LIMIT_S,
    STATE_NO_DATA,
    SignalBoard,
)

_LOGGER = get_logger("posture_monitor.domain.people_service")

#: Sentinel báo lượt này bị bỏ qua (cổng nhịp ``interval_s`` hoặc model ném lỗi).
OBSERVATION_SKIPPED = object()


def _coerce_embedding(value: Any) -> np.ndarray | None:
    """Chuẩn hoá embedding do processor trả về; ``None`` nếu không dùng được."""
    if value is None:
        return None
    try:
        return normalise_embedding(value)
    except (TypeError, ValueError, OverflowError):
        return None


class PeopleService:
    """Điều phối kho khuôn mặt, phiên đăng ký 5 bước, lựa chọn người học, tín hiệu và lịch học."""

    def __init__(
        self,
        store: Any,
        recognizer: Any,
        *,
        clock: Callable[[], float] | None = None,
        threshold: float | None = None,
        steps: Sequence[str] | None = None,
        step_s: float = DEFAULT_STEP_S,
        samples_needed: int = DEFAULT_SAMPLES_NEEDED,
        schedule: ScheduleConfig | None = None,
        threshold_path: str | os.PathLike[str] | None = None,
        logger: Any = None,
    ) -> None:
        self._store = store
        self._recognizer = recognizer
        self._clock = clock or time.monotonic
        self._log = logger if logger is not None else _LOGGER

        self._thresholds = ThresholdManager(
            manual_threshold=threshold,
            store=self._store,
            threshold_path=threshold_path,
            clock=self._clock,
            log=self._log,
        )
        self._enrollment = EnrollmentTracker(
            store=self._store,
            thresholds=self._thresholds,
            steps=steps,
            step_s=step_s,
            samples_needed=samples_needed,
            clock=self._clock,
            log=self._log,
        )
        self._signals = SignalBoard(self._clock)

        self._lock = threading.RLock()
        self._selected: str | None = None
        # Giữ nguyên tham chiếu ScheduleConfig được truyền vào để put_schedule sửa tại chỗ.
        self._schedule: ScheduleConfig = (
            schedule if schedule is not None else ScheduleConfig()
        )

        self._cond = threading.Condition(threading.Lock())
        self._pending: tuple[Any, float] | None = None
        self._worker: threading.Thread | None = None
        self._stop = False
        self._processor: Callable[[Any], Any] | None = None
        self._processor_error: str | None = None
        self._apply_error: str | None = None

    # -- processor & worker chạy nền ---------------------------------------
    def set_processor(self, processor: Callable[[Any], Any] | None) -> None:
        with self._lock:
            self._processor = processor

    def _default_processor(self, frame: Any) -> Any:
        return self._recognizer.embed_largest(frame)

    def _current_processor(self) -> Callable[[Any], Any]:
        with self._lock:
            processor = self._processor
        return processor or self._default_processor

    def _ensure_worker(self) -> None:
        with self._lock:
            worker = self._worker
            if worker is not None and worker.is_alive():
                return
            if self._stop:
                return
            if worker is not None:
                self._log.warning(
                    "Luồng nhận diện khuôn mặt đã dừng; khởi động lại luồng mới."
                )
            thread = threading.Thread(
                target=self._worker_loop,
                name="people-service-worker",
                daemon=True,
            )
            self._worker = thread
            thread.start()

    def close(self) -> None:
        with self._lock:
            self._stop = True
        with self._cond:
            self._cond.notify_all()
        worker = self._worker
        if worker is not None:
            worker.join(timeout=2.0)

    def _worker_loop(self) -> None:
        while True:
            with self._cond:
                while self._pending is None and not self._stop:
                    self._cond.wait()
                if self._stop and self._pending is None:
                    return
                frame, now = self._pending
                self._pending = None
            try:
                self.process_frame(frame, now=now)
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                if message != self._apply_error:
                    self._apply_error = message
                    self._log.warning(
                        "Không áp dụng được kết quả nhận diện khuôn mặt: %s", exc
                    )
            else:
                self._apply_error = None

    # -- quan sát khung & cập nhật tín hiệu ---------------------------------
    def observe(self, frame: Any, now: float) -> None:
        moment = float(now)
        with self._cond:
            self._pending = (frame, moment)
            self._cond.notify()
        self._ensure_worker()

    def process_frame(self, frame: Any, now: float | None = None) -> None:
        try:
            moment = self._clock() if now is None else float(now)
        except (TypeError, ValueError) as exc:
            raise PeopleServiceError(
                f"Mốc thời gian của khung không hợp lệ: {now!r}."
            ) from exc

        processor = self._current_processor()
        try:
            raw = processor(frame)
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if message != self._processor_error:
                self._processor_error = message
                self._log.warning(
                    "Không xử lý được khung nhận diện khuôn mặt: %s", exc
                )
            raw = OBSERVATION_SKIPPED
        else:
            self._processor_error = None

        if raw is OBSERVATION_SKIPPED:
            with self._lock:
                self._enrollment.collect_sample(None, moment)
            return
        self._apply_observation(raw, moment)

    def update_signals(
        self,
        presence: str | None = None,
        phone: str | None = None,
        now: float | None = None,
    ) -> None:
        moment = self._clock() if now is None else float(now)
        with self._lock:
            self._signals.update_presence_phone(
                presence=presence, phone=phone, moment=moment
            )

    def note_phone(self, state: str, now: float | None = None) -> None:
        moment = self._clock() if now is None else float(now)
        with self._lock:
            self._signals.update_presence_phone(phone=state, moment=moment)

    def note_face_box(self, box: Any, now: float | None = None) -> None:
        try:
            values = tuple(float(value) for value in box)
        except (TypeError, ValueError, OverflowError):
            return
        if len(values) != 4 or not all(math.isfinite(v) for v in values):
            return
        try:
            moment = float(self._clock() if now is None else now)
        except (TypeError, ValueError, OverflowError):
            return
        if not math.isfinite(moment):
            return
        with self._lock:
            self._signals.set_face_box(
                (values[0], values[1], values[2], values[3]), moment
            )

    def latest_face_box(
        self, now: float | None = None
    ) -> tuple[float, float, float, float] | None:
        try:
            moment = float(self._clock() if now is None else now)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(moment):
            return None
        with self._lock:
            return self._signals.latest_face_box(moment)

    def signals(self) -> dict:
        with self._lock:
            return self._signals.snapshot()

    # -- so khớp danh tính --------------------------------------------------
    def _apply_observation(self, raw: Any, moment: float) -> None:
        vector = _coerce_embedding(raw)
        with self._lock:
            state, name, reason = self._classify(vector)
            self._signals.set_identity(
                state=state, name=name, reason=reason, moment=self._clock()
            )
            if vector is None:
                self._signals.clear_face_box()
            self._enrollment.collect_sample(vector, moment)

    def _classify(self, vector: np.ndarray | None) -> tuple[str, str | None, str]:
        if vector is None:
            return (
                IDENTITY_UNKNOWN,
                None,
                "Không thấy khuôn mặt dùng được trong khung.",
            )
        effective = self._thresholds.effective
        if effective is None:
            return (
                IDENTITY_UNKNOWN,
                None,
                "Chưa có ngưỡng nhận diện khuôn mặt (match_threshold là null); "
                "không kết luận danh tính.",
            )
        try:
            entries = self._store.pairs()
        except FaceStoreError as exc:
            return IDENTITY_UNKNOWN, None, f"Không đọc được kho khuôn mặt: {exc}"
        if not entries:
            return (
                IDENTITY_UNKNOWN,
                None,
                "Chưa có ai được đăng ký trên thiết bị này.",
            )

        best_name: str | None = None
        best_score: float | None = None
        scores: dict[str, float] = {}
        for name, registered in entries:
            try:
                score = cosine_similarity(vector, registered)
            except (TypeError, ValueError):
                continue
            scores[name] = score
            if best_score is None or score > best_score:
                best_name, best_score = name, score

        if not scores or best_score is None:
            return IDENTITY_UNKNOWN, None, "Dữ liệu đã đăng ký không so sánh được."

        selected = self._selected
        if selected is not None:
            selected_score = scores.get(selected)
            if selected_score is not None and not best_disqualified(
                selected_score, effective
            ):
                return IDENTITY_MATCH, selected, ""
            return (
                IDENTITY_MISMATCH,
                None,
                "Khuôn mặt không phải người đang được chọn.",
            )
        if best_disqualified(best_score, effective):
            return (
                IDENTITY_MISMATCH,
                None,
                "Khuôn mặt không khớp ai trong kho (điểm dưới ngưỡng).",
            )
        return IDENTITY_MATCH, best_name, ""

    # -- đăng ký khuôn mặt --------------------------------------------------
    def start_enroll(self, name: str) -> dict:
        with self._lock:
            return self._enrollment.start(name)

    def enroll_status(self, enroll_id: str) -> dict:
        with self._lock:
            return self._enrollment.status(enroll_id)

    def cancel_enroll(self, enroll_id: str) -> bool:
        with self._lock:
            return self._enrollment.cancel(enroll_id)

    def is_enrolling(self) -> bool:
        with self._lock:
            return self._enrollment.running_record() is not None

    # -- uỷ quyền thuộc tính nội bộ cho kiểm thử hộp trắng ------------------
    @property
    def _enrollments(self) -> dict[str, dict[str, Any]]:
        return self._enrollment.records

    @property
    def _auto_threshold(self) -> float | None:
        return self._thresholds.auto

    @property
    def _identity(self) -> dict[str, Any]:
        return self._signals.identity

    @_identity.setter
    def _identity(self, value: dict[str, Any]) -> None:
        self._signals.identity = value

    def _collect_sample(self, vector: np.ndarray | None, moment: float) -> None:
        self._enrollment.collect_sample(vector, moment)

    # -- quản lý người học --------------------------------------------------
    def list_people(self) -> list[dict]:
        try:
            people = self._store.load()
        except FaceStoreError as exc:
            raise PeopleServiceError(
                f"Không đọc được danh sách người đã đăng ký: {exc}"
            ) from exc
        return [
            {
                "id": person.name,
                "name": person.name,
                "created_ts": float(person.enrolled_at),
            }
            for person in people
        ]

    def delete_person(self, person_id: str) -> bool:
        try:
            removed = self._store.remove(person_id)
        except FaceStoreError as exc:
            raise PeopleServiceError(
                f"Không xoá được người '{person_id}': {exc}"
            ) from exc
        if not removed:
            return False
        with self._lock:
            if self._selected is not None and self._selected == str(person_id).strip():
                self._selected = None
        return True

    def select_person(self, person_id: str | None) -> bool:
        if person_id is None:
            with self._lock:
                self._selected = None
            return True
        wanted = str(person_id).strip()
        if not wanted:
            return False
        try:
            exists = self._store.get(wanted) is not None
        except FaceStoreError as exc:
            raise PeopleServiceError(
                f"Không đọc được kho khuôn mặt: {exc}"
            ) from exc
        if not exists:
            return False
        with self._lock:
            self._selected = wanted
        return True

    def selected_person(self) -> str | None:
        with self._lock:
            return self._selected

    # -- khung giờ học trong bộ nhớ -----------------------------------------
    def get_schedule(self) -> dict:
        with self._lock:
            return schedule_to_dict(self._schedule)

    def put_schedule(self, payload: Mapping[str, Any]) -> dict:
        if not isinstance(payload, Mapping):
            raise PeopleServiceError("Cấu hình giờ học phải là một đối tượng JSON.")
        try:
            schedule = parse_schedule_mapping(
                payload, prefix="", reject_unknown_keys=True
            )
        except ScheduleError as exc:
            raise PeopleServiceError(str(exc)) from exc
        with self._lock:
            self._schedule.kinds = schedule.kinds
            self._schedule.windows = schedule.windows
            self._schedule.enabled = schedule.enabled
            result = schedule_to_dict(self._schedule)
        self._log.info(
            "Đã cập nhật giờ học trong bộ nhớ: enabled=%s, %d khung giờ.",
            schedule.enabled,
            len(schedule.windows),
        )
        return result


__all__ = [
    "AUTO_THRESHOLD_MARGIN",
    "AUTO_THRESHOLD_MAX",
    "AUTO_THRESHOLD_MIN",
    "DEFAULT_SAMPLES_NEEDED",
    "DEFAULT_STEPS",
    "DEFAULT_STEP_S",
    "ENROLL_STEPS",
    "FACE_BOX_MAX_AGE_S",
    "IDENTITY_AGE_LIMIT_S",
    "IDENTITY_MATCH",
    "IDENTITY_MISMATCH",
    "IDENTITY_UNKNOWN",
    "OBSERVATION_SKIPPED",
    "PHONE_AGE_LIMIT_S",
    "PHONE_STATE_NONE",
    "PHONE_STATE_USE",
    "PRESENCE_AGE_LIMIT_S",
    "PeopleService",
    "PeopleServiceError",
    "STATE_CANCELLED",
    "STATE_DONE",
    "STATE_FAILED",
    "STATE_NO_DATA",
    "STATE_RUNNING",
    "THRESHOLD_FILENAME",
    "THRESHOLD_VERSION",
    "_coerce_embedding",
    "build_threshold_payload",
    "default_threshold_path",
    "derive_threshold",
    "parse_threshold_payload",
    "write_threshold_file",
]
