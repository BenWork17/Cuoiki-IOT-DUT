"""Chặn tái phạm: spec không được hứa một lệnh/cờ không tồn tại.

Lỗi đang sửa (SPEC_V3 §7 cũ) là kiểu lỗi **tài liệu hứa một thứ chưa làm**:
`python -m posture_monitor speak-test`, `faces list`, `schedule check`,
`--signals`, `--no-face`, `--no-phone` đều chưa từng có trong parser, và
`--profile full` không nằm trong :data:`posture_monitor.benchmark.PROFILES`.
§8 còn gắn một tiêu chí nghiệm thu vào `schedule check`.

Bài kiểm thử đọc ``docs/SPEC_V3.md`` **như dữ liệu** (giống
``test_benchmark_profile.py``) và đối chiếu từng dòng với mã thật:

(a) mọi ``python -m posture_monitor <lệnh>`` phải có lệnh con trong
    ``build_parser()``;
(b) mọi ``--profile <tên>`` phải có tên trong ``benchmark.PROFILES``.

**Ngoại lệ duy nhất:** chính dòng đó ghi rõ ``chưa hiện thực``. Marker phải
nằm **cùng dòng** với tên — không được miễn trừ chỉ vì tên xuất hiện ở một
chỗ khác trong file. Nhờ vậy khi ai đó thêm lại một dòng lệnh hứa hão mà
quên ghi chú, test đỏ ngay, và thông điệp nêu tên lệnh kèm số dòng.

Không cần camera, trọng số hay mạng: chỉ import parser.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor import benchmark as bench  # noqa: E402
from posture_monitor.__main__ import build_parser  # noqa: E402

_SPEC = _REPO_ROOT / "docs" / "SPEC_V3.md"

#: Chuỗi đánh dấu một dòng **đã tự khai** là lệnh chưa tồn tại. Phải xuất hiện
#: trên đúng dòng đó; xem docstring module.
_MARKER = "chưa hiện thực"

#: ``python -m posture_monitor <lệnh>``. Không khớp
#: ``python -m posture_monitor.benchmark`` (không có khoảng trắng sau tên
#: module) nên dạng chạy module con không bị nhận nhầm là lệnh con.
_CLI_RE = re.compile(r"python\s+-m\s+posture_monitor\s+(?P<command>[A-Za-z0-9_-]+)")

#: ``--profile <tên>``; chỉ bắt tên, không bắt các chỗ nhắc trống tới cờ.
_PROFILE_RE = re.compile(r"--profile\s+(?P<profile>[A-Za-z0-9_]+)")


def _spec_lines() -> list[tuple[int, str]]:
    """Trả ``(số dòng 1-based, nội dung)`` cho mọi dòng của spec."""
    assert _SPEC.is_file(), f"Không thấy spec: {_SPEC}"
    text = _SPEC.read_text(encoding="utf-8")
    return list(enumerate(text.splitlines(), start=1))


def _real_commands() -> set[str]:
    """Tên các lệnh con mà CLI thật đăng ký qua ``add_parser``."""
    parser = build_parser()
    for action in parser._actions:  # noqa: SLF001 - argparse không có API công khai
        choices = getattr(action, "choices", None)
        if choices:
            return set(choices)
    raise AssertionError("Không đọc được danh sách lệnh con của build_parser()")


def _violations(
    lines: list[tuple[int, str]],
    pattern: re.Pattern[str],
    known: set[str],
    group: str,
) -> list[tuple[int, str]]:
    """Liệt kê ``(số dòng, tên sai)`` chưa tồn tại và không có marker cùng dòng."""
    bad: list[tuple[int, str]] = []
    for number, line in lines:
        for match in pattern.finditer(line):
            name = match.group(group)
            if name in known:
                continue
            if _MARKER in line:
                # Dòng đã tự khai "chưa hiện thực": ngoại lệ hợp lệ.
                continue
            bad.append((number, name))
    return bad


def _format(bad: list[tuple[int, str]], what: str, hint: str) -> str:
    detail = "; ".join(f"{name!r} ở dòng {number}" for number, name in bad)
    return (
        f"SPEC_V3 hứa {what} nhưng mã không có: {detail}. "
        f"{hint} Nếu tính năng thật sự chưa có, ghi rõ 'chưa hiện thực' "
        "ngay trên chính dòng đó."
    )


# --------------------------------------------------------------------------
# (a) Lệnh con dòng lệnh
# --------------------------------------------------------------------------


def test_moi_lenh_con_trong_spec_deu_co_that() -> None:
    """Mọi ``python -m posture_monitor <lệnh>`` phải là lệnh con có thật.

    Không chạy lệnh nào, chỉ đọc parser: lệnh hứa hão là lỗi tài liệu.
    """
    lines = _spec_lines()
    known = _real_commands()
    assert {"run", "calibrate", "replay", "benchmark"} <= known, (
        f"Parser đổi tên lệnh con: {sorted(known)}. Spec §7.1 mô tả bốn lệnh "
        "này; đổi ở mã thì phải đổi ở tài liệu."
    )

    bad = _violations(lines, _CLI_RE, known, "command")
    assert not bad, _format(
        bad,
        "các lệnh con dòng lệnh",
        f"Lệnh con thật hiện có: {', '.join(sorted(known))}.",
    )


def test_marker_chua_hien_thuc_khong_ro_ri_sang_dong_khac() -> None:
    """Marker ``chưa hiện thực`` chỉ miễn trừ cho **chính dòng** mang nó.

    Dòng nêu lệnh mà không có marker phải bị bắt, kể cả khi một dòng khác
    trong file có chữ "chưa hiện thực". Bài này khoá đúng lỗ hổng đó: nếu ai
    sửa test thành "file có chữ đó thì bỏ qua", nó sẽ đỏ.
    """
    lines = _spec_lines()
    marker_lines = [number for number, line in lines if _MARKER in line]
    assert marker_lines, (
        "Spec không còn dòng nào ghi 'chưa hiện thực'. Nếu mọi lệnh §7 đã được "
        "hiện thực thật, xoá cả khối ghi chú; nếu không, khôi phục ghi chú."
    )

    known = _real_commands()
    bad = _violations(lines, _CLI_RE, known, "command")
    for number, _name in bad:
        assert number not in marker_lines
    assert not bad


# --------------------------------------------------------------------------
# (b) Tên hồ sơ benchmark
# --------------------------------------------------------------------------


def test_moi_ten_profile_trong_spec_deu_co_that() -> None:
    """Mọi ``--profile <tên>`` phải có trong ``benchmark.PROFILES``."""
    lines = _spec_lines()
    known = set(bench.PROFILES)

    bad = _violations(lines, _PROFILE_RE, known, "profile")
    assert not bad, _format(
        bad,
        "các hồ sơ benchmark",
        f"Hồ sơ thật hiện có: {', '.join(sorted(known))}.",
    )


def test_profile_xuat_hien_it_nhat_mot_lan() -> None:
    """Chống test rỗng: spec thật sự có nhắc ``--profile`` để mà đối chiếu."""
    lines = _spec_lines()
    found = [
        match.group("profile")
        for _number, line in lines
        for match in _PROFILE_RE.finditer(line)
    ]
    assert found, "Không tìm thấy dòng '--profile <tên>' nào trong spec."
    assert set(found) <= set(bench.PROFILES)


# --------------------------------------------------------------------------
# Ghi đè một phần: cờ của lệnh **có thật** cũng phải kiểm, không chỉ tên lệnh
# --------------------------------------------------------------------------

#: Cờ từng bị hứa cho một lệnh con *có thật* — kiểm tên lệnh một mình sẽ bỏ
#: sót đúng lớp lỗi này.
_PROMISED_FLAGS = {
    "run": ("--no-face", "--no-phone"),
    "replay": ("--signals",),
}


def _parser_accepts(command: str, flag: str) -> bool:
    """``argparse`` có nhận được ``command flag`` không (dùng mẩu tối thiểu)."""
    from posture_monitor.__main__ import build_parser as _build

    argv = [command, flag]
    if command == "replay":
        argv.append("video.mp4")
    try:
        _build().parse_args(argv)
    except SystemExit:
        return False
    return True


def test_co_hua_cho_lenh_co_that_phai_khop_parser() -> None:
    """``run --no-face``… : hoặc parser nhận, hoặc dòng spec phải có marker.

    Không khảng định "chưa có" một cách cứng: nếu ai đó hiện thực cờ này thật,
    bài này vẫn xanh, miễn là parser nhận nó. Nó chỉ đỏ khi spec hứa cờ
    không tồn tại mà không ghi chú.
    """
    lines = _spec_lines()
    for command, flags in _PROMISED_FLAGS.items():
        for flag in flags:
            if _parser_accepts(command, flag):
                continue  # Đã hiện thực: lời hứa thành sự thật.
            # Chưa hiện thực: mọi dòng nêu cờ này phải tự khai.
            mentions = [
                (number, line)
                for number, line in lines
                if flag in line and _CLI_RE.search(line)
            ]
            assert mentions, (
                f"Spec không còn nhắc '{flag}' cho '{command}'; xoá bài này "
                "cùng dòng hứa cũ nếu tính năng bị bỏ hẳn."
            )
            for number, line in mentions:
                assert _MARKER in line, (
                    f"SPEC_V3 dòng {number} hứa '{command} {flag}' nhưng "
                    f"parser không nhận cờ này, và dòng đó không ghi 'chưa "
                    f"hiện thực'. Nội dung: {line.strip()!r}"
                )
