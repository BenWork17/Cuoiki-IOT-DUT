"""Gói thị giác máy tính ``vision``: Pose, Điện thoại, Khuôn mặt, Hiệu chỉnh, Phân loại & Overlay."""

from __future__ import annotations

import importlib

_EXPORTS: dict[str, tuple[str, str]] = {
    "Baseline": (".calibration", "Baseline"),
    "CalibrationError": (".calibration", "CalibrationError"),
    "compute_baseline": (".calibration", "compute_baseline"),
    "load": (".calibration", "load"),
    "save": (".calibration", "save"),
    "Classification": (".classifier", "Classification"),
    "classify": (".classifier", "classify"),
    "filter_posture_labels": (".classifier", "filter_posture_labels"),
    "FaceError": (".faces", "FaceError"),
    "FaceModelError": (".faces", "FaceModelError"),
    "FaceRecognizer": (".faces", "FaceRecognizer"),
    "FaceStore": (".faces", "FaceStore"),
    "FaceStoreError": (".faces", "FaceStoreError"),
    "build_face_processor": (".faces", "build_face_processor"),
    "ALL_NAMES": (".features", "ALL_NAMES"),
    "Features": (".features", "Features"),
    "extract": (".features", "extract"),
    "draw_detections": (".overlay", "draw_detections"),
    "draw_pose": (".overlay", "draw_pose"),
    "PHONE_CLASS_ID": (".phone", "PHONE_CLASS_ID"),
    "HandPhoneResult": (".phone", "HandPhoneResult"),
    "hand_phone_contact": (".phone", "hand_phone_contact"),
    "PhoneDetector": (".phone_detector", "PhoneDetector"),
    "PhoneDetectorError": (".phone_detector", "PhoneDetectorError"),
    "PhoneSignal": (".phone_detector", "PhoneSignal"),
    "PoseError": (".pose", "PoseError"),
    "PoseEstimator": (".pose", "PoseEstimator"),
    "PoseResult": (".pose", "PoseResult"),
    "pose_to_keypoints_array": (".pose", "pose_to_keypoints_array"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} không có thuộc tính {name!r}")
    mod_name, attr_name = target
    module = importlib.import_module(mod_name, __name__)
    return getattr(module, attr_name)
