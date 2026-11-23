"""Gói nền tảng ``core``: cấu hình, thông tin xác thực, nhãn miền, log và ghi tệp nguyên tử."""

from .atomic_io import write_json_atomic
from .config import Config, ConfigError, load_config
from .credentials import (
    CAMERA_SOURCE_ENV,
    ONVIF_PASSWORD_ENV,
    camera_credentials,
    camera_source_host,
    onvif_credentials,
    onvif_password,
    parse_camera_source,
    redact_camera_source,
    resolve_model_path,
)
from .log_buffer import LogBuffer
from .logging_setup import (
    ROOT_LOGGER_NAME,
    get_log_buffer,
    get_logger,
    reset_log_buffer,
    setup_logging,
)

__all__ = [
    "CAMERA_SOURCE_ENV",
    "Config",
    "ConfigError",
    "LogBuffer",
    "ONVIF_PASSWORD_ENV",
    "ROOT_LOGGER_NAME",
    "camera_credentials",
    "camera_source_host",
    "get_log_buffer",
    "get_logger",
    "load_config",
    "onvif_credentials",
    "onvif_password",
    "parse_camera_source",
    "redact_camera_source",
    "reset_log_buffer",
    "resolve_model_path",
    "setup_logging",
    "write_json_atomic",
]
