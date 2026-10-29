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

import json
import math
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

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
from .schedule import (
    ALERT_KINDS,
    DEFAULT_KINDS,
    ScheduleConfig,
    ScheduleError,
    parse_kind_settings,
    parse_window,
)

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

# -- Ngưỡng tự suy từ dữ liệu đăng ký ---------------------------------------
#
# Khi ``face.match_threshold`` là null, ngưỡng cosine được suy ra từ chính
# các mẫu của người vừa đăng ký: độ giống nhau THẤP NHẤT giữa hai mẫu bất kỳ
# của cùng một người chính là mức "vẫn còn là chính mình" trên thiết bị này.
# Đặt ngưỡng thấp hơn mức đó một khoảng an toàn để biến thiên ánh sáng/góc
# mặt giữa các lần đo không làm rơi người thật xuống dưới ngưỡng.
#
# Đây KHÔNG phải ngưỡng chép từ tài liệu hay repo khác: giá trị cuối cùng
# phụ thuộc hoàn toàn vào dữ liệu người dùng vừa đăng ký.
AUTO_THRESHOLD_MARGIN = 0.15
#: Sàn: dưới mức này thì "khớp" gần như vô nghĩa (hai vector gần trực giao).
AUTO_THRESHOLD_MIN = 0.30
#: Trần: trên mức này chỉ khung gần như trùng khít mới qua, dễ bỏ sót người
#: thật; dữ liệu đăng ký ít mẫu không đủ tư cách đòi hỏi cao hơn.
AUTO_THRESHOLD_MAX = 0.95

# -- Tệp phụ giữ ngưỡng tự suy qua lần khởi động lại -----------------------
#
# Ngưỡng tự suy sống trong RAM sẽ mất mỗi lần restart, và khi đó ``_classify``
# trả ``UNKNOWN`` cho mọi khung → cảnh báo "người khác vào học hộ" im lặng vĩnh
# viễn cho tới lần đăng ký kế tiếp. Ghi nó xuống một **tệp phụ** thay vì nhét
# vào ``faces.json``: kho khuôn mặt là hợp đồng với :class:`FaceStore`
# (``STORE_VERSION``, ``parse_store_payload``) đã có test, thêm khoá lạ vào đó
# sẽ phải migration và có nguy cơ làm hỏng kho đang chạy trên Pi.
#
# Nội dung tệp chỉ có ngưỡng + phiên bản + thời điểm. **Không** vector, không
# ảnh, không tên người (spec §5.13.1, §11.5).
THRESHOLD_FILENAME = "face_threshold.json"
#: Phiên bản định dạng tệp phụ; khác phiên bản thì bỏ qua (chạy không ngưỡng).
THRESHOLD_VERSION = 1
#: Tiền tố tệp tạm khi ghi nguyên tử; "." để không ai nhầm là dữ liệu.
_THRESHOLD_TEMP_PREFIX = ".face-threshold-"
_THRESHOLD_TEMP_SUFFIX = ".tmp"

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

#: Hai kết quả của tín hiệu điện thoại. Tên có dấu gạch dưới cho khớp
#: ``presence.STATE_PRESENT``/``STATE_ABSENT`` (cũng là chuỗi tiếng Việt không
#: dấu), để hai nửa của cùng thẻ "Trạng thái học" dùng chung một quy ước.
PHONE_STATE_NONE = "khong_dung"
PHONE_STATE_USE = "dung"

#: Tuổi tối đa mặc định của từng tín hiệu trước khi bị coi là cũ.
#:
#: Presence/phone do vòng lặp cập nhật mỗi khung nên 3 s là rộng rãi; danh
#: tính chỉ chạy mỗi ~2 s (spec §4.2) nên cần cửa sổ dài hơn. Đây là lựa chọn
#: của lớp dịch vụ, không phải số đo — người gọi vẫn phải đọc ``fresh`` chứ
#: không dựa vào việc "3 s là đúng".
PRESENCE_AGE_LIMIT_S = 3.0
PHONE_AGE_LIMIT_S = 3.0
IDENTITY_AGE_LIMIT_S = 10.0

#: Sentinel "lượt này **không nhìn**", khác hẳn "nhìn mà không thấy mặt".
#:
#: ``processor`` trả ``None`` khi nó đã chạy và kết luận khung không có khuôn
#: mặt dùng được — đó là ``UNKNOWN``, một kết quả. Nhưng cổng ``interval_s``
#: hay một lỗi model thì **không phải** kết quả: chưa ai nhìn khung này. Nếu
#: trả ``None`` cho cả hai, :meth:`PeopleService.process_frame` sẽ ghi đè danh
#: tính vừa nhận ra bằng ``UNKNOWN`` ngay khung kế tiếp, khiến ``MATCH`` chỉ
#: sống một khung và bộ tích luỹ "người lạ" bị reset liên tục.
#:
#: Vì vậy ``processor`` trả sentinel này để báo "bỏ qua lượt", và
#: ``process_frame`` trả về sớm: danh tính cũ giữ nguyên, ``age_s`` tự lớn
#: dần rồi ``fresh`` tự thành ``False`` sau :data:`IDENTITY_AGE_LIMIT_S`.
OBSERVATION_SKIPPED = object()


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


#: Khóa hợp lệ ở cấp ngoài cùng của payload ``PUT /api/schedule``.
_SCHEDULE_KEYS = ("enabled", "windows", "kinds")


def derive_threshold(
    samples: Sequence[np.ndarray],
) -> float | None:
    """Suy ngưỡng cosine từ các embedding mẫu của **cùng một người**.

    Lấy độ giống nhau **thấp nhất** giữa mọi cặp mẫu (mức còn nhận ra chính
    mình), trừ :data:`AUTO_THRESHOLD_MARGIN` để có khoảng an toàn, rồi kẹp
    vào ``[AUTO_THRESHOLD_MIN, AUTO_THRESHOLD_MAX]`` và làm tròn 2 chữ số.

    Trả ``None`` khi không có cơ sở để suy: ít hơn 3 mẫu (cần ít nhất ba mẫu
    để có ba cặp), mẫu khác số chiều, hoặc một cặp không so được. Khi đó
    tính năng giữ nguyên trạng thái "chưa có ngưỡng" thay vì bịa số.
    """
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
    derived = lowest - AUTO_THRESHOLD_MARGIN
    derived = max(AUTO_THRESHOLD_MIN, min(AUTO_THRESHOLD_MAX, derived))
    return round(float(derived), 2)


def _parse_threshold_payload(payload: Any) -> float:
    """Đọc nội dung tệp phụ; trả ngưỡng hoặc ném :class:`ValueError`.

    Tách khỏi phần đọc tệp để test được định dạng mà không cần đĩa. Mọi lý do
    từ chối đều là :class:`ValueError` với thông điệp tiếng Việt: người gọi
    (constructor) bắt lỗi này, ghi **một** dòng cảnh báo rồi chạy không ngưỡng
    — tệp phụ hỏng không bao giờ được làm sập dashboard (spec §11.3, §11.4).
    """
    if not isinstance(payload, dict):
        raise ValueError("nội dung phải là một đối tượng JSON")
    version = payload.get("version")
    if version != THRESHOLD_VERSION:
        raise ValueError(
            f"phiên bản {version!r} không được hỗ trợ "
            f"(chỉ đọc được phiên bản {THRESHOLD_VERSION})"
        )
    raw = payload.get("threshold")
    if isinstance(raw, bool):
        # bool là lớp con của int; True/False không phải ngưỡng hợp lệ.
        raise ValueError("ngưỡng phải là số thực, không phải bool")
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        # ``OverflowError`` (``ArithmeticError``, không phải ``ValueError``) khi
        # JSON hợp lệ chứa số nguyên quá lớn, ví dụ ``10**400``: ``float()``
        # không biểu diễn nổi. Không bắt nó ở đây thì constructor và dashboard
        # chết vì một tệp phụ — trái lời hứa của ``_load_auto_threshold``.
        raise ValueError(f"ngưỡng không phải số thực ({raw!r})") from exc
    if not math.isfinite(value):
        raise ValueError(f"ngưỡng không hữu hạn ({value!r})")
    if not (-1.0 <= value <= 1.0):
        raise ValueError(
            f"ngưỡng {value!r} nằm ngoài [-1.0, 1.0] (miền giá trị của cosine)"
        )
    return value


def _build_threshold_payload(threshold: float, moment: float) -> dict[str, Any]:
    """Nội dung tệp phụ: chỉ ngưỡng, phiên bản và thời điểm (spec §11.5)."""
    return {
        "version": THRESHOLD_VERSION,
        "threshold": float(threshold),
        "updated_at": float(moment),
    }


def _write_threshold_file(path: Path, threshold: float, moment: float) -> None:
    """Ghi tệp phụ **nguyên tử**: tệp tạm cùng thư mục → fsync → ``os.replace``.

    Cùng thư mục để ``os.replace`` là rename nội bộ một ổ đĩa (nguyên tử); ghi
    tệp tạm ở thư mục khác có thể rơi vào trường hợp tệp đích nửa vời.

    Raises:
        OSError: không tạo/ghi/đổi tên được.
    """
    payload = json.dumps(
        _build_threshold_payload(threshold, moment), ensure_ascii=False, indent=2
    )
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(parent),
            prefix=_THRESHOLD_TEMP_PREFIX,
            suffix=_THRESHOLD_TEMP_SUFFIX,
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
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def _default_threshold_path(store: Any) -> Path | None:
    """Suy vị trí tệp phụ từ thư mục kho; ``None`` khi kho không có thư mục.

    Dùng ``store.data_dir`` nếu có (đúng như :class:`FaceStore`), nên tệp phụ
    nằm **cạnh** ``faces.json``. Kho giả không có ``data_dir`` thì dịch vụ chỉ
    giữ ngưỡng trong RAM như trước — persistence là tính năng thêm, không phải
    điều kiện để dùng được lớp này.
    """
    data_dir = getattr(store, "data_dir", None)
    if data_dir is None:
        return None
    try:
        return Path(data_dir) / THRESHOLD_FILENAME
    except (TypeError, ValueError):
        return None


def _schedule_payload(schedule: ScheduleConfig) -> dict[str, Any]:
    """Đổi :class:`ScheduleConfig` thành dict thuần để trả qua JSON."""
    return {
        "enabled": bool(schedule.enabled),
        "windows": [
            {
                "days": list(window.days),
                "start": window.start.strftime("%H:%M"),
                "end": window.end.strftime("%H:%M"),
            }
            for window in schedule.windows
        ],
        "kinds": {
            name: {
                "enabled": bool(settings.enabled),
                "cooldown_s": float(settings.cooldown_s),
                "hold_s": float(settings.hold_s),
            }
            for name, settings in schedule.kinds.items()
        },
    }


def _parse_schedule_payload(raw: Mapping[str, Any]) -> ScheduleConfig:
    """Đọc payload của ``PUT /api/schedule`` bằng chính hàm của ``schedule``.

    Cùng cú pháp và cùng lời báo lỗi với ``config.yaml``. Khóa lạ bị từ chối
    thay vì bỏ qua: người dùng gõ nhầm ``window`` cho ``windows`` mà không
    thấy lỗi sẽ tưởng lịch đã đổi.

    Raises:
        PeopleServiceError: payload sai ở bất kỳ mức nào.
    """
    unknown = sorted(set(raw) - set(_SCHEDULE_KEYS))
    if unknown:
        raise PeopleServiceError(
            f"Khóa giờ học không hợp lệ: {', '.join(unknown)}; dùng một trong "
            f"{', '.join(_SCHEDULE_KEYS)}."
        )

    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise PeopleServiceError(
            f"'{'enabled'}' của giờ học phải là true/false, nhận được "
            f"{enabled!r}."
        )

    raw_windows = raw.get("windows")
    windows: list[Any] = []
    try:
        if raw_windows is not None:
            if not isinstance(raw_windows, (list, tuple)):
                raise PeopleServiceError(
                    "'windows' phải là danh sách khung giờ, nhận được "
                    f"{type(raw_windows).__name__}."
                )
            for index, item in enumerate(raw_windows):
                windows.append(parse_window(item, f"windows[{index}]"))
        if enabled and not windows:
            raise PeopleServiceError(
                "Bật giờ học nhưng 'windows' đang trống. Thêm ít nhất một "
                "khung giờ hoặc đặt enabled: false."
            )

        raw_kinds = raw.get("kinds")
        kinds: dict[str, Any] = {}
        if raw_kinds is not None:
            if not isinstance(raw_kinds, Mapping):
                raise PeopleServiceError(
                    "'kinds' phải là ánh xạ theo tên loại cảnh báo "
                    f"({', '.join(ALERT_KINDS)}), nhận được "
                    f"{type(raw_kinds).__name__}."
                )
            for name, item in raw_kinds.items():
                if name not in ALERT_KINDS:
                    raise PeopleServiceError(
                        f"'kinds.{name}' không phải loại cảnh báo hợp lệ; "
                        f"dùng một trong {ALERT_KINDS}."
                    )
                kinds[name] = parse_kind_settings(item, f"kinds.{name}")
    except ScheduleError as exc:
        # Lỗi cú pháp của ``schedule.py`` là lỗi người dùng sửa được, nên
        # dịch sang lỗi nghiệp vụ của dịch vụ (400), không phải 503.
        raise PeopleServiceError(str(exc)) from exc

    return ScheduleConfig(
        enabled=enabled,
        windows=tuple(windows),
        kinds={**DEFAULT_KINDS, **kinds},
    )


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
        schedule: khung giờ học ban đầu cho :meth:`get_schedule`; ``None``
            thì dùng ``ScheduleConfig()`` (tắt, không khung giờ). Đối tượng
            được **giữ nguyên tham chiếu** (không sao chép) và
            :meth:`put_schedule` sửa tại chỗ, để mọi bên đã chia sẻ nó —
            nhất là ``_monitor_loop`` — thấy thay đổi ngay.
        logger: logger dùng riêng (mặc định logger của module).
        threshold_path: tệp phụ giữ ngưỡng tự suy qua lần khởi động lại.
            ``None`` (mặc định) thì suy ra ``<data_dir của kho>/face_threshold.json``;
            kho không có ``data_dir`` thì không bền hoá. Truyền đường dẫn cụ
            thể để đặt chỗ khác hoặc để test.

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
        schedule: ScheduleConfig | None = None,
        threshold_path: str | os.PathLike[str] | None = None,
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

        # Ngưỡng tự suy từ dữ liệu đăng ký, chỉ có khi ``threshold`` là None
        # và đã đăng ký đủ mẫu. Giá trị trong config luôn thắng giá trị này.
        #
        # Ngưỡng **bền qua lần khởi động lại**: đọc từ tệp phụ cạnh kho. Không
        # có tệp / tệp hỏng / sai phiên bản → chạy tiếp với ``None`` (giữ
        # nguyên hành vi cũ: mọi quan sát ``UNKNOWN``), chỉ một dòng cảnh báo.
        # Không bao giờ ném từ đây (spec §11.3): dashboard phải dậy được.
        self._auto_threshold: float | None = None
        derived_path = _default_threshold_path(self._store)
        if threshold_path is not None:
            try:
                derived_path = Path(threshold_path)
            except (TypeError, ValueError):
                derived_path = None
        self._threshold_path: Path | None = derived_path
        self._load_auto_threshold()

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

        # Khung giờ học sống **trong bộ nhớ** (xem ``put_schedule``). Giữ
        # đúng đối tượng được truyền vào (thường là ``config.schedule``) chứ
        # không sao chép — vòng lặp giám sát cũng giữ chính đối tượng đó, nên
        # ``put_schedule`` phải sửa tại chỗ mới tới được nó.
        self._schedule: ScheduleConfig = (
            schedule if schedule is not None else ScheduleConfig()
        )

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
        #: Thông điệp lỗi processor gần nhất, để chỉ log khi lỗi ĐỔI (thiếu
        #: tệp mô hình lặp lại mỗi khung; log hết sẽ ngập).
        self._processor_error: str | None = None

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
        lặp, nhưng **cũng không** bị hiểu thành "khung này không có mặt": một
        lỗi model chỉ nghĩa là lượt này không quan sát được, nên danh tính cũ
        được giữ nguyên và tự hết hạn theo :data:`IDENTITY_AGE_LIMIT_S`.

        ``processor`` có thể trả :data:`OBSERVATION_SKIPPED` để báo "bỏ qua
        lượt" (ví dụ cổng ``interval_s``); khi đó **không** gọi
        :meth:`_apply_observation` — danh tính cũ giữ nguyên, không bị ghi đè
        thành ``UNKNOWN``.

        Nhưng lượt bị bỏ **vẫn phải là một nhịp của đồng hồ đăng ký**. Lý do
        là một lỗi thật đã đo: model khuôn mặt hỏng ở *mọi* khung thì
        ``processor`` nào cũng trả sentinel; về sớm trước ``_collect_sample``
        nghĩa là ``_expire`` không bao giờ chạy (nó chỉ được gọi từ
        ``_collect_sample`` và ``enroll_status``, mà ``enroll_status`` chỉ có
        người gọi khi dashboard hỏi). Phiên ``running`` treo vĩnh viễn →
        :meth:`is_enrolling` mãi ``True`` → cổng ``interval_s`` bị tắt mãi →
        detect mỗi khung. Vì vậy ở đây vẫn gọi ``_collect_sample(None, ...)``:
        ``vector is None`` nên **không** thêm mẫu, chỉ cập nhật ``step_index``
        và chạy ``_expire``. Đây cũng là chỗ ``_lock`` cần: ``processor``
        chạy ngoài lock.
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
            # Chỉ log lần đầu và khi lỗi đổi khác: thiếu tệp mô hình là lỗi
            # lặp lại MỖI khung, ghi hết sẽ ngập log (xem bài học cooldown).
            message = str(exc)
            if message != self._processor_error:
                self._processor_error = message
                self._log.warning(
                    "Không xử lý được khung nhận diện khuôn mặt: %s", exc
                )
            # Lỗi model KHÔNG phải "không có mặt trong khung": giữ nguyên
            # danh tính cũ thay vì ghi đè thành UNKNOWN.
            raw = OBSERVATION_SKIPPED
        else:
            self._processor_error = None
        if raw is OBSERVATION_SKIPPED:
            # Lượt bị bỏ vẫn tick đồng hồ phiên đăng ký (xem docstring).
            with self._lock:
                self._collect_sample(None, moment)
            return
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

    def note_phone(self, state: str, now: float | None = None) -> None:
        """Ghi **riêng** tín hiệu điện thoại; tương đương ``phone=`` của
        :meth:`update_signals`.

        Có mặt để vòng lặp gọi được tín hiệu điện thoại mà không phải chạm
        vào ``update_signals``. Lý do là một lỗi thật đã xảy ra: vòng lặp chỉ
        gọi ``update_signals(presence=..., now=...)``, thiếu ``phone=``, nên
        dashboard vĩnh viễn hiện "chưa có dữ liệu" cho dòng điện thoại trong
        khi loa vẫn đọc câu "cất điện thoại" — hai nguồn sự thật rời nhau.

        Args:
            state: một trong :data:`PHONE_STATE_NONE` / :data:`PHONE_STATE_USE`
                (hoặc chuỗi khác do tầng gọi tự định nghĩa; lớp này không
                kiểm tra để không khoá cứng từ vựng của UI).
            now: mốc ``clock``; mặc định lấy từ ``clock`` của dịch vụ. Phải
                cùng gốc với ``observe``/``signals`` (``time.monotonic``),
                không phải ``now`` tương đối của vòng lặp.
        """
        moment = self._clock() if now is None else float(now)
        with self._lock:
            self._phone = {"state": str(state), "updated_at": moment}

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
        # Ngưỡng trong config luôn thắng; nếu chưa có thì dùng ngưỡng tự suy
        # từ dữ liệu đăng ký. Cả hai đều None mới là "chưa có ngưỡng".
        effective = self._threshold if self._threshold is not None else self._auto_threshold
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

    def is_enrolling(self) -> bool:
        """Có phiên đăng ký nào đang chạy không.

        Vòng lặp dùng cờ này để BỎ QUA cổng nhịp ``face.interval_s`` trong
        lúc đăng ký: cửa sổ đăng ký chỉ dài ``len(steps) * step_s`` (7,5 s) và
        mỗi bước chỉ nhận một mẫu, nên hai lần trượt detect rơi đúng nhịp cổng
        là đủ làm phiên thất bại. Đo thật: có cổng → ``failed`` 2/3 mẫu;
        không cổng → ``done`` 3/3.
        """
        with self._lock:
            return self._running_enrollment() is not None

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
        # Ngưỡng chỉ tự suy khi người dùng KHÔNG đặt tay trong config.
        if self._threshold is None:
            self._derive_auto_threshold(record["samples"])
        self._log.info(
            "Đã đăng ký khuôn mặt '%s' từ %d mẫu ở %d bước.",
            record["name"],
            len(record["samples"]),
            len(record["sampled_steps"]),
        )

    def _load_auto_threshold(self) -> None:
        """Nạp ngưỡng tự suy đã lưu ở lần chạy trước; không bao giờ ném.

        Thứ tự ưu tiên (spec yêu cầu): ``face.match_threshold`` trong config
        **luôn thắng**. Vì vậy khi ``self._threshold`` có giá trị thì hàm này
        không đọc tệp: ngưỡng lưu trên đĩa không thể thay đổi kết luận, nên
        đọc chỉ tốn I/O và có thể sinh cảnh báo gây nhiễu. Ngược lại, đây là
        đường **duy nhất** để ngưỡng tự suy sống qua restart — nếu bỏ nó,
        ``_classify`` thấy ``effective is None`` và trả ``UNKNOWN`` cho mọi
        khung, khiến cảnh báo "người khác vào học hộ" im lặng vĩnh viễn.

        Mọi trục trặc của tệp (thiếu, JSON rác, sai phiên bản, ngưỡng ngoài
        ``[-1, 1]``/không hữu hạn, không đọc được) đều kết thúc bằng **một**
        dòng cảnh báo và chế độ "chưa có ngưỡng". Không ném: dashboard và
        vòng lặp giám sát không được chết vì một tệp phụ (spec §11.3, §11.4).
        """
        if self._threshold is not None or self._threshold_path is None:
            return
        path = self._threshold_path
        try:
            if not path.exists():
                return
            text = path.read_text(encoding="utf-8")
            payload = json.loads(text)
            value = _parse_threshold_payload(payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._log.warning(
                "Bỏ qua ngưỡng nhận diện đã lưu ở '%s': %s. Chạy tiếp không "
                "có ngưỡng tự suy cho tới lần đăng ký kế tiếp.",
                path,
                exc,
            )
            return
        self._auto_threshold = value
        self._log.info(
            "Đã nạp lại ngưỡng nhận diện khuôn mặt %.2f từ '%s'.", value, path
        )

    def _save_auto_threshold(self, threshold: float) -> None:
        """Ghi ngưỡng tự suy xuống tệp phụ; lỗi ghi chỉ cảnh báo, không ném.

        Lỗi ghi (thẻ nhớ đầy, quyền) không được làm hỏng buổi đăng ký vừa
        thành công: ngưỡng vẫn dùng được trong RAM phiên này, chỉ mất tính
        bền. Vì vậy :class:`OSError` bị nuốt sau khi log.
        """
        path = self._threshold_path
        if path is None:
            return
        try:
            _write_threshold_file(path, threshold, self._clock())
        except OSError as exc:
            self._log.warning(
                "Không lưu được ngưỡng nhận diện vào '%s': %s. Ngưỡng vẫn "
                "dùng được trong phiên này nhưng sẽ mất khi khởi động lại.",
                path,
                exc,
            )
            return
        self._log.info("Đã lưu ngưỡng nhận diện khuôn mặt vào '%s'.", path)

    def _derive_auto_threshold(self, samples: Sequence[np.ndarray]) -> None:
        """Suy ngưỡng từ các mẫu vừa đăng ký, ghi xuống tệp phụ và giữ trong RAM.

        Chỉ chạy khi ``self._threshold is None`` (config không đặt tay).
        Không đủ mẫu để suy thì **giữ nguyên** trạng thái chưa có ngưỡng và
        ghi log lý do — tuyệt đối không điền một con số bịa.

        Ngưỡng **không** được ghi vào ``faces.json``: kho chỉ chứa vector
        (spec §5.13.1) và là hợp đồng đã có test. Nó sống ở **tệp phụ** cạnh
        kho (:data:`THRESHOLD_FILENAME`) để cảnh báo "người khác vào học hộ"
        vẫn hoạt động sau mỗi lần khởi động lại Pi.

        Đăng ký lại (người khác hoặc chính người cũ) suy ra ngưỡng mới và
        **ghi đè** tệp phụ: ngưỡng phản ánh dữ liệu mới nhất trên thiết bị.

        ``delete_person`` xoá người cuối cùng **không** xoá tệp phụ: ngưỡng
        chỉ là con số cosine, không định danh ai; kho rỗng thì ``_classify``
        đã trả "Chưa có ai được đăng ký trên thiết bị này" trước khi chạm tới
        ngưỡng, nên trạng thái đó vô hại. Giữ tệp phụ còn tránh một trạng
        thái nửa vời khác: xoá nhầm người rồi đăng ký lại mà phải chờ suy lại.
        """
        derived = derive_threshold(samples)
        if derived is None:
            self._log.warning(
                "Chưa tự suy được ngưỡng nhận diện: cần ít nhất 3 mẫu hợp lệ "
                "cùng số chiều (hiện có %d). Mọi quan sát vẫn là UNKNOWN.",
                len(samples),
            )
            return
        self._auto_threshold = derived
        self._save_auto_threshold(derived)
        self._log.info(
            "Đã tự suy ngưỡng nhận diện khuôn mặt %.2f từ dữ liệu đăng ký "
            "(%d mẫu, khoảng cách an toàn %.2f); lưu lại cho lần khởi động kế "
            "tiếp.",
            derived,
            len(samples),
            AUTO_THRESHOLD_MARGIN,
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
    # khung giờ học (spec §5.16)
    # ------------------------------------------------------------------
    def get_schedule(self) -> dict:
        """Khung giờ học hiện tại, cùng dạng với mục ``schedule`` của config.

        Returns:
            ``{"enabled": bool, "windows": [{"days": [...], "start": "HH:MM",
            "end": "HH:MM"}, ...], "kinds": {name: {"enabled": ...,
            "cooldown_s": ..., "hold_s": ...}}}``.

        **Không lưu qua lần khởi động lại.** Thay đổi từ
        :meth:`put_schedule` chỉ sống trong bộ nhớ; khởi động lại ``run`` sẽ
        đọc lại ``config.yaml``. Module này cố ý không có helper ghi YAML nào.
        """
        with self._lock:
            return _schedule_payload(self._schedule)

    def put_schedule(self, payload: Mapping[str, Any]) -> dict:
        """Kiểm tra rồi ghi khung giờ học vào **bộ nhớ**; trả cấu hình mới.

        Dùng lại đúng các hàm đọc của ``config.py``/``schedule.py``
        (:func:`~posture_monitor.schedule.parse_window`,
        :func:`~posture_monitor.schedule.parse_kind_settings`) để cú pháp và
        lời báo lỗi khớp với ``config.yaml``; giữ nguyên luật nghiệp vụ
        "``enabled: true`` với danh sách khung giờ rỗng là không hợp lệ".

        Payload **không** nằm trong danh sách khóa đã biết bị bỏ qua im lặng:
        khóa lạ là lỗi, để người dùng không tưởng nhầm là đã đặt.

        **Không ghi ra tệp.** Cấu hình mới mất khi khởi động lại; muốn bền
        thì sửa ``config.yaml`` tay. Ghi ngầm vào ``config.yaml`` sẽ làm hỏng
        định dạng/ghi chú người dùng tự viết — quyết định có chủ ý.

        **Sửa tại chỗ chứ không rebind.** Vòng lặp giám sát
        (``_monitor_loop``) lấy ``config.schedule`` **một lần** trước vòng
        lặp rồi truyền đúng đối tượng đó vào ``should_alert`` mỗi khung. Gán
        ``self._schedule = schedule`` chỉ đổi thuộc tính của dịch vụ, nên
        vòng lặp vẫn giữ đối tượng cũ và không bao giờ thấy khung giờ mới.
        Vì vậy ở đây chép nội dung mới **vào chính đối tượng** mà dịch vụ
        đang giữ (cũng là đối tượng ``config.schedule`` chia sẻ cho mọi bên).

        Thứ tự ghi: ``kinds``/``windows`` trước, ``enabled`` sau, để trạng
        thái trung gian khi bật giờ học không phải là "bật mà chưa có khung".

        Raises:
            PeopleServiceError: payload sai (không phải ánh xạ, khóa lạ,
                giờ/thứ sai, khung rỗng khi ``enabled``).
        """
        if not isinstance(payload, Mapping):
            raise PeopleServiceError(
                "Cấu hình giờ học phải là một đối tượng JSON."
            )
        schedule = _parse_schedule_payload(payload)
        with self._lock:
            # ``ScheduleConfig`` là dataclass thường (không frozen), nên sửa
            # tại chỗ được. Không thay ``self._schedule`` bằng đối tượng mới.
            self._schedule.kinds = schedule.kinds
            self._schedule.windows = schedule.windows
            self._schedule.enabled = schedule.enabled
        self._log.info(
            "Đã cập nhật giờ học trong bộ nhớ: enabled=%s, %d khung giờ.",
            schedule.enabled,
            len(schedule.windows),
        )
        return _schedule_payload(self._schedule)

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
