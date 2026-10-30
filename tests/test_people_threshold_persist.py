"""Test ngưỡng nhận diện tự suy **bền qua lần khởi động lại**.

Lỗi thật đang được chặn ở đây: ngưỡng tự suy chỉ sống trong RAM, nên mỗi lần
restart Pi, ``_classify`` thấy ``effective is None`` và trả ``UNKNOWN`` cho mọi
khung. Cảnh báo "người khác vào học hộ" trong ``__main__.py`` đòi
``IDENTITY_MISMATCH`` + ``fresh``, nên nó **im lặng vĩnh viễn** cho tới lần
đăng ký kế tiếp — trong khi kho ``faces.json`` vẫn còn vector.

Test dùng kho :class:`FaceStore` thật trong ``tmp_path`` (chỉ ghi JSON, không
cần OpenCV) và processor giả trả các embedding khác nhau cho từng bước đăng
ký, nên ngưỡng suy ra là một con số thật chứ không phải hằng.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.faces import (  # noqa: E402
    STORE_FILENAME,
    FaceStore,
    cosine_similarity,
)
from posture_monitor.people_service import (  # noqa: E402
    IDENTITY_MATCH,
    IDENTITY_MISMATCH,
    IDENTITY_UNKNOWN,
    THRESHOLD_FILENAME,
    THRESHOLD_VERSION,
    PeopleService,
)

#: Vector đơn vị 128 chiều làm gốc; cố định để kết quả tất định.
BASE_VECTOR = np.ones(128, dtype=np.float32) / np.sqrt(128.0)


class FakeClock:
    def __init__(self, start: float = 100.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now


def _orthogonal_to_base(seed: int) -> np.ndarray:
    """Vector đơn vị trực giao với :data:`BASE_VECTOR`, tất định theo ``seed``."""
    rng = np.random.default_rng(seed)
    candidate = rng.standard_normal(128).astype(np.float64)
    candidate -= BASE_VECTOR.astype(np.float64) * float(
        np.dot(candidate, BASE_VECTOR)
    )
    return (candidate / np.linalg.norm(candidate)).astype(np.float32)


def _vector_at_cosine(cosine: float) -> np.ndarray:
    """Vector đơn vị có cosine đúng bằng ``cosine`` với :data:`BASE_VECTOR`."""
    other = _orthogonal_to_base(7)
    return (
        float(cosine) * BASE_VECTOR + float(np.sqrt(1.0 - cosine**2)) * other
    ).astype(np.float32)


class DistinctSamples:
    """Processor giả: mỗi lời gọi trả một embedding hơi khác nhau.

    Cần ba mẫu **khác nhau** để ``derive_threshold`` có cơ sở (ba cặp). Ba
    vector gần nhau cho ngưỡng cao; đây là dữ liệu thật của phép suy, không
    phải số bịa đặt trong test.
    """

    def __init__(self) -> None:
        self.samples = [
            BASE_VECTOR,
            _vector_at_cosine(0.97),
            _vector_at_cosine(0.95),
        ]
        self.index = 0

    def __call__(self, _frame: object) -> np.ndarray:
        vector = self.samples[min(self.index, len(self.samples) - 1)]
        self.index += 1
        return np.array(vector)


class RecordingLogger:
    """Logger giả ghi lại các dòng cảnh báo để test khẳng định có log."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def warning(self, message: str, *args: object) -> None:
        self.warnings.append(message % args if args else message)

    def info(self, message: str, *args: object) -> None:
        self.infos.append(message % args if args else message)

    def error(self, message: str, *args: object) -> None:
        pass

    def debug(self, message: str, *args: object) -> None:
        pass

    def exception(self, message: str, *args: object) -> None:
        pass


def _new_service(
    data_dir: Path,
    *,
    threshold: float | None = None,
    logger: RecordingLogger | None = None,
    clock: FakeClock | None = None,
) -> PeopleService:
    """Dịch vụ **mới** trên cùng thư mục — mô phỏng một lần khởi động lại."""
    fake_clock = clock or FakeClock()
    store = FaceStore(data_dir, clock=fake_clock)
    return PeopleService(
        store,
        object(),
        clock=fake_clock,
        threshold=threshold,
        logger=logger,
    )


def _enroll_with_distinct_samples(service: PeopleService, name: str) -> None:
    """Đăng ký đủ ba mẫu khác nhau (một mẫu mỗi bước 1,5 s)."""
    service.set_processor(DistinctSamples())
    started = service.start_enroll(name)
    for now in (100.0, 101.5, 103.0):
        service.process_frame(object(), now=now)
    assert service.enroll_status(started["enroll_id"])["state"] == "done"


# ---------------------------------------------------------------------------
# 1. Ngưỡng tự suy sống qua lần khởi động lại
# ---------------------------------------------------------------------------
def test_nguong_tu_suy_duoc_nap_lai_sau_khoi_dong_lai(tmp_path: Path) -> None:
    first = _new_service(tmp_path)
    _enroll_with_distinct_samples(first, "An")
    first.close()

    saved = tmp_path / THRESHOLD_FILENAME
    assert saved.is_file(), (
        "Ngưỡng tự suy phải được ghi xuống tệp phụ; nếu không, một lần "
        "restart Pi là cảnh báo 'người khác vào học trộm' im lặng vĩnh viễn."
    )

    # Dịch vụ MỚI, cùng thư mục: đây chính là một lần khởi động lại.
    restarted = _new_service(tmp_path, logger=RecordingLogger())
    try:
        # Kho vẫn còn vector của "An"; chỉ con số ngưỡng từng bị mất.
        assert restarted._auto_threshold is not None, (
            "Sau restart, ngưỡng tự suy không được nạp lại; _classify sẽ trả "
            "UNKNOWN cho mọi khung và cảnh báo người lạ không bao giờ bật."
        )
        state, name, _ = restarted._classify(np.array(BASE_VECTOR))
        assert (state, name) == (IDENTITY_MATCH, "An")
        # Một khuôn mặt khác dưới ngưỡng phải ra MISMATCH — không phải UNKNOWN.
        state, name, _ = restarted._classify(_vector_at_cosine(0.10))
        assert (state, name) == (IDENTITY_MISMATCH, None)
    finally:
        restarted.close()


# ---------------------------------------------------------------------------
# 2. Chưa có tệp phụ → đúng hành vi cũ
# ---------------------------------------------------------------------------
def test_khong_co_tep_phu_thi_van_unknown(tmp_path: Path) -> None:
    logger = RecordingLogger()
    service = _new_service(tmp_path, logger=logger)
    try:
        assert not (tmp_path / THRESHOLD_FILENAME).exists()
        assert service._auto_threshold is None
        state, _, reason = service._classify(np.array(BASE_VECTOR))
        assert state == IDENTITY_UNKNOWN
        assert "ngưỡng" in reason
        # Chưa có tệp là chuyện bình thường, không phải cảnh báo.
        assert logger.warnings == []
    finally:
        service.close()


# ---------------------------------------------------------------------------
# 3. Tệp phụ hỏng / sai phiên bản → không ném, UNKNOWN, có cảnh báo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("{ đây không phải JSON", id="json-rac"),
        pytest.param(
            json.dumps({"version": 999, "threshold": 0.8}),
            id="sai-phien-version",
        ),
        pytest.param(
            json.dumps({"version": THRESHOLD_VERSION, "threshold": 7.5}),
            id="ngoai-mien-cosine",
        ),
        pytest.param(
            json.dumps({"version": THRESHOLD_VERSION, "threshold": "cao"}),
            id="khong-phai-so",
        ),
        # JSON hợp lệ nhưng số nguyên quá lớn: ``float(10**400)`` ném
        # ``OverflowError`` (lớp con của ``ArithmeticError``, KHÔNG phải
        # ``ValueError``). Không bắt nó thì constructor chết và dashboard không
        # dựng lên được — đúng lời hứa "không bao giờ ném" ở §11.3/§11.4.
        pytest.param(
            json.dumps(
                {"version": THRESHOLD_VERSION, "threshold": 10**400, "updated_at": 0}
            ),
            id="so-nguyen-qua-lon",
        ),
        pytest.param(
            json.dumps(
                {"version": THRESHOLD_VERSION, "threshold": -(10**400), "updated_at": 0}
            ),
            id="so-nguyen-am-qua-lon",
        ),
        pytest.param(
            json.dumps({"version": THRESHOLD_VERSION}),
            id="thieu-nguong",
        ),
    ],
)
def test_tep_phu_hong_thi_unknown_va_chi_canh_bao(
    tmp_path: Path, payload: str
) -> None:
    (tmp_path / THRESHOLD_FILENAME).write_text(payload, encoding="utf-8")
    logger = RecordingLogger()

    service = _new_service(tmp_path, logger=logger)  # không được ném

    try:
        assert service._auto_threshold is None
        # Dịch vụ phải chạy tiếp được, không chỉ "không ném lúc dựng".
        assert set(service.signals()) == {"presence", "phone", "identity"}
        state, _, _ = service._classify(np.array(BASE_VECTOR))
        assert state == IDENTITY_UNKNOWN
        assert len(logger.warnings) == 1, logger.warnings
        assert THRESHOLD_FILENAME in logger.warnings[0]
    finally:
        service.close()


def test_tep_phu_hong_khong_lam_hong_kho(tmp_path: Path) -> None:
    """Kho lành + tệp phụ hỏng: người đã đăng ký vẫn còn nguyên."""
    store = FaceStore(tmp_path, clock=FakeClock())
    store.add("An", BASE_VECTOR, enrolled_at=1.0)
    (tmp_path / THRESHOLD_FILENAME).write_text("{{{{", encoding="utf-8")

    service = _new_service(tmp_path, logger=RecordingLogger())
    try:
        assert store.names() == ["An"]
        assert (tmp_path / STORE_FILENAME).is_file()
    finally:
        service.close()


# ---------------------------------------------------------------------------
# 4. Config luôn thắng tệp phụ
# ---------------------------------------------------------------------------
def test_nguong_trong_config_thang_tep_phu(tmp_path: Path) -> None:
    (tmp_path / THRESHOLD_FILENAME).write_text(
        json.dumps(
            {
                "version": THRESHOLD_VERSION,
                "threshold": 0.9,
                "updated_at": 123.0,
            }
        ),
        encoding="utf-8",
    )
    store = FaceStore(tmp_path, clock=FakeClock())
    store.add("An", BASE_VECTOR, enrolled_at=1.0)

    service = _new_service(tmp_path, threshold=0.5)
    try:
        # Điểm 0,7: trên 0,5 (config) nhưng dưới 0,9 (tệp phụ).
        query = _vector_at_cosine(0.7)
        state, name, _ = service._classify(query)
        assert (state, name) == (IDENTITY_MATCH, "An"), (
            "Config đặt match_threshold thì phải dùng nó; nếu tệp phụ 0,9 "
            "thắng thì người thật bị báo MISMATCH."
        )
        assert service._auto_threshold is None
    finally:
        service.close()


# ---------------------------------------------------------------------------
# 5. Đăng ký lại ghi đè tệp phụ
# ---------------------------------------------------------------------------
def test_dang_ky_lai_ghi_de_tep_phu(tmp_path: Path) -> None:
    first = _new_service(tmp_path)
    _enroll_with_distinct_samples(first, "An")
    first.close()
    before = json.loads(
        (tmp_path / THRESHOLD_FILENAME).read_text(encoding="utf-8")
    )

    second = _new_service(tmp_path, clock=FakeClock(200.0))
    try:
        second.set_processor(DistinctSamples())
        second.start_enroll("Bình")
        for now in (200.0, 201.5, 203.0):
            second.process_frame(object(), now=now)
    finally:
        second.close()

    after = json.loads(
        (tmp_path / THRESHOLD_FILENAME).read_text(encoding="utf-8")
    )
    assert after["version"] == THRESHOLD_VERSION
    assert set(after) == {"version", "threshold", "updated_at"}
    # Lần đăng ký sau ghi lại thời điểm; tệp vẫn chỉ có ngưỡng, không vector.
    assert after["updated_at"] != before["updated_at"]
    assert isinstance(after["threshold"], float)


# ---------------------------------------------------------------------------
# 6. Tệp phụ không chứa dữ liệu sinh trắc học
# ---------------------------------------------------------------------------
def test_tep_phu_chi_chua_nguong_va_thoi_diem(tmp_path: Path) -> None:
    service = _new_service(tmp_path)
    try:
        _enroll_with_distinct_samples(service, "An")
    finally:
        service.close()

    payload = json.loads(
        (tmp_path / THRESHOLD_FILENAME).read_text(encoding="utf-8")
    )
    assert set(payload) == {"version", "threshold", "updated_at"}
    assert payload["version"] == THRESHOLD_VERSION
    assert -1.0 <= payload["threshold"] <= 1.0
    # Không tên người, không vector, không đường dẫn ảnh (spec §5.13.1).
    raw = json.dumps(payload, ensure_ascii=False)
    assert "An" not in raw
    assert "embedding" not in raw
    assert "vector" not in raw


# ---------------------------------------------------------------------------
# 7. Ghi nguyên tử, không để lại tệp tạm
# ---------------------------------------------------------------------------
def test_khong_de_lai_tep_tam_sau_khi_ghi(tmp_path: Path) -> None:
    service = _new_service(tmp_path)
    try:
        _enroll_with_distinct_samples(service, "An")
    finally:
        service.close()

    left = sorted(
        path.name
        for path in tmp_path.iterdir()
        if path.is_file() and path.name.startswith(".")
    )
    assert left == [], f"Còn tệp tạm sau khi ghi nguyên tử: {left}"
    assert (tmp_path / STORE_FILENAME).is_file()
    assert (tmp_path / THRESHOLD_FILENAME).is_file()


# ---------------------------------------------------------------------------
# 8. Kho rỗng sau khi xoá người cuối: ngưỡng còn cũng vô hại
# ---------------------------------------------------------------------------
def test_kho_rong_thi_unknown_du_nguong_con(tmp_path: Path) -> None:
    service = _new_service(tmp_path)
    try:
        _enroll_with_distinct_samples(service, "An")
        assert service.delete_person("An") is True
        state, _, reason = service._classify(np.array(BASE_VECTOR))
        assert state == IDENTITY_UNKNOWN
        assert "Chưa có ai được đăng ký" in reason
    finally:
        service.close()


def test_nguong_tai_sinh_khop_voi_ham_suy(tmp_path: Path) -> None:
    """Tệp phụ phải giữ đúng con số ``derive_threshold`` đã suy, không lệch."""
    service = _new_service(tmp_path)
    samples = DistinctSamples().samples
    try:
        _enroll_with_distinct_samples(service, "An")
        in_memory = service._auto_threshold
    finally:
        service.close()

    # Ba cặp, lấy độ giống THẤP NHẤT rồi trừ 0,15 và kẹp [0,30, 0,95].
    lowest = min(
        cosine_similarity(samples[i], samples[j])
        for i in range(len(samples))
        for j in range(i + 1, len(samples))
    )
    expected = round(max(0.30, min(0.95, lowest - 0.15)), 2)
    saved = json.loads(
        (tmp_path / THRESHOLD_FILENAME).read_text(encoding="utf-8")
    )
    assert in_memory == pytest.approx(expected)
    assert saved["threshold"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 8. Ngưỡng chạm sàn phải KÊU, không được im lặng
# ---------------------------------------------------------------------------
class _ContradictorySamples:
    """Ba mẫu "cùng người" nhưng lệch nhau nhiều — như phiên bị tay che mặt.

    Đo thật: chuỗi 14 khung bị tay che mặt cho cosine thấp nhất 0,40, tức là
    0,40 - 0,15 = 0,25 < sàn 0,30 -> ngưỡng kẹp về đúng sàn. Cùng người trên
    khung sạch cho cosine 0,92 -> 0,77. Ba vector dưới đây tái hiện đúng tình
    huống thứ nhất ở mức cosine 0,40.
    """

    def __init__(self) -> None:
        self.samples = [
            BASE_VECTOR,
            _vector_at_cosine(0.40),
            _vector_at_cosine(0.95),
        ]
        self.index = 0

    def __call__(self, _frame: object) -> np.ndarray:
        vector = self.samples[min(self.index, len(self.samples) - 1)]
        self.index += 1
        return np.array(vector)


def test_nguong_cham_san_thi_canh_bao_lo_nguong(tmp_path: Path) -> None:
    """Mẫu đăng ký mâu thuẫn -> ngưỡng về sàn -> PHẢI có cảnh báo.

    Vì sao cần: sàn 0,30 làm cổng danh tính lỏng đến mức người khác có thể
    được nhận thành chủ, mà ``_classify`` dùng con số đó y như ngưỡng thật.
    Không có dòng cảnh báo thì sự cố này hoàn toàn vô hình — đúng kiểu "cảnh
    báo người lạ không bao giờ kêu" mà spec §5.13 lo.

    Đột biến để kiểm chứng: bỏ khối ``if derived <= AUTO_THRESHOLD_MIN`` trong
    ``_derive_auto_threshold`` — test này phải đỏ.
    """
    logger = RecordingLogger()
    service = _new_service(tmp_path, logger=logger)
    try:
        service.set_processor(_ContradictorySamples())
        started = service.start_enroll("An")
        for now in (100.0, 101.5, 103.0):
            service.process_frame(object(), now=now)
        assert service.enroll_status(started["enroll_id"])["state"] == "done"
        assert service._auto_threshold == pytest.approx(0.30)
    finally:
        service.close()

    assert any("chạm sàn" in message for message in logger.warnings), (
        "Ngưỡng tự suy chạm sàn 0,30 mà không có cảnh báo; người dùng không "
        f"thể biết cổng danh tính đã lỏng. Cảnh báo có: {logger.warnings}"
    )


def test_nguong_tot_thi_khong_canh_bao_san(tmp_path: Path) -> None:
    """Mẫu đồng ý với nhau -> ngưỡng bình thường -> KHÔNG được kêu.

    Cặp test này giữ cho cảnh báo trên có nghĩa: nếu nó kêu ở mọi lần đăng ký
    thì nó thành tiếng ồn và người dùng sẽ học cách bỏ qua.
    """
    logger = RecordingLogger()
    service = _new_service(tmp_path, logger=logger)
    try:
        _enroll_with_distinct_samples(service, "An")
        # Ba mẫu gần nhau (cosine thấp nhất 0,95) -> 0,95 - 0,15 = 0,80, trên
        # sàn. Không khoá đúng con số: điều cần khẳng định là "trên sàn".
        assert service._auto_threshold > 0.30
    finally:
        service.close()

    assert not any("chạm sàn" in message for message in logger.warnings), (
        f"Ngưỡng {service._auto_threshold} (tốt) mà vẫn cảnh báo chạm sàn: "
        f"{logger.warnings}"
    )
