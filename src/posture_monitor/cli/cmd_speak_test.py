"""Lệnh ``speak-test``: phát thử hoặc liệt kê giọng đọc cảnh báo qua RTSP backchannel."""

from __future__ import annotations

import argparse

from ..core.config import ConfigError
from ..core.labels import VOICE_LABELS
from ..core.logging_setup import setup_logging
from ..domain.schedule import KIND_LABELS
from .parser import SPEAK_TEST_GAP_S, SPEAK_TEST_KINDS


def cmd_speak_test(args: argparse.Namespace) -> int:
    """Xử lý lệnh ``speak-test``: phát thử giọng đọc ra loa camera."""
    from .. import cli as _cli  # noqa: PLC0415
    from ..alerts.speaker_alert import SpeakerAlerter  # noqa: PLC0415

    logger = setup_logging(args.log_level)

    try:
        config = _cli.load_config(args.config)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 2
    except ConfigError as exc:
        logger.error("Cấu hình không hợp lệ: %s", exc)
        return 2

    kinds = list(SPEAK_TEST_KINDS) if args.kind == "all" else [args.kind]

    kwargs: dict[str, object] = {}
    if args.voice is not None:
        kwargs["voice"] = args.voice
    if args.volume is not None:
        kwargs["volume"] = args.volume
    if args.speed is not None:
        kwargs["speed"] = args.speed

    try:
        alerter = SpeakerAlerter.from_config(config, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.error("Không dựng được loa cảnh báo: %s", exc)
        return 2

    if not alerter.available:
        logger.error(
            "Chưa bật được loa camera nên không phát thử được. Bật "
            "'camera.speaker.enabled: true' và đặt 'camera.speaker.host' "
            "(hoặc dùng 'camera.source' là URL rtsp:// để tự suy ra host), "
            "rồi thử lại. Muốn chỉ kiểm tra cấu hình giọng, dùng "
            "'speak-test --list'."
        )
        return 2

    report = alerter.voice_report()

    if args.list:
        _print_speak_test_list(report, kinds)
        return 0

    alerter.prepare()
    report = alerter.voice_report()
    _print_speak_test_header(alerter, report, kinds, args.tone)

    failures: list[str] = []
    for index, kind in enumerate(kinds):
        if index:
            _cli.time.sleep(SPEAK_TEST_GAP_S)
        outcome = alerter.speak_tone_now(kind) if args.tone else alerter.alert(kind)

        label = KIND_LABELS.get(kind, kind)
        if outcome.spoken and outcome.error is None:
            print(f"  [OK]   {label:<20} — {outcome.reason}")
        elif outcome.spoken:
            print(f"  [BÍP]  {label:<20} — {outcome.reason}")
            print(f"         lỗi: {outcome.error}")
            failures.append(kind)
        else:
            print(f"  [LỖI]  {label:<20} — {outcome.reason}")
            if outcome.error is not None:
                print(f"         lỗi: {outcome.error}")
            failures.append(kind)

    print()
    if failures:
        print(
            f"Không phát được {len(failures)}/{len(kinds)} câu: "
            + ", ".join(KIND_LABELS.get(k, k) for k in failures)
            + "."
        )
        print(
            "Xem log phía trên để biết lý do cụ thể. Kiểm tra: camera có bật "
            "loa/backchannel không, 'camera.speaker' đúng chưa, ffmpeg đã cài "
            "chưa (câu nói cần ffmpeg; --tone thì không)."
        )
        print()
        return 1

    print(f"Đã phát được {len(kinds)}/{len(kinds)} câu ra loa camera.")
    print()
    return 0


def _print_speak_test_header(alerter, report: dict, kinds, tone: bool) -> None:
    """In khối mở đầu của ``speak-test``: giọng, nguồn file, cảnh báo thiếu."""
    voice = report.get("voice")
    print()
    print("=" * 66)
    print("  PHÁT THỬ GIỌNG ĐỌC RA LOA CAMERA")
    print("=" * 66)
    print(f"  Giọng đang dùng : {VOICE_LABELS.get(voice, voice)} ({voice})")
    print(f"  Thư mục âm thanh: {alerter.audio_dir}")
    print(f"  Chế độ          : {'tiếng bíp' if tone else 'câu nói'}")
    if not tone:
        print(f"  Âm lượng        : {alerter.volume:.2f}")
        print(f"  Tốc độ đọc      : {alerter.speed:.2f}×")
    print(f"  Số câu          : {len(kinds)}")
    if report.get("error"):
        print(f"  Cảnh báo        : {report['error']}")
    print("-" * 66)
    print(f"  {'Câu':<20} {'Nguồn phát'}")
    print("-" * 66)
    for kind in kinds:
        label = KIND_LABELS.get(kind, kind)
        wav = alerter.wav_path(kind)
        if tone:
            source = "(tiếng bíp)"
        elif wav is not None:
            source = wav.name
        else:
            source = "THIẾU — sẽ dùng tiếng bíp"
        print(f"  {label:<20} {source}")
    print("-" * 66)
    print("  Loa sẽ phát ngay; tăng âm lượng loa camera nếu không nghe rõ.")
    print()


def _print_speak_test_list(report: dict, kinds) -> None:
    """In danh sách giọng và câu có sẵn, không phát gì (``--list``)."""
    voice = report.get("voice")
    print()
    print("=" * 66)
    print("  GIỌNG ĐỌC ĐANG CÓ (không phát gì)")
    print("=" * 66)
    print(f"  Đang chọn: {VOICE_LABELS.get(voice, voice)} ({voice})")
    print(
        f"  Âm lượng : {report.get('volume', 0):.2f}   "
        f"Tốc độ: {report.get('speed', 0):.2f}×"
    )
    print("-" * 66)
    for key, info in (report.get("voices") or {}).items():
        mark = "*" if key == voice else " "
        label = info.get("label") or VOICE_LABELS.get(key, key)
        clips = info.get("clips") or {}
        print(f" {mark} {label:<12} {len(clips)}/{len(kinds)} câu")
        for kind in kinds:
            name = clips.get(kind)
            kind_label = KIND_LABELS.get(kind, kind)
            if name:
                print(f"       {kind_label:<20} {name}")
            elif key in ("nam", "nu"):
                print(f"       {kind_label:<20} THIẾU")
    print("-" * 66)
    fallbacks = report.get("fallbacks") or {}
    for note in fallbacks.values():
        print(f"  Lưu ý: {note}")
    if report.get("error"):
        print(f"  Lỗi  : {report['error']}")
    print("=" * 66)
    print()
