"""Quản lý đăng ký khuôn mặt 5 bước và tự suy / lưu bền vững ngưỡng cosine."""

from __future__ import annotations

import json
import math
import os
import uuid
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

from ..core.atomic_io import write_json_atomic
from ..vision.faces import (
    FaceStoreError,
    average_embedding,
    cosine_similarity,
    validate_threshold,
)

#: Năm bước hướng dẫn đăng ký khuôn mặt (nguồn sự thật duy nhất cho cả domain & web).
ENROLL_STEPS: tuple[str, ...] = (
    "Nhìn thẳng",
    "Quay sang phải",
    "Quay sang trái",
    "Ngẩng lên",
    "Cúi xuống",
)
DEFAULT_STEPS = ENROLL_STEPS

DEFAULT_STEP_S = 1.5
DEFAULT_SAMPLES_NEEDED = 3

AUTO_THRESHOLD_MARGIN = 0.15
AUTO_THRESHOLD_MIN = 0.30
AUTO_THRESHOLD_MAX = 0.95

THRESHOLD_FILENAME = "face_threshold.json"
THRESHOLD_VERSION = 1

STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_CANCELLED = "cancelled"
STATE_FAILED = "failed"


class PeopleServiceError(ValueError):
    """Lỗi nghiệp vụ người học; tầng HTTP trả mã 400 kèm thông điệp tiếng Việt."""


def derive_threshold(samples: Sequence[np.ndarray]) -> float | None:
    """Suy ngưỡng cosine từ ít nhất 3 embedding mẫu của cùng một người."""
    vectors = [np.asarray(sample, dtype=np.float64).reshape(-1) for sample in samples]
    if len(vectors) < 3:
        return None
    dim = vectors[0].size
    if dim == 0 or any(vector.size != dim for vector in vectors):
        return None
    lowest: float | None = None
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            try:
                score = cosine_similarity(vectors[i], vectors[j])
            except (TypeError, ValueError):
                return None
            if lowest is None or score < lowest:
                lowest = score
    if lowest is None:
        return None
    derived = max(
        AUTO_THRESHOLD_MIN, min(AUTO_THRESHOLD_MAX, lowest - AUTO_THRESHOLD_MARGIN)
    )
    return round(float(derived), 2)


def parse_threshold_payload(payload: Any) -> float:
    """Đọc nội dung tệp phụ ``face_threshold.json``; trả ngưỡng hoặc ném ``ValueError``."""
    if not isinstance(payload, dict):
        raise ValueError("nội dung phải là một đối tượng JSON")
    version = payload.get("version")
    if version != THRESHOLD_VERSION:
        raise ValueError(
            f"phiên bản {version!r} không được hỗ trợ (chỉ đọc được phiên bản {THRESHOLD_VERSION})"
        )
    raw = payload.get("threshold")
    if isinstance(raw, bool):
        raise ValueError("ngưỡng phải là số thực, không phải bool")
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"ngưỡng không phải số thực ({raw!r})") from exc
    if not math.isfinite(value):
        raise ValueError(f"ngưỡng không hữu hạn ({value!r})")
    if not (-1.0 <= value <= 1.0):
        raise ValueError(
            f"ngưỡng {value!r} nằm ngoài [-1.0, 1.0] (miền giá trị của cosine)"
        )
    return value


def build_threshold_payload(threshold: float, moment: float) -> dict[str, Any]:
    return {
        "version": THRESHOLD_VERSION,
        "threshold": float(threshold),
        "updated_at": float(moment),
    }


def write_threshold_file(path: Path, threshold: float, moment: float) -> None:
    write_json_atomic(path, build_threshold_payload(threshold, moment))


def default_threshold_path(store: Any) -> Path | None:
    data_dir = getattr(store, "data_dir", None)
    if data_dir is None:
        return None
    try:
        return Path(data_dir) / THRESHOLD_FILENAME
    except (TypeError, ValueError):
        return None


def validate_steps(steps: Sequence[str] | None) -> tuple[str, ...]:
    if steps is None:
        return ENROLL_STEPS
    cleaned: list[str] = []
    for index, step in enumerate(steps):
        if not isinstance(step, str) or not step.strip():
            raise ValueError(f"Bước đăng ký thứ {index + 1} phải là chuỗi không rỗng.")
        cleaned.append(step)
    if not cleaned:
        raise ValueError("Danh sách bước đăng ký không được rỗng.")
    return tuple(cleaned)


class ThresholdManager:
    """Quản lý ngưỡng nhận diện cấu hình tay và ngưỡng tự suy bền vững trên đĩa."""

    def __init__(
        self,
        *,
        manual_threshold: float | None,
        store: Any,
        threshold_path: str | os.PathLike[str] | None,
        clock: Callable[[], float],
        log: Any,
    ) -> None:
        self.manual: float | None = (
            validate_threshold(manual_threshold) if manual_threshold is not None else None
        )
        self.auto: float | None = None
        self._clock = clock
        self._log = log

        derived_path = default_threshold_path(store)
        if threshold_path is not None:
            try:
                derived_path = Path(threshold_path)
            except (TypeError, ValueError):
                derived_path = None
        self.path: Path | None = derived_path
        self.load()

    @property
    def effective(self) -> float | None:
        return self.manual if self.manual is not None else self.auto

    def load(self) -> None:
        if self.manual is not None or self.path is None:
            return
        try:
            if not self.path.exists():
                return
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            value = parse_threshold_payload(payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._log.warning(
                "Bỏ qua ngưỡng nhận diện đã lưu ở '%s': %s. Chạy tiếp không "
                "có ngưỡng tự suy cho tới lần đăng ký kế tiếp.",
                self.path,
                exc,
            )
            return
        self.auto = value
        self._log.info(
            "Đã nạp lại ngưỡng nhận diện khuôn mặt %.2f từ '%s'.", value, self.path
        )

    def update_from_samples(self, samples: Sequence[np.ndarray]) -> None:
        if self.manual is not None:
            return
        derived = derive_threshold(samples)
        if derived is None:
            self._log.warning(
                "Chưa tự suy được ngưỡng nhận diện: cần ít nhất 3 mẫu hợp lệ "
                "cùng số chiều (hiện có %d). Mọi quan sát vẫn là UNKNOWN.",
                len(samples),
            )
            return
        self.auto = derived
        if self.path is not None:
            try:
                write_threshold_file(self.path, derived, self._clock())
            except OSError as exc:
                self._log.warning(
                    "Không lưu được ngưỡng nhận diện vào '%s': %s. Ngưỡng vẫn "
                    "dùng được trong phiên này nhưng sẽ mất khi khởi động lại.",
                    self.path,
                    exc,
                )
            else:
                self._log.info("Đã lưu ngưỡng nhận diện khuôn mặt vào '%s'.", self.path)

        if derived <= AUTO_THRESHOLD_MIN:
            self._log.warning(
                "Ngưỡng nhận diện tự suy chỉ %.2f (chạm sàn %.2f): các mẫu "
                "đăng ký không đồng ý với nhau (mức giống thấp nhất giữa hai "
                "mẫu cùng người rất thấp). Ngưỡng này lỏng — người khác có "
                "thể được nhận thành chủ. Hãy đăng ký lại ở nơi đủ sáng, "
                "nhìn thẳng vào camera, không che mặt.",
                derived,
                AUTO_THRESHOLD_MIN,
            )
        self._log.info(
            "Đã tự suy ngưỡng nhận diện khuôn mặt %.2f từ dữ liệu đăng ký "
            "(%d mẫu, khoảng cách an toàn %.2f); lưu lại cho lần khởi động kế tiếp.",
            derived,
            len(samples),
            AUTO_THRESHOLD_MARGIN,
        )


class EnrollmentTracker:
    """Máy trạng thái phiên đăng ký 5 bước (được bảo vệ bởi khoá của PeopleService)."""

    def __init__(
        self,
        *,
        store: Any,
        thresholds: ThresholdManager,
        steps: Sequence[str] | None,
        step_s: float,
        samples_needed: int,
        clock: Callable[[], float],
        log: Any,
    ) -> None:
        self.steps = validate_steps(steps)
        step_value = float(step_s)
        if not math.isfinite(step_value) or step_value <= 0.0:
            raise ValueError(
                f"Thời gian mỗi bước đăng ký phải là số dương hữu hạn, nhận được {step_s!r}."
            )
        self.step_s = step_value
        samples_value = int(samples_needed)
        if samples_value < 1:
            raise ValueError(
                f"Số mẫu cần thiết phải >= 1, nhận được {samples_needed!r}."
            )
        self.samples_needed = samples_value
        self._store = store
        self._thresholds = thresholds
        self._clock = clock
        self._log = log
        self.records: dict[str, dict[str, Any]] = {}

    def start(self, name: str) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            raise PeopleServiceError("Tên người đăng ký không được để trống.")
        clean_name = name.strip()
        enroll_id = uuid.uuid4().hex
        moment = self._clock()
        for existing in self.records.values():
            if existing["state"] == STATE_RUNNING:
                existing["state"] = STATE_CANCELLED
                existing["error"] = "Bị thay bằng phiên đăng ký mới."
        self.records[enroll_id] = {
            "name": clean_name,
            "state": STATE_RUNNING,
            "started_at": moment,
            "step_index": 0,
            "sampled_steps": set(),
            "samples": [],
            "error": None,
        }
        self._log.info("Bắt đầu đăng ký khuôn mặt cho '%s'.", clean_name)
        return {"enroll_id": enroll_id, "steps": list(self.steps)}

    def status(self, enroll_id: str) -> dict[str, Any]:
        record = self.records.get(enroll_id)
        if record is None:
            raise PeopleServiceError(f"Không tìm thấy phiên đăng ký '{enroll_id}'.")
        self._expire(record, self._clock())
        step_index = max(0, min(int(record.get("step_index", 0)), len(self.steps) - 1))
        return {
            "state": record["state"],
            "step_index": step_index,
            "step_name": self.steps[step_index],
            "samples": len(record["samples"]),
            "samples_needed": self.samples_needed,
            "error": record.get("error"),
        }

    def cancel(self, enroll_id: str) -> bool:
        record = self.records.get(str(enroll_id))
        if record is None or record["state"] != STATE_RUNNING:
            return False
        record["state"] = STATE_CANCELLED
        record["error"] = "Đã huỷ theo yêu cầu; không ghi danh tính."
        record["samples"] = []
        self._log.info("Đã huỷ đăng ký khuôn mặt cho '%s'.", record["name"])
        return True

    def running_record(self) -> dict[str, Any] | None:
        for record in self.records.values():
            if record["state"] == STATE_RUNNING:
                return record
        return None

    def collect_sample(self, vector: np.ndarray | None, moment: float) -> None:
        record = self.running_record()
        if record is None:
            return
        elapsed = max(0.0, moment - record["started_at"])
        step_index = min(int(elapsed // self.step_s), len(self.steps) - 1)
        record["step_index"] = step_index
        if vector is not None and len(record["samples"]) < self.samples_needed:
            if step_index not in record["sampled_steps"]:
                record["sampled_steps"].add(step_index)
                record["samples"].append(vector)
        if len(record["samples"]) >= self.samples_needed:
            self._finish_success(record)
        else:
            self._expire(record, moment)

    def _expire(self, record: dict[str, Any], moment: float) -> None:
        if record["state"] != STATE_RUNNING:
            return
        total = len(self.steps) * self.step_s
        if moment - record["started_at"] < total:
            return
        had_samples = len(record["samples"])
        record["state"] = STATE_FAILED
        record["error"] = (
            f"Không đủ mẫu hợp lệ ({had_samples}/{self.samples_needed}) sau {total:g} giây. "
            "Không ghi danh tính nửa vời; hãy đăng ký lại khi đủ sáng và nhìn thẳng vào camera."
        )
        record["samples"] = []
        self._log.warning(
            "Đăng ký '%s' thất bại: chỉ có %d/%d mẫu.",
            record["name"],
            had_samples,
            self.samples_needed,
        )

    def _finish_success(self, record: dict[str, Any]) -> None:
        merged = average_embedding(record["samples"])
        if merged is None:
            record["state"] = STATE_FAILED
            record["error"] = (
                "Các mẫu thu được không đủ khác nhau để tạo đặc trưng ổn định; không ghi danh tính."
            )
            record["samples"] = []
            return
        try:
            self._store.add(record["name"], merged, enrolled_at=self._clock())
        except (FaceStoreError, ValueError) as exc:
            record["state"] = STATE_FAILED
            record["error"] = f"Không lưu được danh tính: {exc}"
            record["samples"] = []
            self._log.error("Không lưu được khuôn mặt '%s': %s", record["name"], exc)
            return
        record["state"] = STATE_DONE
        record["error"] = None
        self._thresholds.update_from_samples(record["samples"])
        self._log.info(
            "Đã đăng ký khuôn mặt '%s' từ %d mẫu ở %d bước.",
            record["name"],
            len(record["samples"]),
            len(record["sampled_steps"]),
        )
