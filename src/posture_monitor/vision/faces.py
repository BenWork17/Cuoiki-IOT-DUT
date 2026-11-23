"""Nhận diện khuôn mặt bằng OpenCV (YuNet phát hiện + SFace đặc trưng) & kho vector JSON."""

from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np

from ..core.atomic_io import write_json_atomic
from ..core.credentials import resolve_model_path
from ..core.labels import FACE_STORE_FILENAME
from ..core.logging_setup import get_logger

logger = get_logger("posture_monitor.vision.faces")

UNKNOWN_NAME = "không biết"
REFERENCE_LFW_THRESHOLD = 0.363
DEFAULT_SCORE_THRESHOLD = 0.9
DEFAULT_NMS_THRESHOLD = 0.3
DEFAULT_TOP_K = 5000
DEFAULT_MIN_FACE_PX = 40
MIN_ENROL_FRAMES = 3
DEFAULT_INPUT_SIZE = (320, 320)
EMBEDDING_DIM = 128
STORE_FILENAME = FACE_STORE_FILENAME
STORE_VERSION = 1


class FaceError(RuntimeError):
    """Lỗi cơ bản của module nhận diện khuôn mặt."""


class FaceModelError(FaceError):
    """Thiếu mô hình OpenCV hoặc không nạp được mô hình."""


class FaceStoreError(FaceError):
    """Kho embedding không đọc/ghi/kiểm tra được."""


@dataclass(frozen=True)
class DetectedFace:
    """Một khuôn mặt phát hiện được trong khung."""

    x: float
    y: float
    width: float
    height: float
    score: float
    box: np.ndarray

    @property
    def min_side(self) -> float:
        return float(min(self.width, self.height))

    @property
    def area(self) -> float:
        return max(0.0, float(self.width)) * max(0.0, float(self.height))


@dataclass(frozen=True)
class MatchResult:
    """Kết quả so khớp một khuôn mặt với kho đã đăng ký."""

    name: str | None
    score: float
    message: str = ""

    @property
    def known(self) -> bool:
        return self.name is not None

    @property
    def label(self) -> str:
        return self.name if self.name is not None else UNKNOWN_NAME


@dataclass(frozen=True)
class Person:
    """Một người đã đăng ký trong kho (chỉ tên, vector L2 và thời điểm)."""

    name: str
    embedding: np.ndarray
    enrolled_at: float


@dataclass(frozen=True)
class EnrolResult:
    """Kết quả đăng ký một người."""

    name: str
    used: int
    total: int
    warning: str | None = None


def normalise_embedding(vector: Sequence[float] | np.ndarray) -> np.ndarray:
    """Chuẩn hoá một vector về độ dài 1 (kiểu ``float32``)."""
    arr = np.asarray(vector, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        raise ValueError("Vector đặc trưng rỗng, không chuẩn hoá được.")
    if not np.all(np.isfinite(arr)):
        raise ValueError("Vector đặc trưng chứa NaN hoặc vô cực, không chuẩn hoá được.")
    norm = float(np.linalg.norm(arr))
    if norm <= 0.0 or not math.isfinite(norm):
        raise ValueError("Vector đặc trưng có độ dài bằng 0, không chuẩn hoá được.")
    return (arr / norm).astype(np.float32)


def cosine_similarity(
    first: Sequence[float] | np.ndarray,
    second: Sequence[float] | np.ndarray,
) -> float:
    """Cosine similarity giữa hai vector, trong ``[-1, 1]``."""
    a = np.asarray(first, dtype=np.float64).reshape(-1)
    b = np.asarray(second, dtype=np.float64).reshape(-1)
    if a.size == 0 or b.size == 0:
        raise ValueError("Không tính cosine của vector rỗng.")
    if a.size != b.size:
        raise ValueError(
            f"Hai vector khác số chiều ({a.size} và {b.size}), không so được."
        )
    if not (np.all(np.isfinite(a)) and np.all(np.isfinite(b))):
        raise ValueError("Vector chứa NaN hoặc vô cực, không tính cosine.")
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a <= 0.0 or norm_b <= 0.0:
        raise ValueError("Không tính cosine với vector có độ dài bằng 0.")
    value = float(np.dot(a, b) / (norm_a * norm_b))
    return max(-1.0, min(1.0, value))


def average_embedding(
    vectors: Iterable[Sequence[float] | np.ndarray],
) -> np.ndarray | None:
    """Vector trung bình của các embedding cùng một người, đã chuẩn hoá L2."""
    arrays = [np.asarray(vector, dtype=np.float64).reshape(-1) for vector in vectors]
    if not arrays:
        return None
    dim = arrays[0].size
    if dim == 0:
        raise ValueError("Embedding rỗng, không gộp được.")
    for arr in arrays:
        if arr.size != dim:
            raise ValueError(
                f"Các embedding khác số chiều ({arr.size} và {dim}); "
                "có thể chúng đến từ hai mô hình khác nhau."
            )
        if not np.all(np.isfinite(arr)):
            raise ValueError("Embedding chứa NaN hoặc vô cực, không gộp được.")
    mean = np.mean(np.stack(arrays, axis=0), axis=0)
    try:
        return normalise_embedding(mean)
    except ValueError:
        return None


def validate_threshold(threshold: Any) -> float:
    """Kiểm tra ngưỡng cosine bắt buộc (trong ``[-1.0, 1.0]``, hữu hạn, không phải bool/chuỗi)."""
    if threshold is None:
        raise ValueError(
            "Chưa có ngưỡng nhận diện khuôn mặt: 'threshold' là bắt buộc và "
            "phải được đặt sau khi đo trên dữ liệu thật của dự án "
            "(match_threshold hiện là null). Không dùng ngưỡng mặc định."
        )
    if isinstance(threshold, bool):
        raise ValueError("Ngưỡng nhận diện khuôn mặt phải là số thực, không phải bool.")
    if isinstance(threshold, (str, bytes)):
        raise ValueError(
            f"Ngưỡng nhận diện khuôn mặt phải là số thực, nhận được chuỗi "
            f"{threshold!r}. Sửa kiểu dữ liệu trong cấu hình."
        )
    try:
        value = float(threshold)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Ngưỡng nhận diện khuôn mặt phải là số thực, nhận được {threshold!r}."
        ) from exc
    if not math.isfinite(value):
        raise ValueError(
            f"Ngưỡng nhận diện khuôn mặt phải hữu hạn, nhận được {threshold!r}."
        )
    if not (-1.0 <= value <= 1.0):
        raise ValueError(
            f"Ngưỡng nhận diện khuôn mặt phải nằm trong [-1.0, 1.0] (miền "
            f"giá trị của cosine), nhận được {value!r}."
        )
    return value


def best_disqualified(score: float, threshold: float) -> bool:
    """Điểm ``score`` có thấp hơn ngưỡng ``threshold`` hay không."""
    return not (score >= float(threshold))


def best_match(
    query: Sequence[float] | np.ndarray,
    entries: Iterable[tuple[str, Sequence[float] | np.ndarray]],
    *,
    threshold: float,
) -> MatchResult:
    """Chọn người khớp nhất với ``query`` theo cosine."""
    limit = validate_threshold(threshold)
    try:
        q = np.asarray(query, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError):
        return MatchResult(None, 0.0, "Dữ liệu khuôn mặt không hợp lệ.")
    if q.size == 0 or not np.all(np.isfinite(q)):
        return MatchResult(None, 0.0, "Dữ liệu khuôn mặt không hợp lệ.")

    best_name: str | None = None
    best_score = -math.inf
    compared = 0
    for name, vector in entries:
        try:
            score = cosine_similarity(q, vector)
        except (TypeError, ValueError) as exc:
            logger.debug("Bỏ qua embedding không so được của '%s': %s", name, exc)
            continue
        compared += 1
        if score > best_score:
            best_name = name
            best_score = score

    if compared == 0:
        return MatchResult(
            None,
            0.0,
            "Chưa có ai được đăng ký hoặc dữ liệu đã đăng ký không dùng được.",
        )
    if best_disqualified(best_score, limit):
        return MatchResult(
            None,
            best_score,
            "Không nhận ra khuôn mặt: điểm giống thấp hơn ngưỡng.",
        )
    return MatchResult(best_name, best_score)


def _format_moment(ts: float) -> str:
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError, TypeError):
        return "mốc không xác định"


def parse_store_payload(payload: Any) -> list[Person]:
    """Kiểm tra và chuyển nội dung JSON của kho thành danh sách :class:`Person`."""
    if not isinstance(payload, dict):
        raise FaceStoreError(
            "Dữ liệu khuôn mặt không hợp lệ: nội dung tệp phải là một đối tượng JSON."
        )
    version = payload.get("version")
    if version != STORE_VERSION:
        raise FaceStoreError(
            f"Dữ liệu khuôn mặt không hợp lệ: phiên bản {version!r} không "
            f"được hỗ trợ (chỉ đọc được phiên bản {STORE_VERSION})."
        )
    raw_people = payload.get("people")
    if not isinstance(raw_people, list):
        raise FaceStoreError(
            "Dữ liệu khuôn mặt không hợp lệ: thiếu danh sách 'people'."
        )

    people: list[Person] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_people):
        if not isinstance(item, dict):
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt không hợp lệ: mục thứ {index + 1} không phải đối tượng."
            )
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt không hợp lệ: mục thứ {index + 1} thiếu tên người."
            )
        name = name.strip()
        if name in seen:
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt không hợp lệ: tên '{name}' bị trùng."
            )
        raw_vector = item.get("embedding")
        if not isinstance(raw_vector, list) or not raw_vector:
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt không hợp lệ: người '{name}' thiếu vector đặc trưng."
            )
        try:
            vector = np.asarray(raw_vector, dtype=np.float64).reshape(-1)
        except (TypeError, ValueError) as exc:
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt không hợp lệ: vector của '{name}' không phải dãy số ({exc})."
            ) from exc
        if not np.all(np.isfinite(vector)):
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt không hợp lệ: vector của '{name}' chứa NaN hoặc vô cực."
            )
        try:
            normalised = normalise_embedding(vector)
        except ValueError as exc:
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt không hợp lệ: vector của '{name}' không dùng được ({exc})."
            ) from exc

        raw_ts = item.get("enrolled_at", 0.0)
        try:
            enrolled_at = float(raw_ts)
        except (TypeError, ValueError) as exc:
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt không hợp lệ: thời điểm đăng ký của '{name}' không phải số."
            ) from exc
        if not math.isfinite(enrolled_at):
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt không hợp lệ: thời điểm đăng ký của '{name}' không hữu hạn."
            )

        seen.add(name)
        people.append(Person(name=name, embedding=normalised, enrolled_at=enrolled_at))
    return people


def build_store_payload(people: Iterable[Person]) -> dict[str, Any]:
    """Dựng nội dung JSON của kho (chỉ tên, vector và thời điểm — không ảnh)."""
    return {
        "version": STORE_VERSION,
        "people": [
            {
                "name": person.name,
                "enrolled_at": float(person.enrolled_at),
                "embedding": [float(value) for value in person.embedding],
            }
            for person in people
        ],
    }


def enrol_embeddings(
    store: "FaceStore",
    name: str,
    embeddings: Iterable[Sequence[float] | np.ndarray],
    total_frames: int | None = None,
) -> EnrolResult:
    """Tính embedding trung bình từ các khung rồi lưu vào kho."""
    clean_name = str(name).strip()
    if not clean_name:
        raise ValueError("Tên người đăng ký không được để trống.")

    vectors = list(embeddings)
    total = len(vectors) if total_frames is None else int(total_frames)
    if not vectors:
        raise FaceError(
            "Không đăng ký được: không có khuôn mặt hợp lệ nào trong các "
            "khung đã đưa vào. Hãy thử lại khi mặt nhìn thẳng và đủ sáng."
        )

    merged = average_embedding(vectors)
    if merged is None:
        raise FaceError(
            "Không đăng ký được: các khung đưa vào không đủ khác nhau để tạo "
            "đặc trưng ổn định. Hãy dùng thêm khung ở các góc hơi khác nhau."
        )

    store.add(clean_name, merged)
    used = len(vectors)
    warning = None
    if used < MIN_ENROL_FRAMES:
        warning = (
            f"Chỉ có {used}/{total} khung dùng được, ít hơn khuyến nghị "
            f"{MIN_ENROL_FRAMES} khung. Đăng ký vẫn được lưu nhưng dễ nhận "
            "nhầm hơn; nên đăng ký lại với nhiều khung hơn."
        )
        logger.warning(
            "Đăng ký '%s' chỉ dùng %d/%d khung (%d khung khuyến nghị).",
            clean_name,
            used,
            total,
            MIN_ENROL_FRAMES,
        )
    else:
        logger.info("Đã đăng ký khuôn mặt '%s' từ %d khung.", clean_name, used)
    return EnrolResult(name=clean_name, used=used, total=total, warning=warning)


class FaceStore:
    """Kho embedding khuôn mặt bền vững lưu trong tệp JSON nguyên tử."""

    def __init__(
        self,
        data_dir: str | os.PathLike[str],
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self._clock = clock or (lambda: datetime.now().timestamp())
        self._lock = threading.RLock()
        self._corrupt_logged = False

    @property
    def path(self) -> Path:
        return self.data_dir / STORE_FILENAME

    def load(self) -> list[Person]:
        with self._lock:
            return self._load_unlocked()

    def _load_unlocked(self) -> list[Person]:
        path = self.path
        if not path.exists():
            return []
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise FaceStoreError(
                f"Không đọc được dữ liệu khuôn mặt tại '{path}': {exc}."
            ) from exc
        if not text.strip():
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt tại '{path}' rỗng hoặc bị cắt cụt."
            )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt tại '{path}' bị hỏng (JSON không hợp lệ "
                f"ở dòng {exc.lineno} cột {exc.colno}). Có thể sửa tay hoặc "
                "xoá tệp rồi đăng ký lại."
            ) from exc
        return parse_store_payload(payload)

    def pairs(self) -> list[tuple[str, np.ndarray]]:
        try:
            people = self.load()
        except FaceStoreError as exc:
            self._log_corrupt(exc)
            return []
        return [(person.name, person.embedding) for person in people]

    def names(self) -> list[str]:
        try:
            return [person.name for person in self.load()]
        except FaceStoreError as exc:
            self._log_corrupt(exc)
            return []

    def get(self, name: str) -> Person | None:
        wanted = str(name).strip()
        for person in self._safe_load():
            if person.name == wanted:
                return person
        return None

    def _safe_load(self) -> list[Person]:
        try:
            return self.load()
        except FaceStoreError as exc:
            self._log_corrupt(exc)
            return []

    def _log_corrupt(self, exc: FaceStoreError) -> None:
        if self._corrupt_logged:
            return
        self._corrupt_logged = True
        logger.error(
            "Kho khuôn mặt không dùng được, tạm coi như chưa đăng ký ai: %s",
            exc,
        )

    def add(
        self,
        name: str,
        embedding: Sequence[float] | np.ndarray,
        enrolled_at: float | None = None,
    ) -> None:
        clean_name = str(name).strip()
        if not clean_name:
            raise ValueError("Tên người đăng ký không được để trống.")
        vector = normalise_embedding(embedding)
        moment = float(self._clock()) if enrolled_at is None else float(enrolled_at)
        if not math.isfinite(moment):
            moment = 0.0

        with self._lock:
            people = self.load()
            updated = Person(name=clean_name, embedding=vector, enrolled_at=moment)
            replaced = False
            for index, person in enumerate(people):
                if person.name == clean_name:
                    people[index] = updated
                    replaced = True
                    break
            if not replaced:
                people.append(updated)
            self._write_unlocked(people)
        logger.info(
            "Đã %s khuôn mặt '%s' trong kho (%d người).",
            "cập nhật" if replaced else "thêm",
            clean_name,
            len(people),
        )

    def remove(self, name: str) -> bool:
        clean_name = str(name).strip()
        with self._lock:
            people = self.load()
            remaining = [person for person in people if person.name != clean_name]
            if len(remaining) == len(people):
                return False
            self._write_unlocked(remaining)
        logger.info(
            "Đã xoá khuôn mặt '%s' khỏi kho (còn %d người).",
            clean_name,
            len(remaining),
        )
        return True

    def _write_unlocked(self, people: Sequence[Person]) -> None:
        try:
            write_json_atomic(
                self.path,
                build_store_payload(people),
                fsync_fn=os.fsync,
            )
        except OSError as exc:
            raise FaceStoreError(
                f"Không ghi được dữ liệu khuôn mặt vào '{self.path}': {exc}."
            ) from exc


class FaceRecognizer:
    """Phát hiện và nhận diện khuôn mặt bằng YuNet + SFace của OpenCV (nạp lười)."""

    def __init__(
        self,
        yunet_path: str | os.PathLike[str],
        sface_path: str | os.PathLike[str],
        *,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        nms_threshold: float = DEFAULT_NMS_THRESHOLD,
        top_k: int = DEFAULT_TOP_K,
        min_face_px: int = DEFAULT_MIN_FACE_PX,
        input_size: tuple[int, int] = DEFAULT_INPUT_SIZE,
    ) -> None:
        self.yunet_path = resolve_model_path(yunet_path)
        self.sface_path = resolve_model_path(sface_path)
        self.score_threshold = float(score_threshold)
        self.nms_threshold = float(nms_threshold)
        self.top_k = int(top_k)
        self.min_face_px = int(min_face_px)
        self.input_size = (int(input_size[0]), int(input_size[1]))

        self._cv2: Any = None
        self._detector: Any = None
        self._recognizer: Any = None
        self._load_lock = threading.Lock()

    def _ensure_models(self) -> Any:
        if self._detector is not None and self._recognizer is not None:
            return self._cv2
        with self._load_lock:
            if self._detector is not None and self._recognizer is not None:
                return self._cv2

            missing = [
                str(path)
                for path in (self.yunet_path, self.sface_path)
                if not path.is_file()
            ]
            if missing:
                raise FaceModelError(
                    "Thiếu tệp mô hình nhận diện khuôn mặt: "
                    + ", ".join(f"'{path}'" for path in missing)
                    + ". Cần 'yunet.onnx' (phát hiện) và 'sface.onnx' "
                    "(đặc trưng); hãy tải về thư mục 'models/' hoặc truyền "
                    "đường dẫn vào khi khởi tạo FaceRecognizer."
                )

            try:
                import cv2  # noqa: PLC0415
            except ImportError as exc:
                raise FaceModelError(
                    "Không nhận diện khuôn mặt được vì thiếu gói OpenCV "
                    "(opencv-python). Hãy cài đặt theo requirements.txt."
                ) from exc

            width, height = self.input_size
            try:
                detector = cv2.FaceDetectorYN_create(
                    str(self.yunet_path),
                    "",
                    (width, height),
                    self.score_threshold,
                    self.nms_threshold,
                    self.top_k,
                )
            except cv2.error as exc:
                raise FaceModelError(
                    f"Không nạp được mô hình phát hiện khuôn mặt từ "
                    f"'{self.yunet_path}': {exc}"
                ) from exc
            try:
                recognizer = cv2.FaceRecognizerSF_create(str(self.sface_path), "")
            except cv2.error as exc:
                raise FaceModelError(
                    f"Không nạp được mô hình đặc trưng khuôn mặt từ "
                    f"'{self.sface_path}': {exc}"
                ) from exc

            self._cv2 = cv2
            self._detector = detector
            self._recognizer = recognizer
            logger.info("Đã nạp mô hình nhận diện khuôn mặt.")
            return cv2

    def detect(self, image: Any) -> list[DetectedFace]:
        cv2 = self._ensure_models()
        if image is None or not hasattr(image, "shape"):
            raise ValueError("Khung hình không hợp lệ để phát hiện khuôn mặt.")
        height, width = int(image.shape[0]), int(image.shape[1])
        if height <= 0 or width <= 0:
            return []

        self._detector.setInputSize((width, height))
        try:
            _, faces = self._detector.detect(image)
        except cv2.error as exc:
            raise FaceModelError(f"Lỗi khi phát hiện khuôn mặt: {exc}") from exc
        if faces is None or len(faces) == 0:
            return []

        detected: list[DetectedFace] = []
        for row in np.asarray(faces, dtype=np.float32):
            x, y, box_w, box_h = (float(v) for v in row[:4])
            if box_w < self.min_face_px or box_h < self.min_face_px:
                continue
            detected.append(
                DetectedFace(
                    x=x,
                    y=y,
                    width=box_w,
                    height=box_h,
                    score=float(row[-1]),
                    box=np.asarray(row, dtype=np.float32),
                )
            )
        return detected

    def embedding(self, image: Any, face: DetectedFace) -> np.ndarray:
        cv2 = self._ensure_models()
        try:
            aligned = self._recognizer.alignCrop(image, face.box)
            feature = self._recognizer.feature(aligned)
        except cv2.error as exc:
            raise ValueError(f"Không trích được đặc trưng khuôn mặt: {exc}") from exc
        vector = np.asarray(feature, dtype=np.float32).reshape(-1)
        if vector.size == 0 or not np.all(np.isfinite(vector)):
            raise ValueError("Đặc trưng khuôn mặt rỗng hoặc không hợp lệ.")
        return vector

    def embed_largest(self, image: Any) -> np.ndarray | None:
        faces = self.detect(image)
        if not faces:
            return None
        largest = max(faces, key=lambda face: face.area)
        return self.embedding(image, largest)

    def enrol(
        self,
        store: FaceStore,
        name: str,
        frames: Iterable[Any],
    ) -> EnrolResult:
        embeddings: list[np.ndarray] = []
        total = 0
        for frame in frames:
            total += 1
            try:
                vector = self.embed_largest(frame)
            except ValueError as exc:
                logger.debug("Bỏ qua khung %d khi đăng ký '%s': %s", total, name, exc)
                continue
            if vector is not None:
                embeddings.append(vector)
        return enrol_embeddings(store, name, embeddings, total_frames=total)

    def recognize(
        self,
        store: FaceStore,
        image: Any,
        *,
        threshold: float,
    ) -> MatchResult:
        limit = validate_threshold(threshold)
        entries = store.pairs()
        if not entries:
            return MatchResult(
                None, 0.0, "Chưa có ai được đăng ký trên thiết bị này."
            )
        try:
            query = self.embed_largest(image)
        except ValueError as exc:
            logger.debug("Không nhận diện được khung này: %s", exc)
            return MatchResult(None, 0.0, "Khung hình không dùng được.")
        if query is None:
            return MatchResult(None, 0.0, "Không thấy khuôn mặt nào trong khung.")
        return best_match(query, entries, threshold=limit)


def build_face_processor(
    recognizer: Any,
    face_cfg: Any,
    log: Any,
    *,
    skipped_sentinel: object,
    skip_gate: Callable[[], bool] | None = None,
    note_box: Callable[[Any], None] | None = None,
    clock: Callable[[], float] | None = None,
) -> Callable[[Any], Any]:
    """Đóng gói đường ống phát hiện + trích xuất đặc trưng khuôn mặt có cổng nhịp ``interval_s``.

    - Trả ``skipped_sentinel`` khi chưa tới nhịp ``interval_s`` hoặc khi model ném lỗi.
    - Khi ``skip_gate()`` là ``True`` (đang trong phiên đăng ký 5 bước), bỏ qua cổng nhịp
      để thu mẫu mọi khung mà không đánh rơi mẫu.
    - Trả ``None`` khi đã nhìn nhưng khung không có mặt; báo hộp ``(x, y, w, h)`` qua ``note_box``.
    """
    interval_s = float(getattr(face_cfg, "interval_s", 2.0) or 2.0)
    now_fn = time.monotonic if clock is None else clock
    state: dict[str, Any] = {"last_at": -math.inf, "error": None}

    def _report_box(box: Any) -> None:
        if note_box is None:
            return
        try:
            note_box(box)
        except Exception:  # noqa: BLE001
            pass

    def processor(frame: Any) -> Any:
        now = now_fn()
        if skip_gate is not None and skip_gate():
            state["last_at"] = now
        elif now - state["last_at"] < interval_s:
            return skipped_sentinel
        else:
            state["last_at"] = now
        try:
            faces = recognizer.detect(frame)
            if not faces:
                state["error"] = None
                _report_box(None)
                return None
            largest = max(faces, key=lambda detected: detected.area)
            _report_box((largest.x, largest.y, largest.width, largest.height))
            embedding = recognizer.embedding(frame, largest)
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if message != state["error"]:
                state["error"] = message
                log.warning(
                    "Không nhận diện được khuôn mặt ở khung này (%s); giữ "
                    "nguyên danh tính gần nhất.",
                    exc,
                )
            return skipped_sentinel
        state["error"] = None
        return embedding

    return processor
