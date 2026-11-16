# Chạy pytest trong sandbox Windows của phiên này

Tài liệu này tồn tại vì **cùng một lỗi hợp đồng đã xảy ra ba lần** (task t2, t4,
t13): một lệnh `pytest` trần được coi là "phải exit 0", nhưng lệnh đó **không
thể** exit 0 trong môi trường này. Mỗi lần như vậy một người phải làm thêm một
vòng chỉ để chạy lại đúng lệnh. Đọc mục 1 trước khi viết bất kỳ lệnh verify nào.

## 1. Nguyên nhân gốc — đo được, không phải suy đoán

Sandbox của phiên này chặn thư mục được tạo với `mode=0o700`:

| Cách tạo | `os.scandir` trên thư mục đó |
|---|---|
| `os.makedirs(p, mode=0o777)` | OK |
| `os.makedirs(p, mode=0o755)` | OK |
| `os.makedirs(p, mode=0o700)` | **FAIL `PermissionError: [WinError 5]`** |

`os.chmod` sau khi tạo cũng bị từ chối, nên không cứu được.

pytest **luôn** tạo `tmp_path` bằng `mode=0o700`. Các vị trí trong
`_pytest` của bản đang cài:

- `_pytest/tmpdir.py` dòng 133, 135, 152, 162, 166, 191
- `_pytest/pathlib.py` dòng 225–233 (`make_numbered_dir(..., mode=0o700)`)

Hệ quả: mọi bài test dùng fixture `tmp_path` (hoặc `tmpdir`, hoặc
`tempfile.TemporaryDirectory()`) đều lỗi **ở khâu tạo thư mục**, trước khi tới
phần assert. Đây là **lỗi môi trường**, không phải lỗi mã nguồn. Trong một lần
chạy toàn bộ `tests/`, con số từng thấy là **448 errors** — tất cả đều thuộc
nhóm này, và **0 `AssertionError`**.

## 2. Cách chạy đúng

Dùng một plugin nhỏ vá `mode` khi tạo thư mục. Plugin nằm trong `.scratch/`
(đã bị `.gitignore` chặn ở dòng 70), **không** đưa vào repo dùng chung.

Tạo tệp `.scratch/plug/tmpmode.py` với nội dung:

```python
import os, pathlib

# os.mkdir: dùng bởi tempfile.TemporaryDirectory()
_orig_mkdir = os.mkdir
def _mkdir(path, mode=0o777, *, dir_fd=None):
    return _orig_mkdir(path, mode=0o777, dir_fd=dir_fd)
os.mkdir = _mkdir

# pathlib.Path.mkdir: dùng bởi _pytest/tmpdir.py và _pytest/pathlib.py
_orig_pmkdir = pathlib.Path.mkdir
def _p_mkdir(self, mode=0o777, parents=False, exist_ok=False):
    return _orig_pmkdir(self, mode=0o777, parents=parents, exist_ok=exist_ok)
pathlib.Path.mkdir = _p_mkdir

# os.makedirs: đường phòng vệ
_orig_makedirs = os.makedirs
def _makedirs(name, mode=0o777, exist_ok=False):
    return _orig_makedirs(name, mode=0o777, exist_ok=exist_ok)
os.makedirs = _makedirs
```

Đủ **cả ba** chỗ patch mới đúng: chỉ patch `pathlib.Path.mkdir` thì
`tempfile.TemporaryDirectory()` vẫn lỗi (nó đi qua `os.mkdir`). Đây chính là
lỗi mà một phép đo từng mắc phải (21 passed / 1 failed thay vì 22 passed).

Lệnh mẫu, dùng cho **mọi** tệp có `tmp_path`:

```powershell
$env:PYTHONPATH="src;.scratch\plug"
python -m pytest <danh sach tep> -q -p tmpmode -p no:cacheprovider --basetemp="E:\2026\DUT\IOT\Cuoiki\.scratch\btN"
```

`--basetemp` phải trỏ vào một thư mục **mới** trong `.scratch/` (đổi `N` mỗi
lần). Dùng lại một basetemp đã tạo bằng `0o700` từ lần chạy trước vẫn lỗi, vì
thư mục đó đã tồn tại với mode sai.

Nếu các tệp trong lệnh **không** dùng `tmp_path`, chạy trần là được:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_pose.py -q -p no:cacheprovider
```

## 3. Danh sách tệp PHẢI dùng plugin

Quét bằng cách đếm số lần xuất hiện `tmp_path|tmpdir|TemporaryDirectory`:

| Tệp | Số chỗ |
|---|---|
| `tests/test_config.py` | 94 |
| `tests/test_web.py` | 84 |
| `tests/test_people_service.py` | 78 |
| `tests/test_faces.py` | 70 |
| `tests/test_cli_replay.py` | 69 |
| `tests/test_voice_library.py` | 58 |
| `tests/test_speaker_alert.py` | 56 |
| `tests/test_cli_calibrate.py` | 52 |
| `tests/test_wire_alert_gate.py` | 47 |
| `tests/test_people_threshold_persist.py` | 42 |
| `tests/test_storage.py` | 31 |
| `tests/test_face_worker.py` | 29 |
| `tests/test_rtsp.py` | 22 |
| `tests/test_wire_people_real.py` | 20 |
| `tests/test_benchmark.py` | 18 |
| `tests/test_capture.py` | 18 |
| `tests/test_enroll_hang_on_model_error.py` | 16 |
| `tests/test_phone_detector.py` | 16 |
| `tests/test_wire_face_gate.py` | 15 |
| `tests/test_worker_survives.py` | 13 |
| `tests/test_camera_audio.py` | 12 |
| `tests/test_state.py` | 12 |
| `tests/test_cli_speak_test.py` | 9 |
| `tests/test_web_wire.py` | 8 |
| `tests/test_cli_benchmark.py` | 6 |
| `tests/test_benchmark_profile.py` | 4 |
| `tests/test_benchmark_redact.py` | 4 |

**Cẩn thận — đếm số lần khớp không đủ.** `tests/test_web_frame.py` khớp 2 lần
nhưng **cả hai là chú thích** giải thích vì sao tệp đó *không* dùng `tmp_path`.
Nó chạy trần được. Luôn đọc ngữ cảnh trước khi kết luận.

## 4. Vì sao KHÔNG sửa repo để né lỗi này

Có ba cách "làm cho xanh" và cả ba đều sai:

1. Thêm `conftest.py`/`pytest.ini` ở gốc repo đổi `mode` — biến workaround đặc
   thù của một máy Windows thành rác vĩnh viễn trong repo dùng chung, và người
   dùng Linux/Pi sẽ không hiểu vì sao nó ở đó.
2. Đổi test để không dùng `tmp_path` — làm sai lệch bằng chứng; test đang kiểm
   đúng thứ nó cần kiểm.
3. Đánh dấu skip toàn bộ tệp có `tmp_path` — mất coverage thật.

Plugin trong `.scratch/` là lựa chọn đúng: nó sửa **môi trường**, không sửa
sản phẩm, và không vào git.

## 5. Cảnh báo vận hành — lệnh pytest trần có thể xoá thư mục tạm của sandbox

Đã xảy ra một lần trong phiên này: một lệnh `pytest` **không** có `--basetemp`
đã xoá thư mục tạm riêng của sandbox (`C:\Users\ACER\AppData\Local\Temp\dsh-*`),
làm mọi lệnh `pwsh` sau đó thất bại với
`windows-acl-run: --temp is not an existing directory`.

Vì vậy: **luôn** truyền `--basetemp` trỏ vào `.scratch/` khi chạy pytest, kể cả
khi lệnh không chạm tệp nào dùng `tmp_path`. Đừng chạy `pytest tests/` trần để
"xem nhanh".

## 6. Bằng chứng rằng sản phẩm không có lỗi

Khi chạy đúng cách (mục 2), các con số đã ghi nhận trong phiên này:

| Lệnh | Kết quả |
|---|---|
| toàn bộ `tests/` (có plugin) | **1512 passed, 4 skipped, exit 0** |
| `tests/test_wire_alert_gate.py` (có plugin) | **22 passed, exit 0** |
| `tests/test_web_frame.py tests/test_web.py` (có plugin) | **68–69 passed, exit 0** |
| `tests/test_pose.py tests/test_presence.py tests/test_pose_track_reacquire.py` (trần) | **59 passed, 1 skipped, exit 0** |

Bài bị skip là bài tích hợp cần trọng số `yolo11n-pose.pt` + `bus.jpg` thật,
tự gọi `pytest.skip` khi thiếu tệp — không phải test hỏng.
