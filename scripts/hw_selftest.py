"""Tự kiểm tra phần cứng cảnh báo: LED, buzzer, mô-tơ rung và siêu âm (spec §9).

Công cụ này để **người dùng chạy tay** và nhìn/nghe tận mắt, không phải unit
test. Nó bật lần lượt từng LED (xanh/vàng/đỏ), kêu buzzer, chạy mô-tơ rung,
rồi đọc siêu âm 10 lần, dừng đủ lâu để mắt thấy từng linh kiện.

Chạy được cả trên Pi lẫn PC::

    python scripts/hw_selftest.py
    python scripts/hw_selftest.py --no-gpio      # PC, không đụng chân nào
    python scripts/hw_selftest.py --config config.yaml

Mỗi linh kiện được thử độc lập: cái nào vắng hoặc lỗi thì ghi rõ lý do và
**vẫn chạy tiếp các mục còn lại**, cuối cùng mới in bảng và trả mã thoát.

Mã thoát:

- ``0`` — mọi linh kiện có mặt và chạy được (với siêu âm: có ít nhất một lần
  đọc ra số).
- ``1`` — có ít nhất một linh kiện vắng hoặc lỗi.
- ``2`` — không nạp được cấu hình (vẫn chạy bằng chân mặc định).

Không dùng :class:`posture_monitor.hardware.Hardware` ở đây vì lớp đó cố ý
nuốt lỗi từng thiết bị — đúng cho lúc chạy thật, nhưng che mất chính cái mà
bài tự kiểm tra cần báo: linh kiện nào không dựng được và vì sao.
"""

from __future__ import annotations

import argparse
import sys
import time
import warnings
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.config import (  # noqa: E402
    ConfigError,
    PinsConfig,
    load_config,
)
from posture_monitor.sensors import (  # noqa: E402
    MAX_DISTANCE_M,
    MAX_VALID_CM,
    MIN_VALID_CM,
    aggregate_distance,
)

#: Thời gian mỗi LED sáng, đủ để mắt người kịp thấy (spec §9).
LED_ON_S = 0.5

#: Thời gian mỗi tiếng buzzer/rung.
PULSE_S = 0.3

#: Số lần đọc siêu âm theo spec §9.
ULTRASONIC_READS = 10

#: Khoảng nghỉ giữa hai lần đọc siêu âm.
ULTRASONIC_GAP_S = 0.3

OK = "ok"
ABSENT = "vắng"
ERROR = "lỗi"


@dataclass(frozen=True)
class Result:
    """Kết quả thử một linh kiện."""

    name: str
    status: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == OK

    def describe(self) -> str:
        """Chuỗi cột kết quả, kèm lý do trong ngoặc khi không ``ok``."""
        if self.ok or not self.detail:
            return self.status
        return f"{self.status} ({self.detail})"


def _short_reason(exc: BaseException) -> str:
    """Lý do ngắn gọn, một dòng, đủ để người dùng tra tiếp."""
    text = str(exc).strip().replace("\n", " ")
    if len(text) > 120:
        text = text[:117] + "..."
    name = type(exc).__name__
    return f"{name}: {text}" if text else name


def _resolve_sleep(sleep):
    """``None`` → ``time.sleep`` tại thời điểm gọi, không phải lúc định nghĩa.

    Nhờ vậy test chặn được thời gian chờ của bài tự kiểm tra (vốn có ~6 s
    nghỉ để mắt người kịp thấy) mà vẫn dùng đúng hàm mặc định khi chạy thật.
    """
    return time.sleep if sleep is None else sleep


def _import_gpiozero():
    """Import gpiozero muộn; trả ``(module, None)`` hoặc ``(None, lý do)``."""
    try:
        import gpiozero  # noqa: PLC0415 - import muộn để PC thiếu thư viện vẫn chạy

        return gpiozero, None
    except Exception as exc:  # noqa: BLE001 - thiếu thư viện là trường hợp có thật
        return None, f"không import được gpiozero ({_short_reason(exc)})"


def _pins_from_config(path: str | None) -> tuple[PinsConfig, str | None]:
    """Nạp chân từ ``config.yaml``; lỗi thì dùng mặc định và trả lý do."""
    if path is None:
        return PinsConfig(), None
    try:
        config = load_config(path)
        return config.hardware.pins, config.path
    except (FileNotFoundError, ConfigError) as exc:
        return PinsConfig(), f"không nạp được cấu hình ({exc})"


# ---------------------------------------------------------------------------
# Từng linh kiện
# ---------------------------------------------------------------------------


def check_led(
    name: str,
    pin: int,
    *,
    seconds: float = LED_ON_S,
    sleep=None,
    out=print,
    no_gpio: bool = False,
    gpiozero=None,
) -> Result:
    """Bật một LED trong ``seconds`` giây rồi tắt."""
    sleep = _resolve_sleep(sleep)
    label = f"{name} (GPIO{pin})"
    if no_gpio:
        return Result(label, ABSENT, "--no-gpio: không mở chân")
    if gpiozero is None:
        return Result(label, ABSENT, "không có gpiozero")
    out(f"  → Bật {label} trong {seconds:.1f} s…")
    try:
        led = gpiozero.LED(pin)
    except Exception as exc:  # noqa: BLE001 - chân bận hoặc backend hỏng
        return Result(label, ABSENT, _short_reason(exc))
    try:
        led.on()
        sleep(seconds)
        led.off()
    except Exception as exc:  # noqa: BLE001
        return Result(label, ERROR, _short_reason(exc))
    finally:
        try:
            led.close()
        except Exception:  # noqa: BLE001
            pass
    return Result(label, OK)


def check_buzzer(
    pin: int,
    *,
    times: int = 2,
    pulse_s: float = PULSE_S,
    sleep=None,
    out=print,
    no_gpio: bool = False,
    gpiozero=None,
) -> Result:
    """Kêu ``times`` tiếng ngắn, giống nhịp cảnh báo BAD."""
    sleep = _resolve_sleep(sleep)
    label = f"Buzzer (GPIO{pin})"
    if no_gpio:
        return Result(label, ABSENT, "--no-gpio: không mở chân")
    if gpiozero is None:
        return Result(label, ABSENT, "không có gpiozero")
    out(f"  → Kêu buzzer {times} tiếng ngắn…")
    try:
        buzzer = gpiozero.Buzzer(pin)
    except Exception as exc:  # noqa: BLE001
        return Result(label, ABSENT, _short_reason(exc))
    try:
        for _ in range(max(0, times)):
            buzzer.on()
            sleep(pulse_s)
            buzzer.off()
            sleep(pulse_s)
    except Exception as exc:  # noqa: BLE001
        return Result(label, ERROR, _short_reason(exc))
    finally:
        try:
            buzzer.close()
        except Exception:  # noqa: BLE001
            pass
    return Result(label, OK)


def check_vibration(
    pin: int,
    *,
    seconds: float = 0.5,
    sleep=None,
    out=print,
    no_gpio: bool = False,
    gpiozero=None,
) -> Result:
    """Chạy mô-tơ rung trong ``seconds`` giây."""
    sleep = _resolve_sleep(sleep)
    label = f"Mô-tơ rung (GPIO{pin})"
    if no_gpio:
        return Result(label, ABSENT, "--no-gpio: không mở chân")
    if gpiozero is None:
        return Result(label, ABSENT, "không có gpiozero")
    out(f"  → Rung {seconds:.1f} s…")
    try:
        motor = gpiozero.Buzzer(pin)
    except Exception as exc:  # noqa: BLE001
        return Result(label, ABSENT, _short_reason(exc))
    try:
        motor.on()
        sleep(seconds)
        motor.off()
    except Exception as exc:  # noqa: BLE001
        return Result(label, ERROR, _short_reason(exc))
    finally:
        try:
            motor.close()
        except Exception:  # noqa: BLE001
            pass
    return Result(label, OK)


def check_ultrasonic(
    trig: int,
    echo: int,
    *,
    reads: int = ULTRASONIC_READS,
    gap_s: float = ULTRASONIC_GAP_S,
    sleep=None,
    out=print,
    no_gpio: bool = False,
    gpiozero=None,
) -> Result:
    """Đọc HC-SR04 ``reads`` lần, in từng lần kèm cm hoặc ``no echo``.

    Một lần đọc lỗi không dừng bài: mỗi lần là một dòng riêng để người dùng
    thấy ngay cả khi chỉ thỉnh thoảng mất echo. Linh kiện được coi là ``ok``
    khi có ít nhất một lần ra số trong dải hợp lệ.
    """
    sleep = _resolve_sleep(sleep)
    label = f"HC-SR04 (TRIG=GPIO{trig}, ECHO=GPIO{echo})"
    if no_gpio:
        return Result(label, ABSENT, "--no-gpio: không mở chân")
    if gpiozero is None:
        return Result(label, ABSENT, "không có gpiozero")

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            device = gpiozero.DistanceSensor(
                echo=echo,
                trigger=trig,
                max_distance=MAX_DISTANCE_M,
                queue_len=1,
            )
        for warning in caught:
            out(f"  ! gpiozero cảnh báo: {warning.message}")
    except Exception as exc:  # noqa: BLE001 - chân bận/backend hỏng
        return Result(label, ABSENT, _short_reason(exc))

    out(f"  → Đọc siêu âm {reads} lần (dải hợp lệ {MIN_VALID_CM:.0f}–"
        f"{MAX_VALID_CM:.0f} cm):")
    values: list[float | None] = []
    errors = 0
    last_error = ""
    try:
        for index in range(1, max(0, reads) + 1):
            try:
                value = float(device.distance) * 100.0
            except Exception as exc:  # noqa: BLE001 - no echo là bình thường
                errors += 1
                last_error = _short_reason(exc)
                out(f"    lần {index:2d}: no echo ({last_error})")
                values.append(None)
            else:
                in_range = MIN_VALID_CM <= value <= MAX_VALID_CM
                note = "" if in_range else "  ← ngoài dải hợp lệ, bị loại"
                out(f"    lần {index:2d}: {value:6.1f} cm{note}")
                values.append(value if in_range else None)
            if index < reads:
                sleep(gap_s)
    except Exception as exc:  # noqa: BLE001 - lỗi bất ngờ vẫn phải đóng thiết bị
        return Result(label, ERROR, _short_reason(exc))
    finally:
        try:
            device.close()
        except Exception:  # noqa: BLE001
            pass

    median = aggregate_distance(values)
    valid_count = sum(1 for value in values if value is not None)
    if median is None:
        detail = (
            f"không lần nào đọc được; {errors}/{reads} lỗi"
            + (f", lần cuối: {last_error}" if last_error else "")
        )
        return Result(label, ERROR, detail)
    return Result(
        label,
        OK,
        f"{valid_count}/{reads} lần hợp lệ, trung vị {median:.1f} cm",
    )


# ---------------------------------------------------------------------------
# Chạy toàn bộ và in bảng
# ---------------------------------------------------------------------------


def _print_header(
    pins: PinsConfig,
    config_note: str | None,
    no_gpio: bool,
    out=print,
) -> None:
    out("")
    out("=" * 74)
    out("  TỰ KIỂM TRA PHẦN CỨNG — Hệ thống giám sát tư thế")
    out("=" * 74)
    out(f"  Nền tảng : {sys.platform}")
    if config_note:
        out(f"  Cấu hình : {config_note}")
    else:
        out("  Cấu hình : (chân mặc định)")
    if no_gpio:
        out("  Chế độ  : --no-gpio — KHÔNG mở chân nào; chỉ kiểm tra luồng chạy.")
    out(
        "  Chân     : "
        f"LED xanh={pins.led_green}, vàng={pins.led_yellow}, đỏ={pins.led_red}, "
        f"buzzer={pins.buzzer}, rung={pins.vibration}, "
        f"TRIG={pins.trig}, ECHO={pins.echo}"
    )
    out("-" * 74)
    out("  Hãy nhìn LED và nghe tiếng buzzer trong lúc chạy.")
    out("")


def _print_table(results: list[Result], out=print) -> None:
    width = max((len(item.name) for item in results), default=10)
    width = max(width, len("Linh kiện"))
    out("")
    out("-" * 74)
    out(f"  {'Linh kiện':<{width}}  Kết quả")
    out("  " + "-" * (width + 40))
    for item in results:
        out(f"  {item.name:<{width}}  {item.describe()}")
    out("-" * 74)


def run(
    *,
    no_gpio: bool = False,
    config_path: str | None = "config.yaml",
    sleep=None,
    out=print,
) -> int:
    """Chạy toàn bộ bài tự kiểm tra và trả mã thoát.

    Không bao giờ raise vì phần cứng: mỗi mục tự bắt lỗi và ghi kết quả.

    ``sleep=None`` nghĩa là dùng ``time.sleep`` tại thời điểm gọi (không bind
    lúc định nghĩa hàm); nhờ vậy test chặn được thời gian chờ mà không phải
    chạy bài tự kiểm tra thật 6 giây.
    """
    sleep = _resolve_sleep(sleep)
    pins, config_note = _pins_from_config(config_path)
    _print_header(pins, config_note, no_gpio, out=out)

    gpiozero = None
    if not no_gpio:
        gpiozero, reason = _import_gpiozero()
        if gpiozero is None:
            out(f"  ! {reason}")
            out("  ! Các mục phần cứng sẽ ghi 'vắng'; vẫn chạy hết bài.")
            out("")

    results: list[Result] = []
    results.append(
        check_led(
            "LED xanh", pins.led_green, sleep=sleep, out=out,
            no_gpio=no_gpio, gpiozero=gpiozero,
        )
    )
    results.append(
        check_led(
            "LED vàng", pins.led_yellow, sleep=sleep, out=out,
            no_gpio=no_gpio, gpiozero=gpiozero,
        )
    )
    results.append(
        check_led(
            "LED đỏ", pins.led_red, sleep=sleep, out=out,
            no_gpio=no_gpio, gpiozero=gpiozero,
        )
    )
    results.append(
        check_buzzer(
            pins.buzzer, sleep=sleep, out=out,
            no_gpio=no_gpio, gpiozero=gpiozero,
        )
    )
    results.append(
        check_vibration(
            pins.vibration, sleep=sleep, out=out,
            no_gpio=no_gpio, gpiozero=gpiozero,
        )
    )
    results.append(
        check_ultrasonic(
            pins.trig, pins.echo, sleep=sleep, out=out,
            no_gpio=no_gpio, gpiozero=gpiozero,
        )
    )

    _print_table(results, out=out)
    failed = [item for item in results if not item.ok]
    if not failed:
        out("  KẾT LUẬN: tất cả linh kiện có mặt và chạy được.")
        out("  Lưu ý: kết quả 'ok' nghĩa là lệnh điều khiển không lỗi —")
        out("  chỉ mắt/ tai người mới xác nhận đèn sáng thật và buzzer kêu thật.")
        out("=" * 74)
        out("")
        return 0

    out(f"  KẾT LUẬN: {len(failed)}/{len(results)} mục vắng hoặc lỗi:")
    for item in failed:
        out(f"    - {item.name}: {item.describe()}")
    out("  Kiểm tra dây, chân trong config.yaml và nguồn của linh kiện.")
    out("=" * 74)
    out("")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hw_selftest",
        description=(
            "Bật lần lượt LED, buzzer, mô-tơ rung và đọc siêu âm 10 lần để "
            "kiểm tra phần cứng."
        ),
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Đường dẫn file cấu hình (mặc định: config.yaml).",
    )
    parser.add_argument(
        "--no-gpio",
        action="store_true",
        help="Không mở chân GPIO nào; kiểm tra script chạy được trên PC.",
    )
    return parser


def _use_utf8_output() -> None:
    """Ép stdout/stderr sang UTF-8 để chữ Việt không làm chết script trên PC.

    Console Windows mặc định dùng bảng mã cp1252/cp437; in một chữ như "Ự"
    sẽ ném ``UnicodeEncodeError`` ngay giữa bài tự kiểm tra — đúng lúc người
    dùng đang nhìn đèn. ``errors="replace"`` chỉ đổi ký tự không in được
    thành ``?`` thay vì dừng chương trình. Khi stdout không phải luồng thật
    (bị pytest bắt lại), bỏ qua im lặng.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # Luồng không cho đổi mã hoá (đã đóng, hoặc bị bọc đặc biệt).
            continue


def main(argv: list[str] | None = None) -> int:
    _use_utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(no_gpio=args.no_gpio, config_path=args.config)
    except KeyboardInterrupt:
        print("\nĐã dừng theo yêu cầu.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - công cụ tay không nên traceback
        print(f"Lỗi không mong muốn: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
