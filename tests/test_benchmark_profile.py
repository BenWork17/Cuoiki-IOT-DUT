"""Kiểm thử ``--profile`` của ``benchmark`` và test chống tái phát cho spec.

Hai nhóm mục đích, đều là **tính trung thực của số liệu**, không phải tính
năng đẹp:

1. **Không được đo nhầm cấu hình.** Hồ sơ sai tên, hoặc hồ sơ cần module/cấu
   hình mà bản này chưa có, phải bị **từ chối** bằng thông điệp tiếng Việt và
   mã thoát khác 0 — không bao giờ lặng lẽ chạy ``pose`` rồi in số dưới nhãn
   ``pose_phone``. Đó chính là lỗi đã sinh ra sự cố số liệu ở §19 của spec.
2. **Spec không được chứa lại số FPS bịa.** Bài đọc ``SPEC_V3.md`` như dữ
   liệu và khẳng định các giá trị đã bị hạ nhãn không quay lại §4.3 / §8.1.

Không cần camera, trọng số hay mạng: mọi thứ đắt đều được thay bằng đối
tượng giả, giống ``tests/test_benchmark.py``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor import benchmark as bench  # noqa: E402
from posture_monitor.config import Config  # noqa: E402
from posture_monitor.pose import PoseResult  # noqa: E402

_SPEC = _REPO_ROOT / "docs" / "SPEC_V3.md"


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
    xy[9] = (210.0, 300.0)  # cổ tay trái
    xy[10] = (390.0, 300.0)  # cổ tay phải
    xy[11] = (220.0, 330.0)
    xy[12] = (380.0, 330.0)
    conf = np.full((17,), 0.9, dtype=np.float32)
    bbox = np.array([200.0, 100.0, 400.0, 400.0], dtype=np.float32)
    return PoseResult(xy=xy, conf=conf, bbox=bbox)


class FakeEstimator:
    """Thay ``PoseEstimator``: không tải model, trả pose tổng hợp."""

    backend = "giả-lập"

    def __init__(self, config=None) -> None:  # noqa: ANN001
        self._model = None
        self.calls = 0

    def detect(self, frame):  # noqa: ANN001, ANN201
        self.calls += 1
        return _keypoints()


def _patch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bench, "PoseEstimator", FakeEstimator)

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


def _frames(count: int = 3, size: int = 64) -> list[np.ndarray]:
    return [
        np.full((size, size, 3), fill_value=index * 10, dtype=np.uint8)
        for index in range(count)
    ]


# --------------------------------------------------------------------------
# Tên hồ sơ: sai thì dừng, không đoán
# --------------------------------------------------------------------------


class TestTenHoSo:
    def test_ten_ho_so_dung_duoc_chap_nhan(self) -> None:
        assert bench.normalise_profile(None) == bench.DEFAULT_PROFILE
        for name in bench.PROFILES:
            assert bench.normalise_profile(name) == name

    def test_ten_ho_so_sai_bi_tu_choi(self) -> None:
        for bad in ("", "poses", "full", "pose_phone_face_x", "POSE"):
            with pytest.raises(bench.BenchmarkError) as info:
                bench.normalise_profile(bad)
            message = str(info.value)
            # Thông điệp phải nêu tên sai và liệt kê lựa chọn hợp lệ.
            assert repr(bad) in message or bad in message
            assert "pose_phone" in message

    def test_chay_voi_ten_sai_khong_do_gi(self, monkeypatch) -> None:  # noqa: ANN001
        """Tên sai phải dừng **trước** khi chạm nguồn hay model."""
        _patch(monkeypatch)

        with pytest.raises(bench.BenchmarkError):
            bench.run_benchmark(
                Config(), 0.1, source_override=_frames(), profile="khong_co"
            )


# --------------------------------------------------------------------------
# Hồ sơ pose giữ nguyên hành vi cũ
# --------------------------------------------------------------------------


class TestHoSoPose:
    def test_mac_dinh_van_la_pose_va_bao_cao_co_profile_models(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch)

        report = bench.run_benchmark(
            Config(), 0.15, source_override=_frames()
        )

        assert report["profile"] == "pose"
        assert isinstance(report["models"], list) and report["models"]
        pose_models = [
            entry for entry in report["models"] if entry["role"] == "pose"
        ]
        assert len(pose_models) == 1
        assert pose_models[0]["name"] == Config().model.name

    def test_khong_co_model_phu_nao_trong_ho_so_pose(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch)

        report = bench.run_benchmark(
            Config(), 0.15, source_override=_frames()
        )
        roles = {entry["role"] for entry in report["models"]}
        assert roles == {"pose"}


# --------------------------------------------------------------------------
# Hồ sơ chưa hỗ trợ: từ chối rõ ràng, không im lặng đo thiếu model
# --------------------------------------------------------------------------


class TestHoSoChuaHoTro:
    def test_pose_phone_thieu_module_thi_tu_choi(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nhánh này chưa có ``phone_detector`` → phải từ chối, không đo pose."""
        _patch(monkeypatch)

        # Ép điều kiện "không có module" bất kể máy chạy test có nhánh kia.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):  # noqa: ANN001, ANN202
            if name.endswith("phone_detector") or (
                args and args[0] and "phone_detector" in str(args[0])
            ):
                raise ImportError("giả lập thiếu module cho test")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(bench.BenchmarkError) as info:
            bench.run_benchmark(
                Config(), 0.1, source_override=_frames(), profile="pose_phone"
            )

        message = str(info.value)
        assert "phone_detector" in message
        assert "r3-phone" in message
        # Không được khuyên người dùng "cứ chạy pose".
        assert "Không đo thay" in message or "không" in message.lower()

    def test_pose_phone_face_thieu_module_thi_tu_choi(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch)

        with pytest.raises(bench.BenchmarkError) as info:
            bench.run_benchmark(
                Config(),
                0.1,
                source_override=_frames(),
                profile="pose_phone_face",
            )
        assert str(info.value).strip()

    def test_main_tra_ma_khac_0_khi_ho_so_chua_ho_tro(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Qua đường CLI thật: phải là mã lỗi, tuyệt đối không phải 0."""
        _patch(monkeypatch)
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "camera:\n  source: usb:0\n", encoding="utf-8"
        )

        code = bench.main(
            [
                "--config", str(config_path),
                "--seconds", "0.1",
                "--profile", "pose_phone",
            ]
        )
        assert code != 0

    def test_khong_in_bao_cao_khi_ho_so_bi_tu_choi(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Không được in bảng FPS nào khi hồ sơ bị từ chối."""
        _patch(monkeypatch)
        config_path = tmp_path / "config.yaml"
        config_path.write_text("camera:\n  source: usb:0\n", encoding="utf-8")

        bench.main(
            [
                "--config", str(config_path),
                "--seconds", "0.1",
                "--profile", "pose_phone_face",
            ]
        )

        captured = capsys.readouterr()
        assert "BÁO CÁO BENCHMARK" not in captured.out
        assert "FPS pipeline" not in captured.out


# --------------------------------------------------------------------------
# Chống tái phát: số liệu bịa không được quay lại spec
# --------------------------------------------------------------------------

#: Các giá trị đã bị hạ nhãn ngày 2026-10-29 (SPEC_V3 §19). Dạng thập phân
#: theo cả hai quy ước dấu phẩy/chấm vì tài liệu dùng dấu phẩy.
_BIA = ("6,18", "6.18", "4,74", "4.74", "112,5", "112.5")


def _section(text: str, start_marker: str, end_marker: str) -> str:
    """Cắt một mục Markdown giữa hai tiêu đề ``##``."""
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


def test_spec_khong_con_so_fps_bia() -> None:
    """§4.3 và §8.1 của SPEC_V3 không được chứa lại các số đã hạ nhãn.

    Bài này đọc file spec **như dữ liệu**. Xoá nó đi là mở đường cho đúng sự
    cố cũ quay lại (một con số bịa được chép sang ``config.yaml`` và docstring).
    """
    assert _SPEC.is_file(), f"Không thấy spec: {_SPEC}"
    text = _SPEC.read_text(encoding="utf-8")

    checked = {
        "§4.3": _section(text, "### 4.3 Ngân sách FPS", "## 5. Chi tiết"),
        "§8.1": _section(text, "### 8.1 Hiệu năng", "### 8.2"),
    }
    for name, body in checked.items():
        for value in _BIA:
            assert value not in body, (
                f"{name} còn chứa số liệu đã bị hạ nhãn: {value!r}. Số này "
                "không đến từ bài đo nào (SPEC_V3 §19); không được đưa lại "
                "dưới bất kỳ nhãn nào."
            )


def test_spec_ghi_ro_moi_nhip_detect_deu_khong_dat() -> None:
    """§4.3 phải nói thẳng cả bốn nhịp detect đều chưa đạt 5 FPS."""
    text = _SPEC.read_text(encoding="utf-8")
    body = _section(text, "### 4.3 Ngân sách FPS", "## 5. Chi tiết")

    for fps in ("3,36", "4,02", "4,31", "4,46"):
        assert fps in body, f"§4.3 thiếu kết quả {fps} FPS cho một nhịp detect"
    assert "KHÔNG" in body
    # Kết luận phải nêu rõ detect chưa được đo trong pipeline thật.
    lowered = body.lower()
    assert "chưa" in lowered
    assert "5 fps" in lowered


def test_spec_co_dau_vet_dinh_chinh() -> None:
    """Phải còn mục ghi ngày, số bị hạ nhãn và lý do — không xoá dấu vết."""
    text = _SPEC.read_text(encoding="utf-8")
    assert "## 19." in text
    tail = text[text.index("## 19.") :]
    assert "2026-10-29" in tail
    for value in ("112,5", "4,74", "6,18"):
        assert value in tail, (
            f"Mục đính chính phải nêu lại {value!r} trong bảng 'số nào bị hạ "
            "nhãn'; người đọc sau cần biết vì sao con số đổi."
        )


# --------------------------------------------------------------------------
# Nhãn hồ sơ trong báo cáo không được nói dối
# --------------------------------------------------------------------------

#: Ghi chú thiết kế cho hai bài dưới.
#:
#: Ở nhánh ``r3-fps``, ``pose_phone``/``pose_phone_face`` **luôn** bị từ chối
#: vì thiếu ``phone_detector``. Nghĩa là nhánh "hồ sơ chạy được thật" của
#: ``run_benchmark`` chưa có test nào đi qua — và một mutation đổi nhãn báo
#: cáo về ``pose`` trong khi vẫn chạy model phụ đã **sống sót**. Hai bài dưới
#: bịt lỗ đó bằng cách tiêm một model phụ giả, nên nhánh thật được chạy mà
#: không cần module của nhánh khác.


class _FakeExtra(bench._ExtraModel):
    """Model phụ giả: đếm số lần được gọi, không đụng model/thư viện nào."""

    def __init__(self) -> None:
        self.seen = 0

        def step(frame, pose, now) -> None:  # noqa: ANN001
            self.seen += 1

        super().__init__(
            name="gia-lap-detect",
            role="phone_detect",
            cadence="mỗi khung",
            step=step,
            meta={"imgsz": 320},
        )


class TestNhanHoSoTrongBaoCao:
    def test_ho_so_chay_duoc_ghi_dung_nhan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Báo cáo phải mang đúng ``profile`` và liệt kê model phụ đã chạy."""
        _patch(monkeypatch)
        extra = _FakeExtra()
        monkeypatch.setattr(
            bench, "_build_extras", lambda config, profile: [extra]
        )

        report = bench.run_benchmark(
            Config(), 0.15, source_override=_frames(), profile="pose_phone"
        )

        # Nhãn không được rơi về 'pose' dù hồ sơ chọn là pose_phone.
        assert report["profile"] == "pose_phone"
        roles = {entry["role"] for entry in report["models"]}
        assert "phone_detect" in roles, (
            "báo cáo phải liệt kê model phụ đã chạy; thiếu nó thì người đọc "
            "tưởng bài đo chỉ có pose"
        )
        assert extra.seen > 0, "model phụ phải thật sự được gọi"
        assert any("pose_phone" in notice for notice in report["notices"])

    def test_model_phu_khong_lam_sap_bai_do(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Model phụ ném lỗi: đếm riêng, khung pose vẫn được đo."""
        _patch(monkeypatch)

        def boom(frame, pose, now) -> None:  # noqa: ANN001
            raise RuntimeError("model phụ hỏng")

        extra = bench._ExtraModel(
            name="hỏng", role="phone_detect", cadence="mỗi khung",
            step=boom, meta={},
        )
        monkeypatch.setattr(
            bench, "_build_extras", lambda config, profile: [extra]
        )

        report = bench.run_benchmark(
            Config(), 0.15, source_override=_frames(), profile="pose_phone"
        )

        assert report["frames"]["measured"] > 0
        entry = next(
            item for item in report["models"] if item["role"] == "phone_detect"
        )
        assert entry["errors"] > 0
        assert entry["timing_ms"] is None


def test_parser_co_profile_va_mac_dinh_la_pose() -> None:
    parser = bench.build_parser()
    args = parser.parse_args([])
    assert args.profile == "pose"
    assert set(bench.PROFILES) >= {"pose", "pose_phone", "pose_phone_face"}
