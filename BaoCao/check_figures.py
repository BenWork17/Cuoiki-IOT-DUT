# -*- coding: utf-8 -*-
"""Kiểm tra kích thước hình khi đặt vào trang A4 của báo cáo.

Quy tắc dùng **chung một nguồn** với ``make_docx.add_image``:
rộng tối đa 16 cm, cao tối đa 22,5 cm (chừa chỗ cho chú thích).
Ảnh nào vượt chiều cao sẽ được thu theo chiều cao, không theo chiều rộng —
nhờ vậy ảnh dọc của điện thoại không tràn trang.

Chạy:  python BaoCao/check_figures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"

MAX_W_CM = 16.0
MAX_H_CM = 22.5


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
    print(f"Khung đặt hình: rộng ≤ {MAX_W_CM:.1f} cm · cao ≤ {MAX_H_CM:.1f} cm\n")
    header = f"{'hình':34s} {'pixel':>13s} {'đặt (cm)':>15s} {'tỉ lệ':>7s}  cách đặt"
    print(header)
    print("-" * len(header))

    problems = 0
    for path in sorted(FIG.glob("*.png")):
        with Image.open(path) as img:
            width_px, height_px = img.size
        width_cm, height_cm, mode = fit(width_px, height_px)
        if width_cm > MAX_W_CM + 0.01 or height_cm > MAX_H_CM + 0.01:
            problems += 1
            mode = "VƯỢT KHUNG"
        print(
            f"{path.name:34s} {width_px:5d}x{height_px:<7d} "
            f"{width_cm:6.2f} x {height_cm:6.2f} {width_px / height_px:7.2f}  {mode}"
        )

    print()
    print("KẾT LUẬN:", "OK — mọi hình nằm trong vùng in" if problems == 0 else "CẦN SỬA")
    return 0 if problems == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
