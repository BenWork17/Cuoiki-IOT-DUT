"""Gói con ``camera``: thu khung hình, điều khiển PTZ ONVIF và loa backchannel."""

from .audio import CameraAudioError, SpeakController
from .capture import CameraError, FrameSource, capture_from_config
from .control import PtzController, PtzError

__all__ = [
    "CameraAudioError",
    "CameraError",
    "FrameSource",
    "PtzController",
    "PtzError",
    "SpeakController",
    "capture_from_config",
]
