"""Đăng ký người bằng khuôn mặt và chọn người đang học.

Module này là **lớp dịch vụ** đứng trên :mod:`posture_monitor.faces`: nó giữ
trạng thái của một phiên đăng ký nhiều bước, quyết định kết quả danh tính
(``MATCH`` / ``MISMATCH`` / ``UNKNOWN``) và cung cấp tín hiệu có tuổi cho web
(spec V3 §5.13, §5.16). Nó **không** đọc camera, **không** đọc config toàn cục
và **không** giữ ảnh trên đĩa.

Bốn quyết định thiết kế quan trọng
----------------------------------

**1. ``id`` của một người chính là tên của họ.** Kho JSON của ``faces.py``
khoá bản ghi theo tên (``FaceStore.get(name)``, ``FaceStore.remove(name)``),
nên dùng một mã số riêng sẽ tạo ra hai nguồn sự thật phải đồng bộ tay. Vì
vậy ``list_people()`` trả ``{"id": <tên>, "name": <tên>, ...}`` và
``delete_person(id)``/``select_person(id)`` nhận đúng tên đó. Hệ quả cần biết:
đổi tên người = xoá + đăng ký lại.

**2. ``observe()`` không bao giờ làm việc nặng.** Vòng lặp camera gọi nó mỗi
khung (5–6 FPS trên Pi 4), trong khi cả đường ống YuNet + SFace tốn **86,1
ms/lượt** (spec §4.2, ĐÃ ĐO). Chặn ở đây là vi phạm ngân sách khung. Vì vậy
``observe()`` chỉ **cất tham chiếu** khung mới nhất (khung sau ghi đè khung
trước, không copy) rồi trả về ngay. Việc nặng chạy trên **một luồng worker
nội bộ**, gọi tới ``processor`` (mặc định là ``recognizer.embed_largest``,
thay được bằng :meth:`PeopleService.set_processor` để test hoặc để dùng
worker bên ngoài).

**3. Tín hiệu luôn kèm tuổi.** ``signals()`` trả ``age_s`` và ``fresh`` cho
từng tín hiệu. ``fresh is False`` nghĩa là **hết dữ liệu**, không phải "vẫn
có mặt"/"vẫn đang dùng điện thoại": UI phải nói "chưa có dữ liệu mới" thay vì
trình bày kết luận cũ như mới (spec §5.16).

**4. ``UNKNOWN`` không bao giờ được suy thành "người lạ".** Che mặt, ngược
sáng, gallery rỗng hay chưa có ngưỡng đều là ``UNKNOWN``; chỉ khi so được với
gallery và mọi người đều dưới ngưỡng mới là ``MISMATCH`` (spec §3.4: báo nhầm
vì không nhận ra là lỗi nghiêm trọng hơn bỏ sót).

Quyền riêng tư (spec §5.13.1)
-----------------------------

Chỉ embedding được giữ lại. Khung hình chỉ tồn tại trong RAM đúng một lời gọi
``processor``; module không gọi ``cv2.imwrite``, không tạo tệp ảnh, không trả
vector ra ngoài (``list_people()``/``signals()`` không có khoá nào chứa
vector). Khi đăng ký thiếu mẫu hoặc bị huỷ thì **không ghi gì**.
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from typing import Any, Callable, Sequence

import numpy as np

from .faces import (
    FaceStoreError,
    average_embedding,
    best_disqualified,
    cosine_similarity,
    normalise_embedding,
    validate_threshold,
)
from .logging_setup import get_logger

_LOGGER = get_logger(__name__)

#: Năm câu hướng dẫn mặc định, đúng nguyên văn spec V3 §5.13.
DEFAULT_STEPS: tuple[str, ...] = (
    "Nhìn thẳng",
    "Quay sang phải",
    "Quay sang trái",
    "Ngẩng lên",
    "Cúi xuống",
)

#: Thời gian mỗi tư thế (giây); spec §5.13: 1,5 s × 5 tư thế ≈ 7,5 s.
DEFAULT_STEP_S = 1.5

#: Số embedding hợp lệ tối thiểu để ghi danh tính; spec §5.13: 3.
DEFAULT_SAMPLES_NEEDED = 3

#: Trạng thái của một phiên đăng ký.
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_CANCELLED = "cancelled"
STATE_FAILED = "failed"

#: Ba kết quả danh tính (spec §5.13) — không có kết quả thứ tư.
IDENTITY_MATCH = "MATCH"
IDENTITY_MISMATCH = "MISMATCH"
IDENTITY_UNKNOWN = "UNKNOWN"

#: Trạng thái "chưa từng có dữ liệu" cho presence/phone.
STATE_NO_DATA = "chua_co_du_lieu"

#: Tuổi tối đa mặc định của từng tín hiệu trước khi bị coi là cũ.
#:
#: Presence/phone do vòng lặp cập nhật mỗi khung nên 3 s là rộng rãi; danh
#: tính chỉ chạy mỗi ~2 s (spec §4.2) nên cần cửa sổ dài hơn. Đây là lựa chọn
#: của lớp dịch vụ, không phải số đo — người gọi vẫn phải đọc ``fresh`` chứ
#: không dựa vào việc "3 s là đúng".
PRESENCE_AGE_LIMIT_S = 3.0
PHONE_AGE_LIMIT_S = 3.0
IDENTITY_AGE_LIMIT_S = 10.0


class PeopleServiceError(ValueError):
    """Lỗi nghiệp vụ; route trả 400 kèm thông điệp tiếng Việt."""


def _coerce_embedding(value: Any) -> np.ndarray | None:
    """Chuẩn hoá embedding do processor trả về; ``None`` nếu không dùng được."""
    if value is None:
        return None
    try:
        return normalise_embedding(value)
    except (TypeError, ValueError):
        return None


def _as_steps(steps: Sequence[str] | None) -> tuple[str, ...]:
    """Kiểm tra danh sách bước đăng ký."""
    if steps is None:
        return DEFAULT_STEPS
    cleaned: list[str] = []
    for index, step in enumerate(steps):
        if not isinstance(step, str) or not step.strip():
            raise ValueError(
                f"Bước đăng ký thứ {index + 1} phải là chuỗi không rỗng."
            )
        cleaned.append(step)
    if not cleaned:
        raise ValueError("Danh sách bước đăng ký không được rỗng.")
    return tuple(cleaned)


class PeopleService:
    """Phiên đăng ký khuôn mặt, lựa chọn người học và tín hiệu danh tính.

    Args:
        store: :class:`posture_monitor.faces.FaceStore` thật hoặc cùng giao
            diện. Khoá bản ghi là tên người, nên ``id`` ở đây cũng là tên.
        recognizer: đối tượng cung cấp ``embed_largest(image)`` trả embedding
            128 chiều hoặc ``None`` (thường là
            :class:`posture_monitor.faces.FaceRecognizer`). Test truyền bản
            giả; không cần mô hình.
        clock: hàm trả mốc thời gian (giây). Mặc định ``time.monotonic``.
            Test truyền đồng hồ giả để không cần ``sleep``.
        threshold: ngưỡng cosine để coi là ``MATCH``. ``None`` (giá trị của
            ``match_threshold: null`` khi chưa đo) **tắt** phần kết luận danh
            tính: mọi quan sát đều ``UNKNOWN`` — không dùng ngưỡng mặc định.
        steps: năm câu hướng dẫn; mặc định :data:`DEFAULT_STEPS`.
        step_s: thời gian mỗi tư thế.
        samples_needed: số embedding hợp lệ tối thiểu để ghi.
        logger: logger dùng riêng (mặc định logger của module).

    Raises:
        ValueError: tham số cấu hình không dùng được (bước rỗng, ``step_s``
            không dương, ``samples_needed`` < 1, ngưỡng ngoài ``[-1, 1]``).
    """

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
        logger: Any = None,
    ) -> None:
        self._store = store
        self._recognizer = recognizer
        self._clock = clock or time.monotonic
        self._log = logger if logger is not None else _LOGGER

        # Ngưỡng None là hợp lệ (tính năng tắt); ngưỡng có giá trị thì phải
        # đúng ngay từ đầu, không để lỗi cấu hình lộ ra giữa vòng lặp.
        self._threshold: float | None = None
        if threshold is not None:
            self._threshold = validate_threshold(threshold)

        self._steps = _as_steps(steps)
        step_value = float(step_s)
        if not math.isfinite(step_value) or step_value <= 0.0:
            raise ValueError(
                f"Thời gian mỗi bước đăng ký phải là số dương hữu hạn, "
                f"nhận được {step_s!r}."
            )
        self._step_s = step_value
        samples_value = int(samples_needed)
        if samples_value < 1:
            raise ValueError(
                f"Số mẫu cần thiết phải >= 1, nhận được {samples_needed!r}."
            )
        self._samples_needed = samples_value

        self._lock = threading.RLock()
        self._enrollments: dict[str, dict[str, Any]] = {}
        self._selected: str | None = None

        # Tín hiệu đã cập nhật gần nhất; mỗi bản ghi có "updated_at".
        self._presence: dict[str, Any] = {"state": STATE_NO_DATA, "updated_at": None}
        self._phone: dict[str, Any] = {"state": STATE_NO_DATA, "updated_at": None}
        self._identity: dict[str, Any] = {
            "state": IDENTITY_UNKNOWN,
            "name": None,
            "reason": "Chưa có dữ liệu nhận diện.",
            "updated_at": None,
        }

        # Khe khung mới nhất cho worker: một tham chiếu, không copy.
        self._cond = threading.Condition(threading.Lock())
        self._pending: tuple[Any, float] | None = None
        self._worker: threading.Thread | None = None
        self._stop = False
        self._processor: Callable[[Any], Any] | None = None

    # ------------------------------------------------------------------
    # processor / luồng worker
    # ------------------------------------------------------------------
    def set_processor(
        self, processor: Callable[[Any], Any] | None
    ) -> None:
        """Đặt hàm nặng thay cho ``recognizer.embed_largest``.

        ``processor(frame)`` phải trả embedding hoặc ``None``. Đây là điểm
        tiêm để test đo rằng :meth:`observe` không chặn, và để tầng trên dùng
        worker riêng nếu muốn. Truyền ``None`` để quay lại mặc định.
        """
        with self._lock:
            self._processor = processor

    def _default_processor(self, frame: Any) -> Any:
        return self._recognizer.embed_largest(frame)

    def _ensure_worker(self) -> None:
        if self._worker is not None:
            return
        with self._lock:
            if self._worker is not None or self._stop:
                return
            thread = threading.Thread(
                target=self._worker_loop,
                name="people-service-worker",
                daemon=True,
            )
            self._worker = thread
            thread.start()

    def close(self) -> None:
        """Dừng luồng worker (gọi khi tắt ứng dụng hoặc trong test)."""
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
            self.process_frame(frame, now=now)

    def _current_processor(self) -> Callable[[Any], Any]:
        with self._lock:
            processor = self._processor
        return processor or self._default_processor

    # ------------------------------------------------------------------
    # vòng lặp chính
    # ------------------------------------------------------------------
    def observe(self, frame: Any, now: float) -> None:
        """Nhận khung mới nhất từ vòng lặp camera; **trả về ngay**.

        Chỉ cất tham chiếu (không copy) và đánh thức worker. Khung chưa kịp
        xử lý bị khung sau ghi đè, đúng tinh thần "luôn dùng khung mới nhất".
        Không gọi detect/embedding ở đây: cả đường ống tốn 86,1 ms/lượt
        (spec §4.2) và chặn ở đây là vi phạm ngân sách khung.
        """
        moment = float(now)
        with self._cond:
            self._pending = (frame, moment)
            self._cond.notify()
        self._ensure_worker()

    def process_frame(self, frame: Any, now: float | None = None) -> None:
        """Xử lý **đồng bộ** một khung (dùng trong test và worker).

        Tách khỏi :meth:`observe` để test điều khiển thời điểm một cách tất
        định, không phụ thuộc luồng. Lỗi của ``processor`` không làm sập vòng
        lặp: coi như khung đó không có khuôn mặt.
        """
        try:
            moment = self._clock() if now is None else float(now)
        except (TypeError, ValueError) as exc:
            raise PeopleServiceError(
                f"Mốc thời gian của khung không hợp lệ: {now!r}."
            ) from exc

        processor = self._current_processor()
        try:
            raw = processor(frame)
        except Exception as exc:  # noqa: BLE001 - lỗi model không được giết vòng lặp
            self._log.warning(
                "Không xử lý được khung nhận diện khuôn mặt: %s", exc
            )
            raw = None
        self._apply_observation(raw, moment)

    def update_signals(
        self,
        presence: str | None = None,
        phone: str | None = None,
        now: float | None = None,
    ) -> None:
        """Cập nhật tín hiệu presence/phone do tầng tính toán đưa vào.

        Tách khỏi :meth:`observe` để ``observe`` không phải làm gì ngoài cất
        khung. ``now`` mặc định lấy từ ``clock``; tuổi trong :meth:`signals`
        luôn tính theo ``clock``.
        """
        moment = self._clock() if now is None else float(now)
        with self._lock:
            if presence is not None:
                self._presence = {"state": str(presence), "updated_at": moment}
            if phone is not None:
                self._phone = {"state": str(phone), "updated_at": moment}

    # ------------------------------------------------------------------
    # áp dụng kết quả nhận diện
    # ------------------------------------------------------------------
    def _apply_observation(self, raw: Any, moment: float) -> None:
        vector = _coerce_embedding(raw)
        with self._lock:
            state, name, reason = self._classify(vector)
            self._identity = {
                "state": state,
                "name": name,
                "reason": reason,
                "updated_at": self._clock(),
            }
            self._collect_sample(vector, moment)

    def _classify(self, vector: np.ndarray | None) -> tuple[str, str | None, str]:
        """Trả ``(state, name, reason)`` cho một embedding (hoặc ``None``)."""
        if vector is None:
            return (
                IDENTITY_UNKNOWN,
                None,
                "Không thấy khuôn mặt dùng được trong khung.",
            )
        if self._threshold is None:
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
            return (
                IDENTITY_UNKNOWN,
                None,
                "Dữ liệu đã đăng ký không so sánh được.",
            )

        selected = self._selected
        if selected is not None:
            # Có người đang học: MATCH chỉ khi chính người đó trên ngưỡng.
            selected_score = scores.get(selected)
            if selected_score is not None and not best_disqualified(
                selected_score, self._threshold
            ):
                return IDENTITY_MATCH, selected, ""
            return (
                IDENTITY_MISMATCH,
                None,
                "Khuôn mặt không phải người đang được chọn.",
            )
        if best_disqualified(best_score, self._threshold):
            return (
                IDENTITY_MISMATCH,
                None,
                "Khuôn mặt không khớp ai trong kho (điểm dưới ngưỡng).",
            )
        return IDENTITY_MATCH, best_name, ""

    # ------------------------------------------------------------------
    # đăng ký
    # ------------------------------------------------------------------
    def start_enroll(self, name: str) -> dict:
        """Bắt đầu một phiên đăng ký; trả ``{"enroll_id", "steps"}``.

        Tên đã tồn tại được phép: đăng ký lại sẽ **cập nhật** người đó
        (``FaceStore.add`` thay bản ghi cũ). Một phiên đang chạy trước đó bị
        chuyển sang ``cancelled`` — mỗi lúc chỉ có một phiên thu mẫu, để mọi
        khung không bị chia cho hai phiên.

        Raises:
            PeopleServiceError: tên rỗng hoặc không phải chuỗi.
        """
        if not isinstance(name, str) or not name.strip():
            raise PeopleServiceError("Tên người đăng ký không được để trống.")
        clean_name = name.strip()
        enroll_id = uuid.uuid4().hex
        moment = self._clock()
        with self._lock:
            for existing in self._enrollments.values():
                if existing["state"] == STATE_RUNNING:
                    existing["state"] = STATE_CANCELLED
                    existing["error"] = "Bị thay bằng phiên đăng ký mới."
            self._enrollments[enroll_id] = {
                "name": clean_name,
                "state": STATE_RUNNING,
                "started_at": moment,
                "step_index": 0,
                "sampled_steps": set(),
                "samples": [],
                "error": None,
            }
        self._log.info("Bắt đầu đăng ký khuôn mặt cho '%s'.", clean_name)
        return {"enroll_id": enroll_id, "steps": list(self._steps)}

    def enroll_status(self, enroll_id: str) -> dict:
        """Tiến độ một phiên đăng ký.

        Tự đánh giá hết hạn tại đây (thời gian có thể trôi mà không có khung
        nào), nên gọi sau khi đã quá ``len(steps) * step_s`` sẽ thấy ``failed``.

        Raises:
            PeopleServiceError: không có phiên với ``enroll_id`` này.
        """
        with self._lock:
            record = self._enrollment_or_error(enroll_id)
            self._expire(record, self._clock())
            return self._status_payload(record)

    def cancel_enroll(self, enroll_id: str) -> bool:
        """Huỷ phiên đang chạy; trả ``False`` nếu không huỷ được.

        Huỷ không ghi gì vào kho, kể cả khi đã đủ mẫu nhưng chưa kịp ghi.
        """
        with self._lock:
            record = self._enrollments.get(str(enroll_id))
            if record is None or record["state"] != STATE_RUNNING:
                return False
            record["state"] = STATE_CANCELLED
            record["error"] = "Đã huỷ theo yêu cầu; không ghi danh tính."
            record["samples"] = []
            self._log.info(
                "Đã huỷ đăng ký khuôn mặt cho '%s'.", record["name"]
            )
            return True

    def _enrollment_or_error(self, enroll_id: str) -> dict[str, Any]:
        record = self._enrollments.get(str(enroll_id))
        if record is None:
            raise PeopleServiceError(
                f"Không tìm thấy phiên đăng ký '{enroll_id}'."
            )
        return record

    def _collect_sample(self, vector: np.ndarray | None, moment: float) -> None:
        """Gom tối đa một embedding cho mỗi bước, đủ mẫu thì ghi."""
        record = self._running_enrollment()
        if record is None:
            return
        elapsed = max(0.0, moment - record["started_at"])
        step_index = min(
            int(elapsed // self._step_s), len(self._steps) - 1
        )
        record["step_index"] = step_index
        if vector is not None and len(record["samples"]) < self._samples_needed:
            if step_index not in record["sampled_steps"]:
                record["sampled_steps"].add(step_index)
                record["samples"].append(vector)
        if len(record["samples"]) >= self._samples_needed:
            self._finish_success(record)
        else:
            self._expire(record, moment)

    def _running_enrollment(self) -> dict[str, Any] | None:
        for record in self._enrollments.values():
            if record["state"] == STATE_RUNNING:
                return record
        return None

    def _expire(self, record: dict[str, Any], moment: float) -> None:
        """Hết thời gian cả chuỗi tư thế mà chưa đủ mẫu → ``failed``, không ghi."""
        if record["state"] != STATE_RUNNING:
            return
        total = len(self._steps) * self._step_s
        if moment - record["started_at"] < total:
            return
        record["state"] = STATE_FAILED
        record["error"] = (
            f"Không đủ mẫu hợp lệ ({len(record['samples'])}/"
            f"{self._samples_needed}) sau {total:g} giây. "
            "Không ghi danh tính nửa vời; hãy đăng ký lại khi đủ sáng và "
            "nhìn thẳng vào camera."
        )
        had_samples = len(record["samples"])
        record["samples"] = []
        self._log.warning(
            "Đăng ký '%s' thất bại: chỉ có %d/%d mẫu.",
            record["name"],
            had_samples,
            self._samples_needed,
        )

    def _finish_success(self, record: dict[str, Any]) -> None:
        """Ghi trung bình các embedding; lỗi ghi → ``failed``, không nửa vời."""
        merged = average_embedding(record["samples"])
        if merged is None:
            record["state"] = STATE_FAILED
            record["error"] = (
                "Các mẫu thu được không đủ khác nhau để tạo đặc trưng ổn "
                "định; không ghi danh tính."
            )
            record["samples"] = []
            return
        try:
            self._store.add(
                record["name"], merged, enrolled_at=self._clock()
            )
        except (FaceStoreError, ValueError) as exc:
            record["state"] = STATE_FAILED
            record["error"] = f"Không lưu được danh tính: {exc}"
            record["samples"] = []
            self._log.error(
                "Không lưu được khuôn mặt '%s': %s", record["name"], exc
            )
            return
        record["state"] = STATE_DONE
        record["error"] = None
        self._log.info(
            "Đã đăng ký khuôn mặt '%s' từ %d mẫu ở %d bước.",
            record["name"],
            len(record["samples"]),
            len(record["sampled_steps"]),
        )

    def _status_payload(self, record: dict[str, Any]) -> dict[str, Any]:
        step_index = int(record.get("step_index", 0))
        step_index = max(0, min(step_index, len(self._steps) - 1))
        return {
            "state": record["state"],
            "step_index": step_index,
            "step_name": self._steps[step_index],
            "samples": len(record["samples"]),
            "samples_needed": self._samples_needed,
            "error": record.get("error"),
        }

    # ------------------------------------------------------------------
    # danh sách / xoá / chọn người
    # ------------------------------------------------------------------
    def list_people(self) -> list[dict]:
        """Danh sách người đã đăng ký: ``id``, ``name``, ``created_ts``.

        ``id`` chính là tên (kho ``faces.py`` khoá theo tên). **Không** trả
        embedding hay bất kỳ dữ liệu sinh trắc học nào (spec §5.16).

        Raises:
            PeopleServiceError: kho không đọc được.
        """
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
        """Xoá một người và vector của họ; ``False`` nếu không có người đó.

        Xoá người đang được chọn thì tự bỏ chọn.
        """
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
        """Chọn người đang học; ``None`` bỏ chọn.

        Returns:
            ``True`` khi bỏ chọn hoặc khi người đó tồn tại; ``False`` khi
            ``person_id`` không có trong kho. Lựa chọn không bị xoá khi đăng
            ký người khác; chỉ bị xoá khi chính người đó bị xoá.
        """
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
        """Tên người đang được chọn, hoặc ``None``."""
        with self._lock:
            return self._selected

    # ------------------------------------------------------------------
    # tín hiệu cho web
    # ------------------------------------------------------------------
    def signals(self) -> dict:
        """Tín hiệu presence/phone/identity kèm tuổi (spec §5.16).

        Mỗi mục có ``state``, ``age_s``, ``age_limit_s``, ``fresh``; mục
        ``identity`` thêm ``name`` và ``reason``. ``age_s`` là ``None`` khi
        tín hiệu chưa từng được cập nhật. ``fresh is False`` nghĩa là dữ liệu
        đã cũ — người gọi **phải** nói "chưa có dữ liệu mới", không được
        trình bày ``state`` cũ như kết luận hiện tại.

        Không có khoá nào chứa vector/embedding.
        """
        with self._lock:
            presence = self._payload(self._presence, PRESENCE_AGE_LIMIT_S)
            phone = self._payload(self._phone, PHONE_AGE_LIMIT_S)
            identity = self._payload(self._identity, IDENTITY_AGE_LIMIT_S)
            identity["name"] = self._identity.get("name")
            identity["reason"] = self._identity.get("reason")
        return {"presence": presence, "phone": phone, "identity": identity}

    def _payload(self, record: dict[str, Any], limit: float) -> dict[str, Any]:
        updated = record.get("updated_at")
        age: float | None = None
        if updated is not None:
            age = max(0.0, float(self._clock()) - float(updated))
        return {
            "state": record.get("state", STATE_NO_DATA),
            "age_s": age,
            "age_limit_s": float(limit),
            "fresh": age is not None and age <= limit,
        }
