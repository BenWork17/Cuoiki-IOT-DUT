# -*- coding: utf-8 -*-
"""Kiểm tra sâu tệp .docx: thứ tự phần tử theo schema OOXML + đọc lại toàn bộ.

python-docx không kiểm tra thứ tự phần tử con trong w:pPr / w:rPr / w:tcPr.
Sai thứ tự làm Word treo hoặc hiện hộp thoại "repair". Script này soát đúng chỗ đó.

Chạy:  python BaoCao/verify_docx.py
"""

from __future__ import annotations

import sys
import zipfile
from collections import Counter
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

HERE = Path(__file__).resolve().parent
TARGET = HERE / "BaoCao_DoAn_GiamSatHocTap.docx"

ORDERS = {
    "pPr": (
        "pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr",
        "widowControl", "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs",
        "suppressAutoHyphens", "kinsoku", "wordWrap", "overflowPunct",
        "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
        "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents",
        "suppressOverlap", "jc", "textDirection", "textAlignment",
        "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr",
        "pPrChange",
    ),
    "rPr": (
        "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps",
        "strike", "dstrike", "outline", "shadow", "emboss", "imprint",
        "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing",
        "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect",
        "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang",
        "eastAsianLayout", "specVanish", "oMath",
    ),
    "tcPr": (
        "cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders", "shd",
        "noWrap", "tcMar", "textDirection", "tcFitText", "vAlign", "hideMark",
        "headers", "cellIns", "cellDel", "cellMerge", "tcPrChange",
    ),
}


def local(tag: str) -> str:
    return tag.split("}")[-1]


def check_order(root, label: str) -> list[str]:
    problems: list[str] = []
    for container, order in ORDERS.items():
        index = {name: i for i, name in enumerate(order)}
        for node in root.iter(qn(f"w:{container}")):
            seen = -1
            for child in node:
                name = local(child.tag)
                if name not in index:
                    continue
                if index[name] < seen:
                    problems.append(
                        f"{label}: w:{container} — '{name}' đứng sau phần tử có thứ tự lớn hơn"
                    )
                    break
                seen = index[name]
    return problems


def main() -> int:
    if not TARGET.is_file():
        print("KHÔNG THẤY", TARGET)
        return 1

    print("== TỆP ==")
    print("  đường dẫn :", TARGET)
    print(f"  dung lượng: {TARGET.stat().st_size / 1024:.0f} KB")

    with zipfile.ZipFile(TARGET) as zf:
        broken = zf.testzip()
        names = zf.namelist()
        media = sorted(n for n in names if n.startswith("word/media/"))
        print("  zip hỏng   :", broken or "không")
        print("  số media   :", len(media))
        for m in media:
            print(f"    - {m:24s} {zf.getinfo(m).file_size / 1024:6.0f} KB")

    doc = Document(str(TARGET))
    print("\n== CẤU TRÚC ==")
    print("  đoạn văn:", len(doc.paragraphs), "· bảng:", len(doc.tables),
          "· section:", len(doc.sections))

    problems: list[str] = []
    problems += check_order(doc.element.body, "body")
    for idx, section in enumerate(doc.sections, start=1):
        problems += check_order(section.footer._element, f"footer{idx}")
        problems += check_order(section.header._element, f"header{idx}")
    styles_el = doc.styles.element
    problems += check_order(styles_el, "styles")

    print("\n== THỨ TỰ PHẦN TỬ THEO SCHEMA OOXML ==")
    if problems:
        for p in problems[:20]:
            print("  LỖI:", p)
        print(f"  tổng lỗi: {len(problems)}")
    else:
        print("  không có lỗi thứ tự trong pPr / rPr / tcPr")

    # --- tiêu đề
    heads = []
    for p in doc.paragraphs:
        style = p.style.name or ""
        if style.startswith("Heading"):
            try:
                level = int(style.split()[-1])
            except ValueError:
                level = 0
            heads.append((level, p.text.strip()))

    print("\n== TIÊU ĐỀ CẤP 1–2 ==")
    for level, text in heads:
        if level <= 2:
            print("  " + "   " * (level - 1) + f"H{level} · {text}")
    print("  tổng tiêu đề:", len(heads))

    for want in ("Chương 1", "Chương 2", "Chương 3", "Chương 4", "Chương 5", "Chương 6", "Phụ lục"):
        ok = any(want in t for _, t in heads)
        print(f"    {want:11s}: {'CÓ' if ok else 'THIẾU'}")

    # --- bảng
    print("\n== BẢNG ==")
    bad_tables = 0
    empty_cells = 0
    for i, table in enumerate(doc.tables, start=1):
        widths = {len(r.cells) for r in table.rows}
        if len(widths) != 1:
            bad_tables += 1
            print(f"    bảng {i}: số cột không đều {widths}")
        if not table.rows[0].cells[0].text.strip():
            print(f"    bảng {i}: dòng đầu trống")
        for row in table.rows:
            for cell in row.cells:
                if not cell.text.strip():
                    empty_cells += 1
    print(f"  {len(doc.tables)} bảng · bảng lỗi: {bad_tables} · ô trống: {empty_cells}")

    # --- văn bản
    chunks = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                chunks.extend(p.text for p in cell.paragraphs)
    text = "\n".join(chunks)

    print("\n== VĂN BẢN ==")
    print("  tổng ký tự:", len(text))
    print("  U+FFFD     :", text.count("\ufffd"))
    print("  '**' sót   :", text.count("**"))
    print("  '`' sót    :", text.count("`") )
    print("  '![' sót   :", text.count("!["))
    print("  '](' sót   :", text.count("]("))

    marks = [
        "Hệ thống giám sát học tập", "199,25", "5,02", "86,1", "98,6",
        "DashboardState", "ĐÃ ĐO", "TÍNH TỪ ĐO", "CHƯA ĐO", "704×576",
        "YOLO11n-pose", "SFace", "backchannel", "ONVIF",
    ]
    print("\n  mốc nội dung (không phân biệt hoa thường):")
    haystack = text.casefold()
    missing = 0
    for m in marks:
        ok = m.casefold() in haystack
        missing += 0 if ok else 1
        print(f"    {m:22s}: {'CÓ' if ok else 'THIẾU'}")

    # --- thống kê định dạng
    font_counter: Counter[str] = Counter()
    size_counter: Counter[float] = Counter()
    for p in doc.paragraphs:
        for r in p.runs:
            if r.font.name:
                font_counter[r.font.name] += 1
            if r.font.size:
                size_counter[r.font.size.pt] += 1
    print("\n== ĐỊNH DẠNG ==")
    print("  font dùng :", dict(font_counter.most_common(5)))
    print("  cỡ chữ    :", dict(size_counter.most_common(6)))

    ok = not problems and bad_tables == 0 and missing == 0 and text.count("\ufffd") == 0
    print("\nKẾT LUẬN:", "OK" if ok else "CẦN SỬA")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
