"""Bộ phân tích đối số dòng lệnh cho ``python -m posture_monitor <lệnh>``."""

from __future__ import annotations

import argparse

from .. import __version__
from ..core.labels import VOICES

#: Tên cửa sổ xem trước của OpenCV.
WINDOW_NAME = "Giam sat hoc tap — bam q de thoat"

#: Phím thoát (mã ASCII của ``q`` và ``Esc``).
QUIT_KEYS = (ord("q"), ord("Q"), 27)

#: Số khung tối đa đọc khi chờ có người cho ``--save-overlay``.
SAVE_OVERLAY_MAX_FRAMES = 10

#: Ba câu cảnh báo mà ``speak-test`` phát thử, **đúng thứ tự** đọc ra loa.
SPEAK_TEST_KINDS = ("leave_frame", "phone", "stranger")

#: Nghỉ giữa hai câu khi phát thử để loa camera không cắt cụt câu trước.
SPEAK_TEST_GAP_S = 0.6


def build_parser() -> argparse.ArgumentParser:
    """Dựng parser cho toàn bộ CLI."""
    parser = argparse.ArgumentParser(
        prog="posture_monitor",
        description="Hệ thống giám sát tư thế học tập trên Raspberry Pi 4.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"posture_monitor {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Chạy giám sát trực tiếp từ camera.")
    run.add_argument(
        "--config",
        default="config.yaml",
        help="Đường dẫn file cấu hình (mặc định: config.yaml).",
    )
    run.add_argument(
        "--no-gpio",
        action="store_true",
        help="Không dùng GPIO thật; dùng phần cứng giả lập.",
    )
    run.add_argument(
        "--view",
        choices=("front", "side"),
        default=None,
        help="Ghi đè góc đặt camera trong cấu hình.",
    )
    run.add_argument(
        "--save-overlay",
        default=None,
        metavar="DUONG_DAN",
        help=(
            "Lưu một khung đã vẽ ra file ảnh rồi thoát (dùng để kiểm chứng "
            "khi không có màn hình). Ví dụ: --save-overlay frame.jpg"
        ),
    )
    run.add_argument(
        "--fps",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Ghi đè 'model.target_fps' (mặc định 5). Đo trên laptop: nguồn "
            "RTSP đọc nền chịu được tới ~15 FPS; tăng lên để xem mượt hơn, "
            "hạ xuống nếu CPU yếu."
        ),
    )
    run.add_argument(
        "--preview",
        action="store_true",
        help=(
            "Mở cửa sổ xem trước của OpenCV. MẶC ĐỊNH KHÔNG MỞ: hình đã có "
            "trên dashboard web, còn cửa sổ thì cần màn hình thật (trên Pi qua "
            "xrdp nó ném lỗi Qt) và mỗi khung phải vẽ lại cùng xử lý sự kiện "
            "cửa sổ. Chỉ thêm cờ này khi ngồi ngay máy có màn hình."
        ),
    )
    run.add_argument(
        "--no-preview",
        action="store_true",
        help=(
            "Giữ cho tương thích: không mở cửa sổ xem trước. Đây đã là mặc "
            "định, nên cờ này không cần thiết nữa."
        ),
    )
    run.add_argument(
        "--log-level",
        default="INFO",
        help="Mức log: DEBUG, INFO, WARNING, ERROR (mặc định: INFO).",
    )

    calibrate = subparsers.add_parser(
        "calibrate",
        help="Hiệu chỉnh tư thế chuẩn và lưu baseline (calibration.json).",
    )
    from ..vision.calibration import DEFAULT_PATH  # noqa: PLC0415

    calibrate.add_argument(
        "--config",
        default="config.yaml",
        help="Đường dẫn file cấu hình (mặc định: config.yaml).",
    )
    calibrate.add_argument(
        "--output",
        default=DEFAULT_PATH,
        metavar="DUONG_DAN",
        help=f"File baseline ghi ra (mặc định: {DEFAULT_PATH}).",
    )
    calibrate.add_argument(
        "--no-gpio",
        action="store_true",
        help=(
            "Chấp nhận cho đồng bộ với 'run'; calibrate không dùng GPIO nên "
            "cờ này là no-op."
        ),
    )
    calibrate.add_argument(
        "--log-level",
        default="INFO",
        help="Mức log: DEBUG, INFO, WARNING, ERROR (mặc định: INFO).",
    )

    replay = subparsers.add_parser(
        "replay", help="Chạy lại trên video có sẵn và xuất báo cáo JSON."
    )
    replay.add_argument("video", help="Đường dẫn video (mp4/avi/mkv).")
    replay.add_argument(
        "--config",
        default="config.yaml",
        help="Đường dẫn file cấu hình (mặc định: config.yaml).",
    )
    replay.add_argument(
        "--no-gpio",
        action="store_true",
        help="Tương thích CLI chung; replay không dùng GPIO.",
    )
    replay.add_argument(
        "--save-report",
        default=None,
        metavar="DUONG_DAN",
        help="Ghi báo cáo JSON (UTF-8) ra file. Ví dụ: --save-report out.json",
    )
    replay.add_argument(
        "--log-level",
        default="INFO",
        help="Mức log: DEBUG, INFO, WARNING, ERROR (mặc định: INFO).",
    )

    benchmark = subparsers.add_parser(
        "benchmark", help="Đo hiệu năng trên máy đích (spec §8)."
    )
    benchmark.add_argument(
        "--seconds",
        type=float,
        default=60.0,
        help="Thời lượng đo, giây (mặc định: 60).",
    )
    benchmark.add_argument(
        "--config",
        default="config.yaml",
        help="Đường dẫn file cấu hình (mặc định: config.yaml).",
    )
    benchmark.add_argument(
        "--source",
        default=None,
        metavar="NGUON",
        help=(
            "Ghi đè nguồn ảnh: usb:0 | picamera | file:anh.jpg | "
            "file:video.mp4. Trên Pi chưa có camera, dùng ảnh tĩnh."
        ),
    )
    benchmark.add_argument(
        "--json",
        default=None,
        metavar="DUONG_DAN",
        help="Ghi báo cáo JSON ra file (ngoài bảng in trên màn hình).",
    )
    benchmark.add_argument(
        "--profile",
        default=None,
        metavar="HO_SO",
        help=(
            "Hồ sơ đo: pose (mặc định) | pose_phone | pose_phone_face. "
            "Hồ sơ cần module/cấu hình chưa có sẽ bị từ chối rõ ràng, không "
            "đo thiếu model."
        ),
    )
    benchmark.add_argument(
        "--no-gpio",
        action="store_true",
        help="Tương thích CLI chung; benchmark không dùng GPIO.",
    )
    benchmark.add_argument(
        "--log-level",
        default="INFO",
        help="Mức log: DEBUG, INFO, WARNING, ERROR (mặc định: INFO).",
    )

    speak_test = subparsers.add_parser(
        "speak-test",
        help="Phát thử giọng đọc ra loa camera rồi thoát (không mở camera).",
        description=(
            "Phát thử câu cảnh báo ra loa của camera IP qua RTSP backchannel. "
            "Lệnh này KHÔNG mở luồng hình, KHÔNG đụng GPIO và KHÔNG ghi DB, "
            "nên chạy được trong lúc 'run' đang chạy — miễn là loa rảnh. "
            "Dùng để kiểm tra âm thanh thật sự ra loa trước khi trình diễn."
        ),
    )
    speak_test.add_argument(
        "--config",
        default="config.yaml",
        help="Đường dẫn file cấu hình (mặc định: config.yaml).",
    )
    speak_test.add_argument(
        "--kind",
        choices=(*SPEAK_TEST_KINDS, "all"),
        default="all",
        help=(
            "Câu cần phát thử; 'all' (mặc định) phát lần lượt cả ba câu để "
            "nghe được câu nào còn thiếu bản thu."
        ),
    )
    speak_test.add_argument(
        "--voice",
        choices=VOICES,
        default=None,
        help=(
            "Ghi đè giọng cho riêng lần thử này (nam | nu | espeak). "
            "KHÔNG lưu vào data/audio/voice.json — lựa chọn trên dashboard "
            "giữ nguyên."
        ),
    )
    speak_test.add_argument(
        "--volume",
        type=float,
        default=None,
        metavar="0..1",
        help=(
            "Âm lượng gửi ra loa cho riêng lần thử này (mặc định lấy "
            "'speaker_alert.volume'). Hạ xuống 0.6–0.7 nếu loa nhỏ bị rè."
        ),
    )
    speak_test.add_argument(
        "--speed",
        type=float,
        default=None,
        metavar="0.5..1.0",
        help=(
            "Tốc độ đọc cho riêng lần thử này (mặc định lấy "
            "'speaker_alert.speed', thường là 0.9 = chậm lại 10 %%). Chậm hơn "
            "thì giữ nguyên cao độ, không làm giọng trầm."
        ),
    )
    speak_test.add_argument(
        "--tone",
        action="store_true",
        help=(
            "Phát tiếng bíp thay vì câu nói. Đường này KHÔNG cần ffmpeg và "
            "không cần bản thu, nên dùng để tách 'loa không nhận backchannel' "
            "khỏi 'file giọng đọc hỏng'."
        ),
    )
    speak_test.add_argument(
        "--list",
        action="store_true",
        help="Chỉ liệt kê giọng/câu đang có rồi thoát, không phát gì.",
    )
    speak_test.add_argument(
        "--log-level",
        default="INFO",
        help="Mức log: DEBUG, INFO, WARNING, ERROR (mặc định: INFO).",
    )

    return parser
