# -*- coding: utf-8 -*-
"""Chuyển BAO_CAO_DO_AN.md sang .docx (Word) bằng python-docx.

Hỗ trợ: tiêu đề #..####, đoạn văn, **đậm**, *nghiêng*, `mã nội tuyến`,
danh sách gạch đầu dòng, danh sách số, bảng (có dòng căn lề),
khối mã ```, ảnh ![chú thích](đường/dẫn), trích dẫn >, đường kẻ ---.

Chạy:  python BaoCao/make_docx.py
Kết quả: BaoCao/BaoCao_DoAn_GiamSatHocTap.docx
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Emu, Pt, RGBColor
from PIL import Image as PILImage

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "BAO_CAO_DO_AN.md"
TARGET = HERE / "BaoCao_DoAn_GiamSatHocTap.docx"

BODY_FONT = "Calibri"
CODE_FONT = "Consolas"

INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x50, 0x5A, 0x66)
ACCENT = RGBColor(0x1F, 0x4E, 0x79)
CODE_INK = RGBColor(0x22, 0x2B, 0x38)


# ------------------------------------------------------------------ XML helpers
# Thứ tự phần tử con của w:rPr / w:pPr / w:tcPr là BẮT BUỘC theo schema OOXML.
# Chèn sai thứ tự làm Word treo hoặc phải "repair" tệp khi mở.
_RPR_ORDER = (
    "w:rStyle", "w:rFonts", "w:b", "w:bCs", "w:i", "w:iCs", "w:caps",
    "w:smallCaps", "w:strike", "w:dstrike", "w:outline", "w:shadow",
    "w:emboss", "w:imprint", "w:noProof", "w:snapToGrid", "w:vanish",
    "w:webHidden", "w:color", "w:spacing", "w:w", "w:kern", "w:position",
    "w:sz", "w:szCs", "w:highlight", "w:u", "w:effect", "w:bdr", "w:shd",
    "w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang",
    "w:eastAsianLayout", "w:specVanish", "w:oMath",
)

_PPR_ORDER = (
    "w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore", "w:framePr",
    "w:widowControl", "w:numPr", "w:suppressLineNumbers", "w:pBdr", "w:shd",
    "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
    "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN",
    "w:bidi", "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind",
    "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
    "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl",
    "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange",
)

_TCPR_ORDER = (
    "w:cnfStyle", "w:tcW", "w:gridSpan", "w:hMerge", "w:vMerge", "w:tcBorders",
    "w:shd", "w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText",
    "w:vAlign", "w:hideMark", "w:headers", "w:cellIns", "w:cellDel",
    "w:cellMerge", "w:tcPrChange",
)


def _insert_ordered(parent, element, order: tuple[str, ...]) -> None:
    """Chèn ``element`` vào ``parent`` đúng vị trí theo schema."""
    tag = element.tag.split("}")[-1]
    full = f"w:{tag}"
    try:
        index = order.index(full)
        successors = {qn(t) for t in order[index + 1:]}
    except ValueError:
        parent.append(element)
        return

    for child in parent:
        if child.tag in successors:
            child.addprevious(element)
            return
    parent.append(element)


def _shade_rpr(rpr, fill: str) -> None:
    for existing in rpr.findall(qn("w:shd")):
        rpr.remove(existing)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    _insert_ordered(rpr, shd, _RPR_ORDER)


def _cell_shade(cell, fill: str) -> None:
    tcpr = cell._tc.get_or_add_tcPr()
    for existing in tcpr.findall(qn("w:shd")):
        tcpr.remove(existing)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    _insert_ordered(tcpr, shd, _TCPR_ORDER)


def _para_border_bottom(paragraph, color="C7CED8", size=6) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    for existing in pPr.findall(qn("w:pBdr")):
        pPr.remove(existing)
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), color)
    borders.append(bottom)
    _insert_ordered(pPr, borders, _PPR_ORDER)


def _para_shade(paragraph, fill: str) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    for existing in pPr.findall(qn("w:shd")):
        pPr.remove(existing)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    _insert_ordered(pPr, shd, _PPR_ORDER)


def _set_font(run, name: str, size: float | None = None, *, bold=None,
              italic=None, color=None) -> None:
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if color is not None:
        run.font.color.rgb = color


def _add_page_number_field(paragraph) -> None:
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_end)
    _set_font(run, BODY_FONT, 9, color=MUTED)


# ------------------------------------------------------------------ inline
INLINE_RE = re.compile(
    r"(\*\*.+?\*\*|`[^`]+`|(?<![\w*])\*[^*\n]+?\*(?![\w*])|\[[^\]\n]+\]\([^)\n]+\))"
)


def add_inline(paragraph, text: str, *, size: float = 10.5, base_bold=False,
               base_italic=False, color=INK, depth: int = 0) -> None:
    """Thêm đoạn văn có **đậm**, *nghiêng*, `mã`, [liên kết](…) vào paragraph.

    ``*đoạn có `mã` bên trong*`` được xử lý đệ quy: dấu ``*`` ngoài cùng là
    nghiêng, phần ``mã`` bên trong vẫn giữ font code và in nghiêng.
    """
    if depth > 4:                       # chặn đệ quy vô hạn với dấu lạc
        run = paragraph.add_run(text)
        _set_font(run, BODY_FONT, size, bold=base_bold, italic=base_italic, color=color)
        return

    for piece in INLINE_RE.split(text):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**") and len(piece) > 4:
            add_inline(paragraph, piece[2:-2], size=size, base_bold=True,
                       base_italic=base_italic, color=color, depth=depth + 1)
        elif piece.startswith("`") and piece.endswith("`") and len(piece) > 2:
            run = paragraph.add_run(piece[1:-1])
            _set_font(run, CODE_FONT, size - 0.5, bold=base_bold,
                      italic=base_italic, color=CODE_INK)
            _shade_rpr(run._element.get_or_add_rPr(), "F1F3F6")
        elif piece.startswith("[") and "](" in piece and piece.endswith(")"):
            label = piece[1:piece.index("](")]
            run = paragraph.add_run(label)
            _set_font(run, BODY_FONT, size, bold=base_bold, italic=base_italic,
                      color=color)
        elif piece.startswith("*") and piece.endswith("*") and len(piece) > 2:
            add_inline(paragraph, piece[1:-1], size=size, base_bold=base_bold,
                       base_italic=True, color=color, depth=depth + 1)
        else:
            run = paragraph.add_run(piece)
            _set_font(run, BODY_FONT, size, bold=base_bold, italic=base_italic,
                      color=color)


# ------------------------------------------------------------------ document
def build_document() -> Document:
    doc = Document()

    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.2)
    section.bottom_margin = Cm(2.2)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2.0)

    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = INK
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.28

    for name, size, color, before, after in (
        ("Heading 1", 17, ACCENT, 20, 10),
        ("Heading 2", 13.5, ACCENT, 14, 6),
        ("Heading 3", 11.5, INK, 11, 4),
        ("Heading 4", 10.5, INK, 9, 3),
    ):
        style = doc.styles[name]
        style.font.name = BODY_FONT
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = color
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True

    # chân trang: số trang
    footer_p = section.footer.paragraphs[0]
    footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer_p.add_run("Báo cáo đồ án — Hệ thống giám sát học tập trên Raspberry Pi 4   ·   ")
    _set_font(run, BODY_FONT, 8.5, color=MUTED)
    _add_page_number_field(footer_p)

    return doc


def add_cover(doc: Document, meta: dict[str, str]) -> None:
    for _ in range(3):
        doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("BÁO CÁO ĐỒ ÁN")
    _set_font(run, BODY_FONT, 15, bold=True, color=MUTED)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(10)
    run = p.add_run("HỆ THỐNG GIÁM SÁT HỌC TẬP\nTRÊN RASPBERRY PI 4")
    _set_font(run, BODY_FONT, 28, bold=True, color=ACCENT)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(14)
    run = p.add_run(
        "Camera IP · Model AI trên thiết bị biên · Dashboard web · Cảnh báo ra loa"
    )
    _set_font(run, BODY_FONT, 11.5, italic=True, color=MUTED)

    doc.add_paragraph()
    doc.add_paragraph()
    doc.add_paragraph()

    rows = [
        ("Sáu chương nội dung", "Tổng quan · Model AI · Web FE/BE · Phần cứng · Đánh giá · Mobile App"),
        ("Mã nguồn", "src/posture_monitor/ (9 subpackages) & apps/mobile/"),
        ("Bộ kiểm thử", "60 tệp Python + 13 tệp Mobile TypeScript/UI"),
        ("Phiên bản tài liệu", meta.get("version", "1.0")),
        ("Ngày hoàn thành", meta.get("date", "")),
    ]
    table = doc.add_table(rows=0, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for label, value in rows:
        cells = table.add_row().cells
        cells[0].width = Cm(5.2)
        cells[1].width = Cm(9.6)
        p0 = cells[0].paragraphs[0]
        r0 = p0.add_run(label)
        _set_font(r0, BODY_FONT, 10, bold=True, color=MUTED)
        p0.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p1 = cells[1].paragraphs[0]
        r1 = p1.add_run(value)
        _set_font(r1, BODY_FONT, 10, color=INK)

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(60)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(
        "Mọi con số hiệu năng trong báo cáo đều mang nhãn ĐÃ ĐO · TÍNH TỪ ĐO · CHƯA ĐO,\n"
        "và truy được về bài đo gốc trên chính thiết bị của dự án."
    )
    _set_font(run, BODY_FONT, 9, italic=True, color=MUTED)

    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


# ------------------------------------------------------------------ parsing
def split_row(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in body.split("|")]


def is_separator(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return False
    return bool(re.fullmatch(r"\|?[\s:|-]+\|?", stripped)) and "-" in stripped


def clean_heading(text: str) -> str:
    text = text.replace("**", "").replace("`", "")
    return text.strip()


def _set_table_fixed_layout(table) -> None:
    """Bật bố cục cố định + bề rộng tường minh — Word bỏ qua cell.width nếu thiếu."""
    tblPr = table._tbl.tblPr
    for existing in tblPr.findall(qn("w:tblLayout")):
        tblPr.remove(existing)
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblPr.append(layout)

    for existing in tblPr.findall(qn("w:tblW")):
        tblPr.remove(existing)
    width = OxmlElement("w:tblW")
    width.set(qn("w:type"), "dxa")
    width.set(qn("w:w"), str(int(Cm(16.5).twips)))
    tblPr.append(width)


def _column_weights(header: list[str], rows: list[list[str]], cols: int) -> list[float]:
    """Trọng số bề rộng cột theo độ dài nội dung, có sàn và trần.

    Hai chặn bắt buộc: một cột toàn số ("#") hay toàn nhãn ngắn ("ĐÃ ĐO")
    không được bóp còn vài milimét; một cột văn bản dài không được chiếm
    gần hết bề ngang. Không có hai chặn này, bảng 3–4 cột sẽ méo.
    """
    lengths: list[float] = []
    for i in range(cols):
        values = []
        if i < len(header):
            values.append(len(header[i]))
        for row in rows:
            if i < len(row):
                values.append(len(row[i]))
        if not values:
            lengths.append(1.0)
            continue
        avg = sum(values) / len(values)
        peak = max(values)
        # trung bình + một phần đỉnh, để cột có ô dài không bị bóp;
        # lấy căn bậc hai để giảm chênh lệch giữa cột ngắn và cột rất dài
        lengths.append(max(2.0, (0.6 * avg + 0.4 * peak)) ** 0.5)

    total = sum(lengths)
    shares = [v / total for v in lengths]

    floor, ceil = 0.115, 0.58
    shares = [min(ceil, max(floor, s)) for s in shares]

    # chuẩn hoá lại sau khi kẹp, giữ tổng = 1
    for _ in range(6):
        total = sum(shares)
        if abs(total - 1.0) < 1e-6:
            break
        shares = [s / total for s in shares]
        shares = [min(ceil, max(floor, s)) for s in shares]

    total = sum(shares)
    return [s / total for s in shares]


def add_table(doc: Document, header: list[str], rows: list[list[str]]) -> None:
    cols = max(len(header), max((len(r) for r in rows), default=0))
    table = doc.add_table(rows=1, cols=cols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    _set_table_fixed_layout(table)

    head = table.rows[0].cells
    for i in range(cols):
        cell = head[i]
        cell.text = ""
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        text = header[i] if i < len(header) else ""
        add_inline(p, text, size=9, base_bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
        _cell_shade(cell, "1F4E79")

    for r_index, row in enumerate(rows):
        cells = table.add_row().cells
        for i in range(cols):
            cell = cells[i]
            cell.text = ""
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            text = row[i] if i < len(row) else ""
            add_inline(p, text, size=9)
            if r_index % 2 == 1:
                _cell_shade(cell, "F4F6F9")

    # độ rộng cột: chia theo trọng số nội dung, không chia đều
    usable = Cm(21.0 - 2.5 - 2.0)
    weights = _column_weights(header, rows, cols)
    widths = [Emu(int(usable * w)) for w in weights]

    grid = table._tbl.find(qn("w:tblGrid"))
    if grid is not None:
        for col_el, width in zip(grid.findall(qn("w:gridCol")), widths):
            col_el.set(qn("w:w"), str(int(width.twips)))

    for row in table.rows:
        for i, cell in enumerate(row.cells):
            if i < len(widths):
                cell.width = widths[i]
            for p in cell.paragraphs:
                p.paragraph_format.line_spacing = 1.15

    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def add_code_block(doc: Document, lines: list[str]) -> None:
    """Khối mã: mỗi dòng một đoạn, nền xám, giữ đúng khoảng trắng.

    Dòng dài hơn ``MAX_CODE_CHARS`` được ngắt tại khoảng trắng gần nhất để
    không tràn lề phải (khổ A4 trừ lề chỉ chứa được ~86 ký tự Consolas 8,8 pt).
    """
    MAX_CODE_CHARS = 84

    parts: list[str] = []
    for line in lines:
        if len(line) <= MAX_CODE_CHARS or not line.strip():
            parts.append(line)
            continue
        indent = " " * (len(line) - len(line.lstrip()))
        rest = line
        while len(rest) > MAX_CODE_CHARS:
            window = rest[:MAX_CODE_CHARS]
            cut = max(window.rfind("  "), window.rfind("\t"), window.rfind(" "))
            if cut <= len(indent) + 8:          # không cắt vào giữa từ
                cut = MAX_CODE_CHARS
            parts.append(rest[:cut].rstrip())
            rest = indent + "    " + rest[cut:].lstrip()
        parts.append(rest)

    for line in parts:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.left_indent = Cm(0.4)
        p.paragraph_format.line_spacing = 1.0
        _para_shade(p, "F4F6F9")
        run = p.add_run(line if line.strip() else " ")
        _set_font(run, CODE_FONT, 8.8, color=CODE_INK)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def add_image(doc: Document, path: Path, caption: str) -> None:
    """Chèn hình, giữ nó vừa vùng in A4 (16 × 25,3 cm) và không tràn trang.

    Ảnh dọc (như ảnh chụp màn hình điện thoại 780×1688) rộng 16 cm sẽ cao
    34,6 cm — tràn trang và bị Word cắt. Vì vậy chiều rộng được chọn theo
    chiều cao khả dụng, không cố định.
    """
    if not path.is_file():
        p = doc.add_paragraph()
        add_inline(p, f"[thiếu hình: {path.name}]", size=9, color=MUTED)
        return

    MAX_W_CM = 16.0
    MAX_H_CM = 22.5          # chừa chỗ cho chú thích + khoảng thở

    try:
        with PILImage.open(path) as img:
            width_px, height_px = img.size
        aspect = width_px / height_px if height_px else 1.0
    except Exception:
        aspect = MAX_W_CM / MAX_H_CM

    width_cm = MAX_W_CM
    height_cm = width_cm / aspect
    if height_cm > MAX_H_CM:
        height_cm = MAX_H_CM
        width_cm = height_cm * aspect

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.keep_with_next = True
    p.add_run().add_picture(str(path), width=Cm(width_cm))

    if caption:
        cap = doc.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap.paragraph_format.space_after = Pt(12)
        add_inline(cap, caption, size=9, color=MUTED)


def add_quote(doc: Document, lines: list[str]) -> None:
    for line in lines:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.7)
        p.paragraph_format.space_after = Pt(3)
        _para_shade(p, "FBF6E6")
        add_inline(p, line, size=10, color=RGBColor(0x4A, 0x3B, 0x12))
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


# ------------------------------------------------------------------ main converter
def add_toc_field(doc: Document, levels: str = "1-3") -> None:
    """Chèn mục lục tự động của Word (cập nhật khi mở tệp hoặc nhấn F9)."""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    run = p.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    fld_begin.set(qn("w:dirty"), "true")

    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f' TOC \\o "{levels}" \\h \\z \\u '

    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")

    placeholder = OxmlElement("w:t")
    placeholder.text = "Nhấn F9 (hoặc chuột phải → Update Field) để dựng mục lục."

    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")

    for el in (fld_begin, instr, fld_sep, placeholder, fld_end):
        run._r.append(el)
    _set_font(run, BODY_FONT, 10, color=MUTED)

    note = doc.add_paragraph()
    note.paragraph_format.space_after = Pt(10)
    add_inline(
        note,
        "Mục lục trên là **trường tự động**: số trang chỉ hiện sau khi Word cập nhật "
        "(mở tệp, hoặc chọn toàn bộ rồi nhấn F9).",
        size=9,
        color=MUTED,
    )


def main_build() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    lines = text.splitlines()

    meta = {}
    for line in lines[:12]:
        m = re.match(r"\*\*Phiên bản tài liệu:\*\*\s*([0-9.]+)", line)
        if m:
            meta["version"] = m.group(1)
        m = re.match(r"\*\*Ngày:\*\*\s*(\S+)", line)
        if m:
            meta["date"] = m.group(1)
    meta.setdefault("date", "11/11/2026")

    doc = build_document()
    add_cover(doc, meta)

    # Bỏ phần "front matter" của Markdown (tiêu đề + dòng phiên bản + đường kẻ)
    # vì trang bìa đã trình bày đúng những thông tin đó.
    start = 0
    for idx, line in enumerate(lines):
        if re.match(r"^#{1,3}\s+.*mục lục", line.strip(), re.IGNORECASE):
            start = idx
            break

    i = start
    total = len(lines)
    while i < total:
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.strip()

        # --- khối mã
        if stripped.startswith("```"):
            i += 1
            block: list[str] = []
            while i < total and not lines[i].strip().startswith("```"):
                block.append(lines[i].rstrip("\n"))
                i += 1
            i += 1
            add_code_block(doc, block)
            continue

        # --- ảnh
        m = re.match(r"!\[(.*?)\]\((.*?)\)", stripped)
        if m:
            caption, rel = m.group(1), m.group(2)
            target = (HERE / rel).resolve()
            add_image(doc, target, caption)
            i += 1
            continue

        # --- tiêu đề
        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            title = clean_heading(m.group(2))
            if level == 1:
                # bỏ tiêu đề tài liệu ở đầu (đã có trang bìa)
                if "BÁO CÁO ĐỒ ÁN" in title.upper():
                    i += 1
                    continue
                doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            # Markdown dùng ## cho chương; Word cần Chương = Heading 1
            doc_level = min(4, max(1, level - 1)) if level >= 2 else 1
            heading = doc.add_heading(title, level=doc_level)
            if doc_level <= 2:
                _para_border_bottom(heading)
            i += 1
            # "Mục lục": thay danh sách tĩnh bằng mục lục tự động của Word
            if title.strip().lower() in {"mục lục", "muc luc"}:
                add_toc_field(doc)
                while i < total and not lines[i].strip().startswith("#"):
                    i += 1
            continue

        # --- đường kẻ
        if stripped in {"---", "***", "___"}:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(8)
            _para_border_bottom(p)
            i += 1
            continue

        # --- bảng
        if stripped.startswith("|") and i + 1 < total and is_separator(lines[i + 1]):
            header = split_row(stripped)
            i += 2
            rows: list[list[str]] = []
            while i < total and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            add_table(doc, header, rows)
            continue

        # --- trích dẫn
        if stripped.startswith(">"):
            block: list[str] = []
            while i < total and lines[i].strip().startswith(">"):
                block.append(lines[i].strip().lstrip(">").strip())
                i += 1
            add_quote(doc, [b for b in block if b])
            continue

        # --- danh sách
        m = re.match(r"^(\s*)([-*])\s+(.*)$", raw)
        if m:
            depth = len(m.group(1)) // 2
            parts = [m.group(3)]
            i += 1
            # gộp dòng tiếp nối (thụt lề, không phải mục mới)
            while i < total:
                nxt = lines[i]
                ns = nxt.strip()
                indented = nxt[:1].isspace()
                if (not ns or not indented
                        or ns.startswith(("#", "|", ">", "```", "![", "- ", "* "))
                        or re.match(r"^\d+\.\s", ns) or ns in {"---", "***", "___"}):
                    break
                parts.append(ns)
                i += 1
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.left_indent = Cm(0.75 + 0.55 * depth)
            p.paragraph_format.space_after = Pt(3)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            add_inline(p, " ".join(parts))
            continue

        m = re.match(r"^(\s*)(\d+)\.\s+(.*)$", raw)
        if m:
            depth = len(m.group(1)) // 2
            parts = [m.group(3)]
            i += 1
            while i < total:
                nxt = lines[i]
                ns = nxt.strip()
                indented = nxt[:1].isspace()
                if (not ns or not indented
                        or ns.startswith(("#", "|", ">", "```", "![", "- ", "* "))
                        or re.match(r"^\d+\.\s", ns) or ns in {"---", "***", "___"}):
                    break
                parts.append(ns)
                i += 1
            p = doc.add_paragraph(style="List Number")
            p.paragraph_format.left_indent = Cm(0.75 + 0.55 * depth)
            p.paragraph_format.space_after = Pt(3)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            add_inline(p, " ".join(parts))
            continue

        # --- dòng trống
        if not stripped:
            i += 1
            continue

        # --- đoạn văn (gộp các dòng liên tiếp)
        paragraph_lines = [stripped]
        i += 1
        while i < total:
            nxt = lines[i]
            ns = nxt.strip()
            if (not ns or ns.startswith(("#", "|", ">", "```", "![", "- ", "* "))
                    or re.match(r"^\d+\.\s", ns) or ns in {"---", "***", "___"}):
                break
            paragraph_lines.append(ns)
            i += 1

        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        add_inline(p, " ".join(paragraph_lines))

    doc.save(TARGET)
    print("Đã ghi", TARGET)
    print("Số đoạn văn:", len(doc.paragraphs), "· số bảng:", len(doc.tables))
    return 0


if __name__ == "__main__":
    sys.exit(main_build())
