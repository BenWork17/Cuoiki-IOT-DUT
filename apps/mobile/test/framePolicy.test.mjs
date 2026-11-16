/**
 * Test cho chính sách thử lại ảnh camera (`src/api/framePolicy.ts`).
 *
 * Đây là chỗ quyết định app có biến thành máy dò lỗi liên tục hay không, nên
 * mỗi nhánh đều có test riêng.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  INITIAL_RETRY_STATE,
  MAX_AUTO_RETRY,
  afterFrameFailure,
  shouldPollAgain,
} from '../src/api/framePolicy.ts';

test('ban đầu thì được phép hỏi tiếp', () => {
  assert.equal(shouldPollAgain(INITIAL_RETRY_STATE), true);
});

test('403 (stream tắt) ⇒ dừng hẳn, không hỏi lại', () => {
  const state = afterFrameFailure({ kind: 'http', status: 403 }, INITIAL_RETRY_STATE);
  assert.equal(state.stopReason, 'disabled');
  assert.equal(shouldPollAgain(state), false);
});

test('404 (bản dashboard chưa có route) ⇒ dừng, không hỏi lại liên tục', () => {
  const state = afterFrameFailure({ kind: 'http', status: 404 }, INITIAL_RETRY_STATE);
  assert.equal(state.stopReason, 'missing');
  assert.equal(shouldPollAgain(state), false);
});

test('503 (chưa có khung) ⇒ vẫn hỏi lại vì camera có thể sắp lên', () => {
  const state = afterFrameFailure({ kind: 'http', status: 503 }, INITIAL_RETRY_STATE);
  assert.equal(state.stopReason, 'none');
  // 503 KHÔNG cộng vào bộ đếm kiệt: camera chậm khởi động không phải lỗi.
  assert.equal(state.retryCount, 0);
  assert.equal(shouldPollAgain(state), true);
});

test('10 lần 503 liên tiếp KHÔNG làm kiệt bộ đếm — vẫn hỏi lại', () => {
  let state = INITIAL_RETRY_STATE;
  for (let i = 0; i < 10; i++) {
    state = afterFrameFailure({ kind: 'http', status: 503 }, state);
    assert.equal(
      shouldPollAgain(state),
      true,
      `sau ${i + 1} lần 503 vẫn phải tiếp tục hỏi lại (retryCount=${state.retryCount})`,
    );
  }
  assert.equal(state.stopReason, 'none');
  assert.equal(state.retryCount, 0);
});

test('503 chen giữa các lỗi mạng không xoá dấu vết lỗi mạng', () => {
  let state = INITIAL_RETRY_STATE;
  // Hai lỗi mạng thật → bộ đếm phải là 2.
  state = afterFrameFailure({ kind: 'network', status: null }, state);
  state = afterFrameFailure({ kind: 'network', status: null }, state);
  assert.equal(state.retryCount, 2);
  // Một nhịp 503 không được reset bộ đếm về 0 (nếu reset, app sẽ thử lại vô
  // hạn một máy chủ đang hỏng thật chỉ vì thỉnh thoảng trả 503).
  state = afterFrameFailure({ kind: 'http', status: 503 }, state);
  assert.equal(state.retryCount, 2);
  assert.equal(state.stopReason, 'none');
  // Lỗi mạng thứ ba mới là lần chạm ngưỡng.
  state = afterFrameFailure({ kind: 'network', status: null }, state);
  assert.equal(state.retryCount, MAX_AUTO_RETRY);
  assert.equal(state.stopReason, 'exhausted');
});

test('500 (lỗi nội bộ máy chủ) VẪN đếm và kiệt — khác 503', () => {
  let state = INITIAL_RETRY_STATE;
  for (let i = 0; i < MAX_AUTO_RETRY; i++) {
    state = afterFrameFailure({ kind: 'http', status: 500 }, state);
  }
  assert.equal(state.stopReason, 'exhausted');
  assert.equal(shouldPollAgain(state), false);
});

test('lỗi mạng ⇒ hỏi lại, có đếm', () => {
  const state = afterFrameFailure({ kind: 'network', status: null }, INITIAL_RETRY_STATE);
  assert.equal(state.stopReason, 'none');
  assert.equal(state.retryCount, 1);
});

test('quá hạn chờ ⇒ hỏi lại, có đếm', () => {
  const state = afterFrameFailure({ kind: 'timeout', status: null }, INITIAL_RETRY_STATE);
  assert.equal(state.stopReason, 'none');
  assert.equal(state.retryCount, 1);
});

test('502 (máy chủ không nói chuyện được với camera) ⇒ hỏi lại', () => {
  const state = afterFrameFailure({ kind: 'http', status: 502 }, INITIAL_RETRY_STATE);
  assert.equal(shouldPollAgain(state), true);
});

test('hết số lần thử thì dừng và chờ người dùng bấm', () => {
  let state = INITIAL_RETRY_STATE;
  for (let i = 0; i < MAX_AUTO_RETRY; i++) {
    assert.equal(shouldPollAgain(state), true, `lượt ${i + 1} vẫn phải được thử`);
    state = afterFrameFailure({ kind: 'network', status: null }, state);
  }
  assert.equal(state.retryCount, MAX_AUTO_RETRY);
  assert.equal(state.stopReason, 'exhausted');
  assert.equal(shouldPollAgain(state), false);
});

test('chưa cấu hình địa chỉ ⇒ dừng ngay, không thử lại', () => {
  const state = afterFrameFailure({ kind: 'config', status: null }, INITIAL_RETRY_STATE);
  assert.equal(state.stopReason, 'exhausted');
  assert.equal(shouldPollAgain(state), false);
});

test('lượt bị huỷ không tính là thất bại và không đổi bộ đếm', () => {
  const before = { retryCount: 2, stopReason: 'none' };
  const after = afterFrameFailure({ kind: 'cancelled', status: null }, before);
  assert.deepEqual(after, before);
});

test('lượt bị huỷ không làm mất trạng thái "stream tắt"', () => {
  const before = { retryCount: 0, stopReason: 'disabled' };
  const after = afterFrameFailure({ kind: 'cancelled', status: null }, before);
  assert.equal(after.stopReason, 'disabled');
});

test('403 không cộng vào bộ đếm (đổi sang 403 không phải là "thử thêm một lần")', () => {
  const before = { retryCount: 1, stopReason: 'none' };
  const after = afterFrameFailure({ kind: 'http', status: 403 }, before);
  assert.equal(after.retryCount, 1);
  assert.equal(after.stopReason, 'disabled');
});

test('một lượt thành công (không gọi hàm này) là cách duy nhất để quay lại none', () => {
  // Tài liệu hoá ý đồ: `afterFrameFailure` chỉ đi theo hướng dừng. Màn hình
  // phải tự đặt lại `INITIAL_RETRY_STATE` khi tải được ảnh — nếu không, một
  // lần lỗi sẽ để bộ đếm dính mãi.
  const stopped = afterFrameFailure({ kind: 'network', status: null }, {
    retryCount: MAX_AUTO_RETRY - 1,
    stopReason: 'none',
  });
  assert.equal(stopped.stopReason, 'exhausted');
  assert.deepEqual(INITIAL_RETRY_STATE, { retryCount: 0, stopReason: 'none' });
});
