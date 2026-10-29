"""Lọc nhãn tư thế khỏi cảnh báo, giữ ``ABSENT``.

Chủ đề sản phẩm đã đổi sang theo dõi người học, không chấm điểm tư thế.
Nhưng ``classify()`` vẫn sinh nhãn tư thế (``HEAD_DOWN``, ``LEAN``,
``LOOK_AWAY``, ...) và chúng vẫn chạy qua máy trạng thái tới GPIO. Hai công
tắc mới trong cấu hình cắt đường đó:

- ``posture_labels_enabled`` (mặc định ``false``): nhãn tư thế vẫn được tính
  nhưng bị bỏ khỏi tập nhãn đi tiếp, nên không sinh cảnh báo.
- ``alerts.gpio_alert_enabled`` (mặc định ``false``): kêu/rung bị chặn.

``ABSENT`` phải **luôn** còn lại: cảnh báo "đi ra khỏi khung hình" phụ thuộc
vào nó. Bài ``test_absent_khong_bi_loc`` là bài bảo vệ yêu cầu đó.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.__main__ import _loc_nhan_tu_the  # noqa: E402
from posture_monitor.classifier import (  # noqa: E402
    ABSENT,
    BAD_LABELS,
    HEAD_DOWN,
    LEAN,
)
from posture_monitor.config import Config  # noqa: E402

_CONFIG_YAML = _REPO_ROOT / "config.yaml"

#: Toàn bộ nhãn tư thế (mọi nhãn xấu trừ ``ABSENT``).
_NHAN_TU_THE = frozenset(BAD_LABELS) - {ABSENT}


def test_mac_dinh_loc_het_nhan_tu_the() -> None:
    """Với config mặc định, mọi nhãn tư thế bị bỏ, tập nhãn còn rỗng."""
    assert _NHAN_TU_THE, "BAD_LABELS phải có nhãn tư thế để bài này có nghĩa"

    ket_qua = _loc_nhan_tu_the(_NHAN_TU_THE, Config().posture_labels_enabled)

    assert ket_qua == frozenset(), (
        f"Còn nhãn tư thế lọt qua bộ lọc: {sorted(ket_qua)} — nhãn tư thế "
        "không được sinh cảnh báo ở chế độ mặc định."
    )


def test_absent_khong_bi_loc() -> None:
    """``ABSENT`` sống sót qua bộ lọc, một mình hay lẫn với nhãn tư thế."""
    enabled = Config().posture_labels_enabled

    assert _loc_nhan_tu_the({ABSENT}, enabled) == frozenset({ABSENT}), (
        "ABSENT bị lọc mất — cảnh báo 'đi ra khỏi khung hình' không còn "
        "đường sinh ra."
    )

    ket_qua = _loc_nhan_tu_the({ABSENT, HEAD_DOWN}, enabled)
    assert ket_qua == frozenset({ABSENT}), (
        f"Kỳ vọng chỉ còn ABSENT, nhận được {sorted(ket_qua)}."
    )


def test_bat_posture_labels_thi_giu_nguyen() -> None:
    """Bật ``posture_labels_enabled`` thì tập nhãn không đổi."""
    dau_vao = frozenset({ABSENT, HEAD_DOWN, LEAN})

    ket_qua = _loc_nhan_tu_the(dau_vao, True)

    assert ket_qua == dau_vao


def test_gpio_alert_tat_theo_mac_dinh() -> None:
    """Hai nguồn đều tắt: dataclass ``Config()`` và ``config.yaml`` thật."""
    mac_dinh = Config()
    assert mac_dinh.alerts.gpio_alert_enabled is False
    assert mac_dinh.posture_labels_enabled is False

    assert _CONFIG_YAML.is_file(), f"thiếu file cần kiểm: {_CONFIG_YAML}"
    raw = yaml.safe_load(_CONFIG_YAML.read_text(encoding="utf-8"))

    assert "gpio_alert_enabled" in raw["alerts"], (
        "config.yaml thiếu khóa alerts.gpio_alert_enabled"
    )
    assert raw["alerts"]["gpio_alert_enabled"] is False, (
        "config.yaml phải để alerts.gpio_alert_enabled: false theo mặc định"
    )

    assert "posture_labels_enabled" in raw, (
        "config.yaml thiếu khóa cấp ngoài cùng posture_labels_enabled"
    )
    assert raw["posture_labels_enabled"] is False, (
        "config.yaml phải để posture_labels_enabled: false theo mặc định"
    )
