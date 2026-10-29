"""Hợp đồng dịch vụ "người học" cho dashboard (spec v3 §5.13, §5.16).

Lớp web **không** tự nhận diện khuôn mặt, không mở camera và không đụng vào
CSDL: nó chỉ gọi một đối tượng tiêm được theo đúng :class:`PeopleService` bên
dưới. Nhờ vậy route và giao diện test được trên PC bằng một bản giả, còn phần
thu mẫu/SFace nằm ở module khác.

Quyền riêng tư là một phần của hợp đồng, không phải lời hứa suông: danh sách
người học chỉ có ``id``, ``name``, ``created_ts``. **Không** phương thức nào
trả embedding/vector ra ngoài (spec §5.13.1, §8.3).

Lỗi nghiệp vụ (tên rỗng, không tìm thấy người, huỷ phiên đã xong…) phải là
:class:`PeopleServiceError` — lớp web đổi thành HTTP 400. Mọi lỗi khác được
coi là sự cố hệ thống và đổi thành 503, không lộ traceback ra client.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

#: Lỗi nghiệp vụ **thật** của dịch vụ người học, dùng lại chứ không định nghĩa
#: lớp thứ hai. Hai lớp cùng tên là cách chắc chắn nhất để ``except`` bên web
#: không bao giờ khớp lỗi dịch vụ thật ném ra — và biến 400 thành 503.
from ..people_service import PeopleServiceError  # noqa: F401  re-export

#: Năm bước hướng dẫn đăng ký, đúng thứ tự spec §5.13 và §3.4:
#: nhìn thẳng → quay phải → quay trái → ngẩng → cúi. Bản thật phát đúng
#: chuỗi này ra loa camera lẫn màn hình, nên chuỗi phải khớp từng chữ.
ENROLL_STEPS: tuple[str, ...] = (
    "Nhìn thẳng",
    "Quay sang phải",
    "Quay sang trái",
    "Ngẩng lên",
    "Cúi xuống",
)


@runtime_checkable
class PeopleService(Protocol):
    """Dịch vụ người học mà :func:`posture_monitor.web.create_app` cần.

    Bản thật (thu mẫu bằng YuNet/SFace + CSDL) do module khác cung cấp. Bản
    giả trong test chỉ cần đúng các phương thức dưới đây.
    """

    def list_people(self) -> list[dict]:
        """``[{"id": str, "name": str, "created_ts": float}]`` — **không** có embedding."""

    def start_enroll(self, name: str) -> dict:
        """Mở phiên đăng ký mới.

        Returns:
            ``{"enroll_id": str, "steps": [str, ...]}``, ``steps`` là năm câu
            hướng dẫn tiếng Việt của :data:`ENROLL_STEPS`.
        """

    def enroll_status(self, enroll_id: str) -> dict:
        """Tiến độ một phiên đăng ký.

        Returns:
            ``{"state": "running"|"done"|"cancelled"|"failed",
            "step_index": int, "step_name": str, "samples": int,
            "samples_needed": int, "error": str|None}``.
        """

    def cancel_enroll(self, enroll_id: str) -> bool:
        """Huỷ phiên đăng ký; ``False`` nếu không có phiên đang chạy mã đó."""

    def delete_person(self, person_id: str) -> bool:
        """Xoá người học (bản ghi + vector); ``False`` nếu không tồn tại."""

    def select_person(self, person_id: str | None) -> bool:
        """Chọn người đang học cho phiên này; ``None`` = bỏ chọn.

        Returns:
            ``False`` nếu ``person_id`` không tồn tại.
        """

    def selected_person(self) -> str | None:
        """``id`` người đang được chọn, hoặc ``None``."""

    def signals(self) -> dict:
        """Tín hiệu thô gần nhất, kèm tuổi của từng tín hiệu.

        Returns:
            ``{"presence": S, "phone": S, "identity": S}`` với
            ``S = {"state": str, "age_s": float|None, "age_limit_s": float,
            "fresh": bool}``. ``identity["state"]`` thuộc ``MATCH`` /
            ``MISMATCH`` / ``UNKNOWN`` và có thêm ``name`` khi ``MATCH``.
            Không bao giờ chứa embedding.
        """

    def get_schedule(self) -> dict:
        """Khung giờ học hiện tại (cùng dạng với ``ScheduleConfig``)."""

    def put_schedule(self, payload: dict) -> dict:
        """Ghi khung giờ học; trả cấu hình sau khi ghi."""
