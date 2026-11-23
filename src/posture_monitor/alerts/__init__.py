"""Gói con ``alerts``: điều phối cảnh báo GPIO, thư viện giọng thu sẵn và loa camera."""

from .gpio_dispatcher import HW_BREAK, AlertDispatcher
from .speaker_alert import AlertOutcome, SpeakerAlerter

__all__ = [
    "AlertDispatcher",
    "AlertOutcome",
    "HW_BREAK",
    "SpeakerAlerter",
]
