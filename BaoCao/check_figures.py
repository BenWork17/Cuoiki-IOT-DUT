# -*- coding: utf-8 -*-
"""Kiểm tra kích thước hình khi đặt vào trang A4 chuẩn Khoa CNTT - ĐHBK Đà Nẵng.

Khổ giấy A4 (21,0 x 29,7 cm) với lề trái 3,5 cm, phải 2,0 cm, trên 2,5 cm, dưới 2,5 cm
cho vùng in 15,5 x 24,7 cm.
Quy tắc dùng chung với ``make_docx.add_image``:
- Rộng tối đa: 15,0 cm
- Cao tối đa: 19,0 cm (chừa chỗ cho chú thích Hình 13 pt Bold Italic bên dưới).

Chạy:  python BaoCao/check_figures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"

MAX_W_CM = 15.5
MAX_H_CM = 19.2


def fit(width_px: int, height_px: int) -> tuple[float, float, str]:
    """Trả (rộng_cm, cao_cm, cách_đặt) đúng như ``make_docx.add_image``."""
    aspect = width_px / height_px if height_px else 1.0
    width_cm, height_cm = MAX_W_CM, MAX_W_CM / aspect
    mode = "theo chiều rộng"
    if height_cm > MAX_H_CM:
        height_cm = MAX_H_CM
        width_cm = height_cm * aspect
        mode = "thu theo chiều cao"
    return width_cm, height_cm, mode


def main() -> int:
    print(f"Khung đặt hình chuẩn DUT: rộng ≤ {MAX_W_CM:.1f} cm · cao ≤ {MAX_H_CM:.1f} cm\n")
    header = f"{'hình':34s} {'pixel':>13s} {'đặt (cm)':>15s} {'tỉ lệ':>7s}  cách đặt"
    print(header)
    print("-" * len(header))

    problems = 0
    files = sorted(list(FIG.glob("*.png")) + list(FIG.glob("*.jpg")))
    for path in files:
        with Image.open(path) as img:
            width_px, height_px = img.size
        if path.name.startswith("logo-"):
            print(
                f"{path.name:34s} {width_px:5d}x{height_px:<7d} "
                f"{2.30:6.2f} x {2.30 / (width_px / height_px):6.2f} {width_px / height_px:7.2f}  logo trang bìa"
            )
            continue
        width_cm, height_cm, mode = fit(width_px, height_px)
        if width_cm > MAX_W_CM + 0.01 or height_cm > MAX_H_CM + 0.01:
            problems += 1
            mode = "VƯỢT KHUNG"
        print(
            f"{path.name:34s} {width_px:5d}x{height_px:<7d} "
            f"{width_cm:6.2f} x {height_cm:6.2f} {width_px / height_px:7.2f}  {mode}"
        )

    print()
    print("KẾT LUẬN:", "OK - mọi hình và logo nằm gọn trong vùng in A4 chuẩn DUT" if problems == 0 else "CẦN SỬA")
    return 0 if problems == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
