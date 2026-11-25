# -*- coding: utf-8 -*-
"""Chuyển BAO_CAO_DO_AN.md sang .docx theo đúng định dạng chuẩn Khoa CNTT - ĐHBK Đà Nẵng (DUT).

Quy cách chuẩn áp dụng (theo skill dut-capstone-report):
- Khổ giấy A4 (21,0 x 29,7 cm); lề trái 3,5 cm, phải 2,0 cm, trên 2,5 cm, dưới 2,5 cm.
- Vùng in khả dụng ngang: 15,5 cm. Trang bìa không hiển thị Header/Footer.
- Phông chữ chính: Times New Roman, màu đen thuần (#000000), cỡ 13 pt, giãn dòng 1,5,
  thụt đầu dòng 1,0 cm, căn đều hai bên (Justify).
- Chương (Heading 1): 16 pt Bold IN HOA, ngắt trang mới; Mục N.M. (Heading 2): 14 pt Bold;
  Mục N.M.K. (Heading 3): 13 pt Bold.
- Ba danh mục tự động đầu báo cáo bằng trường Word: MỤC LỤC, HÌNH ẢNH, BẢNG BIỂU.
- Bảng biểu: Tên bảng 13 pt Bold Italic đặt TRÊN bảng (kèm SEQ Bảng), khung đen Table Grid
  nền trắng rộng 15,5 cm, dòng tiêu đề lặp lại khi qua trang (w:tblHeader).
- Hình ảnh: Căn giữa (rộng <= 15,0 cm, cao <= 19,0 cm), tên hình 13 pt Bold Italic đặt DƯỚI hình
  (kèm SEQ Hình).

Chạy:  python BaoCao/make_docx.py
Đầu ra: BaoCao/BaoCao_DoAn_GiamSatHocTap.docx
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Emu, Pt, RGBColor
from PIL import Image as PILImage

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "BAO_CAO_DO_AN.md"
TARGET = HERE / "BaoCao_DoAn_GiamSatHocTap.docx"
LOGO_DUT = HERE / "figures" / "logo-dut.png"
LOGO_CNTT = HERE / "figures" / "logo-cntt.jpg"

BODY_FONT = "Times New Roman"
CODE_FONT = "Courier New"
BLACK = RGBColor(0x00, 0x00, 0x00)

USABLE_W_CM = 15.5
MAX_FIG_W_CM = 15.5
MAX_FIG_H_CM = 19.2

# ------------------------------------------------------------------ Schema OOXML element order
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
    """Chèn phần tử XML vào đúng thứ tự chuẩn ECMA-376 để Word không báo lỗi Repair."""
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


def _set_style_fonts(style, font_name: str) -> None:
    style.font.name = font_name
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        _insert_ordered(rpr, rfonts, _RPR_ORDER)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), font_name)


def _set_font(
    run,
    name: str = BODY_FONT,
    size: float | None = 13.0,
    *,
    bold: bool | None = None,
    italic: bool | None = None,
    color: RGBColor = BLACK,
) -> None:
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        _insert_ordered(rpr, rfonts, _RPR_ORDER)
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


def _para_shade(paragraph, fill: str) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    for existing in pPr.findall(qn("w:shd")):
        pPr.remove(existing)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    _insert_ordered(pPr, shd, _PPR_ORDER)


def _para_box_border(paragraph, color: str = "D0D0D0", size: int = 4) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    for existing in pPr.findall(qn("w:pBdr")):
        pPr.remove(existing)
    borders = OxmlElement("w:pBdr")
    for side in ("top", "left", "bottom", "right"):
        b = OxmlElement(f"w:{side}")
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), str(size))
        b.set(qn("w:space"), "4")
        b.set(qn("w:color"), color)
        borders.append(b)
    _insert_ordered(pPr, borders, _PPR_ORDER)


def _set_cell_margins(cell, top: int = 80, bottom: int = 80, left: int = 110, right: int = 110) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    for existing in tcPr.findall(qn("w:tcMar")):
        tcPr.remove(existing)
    tcMar = OxmlElement("w:tcMar")
    for side, val in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        tcMar.append(node)
    _insert_ordered(tcPr, tcMar, _TCPR_ORDER)


def _clear_table_borders(table) -> None:
    """Xóa toàn bộ khung viền của bảng (dùng cho cụm 2 logo đầu trang bìa)."""
    tblPr = table._tbl.tblPr
    for existing in tblPr.findall(qn("w:tblBorders")):
        tblPr.remove(existing)
    borders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "none")
        el.set(qn("w:sz"), "0")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "auto")
        borders.append(el)
    tblPr.append(borders)


def _enable_update_fields_on_open(doc: Document) -> None:
    """Đặt w:updateFields trong settings.xml để Word cập nhật Mục lục/Hình/Bảng khi mở."""
    settings = doc.settings.element
    if settings.find(qn("w:updateFields")) is None:
        upd = OxmlElement("w:updateFields")
        upd.set(qn("w:val"), "true")
        settings.append(upd)


def _add_simple_field(paragraph, instruction: str, cached_text: str = "", *,
                      size: float = 13.0, bold: bool = False, italic: bool = False) -> None:
    """Chèn trường động Word (PAGE, SEQ Hình, SEQ Bảng, TOC) đúng cấu trúc begin-separate-end."""
    run_begin = paragraph.add_run()
    _set_font(run_begin, BODY_FONT, size, bold=bold, italic=italic)
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    fld_begin.set(qn("w:dirty"), "true")
    run_begin._r.append(fld_begin)

    run_instr = paragraph.add_run()
    _set_font(run_instr, BODY_FONT, size, bold=bold, italic=italic)
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    run_instr._r.append(instr)

    run_sep = paragraph.add_run()
    _set_font(run_sep, BODY_FONT, size, bold=bold, italic=italic)
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    run_sep._r.append(fld_sep)

    if cached_text:
        run_val = paragraph.add_run(cached_text)
        _set_font(run_val, BODY_FONT, size, bold=bold, italic=italic)

    run_end = paragraph.add_run()
    _set_font(run_end, BODY_FONT, size, bold=bold, italic=italic)
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run_end._r.append(fld_end)


# ------------------------------------------------------------------ Math & Inline Markdown
def _latex_to_unicode(expr: str) -> str:
    """Chuyển biểu thức toán LaTeX gọn sang ký hiệu toán học Unicode sạch trong Word."""
    s = expr.strip()
    s = re.sub(r"\\text\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\mathbf\{([^}]*)\}", r"\1", s)
    s = s.replace(r"\,", " ").replace(r"\_", "_")
    s = s.replace(r"\|", "‖")
    s = s.replace(r"\le", "≤").replace(r"\ge", "≥")
    s = s.replace(r"\in", "∈").replace(r"\times", "×").replace(r"\cdot", "·")
    s = s.replace(r"\min_", "min_")
    s = re.sub(r"_\{([^}]*)\}", r"[\1]", s)
    s = s.replace("_2", "₂").replace("_k", "ₖ")
    return re.sub(r"\s+", " ", s).strip()


INLINE_RE = re.compile(
    r"(\*\*\*[^*\n]+?\*\*\*|\*\*.+?\*\*|`[^`]+`|\$[^$\n]+?\$|(?<![\w*])\*[^*\n]+?\*(?![\w*])|\[[^\]\n]+\]\([^)\n]+\))"
)


def add_inline(
    paragraph,
    text: str,
    *,
    size: float = 13.0,
    base_bold: bool = False,
    base_italic: bool = False,
    depth: int = 0,
) -> None:
    """Phân tích định dạng nội tuyến (**đậm**, *nghiêng*, `mã`, $toán$, [nhãn](url)) sang run Word."""
    if depth > 4:
        run = paragraph.add_run(text)
        _set_font(run, BODY_FONT, size, bold=base_bold, italic=base_italic)
        return

    for piece in INLINE_RE.split(text):
        if not piece:
            continue
        if piece.startswith("***") and piece.endswith("***") and len(piece) > 6:
            add_inline(paragraph, piece[3:-3], size=size, base_bold=True,
                       base_italic=True, depth=depth + 1)
        elif piece.startswith("**") and piece.endswith("**") and len(piece) > 4:
            add_inline(paragraph, piece[2:-2], size=size, base_bold=True,
                       base_italic=base_italic, depth=depth + 1)
        elif piece.startswith("`") and piece.endswith("`") and len(piece) > 2:
            code_txt = piece[1:-1]
            # Trong chú thích đậm nghiêng (Bảng/Hình), giữ Times New Roman để đồng bộ mục lục Hình/Bảng
            if base_bold and base_italic:
                run = paragraph.add_run(code_txt)
                _set_font(run, BODY_FONT, size, bold=True, italic=True)
            else:
                code_sz = max(10.0, size - 1.5)
                run = paragraph.add_run(code_txt)
                _set_font(run, CODE_FONT, code_sz, bold=base_bold, italic=base_italic)
        elif piece.startswith("$") and piece.endswith("$") and len(piece) > 2:
            math_txt = _latex_to_unicode(piece[1:-1])
            run = paragraph.add_run(math_txt)
            _set_font(run, BODY_FONT, size, bold=base_bold, italic=True)
        elif piece.startswith("[") and "](" in piece and piece.endswith(")"):
            label = piece[1:piece.index("](")]
            run = paragraph.add_run(label)
            _set_font(run, BODY_FONT, size, bold=base_bold, italic=base_italic)
        elif piece.startswith("*") and piece.endswith("*") and len(piece) > 2:
            add_inline(paragraph, piece[1:-1], size=size, base_bold=base_bold,
                       base_italic=True, depth=depth + 1)
        else:
            run = paragraph.add_run(piece)
            _set_font(run, BODY_FONT, size, bold=base_bold, italic=base_italic)


# ------------------------------------------------------------------ Document Setup & Cover
def build_document(meta: dict[str, Any]) -> Document:
    doc = Document()
    _enable_update_fields_on_open(doc)

    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.left_margin = Cm(3.5)
    section.right_margin = Cm(2.0)
    section.top_margin = Cm(2.5)
    section.bottom_margin = Cm(2.5)
    section.header_distance = Cm(1.5)
    section.footer_distance = Cm(1.65)
    section.different_first_page_header_footer = True

    # Normal style: Times New Roman 13 pt, Justify, first-line indent 1.0 cm, 1.5 lines
    normal = doc.styles["Normal"]
    _set_style_fonts(normal, BODY_FONT)
    normal.font.size = Pt(13)
    normal.font.color.rgb = BLACK
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    normal.paragraph_format.first_line_indent = Cm(1.0)
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)

    # Heading 1..3 chuẩn DUT
    heading_specs = (
        ("Heading 1", 16.0, 12, 12, True),
        ("Heading 2", 14.0, 10, 6, False),
        ("Heading 3", 13.0, 8, 4, False),
        ("Heading 4", 13.0, 6, 3, False),
    )
    for style_name, pt_size, before_pt, after_pt, break_before in heading_specs:
        st = doc.styles[style_name]
        _set_style_fonts(st, BODY_FONT)
        st.font.size = Pt(pt_size)
        st.font.bold = True
        st.font.italic = False
        st.font.color.rgb = BLACK
        st.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        st.paragraph_format.first_line_indent = Cm(1.0)
        st.paragraph_format.line_spacing = 1.35
        st.paragraph_format.space_before = Pt(before_pt)
        st.paragraph_format.space_after = Pt(after_pt)
        st.paragraph_format.keep_with_next = True
        st.paragraph_format.page_break_before = break_before

    # Caption style cho Bảng & Hình: 13 pt Bold Italic căn giữa
    if "Caption" in doc.styles:
        cap_style = doc.styles["Caption"]
        _set_style_fonts(cap_style, BODY_FONT)
        cap_style.font.size = Pt(13)
        cap_style.font.bold = True
        cap_style.font.italic = True
        cap_style.font.color.rgb = BLACK
        cap_style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap_style.paragraph_format.first_line_indent = Cm(0)
        cap_style.paragraph_format.line_spacing = 1.3

    # Running Header (trang 2 trở đi)
    header_p = section.header.paragraphs[0]
    header_p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    header_p.paragraph_format.first_line_indent = Cm(0)
    header_p.paragraph_format.space_after = Pt(0)
    h_run = header_p.add_run(meta.get("header_text", "Báo cáo Đồ án IoT"))
    _set_font(h_run, BODY_FONT, 10.0, italic=True)

    # Running Footer (trang 2 trở đi): Tên sinh viên bên trái, số trang căn phải ở 15.5 cm
    footer_p = section.footer.paragraphs[0]
    footer_p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    footer_p.paragraph_format.first_line_indent = Cm(0)
    footer_p.paragraph_format.space_after = Pt(0)
    footer_p.paragraph_format.tab_stops.add_tab_stop(Cm(USABLE_W_CM), WD_TAB_ALIGNMENT.RIGHT)
    f_left = footer_p.add_run(meta.get("footer_students", "") + "\t")
    _set_font(f_left, BODY_FONT, 10.0, italic=True)
    _add_simple_field(footer_p, "PAGE", size=10.0, italic=True)

    return doc


def _set_table_fixed_width(table, total_cm: float, col_widths_cm: list[float]) -> None:
    tblPr = table._tbl.tblPr
    for existing in tblPr.findall(qn("w:tblLayout")):
        tblPr.remove(existing)
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblPr.append(layout)

    for existing in tblPr.findall(qn("w:tblW")):
        tblPr.remove(existing)
    tblW = OxmlElement("w:tblW")
    tblW.set(qn("w:type"), "dxa")
    tblW.set(qn("w:w"), str(int(Cm(total_cm).twips)))
    tblPr.append(tblW)

    widths = [Cm(w) for w in col_widths_cm]
    grid = table._tbl.find(qn("w:tblGrid"))
    if grid is not None:
        for col_el, w_obj in zip(grid.findall(qn("w:gridCol")), widths):
            col_el.set(qn("w:w"), str(int(w_obj.twips)))

    for row in table.rows:
        for idx, cell in enumerate(row.cells):
            if idx < len(widths):
                cell.width = widths[idx]


def add_cover_page(doc: Document, meta: dict[str, Any]) -> None:
    """Dựng trang bìa chuẩn Khoa CNTT - Trường Đại học Bách Khoa, ĐHĐN."""
    top_tbl = doc.add_table(rows=1, cols=3)
    top_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    top_tbl.autofit = False
    _clear_table_borders(top_tbl)
    _set_table_fixed_width(top_tbl, USABLE_W_CM, [2.5, 10.5, 2.5])

    c_left, c_mid, c_right = top_tbl.rows[0].cells
    for c in (c_left, c_mid, c_right):
        c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

    p_left = c_left.paragraphs[0]
    p_left.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_left.paragraph_format.first_line_indent = Cm(0)
    p_left.paragraph_format.space_after = Pt(0)
    if LOGO_DUT.is_file():
        p_left.add_run().add_picture(str(LOGO_DUT), width=Cm(2.3))

    p_mid1 = c_mid.paragraphs[0]
    p_mid1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_mid1.paragraph_format.first_line_indent = Cm(0)
    p_mid1.paragraph_format.line_spacing = 1.25
    p_mid1.paragraph_format.space_after = Pt(2)
    r_uni = p_mid1.add_run(meta.get("university", "TRƯỜNG ĐẠI HỌC BÁCH KHOA"))
    _set_font(r_uni, BODY_FONT, 15.0, bold=True)

    p_mid2 = c_mid.add_paragraph()
    p_mid2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_mid2.paragraph_format.first_line_indent = Cm(0)
    p_mid2.paragraph_format.line_spacing = 1.25
    p_mid2.paragraph_format.space_after = Pt(0)
    r_fac = p_mid2.add_run(meta.get("faculty", "KHOA CÔNG NGHỆ THÔNG TIN"))
    _set_font(r_fac, BODY_FONT, 15.0, bold=True)

    p_right = c_right.paragraphs[0]
    p_right.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_right.paragraph_format.first_line_indent = Cm(0)
    p_right.paragraph_format.space_after = Pt(0)
    if LOGO_CNTT.is_file():
        p_right.add_run().add_picture(str(LOGO_CNTT), width=Cm(2.3))

    # Khối BÁO CÁO & Học phần
    p_type = doc.add_paragraph()
    p_type.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_type.paragraph_format.first_line_indent = Cm(0)
    p_type.paragraph_format.space_before = Pt(42)
    p_type.paragraph_format.space_after = Pt(6)
    _set_font(p_type.add_run(meta.get("report_type", "BÁO CÁO")), BODY_FONT, 20.0, bold=True)

    p_course = doc.add_paragraph()
    p_course.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_course.paragraph_format.first_line_indent = Cm(0)
    p_course.paragraph_format.space_after = Pt(28)
    _set_font(p_course.add_run(meta.get("course_title", "")), BODY_FONT, 17.0, bold=True)

    # Khối Tên đề tài
    p_lbl = doc.add_paragraph()
    p_lbl.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_lbl.paragraph_format.first_line_indent = Cm(0)
    p_lbl.paragraph_format.space_after = Pt(6)
    _set_font(p_lbl.add_run("Tên Đề Tài:"), BODY_FONT, 14.0, bold=True)

    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_title.paragraph_format.first_line_indent = Cm(0)
    p_title.paragraph_format.line_spacing = 1.35
    p_title.paragraph_format.space_after = Pt(28)
    _set_font(p_title.add_run(meta.get("project_title", "")), BODY_FONT, 16.0, bold=True)

    # Giảng viên hướng dẫn
    p_adv = doc.add_paragraph()
    p_adv.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_adv.paragraph_format.first_line_indent = Cm(0)
    p_adv.paragraph_format.space_after = Pt(22)
    _set_font(
        p_adv.add_run(f"Giảng viên hướng dẫn:    {meta.get('advisor', '')}"),
        BODY_FONT,
        14.0,
        bold=True,
    )

    # Bảng Sinh viên thực hiện (3 cột chuẩn DUT)
    students = meta.get("students") or []
    st_tbl = doc.add_table(rows=1 + len(students), cols=3)
    st_tbl.style = "Table Grid"
    st_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    st_tbl.autofit = False
    _set_table_fixed_width(st_tbl, 14.8, [6.2, 4.3, 4.3])

    headers = ("HỌ VÀ TÊN", "Lớp Học Phần", "Mã Sinh Viên")
    for idx, h_text in enumerate(headers):
        cell = st_tbl.rows[0].cells[idx]
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        _set_cell_margins(cell, top=120, bottom=120, left=100, right=100)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.space_after = Pt(0)
        _set_font(p.add_run(h_text), BODY_FONT, 13.0, bold=True)

    for r_idx, st_info in enumerate(students, start=1):
        vals = (
            str(st_info.get("name", "")),
            str(st_info.get("class_code", "")),
            str(st_info.get("student_id", "")),
        )
        for c_idx, val in enumerate(vals):
            cell = st_tbl.rows[r_idx].cells[c_idx]
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            _set_cell_margins(cell, top=120, bottom=120, left=100, right=100)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.first_line_indent = Cm(0)
            p.paragraph_format.space_after = Pt(0)
            _set_font(p.add_run(val), BODY_FONT, 13.0)

    # Địa điểm & thời gian cuối trang bìa
    spacer_pt = max(36, 130 - 22 * len(students))
    p_loc = doc.add_paragraph()
    p_loc.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_loc.paragraph_format.first_line_indent = Cm(0)
    p_loc.paragraph_format.space_before = Pt(spacer_pt)
    p_loc.paragraph_format.space_after = Pt(0)
    _set_font(p_loc.add_run(meta.get("location_date", "ĐÀ NẴNG, 11/2026")), BODY_FONT, 13.0)


def add_front_matter_lists(doc: Document) -> None:
    """Tạo 3 trang danh mục tự động chuẩn DUT: MỤC LỤC, HÌNH ẢNH, BẢNG BIỂU."""
    specs = (
        ("MỤC LỤC", 'TOC \\o "1-2" \\h \\z \\u',
         "Nhấn Ctrl+A rồi nhấn F9 (hoặc chọn Update Field khi mở Word) để cập nhật số trang Mục lục."),
        ("HÌNH ẢNH", 'TOC \\h \\z \\c "Hình"',
         "Danh mục Hình ảnh tự động (nhấn F9 để cập nhật số trang)."),
        ("BẢNG BIỂU", 'TOC \\h \\z \\c "Bảng"',
         "Danh mục Bảng biểu tự động (nhấn F9 để cập nhật số trang)."),
    )
    for title, toc_instr, hint in specs:
        p_head = doc.add_paragraph()
        p_head.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_head.paragraph_format.first_line_indent = Cm(0)
        p_head.paragraph_format.page_break_before = True
        p_head.paragraph_format.space_before = Pt(6)
        p_head.paragraph_format.space_after = Pt(14)
        p_head.paragraph_format.keep_with_next = True
        _set_font(p_head.add_run(title), BODY_FONT, 16.0, bold=True)

        p_toc = doc.add_paragraph()
        p_toc.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p_toc.paragraph_format.first_line_indent = Cm(0)
        p_toc.paragraph_format.line_spacing = 1.35
        p_toc.paragraph_format.space_after = Pt(6)
        _add_simple_field(p_toc, toc_instr, cached_text=hint, size=13.0, italic=True)


# ------------------------------------------------------------------ Captions, Tables, Figures, Code
def add_seq_caption(
    doc: Document,
    label: str,
    seq_num: int,
    title_text: str,
    *,
    keep_with_next: bool,
    space_before_pt: float,
    space_after_pt: float,
) -> None:
    """Tạo dòng chú thích 'Bảng N. ...' hoặc 'Hình N. ...' có trường SEQ để lên danh mục tự động."""
    style_name = "Caption" if "Caption" in doc.styles else "Normal"
    p = doc.add_paragraph(style=style_name)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.line_spacing = 1.3
    p.paragraph_format.space_before = Pt(space_before_pt)
    p.paragraph_format.space_after = Pt(space_after_pt)
    p.paragraph_format.keep_with_next = keep_with_next

    r_lbl = p.add_run(f"{label} ")
    _set_font(r_lbl, BODY_FONT, 13.0, bold=True, italic=True)
    _add_simple_field(
        p,
        f"SEQ {label} \\* ARABIC",
        cached_text=str(seq_num),
        size=13.0,
        bold=True,
        italic=True,
    )
    r_dot = p.add_run(". ")
    _set_font(r_dot, BODY_FONT, 13.0, bold=True, italic=True)
    add_inline(p, title_text, size=13.0, base_bold=True, base_italic=True)


def split_row(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith(r"\|"):
        body = body[:-1]
    parts = re.split(r"(?<!\\)\|", body)
    return [cell.replace(r"\|", "|").strip() for cell in parts]


def is_separator(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return False
    return bool(re.fullmatch(r"\|?[\s:|-]+\|?", stripped)) and "-" in stripped


def _column_weights(header: list[str], rows: list[list[str]], cols: int) -> list[float]:
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
        lengths.append(max(2.0, (0.6 * avg + 0.4 * peak)) ** 0.5)

    total = sum(lengths)
    shares = [v / total for v in lengths]
    floor = 0.085 if cols >= 5 else 0.11
    ceil = 0.54
    shares = [min(ceil, max(floor, s)) for s in shares]

    for _ in range(6):
        total = sum(shares)
        if abs(total - 1.0) < 1e-6:
            break
        shares = [s / total for s in shares]
        shares = [min(ceil, max(floor, s)) for s in shares]

    total = sum(shares)
    return [s / total for s in shares]


def _mark_row_header_and_cant_split(row, *, is_header: bool) -> None:
    trPr = row._tr.get_or_add_trPr()
    if trPr.find(qn("w:cantSplit")) is None:
        trPr.append(OxmlElement("w:cantSplit"))
    if is_header and trPr.find(qn("w:tblHeader")) is None:
        trPr.append(OxmlElement("w:tblHeader"))


def add_table(doc: Document, header: list[str], rows: list[list[str]]) -> None:
    """Dựng bảng chuẩn học thuật DUT: viền đen Table Grid, nền trắng, rộng 15,5 cm."""
    cols = max(len(header), max((len(r) for r in rows), default=0))
    table = doc.add_table(rows=1, cols=cols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    cell_font_pt = 11.5 if cols >= 5 else 12.0

    # Hàng tiêu đề
    _mark_row_header_and_cant_split(table.rows[0], is_header=True)
    head_cells = table.rows[0].cells
    for i in range(cols):
        cell = head_cells[i]
        cell.text = ""
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        _set_cell_margins(cell, top=85, bottom=85, left=95, right=95)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.line_spacing = 1.15
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        text = header[i] if i < len(header) else ""
        add_inline(p, text, size=cell_font_pt, base_bold=True)

    # Các hàng dữ liệu
    short_col0 = all(len((r[0] if r else "").strip()) <= 8 for r in rows) if rows else False
    for row in rows:
        tr = table.add_row()
        _mark_row_header_and_cant_split(tr, is_header=False)
        cells = tr.cells
        for i in range(cols):
            cell = cells[i]
            cell.text = ""
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            _set_cell_margins(cell, top=75, bottom=75, left=95, right=95)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if (i == 0 and short_col0) else WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.first_line_indent = Cm(0)
            p.paragraph_format.line_spacing = 1.18
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            text = row[i] if i < len(row) else ""
            add_inline(p, text, size=cell_font_pt)

    weights = _column_weights(header, rows, cols)
    widths_cm = [USABLE_W_CM * w for w in weights]
    _set_table_fixed_width(table, USABLE_W_CM, widths_cm)

    spacer = doc.add_paragraph()
    spacer.paragraph_format.first_line_indent = Cm(0)
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(4)


def add_code_block(doc: Document, lines: list[str]) -> None:
    """Khối mã nguồn / cấu hình: Courier New 9,5 pt, vừa khít chiều ngang 15,5 cm."""
    MAX_CODE_CHARS = 78
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
            if cut <= len(indent) + 8:
                cut = MAX_CODE_CHARS
            parts.append(rest[:cut].rstrip())
            rest = indent + "    " + rest[cut:].lstrip()
        parts.append(rest)

    for line in parts:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.left_indent = Cm(0.35)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.08
        _para_shade(p, "F5F5F5")
        run = p.add_run(line if line.strip() else " ")
        _set_font(run, CODE_FONT, 9.5)

    spacer = doc.add_paragraph()
    spacer.paragraph_format.first_line_indent = Cm(0)
    spacer.paragraph_format.space_after = Pt(4)


def add_image(doc: Document, path: Path, fig_num: int, caption_title: str) -> None:
    """Chèn hình căn giữa trong khung A4 (<= 15,0 x 19,0 cm) kèm chú thích SEQ Hình bên dưới."""
    if not path.is_file():
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        add_inline(p, f"[Thiếu tệp hình: {path.name}]", size=12.0, base_italic=True)
        return

    try:
        with PILImage.open(path) as img:
            width_px, height_px = img.size
        aspect = width_px / height_px if height_px else 1.0
    except Exception:
        aspect = MAX_FIG_W_CM / MAX_FIG_H_CM

    width_cm = MAX_FIG_W_CM
    height_cm = width_cm / aspect
    if height_cm > MAX_FIG_H_CM:
        height_cm = MAX_FIG_H_CM
        width_cm = height_cm * aspect

    p_img = doc.add_paragraph()
    p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_img.paragraph_format.first_line_indent = Cm(0)
    p_img.paragraph_format.space_before = Pt(8)
    p_img.paragraph_format.space_after = Pt(3)
    p_img.paragraph_format.keep_with_next = True
    _para_box_border(p_img, color="BFBFBF", size=4)
    p_img.add_run().add_picture(str(path), width=Cm(width_cm))

    add_seq_caption(
        doc,
        "Hình",
        fig_num,
        caption_title,
        keep_with_next=False,
        space_before_pt=2,
        space_after_pt=10,
    )


def parse_frontmatter(lines: list[str]) -> tuple[dict[str, Any], int]:
    """Tách khối YAML frontmatter ở đầu tệp Markdown và trả về (metadata, chỉ_số_dòng_tiếp)."""
    if not lines or lines[0].strip() != "---":
        return {}, 0
    end_idx = -1
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx == -1:
        return {}, 0
    raw_yaml = "\n".join(lines[1:end_idx])
    meta = yaml.safe_load(raw_yaml) or {}
    return meta, end_idx + 1


def clean_heading(text: str) -> str:
    return text.replace("**", "").replace("`", "").strip()


# ------------------------------------------------------------------ Main Builder
TABLE_CAP_RE = re.compile(r"^\*Bảng\s+(\d+)\.\s*(.+)\*$")
FIG_CAP_RE = re.compile(r"^\*Hình\s+(\d+)\.\s*(.+)\*$")
REF_ITEM_RE = re.compile(r"^\[(\d+)\]\s+(.*)$")


def main_build() -> int:
    text = SOURCE.read_text(encoding="utf-8")
    lines = text.splitlines()
    meta, start_idx = parse_frontmatter(lines)

    doc = build_document(meta)
    add_cover_page(doc, meta)
    add_front_matter_lists(doc)

    table_counter = 0
    fig_counter = 0

    i = start_idx
    total = len(lines)
    while i < total:
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # --- Khối công thức toán $$ ... $$
        if stripped.startswith("$$"):
            math_lines: list[str] = []
            if stripped != "$$" and stripped.endswith("$$") and len(stripped) > 4:
                math_lines.append(stripped[2:-2])
                i += 1
            else:
                i += 1
                while i < total and not lines[i].strip().startswith("$$"):
                    math_lines.append(lines[i].strip())
                    i += 1
                i += 1
            formula = _latex_to_unicode(" ".join(math_lines))
            p_math = doc.add_paragraph()
            p_math.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_math.paragraph_format.first_line_indent = Cm(0)
            p_math.paragraph_format.space_before = Pt(6)
            p_math.paragraph_format.space_after = Pt(8)
            _set_font(p_math.add_run(formula), BODY_FONT, 13.0, italic=True)
            continue

        # --- Khối mã ```
        if stripped.startswith("```"):
            i += 1
            block: list[str] = []
            while i < total and not lines[i].strip().startswith("```"):
                block.append(lines[i].rstrip("\n"))
                i += 1
            i += 1
            add_code_block(doc, block)
            continue

        # --- Dòng chú thích Bảng đặt phía trên bảng: *Bảng N. Tên bảng*
        m_tcap = TABLE_CAP_RE.match(stripped)
        if m_tcap:
            table_counter += 1
            cap_title = m_tcap.group(2).strip()
            add_seq_caption(
                doc,
                "Bảng",
                table_counter,
                cap_title,
                keep_with_next=True,
                space_before_pt=8,
                space_after_pt=4,
            )
            i += 1
            continue

        # --- Hình ảnh ![alt](rel_path) + dòng chú thích *Hình N. Tên hình* kế tiếp
        m_img = re.match(r"^!\[(.*?)\]\((.*?)\)$", stripped)
        if m_img:
            fig_counter += 1
            alt_text, rel = m_img.group(1).strip(), m_img.group(2).strip()
            target = (HERE / rel).resolve()
            i += 1
            # Kiểm tra dòng không trống kế tiếp có phải *Hình N. ...* không
            j = i
            while j < total and not lines[j].strip():
                j += 1
            cap_title = alt_text
            if j < total:
                m_fcap = FIG_CAP_RE.match(lines[j].strip())
                if m_fcap:
                    cap_title = m_fcap.group(2).strip()
                    i = j + 1
            add_image(doc, target, fig_counter, cap_title)
            continue

        # --- Tiêu đề ## CHƯƠNG N / ### N.M / #### N.M.K
        m_head = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m_head:
            hashes = len(m_head.group(1))
            title = clean_heading(m_head.group(2))
            doc_level = min(4, max(1, hashes - 1)) if hashes >= 2 else 1
            if doc_level == 1:
                title = title.upper()
            h_para = doc.add_heading("", level=doc_level)
            h_size = {1: 16.0, 2: 14.0, 3: 13.0, 4: 13.0}[doc_level]
            h_run = h_para.add_run(title)
            _set_font(h_run, BODY_FONT, h_size, bold=True)
            i += 1
            continue

        # --- Đường kẻ ngang (bỏ qua vì văn bản học thuật DUT không kẻ vạch ngăn mục)
        if stripped in {"---", "***", "___"}:
            i += 1
            continue

        # --- Bảng Markdown
        if stripped.startswith("|") and i + 1 < total and is_separator(lines[i + 1]):
            header = split_row(stripped)
            i += 2
            rows: list[list[str]] = []
            while i < total and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            add_table(doc, header, rows)
            continue

        # --- Trích dẫn >
        if stripped.startswith(">"):
            q_lines: list[str] = []
            while i < total and lines[i].strip().startswith(">"):
                q_lines.append(lines[i].strip().lstrip(">").strip())
                i += 1
            p_q = doc.add_paragraph()
            p_q.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p_q.paragraph_format.left_indent = Cm(1.0)
            p_q.paragraph_format.first_line_indent = Cm(0)
            add_inline(p_q, " ".join(q_lines), size=13.0, base_italic=True)
            continue

        # --- Danh sách gạch đầu dòng
        m_bul = re.match(r"^(\s*)([-*])\s+(.*)$", raw)
        if m_bul:
            depth = len(m_bul.group(1)) // 2
            parts = [m_bul.group(3)]
            i += 1
            while i < total:
                nxt = lines[i]
                ns = nxt.strip()
                indented = nxt[:1].isspace()
                if (
                    not ns
                    or not indented
                    or ns.startswith(("#", "|", ">", "```", "![", "- ", "* ", "$$"))
                    or re.match(r"^\d+\.\s", ns)
                    or ns in {"---", "***", "___"}
                ):
                    break
                parts.append(ns)
                i += 1
            p_b = doc.add_paragraph(style="List Bullet")
            p_b.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p_b.paragraph_format.left_indent = Cm(1.25 + 0.5 * depth)
            p_b.paragraph_format.first_line_indent = Cm(-0.45)
            p_b.paragraph_format.line_spacing = 1.4
            p_b.paragraph_format.space_after = Pt(4)
            add_inline(p_b, " ".join(parts), size=13.0)
            continue

        # --- Danh sách đánh số 1. 2. 3.
        m_num = re.match(r"^(\s*)(\d+)\.\s+(.*)$", raw)
        if m_num:
            depth = len(m_num.group(1)) // 2
            num_str = m_num.group(2)
            parts = [m_num.group(3)]
            i += 1
            while i < total:
                nxt = lines[i]
                ns = nxt.strip()
                indented = nxt[:1].isspace()
                if (
                    not ns
                    or not indented
                    or ns.startswith(("#", "|", ">", "```", "![", "- ", "* ", "$$"))
                    or re.match(r"^\d+\.\s", ns)
                    or ns in {"---", "***", "___"}
                ):
                    break
                parts.append(ns)
                i += 1
            p_n = doc.add_paragraph()
            p_n.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p_n.paragraph_format.left_indent = Cm(1.25 + 0.5 * depth)
            p_n.paragraph_format.first_line_indent = Cm(-0.55)
            p_n.paragraph_format.line_spacing = 1.4
            p_n.paragraph_format.space_after = Pt(4)
            r_prefix = p_n.add_run(f"{num_str}. ")
            _set_font(r_prefix, BODY_FONT, 13.0, bold=True)
            add_inline(p_n, " ".join(parts), size=13.0)
            continue

        # --- Mục tài liệu tham khảo [1] ...
        m_ref = REF_ITEM_RE.match(stripped)
        if m_ref:
            ref_idx, ref_body = m_ref.group(1), m_ref.group(2)
            p_r = doc.add_paragraph()
            p_r.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p_r.paragraph_format.left_indent = Cm(1.1)
            p_r.paragraph_format.first_line_indent = Cm(-1.1)
            p_r.paragraph_format.line_spacing = 1.4
            p_r.paragraph_format.space_after = Pt(5)
            r_tag = p_r.add_run(f"[{ref_idx}] ")
            _set_font(r_tag, BODY_FONT, 13.0, bold=True)
            add_inline(p_r, ref_body, size=13.0)
            i += 1
            continue

        # --- Đoạn văn học thuật thông thường (thụt đầu dòng 1,0 cm, giãn dòng 1,5, Justify)
        para_lines = [stripped]
        i += 1
        while i < total:
            nxt = lines[i]
            ns = nxt.strip()
            if (
                not ns
                or ns.startswith(("#", "|", ">", "```", "![", "- ", "* ", "$$"))
                or TABLE_CAP_RE.match(ns)
                or FIG_CAP_RE.match(ns)
                or REF_ITEM_RE.match(ns)
                or re.match(r"^\d+\.\s", ns)
                or ns in {"---", "***", "___"}
            ):
                break
            para_lines.append(ns)
            i += 1

        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.first_line_indent = Cm(1.0)
        p.paragraph_format.line_spacing = 1.5
        p.paragraph_format.space_after = Pt(6)
        add_inline(p, " ".join(para_lines), size=13.0)

    out_path = TARGET
    try:
        doc.save(out_path)
    except PermissionError:
        out_path = HERE / "BaoCao_DoAn_GiamSatHocTap_ChuLon.docx"
        doc.save(out_path)
        print(
            f"Lưu ý: {TARGET.name} đang được mở trong Microsoft Word nên không thể ghi đè trực tiếp.\n"
            f"Đã ghi bản cập nhật hình chữ lớn sang tệp mới: {out_path}"
        )
    else:
        print(f"Đã xuất thành công: {out_path}")

    print(
        f"Thống kê: {len(doc.paragraphs)} đoạn văn · {len(doc.tables)} bảng tổng "
        f"({table_counter} bảng nội dung đánh số SEQ) · {fig_counter} hình đánh số SEQ"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main_build())
