"""Không được rò rỉ mật khẩu camera IP qua báo cáo benchmark.

``benchmark.py`` vừa in bảng ra màn hình (:func:`format_report`) vừa ghi
thẳng dict báo cáo ra file qua ``--json``. Vì thế mật khẩu trong URL RTSP phải
được che **trước khi** giá trị vào dict (trong :func:`_source_meta`), chứ không
chỉ che lúc in — che muộn thì file JSON vẫn lộ.

Bài test này dựng báo cáo qua đúng đường chạy thật (``run_benchmark``), nhưng
thay ``capture_from_config`` bằng nguồn giả: không mở kết nối RTSP, không cần
camera, mạng hay model. Mật khẩu dùng trong test đều là chuỗi giả.

Lưu ý khi viết assertion: **không** kiểm một ký tự đơn như ``"p"`` — chữ ``p``
có sẵn trong ``rtsp`` nên test sẽ xanh giả. Ở đây luôn so cả chuỗi mật khẩu.
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

from posture_monitor import benchmark as bench  # noqa: E402
from posture_monitor.capture import FrameSource  # noqa: E402
from posture_monitor.config import Config  # noqa: E402
from posture_monitor.pose import PoseResult  # noqa: E402

# --------------------------------------------------------------------------
# Đối tượng giả
# --------------------------------------------------------------------------


def _keypoints() -> PoseResult:
    """Pose tổng hợp tối giản, đủ để ``features.extract`` tính được."""
    xy = np.zeros((17, 2), dtype=np.float32)
    xy[5] = (200.0, 200.0)
    xy[6] = (400.0, 200.0)
    xy[0] = (300.0, 120.0)
    xy[11] = (220.0, 330.0)
    xy[12] = (380.0, 330.0)
    conf = np.full((17,), 0.9, dtype=np.float32)
    bbox = np.array([200.0, 100.0, 400.0, 400.0], dtype=np.float32)
    return PoseResult(xy=xy, conf=conf, bbox=bbox)


class _FakeEstimator:
    """Thay ``PoseEstimator``: không tải trọng số, trả pose tổng hợp."""

    backend = "giả-lập"

    def __init__(self) -> None:
        self._model = None  # không có callback ultralytics

    def detect(self, frame):  # noqa: ANN001, ANN201 - khớp hợp đồng
        return _keypoints()


class _FakeSource(FrameSource):
    """Nguồn giả đóng vai camera/RTSP đã mở sẵn."""

    backend = "rtsp"

    def __init__(self) -> None:
        self.closed = False

    def read(self):  # noqa: ANN201
        return np.zeros((64, 64, 3), dtype=np.uint8)

    def close(self) -> None:
        self.closed = True


class _FakeCommand:
    """Thay ``_Command`` để không phụ thuộc ``vcgencmd`` của máy chạy test."""

    def __init__(self, *argv: str) -> None:
        self._argv = argv

    def run(self, timeout: float = 2.0):  # noqa: ANN201
        if self._argv[0] != "vcgencmd":
            return None, "Không có lệnh."
        if self._argv[-1] == "measure_temp":
            return "temp=50.0'C", None
        if self._argv[-1] == "get_throttled":
            return "throttled=0x0", None
        return None, "Tham số không hỗ trợ."


def _patch_environment(monkeypatch: pytest.MonkeyPatch, source=None) -> None:  # noqa: ANN001
    """Thay model + lệnh hệ thống + hàm mở nguồn bằng đối tượng giả.

    ``source=None`` mô phỏng ``capture_from_config`` trả ``None`` (không mở
    được nguồn) để kiểm thông điệp lỗi.
    """

    def _fake_capture(config):  # noqa: ANN001, ANN202 - khớp hợp đồng
        return source

    monkeypatch.setattr(bench, "PoseEstimator", lambda config: _FakeEstimator())
    monkeypatch.setattr(bench, "_Command", _FakeCommand)
    monkeypatch.setattr(bench, "capture_from_config", _fake_capture)


def _spec_rtsp(password: str, host: str = "192.168.17.112") -> str:
    """Spec ``camera.source`` cho camera IP có mật khẩu."""
    return f"rtsp:rtsp://admin:{password}@{host}:554/1/2"


#: Bộ mật khẩu giả cần chặn. ``p@ssw0rd!`` là ca M6 từng rò phần đuôi khi
#: biểu thức che dùng ``[^/@]*`` (dừng ở ``@`` đầu tiên). Không thử mật khẩu
#: chứa ``/``: theo RFC 3986 nó phải được percent-encode, và ``/`` kết thúc
#: authority nên URL đó không còn là URL hợp lệ.
_PASSWORDS = ["matkhau-gia", "p@ssw0rd!", "secret", "MatKhau.Viet-Hoa_2026"]


# --------------------------------------------------------------------------
# Báo cáo sinh ra từ đường chạy thật
# --------------------------------------------------------------------------


@pytest.mark.parametrize("password", _PASSWORDS)
def test_bao_cao_khong_chua_mat_khau(
    password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dict báo cáo, bảng in và JSON đều không được chứa mật khẩu."""
    _patch_environment(monkeypatch, _FakeSource())

    report = bench.run_benchmark(
        Config(), 0.15, source_override=_spec_rtsp(password)
    )
    text = bench.format_report(report)
    as_json = json.dumps(report, ensure_ascii=False)

    for label, blob in (
        ("source['spec']", report["source"]["spec"]),
        ("format_report", text),
        ("json.dumps", as_json),
    ):
        assert password not in blob, f"{label} còn chứa mật khẩu {password!r}"

    # Che nhưng phải giữ phần dùng được: user/mật khẩu thành ``***:***``.
    assert "***:***" in report["source"]["spec"]
    assert "192.168.17.112:554/1/2" in report["source"]["spec"]


def test_bao_cao_khong_con_ten_dang_nhap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tên đăng nhập cũng nằm trong userinfo nên phải bị che cùng."""
    _patch_environment(monkeypatch, _FakeSource())

    report = bench.run_benchmark(
        Config(), 0.15, source_override=_spec_rtsp("matkhau-gia")
    )

    assert "admin" not in report["source"]["spec"]
    assert "admin" not in bench.format_report(report)


def test_json_ghi_ra_file_khong_chua_mat_khau(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Đường ``--json``: ghi file rồi đọc lại như người dùng thật."""
    _patch_environment(monkeypatch, _FakeSource())

    report = bench.run_benchmark(
        Config(), 0.15, source_override=_spec_rtsp("p@ssw0rd!")
    )
    target = tmp_path / "bench.json"
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    assert "p@ssw0rd!" not in target.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Nguồn không có thông tin đăng nhập: phải giữ nguyên từng byte
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "detail",
    [
        "rtsp:rtsp://192.168.17.112:554/1/2",
        "rtsps://camera.local:7441/stream",
        "usb:0",
        "picamera",
        "file:C:\\video\\bai_giang.mp4",
        "file:/home/pi/anh mau.jpg",
        "ảnh tĩnh 'mau.jpg' lặp lại",
    ],
)
def test_nguon_khong_co_mat_khau_khong_bi_doi(detail: str) -> None:
    """Không có credential thì ``spec`` phải y hệt trước khi sửa."""
    meta = bench._source_meta("camera", _FakeSource(), detail)

    assert meta["spec"] == detail


# --------------------------------------------------------------------------
# Thông điệp lỗi cũng in ra màn hình
# --------------------------------------------------------------------------


def test_loi_mo_nguon_khong_chua_mat_khau(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``capture_from_config`` trả ``None`` → thông điệp lỗi phải đã che."""
    _patch_environment(monkeypatch, None)

    with pytest.raises(bench.BenchmarkError) as info:
        bench.run_benchmark(
            Config(), 0.1, source_override=_spec_rtsp("p@ssw0rd!")
        )

    message = str(info.value)
    assert "p@ssw0rd!" not in message
    assert "***:***" in message


def test_loi_nguon_file_khong_doi_voi_duong_dan_thuong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Đường dẫn file không có userinfo nên thông điệp lỗi giữ nguyên."""
    _patch_environment(monkeypatch, _FakeSource())
    missing = tmp_path / "khong_co.jpg"

    with pytest.raises(bench.BenchmarkError) as info:
        bench.run_benchmark(Config(), 0.1, source_override=f"file:{missing}")

    message = str(info.value)
    assert "không tồn tại" in message
    assert str(missing) in message
