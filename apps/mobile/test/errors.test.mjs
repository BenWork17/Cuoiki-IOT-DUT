/**
 * Test cho phần đổi mã lỗi thành câu tiếng Việt (`src/api/errors.ts`).
 *
 * Đây là chỗ dễ sai nhất và cũng khó thấy nhất nếu chỉ đọc mã UI: **405 và
 * 404 ngoài `/api/` trả thân HTML**, nên `response.json()` ném lỗi và người
 * dùng nhận một thông điệp vô nghĩa (hoặc không thấy gì).
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  INVALID_JSON_MESSAGE,
  configError,
  describeError,
  extractServerMessage,
  httpError,
  httpStatusMessage,
  messageForStatus,
  networkError,
  routeKey,
  timeoutError,
} from '../src/api/errors.ts';

test('extractServerMessage: đọc được message từ JSON của server', () => {
  const body = JSON.stringify({ ok: false, message: 'Phiên học chưa được bật.' });
  assert.equal(extractServerMessage(body, 'application/json'), 'Phiên học chưa được bật.');
});

test('extractServerMessage: thân HTML trả null thay vì ném lỗi', () => {
  const html = '<!doctype html><html><body><h1>405 Method Not Allowed</h1></body></html>';
  assert.equal(extractServerMessage(html, 'text/html'), null);
});

test('extractServerMessage: HTML không có content-type vẫn trả null', () => {
  assert.equal(extractServerMessage('<html>lỗi</html>', null), null);
});

test('extractServerMessage: body rỗng trả null', () => {
  assert.equal(extractServerMessage('', 'application/json'), null);
  assert.equal(extractServerMessage('   ', 'application/json'), null);
});

test('extractServerMessage: JSON hỏng trả null, không ném SyntaxError', () => {
  assert.equal(extractServerMessage('{"ok": false, "message": ', 'application/json'), null);
});

test('extractServerMessage: JSON không có message trả null', () => {
  assert.equal(extractServerMessage('{"ok": false}', 'application/json'), null);
  assert.equal(extractServerMessage('{"message": 42}', 'application/json'), null);
  assert.equal(extractServerMessage('{"message": "   "}', 'application/json'), null);
});

test('extractServerMessage: mảng JSON không được coi là object lỗi', () => {
  assert.equal(extractServerMessage('[{"message": "x"}]', 'application/json'), null);
});

test('extractServerMessage: nhận JSON dù content-type nói text/html', () => {
  // Một số proxy trả JSON nhưng gắn nhãn sai; vẫn đọc được thì tốt hơn là bỏ.
  assert.equal(extractServerMessage('{"message": "Đã tắt tiếng."}', 'text/html'), 'Đã tắt tiếng.');
});

test('httpStatusMessage: mọi mã hay gặp đều có câu tiếng Việt', () => {
  for (const status of [400, 403, 404, 405, 409, 500, 501, 502, 503, 504]) {
    const text = httpStatusMessage(status);
    assert.ok(text.length > 10, `mã ${status} phải có câu giải thích, nhận: "${text}"`);
    assert.doesNotMatch(text, /undefined|null/);
  }
});

test('httpStatusMessage: mã lạ vẫn có câu, không im lặng', () => {
  const text = httpStatusMessage(418);
  assert.match(text, /418/);
  assert.match(text, /từ chối|bất thường/);
});

test('messageForStatus: ưu tiên câu của server hơn câu mặc định', () => {
  const text = messageForStatus(503, 'Phiên học chưa được bật trong lần chạy này.', '/api/session');
  assert.equal(text, 'Phiên học chưa được bật trong lần chạy này.');
});

test('messageForStatus: 404 ở /api/frame nói đúng "máy chủ chưa có route"', () => {
  const text = messageForStatus(404, null, '/api/frame');
  assert.match(text, /chưa có route ảnh tĩnh/);
});

test('messageForStatus: 403 ở /api/frame nói về stream_enabled + config.yaml', () => {
  const text = messageForStatus(403, null, '/api/frame');
  assert.match(text, /web\.stream_enabled/);
  assert.match(text, /config\.yaml/);
});

test('messageForStatus: 503 ở /api/ptz nhắc camera, không phải lỗi chung', () => {
  const text = messageForStatus(501, null, '/api/ptz');
  assert.match(text, /Camera không hỗ trợ PTZ/);
});

test('messageForStatus: route không có gợi ý thì rơi về câu chung của mã', () => {
  assert.equal(messageForStatus(404, null, '/api/khong-co'), httpStatusMessage(404));
});

test('messageForStatus: không truyền path vẫn có câu', () => {
  assert.equal(messageForStatus(500), httpStatusMessage(500));
});

test('messageForStatus: message rỗng của server không được dùng', () => {
  assert.equal(messageForStatus(404, '   ', '/api/x'), httpStatusMessage(404));
});

test('routeKey: bỏ query để tra gợi ý', () => {
  assert.equal(routeKey('/api/history?range=today'), '/api/history');
  assert.equal(routeKey('/api/frame'), '/api/frame');
});

test('httpError: mã 5xx được đánh dấu thử lại được', () => {
  const error = httpError(503, null, '/api/session');
  assert.equal(error.kind, 'http');
  assert.equal(error.status, 503);
  assert.equal(error.retryable, true);
});

test('httpError: 400 do người dùng gõ sai thì KHÔNG hứa thử lại cứu được', () => {
  const error = httpError(400, 'Số phút phải trong khoảng 1–720.');
  assert.equal(error.retryable, false);
  assert.equal(error.message, 'Số phút phải trong khoảng 1–720.');
  assert.equal(error.serverMessage, 'Số phút phải trong khoảng 1–720.');
});

test('httpError: giữ cả mã HTTP và câu server để màn hình quyết định', () => {
  const error = httpError(403, 'Tính năng xem trực tiếp đang tắt.');
  assert.equal(error.status, 403);
  assert.match(error.message, /xem trực tiếp đang tắt/);
});

test('httpError: 405 có câu tiếng Việt dù thân là HTML (không parse được)', () => {
  const error = httpError(405, null);
  assert.equal(error.status, 405);
  assert.match(error.message, /Sai phương thức gọi API/);
  assert.equal(error.serverMessage, undefined);
});

test('error kinds: cấu hình / mạng / quá hạn chờ mang đúng cờ', () => {
  const config = configError('Chưa nhập địa chỉ máy chủ.');
  assert.equal(config.kind, 'config');
  assert.equal(config.status, null);
  assert.equal(config.retryable, false);

  const network = networkError('TypeError: Network request failed');
  assert.equal(network.kind, 'network');
  assert.equal(network.retryable, true);
  assert.match(network.message, /Không kết nối được tới máy chủ/);
  assert.match(network.cause ?? '', /Network request failed/);

  const timeout = timeoutError();
  assert.equal(timeout.kind, 'timeout');
  assert.equal(timeout.retryable, true);
  assert.match(timeout.message, /không trả lời/);
});

test('describeError: lỗi rỗng không tạo ra chữ rác', () => {
  assert.equal(describeError(null), '');
  assert.equal(describeError(undefined), '');
  assert.equal(describeError(networkError()), networkError().message);
});

test('INVALID_JSON_MESSAGE: nói rõ phải kiểm tra lại địa chỉ', () => {
  assert.match(INVALID_JSON_MESSAGE, /không phải JSON/);
  assert.match(INVALID_JSON_MESSAGE, /địa chỉ máy chủ/);
});
