"""Chặn tái phát số liệu FPS bịa trong tài liệu về detect điện thoại.

Ba con số từng được ghi kèm nhãn "ĐO THẬT" nhưng không hề tồn tại trong bất
kỳ bài đo nào của dự án:

- ``112,5`` — không có trong bất kỳ artifact nào (``grep`` toàn repo: 0 hit
  ngoài chính các dòng tài liệu đó).
- ``6,18`` — suy ra từ ``112,5`` bịa, và bỏ qua hoàn toàn chi phí capture.
- ``4,74`` — suy ra từ ``112,5`` bịa.

Phep đo pipeline thật duy nhất của dự án là pose-only trên camera thật:
199,39 ms/khung → 5,01 FPS. Ghép detect cách khung vào đó ra ≈ 4,02 FPS,
**không đạt** ≥ 5 FPS. Vì vậy không được phép quảng cáo cấu hình có detect
là "đạt ≥ 5 FPS" khi chưa đo.

Test này đọc ``config.yaml`` và ``phone_detector.py`` như dữ liệu văn bản,
không import module — mục đích là bắt chính câu chữ trong tài liệu.

Ma trận mutation tương ứng (xem báo cáo):

- thêm lại ``6,18`` vào comment ``config.yaml`` → :func:`test_khong_con_so_fps_bia`.
- thêm lại ``112,5`` vào docstring ``phone_detector.py`` → :func:`test_khong_con_so_fps_bia`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG = _REPO_ROOT / "config.yaml"
_PHONE_DETECTOR = _REPO_ROOT / "src" / "posture_monitor" / "phone_detector.py"

#: Số FPS bịa, cả dạng dấu phẩy thập phân lẫn dấu chấm. Chỉ những số này bị
#: cấm — ``98,6``/``4,90`` là đo thật (khung tổng hợp, chỉ inference) nên vẫn
#: được xuất hiện.
_SO_FPS_BIA = ("112,5", "112.5", "6,18", "6.18", "4,74", "4.74")

#: Nhãn khẳng định "đã đo" — không được đứng cùng dòng với "FPS" để tránh
#: gán nhãn đo thật cho một con số chưa từng được đo.
_NHAN_DA_DO = ("ĐO THẬT", "đo thật", "DOC THAT", "do that")


def _doc(path: Path) -> str:
    assert path.is_file(), f"thiếu file cần kiểm: {path}"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", [_CONFIG, _PHONE_DETECTOR], ids=["config", "phone_detector"])
@pytest.mark.parametrize("so", _SO_FPS_BIA)
def test_khong_con_so_fps_bia(path: Path, so: str) -> None:
    """Số FPS bịa không được quay lại ``config.yaml`` hay docstring module."""
    noi_dung = _doc(path)
    assert so not in noi_dung, (
        f"{path.name} còn chứa số FPS bịa {so!r}. Ba số 112,5 / 6,18 / 4,74 "
        "không tồn tại trong artifact nào của dự án; phép đo pipeline thật "
        "duy nhất là pose-only 199,39 ms -> 5,01 FPS, và ghép detect cách "
        "khung vào đó ra ~4,02 FPS (KHÔNG đạt >= 5 FPS)."
    )


@pytest.mark.parametrize("path", [_CONFIG, _PHONE_DETECTOR], ids=["config", "phone_detector"])
def test_khong_gan_nhan_do_that_cho_fps(path: Path) -> None:
    """Không dòng tài liệu nào vừa nói "đã đo" vừa nói "FPS".

    Chi phí detect trong pipeline thật chưa được đo; giữ luật này để một câu
    kiểu "ĐO THẬT: 2 mới đạt >= 5 FPS" không lọt vào tài liệu lần nữa.
    """
    for so_dong, dong in enumerate(_doc(path).splitlines(), start=1):
        if "FPS" not in dong:
            continue
        for nhan in _NHAN_DA_DO:
            assert nhan not in dong, (
                f"{path.name}:{so_dong} gán nhãn {nhan!r} cho một khẳng định FPS "
                f"chưa có phép đo: {dong.strip()!r}. Cấu hình có detect chưa có "
                "ngân sách đo; phải đo bằng benchmark --profile pose_phone."
            )


def test_gia_tri_mac_dinh_detect_every_n_frames_khong_doi() -> None:
    """Sửa tài liệu không được đổi hành vi: mặc định vẫn là ``2``."""
    import yaml

    cau_hinh = yaml.safe_load(_doc(_CONFIG))
    phone = cau_hinh["phone"]
    assert phone["enabled"] is True
    assert phone["detect_every_n_frames"] == 2
