"""Phân tích nguồn camera, suy diễn tài khoản ONVIF/RTSP, che mật khẩu & phân giải đường dẫn model.

Tách riêng khỏi bộ nạp YAML để ``log_buffer``, ``camera`` và ``vision`` dùng
được mà không kéo theo các dataclass cấu hình hay tạo vòng lặp import.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlsplit

#: Biến môi trường ghi đè ``camera.source`` (cho phép đặt URL RTSP có mật khẩu).
CAMERA_SOURCE_ENV = "POSTURE_CAMERA_SOURCE"

#: Biến môi trường chứa mật khẩu ONVIF/RTSP của camera IP.
ONVIF_PASSWORD_ENV = "POSTURE_ONVIF_PASSWORD"

#: Chuỗi thay thế thông tin nhạy cảm trong log và thông điệp lỗi.
REDACTED = "***"

#: Thư mục mặc định chứa trọng số mô hình ở gốc repo.
DEFAULT_MODELS_DIR = "models"

_URL_USERINFO = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*://)(?P<userinfo>[^/]*)@"
)
_SOURCE_PREFIX = re.compile(r"^(?:usb|file|rtsp|rtsps):(?!//)")


class ConfigError(ValueError):
    """Cấu hình không hợp lệ (sai kiểu, sai giá trị, sai cú pháp)."""


class _HasUser(Protocol):
    user: str


def redact_camera_source(source: object) -> str:
    """Che user/mật khẩu trong URL RTSP trước khi đưa ra log hay thông điệp lỗi."""
    text = source if isinstance(source, str) else repr(source)

    def _hide(match: re.Match[str]) -> str:
        userinfo = match.group("userinfo")
        hidden = REDACTED if ":" not in userinfo else f"{REDACTED}:{REDACTED}"
        return f"{match.group('scheme')}{hidden}@"

    return _URL_USERINFO.sub(_hide, text)


def _normalize_env_source(override: str) -> str:
    """Chuẩn hoá giá trị biến môi trường thành cú pháp ``camera.source``."""
    text = override.strip()
    lowered = text.lower()
    if _SOURCE_PREFIX.match(lowered):
        return text
    if lowered.startswith(("rtsp://", "rtsps://")):
        return f"rtsp:{text}"
    return text


def onvif_password() -> str:
    """Đọc mật khẩu ONVIF từ biến môi trường :data:`ONVIF_PASSWORD_ENV`."""
    return os.environ.get(ONVIF_PASSWORD_ENV, "").strip()


def parse_camera_source(source: str) -> tuple[str, int | str | None]:
    """Tách ``camera.source`` thành ``(loại, tham số)``."""
    safe = redact_camera_source(source)

    if not isinstance(source, str) or not source.strip():
        raise ConfigError("'camera.source' phải là chuỗi không rỗng.")

    text = source.strip()
    if text == "picamera":
        return "picamera", None

    if ":" not in text:
        raise ConfigError(
            f"'camera.source' = {safe!r} không hợp lệ. Dùng 'usb:N', "
            "'picamera', 'file:duong_dan.mp4' hoặc 'rtsp:rtsp://...'."
        )

    kind, _, value = text.partition(":")
    kind = kind.strip().lower()
    value = value.strip()

    if kind == "rtsp" and text.lower().startswith("rtsp://"):
        if value.startswith("//"):
            value = f"rtsp:{value}"

    if kind == "usb":
        try:
            index = int(value)
        except ValueError as exc:
            raise ConfigError(
                f"'camera.source' = {safe!r}: chỉ số USB phải là số nguyên."
            ) from exc
        if index < 0:
            raise ConfigError(f"'camera.source' = {safe!r}: chỉ số USB không được âm.")
        return "usb", index

    if kind == "file":
        if not value:
            raise ConfigError(f"'camera.source' = {safe!r}: thiếu đường dẫn file.")
        return "file", value

    if kind == "rtsp":
        if not value:
            raise ConfigError(
                f"'camera.source' = {safe!r}: thiếu URL RTSP sau 'rtsp:'."
            )
        if not value.lower().startswith(("rtsp://", "rtsps://")):
            raise ConfigError(
                f"'camera.source' = {safe!r}: URL RTSP phải bắt đầu bằng "
                "'rtsp://' hoặc 'rtsps://'."
            )
        return "rtsp", value

    raise ConfigError(
        f"'camera.source' = {safe!r}: loại {kind!r} không được hỗ trợ. "
        "Dùng 'usb:N', 'picamera', 'file:duong_dan.mp4' hoặc "
        "'rtsp:rtsp://...'."
    )


def camera_source_host(source: str) -> str:
    """Host suy ra từ ``camera.source``; trả ``""`` khi nguồn không phải URL RTSP."""
    try:
        kind, value = parse_camera_source(source)
    except ConfigError:
        return ""
    if kind != "rtsp" or not isinstance(value, str):
        return ""
    try:
        return urlsplit(value).hostname or ""
    except ValueError:
        return ""


def source_credentials(source: str) -> tuple[str, str]:
    """``(user, password)`` nhúng trong URL ``camera.source``; rỗng nếu không có."""
    try:
        kind, value = parse_camera_source(source)
    except ConfigError:
        return "", ""
    if kind != "rtsp" or not isinstance(value, str):
        return "", ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return "", ""
    return unquote(parts.username or ""), unquote(parts.password or "")


def camera_credentials(user: str, source: str) -> tuple[str, str]:
    """``(user, password)`` dùng chung cho ONVIF (PTZ) và loa (RTSP backchannel)."""
    env_password = onvif_password()
    if env_password:
        return user, env_password
    src_user, src_password = source_credentials(source)
    if src_password:
        return src_user, src_password
    return user, ""


def onvif_credentials(onvif: _HasUser, source: str) -> tuple[str, str]:
    """``(user, password)`` để mở phiên ONVIF."""
    return camera_credentials(onvif.user, source)


def resolve_model_path(
    name_or_path: str | Path,
    *,
    default_suffix: str = "",
    models_dir: str | Path = DEFAULT_MODELS_DIR,
) -> Path:
    """Phân giải đường dẫn trọng số mô hình ưu tiên thư mục ``models/``.

    - Nếu người dùng đã chỉ định đường dẫn tuyệt đối hoặc có thư mục cha
      (ví dụ ``models/yunet.onnx`` hoặc ``/tmp/custom.pt``): giữ nguyên.
    - Nếu chỉ ghi tên tệp trần (ví dụ ``yolo11n-pose`` hoặc ``yunet.onnx``):
      1. Ưu tiên ``models/<tên>`` nếu tệp hoặc thư mục ``*_ncnn_model`` tồn tại ở đó.
      2. Rơi về thư mục hiện tại ``./<tên>`` nếu có sẵn ở gốc (tương thích ngược trên Pi).
      3. Nếu chưa tồn tại ở cả hai nơi, trỏ vào ``models/<tên>`` khi thư mục
         ``models/`` hiện diện để tệp tự tải/export không làm bẩn gốc dự án.
    """
    raw = str(name_or_path).strip()
    if default_suffix and not Path(raw).suffix:
        raw = f"{raw}{default_suffix}"
    candidate = Path(raw)
    if candidate.is_absolute() or len(candidate.parts) > 1:
        return candidate

    mdir = Path(models_dir)
    in_models = mdir / candidate
    in_models_ncnn = mdir / f"{candidate.stem}_ncnn_model"
    if in_models.exists() or in_models_ncnn.is_dir():
        return in_models

    cwd_ncnn = candidate.with_name(f"{candidate.stem}_ncnn_model")
    if candidate.exists() or cwd_ncnn.is_dir():
        return candidate

    if mdir.is_dir():
        return in_models
    return candidate
