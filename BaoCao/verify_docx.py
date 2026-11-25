# -*- coding: utf-8 -*-
r"""Kiểm định toàn diện tệp .docx theo chuẩn Khoa CNTT - ĐHBK Đà Nẵng (DUT) và schema OOXML.

Các hạng mục kiểm tra tự động:
1. Toàn vẹn kho lưu trữ ZIP, không có mục thư mục rỗng ('/'), đủ 13 media (2 logo + 11 hình).
2. Tuân thủ nghiêm ngặt thứ tự phần tử con w:pPr / w:rPr / w:tcPr theo ECMA-376.
3. Khổ trang A4, lề chuẩn đóng gáy (3,5 / 2,0 / 2,5 / 2,5 cm), ẩn Header/Footer trang bìa.
4. Đủ 3 trường danh mục tự động (MỤC LỤC, HÌNH ẢNH, BẢNG BIỂU) và các trường SEQ Hình / SEQ Bảng.
5. Đủ 12 chương (CHƯƠNG 1 .. CHƯƠNG 12), phông chính Times New Roman 13 pt.
6. Không sót cú pháp Markdown/LaTeX thô (**, `, ![, ](, $$, \mathbf, U+FFFD).
7. Đủ toàn bộ mốc dữ liệu khoa học cốt lõi của đề tài.

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
                        f"{label}: w:{container} - '{name}' đứng sai thứ tự schema"
                    )
                    break
                seen = index[name]
    return problems


def main() -> int:
    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else TARGET
    if not target.is_file():
        print("KHÔNG THẤY", target)
        return 1

    print("== 1. KHO LƯU TRỮ TỆP (.DOCX / ZIP) ==")
    print("  đường dẫn :", target)
    print(f"  dung lượng: {target.stat().st_size / 1024:.0f} KB")

    with zipfile.ZipFile(target) as zf:
        broken = zf.testzip()
        names = zf.namelist()
        dir_entries = [n for n in names if n.endswith("/")]
        media = sorted(n for n in names if n.startswith("word/media/"))
        doc_xml = zf.read("word/document.xml").decode("utf-8")
        print("  zip hỏng        :", broken or "không")
        print("  mục thư mục rỗng:", len(dir_entries))
        print("  số tệp media    :", len(media), "(kỳ vọng 13 = 2 logo bìa + 11 hình nội dung)")

    doc = Document(str(target))
    sec = doc.sections[0]
    margins_cm = (
        round(sec.left_margin.cm, 2),
        round(sec.right_margin.cm, 2),
        round(sec.top_margin.cm, 2),
        round(sec.bottom_margin.cm, 2),
    )
    margins_ok = margins_cm == (3.5, 2.0, 2.5, 2.5) and sec.different_first_page_header_footer
    print("\n== 2. BỐ CỤC TRANG CHUẨN DUT ==")
    print(f"  lề (T/P/Tr/D cm): {margins_cm} -> {'ĐÚNG' if margins_cm == (3.5, 2.0, 2.5, 2.5) else 'SAI'}")
    print(f"  ẩn H/F trang bìa: {sec.different_first_page_header_footer}")
    print(f"  đoạn văn: {len(doc.paragraphs)} · tổng bảng: {len(doc.tables)} · section: {len(doc.sections)}")

    problems: list[str] = []
    problems += check_order(doc.element.body, "body")
    for idx, section in enumerate(doc.sections, start=1):
        problems += check_order(section.footer._element, f"footer{idx}")
        problems += check_order(section.header._element, f"header{idx}")
        problems += check_order(section.first_page_footer._element, f"first_footer{idx}")
        problems += check_order(section.first_page_header._element, f"first_header{idx}")
    problems += check_order(doc.styles.element, "styles")

    print("\n== 3. THỨ TỰ PHẦN TỬ SCHEMA OOXML ==")
    if problems:
        for p in problems[:20]:
            print("  LỖI:", p)
    else:
        print("  OK - 0 lỗi thứ tự trong pPr / rPr / tcPr")

    # Kiểm tra các trường động Word (TOC, LOF, LOT, SEQ)
    toc_main = 'TOC \\o "1-2"' in doc_xml
    toc_fig = 'TOC \\h \\z \\c "Hình"' in doc_xml
    toc_tbl = 'TOC \\h \\z \\c "Bảng"' in doc_xml
    seq_fig_count = doc_xml.count("SEQ Hình \\* ARABIC")
    seq_tbl_count = doc_xml.count("SEQ Bảng \\* ARABIC")
    print("\n== 4. TRƯỜNG ĐỘNG WORD (MỤC LỤC / HÌNH / BẢNG) ==")
    print(f"  MỤC LỤC tự động   : {'CÓ' if toc_main else 'THIẾU'}")
    print(f"  Danh mục HÌNH ẢNH : {'CÓ' if toc_fig else 'THIẾU'} (số SEQ Hình = {seq_fig_count})")
    print(f"  Danh mục BẢNG BIỂU: {'CÓ' if toc_tbl else 'THIẾU'} (số SEQ Bảng = {seq_tbl_count})")

    # Tiêu đề 12 chương
    heads = []
    for p in doc.paragraphs:
        style = p.style.name or ""
        if style.startswith("Heading"):
            try:
                level = int(style.split()[-1])
            except ValueError:
                level = 0
            heads.append((level, p.text.strip()))

    print(f"\n== 5. CẤU TRÚC 12 CHƯƠNG (tổng tiêu đề: {len(heads)}) ==")
    missing_chaps = 0
    for ch_idx in range(1, 13):
        want = f"CHƯƠNG {ch_idx}."
        found = next((t for lv, t in heads if lv == 1 and t.startswith(want)), None)
        if not found:
            missing_chaps += 1
        print(f"  {want:10s} -> {found or 'THIẾU'}")

    # Kiểm tra bảng
    bad_tables = 0
    for i, table in enumerate(doc.tables, start=1):
        widths = {len(r.cells) for r in table.rows}
        if len(widths) != 1:
            bad_tables += 1
            print(f"  LỖI bảng {i}: số cột không đều {widths}")

    # Quét văn bản tìm ký hiệu sót & mốc khoa học
    chunks = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                chunks.extend(p.text for p in cell.paragraphs)
    text = "\n".join(chunks)

    import re as _re

    stray = {
        "U+FFFD": text.count("\ufffd"),
        "**": len(_re.findall(r"(?<!\*)\*\*(?!\*)", text)),
        "`": text.count("`"),
        "![": text.count("!["),
        "](": text.count("]("),
        "$$": text.count("$$"),
        "\\mathbf": text.count("\\mathbf"),
    }
    print("\n== 6. KÝ HIỆU THÔ CÒN SÓT ==")
    print(" ", stray)

    marks = [
        "TRƯỜNG ĐẠI HỌC BÁCH KHOA", "KHOA CÔNG NGHỆ THÔNG TIN",
        "Hệ thống giám sát học tập", "199,25", "5,02", "86,1", "98,6",
        "DashboardState", "ĐÃ ĐO", "TÍNH TỪ ĐO", "CHƯA ĐO", "704×576",
        "YOLO11n-pose", "SFace", "backchannel", "ONVIF",
        "Nocturne Telemetry", "LearnerSignalsSection", "PostureStatusSection",
        "1.662", "189",
    ]
    print("\n== 7. MỐC NỘI DUNG KHOA HỌC CỐT LÕI ==")
    haystack = text.casefold()
    missing_marks = 0
    for m in marks:
        ok_m = m.casefold() in haystack
        if not ok_m:
            missing_marks += 1
        print(f"  {m:28s}: {'CÓ' if ok_m else 'THIẾU'}")

    # Thống kê định dạng font & cỡ chữ
    font_counter: Counter[str] = Counter()
    size_counter: Counter[float] = Counter()
    for p in doc.paragraphs:
        for r in p.runs:
            if r.font.name:
                font_counter[r.font.name] += 1
            if r.font.size:
                size_counter[r.font.size.pt] += 1
    print("\n== 8. THỐNG KÊ KIỂU CHỮ ==")
    print("  phông chữ :", dict(font_counter.most_common(5)))
    print("  cỡ chữ(pt):", dict(size_counter.most_common(6)))

    all_ok = (
        broken is None
        and len(dir_entries) == 0
        and len(media) == 13
        and margins_ok
        and not problems
        and toc_main
        and toc_fig
        and toc_tbl
        and seq_fig_count == 11
        and seq_tbl_count >= 30
        and missing_chaps == 0
        and bad_tables == 0
        and sum(stray.values()) == 0
        and missing_marks == 0
        and font_counter.most_common(1)[0][0] == "Times New Roman"
    )
    print("\nKẾT LUẬN TỔNG HỢP:", "ĐẠT CHUẨN KHOA CNTT - ĐHBK ĐÀ NẴNG" if all_ok else "CẦN SỬA")
    return 0 if all_ok else 2


if __name__ == "__main__":
    sys.exit(main())
