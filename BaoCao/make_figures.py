# -*- coding: utf-8 -*-
"""Sinh toàn bộ hình cho báo cáo đồ án (matplotlib, tiếng Việt).

Chạy:  python BaoCao/make_figures.py
Kết quả: BaoCao/figures/*.png

Mọi con số trong hình đều lấy từ tài liệu của dự án:
  - docs/SPEC_V2.md  §14  (bảng phân vị p50; 8 lần đo FPS pipeline)
  - docs/SPEC_V3.md  §4.2 / §4.3  (chi phí từng model, ngân sách FPS)
  - docs/SPEC_V3.md  §16  (hiện trạng đo trên Pi 4)
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"
FIG.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- font tiếng Việt
def _pick_font() -> str:
    for path in (
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
    ):
        if Path(path).is_file():
            font_manager.fontManager.addfont(path)
            return font_manager.FontProperties(fname=path).get_name()
    return "DejaVu Sans"


VI_FONT = _pick_font()
plt.rcParams.update(
    {
        "font.family": VI_FONT,
        "font.size": 10,
        "axes.unicode_minus": False,
        "figure.dpi": 200,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
        "savefig.facecolor": "white",
    }
)

C_BLUE, C_BLUE_L = "#1877f2", "#dce9fc"
C_GREEN, C_GREEN_L = "#1f7a4d", "#dbf0e4"
C_AMBER, C_AMBER_L = "#a8681a", "#fbeed6"
C_RED, C_RED_L = "#b3261e", "#fadedb"
C_GREY, C_GREY_L = "#4a5568", "#eceff4"
C_INK = "#16202f"
C_BAND = "#f8fafc"


# ------------------------------------------------------------------- primitives
def _blank(figsize, *, top=0.88):
    fig, ax = plt.subplots(figsize=figsize)
    fig.subplots_adjust(left=0.012, right=0.988, bottom=0.03, top=top)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def _title(fig, text, sub=None):
    """Vẽ tiêu đề; khoảng cách dòng tính theo inch nên không chồng ở hình thấp."""
    height_in = fig.get_size_inches()[1]
    top = 0.988
    fig.text(0.012, top, text, ha="left", va="top", fontsize=15,
             fontweight="bold", color=C_INK)
    if sub:
        # 15 pt ≈ 0,208 in; cộng 0,12 in thở
        sub_y = top - (0.208 + 0.115) / height_in
        fig.text(0.012, sub_y, sub, ha="left", va="top", fontsize=9.6,
                 color=C_GREY)
        return sub_y - (0.135 + 0.10) / height_in
    return top - (0.208 + 0.10) / height_in


def _box(ax, x, y, w, h, text, *, fc=C_GREY_L, ec=C_GREY, fs=9, weight="normal",
         color=C_INK, lw=1.2, ls="-", zorder=3):
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.004,rounding_size=0.012",
            linewidth=lw, facecolor=fc, edgecolor=ec,
            linestyle=ls, zorder=zorder,
        )
    )
    if text:
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
                color=color, fontweight=weight, zorder=zorder + 1, linespacing=1.5)


def _band(ax, y, h, label, *, fc=C_BAND, ec="#cbd5e1"):
    """Dải nền cho một tầng, kèm nhãn ở góc trên trái."""
    ax.add_patch(
        FancyBboxPatch(
            (0.0, y), 1.0, h,
            boxstyle="round,pad=0.0,rounding_size=0.012",
            linewidth=1.0, facecolor=fc, edgecolor=ec, zorder=1,
        )
    )
    ax.text(0.014, y + h - 0.030, label, ha="left", va="center", fontsize=9.2,
            color=C_GREY, fontweight="bold", zorder=2)


def _arrow(ax, p_from, p_to, *, color=C_GREY, lw=1.5, ls="-", rad=0.0, zorder=2):
    ax.add_patch(
        FancyArrowPatch(
            p_from, p_to, arrowstyle="-|>", mutation_scale=14, linewidth=lw,
            color=color, linestyle=ls, zorder=zorder,
            connectionstyle=f"arc3,rad={rad}", shrinkA=1, shrinkB=1,
        )
    )


def _save(fig, name: str) -> None:
    fig.savefig(FIG / name)
    plt.close(fig)
    print("  ghi figures/" + name)


# ============================================================ 1. Kiến trúc tổng thể
def fig_architecture() -> None:
    fig, ax = _blank((11.6, 7.6), top=0.90)
    _title(fig, "Kiến trúc tổng thể hệ thống",
           "Bốn tầng: phần cứng · model AI · điều phối và web backend · giao diện người dùng")

    BH = 0.108          # chiều cao hộp trong một dải
    GAP = 0.050         # khe giữa hai dải (đủ chỗ cho mũi tên + nhãn)
    H = 0.196           # chiều cao một dải
    Y4 = 0.055
    Y3 = Y4 + H + GAP
    Y2 = Y3 + H + GAP
    Y1 = Y2 + H + GAP

    # ---- tầng 1
    _band(ax, Y1, H, "TẦNG 1 — PHẦN CỨNG")
    cells = [
        (0.02, 0.225, "Camera IP (RTSP)\nluồng phụ 704×576 @ 20 fps\nHEVC · có PTZ · có loa"),
        (0.26, 0.225, "Raspberry Pi 4 Model B\n4 GB RAM · Trixie aarch64\nPython 3.13.5"),
        (0.50, 0.225, "GPIO qua gpiozero\n3 LED · buzzer · mô-tơ rung"),
        (0.74, 0.24, "Thẻ nhớ / đĩa\nSQLite — không lưu ảnh, video"),
    ]
    for x, w, t in cells:
        _box(ax, x, Y1 + 0.016, w, BH, t, fc=C_BLUE_L, ec=C_BLUE, fs=8.4)

    # ---- tầng 2
    _band(ax, Y2, H, "TẦNG 2 — MODEL AI (chạy trên Pi, không GPU)")
    cells = [
        (0.02, 0.245, "YOLO11n-pose · NCNN · imgsz 320\n17 keypoint COCO + track id\n→ PoseResult"),
        (0.28, 0.245, "YOLO11n detect · NCNN\nlớp 67 “cell phone”\n→ PhoneDetector"),
        (0.54, 0.22, "YuNet 228 KB\nphát hiện khuôn mặt"),
        (0.78, 0.20, "SFace 37 MB\nembedding 128 chiều\n→ MATCH / MISMATCH / UNKNOWN"),
    ]
    for x, w, t in cells:
        _box(ax, x, Y2 + 0.016, w, BH, t, fc=C_GREEN_L, ec=C_GREEN, fs=8.4)

    # ---- tầng 3
    _band(ax, Y3, H, "TẦNG 3 — ĐIỀU PHỐI VÀ WEB BACKEND (Flask 3.1.3)")
    cells = [
        (0.02, 0.175, "Hợp tín hiệu\npresence · phone\nidentity"),
        (0.21, 0.175, "Phiên học\nStudySession\n+ schedule"),
        (0.40, 0.175, "SpeakerAlerter\nloa camera\nPCMA 8 kHz"),
        (0.59, 0.155, "Storage\nSQLite 3 bảng\n+ faces.json"),
    ]
    for x, w, t in cells:
        _box(ax, x, Y3 + 0.016, w, BH, t, fc=C_AMBER_L, ec=C_AMBER, fs=8.4)
    _box(ax, 0.76, Y3 + 0.016, 0.22, BH,
         "DashboardState\nkhe hẹp duy nhất\ngiữa vòng lặp và web",
         fc=C_RED_L, ec=C_RED, fs=8.4)

    # ---- tầng 4
    _band(ax, Y4, H, "TẦNG 4 — GIAO DIỆN NGƯỜI DÙNG (LAN)")
    cells = [
        (0.02, 0.29, "Dashboard “/”\nMJPEG /stream · 3 thẻ tín hiệu\nthẻ phiên học · 4 nút PTZ"),
        (0.325, 0.29, "JSON API (22 route)\n/api/status · /api/signals\n/api/people · /api/session …"),
        (0.63, 0.35, "Điện thoại trong WiFi\nTắt tiếng · hiệu chỉnh · thêm người\nchọn người · chọn giọng đọc"),
    ]
    for x, w, t in cells:
        _box(ax, x, Y4 + 0.016, w, BH, t, fc=C_GREY_L, ec=C_GREY, fs=8.4)

    # ---- mũi tên giữa các tầng
    gap1 = (Y1, Y2 + H)
    mid = (gap1[0] + gap1[1]) / 2
    _arrow(ax, (0.255, gap1[0]), (0.255, gap1[1]), color=C_BLUE, lw=1.8)
    ax.text(0.266, mid, "khung BGR 640×480 · xả đệm, giữ khung mới nhất",
            fontsize=7.6, color=C_BLUE, va="center")

    gap2 = (Y2, Y3 + H)
    mid = (gap2[0] + gap2[1]) / 2
    for x in (0.36, 0.60, 0.86):
        _arrow(ax, (x, gap2[0]), (x, gap2[1]), color=C_GREEN, lw=1.4)
    ax.text(0.03, mid, "keypoint · hộp điện thoại · embedding (không phải ảnh)",
            fontsize=7.4, color=C_GREEN, va="center")

    gap3 = (Y3, Y4 + H)
    mid = (gap3[0] + gap3[1]) / 2
    _arrow(ax, (0.87, gap3[0]), (0.87, gap3[1]), color=C_RED, lw=1.8)
    ax.text(0.884, mid, "JSON + JPEG", fontsize=7.4, color=C_RED, va="center")
    _arrow(ax, (0.62, gap3[1]), (0.80, gap3[0]), color=C_RED, lw=1.3, ls="--", rad=-0.25)
    ax.text(0.30, mid, "lệnh: bắt đầu / dừng phiên · PTZ · tắt tiếng · thêm người",
            fontsize=7.4, color=C_RED, va="center")

    _save(fig, "01-kien-truc-tong-the.png")


# ============================================================ 2. Luồng xử lý AI
def fig_ai_pipeline() -> None:
    fig, ax = _blank((11.6, 5.6), top=0.86)
    _title(fig, "Luồng xử lý một khung hình qua tầng AI",
           "Mỗi model có chu kỳ riêng để giữ ngân sách thời gian; kết quả là ba tín hiệu, không phải ảnh")

    yc = 0.55
    row = 0.20

    _box(ax, 0.010, yc - 0.145, 0.145, 0.29,
         "CaptureThread\n(RTSP)\n\nxả đệm,\ngiữ khung\nmới nhất",
         fc=C_BLUE_L, ec=C_BLUE, fs=8.2)

    models = [
        (yc + row, "PoseEstimator\nYOLO11n-pose · NCNN\nchạy MỖI khung"),
        (yc, "PhoneDetector\nYOLO11n detect · NCNN\nchạy 1/2 khung"),
        (yc - row, "FaceWorker\nYuNet + SFace\nluồng riêng, mỗi 2 s"),
    ]
    for y, t in models:
        _box(ax, 0.185, y - 0.072, 0.165, 0.144, t, fc=C_GREEN_L, ec=C_GREEN, fs=8.2)

    outs = [
        (yc + row, "Đặc trưng hình học\nvai · mũi · tai · hướng đầu"),
        (yc, "Quy tắc “chạm”\ncổ tay 9/10 trong hộp lớp 67"),
        (yc - row, "FaceMatcher\ncosine với gallery"),
    ]
    for y, t in outs:
        _box(ax, 0.375, y - 0.072, 0.185, 0.144, t, fc=C_GREY_L, ec=C_GREY, fs=8.2)

    _box(ax, 0.585, yc - 0.145, 0.155, 0.29,
         "Hợp tín hiệu\n\ncó mặt / vắng mặt\nđang dùng điện thoại\nđúng người / người lạ",
         fc=C_AMBER_L, ec=C_AMBER, fs=8.2)

    _box(ax, 0.765, yc - 0.145, 0.10, 0.29,
         "Cổng\nhai lớp\n\n1) StudySession\n2) schedule",
         fc=C_RED_L, ec=C_RED, fs=8.2)

    _box(ax, 0.885, yc + 0.055, 0.10, 0.09, "Loa camera\nPCMA", fc=C_RED_L, ec=C_RED, fs=8.2)
    _box(ax, 0.885, yc - 0.145, 0.10, 0.09, "SQLite\nsự kiện", fc=C_RED_L, ec=C_RED, fs=8.2)

    for y in (yc + row, yc, yc - row):
        _arrow(ax, (0.156, yc), (0.185, y), color=C_BLUE, lw=1.3,
               rad=0.12 if y != yc else 0.0)
        _arrow(ax, (0.351, y), (0.375, y), color=C_GREEN, lw=1.3)
        _arrow(ax, (0.561, y), (0.585, yc), color=C_AMBER, lw=1.3,
               rad=0.10 if y > yc else (-0.10 if y < yc else 0.0))
    _arrow(ax, (0.741, yc), (0.765, yc), color=C_RED, lw=1.5)
    _arrow(ax, (0.866, yc + 0.06), (0.885, yc + 0.10), color=C_RED, lw=1.5)
    _arrow(ax, (0.866, yc - 0.06), (0.885, yc - 0.10), color=C_RED, lw=1.5)

    ax.text(0.5, 0.045,
            "Chu kỳ khác nhau là quyết định thiết kế: pose cần tín hiệu tươi nhất; đường ống "
            "khuôn mặt tốn 86,1 ms/lượt\nnên không thể chạy mỗi khung; detect điện thoại chạy "
            "cách khung để tiết kiệm CPU.",
            ha="center", va="center", fontsize=8.6, color=C_GREY,
            bbox=dict(boxstyle="round,pad=0.5", fc=C_BAND, ec="#cbd5e1"))

    _save(fig, "02-luong-xu-ly-ai.png")


# ============================================================ 3. Ngân sách thời gian
def fig_time_budget() -> None:
    fig, ax = plt.subplots(figsize=(10.6, 4.6))
    fig.subplots_adjust(left=0.36, right=0.97, bottom=0.20, top=0.82)
    _title(fig, "Ngân sách thời gian một khung hình trên Raspberry Pi 4",
           "Các cột là số ĐÃ ĐO (SPEC_V2 §14, SPEC_V3 §4.2); đường nét đứt 200 ms là ngưỡng để đạt 5 FPS")

    rows = [
        ("Capture RTSP\n(khung thật 704×576)", 65.93, C_BLUE, "đo · p50"),
        ("Pose — trọn đường ống\n(suy luận bên trong: 100,51 ms)", 133.32, C_GREEN, "đo · p50"),
        ("Đường ống khuôn mặt\n(thu nhỏ + CLAHE + YuNet + SFace)", 86.1, C_AMBER, "đo · mỗi lượt"),
        ("Detect điện thoại\n(một lần suy luận)", 98.6, C_RED, "đo trên khung tổng hợp"),
    ]

    ax.set_xlim(0, 275)
    ax.set_ylim(-0.7, len(rows) - 0.3)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([name for name, *_ in rows], fontsize=8.4)
    ax.set_xlabel("thời gian (ms)", fontsize=9)
    ax.grid(axis="x", color="#dde2e9", lw=0.8)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)

    for i, (name, value, color, tag) in enumerate(rows):
        ax.barh(i, value, height=0.5, color=color, alpha=0.85)
        ax.text(value + 3, i, f"{value:.1f} ms · {tag}", va="center", fontsize=8.2,
                color=C_INK)

    ax.axvline(200, color=C_RED, ls="--", lw=1.4)
    ax.text(203, len(rows) - 0.62, "ngân sách 200 ms → 5 FPS", color=C_RED,
            fontsize=8.2, va="center")

    fig.text(0.012, 0.055,
             "Ghép ba dòng đầu (TÍNH TỪ ĐO): 65,93 + 133,32 + 49,3 = 248,55 ms → 4,02 FPS, tức CHƯA đạt 5 FPS.\n"
             "Cấu hình ba model chạy đồng thời vẫn CHƯA ĐO trọn một lần; phép đo pipeline thật duy nhất của dự án "
             "là pose-only 5,02 FPS.",
             fontsize=8.0, color=C_GREY, va="bottom", linespacing=1.6)

    _save(fig, "03-ngan-sach-thoi-gian.png")


# ============================================================ 4. FPS 8 lần đo
def fig_fps_runs() -> None:
    labels = ["12 s", "20 s", "20 s", "30 s", "40 s", "45 s", "60 s", "60 s"]
    values = [5.006, 5.085, 4.985, 5.015, 3.929, 3.833, 4.207, 5.019]

    fig, ax = plt.subplots(figsize=(8.8, 4.2))
    fig.subplots_adjust(left=0.09, right=0.98, bottom=0.16, top=0.80)
    _title(fig, "Tám lần đo FPS pipeline trên Raspberry Pi 4 (chỉ pose)",
           "Cùng build, cùng camera, ngày 28/10/2026 — nguồn: docs/SPEC_V2.md §14")

    colors = [C_GREEN if v >= 5 else C_AMBER for v in values]
    bars = ax.bar(range(len(values)), values, color=colors, width=0.6)
    ax.axhline(5.0, color=C_RED, ls="--", lw=1.4)
    ax.text(3.9, 5.17, "mục tiêu 5 FPS (đường nét đứt)", color=C_RED, fontsize=8.4,
            ha="left", va="center")

    for rect, v in zip(bars, values):
        ax.text(rect.get_x() + rect.get_width() / 2, v + 0.03, f"{v:.2f}",
                ha="center", fontsize=8.2, color=C_INK)

    ax.set_xticks(range(len(values)))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_xlabel("thời lượng mỗi lần chạy", fontsize=9, labelpad=4)
    ax.set_ylabel("FPS", fontsize=9)
    ax.set_ylim(3.4, 5.32)
    ax.grid(axis="y", color="#dde2e9", lw=0.8)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    fig.text(0.09, 0.028,
             "4/8 lần đạt ≥ 5 FPS · trung vị ≈ 4,96 FPS  →  kết luận trong tài liệu: chưa đạt ổn định",
             fontsize=8.6, color=C_GREY)

    _save(fig, "04-fps-tam-lan-do.png")


# ============================================================ 5. Kiến trúc web
def fig_web() -> None:
    fig, ax = _blank((11.4, 5.8), top=0.87)
    _title(fig, "Kiến trúc tầng web: một khe hẹp giữa vòng lặp camera và Flask",
           "DashboardState là cầu nối duy nhất — web không mở camera, vòng lặp không chạm Flask")

    _box(ax, 0.010, 0.52, 0.215, 0.34,
         "Trình duyệt\n(điện thoại / PC trong LAN)\n\n· thẻ <img> gắn /stream\n· fetch() JSON mỗi 1 giây",
         fc=C_BLUE_L, ec=C_BLUE, fs=8.4)

    _box(ax, 0.255, 0.52, 0.30, 0.34,
         "Flask 3.1.3 — web/app.py\n\n"
         "GET /  ·  GET /stream (MJPEG)\n"
         "GET /api/status · /api/history · /api/signals\n"
         "POST /api/session/start · /stop\n"
         "GET·POST /api/people · /api/enroll · /api/select\n"
         "GET·PUT /api/schedule · POST /api/ptz · /api/speak",
         fc=C_GREEN_L, ec=C_GREEN, fs=7.8)

    _box(ax, 0.585, 0.66, 0.40, 0.20,
         "DashboardState (chỉ trong RAM)\nkhung JPEG mới nhất · trạng thái · muted\ncờ hiệu chỉnh · snapshot phiên học",
         fc=C_RED_L, ec=C_RED, fs=8.2)

    _box(ax, 0.585, 0.40, 0.40, 0.20,
         "Storage (SQLite)\nsessions · events · minute_stats\npeople · face_embeddings",
         fc=C_AMBER_L, ec=C_AMBER, fs=8.2)

    _box(ax, 0.255, 0.07, 0.30, 0.34,
         "Vòng lặp chính _monitor_loop\n(luồng riêng, ~5 FPS)\n\npose · detect điện thoại · khuôn mặt\nquyết định cảnh báo",
         fc=C_GREY_L, ec=C_GREY, fs=8.4)

    _box(ax, 0.010, 0.07, 0.215, 0.34,
         "Camera IP (RTSP)\n\ncapture + xả đệm\nluôn giữ khung mới nhất\n(không xếp hàng, không tăng trễ)",
         fc=C_BLUE_L, ec=C_BLUE, fs=8.4)

    _arrow(ax, (0.225, 0.72), (0.255, 0.72), color=C_GREY, lw=1.5)
    _arrow(ax, (0.255, 0.64), (0.225, 0.64), color=C_GREY, lw=1.5)
    ax.text(0.240, 0.775, "HTTP", fontsize=7.6, color=C_GREY, ha="center")

    _arrow(ax, (0.555, 0.74), (0.585, 0.76), color=C_RED, lw=1.5)
    _arrow(ax, (0.585, 0.70), (0.555, 0.68), color=C_RED, lw=1.5, ls="--")
    ax.text(0.570, 0.700, "ghi/đọc", fontsize=7.4, color=C_RED, ha="center")

    _arrow(ax, (0.555, 0.58), (0.585, 0.54), color=C_AMBER, lw=1.5)
    ax.text(0.565, 0.545, "record()", fontsize=7.4, color=C_AMBER, ha="center")

    _arrow(ax, (0.405, 0.41), (0.405, 0.52), color=C_GREEN, lw=1.8)
    ax.text(0.415, 0.465, "set_frame() · update() · snapshot()", fontsize=7.6,
            color=C_GREEN, va="center")

    _arrow(ax, (0.225, 0.24), (0.255, 0.24), color=C_BLUE, lw=1.5)
    ax.text(0.240, 0.28, "khung", fontsize=7.6, color=C_BLUE, ha="center")

    ax.text(0.5, 0.012,
            "Khung hình chỉ tồn tại trong RAM: không ghi đĩa, không lưu lịch sử, "
            "không route nào trả ảnh hay vector khuôn mặt.",
            ha="center", fontsize=8.6, color=C_GREY, style="italic")

    _save(fig, "05-kien-truc-web.png")


# ============================================================ 6. Luồng sử dụng web
def fig_web_flow() -> None:
    fig, ax = _blank((11.4, 4.4), top=0.84)
    _title(fig, "Một vòng đời sử dụng trên dashboard",
           "Mở trang → xem camera → bấm Bắt đầu học → theo dõi mỗi giây → dừng hoặc hết giờ")

    steps = [
        ("1 · Mở trang", "GET /\ntrả HTML + CSS/JS\nnội bộ, không CDN"),
        ("2 · Xem camera", "GET /stream\nMJPEG từ khung\nmới nhất trong RAM"),
        ("3 · Bắt đầu", "POST /api/session/start\n{\"minutes\": 60}\n→ model AI chạy"),
        ("4 · Theo dõi", "GET /api/signals mỗi 1 s\ntuổi tín hiệu · cảnh báo\nloa tự phát"),
        ("5 · Kết thúc", "POST /api/session/stop\nhoặc hết giờ → dừng\nmodel, ghi SQLite"),
    ]
    w, gap = 0.172, 0.021
    for i, (head, body) in enumerate(steps):
        x = 0.014 + i * (w + gap)
        _box(ax, x, 0.46, w, 0.32, f"{head}\n\n{body}", fc=C_BLUE_L, ec=C_BLUE, fs=8.0)
        if i < len(steps) - 1:
            _arrow(ax, (x + w + 0.004, 0.62), (x + w + gap - 0.004, 0.62), color=C_GREY)

    ax.text(0.5, 0.20,
            "Hai cổng phải cùng mở thì cảnh báo mới phát: StudySession (bấm tay) VÀ schedule (khung giờ học).\n"
            "Ngoài phiên, pose và dò điện thoại KHÔNG chạy — nhưng camera và nhận diện khuôn mặt vẫn chạy.",
            ha="center", va="center", fontsize=8.6, color=C_GREY,
            bbox=dict(boxstyle="round,pad=0.55", fc=C_BAND, ec="#cbd5e1"))

    _save(fig, "06-luong-su-dung-web.png")


# ============================================================ 7. Sơ đồ đấu dây
def fig_wiring() -> None:
    fig, ax = _blank((10.8, 5.6), top=0.87)
    _title(fig, "Nhóm GPIO mặc định (số chân BCM)",
           "Kênh cảnh báo chính của đồ án là loa camera; nhóm này là kênh phụ, mặc định chỉ đổi LED")

    _box(ax, 0.03, 0.14, 0.30, 0.66,
         "Raspberry Pi 4\n40 chân GPIO\n\nlogic 3,3 V\n\n"
         "CHÚ Ý: ECHO của HC-SR04\nlà 5 V — bắt buộc\nchia áp trước khi nối",
         fc=C_GREEN_L, ec=C_GREEN, fs=8.8)

    pins = [
        ("GPIO17", "LED xanh — GOOD", "điện trở 220–330 Ω", C_GREEN, 0.695),
        ("GPIO27", "LED vàng — WARN", "điện trở 220–330 Ω", C_AMBER, 0.585),
        ("GPIO22", "LED đỏ — BAD", "điện trở 220–330 Ω", C_RED, 0.475),
        ("GPIO18", "Buzzer chủ động", "qua transistor NPN nếu dòng lớn", C_GREY, 0.365),
        ("GPIO23", "Mô-tơ rung", "NPN + diode flyback", C_GREY, 0.255),
        ("GPIO5 · GPIO6", "HC-SR04 TRIG · ECHO", "chia áp 5 V → 3,3 V", C_BLUE, 0.145),
    ]
    for pin, device, note, color, y in pins:
        _box(ax, 0.40, y, 0.145, 0.075, pin, fc="white", ec=color, fs=8.4, lw=1.4)
        _box(ax, 0.565, y, 0.215, 0.075, device, fc="white", ec=color, fs=8.4)
        ax.text(0.792, y + 0.037, note, fontsize=7.8, color=C_GREY, va="center")
        _arrow(ax, (0.331, 0.47), (0.40, y + 0.037), color=color, lw=1.2, rad=0.04)

    ax.text(0.03, 0.075,
            "I²C (tuỳ chọn): SDA = GPIO2 · SCL = GPIO3 — OLED SSD1306 địa chỉ 0x3C",
            fontsize=8.2, color=C_GREY)

    _save(fig, "07-so-do-dau-day.png")


# ============================================================ 8. Bản đồ module
def fig_modules() -> None:
    fig, ax = _blank((11.4, 3.1), top=0.74)
    _title(fig, "Bản đồ module theo bốn phần của báo cáo",
           "Mỗi phần ứng với một nhóm tệp trong src/posture_monitor/ — dùng làm mục lục kỹ thuật")

    groups = [
        ("MODEL AI", "pose.py · phone.py\nphone_detector.py · presence.py\nfaces.py · face_worker.py\n"
                     "overlay.py · features.py\nclassifier.py · calibration.py",
         C_GREEN, C_GREEN_L, 0.012),
        ("WEB FE / BE", "web/app.py · web/templates\nweb/static · people_service.py\n"
                        "study_session.py · schedule.py\nstorage.py · alerts.py", C_BLUE, C_BLUE_L, 0.262),
        ("PHẦN CỨNG", "capture.py · camera_control.py\ncamera_audio.py · speaker_alert.py\n"
                      "voice_library.py · sensors.py\nhardware/ (gpio_real, gpio_mock)",
         C_AMBER, C_AMBER_L, 0.512),
        ("VẬN HÀNH", "__main__.py (CLI 5 lệnh)\nconfig.py · benchmark.py\n"
                     "scripts/ (3 công cụ)\ntests/ (54 tệp, 1496 bài)", C_GREY, C_GREY_L, 0.762),
    ]
    for head, body, ec, fc, x in groups:
        _box(ax, x, 0.03, 0.226, 0.80, "", fc=fc, ec=ec, lw=1.4)
        ax.text(x + 0.113, 0.78, head, ha="center", va="center", fontsize=10.5,
                fontweight="bold", color=ec)
        ax.text(x + 0.113, 0.42, body, ha="center", va="center", fontsize=7.9,
                color=C_INK, linespacing=1.75)

    _save(fig, "08-ban-do-module.png")


def main() -> int:
    print("Sinh hình cho báo cáo vào", FIG)
    for fn in (
        fig_architecture,
        fig_ai_pipeline,
        fig_time_budget,
        fig_fps_runs,
        fig_web,
        fig_web_flow,
        fig_wiring,
        fig_modules,
    ):
        fn()
    print("Xong.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
