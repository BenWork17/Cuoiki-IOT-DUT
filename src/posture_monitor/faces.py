"""Nhận diện khuôn mặt bằng OpenCV có sẵn (YuNet phát hiện + SFace đặc trưng).

Module này thêm **danh tính người đang học** cho hệ thống giám sát tư thế:
đăng ký (enrol) một người từ vài khung hình, rồi nhận ra người đó trong các
khung sau. Không thêm phụ thuộc mới — chỉ dùng hai lớp đã có trong
``opencv-python``:

- ``cv2.FaceDetectorYN`` (mô hình ``yunet.onnx``): phát hiện khuôn mặt.
- ``cv2.FaceRecognizerSF`` (mô hình ``sface.onnx``): cắt/gióng khuôn mặt
  (``alignCrop``), trích vector đặc trưng 128 chiều (``feature``) và so khớp
  (``match`` với ``FR_COSINE``).

**Đường dẫn mô hình là tham số truyền vào**, không hardcode: mô hình nằm ngoài
kho mã nguồn và người dùng có thể đặt ở bất kỳ đâu.

Ràng buộc đã cố ý đặt:

- **Nạp mô hình lười và an toàn** (spec §11.4). ``import posture_monitor.faces``
  không mở tệp mô hình nào; thiếu ``yunet.onnx``/``sface.onnx`` thì chỉ khi
  thật sự phát hiện/nhận diện mới ném :class:`FaceModelError` với thông điệp
  tiếng Việt nêu rõ đường dẫn còn thiếu.
- **Không lưu ảnh** (spec §11.5). Kho dữ liệu chỉ chứa vector đặc trưng, tên
  người và thời điểm đăng ký — không có khung hình, không có ảnh khuôn mặt.
  Đây là dữ liệu sinh trắc học, nên module **không log vector** ở bất kỳ cấp
  nào; log chỉ nêu tên, số khung và kết quả.
- **Ghi nguyên tử.** Kho được ghi ra tệp tạm cùng thư mục rồi ``os.replace``
  đè lên tệp thật, nên mất điện giữa chừng không để lại JSON nửa vời.
- **Không crash vì dữ liệu hỏng.** Tệp kho hỏng thì :meth:`FaceStore.load`
  ném :class:`FaceStoreError` nêu rõ lý do (để người vận hành biết phải sửa
  gì); các đường dùng hằng ngày (:meth:`FaceStore.pairs`,
  :meth:`FaceRecognizer.recognize`) bắt lỗi đó, ghi log và coi như chưa có ai
  đăng ký, thay vì làm sập vòng lặp giám sát.
- **Nhịp gọi do bên ngoài quyết định.** Đo trên Pi 4 cho thấy YuNet ~75 ms/
  khung và SFace ~64 ms/khuôn mặt, tức chỉ vài khuôn mặt mỗi giây. Module
  **không** tự chạy mỗi khung và không tự đặt bộ đếm thời gian; người gọi phải
  gọi thưa ra (ví dụ mỗi vài giây một lần) như với mọi tác vụ nặng khác.

Phần logic thuần (cosine, chọn người khớp, gộp vector, đọc/ghi kho) tách khỏi
phần OpenCV để test được mà không cần mô hình thật — xem ``tests/test_faces.py``.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np

from .logging_setup import get_logger

logger = get_logger(__name__)

#: Nhãn hiển thị khi không có ai khớp hoặc chưa ai được đăng ký.
UNKNOWN_NAME = "không biết"

#: Ngưỡng cosine mà tài liệu OpenCV nêu cho SFace trên bộ LFW.
#:
#: **Chỉ là con số tham khảo trong tài liệu, KHÔNG phải mặc định của dự án và
#: KHÔNG được dùng làm giá trị rơi.** Ngưỡng nhận diện phải do người gọi truyền
#: (`best_match`/`FaceRecognizer.recognize` đều yêu cầu ``threshold`` bắt buộc)
#: và phải được đặt sau khi đo trên dữ liệu thật của dự án — chép số của bộ dữ
#: liệu khác vào làm "đã kiểm chứng" là điều spec V3 cấm
#: (``docs/SPEC_V3.md``, ``match_threshold: null  # BẮT BUỘC đặt sau khi đo``).
#:
#: Không có chỗ nào trong module này tự dùng hằng số này.
REFERENCE_LFW_THRESHOLD = 0.363

#: Ngưỡng tin cậy phát hiện khuôn mặt của YuNet.
DEFAULT_SCORE_THRESHOLD = 0.9

#: Ngưỡng NMS của YuNet.
DEFAULT_NMS_THRESHOLD = 0.3

#: Số khuôn mặt giữ lại trước NMS (như khuyến nghị trong ví dụ của OpenCV).
DEFAULT_TOP_K = 5000

#: Cạnh nhỏ nhất (pixel) của khung bao để còn coi là khuôn mặt dùng được.
#: Khuôn mặt nhỏ hơn ngưỡng này bị bỏ qua thay vì đưa vào SFace: vùng ảnh quá
#: nhỏ cho ra vector vô nghĩa và làm bẩn embedding trung bình khi đăng ký.
DEFAULT_MIN_FACE_PX = 40

#: Số khung tối thiểu nên có khi đăng ký; ít hơn thì vẫn lưu nhưng cảnh báo.
MIN_ENROL_FRAMES = 3

#: Kích thước đầu vào mặc định của YuNet khi chưa biết khung hình.
DEFAULT_INPUT_SIZE = (320, 320)

#: Số chiều vector đặc trưng của SFace.
EMBEDDING_DIM = 128

#: Tên tệp kho trong thư mục dữ liệu.
STORE_FILENAME = "faces.json"

#: Phiên bản định dạng kho; đọc được đúng phiên bản này.
STORE_VERSION = 1

#: Đuôi tệp tạm khi ghi nguyên tử; dùng tiền tố "." để không ai nhầm là dữ liệu.
_TEMP_PREFIX = ".faces-"
_TEMP_SUFFIX = ".tmp"


class FaceError(RuntimeError):
    """Lỗi cơ bản của module nhận diện khuôn mặt."""


class FaceModelError(FaceError):
    """Thiếu mô hình OpenCV hoặc không nạp được mô hình."""


class FaceStoreError(FaceError):
    """Kho embedding không đọc/ghi/kiểm tra được."""


@dataclass(frozen=True)
class DetectedFace:
    """Một khuôn mặt phát hiện được trong khung.

    Attributes:
        x: Toạ độ trái (pixel).
        y: Toạ độ trên (pixel).
        width: Chiều rộng khung bao.
        height: Chiều cao khung bao.
        score: Điểm tin cậy của bộ phát hiện, trong ``[0, 1]``.
        box: Cửa sổ 4 số mà ``cv2.FaceRecognizerSF.alignCrop`` cần.
    """

    x: float
    y: float
    width: float
    height: float
    score: float
    box: np.ndarray

    @property
    def min_side(self) -> float:
        """Cạnh ngắn hơn của khung bao, dùng để lọc khuôn mặt quá nhỏ."""
        return float(min(self.width, self.height))

    @property
    def area(self) -> float:
        """Diện tích khung bao (pixel²)."""
        return max(0.0, float(self.width)) * max(0.0, float(self.height))


@dataclass(frozen=True)
class MatchResult:
    """Kết quả so khớp một khuôn mặt với kho đã đăng ký.

    Attributes:
        name: Tên người khớp nhất, hoặc ``None`` khi dưới ngưỡng/chưa đăng ký.
        score: Điểm cosine cao nhất tìm được (``0.0`` khi kho rỗng).
        message: Ghi chú tiếng Việt cho UI khi không nhận ra được.
    """

    name: str | None
    score: float
    message: str = ""

    @property
    def known(self) -> bool:
        """Có nhận ra người cụ thể hay không."""
        return self.name is not None

    @property
    def label(self) -> str:
        """Tên để hiển thị: tên người, hoặc :data:`UNKNOWN_NAME`."""
        return self.name if self.name is not None else UNKNOWN_NAME


@dataclass(frozen=True)
class Person:
    """Một người đã đăng ký trong kho.

    ``embedding`` là vector đã chuẩn hoá L2. Không có ảnh nào ở đây.
    """

    name: str
    embedding: np.ndarray
    enrolled_at: float


@dataclass(frozen=True)
class EnrolResult:
    """Kết quả đăng ký một người.

    Attributes:
        name: Tên đã đăng ký.
        used: Số khung có khuôn mặt dùng được.
        total: Tổng số khung được đưa vào.
        warning: Thông điệp tiếng Việt khi đăng ký quá ít khung, hoặc ``None``.
    """

    name: str
    used: int
    total: int
    warning: str | None = None


# ----------------------------------------------------------------------------
# Logic thuần (không cần OpenCV, không cần mô hình) — test trực tiếp được.
# ----------------------------------------------------------------------------
def normalise_embedding(vector: Sequence[float] | np.ndarray) -> np.ndarray:
    """Chuẩn hoá một vector về độ dài 1 (kiểu ``float32``).

    Raises:
        ValueError: vector rỗng, chứa NaN/vô cực, hoặc có độ dài bằng 0.
    """
    arr = np.asarray(vector, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        raise ValueError("Vector đặc trưng rỗng, không chuẩn hoá được.")
    if not np.all(np.isfinite(arr)):
        raise ValueError(
            "Vector đặc trưng chứa NaN hoặc vô cực, không chuẩn hoá được."
        )
    norm = float(np.linalg.norm(arr))
    if norm <= 0.0 or not math.isfinite(norm):
        raise ValueError(
            "Vector đặc trưng có độ dài bằng 0, không chuẩn hoá được."
        )
    return (arr / norm).astype(np.float32)


def cosine_similarity(
    first: Sequence[float] | np.ndarray,
    second: Sequence[float] | np.ndarray,
) -> float:
    """Cosine similarity giữa hai vector, trong ``[-1, 1]``.

    Đây đúng là đại lượng mà ``cv2.FaceRecognizerSF.match(..., FR_COSINE)``
    trả về, chỉ khác là tính thẳng trong Python để test được và để so được
    nhiều người trong một lần mà không gọi C++ cho từng cặp.

    Raises:
        ValueError: hai vector khác số chiều, rỗng, có NaN/vô cực, hoặc một
            vector có độ dài 0 (khi đó cosine không xác định).
    """
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
    # Sai số dấu phẩy động có thể cho ra 1.0000000000000002.
    return max(-1.0, min(1.0, value))


def average_embedding(
    vectors: Iterable[Sequence[float] | np.ndarray],
) -> np.ndarray | None:
    """Vector trung bình của các embedding cùng một người, đã chuẩn hoá L2.

    Args:
        vectors: các embedding của cùng một người (mỗi khung một vector).

    Returns:
        Vector đơn vị ``float32`` cùng số chiều, hoặc ``None`` khi đầu vào
        rỗng hay trung bình suy biến về vector 0 (không dùng được).

    Raises:
        ValueError: các vector khác số chiều hoặc chứa giá trị không hữu hạn.
    """
    arrays = [
        np.asarray(vector, dtype=np.float64).reshape(-1)
        for vector in vectors
    ]
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
        # Các vector triệt tiêu nhau: trung bình không mang thông tin gì.
        return None


def validate_threshold(threshold: Any) -> float:
    """Kiểm tra ngưỡng cosine và trả về dạng ``float``.

    Ngưỡng **bắt buộc** phải do người gọi cung cấp và phải đến từ phép đo
    trên dữ liệu thật của dự án (spec V3: ``match_threshold`` chỉ được đặt sau
    khi đo). Vì vậy ``None`` — giá trị của ``match_threshold: null`` lúc chưa
    đo — phải nổi lên thành lỗi, **không** được lặng lẽ thay bằng một con số
    bịa: khi chưa đo thì tính năng nhận diện phải không chạy.

    Args:
        threshold: giá trị người gọi truyền vào.

    Returns:
        Ngưỡng dạng ``float``.

    Raises:
        ValueError: ``threshold`` là ``None``, không phải số, NaN/vô cực, hoặc
            nằm ngoài ``[-1.0, 1.0]`` (miền giá trị của cosine).
    """
    if threshold is None:
        raise ValueError(
            "Chưa có ngưỡng nhận diện khuôn mặt: 'threshold' là bắt buộc và "
            "phải được đặt sau khi đo trên dữ liệu thật của dự án "
            "(match_threshold hiện là null). Không dùng ngưỡng mặc định."
        )
    if isinstance(threshold, bool):
        # bool là lớp con của int; True/False không phải ngưỡng hợp lệ.
        raise ValueError(
            "Ngưỡng nhận diện khuôn mặt phải là số thực, không phải bool."
        )
    if isinstance(threshold, (str, bytes)):
        # Chuỗi số ("0.5") thường là hệ quả của việc đọc cấu hình sai kiểu.
        # Nhận nó là hợp lệ sẽ che mất lỗi cấu hình đó, nên từ chối thẳng.
        raise ValueError(
            f"Ngưỡng nhận diện khuôn mặt phải là số thực, nhận được chuỗi "
            f"{threshold!r}. Sửa kiểu dữ liệu trong cấu hình."
        )
    try:
        value = float(threshold)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Ngưỡng nhận diện khuôn mặt phải là số thực, nhận được "
            f"{threshold!r}."
        ) from exc
    if not math.isfinite(value):
        raise ValueError(
            f"Ngưỡng nhận diện khuôn mặt phải hữu hạn, nhận được "
            f"{threshold!r}."
        )
    if not (-1.0 <= value <= 1.0):
        raise ValueError(
            f"Ngưỡng nhận diện khuôn mặt phải nằm trong [-1.0, 1.0] (miền "
            f"giá trị của cosine), nhận được {value!r}."
        )
    return value


def best_match(
    query: Sequence[float] | np.ndarray,
    entries: Iterable[tuple[str, Sequence[float] | np.ndarray]],
    *,
    threshold: float,
) -> MatchResult:
    """Chọn người khớp nhất với ``query`` theo cosine.

    Args:
        query: embedding của khuôn mặt cần nhận diện.
        entries: các cặp ``(tên, embedding)`` đã đăng ký.
        threshold: ngưỡng cosine tối thiểu để trả về tên người; thấp hơn thì
            trả :data:`UNKNOWN_NAME` (``name=None``). **Bắt buộc**, keyword-only,
            không có giá trị mặc định — xem :func:`validate_threshold`.

    Returns:
        :class:`MatchResult`. Khi kho rỗng hoặc mọi vector bị bỏ qua, ``score``
        là ``0.0`` và ``name`` là ``None``. Dưới ngưỡng nhưng có so được,
        ``score`` vẫn là điểm cao nhất để người vận hành chỉnh ngưỡng.

    Raises:
        ValueError: ``threshold`` không dùng được (``None``, ngoài khoảng, ...).

    Không raise vì dữ liệu bẩn: vector sai số chiều hoặc không hữu hạn bị bỏ
    qua (có log DEBUG), để một bản ghi hỏng không làm mất khả năng nhận diện
    những người còn lại.
    """
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
            None, 0.0, "Chưa có ai được đăng ký hoặc dữ liệu đã đăng ký "
            "không dùng được."
        )
    if best_disqualified(best_score, limit):
        return MatchResult(
            None,
            best_score,
            "Không nhận ra khuôn mặt: điểm giống thấp hơn ngưỡng.",
        )
    return MatchResult(best_name, best_score)


def best_disqualified(score: float, threshold: float) -> bool:
    """Điểm ``score`` có thấp hơn ngưỡng ``threshold`` hay không.

    Tách thành hàm riêng để quy tắc so sánh nằm một chỗ: đổi dấu ``<`` thành
    ``<=`` hoặc đảo chiều so sánh ở đây sẽ làm test dưới ngưỡng đỏ ngay.
    """
    return not (score >= float(threshold))


def _format_moment(ts: float) -> str:
    """Mốc thời gian dạng ISO (giờ địa phương), không bao giờ raise.

    ``datetime`` không biểu diễn được mọi ``float`` (trên Windows, mốc gần
    epoch 0 ném ``OSError``); đồng hồ là tham số tiêm được nên phải phòng thủ.
    """
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError, TypeError):
        return "mốc không xác định"


def parse_store_payload(payload: Any) -> list[Person]:
    """Kiểm tra và chuyển nội dung JSON của kho thành danh sách :class:`Person`.

    Tách khỏi phần đọc tệp để test được định dạng mà không cần đĩa.

    Raises:
        FaceStoreError: payload sai cấu trúc, sai phiên bản, tên rỗng, vector
            rỗng/không hữu hạn, hoặc trùng tên.
    """
    if not isinstance(payload, dict):
        raise FaceStoreError(
            "Dữ liệu khuôn mặt không hợp lệ: nội dung tệp phải là một đối "
            "tượng JSON."
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
                f"Dữ liệu khuôn mặt không hợp lệ: mục thứ {index + 1} không "
                "phải đối tượng."
            )
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt không hợp lệ: mục thứ {index + 1} thiếu "
                "tên người."
            )
        name = name.strip()
        if name in seen:
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt không hợp lệ: tên '{name}' bị trùng."
            )
        raw_vector = item.get("embedding")
        if not isinstance(raw_vector, list) or not raw_vector:
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt không hợp lệ: người '{name}' thiếu "
                "vector đặc trưng."
            )
        try:
            vector = np.asarray(raw_vector, dtype=np.float64).reshape(-1)
        except (TypeError, ValueError) as exc:
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt không hợp lệ: vector của '{name}' không "
                f"phải dãy số ({exc})."
            ) from exc
        if not np.all(np.isfinite(vector)):
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt không hợp lệ: vector của '{name}' chứa "
                "NaN hoặc vô cực."
            )
        try:
            normalised = normalise_embedding(vector)
        except ValueError as exc:
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt không hợp lệ: vector của '{name}' không "
                f"dùng được ({exc})."
            ) from exc

        raw_ts = item.get("enrolled_at", 0.0)
        try:
            enrolled_at = float(raw_ts)
        except (TypeError, ValueError) as exc:
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt không hợp lệ: thời điểm đăng ký của "
                f"'{name}' không phải số."
            ) from exc
        if not math.isfinite(enrolled_at):
            raise FaceStoreError(
                f"Dữ liệu khuôn mặt không hợp lệ: thời điểm đăng ký của "
                f"'{name}' không hữu hạn."
            )

        seen.add(name)
        people.append(
            Person(name=name, embedding=normalised, enrolled_at=enrolled_at)
        )
    return people


def build_store_payload(people: Iterable[Person]) -> dict[str, Any]:
    """Dựng nội dung JSON của kho từ danh sách người.

    Chỉ có tên, vector và thời điểm — **không** có ảnh hay dữ liệu khung hình.
    """
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
    """Tính embedding trung bình từ các khung rồi lưu vào kho.

    Tách khỏi :class:`FaceRecognizer` để test được quy tắc gộp/cảnh báo mà
    không cần mô hình hay ảnh thật.

    Args:
        store: kho đích.
        name: tên người; khoảng trắng hai đầu bị cắt.
        embeddings: embedding của từng khung dùng được (có thể là generator).
        total_frames: tổng số khung người gọi đưa vào, để báo "dùng được bao
            nhiêu trên tổng bao nhiêu". Mặc định bằng số embedding.

    Raises:
        ValueError: tên rỗng.
        FaceError: không có embedding nào, hoặc trung bình suy biến.
        FaceStoreError: không ghi được kho.
    """
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


# ----------------------------------------------------------------------------
# Kho embedding bền vững
# ----------------------------------------------------------------------------
class FaceStore:
    """Kho embedding khuôn mặt lưu trong một tệp JSON.

    Args:
        data_dir: thư mục dữ liệu; tệp kho là ``data_dir/faces.json``. Thư mục
            được tạo khi ghi lần đầu, không tạo lúc khởi tạo.
        clock: hàm trả mốc thời gian thực (giây) để ghi ``enrolled_at``; test
            truyền đồng hồ giả.

    Mọi thao tác ghi đều đọc lại tệp dưới một khoá, sửa rồi ghi nguyên tử, nên
    hai lời gọi đồng thời trong cùng tiến trình không làm mất bản ghi của nhau.
    Không khoá giữa các tiến trình: dự án chỉ có một tiến trình giám sát.
    """

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
        """Đường dẫn tệp kho."""
        return self.data_dir / STORE_FILENAME

    # -- đọc ---------------------------------------------------------------
    def load(self) -> list[Person]:
        """Đọc và kiểm tra kho; trả danh sách người (rỗng nếu chưa có tệp).

        Raises:
            FaceStoreError: tệp tồn tại nhưng không đọc/không phân tích được.
        """
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
        """Các cặp ``(tên, embedding)`` để so khớp; kho hỏng → rỗng + log.

        Đây là đường dùng trong vòng lặp giám sát: không được crash vì một tệp
        hỏng (spec §11.4).
        """
        try:
            people = self.load()
        except FaceStoreError as exc:
            self._log_corrupt(exc)
            return []
        return [(person.name, person.embedding) for person in people]

    def names(self) -> list[str]:
        """Tên những người đã đăng ký (rỗng nếu kho hỏng/chưa có)."""
        try:
            return [person.name for person in self.load()]
        except FaceStoreError as exc:
            self._log_corrupt(exc)
            return []

    def get(self, name: str) -> Person | None:
        """Lấy một người theo tên; ``None`` nếu không có."""
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
        """Log lỗi kho hỏng; nhắc đúng một lần để không ngập log thẻ nhớ."""
        if self._corrupt_logged:
            return
        self._corrupt_logged = True
        logger.error(
            "Kho khuôn mặt không dùng được, tạm coi như chưa đăng ký ai: %s",
            exc,
        )

    # -- ghi ---------------------------------------------------------------
    def add(
        self,
        name: str,
        embedding: Sequence[float] | np.ndarray,
        enrolled_at: float | None = None,
    ) -> None:
        """Thêm người mới hoặc cập nhật embedding của người đã có.

        Raises:
            ValueError: tên rỗng hoặc embedding không dùng được.
            FaceStoreError: không ghi được tệp kho.
        """
        clean_name = str(name).strip()
        if not clean_name:
            raise ValueError("Tên người đăng ký không được để trống.")
        vector = normalise_embedding(embedding)
        moment = float(self._clock()) if enrolled_at is None else float(enrolled_at)
        if not math.isfinite(moment):
            moment = 0.0

        with self._lock:
            people = self.load()  # tệp hỏng thì báo lỗi, không ghi đè mù
            updated = Person(
                name=clean_name, embedding=vector, enrolled_at=moment
            )
            replaced = False
            for index, person in enumerate(people):
                if person.name == clean_name:
                    people[index] = updated
                    replaced = True
                    break
            if not replaced:
                people.append(updated)
            self._write_unlocked(people)
        # Log tên người là chấp nhận được; không log vector hay dữ liệu sinh
        # trắc học.
        logger.info(
            "Đã %s khuôn mặt '%s' trong kho (%d người).",
            "cập nhật" if replaced else "thêm",
            clean_name,
            len(people),
        )

    def remove(self, name: str) -> bool:
        """Xoá một người khỏi kho; trả ``True`` nếu thật sự có và đã xoá."""
        clean_name = str(name).strip()
        with self._lock:
            people = self.load()
            remaining = [
                person for person in people if person.name != clean_name
            ]
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
        """Ghi nguyên tử: tệp tạm cùng thư mục → fsync → ``os.replace``."""
        path = self.path
        parent = path.parent
        payload = json.dumps(
            build_store_payload(people), ensure_ascii=False, indent=2
        )
        tmp_name: str | None = None
        try:
            parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(parent),
                prefix=_TEMP_PREFIX,
                suffix=_TEMP_SUFFIX,
                delete=False,
            )
            tmp_name = handle.name
            try:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                handle.close()
            os.replace(tmp_name, path)
            tmp_name = None
        except OSError as exc:
            raise FaceStoreError(
                f"Không ghi được dữ liệu khuôn mặt vào '{path}': {exc}."
            ) from exc
        finally:
            if tmp_name is not None:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass


# ----------------------------------------------------------------------------
# OpenCV: phát hiện + đặc trưng
# ----------------------------------------------------------------------------
class FaceRecognizer:
    """Phát hiện và nhận diện khuôn mặt bằng YuNet + SFace của OpenCV.

    Args:
        yunet_path: đường dẫn ``yunet.onnx`` (bắt buộc, không hardcode).
        sface_path: đường dẫn ``sface.onnx`` (bắt buộc, không hardcode).
        score_threshold: ngưỡng tin cậy của bộ phát hiện.
        nms_threshold: ngưỡng NMS của bộ phát hiện.
        top_k: số khuôn mặt giữ trước NMS.
        min_face_px: cạnh nhỏ nhất của khung bao để còn dùng.
        input_size: kích thước đầu vào gợi ý; bị thay bằng kích thước khung
            thật ở mỗi lần :meth:`detect`.

    Không mở mô hình lúc khởi tạo: lần gọi đầu tiên mới nạp, nên tạo đối tượng
    không bao giờ crash vì thiếu tệp. Thiếu tệp thì lần dùng đầu tiên ném
    :class:`FaceModelError` với thông điệp tiếng Việt nêu đường dẫn.
    """

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
        self.yunet_path = Path(yunet_path)
        self.sface_path = Path(sface_path)
        self.score_threshold = float(score_threshold)
        self.nms_threshold = float(nms_threshold)
        self.top_k = int(top_k)
        self.min_face_px = int(min_face_px)
        self.input_size = (int(input_size[0]), int(input_size[1]))

        self._cv2: Any = None
        self._detector: Any = None
        self._recognizer: Any = None
        self._load_lock = threading.Lock()

    # -- nạp mô hình -------------------------------------------------------
    def _ensure_models(self) -> Any:
        """Nạp (một lần) bộ phát hiện và bộ nhận diện; trả module ``cv2``."""
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
                    "(đặc trưng); hãy tải về rồi truyền đường dẫn vào khi "
                    "khởi tạo FaceRecognizer."
                )

            try:
                import cv2  # noqa: PLC0415 - cố ý nạp lười
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
                recognizer = cv2.FaceRecognizerSF_create(
                    str(self.sface_path), ""
                )
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

    # -- phát hiện ---------------------------------------------------------
    def detect(self, image: Any) -> list[DetectedFace]:
        """Phát hiện khuôn mặt trong ``image`` (mảng BGR của OpenCV).

        Trả danh sách rỗng khi không có khuôn mặt hoặc ảnh rỗng — đây là
        trường hợp bình thường, không phải lỗi. Khuôn mặt nhỏ hơn
        ``min_face_px`` bị loại.

        Raises:
            FaceModelError: thiếu mô hình/OpenCV.
            ValueError: ``image`` không phải ảnh BGR 3 kênh dùng được.
        """
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
            raise FaceModelError(
                f"Lỗi khi phát hiện khuôn mặt: {exc}"
            ) from exc
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
        """Trích embedding 128 chiều của một khuôn mặt đã phát hiện.

        Raises:
            FaceModelError: mô hình lỗi.
            ValueError: không gióng/cắt hoặc không trích được đặc trưng.
        """
        cv2 = self._ensure_models()
        try:
            aligned = self._recognizer.alignCrop(image, face.box)
            feature = self._recognizer.feature(aligned)
        except cv2.error as exc:
            raise ValueError(
                f"Không trích được đặc trưng khuôn mặt: {exc}"
            ) from exc
        vector = np.asarray(feature, dtype=np.float32).reshape(-1)
        if vector.size == 0 or not np.all(np.isfinite(vector)):
            raise ValueError(
                "Đặc trưng khuôn mặt rỗng hoặc không hợp lệ."
            )
        return vector

    def embed_largest(self, image: Any) -> np.ndarray | None:
        """Phát hiện khuôn mặt lớn nhất trong khung và trả embedding.

        Chọn khuôn mặt có diện tích lớn nhất: đó thường là người ngồi gần
        camera nhất, tức người đang học. Trả ``None`` khi không có khuôn mặt
        dùng được (không phải lỗi).
        """
        faces = self.detect(image)
        if not faces:
            return None
        largest = max(faces, key=lambda face: face.area)
        return self.embedding(image, largest)

    # -- đăng ký / nhận diện ----------------------------------------------
    def enrol(
        self,
        store: FaceStore,
        name: str,
        frames: Iterable[Any],
    ) -> EnrolResult:
        """Đăng ký ``name`` từ nhiều khung hình của cùng một người.

        Khung không có khuôn mặt hợp lệ bị bỏ qua (không phải lỗi); nếu không
        khung nào dùng được thì :func:`enrol_embeddings` ném :class:`FaceError`.

        Raises:
            FaceModelError: thiếu mô hình.
            FaceError: không khung nào dùng được.
            FaceStoreError: không ghi được kho.
        """
        embeddings: list[np.ndarray] = []
        total = 0
        for frame in frames:
            total += 1
            try:
                vector = self.embed_largest(frame)
            except ValueError as exc:
                logger.debug(
                    "Bỏ qua khung %d khi đăng ký '%s': %s", total, name, exc
                )
                continue
            if vector is not None:
                embeddings.append(vector)
        return enrol_embeddings(
            store, name, embeddings, total_frames=total
        )

    def recognize(
        self,
        store: FaceStore,
        image: Any,
        *,
        threshold: float,
    ) -> MatchResult:
        """Nhận diện khuôn mặt lớn nhất trong khung so với kho đã đăng ký.

        Không raise vì chuyện thường gặp (không có khuôn mặt, chưa đăng ký ai,
        kho hỏng, ảnh không hợp lệ): trả ``MatchResult`` với ``name=None`` và
        ``message`` giải thích. Chỉ thiếu mô hình mới ném
        :class:`FaceModelError`, vì đó là lỗi cấu hình phải sửa.

        Args:
            store: kho người đã đăng ký.
            image: khung BGR.
            threshold: ngưỡng cosine. **Bắt buộc**, keyword-only, không có mặc
                định: truyền tham số chứ không đọc config ở đây (module không
                sở hữu config), và giá trị phải đến từ phép đo thật. ``None``
                (config ``match_threshold: null``) ném ``ValueError`` thay vì
                chạy với một con số bịa.

        Raises:
            ValueError: ``threshold`` không dùng được (``None``, ngoài khoảng).
        """
        # Kiểm tra ngưỡng TRƯỚC mọi việc khác: cấu hình chưa đo thì tính năng
        # không được chạy, kể cả khi nhìn bề ngoài "không có gì để nhận diện".
        limit = validate_threshold(threshold)
        entries = store.pairs()
        if not entries:
            return MatchResult(
                None,
                0.0,
                "Chưa có ai được đăng ký trên thiết bị này.",
            )
        try:
            query = self.embed_largest(image)
        except ValueError as exc:
            logger.debug("Không nhận diện được khung này: %s", exc)
            return MatchResult(None, 0.0, "Khung hình không dùng được.")
        if query is None:
            return MatchResult(
                None, 0.0, "Không thấy khuôn mặt nào trong khung."
            )
        return best_match(query, entries, threshold=limit)
