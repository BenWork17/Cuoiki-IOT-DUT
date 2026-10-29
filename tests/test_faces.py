"""Unit test cho ``faces.py`` (nhận diện khuôn mặt bằng YuNet + SFace).

Chạy trên PC, **không cần tệp mô hình, không cần camera, không cần mạng**:

- Không test nào nạp ``yunet.onnx``/``sface.onnx`` thật: mô hình là 37 MB và
  đầu ra phụ thuộc phiên bản OpenCV, nên mọi phép đo dùng vector dựng tay.
  Phần cần OpenCV (phát hiện/cắt/trích đặc trưng) được kiểm tra ở mức hợp
  đồng: thiếu tệp mô hình phải ra :class:`FaceModelError` tiếng Việt, không
  được crash lúc import hay lúc khởi tạo.
- Thư mục dữ liệu là ``tmp_path``; không test nào chạm vào thư mục dữ liệu
  thật của ứng dụng.
- Kho chỉ chứa vector, tên và thời điểm — test khẳng định không có ảnh nào
  được ghi ra đĩa (spec v2 §11.5).
"""

from __future__ import annotations

import json
import logging
import math
import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor import faces  # noqa: E402
from posture_monitor.faces import (  # noqa: E402
    DEFAULT_MATCH_THRESHOLD,
    EMBEDDING_DIM,
    MIN_ENROL_FRAMES,
    STORE_FILENAME,
    UNKNOWN_NAME,
    FaceError,
    FaceModelError,
    FaceRecognizer,
    FaceStore,
    FaceStoreError,
    Person,
    average_embedding,
    best_disqualified,
    best_match,
    build_store_payload,
    cosine_similarity,
    enrol_embeddings,
    normalise_embedding,
    parse_store_payload,
)

#: Mốc thời gian cố định để ``enrolled_at`` tất định.
FIXED_NOW = 1_790_000_000.0

#: Ảnh tệp mà kho **không được** chứa.
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".mp4", ".avi"}


def unit(*values: float) -> np.ndarray:
    """Vector đơn vị từ các thành phần cho trước."""
    return normalise_embedding(np.asarray(values, dtype=np.float32))


def make_store(tmp_path: Path) -> FaceStore:
    """Kho với đồng hồ cố định trong ``tmp_path``."""
    return FaceStore(tmp_path / "du-lieu", clock=lambda: FIXED_NOW)


# ---------------------------------------------------------------------------
# Cosine
# ---------------------------------------------------------------------------
def test_cosine_identical_vectors_is_one() -> None:
    vector = unit(0.3, -1.2, 2.5, 0.0)
    assert cosine_similarity(vector, vector) == pytest.approx(1.0, abs=1e-6)


def test_cosine_opposite_vectors_is_minus_one() -> None:
    vector = unit(1.0, 2.0, -3.0)
    assert cosine_similarity(vector, -vector) == pytest.approx(-1.0, abs=1e-6)


def test_cosine_orthogonal_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_ignores_magnitude() -> None:
    """Cosine so hướng, không so độ dài; vector chưa chuẩn hoá vẫn đúng."""
    assert cosine_similarity([2.0, 0.0], [10.0, 0.0]) == pytest.approx(1.0)


@pytest.mark.parametrize(
    "first, second, fragment",
    [
        ([1.0, 2.0], [1.0, 2.0, 3.0], "khác số chiều"),
        ([], [1.0], "rỗng"),
        ([0.0, 0.0], [1.0, 0.0], "độ dài bằng 0"),
        ([float("nan"), 1.0], [1.0, 1.0], "NaN"),
        ([float("inf"), 1.0], [1.0, 1.0], "NaN"),
    ],
)
def test_cosine_rejects_unusable_vectors(
    first: list[float], second: list[float], fragment: str
) -> None:
    with pytest.raises(ValueError, match=fragment):
        cosine_similarity(first, second)


def test_normalise_embedding_returns_unit_vector() -> None:
    result = normalise_embedding([3.0, 4.0])
    assert np.linalg.norm(result) == pytest.approx(1.0)
    assert result.dtype == np.float32


@pytest.mark.parametrize(
    "bad",
    [[], [0.0, 0.0], [float("nan")], [float("inf"), 1.0]],
)
def test_normalise_embedding_rejects_degenerate(bad: list[float]) -> None:
    with pytest.raises(ValueError):
        normalise_embedding(bad)


# ---------------------------------------------------------------------------
# Gộp nhiều khung khi đăng ký
# ---------------------------------------------------------------------------
def test_average_embedding_is_normalised_mean() -> None:
    merged = average_embedding([[1.0, 0.0], [0.0, 1.0]])
    assert merged is not None
    expected = np.asarray([0.5, 0.5], dtype=np.float32)
    expected = expected / np.linalg.norm(expected)
    np.testing.assert_allclose(merged, expected, atol=1e-6)
    assert np.linalg.norm(merged) == pytest.approx(1.0, abs=1e-6)


def test_average_embedding_empty_is_none() -> None:
    assert average_embedding([]) is None


def test_average_embedding_cancelling_vectors_is_none() -> None:
    """Hai vector ngược hướng triệt tiêu: trung bình không dùng được."""
    assert average_embedding([[1.0, 0.0], [-1.0, 0.0]]) is None


def test_average_embedding_rejects_dimension_mismatch() -> None:
    with pytest.raises(ValueError, match="khác số chiều"):
        average_embedding([[1.0, 0.0], [1.0, 0.0, 0.0]])


# ---------------------------------------------------------------------------
# Chọn người khớp
# ---------------------------------------------------------------------------
def _three_people() -> list[tuple[str, np.ndarray]]:
    return [
        ("An", unit(1.0, 0.0, 0.0)),
        ("Bình", unit(0.0, 1.0, 0.0)),
        ("Chi", unit(0.0, 0.0, 1.0)),
    ]


def test_best_match_picks_correct_person_among_three() -> None:
    query = unit(0.9, 0.1, 0.0)
    result = best_match(query, _three_people(), threshold=0.5)
    assert result.name == "An"
    assert result.known is True
    assert result.label == "An"
    assert result.score > 0.9


def test_best_match_picks_each_person() -> None:
    for expected, query in (
        ("An", unit(1.0, 0.05, 0.0)),
        ("Bình", unit(0.05, 1.0, 0.0)),
        ("Chi", unit(0.0, 0.05, 1.0)),
    ):
        result = best_match(query, _three_people(), threshold=0.5)
        assert result.name == expected


def test_best_match_below_threshold_is_unknown() -> None:
    """Query nằm giữa ba người: điểm cao nhất ~0.577, dưới ngưỡng 0.9."""
    query = unit(1.0, 1.0, 1.0)  # cos với mỗi người = 1/sqrt(3)
    result = best_match(query, _three_people(), threshold=0.9)
    assert result.name is None
    assert result.known is False
    assert result.label == UNKNOWN_NAME
    assert result.message
    # Điểm vẫn được trả để người vận hành chỉnh ngưỡng có căn cứ.
    assert result.score == pytest.approx(1.0 / math.sqrt(3.0), abs=1e-6)
    assert 0.0 < result.score < 0.9


def test_best_match_empty_store_is_unknown() -> None:
    result = best_match([1.0, 0.0], [], threshold=0.3)
    assert result.name is None
    assert result.score == 0.0
    assert result.label == UNKNOWN_NAME
    assert "Chưa có ai" in result.message


def test_best_match_threshold_is_inclusive() -> None:
    """Điểm bằng đúng ngưỡng phải được nhận (``>=``, không phải ``>``)."""
    query = unit(1.0, 0.0)
    entry = unit(0.6, 0.8)  # cos = 0.6
    result = best_match(query, [("Ai đó", entry)], threshold=0.6)
    assert result.name == "Ai đó"


def test_best_disqualified_is_false_at_threshold() -> None:
    assert best_disqualified(0.6, 0.6) is False
    assert best_disqualified(0.59, 0.6) is True
    assert best_disqualified(-0.5, -0.9) is False


def test_best_match_skips_unusable_entry_but_keeps_others() -> None:
    """Một embedding hỏng không được làm mất khả năng nhận ra người khác."""
    entries = [
        ("Hỏng", np.asarray([], dtype=np.float32)),
        ("Hỏng2", np.asarray([1.0, float("nan")], dtype=np.float32)),
        ("Tốt", unit(1.0, 0.0)),
    ]
    result = best_match(unit(1.0, 0.0), entries, threshold=0.5)
    assert result.name == "Tốt"


def test_best_match_handles_garbage_query() -> None:
    result = best_match([float("nan"), 1.0], _three_people(), threshold=0.3)
    assert result.name is None
    assert "không hợp lệ" in result.message.lower()


# ---------------------------------------------------------------------------
# Kho: ghi / đọc / xoá
# ---------------------------------------------------------------------------
def test_store_roundtrip_preserves_embedding(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    vector = unit(*(np.linspace(0.1, 1.0, EMBEDDING_DIM)))
    store.add("An", vector)

    reloaded = FaceStore(store.data_dir, clock=lambda: FIXED_NOW)
    people = reloaded.load()
    assert [person.name for person in people] == ["An"]
    np.testing.assert_allclose(people[0].embedding, vector, atol=1e-6)
    assert people[0].enrolled_at == FIXED_NOW


def test_store_missing_file_is_empty(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    assert store.load() == []
    assert store.pairs() == []
    assert store.names() == []


def test_store_add_updates_instead_of_duplicating(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add("An", unit(1.0, 0.0))
    store.add("An", unit(0.0, 1.0))

    people = store.load()
    assert len(people) == 1
    np.testing.assert_allclose(people[0].embedding, unit(0.0, 1.0), atol=1e-6)


def test_store_add_strips_name_and_rejects_blank(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add("  An  ", unit(1.0, 0.0))
    assert store.names() == ["An"]
    with pytest.raises(ValueError, match="không được để trống"):
        store.add("   ", unit(1.0, 0.0))


def test_store_remove_person(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add("An", unit(1.0, 0.0))
    store.add("Bình", unit(0.0, 1.0))

    assert store.remove("An") is True
    assert store.names() == ["Bình"]
    assert store.remove("An") is False
    assert store.names() == ["Bình"]


def test_store_get_person(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add("An", unit(1.0, 0.0))
    assert store.get("An") is not None
    assert store.get("Không có") is None


def test_store_multiple_people_roundtrip(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    for name, vector in _three_people():
        store.add(name, vector)
    reloaded = FaceStore(store.data_dir, clock=lambda: FIXED_NOW)
    # So sánh tập tên, không so thứ tự: sắp xếp chuỗi tiếng Việt theo mã điểm
    # không phải thứ tự người đọc mong đợi và không thuộc hợp đồng của kho.
    assert set(reloaded.names()) == {"An", "Bình", "Chi"}
    assert len(reloaded.load()) == 3


# ---------------------------------------------------------------------------
# Kho: tệp hỏng
# ---------------------------------------------------------------------------
def test_store_corrupt_json_raises_clear_vietnamese_error(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    store.data_dir.mkdir(parents=True, exist_ok=True)
    store.path.write_text('{"version": 1, "people": [', encoding="utf-8")

    with pytest.raises(FaceStoreError) as excinfo:
        store.load()
    message = str(excinfo.value)
    assert "bị hỏng" in message
    assert str(store.path) in message


def test_store_corrupt_json_pairs_does_not_crash_and_logs_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Đường dùng trong vòng lặp giám sát phải nuốt lỗi, không ném."""
    store = make_store(tmp_path)
    store.data_dir.mkdir(parents=True, exist_ok=True)
    store.path.write_text("không phải json", encoding="utf-8")

    with caplog.at_level(logging.ERROR, logger="posture_monitor.faces"):
        assert store.pairs() == []
        assert store.names() == []
        assert store.get("An") is None

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1, "kho hỏng chỉ được log một lần, không ngập log"


def test_store_empty_file_reports_truncation(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.data_dir.mkdir(parents=True, exist_ok=True)
    store.path.write_text("   \n", encoding="utf-8")
    with pytest.raises(FaceStoreError, match="cắt cụt"):
        store.load()


def test_store_add_refuses_to_overwrite_corrupt_file(tmp_path: Path) -> None:
    """Ghi đè mù lên tệp hỏng sẽ xoá sạch người đã đăng ký một cách im lặng."""
    store = make_store(tmp_path)
    store.data_dir.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{rac", encoding="utf-8")

    with pytest.raises(FaceStoreError):
        store.add("An", unit(1.0, 0.0))
    # Tệp hỏng vẫn còn nguyên để người vận hành cứu dữ liệu / xoá có ý thức.
    assert store.path.read_text(encoding="utf-8") == "{rac"


@pytest.mark.parametrize(
    "payload, fragment",
    [
        ([], "đối tượng JSON"),
        ({"version": 99, "people": []}, "phiên bản"),
        ({"version": 1}, "people"),
        ({"version": 1, "people": ["An"]}, "không\\s*phải đối tượng"),
        ({"version": 1, "people": [{"name": "  ", "embedding": [1, 0]}]}, "thiếu tên"),
        ({"version": 1, "people": [{"name": "An"}]}, "thiếu vector"),
        ({"version": 1, "people": [{"name": "An", "embedding": []}]}, "thiếu vector"),
        (
            {"version": 1, "people": [{"name": "An", "embedding": [0, 0]}]},
            "không dùng được",
        ),
        (
            {
                "version": 1,
                "people": [
                    {"name": "An", "embedding": [1, 0]},
                    {"name": "An", "embedding": [0, 1]},
                ],
            },
            "trùng",
        ),
        (
            {
                "version": 1,
                "people": [
                    {"name": "An", "embedding": [1, 0], "enrolled_at": "hôm qua"}
                ],
            },
            "không phải số",
        ),
    ],
)
def test_parse_store_payload_rejects_bad_data(
    payload: object, fragment: str
) -> None:
    with pytest.raises(FaceStoreError, match=fragment):
        parse_store_payload(payload)


def test_parse_store_payload_accepts_valid(tmp_path: Path) -> None:
    people = parse_store_payload(
        {
            "version": 1,
            "people": [
                {"name": " An ", "enrolled_at": 12, "embedding": [3, 4]},
            ],
        }
    )
    assert len(people) == 1
    assert people[0].name == "An"
    assert people[0].enrolled_at == 12.0
    np.testing.assert_allclose(people[0].embedding, [0.6, 0.8], atol=1e-6)


# ---------------------------------------------------------------------------
# Ghi nguyên tử và không lưu ảnh
# ---------------------------------------------------------------------------
def test_write_is_atomic_and_leaves_no_temp_file(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add("An", unit(1.0, 0.0))
    store.add("Bình", unit(0.0, 1.0))
    store.remove("An")

    files = sorted(p.name for p in store.data_dir.iterdir())
    assert files == [STORE_FILENAME], f"còn tệp lạ sau khi ghi: {files}"


def test_write_failure_leaves_previous_store_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Giả lập mất điện giữa lúc ghi: tệp cũ phải còn nguyên, không nửa vời.

    Đây là phép thử thật của ghi nguyên tử, không chỉ "không còn tệp tạm":
    nếu mã ghi thẳng vào tệp thật (bỏ bước tệp tạm + ``os.replace``) thì lúc
    ``fsync`` ném lỗi, tệp thật đã bị ghi đè dở và test này đỏ.
    """
    store = make_store(tmp_path)
    store.add("An", unit(1.0, 0.0))
    original = store.path.read_text(encoding="utf-8")

    def failing_fsync(fd: int) -> None:
        raise OSError(5, "Lỗi đĩa giả lập")

    monkeypatch.setattr(faces.os, "fsync", failing_fsync)

    with pytest.raises(FaceStoreError, match="Không ghi được"):
        store.add("Bình", unit(0.0, 1.0))

    monkeypatch.undo()
    # Nội dung cũ y nguyên — không có "An" lẫn "Bình", không bị cắt cụt.
    assert store.path.read_text(encoding="utf-8") == original
    assert store.names() == ["An"]
    # Và không để lại rác tệp tạm.
    files = sorted(p.name for p in store.data_dir.iterdir())
    assert files == [STORE_FILENAME], f"còn tệp tạm sau lỗi ghi: {files}"


def test_store_writes_no_images(tmp_path: Path) -> None:
    """Spec v2 §11.5: chỉ vector, không ảnh/video, kể cả ảnh khuôn mặt."""
    store = make_store(tmp_path)
    vector = unit(*(np.random.default_rng(7).random(EMBEDDING_DIM).astype(np.float32)))
    store.add("An", vector)
    store.add("Bình", unit(1.0, 0.0))

    written = list(store.data_dir.rglob("*"))
    assert written, "phải có tệp kho"
    for path in written:
        assert path.suffix.lower() not in IMAGE_SUFFIXES, (
            f"phát hiện tệp ảnh/video trong thư mục dữ liệu: {path}"
        )
        assert path.suffix.lower() != ".npz" or path.name == STORE_FILENAME


def test_payload_contains_only_vectors_names_and_time() -> None:
    payload = build_store_payload(
        [Person("An", unit(1.0, 0.0), FIXED_NOW)]
    )
    assert set(payload) == {"version", "people"}
    assert set(payload["people"][0]) == {"name", "enrolled_at", "embedding"}
    # Mọi phần tử của embedding phải là số (không có base64 ảnh, không bytes).
    assert all(
        isinstance(value, float)
        for value in payload["people"][0]["embedding"]
    )


# ---------------------------------------------------------------------------
# Đăng ký: đếm khung và cảnh báo
# ---------------------------------------------------------------------------
def test_enrol_uses_all_usable_frames(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    result = enrol_embeddings(
        store,
        "An",
        [unit(1.0, 0.0), unit(0.9, 0.1), unit(0.8, 0.2)],
        total_frames=5,
    )
    assert result.name == "An"
    assert result.used == 3
    assert result.total == 5
    assert result.warning is None
    assert store.names() == ["An"]


def test_enrol_warns_when_too_few_frames(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    result = enrol_embeddings(
        store, "An", [unit(1.0, 0.0), unit(0.9, 0.1)], total_frames=4
    )
    assert result.used == 2
    assert result.total == 4
    assert result.warning is not None
    assert "2/4" in result.warning
    assert str(MIN_ENROL_FRAMES) in result.warning
    # Vẫn lưu, chỉ cảnh báo.
    assert store.names() == ["An"]


def test_enrol_with_no_usable_frames_raises(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    with pytest.raises(FaceError, match="không có khuôn mặt hợp lệ"):
        enrol_embeddings(store, "An", [], total_frames=5)
    assert store.names() == []


def test_enrol_rejects_blank_name(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    with pytest.raises(ValueError, match="không được để trống"):
        enrol_embeddings(store, "  ", [unit(1.0, 0.0)])


def test_enrol_result_embedding_matches_mean(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    first, second = unit(1.0, 0.0, 0.0), unit(0.0, 1.0, 0.0)
    enrol_embeddings(store, "An", [first, second])

    stored = store.get("An")
    assert stored is not None
    expected = average_embedding([first, second])
    assert expected is not None
    np.testing.assert_allclose(stored.embedding, expected, atol=1e-6)


# ---------------------------------------------------------------------------
# OpenCV: thiếu mô hình phải báo lỗi tiếng Việt, không crash
# ---------------------------------------------------------------------------
def test_import_and_construct_without_models_is_safe(tmp_path: Path) -> None:
    """Tạo đối tượng không được mở tệp mô hình (nạp lười)."""
    recognizer = FaceRecognizer(
        tmp_path / "khong-co-yunet.onnx",
        tmp_path / "khong-co-sface.onnx",
    )
    assert recognizer.min_face_px == faces.DEFAULT_MIN_FACE_PX
    # Không tạo tệp nào cả.
    assert list(tmp_path.iterdir()) == []


def test_missing_model_raises_vietnamese_error(tmp_path: Path) -> None:
    recognizer = FaceRecognizer(
        tmp_path / "khong-co-yunet.onnx",
        tmp_path / "khong-co-sface.onnx",
    )
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    with pytest.raises(FaceModelError) as excinfo:
        recognizer.detect(frame)
    message = str(excinfo.value)
    assert "Thiếu tệp mô hình" in message
    assert "yunet.onnx" in message
    assert "sface.onnx" in message
    # Cả hai đường dẫn thiếu đều được nêu, không chỉ đường đầu tiên.
    assert str(tmp_path / "khong-co-sface.onnx") in message


def test_missing_model_recognize_raises_not_silent(tmp_path: Path) -> None:
    """Thiếu mô hình là lỗi cấu hình, phải nổi lên chứ không nuốt thành unknown."""
    store = make_store(tmp_path)
    store.add("An", unit(1.0, 0.0))
    recognizer = FaceRecognizer(
        tmp_path / "a.onnx", tmp_path / "b.onnx"
    )
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    with pytest.raises(FaceModelError):
        recognizer.recognize(store, frame)


def test_detect_rejects_invalid_frame(tmp_path: Path) -> None:
    """Ảnh không hợp lệ ra ``ValueError``, không phải IndexError khó hiểu."""
    recognizer = FaceRecognizer(tmp_path / "a.onnx", tmp_path / "b.onnx")
    # Không có mô hình thì lỗi mô hình đến trước; kiểm tra hợp đồng bằng
    # cách giả lập trạng thái "đã nạp" để đi tới phần kiểm tra khung hình.
    recognizer._cv2 = object()  # type: ignore[assignment]
    recognizer._detector = object()  # type: ignore[assignment]
    recognizer._recognizer = object()  # type: ignore[assignment]
    with pytest.raises(ValueError, match="không hợp lệ"):
        recognizer.detect(None)


# ---------------------------------------------------------------------------
# Không log dữ liệu sinh trắc học
# ---------------------------------------------------------------------------
def test_embeddings_are_never_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = make_store(tmp_path)
    vector = unit(0.123456789, -0.987654321, 0.5555555555, 0.3141592653)

    with caplog.at_level(logging.DEBUG, logger="posture_monitor.faces"):
        store.add("An", vector)
        store.load()
        store.names()
        best_match(vector, store.pairs(), threshold=0.5)

    text = "\n".join(record.getMessage() for record in caplog.records)
    for value in vector:
        rendered = repr(float(value))
        assert rendered not in text, f"vector bị log ra: {rendered}"
        assert f"{float(value):.6f}" not in text
    # Log tên người thì được phép.
    assert "An" in text


def test_default_threshold_is_documented_opencv_value() -> None:
    """Ngưỡng mặc định là tham số, không phải hằng số nghiệp vụ; giữ đúng số."""
    assert DEFAULT_MATCH_THRESHOLD == pytest.approx(0.363)


def test_unknown_label_is_vietnamese() -> None:
    assert UNKNOWN_NAME == "không biết"
    assert math.isfinite(DEFAULT_MATCH_THRESHOLD)
