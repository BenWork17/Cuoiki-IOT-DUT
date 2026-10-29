"""Dashboard web trong mạng LAN (spec v2 §5.10).

Gói này **tách rời hoàn toàn khỏi vòng lặp camera**: nó không mở camera, không
suy luận pose, không đụng GPIO. Mọi dữ liệu đi qua :class:`DashboardState` —
một đối tượng trạng thái trong bộ nhớ do vòng lặp chính cập nhật và Flask đọc
lại. Nhờ vậy unit test chạy được trên PC mà không cần thiết bị nào.

Cách nối vào CLI (Peer nối dây dùng)::

    from posture_monitor.web import DashboardState, create_app, run_server

    state = DashboardState()
    storage.open()
    app = create_app(config, state=state, storage=storage)
    # ... chạy app trong một thread riêng, rồi trong vòng lặp chính:
    state.update(state="GOOD", labels=["GOOD"], score=100.0, sitting_s=12.0,
                 distance_cm=42.0)
    if state.consume_calibration_request():
        ...  # chạy hiệu chỉnh lại
    muted = state.muted   # vòng lặp tự tắt tiếng theo giá trị này

Không mở cổng ra Internet: ``web.host`` mặc định ``0.0.0.0`` chỉ để xem từ
điện thoại trong cùng LAN; router không được forward cổng này (xem
``docs/WEB_DASHBOARD.md``).
"""

from __future__ import annotations

from .app import DashboardState, create_app, run_server
from .people_service import ENROLL_STEPS, PeopleService, PeopleServiceError

__all__ = [
    "DashboardState",
    "ENROLL_STEPS",
    "PeopleService",
    "PeopleServiceError",
    "create_app",
    "run_server",
]
