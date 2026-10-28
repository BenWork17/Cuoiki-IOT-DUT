"""Dò camera: in bảng các node /dev/video*, trạng thái Pi Camera và gợi ý cấu hình.

Chạy được trên cả PC và Raspberry Pi::

    python scripts/camera_probe.py

Mã thoát:

- ``0`` nếu tìm thấy ít nhất một nguồn ảnh dùng được (USB hoặc Pi Camera).
- ``1`` nếu không có nguồn nào.

Script này chỉ đọc thông tin thiết bị, không ghi file và không mở luồng ảnh
kéo dài.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Cho phép chạy trực tiếp bằng `python scripts/camera_probe.py` mà không cần
# cài gói: thêm thư mục src/ vào sys.path.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.capture import (  # noqa: E402
    _is_linux,  # noqa: PLC2701 - script chẩn đoán cần biết nền tảng
    list_capture_devices,
    probe_cameras,
)


def _print_header() -> None:
    print()
    print("=" * 74)
    print("  DÒ CAMERA — Hệ thống giám sát tư thế")
    print("=" * 74)
    print(f"  Nền tảng: {'Linux' if _is_linux() else sys.platform}")
    print()


def _print_devices(devices) -> int:
    """In bảng node /dev/video*; trả số node capture dùng được."""
    print("  Các node /dev/video*:")
    if not devices:
        if _is_linux():
            print("    (không có node nào)")
        else:
            print("    (không có /dev/video* trên hệ điều hành này — "
                  "xem mục Camera USB bên dưới)")
        print()
        return 0

    print(f"    {'Node':<16} {'Driver':<20} {'Tên thiết bị':<28} Kết luận")
    print("    " + "-" * 70)
    usable = 0
    for device in devices:
        verdict = "CAMERA" if device.is_capture else "bỏ qua (codec/ISP)"
        if device.is_capture:
            usable += 1
        print(
            f"    {f'/dev/video{device.index}':<16} "
            f"{device.driver_name[:19]:<20} "
            f"{device.card_name[:27]:<28} {verdict}"
        )
    print()
    return usable


def _print_picamera(result: dict) -> bool:
    available = bool(result.get("available"))
    reason = result.get("reason", "")
    print("  Pi Camera (picamera2):")
    if available:
        print(f"    CÓ SẴN — {reason}")
    else:
        print(f"    KHÔNG CÓ — {reason}")
    print()
    return available


def _device_label(index: int) -> str:
    """Nhãn thiết bị phù hợp nền tảng: ``/dev/videoN`` trên Linux, ``camera N`` trên PC."""
    return f"/dev/video{index}" if _is_linux() else f"camera {index}"


def _print_usb(result: list[dict]) -> int:
    usable = [item for item in result if item.get("available")]
    print("  Camera USB (UVC):")
    if not usable:
        print("    KHÔNG CÓ — không có node capture nào")
    else:
        for item in usable:
            print(
                f"    CÓ SẴN — {_device_label(item['index'])} "
                f"({item['name']})"
            )
    print()
    return len(usable)


def _print_recommendation(usb: list[dict], picamera: bool) -> None:
    print("  Đề xuất cấu hình (mục camera.source trong config.yaml):")
    if usb:
        first = usb[0]
        print(f"    camera.source: usb:{first['index']}   # {first['name']}")
        if picamera:
            print("    (Pi Camera cũng dùng được: camera.source: picamera)")
    elif picamera:
        print("    camera.source: picamera")
    else:
        print("    Chưa có nguồn ảnh. Kiểm tra:")
        if _is_linux():
            print("      - Cáp CSI đã cắm chắc chưa (Pi Camera)")
            print("      - camera_auto_detect=1 trong /boot/firmware/config.txt")
            print("      - Cắm lại webcam USB rồi chạy: lsusb")
        else:
            print("      - Đây là PC: dùng file:duong_dan.mp4 để thử pipeline")
            print("      - Hoặc cắm webcam USB rồi chạy lại script này")
    print()


def main() -> int:
    _print_header()

    devices = list_capture_devices(probe_opencv=True)
    usable_nodes = _print_devices(devices)
    result = probe_cameras()
    picamera_ok = _print_picamera(result.get("picamera", {}))
    usb_ok = _print_usb(result.get("usb", []))

    _print_recommendation(result.get("usb", []), picamera_ok)

    total = max(usable_nodes, usb_ok)
    if total or picamera_ok:
        print(f"  KẾT LUẬN: tìm thấy nguồn ảnh dùng được "
              f"({total} camera USB, Pi Camera={'có' if picamera_ok else 'không'}).")
        print("=" * 74)
        print()
        return 0

    print("  KẾT LUẬN: KHÔNG tìm thấy nguồn ảnh nào.")
    print("=" * 74)
    print()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
