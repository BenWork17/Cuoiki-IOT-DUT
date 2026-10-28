"""Kiểm thử lệnh CLI ``benchmark`` của ``python -m posture_monitor`` (spec §7).

Lệnh này phải là **một đường vào duy nhất** tới bài đo đã hoàn thành ở
``posture_monitor.benchmark``: ``__main__.main`` không được in thông báo
"chưa triển khai", phải giữ nguyên mã thoát của ``benchmark.main`` và phải
chuyển đủ cờ sang đó.

Giống ``tests/test_benchmark.py``, bộ test này **không cần camera, GPIO, mạng
hay trọng số model**: ``PoseEstimator`` và ``_Command`` (``vcgencmd``) được
thay bằng đối tượng giả, nguồn ảnh là một file ảnh tĩnh nhỏ.
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

from posture_monitor import __main__ as cli  # noqa: E402
from posture_monitor import benchmark as bench  # noqa: E402
from posture_monitor.pose import PoseResult  # noqa: E402

# --------------------------------------------------------------------------
# Đối tượng giả
# --------------------------------------------------------------------------


def _keypoints() -> PoseResult:
    """Pose tổng hợp: hai vai ngang nhau, đủ để ``features`` tính được."""
    xy = np.zeros((17, 2), dtype=np.float32)
    xy[5] = (200.0, 200.0)
    xy[6] = (400.0, 200.0)
    xy[0] = (300.0, 120.0)
    xy[3] = (260.0, 110.0)
    xy[4] = (340.0, 110.0)
    xy[11] = (220.0, 330.0)
    xy[12] = (380.0, 330.0)
    conf = np.full((17,), 0.9, dtype=np.float32)
    bbox = np.array([200.0, 100.0, 400.0, 400.0], dtype=np.float32)
    return PoseResult(xy=xy, conf=conf, bbox=bbox)


class FakeEstimator:
    """Thay ``PoseEstimator``: không tải model, trả pose tổng hợp."""

    backend = "giả-lập"

    def __init__(self, config=None) -> None:  # noqa: ANN001 - khớp hợp đồng
        self._model = None  # không có callback ultralytics

    def detect(self, frame):  # noqa: ANN001, ANN201 - khớp hợp đồng
        return _keypoints()


def _patch_estimator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bench, "PoseEstimator", FakeEstimator)


def _patch_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    """Giả lập Raspberry Pi có ``vcgencmd`` sạch throttle."""

    class _FakeCommand:
        def __init__(self, *argv: str) -> None:
            self._argv = argv

        def run(self, timeout: float = 2.0):  # noqa: ANN201
            if self._argv[-1] == "measure_temp":
                return "temp=55.0'C", None
            if self._argv[-1] == "get_throttled":
                return "throttled=0x0", None
            return None, "Tham số không hỗ trợ."

    monkeypatch.setattr(bench, "_Command", _FakeCommand)


# --------------------------------------------------------------------------
# Chuyển tiếp tham số và mã thoát
# --------------------------------------------------------------------------


class TestChuyenTiep:
    """``cmd_benchmark`` phải dựng đúng argv cho ``benchmark.main``."""

    def test_chuyen_du_co_sang_benchmark_main(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[list[str]] = []

        def fake_main(argv):  # noqa: ANN001, ANN202
            seen.append(list(argv))
            return 0

        monkeypatch.setattr(bench, "main", fake_main)

        code = cli.main(
            [
                "benchmark",
                "--seconds", "2.5",
                "--config", "cau_hinh.yaml",
                "--source", "file:anh.jpg",
                "--json", "bao_cao.json",
                "--no-gpio",
                "--log-level", "DEBUG",
            ]
        )

        assert code == 0
        assert len(seen) == 1
        argv = seen[0]
        # Dựng lại từng cờ; thứ tự không quan trọng nên so sánh theo cặp.
        assert "--seconds" in argv and argv[argv.index("--seconds") + 1] == "2.5"
        assert "--config" in argv and argv[argv.index("--config") + 1] == (
            "cau_hinh.yaml"
        )
        assert "--source" in argv and argv[argv.index("--source") + 1] == (
            "file:anh.jpg"
        )
        assert "--json" in argv and argv[argv.index("--json") + 1] == (
            "bao_cao.json"
        )
        assert "--no-gpio" in argv
        assert "--log-level" in argv and argv[argv.index("--log-level") + 1] == (
            "DEBUG"
        )

    def test_khong_truyen_co_tuy_chon_thi_khong_chen_vao_argv(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[list[str]] = []
        monkeypatch.setattr(bench, "main", lambda argv: seen.append(argv) or 0)

        assert cli.main(["benchmark", "--seconds", "1"]) == 0
        argv = seen[0]
        assert "--source" not in argv
        assert "--json" not in argv
        assert "--no-gpio" not in argv

    @pytest.mark.parametrize("expected", [0, 1, 2, 130])
    def test_ma_thoat_cua_benchmark_duoc_giu_nguyen(
        self, monkeypatch: pytest.MonkeyPatch, expected: int
    ) -> None:
        monkeypatch.setattr(bench, "main", lambda argv: expected)
        assert cli.main(["benchmark", "--seconds", "1"]) == expected

    def test_benchmark_khong_bao_chua_trien_khai(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(bench, "main", lambda argv: 0)

        cli.main(["benchmark", "--seconds", "1"])

        captured = capsys.readouterr()
        assert "chưa triển khai" not in captured.out
        assert "chưa triển khai" not in captured.err

    def test_seconds_nhan_so_thuc(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--seconds 0.5`` phải parse được (bài đo ngắn để kiểm thử)."""
        seen: list[list[str]] = []
        monkeypatch.setattr(bench, "main", lambda argv: seen.append(argv) or 0)

        assert cli.main(["benchmark", "--seconds", "0.5"]) == 0
        assert seen[0][seen[0].index("--seconds") + 1] == "0.5"

    def test_thieu_file_cau_hinh_tra_ma_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Không monkeypatch ``benchmark.main``: đây là mã thoát thật."""
        missing = tmp_path / "khong_co.yaml"
        code = cli.main(
            ["benchmark", "--config", str(missing), "--seconds", "0.1"]
        )
        assert code == 2
        assert "không tìm thấy file cấu hình" in capsys.readouterr().err.lower()


# --------------------------------------------------------------------------
# Đường thật: CLI → run_benchmark → format_report (+ JSON)
# --------------------------------------------------------------------------


class TestDuongThat:
    def test_benchmark_do_that_va_ghi_json(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Chạy trọn đường CLI với model/``vcgencmd`` giả và ảnh tĩnh.

        Bài này chứng minh lệnh **thật sự đo** và in bảng thật, chứ không chỉ
        in thông báo rồi thoát: báo cáo phải có số khung đo được và file JSON
        phải chứa đúng dict báo cáo.
        """
        import cv2

        image_path = tmp_path / "mau.jpg"
        assert cv2.imwrite(
            str(image_path), np.full((96, 128, 3), 110, np.uint8)
        )
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            f"camera:\n  source: file:{image_path}\n", encoding="utf-8"
        )
        json_path = tmp_path / "bao_cao.json"

        _patch_estimator(monkeypatch)
        _patch_commands(monkeypatch)

        code = cli.main(
            [
                "benchmark",
                "--seconds", "0.1",
                "--config", str(config_path),
                "--source", f"file:{image_path}",
                "--json", str(json_path),
                "--no-gpio",
            ]
        )

        captured = capsys.readouterr()
        assert code == 0, captured.err
        assert "BÁO CÁO BENCHMARK" in captured.out
        assert "TIÊU CHÍ NGHIỆM THU" in captured.out
        assert "Đã ghi báo cáo JSON" in captured.out

        assert json_path.is_file()
        # Phải đọc được bằng UTF-8 (tiếng Việt trong báo cáo, không escape).
        report = json.loads(json_path.read_text(encoding="utf-8"))
        assert report["report_version"] == bench.REPORT_VERSION
        assert report["frames"]["measured"] > 0
        assert report["source"]["kind"] == "image"
        assert report["timing_ms"]["pipeline_total"]["count"] == (
            report["frames"]["measured"]
        )
        # Tiếng Việt phải được giữ nguyên, không bị escape thành \uXXXX.
        assert "\\u" not in json_path.read_text(encoding="utf-8")
