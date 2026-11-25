# -*- coding: utf-8 -*-
"""Sinh toàn bộ 9 hình sơ đồ & biểu đồ cho báo cáo đồ án (chuẩn in A4 rõ chữ).

Nguyên tắc tỉ lệ chữ cho trang in A4 (vùng in ngang 15,5 cm ≈ 6,10 inch):
- Đặt chiều rộng ``figsize`` trong khoảng 7,8 - 8,2 inch (hệ số co khi vào Word ≈ 0,76 - 0,78)
  ở độ phân giải 260 DPI (~2.100 px ngang).
- Mọi cỡ chữ nội dung đặt từ 10,8 pt đến 13,5 pt (tiêu đề khối 12 - 14 pt Bold), đảm bảo khi in
  ra giấy A4 hoặc xem 100% trong Word chữ đạt kích thước thực 8,5 - 11,0 pt, rõ nét tuyệt đối.
- Chuyển các sơ đồ dàn ngang quá nhiều cột nhỏ sang bố cục phân tầng dọc / lưới 2x2 thoáng đãng.

Chạy:  python BaoCao/make_figures.py
Kết quả: BaoCao/figures/*.png
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
        "font.size": 11.5,
        "axes.unicode_minus": False,
        "figure.dpi": 260,
        "savefig.dpi": 260,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.08,
        "savefig.facecolor": "white",
    }
)

C_BLUE, C_BLUE_L = "#1d4ed8", "#dbeafe"
C_GREEN, C_GREEN_L = "#15803d", "#dcfce7"
C_AMBER, C_AMBER_L = "#b45309", "#fef3c7"
C_RED, C_RED_L = "#b91c1c", "#fee2e2"
C_GREY, C_GREY_L = "#334155", "#f1f5f9"
C_INK = "#0f172a"
C_BAND = "#f8fafc"


def _blank(figsize: tuple[float, float]):
    fig, ax = plt.subplots(figsize=figsize)
    fig.subplots_adjust(left=0.01, right=0.99, bottom=0.01, top=0.99)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def _box(
    ax,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    *,
    fc: str = C_GREY_L,
    ec: str = C_GREY,
    fs: float = 11.5,
    weight: str = "normal",
    color: str = C_INK,
    lw: float = 1.6,
    ls: str = "-",
    zorder: int = 3,
    linespacing: float = 1.38,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.004,rounding_size=0.014",
            linewidth=lw,
            facecolor=fc,
            edgecolor=ec,
            linestyle=ls,
            zorder=zorder,
        )
    )
    if text:
        ax.text(
            x + w / 2,
            y + h / 2,
            text,
            ha="center",
            va="center",
            fontsize=fs,
            color=color,
            fontweight=weight,
            zorder=zorder + 1,
            linespacing=linespacing,
        )


def _band(ax, y: float, h: float, label: str, *, fc: str = C_BAND, ec: str = "#94a3b8", label_color: str = C_INK) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (0.005, y),
            0.99,
            h,
            boxstyle="round,pad=0.0,rounding_size=0.014",
            linewidth=1.3,
            facecolor=fc,
            edgecolor=ec,
            zorder=1,
        )
    )
    ax.text(
        0.022,
        y + h - 0.026,
        label,
        ha="left",
        va="center",
        fontsize=12.0,
        color=label_color,
        fontweight="bold",
        zorder=2,
    )


def _arrow(
    ax,
    p_from: tuple[float, float],
    p_to: tuple[float, float],
    *,
    color: str = C_GREY,
    lw: float = 2.0,
    ls: str = "-",
    rad: float = 0.0,
    zorder: int = 4,
) -> None:
    ax.add_patch(
        FancyArrowPatch(
            p_from,
            p_to,
            arrowstyle="-|>",
            mutation_scale=16,
            linewidth=lw,
            color=color,
            linestyle=ls,
            zorder=zorder,
            connectionstyle=f"arc3,rad={rad}",
            shrinkA=2,
            shrinkB=2,
        )
    )


def _pill_label(ax, x: float, y: float, text: str, *, color: str = C_INK, ec: str = "#cbd5e1", fs: float = 10.6) -> None:
    ax.text(
        x,
        y,
        text,
        ha="center",
        va="center",
        fontsize=fs,
        fontweight="bold",
        color=color,
        zorder=6,
        bbox=dict(boxstyle="round,pad=0.28", fc="white", ec=ec, lw=1.0),
    )


def _save(fig, name: str) -> None:
    fig.savefig(FIG / name)
    plt.close(fig)
    print("  ghi figures/" + name)


# ============================================================ 1. Kiến trúc tổng thể 4 tầng
def fig_architecture() -> None:
    fig, ax = _blank((8.2, 8.6))

    H = 0.205
    GAP = 0.052
    Y4 = 0.012
    Y3 = Y4 + H + GAP
    Y2 = Y3 + H + GAP
    Y1 = Y2 + H + GAP

    BH = 0.135

    # Tầng 1: Phần cứng
    _band(ax, Y1, H, "TẦNG 1: PHẦN CỨNG & LƯU TRỮ BIÊN", label_color=C_BLUE)
    t1 = [
        (0.02, 0.31, "Camera IP (RTSP / ONVIF)\nLuồng phụ 704×576 @ 20 fps\nHEVC · Loa tích hợp · PTZ"),
        (0.345, 0.31, "Raspberry Pi 4 Model B\n4 GB RAM · Trixie aarch64\nPython 3.13.5 (không GPU)"),
        (0.67, 0.31, "Ngoại vi & Thẻ nhớ\nGPIO (3 LED, còi, rung)\nSQLite WAL (không lưu ảnh)"),
    ]
    for x, w, txt in t1:
        _box(ax, x, Y1 + 0.015, w, BH, txt, fc=C_BLUE_L, ec=C_BLUE, fs=11.0, weight="bold")

    # Tầng 2: Model AI
    _band(ax, Y2, H, "TẦNG 2: MÔ HÌNH AI PRETRAINED TRÊN CPU BIÊN", label_color=C_GREEN)
    t2 = [
        (0.02, 0.305, "YOLO11n-pose (NCNN @320)\n17 khớp xương + track id\nChạy mỗi khung hình", 10.8),
        (0.34, 0.305, "YOLO11n detect (NCNN @320)\nLớp 67 'cell phone'\nChạy 1/2 khung + lọc vai", 10.8),
        (0.66, 0.32, "YuNet + SFace (ONNX)\nVector 128 chiều (mỗi 2 s)\nMATCH · MISMATCH · UNKNOWN", 10.2),
    ]
    for x, w, txt, fsize in t2:
        _box(ax, x, Y2 + 0.015, w, BH, txt, fc=C_GREEN_L, ec=C_GREEN, fs=fsize, weight="bold")

    # Tầng 3: Điều phối miền & Khe hẹp
    _band(ax, Y3, H, "TẦNG 3: ĐIỀU PHỐI NGHIỆP VỤ & KHE HẸP TRẠNG THÁI", label_color=C_AMBER)
    _box(
        ax, 0.02, Y3 + 0.015, 0.32, BH,
        "Nghiệp vụ (domain/)\nPresence · Phiên học 2 lớp\nPeopleService · SignalBoard",
        fc=C_AMBER_L, ec=C_AMBER, fs=11.0, weight="bold",
    )
    _box(
        ax, 0.355, Y3 + 0.015, 0.29, BH,
        "Cảnh báo (alerts/)\nLoa camera PCMA 8 kHz\n3 tầng giọng đọc + GPIO",
        fc=C_AMBER_L, ec=C_AMBER, fs=11.0, weight="bold",
    )
    _box(
        ax, 0.66, Y3 + 0.015, 0.32, BH,
        "DashboardState (RAM)\nKhe hẹp đồng bộ duy nhất\ngiữa vòng lặp AI & Flask",
        fc=C_RED_L, ec=C_RED, fs=11.0, weight="bold",
    )

    # Tầng 4: Giao diện người dùng LAN
    _band(ax, Y4, H, "TẦNG 4: DỊCH VỤ FLASK :8000 & ĐA GIAO DIỆN MẠNG LAN", label_color=C_GREY)
    _box(
        ax, 0.02, Y4 + 0.015, 0.465, BH,
        "Web Dashboard (HTML/JS Offline-first)\nLuồng MJPEG /stream · 24 route HTTP\nQuét 5 góc mặt · Phiên học · PTZ",
        fc=C_GREY_L, ec=C_GREY, fs=11.0, weight="bold",
    )
    _box(
        ax, 0.505, Y4 + 0.015, 0.475, BH,
        "Ứng dụng Di động (React Native / Expo 58)\nNocturne Telemetry · 6 tab điều hướng\nTab Camera gộp 3 Tín hiệu + Tư thế",
        fc=C_GREY_L, ec=C_GREY, fs=11.0, weight="bold",
    )

    # Mũi tên giữa các tầng (rõ ràng, không đè chữ)
    m12 = (Y1 + Y2 + H) / 2
    _arrow(ax, (0.18, Y1), (0.18, Y2 + H), color=C_BLUE, lw=2.2)
    _pill_label(ax, 0.52, m12, "Khung BGR 704×576 (xả đệm 30 ms, giữ khung mới nhất)", color=C_BLUE, ec=C_BLUE)

    m23 = (Y2 + Y3 + H) / 2
    _arrow(ax, (0.18, Y2), (0.18, Y3 + H), color=C_GREEN, lw=2.2)
    _arrow(ax, (0.82, Y2), (0.82, Y3 + H), color=C_GREEN, lw=2.2)
    _pill_label(ax, 0.50, m23, "Tọa độ khớp xương · Hộp điện thoại · Vector 128D", color=C_GREEN, ec=C_GREEN)

    m34 = (Y3 + Y4 + H) / 2
    _arrow(ax, (0.82, Y3), (0.82, Y4 + H), color=C_RED, lw=2.2)
    _arrow(ax, (0.18, Y4 + H), (0.18, Y3), color=C_RED, lw=2.0, ls="--")
    _pill_label(ax, 0.50, m34, "JSON + MJPEG / JPEG  ↔  Lệnh phiên học, PTZ, tắt tiếng", color=C_RED, ec=C_RED)

    _save(fig, "01-kien-truc-tong-the.png")


# ============================================================ 2. Luồng xử lý AI (Bố cục dọc 3 nhánh lớn)
def fig_ai_pipeline() -> None:
    fig, ax = _blank((8.2, 7.4))

    # Hàng 1: Nguồn khung hình
    _box(
        ax, 0.04, 0.855, 0.92, 0.125,
        "Luồng thu nhận RTSP (camera/capture.py)\nKhung thật 704×576 @ 20 fps · Vòng xả grab() > 30 ms giữ khung mới nhất",
        fc=C_BLUE_L, ec=C_BLUE, fs=11.4, weight="bold",
    )

    # Hàng 2: 3 Nhánh AI song song (mỗi cột rộng 30.5% -> chữ rất to!)
    cols = [
        (0.02, "PoseEstimator\nYOLO11n-pose (NCNN)\nChạy MỖI KHUNG",
         "Kiểm tra hiện diện\n≥ 2/7 khớp thân trên\n+ khóa track id (120 s)"),
        (0.347, "PhoneDetector\nYOLO11n detect (NCNN)\nChạy 1/2 KHUNG (TTL 0,5s)",
         "Lọc nhầm gọng kính\nKhoảng cách cổ tay\n≤ 1,0 × bề rộng vai"),
        (0.674, "FaceProcessor\nYuNet + SFace (ONNX)\nChạy MỖI 2,0 GIÂY",
         "So khớp Cosine 128D\n3 trạng thái: MATCH /\nMISMATCH / UNKNOWN"),
    ]
    for x, m_txt, r_txt in cols:
        _box(ax, x, 0.625, 0.306, 0.155, m_txt, fc=C_GREEN_L, ec=C_GREEN, fs=11.2, weight="bold")
        _box(ax, x, 0.415, 0.306, 0.155, r_txt, fc=C_GREY_L, ec=C_GREY, fs=11.0, weight="bold")
        cx = x + 0.153
        _arrow(ax, (0.50, 0.855), (cx, 0.782), color=C_BLUE, lw=2.0)
        _arrow(ax, (cx, 0.625), (cx, 0.572), color=C_GREEN, lw=2.0)
        _arrow(ax, (cx, 0.415), (0.50, 0.342), color=C_AMBER, lw=2.0)

    # Hàng 3: Bảng hợp nhất tín hiệu + Cổng 2 lớp
    _box(
        ax, 0.04, 0.20, 0.44, 0.14,
        "SignalBoard (Hợp nhất 3 tín hiệu)\nCó mặt · Điện thoại · Danh tính\n(Kèm tuổi dữ liệu age_s & cờ fresh)",
        fc=C_AMBER_L, ec=C_AMBER, fs=11.2, weight="bold",
    )
    _box(
        ax, 0.52, 0.20, 0.44, 0.14,
        "Cổng phiên học hai lớp (AND)\n1) StudySession == running\n2) Trong khung giờ schedule",
        fc=C_RED_L, ec=C_RED, fs=11.2, weight="bold",
    )
    _arrow(ax, (0.482, 0.27), (0.518, 0.27), color=C_RED, lw=2.2)

    # Hàng 4: Đầu ra
    _box(
        ax, 0.04, 0.02, 0.44, 0.12,
        "Web Dashboard & App Di động\nCập nhật qua DashboardState (RAM)",
        fc=C_BLUE_L, ec=C_BLUE, fs=11.2, weight="bold",
    )
    _box(
        ax, 0.52, 0.02, 0.44, 0.12,
        "Phát Loa Camera (PCMA 8 kHz)\n& Ghi lô SQLite WAL (10 giây)",
        fc=C_RED_L, ec=C_RED, fs=11.2, weight="bold",
    )
    _arrow(ax, (0.26, 0.20), (0.26, 0.142), color=C_BLUE, lw=2.0)
    _arrow(ax, (0.74, 0.20), (0.74, 0.142), color=C_RED, lw=2.0)

    _save(fig, "02-luong-xu-ly-ai.png")


# ============================================================ 3. Ngân sách thời gian
def fig_time_budget() -> None:
    fig, ax = plt.subplots(figsize=(8.0, 4.9))
    fig.subplots_adjust(left=0.36, right=0.97, bottom=0.25, top=0.93)

    rows = [
        ("Đọc RTSP\n(khung 704×576)", 65.93, C_BLUE, "65,9 ms (ĐÃ ĐO)"),
        ("Trọn nhánh Pose\n(suy luận: 100,5 ms)", 133.32, C_GREEN, "133,3 ms (ĐÃ ĐO)"),
        ("Nhánh Khuôn mặt\n(YuNet + SFace)", 86.1, C_AMBER, "86,1 ms / lượt"),
        ("Detect Điện thoại\n(NCNN @320)", 98.6, C_RED, "98,6 ms / lượt"),
    ]

    ax.set_xlim(0, 290)
    ax.set_ylim(-0.6, len(rows) - 0.35)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([name for name, *_ in rows], fontsize=11.5, fontweight="bold", color=C_INK)
    ax.tick_params(axis="x", labelsize=11.2)
    ax.set_xlabel("Thời gian xử lý (ms)", fontsize=12.0, fontweight="bold", color=C_INK)
    ax.grid(axis="x", color="#cbd5e1", lw=0.9)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)

    for i, (_, value, color, tag) in enumerate(rows):
        ax.barh(i, value, height=0.54, color=color, alpha=0.90)
        ax.text(value + 4, i, tag, va="center", fontsize=11.0, fontweight="bold", color=C_INK)

    ax.axvline(200, color=C_RED, ls="--", lw=2.0)
    ax.text(
        205, len(rows) - 0.35, "Ngưỡng 200 ms\n(5,0 FPS)",
        color=C_RED, fontsize=11.0, fontweight="bold", ha="left", va="top",
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=C_RED, lw=1.0),
    )

    fig.text(
        0.02, 0.02,
        "• Chỉ bật Pose (ĐÃ ĐO): 65,93 + 133,32 = 199,25 ms → 5,02 FPS.\n"
        "• Ghép thêm Detect 1/2 khung (TÍNH TỪ ĐO): 199,25 + 49,30 = 248,55 ms → 4,02 FPS (chưa đạt 5 FPS).",
        fontsize=10.6, fontweight="bold", color=C_GREY, va="bottom", linespacing=1.45,
    )

    _save(fig, "03-ngan-sach-thoi-gian.png")


# ============================================================ 4. FPS 8 lần đo
def fig_fps_runs() -> None:
    labels = ["12 s", "20 s", "20 s", "30 s", "40 s", "45 s", "60 s", "60 s"]
    values = [5.006, 5.085, 4.985, 5.015, 3.929, 3.833, 4.207, 5.019]

    fig, ax = plt.subplots(figsize=(8.0, 4.6))
    fig.subplots_adjust(left=0.10, right=0.98, bottom=0.22, top=0.92)

    colors = [C_GREEN if v >= 5.0 else C_AMBER for v in values]
    bars = ax.bar(range(len(values)), values, color=colors, width=0.58)
    ax.axhline(5.0, color=C_RED, ls="--", lw=2.0)
    ax.text(
        4.35, 5.19, "Mục tiêu 5,0 FPS", color=C_RED, fontsize=11.5, fontweight="bold",
        ha="center", va="center", bbox=dict(boxstyle="round,pad=0.22", fc="white", ec=C_RED, lw=1.0),
    )

    for rect, v in zip(bars, values):
        ax.text(
            rect.get_x() + rect.get_width() / 2,
            v + 0.035,
            f"{v:.2f}".replace(".", ","),
            ha="center",
            fontsize=11.2,
            fontweight="bold",
            color=C_INK,
        )

    ax.set_xticks(range(len(values)))
    ax.set_xticklabels(labels, fontsize=11.5, fontweight="bold")
    ax.tick_params(axis="y", labelsize=11.2)
    ax.set_xlabel("Thời lượng mỗi lượt đo trên Raspberry Pi 4", fontsize=11.8, fontweight="bold", labelpad=6)
    ax.set_ylabel("Tốc độ (FPS)", fontsize=11.8, fontweight="bold")
    ax.set_ylim(3.4, 5.38)
    ax.grid(axis="y", color="#cbd5e1", lw=0.9)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    fig.text(
        0.50, 0.02,
        "Kết quả: 4/8 lượt đạt ≥ 5,0 FPS · Trung vị ≈ 4,96 FPS (dao động sát biên 5 FPS)",
        ha="center", fontsize=11.2, fontweight="bold", color=C_GREY,
    )

    _save(fig, "04-fps-tam-lan-do.png")


# ============================================================ 5. Kiến trúc tầng dịch vụ Web
def fig_web() -> None:
    fig, ax = _blank((8.2, 6.8))

    # Hàng trên: Khách hàng LAN
    _box(
        ax, 0.02, 0.77, 0.45, 0.19,
        "Trình duyệt Web (PC / Điện thoại)\nLuồng <img> /stream (MJPEG)\nFetch JSON mỗi 1,0 giây",
        fc=C_BLUE_L, ec=C_BLUE, fs=11.4, weight="bold",
    )
    _box(
        ax, 0.53, 0.77, 0.45, 0.19,
        "Ứng dụng Di động (Expo SDK 58)\nWebView /stream + /api/frame (300 ms)\nusePoll 2,0 giây + AbortController",
        fc=C_BLUE_L, ec=C_BLUE, fs=11.4, weight="bold",
    )

    # Hàng giữa: Flask + DashboardState
    _box(
        ax, 0.02, 0.41, 0.52, 0.24,
        "Máy chủ Flask 3.1.3 (web/routes/* - 24 route)\n"
        "• core: /, /api/status, /api/mute, /api/history\n"
        "• media: /stream, /api/frame  |  diagnostics: /ptz, /voice\n"
        "• session: /api/session, /schedule, /violations\n"
        "• people: /api/people, /enroll, /signals (scrub_biometrics)",
        fc=C_GREEN_L, ec=C_GREEN, fs=10.6, weight="bold",
    )
    _box(
        ax, 0.60, 0.41, 0.38, 0.24,
        "DashboardState (RAM)\n(threading.Lock duy nhất)\n"
        "• 1 khung JPEG mới nhất\n"
        "• 7 khóa trạng thái + stale\n"
        "• Cờ muted & hiệu chỉnh",
        fc=C_RED_L, ec=C_RED, fs=11.2, weight="bold",
    )

    # Hàng dưới: MonitorRunner + SQLite
    _box(
        ax, 0.02, 0.05, 0.52, 0.23,
        "Vòng lặp MonitorRunner (cli/monitor_runner.py)\n"
        "Camera RTSP → Pose / Phone / Face → Loa PCMA\n"
        "(Hoàn toàn không import Flask)",
        fc=C_GREY_L, ec=C_GREY, fs=11.2, weight="bold",
    )
    _box(
        ax, 0.60, 0.05, 0.38, 0.23,
        "Lưu trữ bền vững trên đĩa\n"
        "• SQLite WAL (3 bảng, lô 10 s)\n"
        "• JSON nguyên tử: faces.json\n"
        "  (Tuyệt đối không lưu ảnh)",
        fc=C_AMBER_L, ec=C_AMBER, fs=11.0, weight="bold",
    )

    # Mũi tên rõ ràng
    _arrow(ax, (0.24, 0.77), (0.24, 0.652), color=C_BLUE, lw=2.0)
    _arrow(ax, (0.75, 0.77), (0.44, 0.652), color=C_BLUE, lw=2.0)
    _pill_label(ax, 0.34, 0.715, "HTTP / MJPEG (Mạng LAN)", color=C_BLUE, ec=C_BLUE)

    _arrow(ax, (0.542, 0.55), (0.598, 0.55), color=C_RED, lw=2.0)
    _arrow(ax, (0.598, 0.50), (0.542, 0.50), color=C_RED, lw=2.0, ls="--")

    _arrow(ax, (0.42, 0.282), (0.68, 0.408), color=C_RED, lw=2.2)
    _pill_label(ax, 0.53, 0.345, "set_frame() · update()", color=C_RED, ec=C_RED)

    _arrow(ax, (0.542, 0.165), (0.598, 0.165), color=C_AMBER, lw=2.0)
    _arrow(ax, (0.79, 0.282), (0.46, 0.408), color=C_AMBER, lw=1.8, ls="--")

    _save(fig, "05-kien-truc-web.png")


# ============================================================ 6. Vòng đời phiên học (Bố cục 2 hàng lớn)
def fig_web_flow() -> None:
    fig, ax = _blank((8.2, 5.6))

    # Hàng 1: Bước 1 -> 2 -> 3
    row1 = [
        (0.02, "1. Mở giao diện", "GET / hoặc mở App\nTải tài nguyên nội bộ\nkhông cần Internet"),
        (0.355, "2. Chỉnh góc & Chọn người", "Xem /stream trực tiếp\nXoay PTZ · Nhận diện\nsẵn người ngồi (2 s/lần)"),
        (0.69, "3. Bắt đầu phiên học", "POST /api/session/start\nBật cổng hai lớp → Kích\nhoạt Pose & Phone AI"),
    ]
    for x, head, body in row1:
        _box(ax, x, 0.60, 0.29, 0.34, f"{head}\n\n{body}", fc=C_BLUE_L, ec=C_BLUE, fs=11.2, weight="bold")

    _arrow(ax, (0.312, 0.77), (0.353, 0.77), color=C_BLUE, lw=2.2)
    _arrow(ax, (0.647, 0.77), (0.688, 0.77), color=C_BLUE, lw=2.2)

    # Hàng 2: Bước 4 & Bước 5 + Ghi chú cổng 2 lớp
    _box(
        ax, 0.52, 0.16, 0.46, 0.32,
        "4. Giám sát trong phiên\nHỏi /api/signals mỗi 1-2 giây · Đủ hold_s\n→ Phát loa camera PCMA & ghi SQLite",
        fc=C_GREEN_L, ec=C_GREEN, fs=11.3, weight="bold",
    )
    _box(
        ax, 0.02, 0.16, 0.44, 0.32,
        "5. Kết thúc phiên học\nHết giờ (báo loa đúng 1 lần) hoặc bấm Dừng\n→ Tắt Pose/Phone AI, xóa sạch bộ đếm",
        fc=C_AMBER_L, ec=C_AMBER, fs=11.3, weight="bold",
    )
    _arrow(ax, (0.835, 0.60), (0.835, 0.485), color=C_GREEN, lw=2.2)
    _arrow(ax, (0.518, 0.32), (0.462, 0.32), color=C_AMBER, lw=2.2)

    ax.text(
        0.50, 0.055,
        "Cổng hai lớp: Chỉ phát cảnh báo khi (StudySession đang mở) VÀ (nằm trong lịch học schedule).",
        ha="center", va="center", fontsize=11.2, fontweight="bold", color=C_RED,
        bbox=dict(boxstyle="round,pad=0.38", fc=C_RED_L, ec=C_RED, lw=1.2),
    )

    _save(fig, "06-luong-su-dung-web.png")


# ============================================================ 7. Sơ đồ đấu dây GPIO
def fig_wiring() -> None:
    fig, ax = _blank((8.2, 5.8))

    _box(
        ax, 0.02, 0.14, 0.31, 0.82,
        "Raspberry Pi 4\nHàng rào 40 chân\n(Logic 3,3 V)\n\n"
        "Thư viện: gpiozero\n(+ MockFactory)\n\n"
        "CẢNH BÁO ĐIỆN ÁP:\nChân ECHO là 5 V,\nbắt buộc chia áp\n1 kΩ + 2 kΩ!",
        fc=C_GREEN_L, ec=C_GREEN, fs=11.4, weight="bold",
    )

    pins = [
        ("GPIO 17", "LED Xanh (GOOD) · nối trở 220–330 Ω", C_GREEN, 0.84),
        ("GPIO 27", "LED Vàng (WARN) · nối trở 220–330 Ω", C_AMBER, 0.70),
        ("GPIO 22", "LED Đỏ (BAD) · nối trở 220–330 Ω", C_RED, 0.56),
        ("GPIO 18", "Còi Buzzer chủ động (qua NPN)", C_GREY, 0.42),
        ("GPIO 23", "Mô-tơ rung (NPN + diode chống ngược)", C_GREY, 0.28),
        ("GPIO 5 · 6", "Siêu âm HC-SR04 (Chia áp ECHO 5V→3,3V)", C_BLUE, 0.14),
    ]
    for pin, desc, color, y in pins:
        _box(ax, 0.39, y, 0.16, 0.105, pin, fc="white", ec=color, fs=11.2, weight="bold", lw=1.8, color=color)
        _box(ax, 0.565, y, 0.415, 0.105, desc, fc=C_BAND, ec=color, fs=10.8, weight="bold")
        _arrow(ax, (0.332, 0.55), (0.388, y + 0.052), color=color, lw=1.7)

    ax.text(
        0.50, 0.045,
        "Ghi chú: Loa tích hợp trên Camera IP (RTSP Backchannel) là kênh âm thanh chính; cụm GPIO là kênh phụ trợ.",
        ha="center", va="center", fontsize=10.8, fontweight="bold", color=C_GREY,
    )

    _save(fig, "07-so-do-dau-day.png")


# ============================================================ 8. Bản đồ phân hệ (Lưới 2x2 chữ cực rõ)
def fig_modules() -> None:
    fig, ax = _blank((8.2, 5.8))

    cards = [
        (
            0.02, 0.52, C_GREEN, C_GREEN_L,
            "1. TẦNG NỀN TẢNG & THỊ GIÁC AI",
            "• core/: config, labels, atomic_io,\n  credentials (che mật khẩu), log_buffer\n"
            "• vision/: yolo_loader (NCNN→ONNX→PT),\n  pose, phone_detector, phone, faces,\n  features, classifier, overlay",
        ),
        (
            0.51, 0.52, C_BLUE, C_BLUE_L,
            "2. NGHIỆP VỤ MIỀN & WEB BACKEND",
            "• domain/: presence, study_session,\n  schedule, state, enrollment,\n  signal_board, people_service\n"
            "• web/: app, context, DashboardState,\n  streaming, privacy, 5 mô-đun routes/*",
        ),
        (
            0.02, 0.03, C_AMBER, C_AMBER_L,
            "3. CAMERA, PHẦN CỨNG & LƯU TRỮ",
            "• camera/: capture (RTSP), control (PTZ),\n  audio (RTP/PCMA 8 kHz backchannel)\n"
            "• alerts/: speaker_alert, espeak_synth,\n  voice_library, gpio_dispatcher\n"
            "• hardware/ (gpiozero) · storage/ (SQLite)",
        ),
        (
            0.51, 0.03, C_GREY, C_GREY_L,
            "4. LẮP RÁP CLI, MOBILE & KIỂM THỬ",
            "• cli/: parser, monitor_runner, cmd_*,\n  benchmark/ (3 hồ sơ đo hiệu năng)\n"
            "• apps/mobile/: Expo SDK 58 (6 tab)\n"
            "• tests/: 10 thư mục, 60 tệp (1.662 bài)\n  + Mobile test/ (189 bài Node & UI)",
        ),
    ]

    for x, y, ec, fc, head, body in cards:
        w, h = 0.47, 0.45
        _box(ax, x, y, w, h, "", fc=fc, ec=ec, lw=1.8)
        ax.text(x + w / 2, y + h - 0.055, head, ha="center", va="center",
                fontsize=12.0, fontweight="bold", color=ec, zorder=4)
        ax.text(x + 0.025, y + (h - 0.08) / 2, body, ha="left", va="center",
                fontsize=10.8, fontweight="bold", color=C_INK, linespacing=1.45, zorder=4)

    _save(fig, "08-ban-do-module.png")


# ============================================================ 11. Bố cục & Kiến trúc App di động
def fig_mobile_stitch() -> None:
    fig, ax = _blank((8.2, 8.6))

    # Cột trái: Màn hình điện thoại Nocturne Telemetry (rộng 47%)
    px, py, pw, ph = 0.015, 0.02, 0.475, 0.96
    _box(ax, px, py, pw, ph, "", fc="#0f141a", ec="#334155", lw=2.2)

    ax.text(px + 0.025, py + ph - 0.045, "Camera & Trạng thái",
            ha="left", va="center", fontsize=12.2, fontweight="bold", color="#f8fafc", zorder=4)
    _box(ax, px + pw - 0.145, py + ph - 0.068, 0.125, 0.045, "● LIVE",
         fc="#1b222b", ec="#34d399", fs=10.5, weight="bold", color="#34d399", zorder=4)

    # Khối 1: Khung Camera 4:3
    cy = py + ph - 0.285
    _box(
        ax, px + 0.02, cy, pw - 0.04, 0.195,
        "Khung Camera 4:3\n[Trực tiếp: /stream] | [Tĩnh: /api/frame]\n■ Luồng MJPEG trực tiếp · 0,2 s",
        fc="#171c22", ec="#60a5fa", fs=10.6, weight="bold", color="#e2e8f0", zorder=4,
    )

    # Khối 2: Cụm 3 Tín hiệu người học Bento 2+1
    sy = cy - 0.285
    _box(ax, px + 0.02, sy, pw - 0.04, 0.265, "", fc="#1b222b", ec="#34d399", lw=1.8, zorder=4)
    ax.text(px + 0.032, sy + 0.235, "● 3 TÍN HIỆU NGƯỜI HỌC (DƯỚI CAMERA)",
            ha="left", va="center", fontsize=10.2, fontweight="bold", color="#34d399", zorder=5)

    hw = (pw - 0.07) / 2
    _box(ax, px + 0.03, sy + 0.112, hw, 0.095, "CÓ MẶT\n● Trong khung",
         fc="#171c22", ec="#334155", fs=10.4, weight="bold", color="#34d399", zorder=5)
    _box(ax, px + 0.04 + hw, sy + 0.112, hw, 0.095, "ĐIỆN THOẠI\n○ Không dùng",
         fc="#171c22", ec="#334155", fs=10.4, weight="bold", color="#34d399", zorder=5)
    _box(ax, px + 0.03, sy + 0.015, pw - 0.06, 0.082,
         "NGƯỜI HỌC: Đúng người (Bảo) [Mới]",
         fc="#171c22", ec="#334155", fs=10.5, weight="bold", color="#34d399", zorder=5)

    # Khối 3: Trạng thái tư thế Bento 2x2
    by = sy - 0.285
    _box(ax, px + 0.02, by, pw - 0.04, 0.265, "", fc="#1b222b", ec="#475569", lw=1.4, zorder=4)
    ax.text(px + 0.032, by + 0.235, "● TRẠNG THÁI: Tư thế tốt (Đúng tư thế)",
            ha="left", va="center", fontsize=10.2, fontweight="bold", color="#34d399", zorder=5)
    _box(ax, px + 0.03, by + 0.115, hw, 0.092, "ĐIỂM TƯ THẾ\n91,5 / 100",
         fc="#171c22", ec="#334155", fs=10.2, weight="bold", color="#f8fafc", zorder=5)
    _box(ax, px + 0.04 + hw, by + 0.115, hw, 0.092, "ĐÃ NGỒI\n42 phút",
         fc="#171c22", ec="#334155", fs=10.2, weight="bold", color="#f8fafc", zorder=5)
    _box(ax, px + 0.03, by + 0.014, hw, 0.088, "KHOẢNG CÁCH\n54 cm",
         fc="#171c22", ec="#334155", fs=10.2, weight="bold", color="#60a5fa", zorder=5)
    _box(ax, px + 0.04 + hw, by + 0.014, hw, 0.088, "LOA CẢNH BÁO\n● Đang bật",
         fc="#171c22", ec="#34d399", fs=10.2, weight="bold", color="#34d399", zorder=5)

    # Thanh 6 tab dưới đáy
    _box(
        ax, px + 0.018, py + 0.015, pw - 0.036, 0.085,
        "Thanh 6 Tab điều hướng:\n[Camera*] · Phiên · Đ.Khiển · Giọng · Vi phạm · Kết nối",
        fc="#0b0f14", ec="#60a5fa", fs=9.8, weight="bold", color="#60a5fa", zorder=5,
    )

    # Cột phải: 4 khối kiến trúc lớn (rộng 45.5%)
    rx, rw = 0.53, 0.455
    _box(
        ax, rx, 0.755, rw, 0.215,
        "1. Quản lý vòng đời (src/hooks/)\n"
        "• usePoll: hỏi mỗi 2 s, tự gọi\n  AbortController.abort() khi rời tab\n"
        "• useAsyncAction: hủy lệnh chồng",
        fc=C_BLUE_L, ec=C_BLUE, fs=10.8, weight="bold",
    )
    _box(
        ax, rx, 0.505, rw, 0.215,
        "2. Tầng API thuần (src/api/)\n"
        "• Không phụ thuộc react-native\n"
        "• fresh=false → 'Chưa có dữ liệu mới'\n"
        "• Hạn chờ JSON 5 s, ảnh tĩnh 10 s",
        fc=C_GREEN_L, ec=C_GREEN, fs=10.8, weight="bold",
    )
    _box(
        ax, rx, 0.255, rw, 0.215,
        "3. Máy chủ Pi 4 (Flask :8000)\n"
        "• Dùng chung 10 route với Web\n"
        "• Thêm /api/frame (JPEG tĩnh)\n  & /api/violations (lịch sử lỗi)",
        fc=C_AMBER_L, ec=C_AMBER, fs=10.8, weight="bold",
    )
    _box(
        ax, rx, 0.02, rw, 0.20,
        "4. Kiểm thử 2 tầng (189 bài PASS)\n"
        "• 160 bài logic thuần (Node ≥ 22.18)\n"
        "• 29 bài giao diện thật (jsdom)\n"
        "• tsc --noEmit: 0 lỗi kiểu tĩnh",
        fc=C_GREY_L, ec=C_GREY, fs=10.8, weight="bold",
    )

    _arrow(ax, (px + pw + 0.004, 0.86), (rx - 0.004, 0.86), color=C_BLUE, lw=2.2)
    _arrow(ax, (rx + rw / 2, 0.755), (rx + rw / 2, 0.722), color=C_GREEN, lw=2.0)
    _arrow(ax, (rx + rw / 2, 0.505), (rx + rw / 2, 0.472), color=C_AMBER, lw=2.0)

    _save(fig, "11-bo-cuc-app-di-dong.png")


def main() -> int:
    print("Sinh lại bộ 9 hình cỡ chữ lớn chuẩn in A4 vào", FIG)
    for fn in (
        fig_architecture,
        fig_ai_pipeline,
        fig_time_budget,
        fig_fps_runs,
        fig_web,
        fig_web_flow,
        fig_wiring,
        fig_modules,
        fig_mobile_stitch,
    ):
        fn()
    print("Xong.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
