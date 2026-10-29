"""Kiểm thử ``scripts/face_threshold_probe.py`` — công cụ đo ngưỡng khuôn mặt.

Không cần camera, không cần mô hình: mọi phụ thuộc được tiêm qua tham số của
:func:`main` (``source_factory``, ``recognizer_factory``, ``today``) và qua
``stdout``/``stderr``. Nhờ vậy test kiểm được **số học phân bố**, **chọn điểm
cân bằng**, **lọc khung nhiều mặt** và **việc che mật khẩu** mà không chạm tới
phần cứng.

Nguyên tắc: mỗi bài khẳng định một hành vi mà đổi mã sẽ làm đỏ đúng bài đó,
với ``AssertionError`` nêu đúng thứ đang kiểm — không phải lỗi import/kiểu.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_SCRIPT = _REPO_ROOT / "scripts" / "face_threshold_probe.py"


def _load_script():
    """Nạp script như module để test hàm bên trong."""
    spec = importlib.util.spec_from_file_location("face_threshold_probe_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = _load_script()

#: Mật khẩu giả để kiểm rò rỉ. Cố ý không phải mật khẩu thật của dự án.
SECRET = "mat-khau-gia-probe-4711"

# --------------------------------------------------------------------------
# Đối tượng giả
# --------------------------------------------------------------------------


class FakeSource:
    """Nguồn ảnh giả: trả lần lượt các khung trong danh sách, rồi ``None``."""

    def __init__(self, frames):
        self._frames = list(frames)
        self._index = 0
        self.closed = False

    def read(self):
        if self._index >= len(self._frames):
            return None
        frame = self._frames[self._index]
        self._index += 1
        return frame

    def close(self):
        self.closed = True

    @property
    def backend(self):
        return "fake"


class FakeRecognizer:
    """Nhận diện giả: đọc số mặt và vector đã đính sẵn trong khung."""

    def __init__(self):
        self.embedding_calls = 0

    def detect(self, frame):
        return list(frame.faces)

    def embedding(self, frame, face):
        self.embedding_calls += 1
        return frame.vector


def _frame(vector=None, faces=1):
    """Một khung giả: ``faces`` khuôn mặt và vector tương ứng."""
    if faces == 0:
        return SimpleNamespace(faces=[], vector=None)
    return SimpleNamespace(
        faces=[SimpleNamespace(index=i) for i in range(faces)],
        vector=np.asarray(vector, dtype=np.float32),
    )


def _unit(degrees: float) -> np.ndarray:
    """Vector đơn vị 2 chiều ở góc ``degrees`` — để biết trước cosine."""
    radians = np.deg2rad(degrees)
    return np.asarray([np.cos(radians), np.sin(radians)], dtype=np.float32)


def _run(frames, argv, *, today="2026-10-29", source="usb:0"):
    """Chạy ``main`` với camera/recognizer giả; trả ``(code, stdout, stderr, src)``."""
    out, err = io.StringIO(), io.StringIO()
    holder = {}
    # Không để biến môi trường của máy chạy test lọt vào phép đo.
    if "--source" not in argv:
        argv = ["--source", source, *argv]

    def factory(text):
        holder["source_text"] = text
        fake = FakeSource(frames)
        holder["source"] = fake
        return fake

    code = probe.main(
        list(argv),
        source_factory=factory,
        recognizer_factory=FakeRecognizer,
        today=lambda: today,
        stdout=out,
        stderr=err,
    )
    return code, out.getvalue(), err.getvalue(), holder.get("source")


# --------------------------------------------------------------------------
# Số học phân bố
# --------------------------------------------------------------------------


def test_within_person_pairs_uses_all_unordered_pairs():
    """3 mẫu → 3 cặp, mỗi cặp đúng cosine của góc tương ứng."""
    vectors = [_unit(0.0), _unit(10.0), _unit(20.0)]
    values = probe.within_person_pairs(vectors)
    assert len(values) == 3, "3 mẫu phải cho 3 cặp (không phải 6, không phải 2)"
    expected = [
        np.cos(np.deg2rad(10.0)),
        np.cos(np.deg2rad(20.0)),
        np.cos(np.deg2rad(10.0)),
    ]
    for got, want in zip(sorted(values), sorted(expected)):
        assert got == pytest.approx(want, abs=1e-5), (
            f"cosine sai: nhận {got}, mong {want}"
        )


def test_between_person_pairs_is_full_cross_product():
    """2 mẫu A × 3 mẫu B → 6 cặp, đúng góc chéo từng cặp."""
    first = [_unit(0.0), _unit(10.0)]
    second = [_unit(60.0), _unit(70.0), _unit(80.0)]
    values = probe.between_person_pairs(first, second)
    assert len(values) == 6, "2×3 phải cho 6 cặp chéo người"
    assert values[0] == pytest.approx(np.cos(np.deg2rad(60.0)), abs=1e-5), (
        "cặp A[0]↔B[0] phải là cos(60°)"
    )
    assert values[-1] == pytest.approx(np.cos(np.deg2rad(70.0)), abs=1e-5), (
        "cặp A[1]↔B[2] phải là cos(70°)"
    )


def test_summarise_reports_min_median_max_or_none():
    dist = probe.summarise([0.2, 0.9, 0.5])
    assert dist is not None
    assert (dist.minimum, dist.median, dist.maximum) == pytest.approx(
        (0.2, 0.5, 0.9)
    ), "min/trung vị/max phải là 0.2/0.5/0.9"
    assert dist.count == 3
    assert probe.summarise([]) is None, "không có cặp nào thì không có phân bố"


def test_threshold_table_scans_005_to_095_and_counts_both_errors():
    """Bảng đúng 19 mức 0.05…0.95; ``< t`` bỏ sót, ``>= t`` báo nhầm."""
    rows = probe.threshold_table([0.4, 0.8], [0.3, 0.7])
    assert len(rows) == 19, f"phải có 19 mức ngưỡng, nhận {len(rows)}"
    assert rows[0].threshold == pytest.approx(0.05)
    assert rows[-1].threshold == pytest.approx(0.95)
    indexed = {row.threshold: row for row in rows}
    row = indexed[0.50]
    assert row.missed == 1, "cosine 0.4 < 0.5 phải bị tính là bỏ sót"
    assert row.false_alarms == 1, "cosine 0.7 >= 0.5 phải bị tính là báo nhầm"
    # cos đúng bằng ngưỡng thuộc phía báo nhầm (>=), không phải bỏ sót.
    exact = {r.threshold: r for r in probe.threshold_table([0.5], [0.5])}[0.50]
    assert exact.missed == 0 and exact.false_alarms == 1, (
        "cosine bằng đúng ngưỡng phải tính là báo nhầm (>=), không phải bỏ sót"
    )


def test_pick_balance_prefers_higher_threshold_on_tie():
    """Hai mức cùng |bỏ sót − báo nhầm| → chọn mức CAO hơn (spec §3.4)."""
    rows = [
        probe.ThresholdRow(threshold=0.30, missed=1, false_alarms=1),
        probe.ThresholdRow(threshold=0.60, missed=1, false_alarms=1),
        probe.ThresholdRow(threshold=0.80, missed=2, false_alarms=0),
    ]
    chosen = probe.pick_balance(rows, same_total=2, different_total=2)
    assert chosen.threshold == pytest.approx(0.60), (
        "khi hoà ở 0.30 và 0.60 phải chọn 0.60 (ngưỡng cao hơn), "
        f"nhưng chọn {chosen.threshold}"
    )
    with pytest.raises(ValueError):
        probe.pick_balance(
            [probe.ThresholdRow(0.5, 0, 0)], same_total=1, different_total=0
        )


def test_distributions_overlap_detects_shared_range():
    same = probe.summarise([0.90, 0.95])
    diff = probe.summarise([0.93, 0.99])
    assert same is not None and diff is not None
    assert probe.distributions_overlap(same, diff) is True, (
        "same.max 0.95 >= diff.min 0.93 phải bị coi là chồng lấn"
    )
    clean_same = probe.summarise([0.98, 0.99])
    clean_diff = probe.summarise([0.10, 0.30])
    assert probe.distributions_overlap(clean_same, clean_diff) is False, (
        "same.min 0.98 > diff.max 0.30 phải là tách sạch"
    )


# --------------------------------------------------------------------------
# Hành vi CLI
# --------------------------------------------------------------------------


def _clean_frames(vectors):
    return [_frame(vector=v, faces=1) for v in vectors]


def test_clean_separation_prints_suggestion_with_date_and_samples():
    """Hai nhóm tách sạch → in gợi ý kèm ngày đo và số mẫu."""
    frames = _clean_frames([_unit(0.0), _unit(10.0)]) + _clean_frames(
        [_unit(70.0), _unit(80.0)]
    )
    code, out, _err, source = _run(
        frames,
        ["--name", "A", "--name2", "B", "--samples", "2"],
        today="2026-10-29",
    )
    assert code == probe.EXIT_OK, f"phải in được bảng, nhận mã {code}"
    assert source.closed, "nguồn ảnh phải được đóng sau khi đo"
    assert "match_threshold: 0.95" in out, (
        "dòng gợi ý phải chọn ngưỡng cao nhất còn tách sạch (0.95); "
        f"stdout:\n{out}"
    )
    assert "đo 2026-10-29" in out, "dòng gợi ý phải có ngày đo"
    assert "2 mẫu/người" in out, "dòng gợi ý phải có số mẫu"


def test_overlapping_distributions_warn_and_offer_no_threshold():
    """Chồng lấn → in cảnh báo, KHÔNG in dòng gợi ý ``match_threshold:``."""
    frames = _clean_frames([_unit(0.0), _unit(20.0)]) + _clean_frames(
        [_unit(10.0), _unit(30.0)]
    )
    code, out, _err, _source = _run(
        frames, ["--name", "A", "--name2", "B", "--samples", "2"]
    )
    assert "chồng lấn" in out, "hai phân bố chồng lấn phải được nói thẳng"
    assert "không có ngưỡng nào tách sạch" in out, "phải nêu rõ không tách sạch"
    assert "match_threshold:" not in out, (
        "chồng lấn thì không được in dòng gợi ý để người dùng dán vào config"
    )


def test_missing_name2_exits_2_and_says_not_enough():
    """Thiếu người thứ hai → mã 2, nói rõ chưa đủ để chọn ngưỡng."""
    frames = _clean_frames([_unit(0.0), _unit(10.0)])
    code, out, _err, _source = _run(
        frames, ["--name", "A", "--samples", "2"]
    )
    assert code == probe.EXIT_INSUFFICIENT, (
        f"thiếu --name2 phải trả mã {probe.EXIT_INSUFFICIENT}, nhận {code}"
    )
    assert "CHƯA ĐỦ ĐỂ CHỌN NGƯỠNG" in out, "phải nói rõ chưa đủ để chọn ngưỡng"
    assert "match_threshold:" not in out, "một người thì không được bịa ngưỡng"


def test_frames_with_zero_or_two_faces_are_skipped():
    """Khung 0 mặt và khung 2 mặt bị bỏ; chỉ khung đúng 1 mặt được thu."""
    frames = [
        _frame(faces=0),
        _frame(vector=_unit(0.0), faces=2),
        _frame(vector=_unit(0.0), faces=1),
        _frame(vector=_unit(10.0), faces=1),
    ]
    code, _out, err, _source = _run(
        frames, ["--name", "A", "--samples", "2"]
    )
    assert code == probe.EXIT_INSUFFICIENT, (
        "thiếu --name2 vẫn trả 2, nhưng phép thu phải chạy hết"
    )
    assert "Đã thu 1/2 mẫu cho 'A'" in err, "phải in tiến độ ra stderr"
    assert "Đã thu 2/2 mẫu cho 'A'" in err, (
        "khung 0 mặt và 2 mặt phải bị bỏ, còn lại đủ 2 mẫu; "
        f"stderr:\n{err}"
    )


def test_recognizer_is_not_asked_for_embedding_on_multi_face_frame():
    """Khung nhiều mặt: không được gọi ``embedding`` (vector không biết của ai)."""
    recognizer = FakeRecognizer()
    source = FakeSource([_frame(vector=_unit(0.0), faces=3)])
    vectors, _exhausted = probe.collect_embeddings(
        recognizer, source, "A", 1, max_frames=1
    )
    assert vectors == [], "khung 3 mặt không được sinh ra mẫu nào"
    assert recognizer.embedding_calls == 0, (
        "không được trích embedding từ khung nhiều mặt"
    )


def test_camera_source_password_never_printed():
    """Nguồn RTSP có mật khẩu: mật khẩu không được xuất hiện ở stdout/stderr."""
    frames = _clean_frames([_unit(0.0), _unit(10.0)]) + _clean_frames(
        [_unit(70.0), _unit(80.0)]
    )
    source_url = f"rtsp://admin:{SECRET}@192.168.1.50:554/1/2"
    code, out, err, _source = _run(
        frames,
        [
            "--source",
            source_url,
            "--name",
            "A",
            "--name2",
            "B",
            "--samples",
            "2",
        ],
    )
    assert code == probe.EXIT_OK, f"phải đo được, nhận mã {code}"
    assert SECRET not in out, "mật khẩu camera không được in ra stdout"
    assert SECRET not in err, "mật khẩu camera không được in ra stderr"
    assert "192.168.1.50" in out, "vẫn phải in host (đã che) để biết đo trên camera nào"


def test_unopenable_camera_and_short_samples_exit_2_with_reason():
    """Không mở được camera, hoặc thu thiếu mẫu → mã 2 kèm lý do cụ thể."""
    out, err = io.StringIO(), io.StringIO()
    code = probe.main(
        ["--source", "usb:0", "--name", "A", "--name2", "B", "--samples", "2"],
        source_factory=lambda _text: None,
        recognizer_factory=FakeRecognizer,
        today=lambda: "2026-10-29",
        stdout=out,
        stderr=err,
    )
    assert code == probe.EXIT_INSUFFICIENT, (
        f"không mở được camera phải trả 2, nhận {code}"
    )
    assert "không mở được nguồn ảnh" in out.getvalue(), (
        "thông điệp phải nêu lý do không mở được camera"
    )

    code, out, _err, _source = _run(
        _clean_frames([_unit(0.0)]), ["--name", "A", "--samples", "5"]
    )
    assert code == probe.EXIT_INSUFFICIENT, (
        f"thiếu mẫu phải trả 2, nhận {code}"
    )
    assert "1/5" in out, "thông điệp phải nêu 1/5 mẫu thu được"


def test_bad_arguments_rejected_with_specific_reason():
    """``--samples`` < 2 và hai tên trùng nhau bị từ chối kèm lý do riêng."""
    code, out, _err, _source = _run(
        _clean_frames([_unit(0.0)]), ["--name", "A", "--samples", "1"]
    )
    assert code == probe.EXIT_INSUFFICIENT, "một mẫu không tạo được cặp nào"
    assert "--samples phải >= 2" in out

    code, out, _err, _source = _run(
        _clean_frames([_unit(0.0)]),
        ["--name", "A", "--name2", "A", "--samples", "2"],
    )
    assert code == probe.EXIT_INSUFFICIENT, (
        "hai người trùng tên thì phép khác-người vô nghĩa"
    )
    assert "--name2 phải là người KHÁC" in out
