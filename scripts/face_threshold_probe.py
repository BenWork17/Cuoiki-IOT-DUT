"""Đo ngưỡng cosine cho ``face.match_threshold`` bằng mẫu thu trực tiếp từ camera.

Công cụ **chỉ đọc và in số**: không ghi ảnh, không ghi embedding ra đĩa, không
tự sửa ``config.yaml``. Người dùng đọc bảng rồi tự dán con số vào cấu hình.

Vì sao cần công cụ này: ``face.match_threshold`` để ``null`` chừng nào chưa
có phép đo trên camera thật (spec V3 §5.13, §14 bước H). Spec **cấm** chép
ngưỡng từ tài liệu OpenCV hay repo khác, nên không có sẵn số nào để điền và
tính năng nhận diện không bật được. Công cụ này sinh ra số đó:

1. Thu ``--samples`` khung có **đúng một** khuôn mặt cho người thứ nhất.
2. Lặp lại cho người thứ hai (``--name2``).
3. In phân bố cosine **trong cùng người** và **khác người**, bảng ngưỡng ứng
   viên với tỉ lệ bỏ sót / báo nhầm, rồi một dòng gợi ý để dán tay.

Khung có 0 khuôn mặt hoặc **hơn 1** khuôn mặt bị bỏ: khung nhiều mặt làm hỏng
phép đo (không biết vector thuộc về ai).

Chạy trên Pi (đúng thư mục repo, đã có ``yunet.onnx``/``sface.onnx``)::

    python scripts/face_threshold_probe.py --source "$POSTURE_CAMERA_SOURCE" \\
        --name "Chính chủ" --name2 "Người khác" --samples 10

Mã thoát:

- ``0`` — in được bảng ngưỡng ứng viên.
- ``2`` — thiếu mẫu, thiếu người thứ hai, không mở được camera, hoặc thiếu mô
  hình. Thông điệp tiếng Việt luôn nêu **lý do cụ thể**.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Sequence, TextIO

import numpy as np

# Cho phép chạy trực tiếp bằng `python scripts/face_threshold_probe.py` mà
# không cần cài gói: thêm thư mục src/ vào sys.path (như scripts/camera_probe.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.capture import (  # noqa: E402
    FrameSource,
    capture_from_config,
)
from posture_monitor.config import (  # noqa: E402
    CAMERA_SOURCE_ENV,
    CameraConfig,
    FaceConfig,
    _normalize_env_source,  # noqa: PLC2701 - dùng đúng chuẩn hoá của config
    redact_camera_source,
)
from posture_monitor.faces import (  # noqa: E402
    FaceError,
    FaceModelError,
    FaceRecognizer,
    cosine_similarity,
    normalise_embedding,
)

#: Mã thoát: in được bảng.
EXIT_OK = 0

#: Mã thoát: không đủ dữ liệu để kết luận (thiếu mẫu/người/camera/mô hình).
EXIT_INSUFFICIENT = 2

#: Số mẫu mặc định cho mỗi người.
DEFAULT_SAMPLES = 10

#: Số khung tối đa bỏ ra để thu mẫu, tính theo bội số của số mẫu cần.
#: Camera có thể đứng ở cảnh không có mặt; không giới hạn thì công cụ treo.
MAX_FRAMES_FACTOR = 20

#: Bước quét ngưỡng (spec: 0.05 → 0.95, bước 0.05).
THRESHOLD_STEP = 0.05

#: Số mức ngưỡng: 0.05, 0.10, ..., 0.95.
THRESHOLD_STEPS = 19


# ----------------------------------------------------------------------------
# Phần thuần số học — test được bằng vector dựng sẵn, không cần camera/mô hình.
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Distribution:
    """Phân bố cosine của một nhóm cặp."""

    count: int
    minimum: float
    median: float
    maximum: float


@dataclass(frozen=True)
class ThresholdRow:
    """Một dòng của bảng ngưỡng ứng viên."""

    threshold: float
    missed: int
    false_alarms: int


def within_person_pairs(vectors: Sequence[np.ndarray]) -> list[float]:
    """Cosine giữa **mọi cặp** mẫu của cùng một người (``i < j``)."""
    values: list[float] = []
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            values.append(cosine_similarity(vectors[i], vectors[j]))
    return values


def between_person_pairs(
    first: Sequence[np.ndarray], second: Sequence[np.ndarray]
) -> list[float]:
    """Cosine giữa mọi cặp ``(A_i, B_j)`` của hai người khác nhau."""
    return [
        cosine_similarity(a, b)
        for a in first
        for b in second
    ]


def summarise(values: Sequence[float]) -> Distribution | None:
    """Tóm tắt min / trung vị / max; ``None`` khi không có cặp nào."""
    if not values:
        return None
    return Distribution(
        count=len(values),
        minimum=float(min(values)),
        median=float(statistics.median(values)),
        maximum=float(max(values)),
    )


def threshold_table(
    same_person: Sequence[float], different_person: Sequence[float]
) -> list[ThresholdRow]:
    """Bảng 19 mức ngưỡng với số cặp bỏ sót và số cặp báo nhầm.

    - **bỏ sót**: cặp cùng người có cosine ``< t`` (ngưỡng cao quá → không
      nhận ra chính chủ).
    - **báo nhầm**: cặp khác người có cosine ``>= t`` (ngưỡng thấp quá → nhận
      người khác là chính chủ).
    """
    rows: list[ThresholdRow] = []
    for index in range(1, THRESHOLD_STEPS + 1):
        threshold = round(index * THRESHOLD_STEP, 10)
        missed = sum(1 for value in same_person if value < threshold)
        false_alarms = sum(
            1 for value in different_person if value >= threshold
        )
        rows.append(
            ThresholdRow(
                threshold=threshold,
                missed=missed,
                false_alarms=false_alarms,
            )
        )
    return rows


def pick_balance(
    rows: Sequence[ThresholdRow],
    same_total: int,
    different_total: int,
) -> ThresholdRow:
    """Chọn điểm cân bằng: ``|bỏ sót − báo nhầm|`` nhỏ nhất.

    Hoà thì chọn ngưỡng **cao hơn**: spec §3.4 coi báo nhầm nghiêm trọng hơn
    bỏ sót (gọi nhầm người lạ là chính chủ tệ hơn bỏ qua một lần nhận ra).

    Raises:
        ValueError: ``rows`` rỗng hoặc tổng số cặp bằng 0.
    """
    if not rows:
        raise ValueError("Không có dòng ngưỡng nào để chọn điểm cân bằng.")
    if same_total <= 0 or different_total <= 0:
        raise ValueError(
            "Cần cả cặp cùng người và cặp khác người mới chọn được ngưỡng."
        )

    def rank(row: ThresholdRow) -> tuple[float, float]:
        gap = abs(
            row.missed / same_total - row.false_alarms / different_total
        )
        # ``-threshold`` để ngưỡng cao hơn đứng trước khi ``gap`` bằng nhau.
        return (round(gap, 12), -row.threshold)

    return min(rows, key=rank)


def distributions_overlap(
    same_person: Distribution, different_person: Distribution
) -> bool:
    """Hai phân bố có chồng lấn không.

    Chồng lấn nghĩa là hai khoảng ``[min, max]`` giao nhau — không tồn tại
    mốc nào tách sạch hai nhóm.
    """
    return same_person.minimum <= different_person.maximum


# ----------------------------------------------------------------------------
# Thu mẫu từ camera
# ----------------------------------------------------------------------------
def collect_embeddings(
    recognizer: Any,
    source: FrameSource,
    name: str,
    samples: int,
    *,
    progress: TextIO = sys.stderr,
    max_frames: int | None = None,
) -> tuple[list[np.ndarray], bool]:
    """Thu ``samples`` embedding đã chuẩn hoá của khuôn mặt trong ``name``.

    Chỉ nhận khung có **đúng một** khuôn mặt dùng được; khung 0 mặt hoặc >1
    mặt bị bỏ. Chỉ vector được giữ trong RAM — không ghi ảnh.

    Returns:
        ``(vectors, camera_exhausted)``; ``camera_exhausted`` là ``True`` khi
        nguồn ảnh hết khung trước khi thu đủ mẫu.
    """
    limit = max_frames if max_frames is not None else samples * MAX_FRAMES_FACTOR
    vectors: list[np.ndarray] = []
    exhausted = False
    frames_read = 0

    while len(vectors) < samples and frames_read < limit:
        frame = source.read()
        frames_read += 1
        if frame is None:
            exhausted = True
            break
        try:
            faces = recognizer.detect(frame)
        except ValueError:
            continue
        if len(faces) != 1:
            # Khung nhiều mặt: không biết vector thuộc về ai → bỏ.
            continue
        try:
            vector = recognizer.embedding(frame, faces[0])
        except ValueError:
            continue
        vectors.append(normalise_embedding(vector))
        print(
            f"Đã thu {len(vectors)}/{samples} mẫu cho '{name}'",
            file=progress,
        )
    return vectors, exhausted


# ----------------------------------------------------------------------------
# In kết quả
# ----------------------------------------------------------------------------
def _print_distribution(
    label: str, distribution: Distribution | None, out: TextIO
) -> None:
    if distribution is None:
        print(f"  {label}: (không có cặp nào)", file=out)
        return
    print(
        f"  {label} ({distribution.count} cặp): "
        f"min {distribution.minimum:.3f}   "
        f"trung vị {distribution.median:.3f}   "
        f"max {distribution.maximum:.3f}",
        file=out,
    )


def _print_table(
    rows: Sequence[ThresholdRow],
    same_total: int,
    different_total: int,
    balance: ThresholdRow,
    out: TextIO,
) -> None:
    print("  Bảng ngưỡng ứng viên:", file=out)
    print(f"    {'ngưỡng':>7}  {'bỏ sót':>9}  {'báo nhầm':>9}", file=out)
    print("    " + "-" * 29, file=out)
    for row in rows:
        marker = "  <== cân bằng" if row.threshold == balance.threshold else ""
        print(
            f"    {row.threshold:>7.2f}  "
            f"{row.missed / same_total * 100:>8.1f}%  "
            f"{row.false_alarms / different_total * 100:>8.1f}%"
            f"{marker}",
            file=out,
        )


def _print_suggestion(
    threshold: float,
    samples: int,
    people: int,
    measured_on: str,
    out: TextIO,
) -> None:
    print(file=out)
    print("  Gợi ý — dán tay dòng dưới vào config.yaml, mục 'face':", file=out)
    print(
        f"      match_threshold: {threshold:.2f}   "
        f"# đo {measured_on}, {samples} mẫu/người, {people} người",
        file=out,
    )
    print(
        "  Con số này chỉ đúng với camera/ánh sáng/vị trí đo hôm nay; đổi "
        "chỗ ngồi hoặc đổi camera thì phải đo lại.",
        file=out,
    )


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def _default_source() -> str:
    """Nguồn ảnh mặc định: ``POSTURE_CAMERA_SOURCE`` nếu có, không thì ``usb:0``."""
    override = os.environ.get(CAMERA_SOURCE_ENV, "").strip()
    if override:
        return _normalize_env_source(override)
    return "usb:0"


def _open_source(source_text: str) -> FrameSource | None:
    """Mở nguồn ảnh qua đúng đường của ứng dụng chính."""
    config = SimpleNamespace(camera=CameraConfig(source=source_text))
    return capture_from_config(config)


def _build_recognizer() -> FaceRecognizer:
    defaults = FaceConfig()
    return FaceRecognizer(defaults.detector, defaults.recognizer)


def _ensure_utf8_stdio() -> None:
    """Ép ``stdout``/``stderr`` sang UTF-8 khi có thể.

    Thông điệp ở đây là tiếng Việt. Trên Windows, khi đầu ra bị chuyển hướng
    (ghi ra tệp hoặc pipe), ``sys.stdout`` mặc định dùng code page ANSI và
    ``print`` ném ``UnicodeEncodeError`` giữa chừng — công cụ chết trước khi
    in xong bảng. Trên Pi locale vốn là UTF-8 nên đây là lưới an toàn.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            # Stream không cho đổi (đã đóng, đang bị bọc) — bỏ qua.
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="face_threshold_probe",
        description=(
            "Đo ngưỡng cosine cho face.match_threshold từ camera thật. "
            "Chỉ đọc và in số, không ghi ảnh và không sửa config.yaml."
        ),
    )
    parser.add_argument(
        "--source",
        default=None,
        help=(
            f"nguồn ảnh (usb:N, picamera, file:..., rtsp:...). Mặc định lấy "
            f"{CAMERA_SOURCE_ENV}, không có thì usb:0"
        ),
    )
    parser.add_argument(
        "--name",
        required=True,
        help="tên người thứ nhất, chỉ dùng để in tiến độ",
    )
    parser.add_argument(
        "--name2",
        default=None,
        help="tên người thứ hai; thiếu thì chỉ in phân bố trong cùng người",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=DEFAULT_SAMPLES,
        help=f"số mẫu mỗi người (mặc định {DEFAULT_SAMPLES})",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    source_factory: Callable[[str], FrameSource | None] | None = None,
    recognizer_factory: Callable[[], Any] | None = None,
    today: Callable[[], str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Chạy công cụ; trả mã thoát. Tham số tiêm được để test không cần camera."""
    _ensure_utf8_stdio()
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    open_source = source_factory or _open_source
    make_recognizer = recognizer_factory or _build_recognizer
    measured_on = today() if today is not None else date.today().isoformat()

    args = build_parser().parse_args(list(argv) if argv is not None else None)

    name = str(args.name).strip()
    name2 = str(args.name2).strip() if args.name2 else None
    samples = int(args.samples)

    print("=" * 74, file=out)
    print("  ĐO NGƯỠNG KHUÔN MẶT — Hệ thống giám sát tư thế", file=out)
    print("=" * 74, file=out)

    if not name:
        print("  LỖI: --name không được để trống.", file=out)
        return EXIT_INSUFFICIENT
    if name2 is not None and not name2:
        print("  LỖI: --name2 được truyền nhưng để trống.", file=out)
        return EXIT_INSUFFICIENT
    if name2 is not None and name2 == name:
        print(
            "  LỖI: --name2 phải là người KHÁC --name; trùng tên thì phép đo "
            "khác-người không có nghĩa.",
            file=out,
        )
        return EXIT_INSUFFICIENT
    if samples < 2:
        print(
            f"  LỖI: --samples phải >= 2 (cần ít nhất 2 mẫu mới có một cặp "
            f"cùng người), nhận được {samples}.",
            file=out,
        )
        return EXIT_INSUFFICIENT

    source_text = args.source or _default_source()
    # Nguồn có thể chứa mật khẩu camera: chỉ in bản đã che.
    print(f"  Nguồn ảnh: {redact_camera_source(source_text)}", file=out)
    print(f"  Mẫu mỗi người: {samples}", file=out)

    try:
        recognizer = make_recognizer()
    except FaceModelError as exc:
        print(f"  LỖI: không dựng được bộ nhận diện: {exc}", file=out)
        return EXIT_INSUFFICIENT

    source = open_source(source_text)
    if source is None:
        print(
            "  LỖI: không mở được nguồn ảnh "
            f"{redact_camera_source(source_text)}. Kiểm tra camera đã cắm/bật, "
            "đúng địa chỉ và đúng luồng phụ; chạy "
            "'python scripts/camera_probe.py' để xem thiết bị.",
            file=out,
        )
        return EXIT_INSUFFICIENT

    try:
        print(file=out)
        print(f"  Thu mẫu cho '{name}' — nhìn thẳng camera.", file=out)
        first, exhausted = collect_embeddings(
            recognizer, source, name, samples, progress=err
        )
        if len(first) < samples:
            reason = (
                "nguồn ảnh hết khung" if exhausted else "hết số khung cho phép"
            )
            print(
                f"  LỖI: chỉ thu được {len(first)}/{samples} mẫu cho '{name}' "
                f"({reason}). Cần đủ mẫu mới đo được phân bố; hãy thử lại ở "
                "nơi đủ sáng và chỉ một người trong khung.",
                file=out,
            )
            return EXIT_INSUFFICIENT

        same_pairs = within_person_pairs(first)
        same_dist = summarise(same_pairs)
        print(file=out)
        _print_distribution(f"Trong cùng người '{name}'", same_dist, out)

        if name2 is None:
            print(file=out)
            print(
                "  CHƯA ĐỦ ĐỂ CHỌN NGƯỠNG: mới đo một người, chưa có phân bố "
                "'khác người' để so. Cần người thứ hai bằng --name2 (người "
                "KHÁC ngồi vào cùng chỗ) thì mới chọn được ngưỡng. Không có "
                "số nào được gợi ý ở đây.",
                file=out,
            )
            return EXIT_INSUFFICIENT

        print(file=out)
        print(f"  Thu mẫu cho '{name2}' — người khác ngồi vào đúng chỗ đó.", file=out)
        second, exhausted2 = collect_embeddings(
            recognizer, source, name2, samples, progress=err
        )
        if len(second) < samples:
            reason = (
                "nguồn ảnh hết khung" if exhausted2 else "hết số khung cho phép"
            )
            print(
                f"  LỖI: chỉ thu được {len(second)}/{samples} mẫu cho "
                f"'{name2}' ({reason}). Cần đủ mẫu mới đo được phân bố; hãy "
                "thử lại ở nơi đủ sáng và chỉ một người trong khung.",
                file=out,
            )
            return EXIT_INSUFFICIENT
    except FaceModelError as exc:
        print(f"  LỖI: không dùng được mô hình nhận diện: {exc}", file=out)
        return EXIT_INSUFFICIENT
    except FaceError as exc:
        print(f"  LỖI: {exc}", file=out)
        return EXIT_INSUFFICIENT
    finally:
        source.close()

    diff_pairs = between_person_pairs(first, second)
    diff_dist = summarise(diff_pairs)
    print(file=out)
    _print_distribution(
        f"Khác người '{name}' ↔ '{name2}'", diff_dist, out
    )

    rows = threshold_table(same_pairs, diff_pairs)
    balance = pick_balance(rows, len(same_pairs), len(diff_pairs))
    print(file=out)
    _print_table(rows, len(same_pairs), len(diff_pairs), balance, out)

    print(file=out)
    if distributions_overlap(same_dist, diff_dist):
        print(
            f"  CẢNH BÁO: hai phân bố chồng lấn, không có ngưỡng nào tách sạch "
            f"với {samples} mẫu/người. Điểm 'cân bằng' "
            f"{balance.threshold:.2f} chỉ là chỗ hai loại lỗi gần bằng nhau, "
            "KHÔNG phải một ngưỡng dùng được. Hãy thu thêm mẫu (ánh sáng tốt "
            "hơn, mặt nhìn thẳng hơn) rồi đo lại.",
            file=out,
        )
        return EXIT_OK

    print(
        f"  Điểm cân bằng: ngưỡng {balance.threshold:.2f} "
        f"(bỏ sót {balance.missed / len(same_pairs) * 100:.1f}%, "
        f"báo nhầm {balance.false_alarms / len(diff_pairs) * 100:.1f}%).",
        file=out,
    )
    _print_suggestion(balance.threshold, samples, 2, measured_on, out)
    print("=" * 74, file=out)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
