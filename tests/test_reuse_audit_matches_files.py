"""Kiểm tra ``docs/REUSE_AUDIT.md`` khớp với tệp thật trong repo.

Tài liệu đánh giá tái sử dụng ghi dung lượng và sha256 cho những tệp được đưa
vào repo (ví dụ ``chart.umd.min.js``). Nếu ai thay tệp mà quên cập nhật tài
liệu — hoặc sửa tài liệu thành số sai — thì bảng "Cách kiểm chứng" trở thành
lời khai không kiểm chứng được. Test này đọc chính tài liệu rồi so với byte
thật của tệp.

Phạm vi: **chỉ** những dòng trong tài liệu có ghi sha256 và có nhắc tên một tệp
mà basename của nó tồn tại trong repo. Tài liệu nhắc nhiều thứ khác (số sao,
số tham số, phiên bản wheel trên PyPI, tệp không commit như ``*.onnx``/``*.pt``)
không được test này phủ — chúng không phải tệp có thật trong repo, nên không
có gì để so. Một tệp được nhắc mà không có sha256 cũng không bị kiểm ở đây.

Cách làm: tìm ``sha256 `([0-9a-f]{64})``` trên từng dòng, lấy các tên tệp trong
dấu backtick trên cùng dòng, đối chiếu basename với cây repo, rồi so cả sha256
lẫn dung lượng ghi kèm (``205.851 byte``). Chuỗi phiên bản trong backtick, ví dụ
``Chart.js v4.4.7``, cũng phải xuất hiện trong nội dung tệp.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_AUDIT = _REPO_ROOT / "docs" / "REUSE_AUDIT.md"

_SHA_RE = re.compile(r"sha256\s+`([0-9a-f]{64})`")
_SIZE_RE = re.compile(r"(\d[\d.,]*)\s*byte")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_VERSION_STR_RE = re.compile(r"`(Chart\.js v\d+\.\d+\.\d+)`")


def _parse_size(raw: str) -> int:
    """Đọc số byte kiểu tài liệu (``205.851`` là hàng nghìn, không phải thập phân)."""
    return int(re.sub(r"[.,]", "", raw))


def _repo_files_by_name() -> dict[str, list[Path]]:
    """Lập chỉ mục basename -> đường dẫn thật trong repo (bỏ qua .git)."""
    index: dict[str, list[Path]] = {}
    for path in _REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(_REPO_ROOT)
        if any(part.startswith(".") for part in rel.parts):
            continue
        index.setdefault(path.name, []).append(path)
    return index


def _audit_rows_with_sha():
    """Sinh (số dòng, nội dung dòng, sha256, các tên tệp trong backtick)."""
    text = _AUDIT.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = _SHA_RE.search(line)
        if not match:
            continue
        names = [tok for tok in _BACKTICK_RE.findall(line) if not tok.startswith("sha256")]
        yield lineno, line, match.group(1), names


def test_reuse_audit_size_and_sha256_match_repo_files():
    assert _AUDIT.is_file(), f"thiếu tài liệu {_AUDIT}"
    files_by_name = _repo_files_by_name()

    checked = 0
    for lineno, line, doc_sha, names in _audit_rows_with_sha():
        for name in names:
            basename = Path(name.replace("\\", "/")).name
            candidates = files_by_name.get(basename)
            if not candidates:
                continue  # tệp không nằm trong repo — ngoài phạm vi test này
            assert len(candidates) == 1, (
                f"REUSE_AUDIT.md:{lineno} nhắc `{name}` nhưng repo có "
                f"{len(candidates)} tệp cùng tên: {[str(p) for p in candidates]}"
            )
            path = candidates[0]
            data = path.read_bytes()
            actual_sha = hashlib.sha256(data).hexdigest()
            rel = path.relative_to(_REPO_ROOT)

            assert doc_sha == actual_sha, (
                f"REUSE_AUDIT.md:{lineno} ghi sha256 sai cho `{rel}`: "
                f"tài liệu {doc_sha}, tệp thật {actual_sha}"
            )

            size_match = _SIZE_RE.search(line)
            if size_match:
                doc_size = _parse_size(size_match.group(1))
                assert doc_size == len(data), (
                    f"REUSE_AUDIT.md:{lineno} ghi dung lượng sai cho `{rel}`: "
                    f"tài liệu {doc_size} byte, tệp thật {len(data)} byte"
                )

            for version in _VERSION_STR_RE.findall(line):
                assert version.encode() in data, (
                    f"REUSE_AUDIT.md:{lineno} khẳng định `{rel}` chứa chuỗi "
                    f"`{version}` nhưng không tìm thấy trong tệp"
                )
            checked += 1

    assert checked > 0, (
        "không đối chiếu được dòng nào — test sẽ xanh vô nghĩa nếu "
        "REUSE_AUDIT.md mất các dòng có sha256; hãy kiểm tra lại định dạng bảng"
    )


def test_reuse_audit_chart_js_row_is_covered():
    """Chốt rằng trường hợp chart.umd.min.js thực sự được kiểm, không bị bỏ qua.

    Nếu dòng Chart.js đổi định dạng (mất backtick, mất sha256) thì test trên sẽ
    lặng lẽ bỏ qua nó; test này giữ chỗ đó.
    """
    files_by_name = _repo_files_by_name()
    assert "chart.umd.min.js" in files_by_name, (
        "không tìm thấy chart.umd.min.js trong repo để đối chiếu"
    )
    covered = [
        (lineno, names)
        for lineno, _line, _sha, names in _audit_rows_with_sha()
        if any(Path(n).name == "chart.umd.min.js" for n in names)
    ]
    assert covered, "docs/REUSE_AUDIT.md không còn dòng sha256 nào cho chart.umd.min.js"
