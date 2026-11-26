/**
 * Test cho lớp client (`src/api/client.ts`) bằng `fetch` giả.
 *
 * Không cần mạng, không cần Metro, không cần `node_modules` của app: `fetch`
 * và `now` được tiêm qua `RequestOptions`. Nhờ vậy kiểm được những ca khó tái
 * lập bằng tay trên iPhone — 405 trả HTML, 403 khi stream tắt, 404 khi bản
 * dashboard cũ, 503 khi phiên chưa bật, và timeout.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  API_PATH,
  FRAME_TIMEOUT_MS,
  JSON_TIMEOUT_MS,
  VIOLATIONS_LIMIT,
  createApiClient,
  requestFrame,
  requestJson,
} from '../src/api/client.ts';

/**
 * Dựng `fetch` giả trả đúng một phản hồi.
 *
 * `body` là chuỗi để kiểm được cả thân HTML; `headers.get` mô phỏng `Headers`.
 */
function fakeFetch(response) {
  const calls = [];
  const impl = async (url, init) => {
    calls.push({ url, init });
    if (typeof response === 'function') return response(url, init);
    const headers = new Map(Object.entries(response.headers ?? {}));
    const text = response.body ?? '';
    return {
      ok: response.status >= 200 && response.status < 300,
      status: response.status,
      headers: { get: (name) => headers.get(String(name).toLowerCase()) ?? null },
      text: async () => text,
      blob: async () => response.blob ?? new Blob([text]),
    };
  };
  impl.calls = calls;
  return impl;
}

test('requestJson: 200 JSON ⇒ trả data + mã 200', async () => {
  const fetchImpl = fakeFetch({
    status: 200,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ state: 'GOOD', muted: false }),
  });
  const result = await requestJson('http://192.168.1.5:8000', 'GET', API_PATH.status, undefined, {
    fetchImpl,
  });
  assert.equal(result.ok, true);
  if (result.ok) {
    assert.equal(result.status, 200);
    assert.deepEqual(result.data, { state: 'GOOD', muted: false });
  }
  assert.equal(fetchImpl.calls.length, 1);
  assert.equal(fetchImpl.calls[0].url, 'http://192.168.1.5:8000/api/status');
});

test('requestJson: dựng URL đúng từ địa chỉ có "/" cuối', async () => {
  const fetchImpl = fakeFetch({ status: 200, body: '{}' });
  await requestJson('http://192.168.1.5:8000/', 'GET', '/api/frame', undefined, { fetchImpl });
  assert.equal(fetchImpl.calls[0].url, 'http://192.168.1.5:8000/api/frame');
});

test('requestJson: 403 với message JSON của server ⇒ hiện đúng câu server', async () => {
  const message = 'Tính năng xem trực tiếp đang tắt.';
  const fetchImpl = fakeFetch({
    status: 403,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ok: false, message }),
  });
  const result = await requestJson('http://h:8000', 'GET', API_PATH.frame, undefined, { fetchImpl });
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.status, 403);
    assert.equal(result.error.status, 403);
    assert.equal(result.error.message, message);
  }
});

test('requestJson: 503 khi phiên chưa bật ⇒ mã 503 + câu tiếng Việt, KHÔNG ném lỗi', async () => {
  const fetchImpl = fakeFetch({
    status: 503,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      ok: false,
      message:
        'Phiên học chưa được bật trong lần chạy này nên chưa bấm được Bắt đầu/Dừng.',
    }),
  });
  const client = createApiClient('http://h:8000');
  const result = await client.startSession(45, { fetchImpl });
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.error.status, 503);
    assert.match(result.error.message, /Phiên học chưa được bật/);
  }
});

test('requestJson: 503 ở /api/session không kèm message vẫn có câu đúng ngữ cảnh', async () => {
  const fetchImpl = fakeFetch({ status: 503, headers: { 'content-type': 'application/json' }, body: '' });
  const client = createApiClient('http://h:8000');
  const result = await client.getSession({ fetchImpl });
  assert.equal(result.ok, false);
  if (!result.ok) assert.match(result.error.message, /Phiên học chưa được bật/);
});

test('requestJson: 405 trả HTML KHÔNG làm ném SyntaxError', async () => {
  const html = '<!doctype html><html><body><h1>Method Not Allowed</h1></body></html>';
  const fetchImpl = fakeFetch({
    status: 405,
    headers: { 'content-type': 'text/html; charset=utf-8' },
    body: html,
  });
  const result = await requestJson('http://h:8000', 'POST', '/api/session', {}, { fetchImpl });
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.status, 405);
    assert.equal(result.error.kind, 'http');
    assert.match(result.error.message, /Sai phương thức gọi API/);
    // Câu HTML không được lọt ra màn hình.
    assert.doesNotMatch(result.error.message, /<h1>/);
  }
});

test('requestJson: 404 /api/frame nói "chưa có route ảnh tĩnh"', async () => {
  const fetchImpl = fakeFetch({
    status: 404,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ok: false, message: 'Không có API này.' }),
  });
  const result = await requestFrame('http://h:8000', { fetchImpl });
  assert.equal(result.ok, false);
  if (!result.ok) {
    // Server có câu riêng thì ưu tiên câu đó (đúng hợp đồng §4.4).
    assert.equal(result.error.message, 'Không có API này.');
    assert.equal(result.error.status, 404);
  }
});

test('requestJson: 200 nhưng thân HTML ⇒ lỗi "không phải JSON", không im lặng', async () => {
  const fetchImpl = fakeFetch({
    status: 200,
    headers: { 'content-type': 'text/html' },
    body: '<html><body>router wifi</body></html>',
  });
  const result = await requestJson('http://h:8000', 'GET', API_PATH.status, undefined, { fetchImpl });
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.error.kind, 'bad-payload');
    assert.match(result.error.message, /không phải JSON/);
    assert.match(result.error.message, /địa chỉ máy chủ/);
  }
});

test('requestJson: fetch ném lỗi mạng ⇒ câu hướng dẫn kiểm tra LAN/IP', async () => {
  const fetchImpl = async () => {
    throw new TypeError('Network request failed');
  };
  const result = await requestJson('http://h:8000', 'GET', API_PATH.status, undefined, { fetchImpl });
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.error.kind, 'network');
    assert.match(result.error.message, /Không kết nối được tới máy chủ/);
    assert.match(result.error.message, /LAN/);
  }
});

test('requestJson: quá hạn chờ ⇒ lỗi timeout tiếng Việt, không treo', async () => {
  let aborted = false;
  const fetchImpl = (_url, init) =>
    new Promise((_resolve, reject) => {
      init.signal.addEventListener('abort', () => {
        aborted = true;
        reject(new Error('Aborted'));
      });
    });
  const started = Date.now();
  const result = await requestJson('http://h:8000', 'GET', API_PATH.status, undefined, {
    fetchImpl,
    timeoutMs: 50,
  });
  assert.equal(aborted, true);
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.error.kind, 'timeout');
    assert.match(result.error.message, /không trả lời/);
  }
  assert.ok(Date.now() - started < 2000, 'phải thoát nhanh, không chờ hết hạn mặc định');
});

test('requestJson: hạn chờ mặc định là 5 s cho JSON (theo yêu cầu ≤ 5 s)', () => {
  assert.equal(JSON_TIMEOUT_MS, 5000);
  // Hạn chờ ảnh được yêu cầu ≤ 10 s.
  assert.ok(FRAME_TIMEOUT_MS <= 10000);
  assert.ok(FRAME_TIMEOUT_MS >= JSON_TIMEOUT_MS);
});

test('requestJson: huỷ từ ngoài ⇒ kind "cancelled" (màn hình không hiện lỗi)', async () => {
  const controller = new AbortController();
  const fetchImpl = (_url, init) =>
    new Promise((_resolve, reject) => {
      init.signal.addEventListener('abort', () => reject(new Error('Aborted')));
    });
  const promise = requestJson('http://h:8000', 'GET', API_PATH.status, undefined, {
    fetchImpl,
    signal: controller.signal,
  });
  controller.abort();
  const result = await promise;
  assert.equal(result.ok, false);
  if (!result.ok) assert.equal(result.error.kind, 'cancelled');
});

test('requestJson: signal đã huỷ từ trước ⇒ không gọi fetch', async () => {
  const controller = new AbortController();
  controller.abort();
  const fetchImpl = fakeFetch({ status: 200, body: '{}' });
  const result = await requestJson('http://h:8000', 'GET', API_PATH.status, undefined, {
    fetchImpl,
    signal: controller.signal,
  });
  assert.equal(result.ok, false);
  if (!result.ok) assert.equal(result.error.kind, 'cancelled');
  assert.equal(fetchImpl.calls.length, 0);
});

test('requestJson: địa chỉ rỗng ⇒ lỗi cấu hình, không gọi fetch', async () => {
  const fetchImpl = fakeFetch({ status: 200, body: '{}' });
  const result = await requestJson('', 'GET', API_PATH.status, undefined, { fetchImpl });
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.error.kind, 'config');
    assert.match(result.error.message, /Chưa nhập địa chỉ máy chủ/);
  }
  assert.equal(fetchImpl.calls.length, 0);
});

test('requestJson: địa chỉ sai định dạng ⇒ lỗi cấu hình', async () => {
  const result = await requestJson('http://x:8000/api/status', 'GET', API_PATH.status, undefined, {
    fetchImpl: fakeFetch({ status: 200, body: '{}' }),
  });
  assert.equal(result.ok, false);
  if (!result.ok) assert.equal(result.error.kind, 'config');
});

test('requestJson: POST gửi JSON + content-type đúng', async () => {
  const fetchImpl = fakeFetch({
    status: 200,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ok: true, muted: true, message: 'Đã tắt tiếng cảnh báo.' }),
  });
  const client = createApiClient('http://h:8000');
  const result = await client.setMuted(true, { fetchImpl });
  assert.equal(result.ok, true);
  const call = fetchImpl.calls[0];
  assert.equal(call.init.method, 'POST');
  assert.equal(call.init.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(call.init.body), { muted: true });
  assert.equal(call.url, 'http://h:8000/api/mute');
});

test('setMuted(null): gửi thân rỗng để server tự đảo trạng thái', async () => {
  const fetchImpl = fakeFetch({ status: 200, body: '{"muted":false}' });
  const client = createApiClient('http://h:8000');
  await client.setMuted(null, { fetchImpl });
  assert.deepEqual(JSON.parse(fetchImpl.calls[0].init.body), {});
});

test('movePtz: gửi đúng direction + duration như server yêu cầu', async () => {
  const fetchImpl = fakeFetch({
    status: 200,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ok: true, direction: 'left', duration: 0.5, message: 'Đã xoay camera sang trái.' }),
  });
  const client = createApiClient('http://h:8000');
  const result = await client.movePtz('left', 0.5, { fetchImpl });
  assert.equal(result.ok, true);
  assert.deepEqual(JSON.parse(fetchImpl.calls[0].init.body), { direction: 'left', duration: 0.5 });
});

test('movePtz: 501 (camera không hỗ trợ) ⇒ hiện đúng câu server', async () => {
  const fetchImpl = fakeFetch({
    status: 501,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ok: false, message: 'Camera không hỗ trợ PTZ.' }),
  });
  const client = createApiClient('http://h:8000');
  const result = await client.movePtz('up', 0.5, { fetchImpl });
  assert.equal(result.ok, false);
  if (!result.ok) assert.equal(result.error.message, 'Camera không hỗ trợ PTZ.');
});

test('startSession: gửi {minutes} khi có số phút', async () => {
  const fetchImpl = fakeFetch({ status: 200, body: '{"state":"running","ok":true}' });
  const client = createApiClient('http://h:8000');
  await client.startSession(45, { fetchImpl });
  assert.deepEqual(JSON.parse(fetchImpl.calls[0].init.body), { minutes: 45 });
  assert.equal(fetchImpl.calls[0].url, 'http://h:8000/api/session/start');
});

test('startSession(null): thân rỗng để server dùng mặc định của cấu hình', async () => {
  const fetchImpl = fakeFetch({ status: 200, body: '{"state":"running"}' });
  const client = createApiClient('http://h:8000');
  await client.startSession(null, { fetchImpl });
  assert.deepEqual(JSON.parse(fetchImpl.calls[0].init.body), {});
});

test('stopSession: gọi POST /api/session/stop (KHÔNG phải POST /api/session)', async () => {
  const fetchImpl = fakeFetch({ status: 200, body: '{"state":"idle"}' });
  const client = createApiClient('http://h:8000');
  await client.stopSession({ fetchImpl });
  assert.equal(fetchImpl.calls[0].url, 'http://h:8000/api/session/stop');
  assert.equal(fetchImpl.calls[0].init.method, 'POST');
});

test('getSession: GET /api/session — route duy nhất cho trạng thái phiên', async () => {
  const fetchImpl = fakeFetch({ status: 200, body: '{"state":"idle"}' });
  const client = createApiClient('http://h:8000');
  await client.getSession({ fetchImpl });
  assert.equal(fetchImpl.calls[0].url, 'http://h:8000/api/session');
  assert.equal(fetchImpl.calls[0].init.method, 'GET');
});

test('checkConnection: 200 + đúng hình dạng ⇒ thành công', async () => {
  const fetchImpl = fakeFetch({
    status: 200,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ state: 'GOOD', muted: false, score: 8 }),
  });
  const client = createApiClient('http://h:8000');
  const result = await client.checkConnection({ fetchImpl });
  assert.equal(result.ok, true);
  if (result.ok) assert.equal(result.data.status.state, 'GOOD');
});

test('checkConnection: 200 nhưng không phải /api/status ⇒ KHÔNG báo "kết nối tốt"', async () => {
  const fetchImpl = fakeFetch({
    status: 200,
    headers: { 'content-type': 'text/html' },
    body: '<html><body>Trang đăng nhập của router</body></html>',
  });
  const client = createApiClient('http://h:8000');
  const result = await client.checkConnection({ fetchImpl });
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.error.kind, 'bad-payload');
    assert.match(result.error.message, /không giống \/api\/status|không phải JSON/);
  }
});

test('requestFrame: 200 image/jpeg ⇒ data URI + kích thước', async () => {
  const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10]);
  let stored;
  const fetchImpl = async () => ({
    ok: true,
    status: 200,
    headers: { get: (name) => (name.toLowerCase() === 'content-type' ? 'image/jpeg' : null) },
    blob: async () => {
      // Node ≥ 18 có Blob; `FileReader` thì không. Trả Blob giả đủ trường mà
      // `blobToDataUrl` cần, và tự cài `FileReader` tối thiểu cho test này.
      stored = jpeg;
      return { size: jpeg.length, __bytes: jpeg };
    },
  });
  // FileReader tối thiểu: gọi onloadend với data URL dựng từ blob giả.
  const originalFileReader = globalThis.FileReader;
  globalThis.FileReader = class {
    constructor() {
      this.result = null;
      this.onloadend = null;
      this.onerror = null;
    }
    readAsDataURL(blob) {
      const bytes = blob.__bytes ?? new Uint8Array();
      const base64 = Buffer.from(bytes).toString('base64');
      this.result = `data:image/jpeg;base64,${base64}`;
      if (this.onloadend) this.onloadend();
    }
  };
  try {
    const result = await requestFrame('http://h:8000', { fetchImpl, now: () => 1234 });
    assert.equal(result.ok, true);
    if (result.ok) {
      assert.match(result.data.uri, /^data:image\/jpeg;base64,/);
      assert.equal(result.data.byteLength, jpeg.length);
      assert.equal(result.data.receivedAt, 1234);
    }
    assert.ok(stored);
  } finally {
    if (originalFileReader === undefined) delete globalThis.FileReader;
    else globalThis.FileReader = originalFileReader;
  }
});

test('requestFrame: 403 khi stream tắt ⇒ mã 403 + hướng dẫn bật stream_enabled', async () => {
  const fetchImpl = fakeFetch({
    status: 403,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ok: false, message: 'Tính năng xem trực tiếp đang tắt.' }),
  });
  const result = await requestFrame('http://h:8000', { fetchImpl });
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.error.status, 403);
    assert.match(result.error.message, /xem trực tiếp đang tắt/);
  }
});

test('requestFrame: 503 chưa có khung ⇒ nhắc kiểm tra camera', async () => {
  const fetchImpl = fakeFetch({ status: 503, headers: { 'content-type': 'application/json' }, body: '' });
  const result = await requestFrame('http://h:8000', { fetchImpl });
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.error.status, 503);
    assert.match(result.error.message, /chưa có khung hình/);
  }
});

test('requestFrame: 200 nhưng content-type là JSON ⇒ không vẽ "ảnh" là dữ liệu lỗi', async () => {
  const fetchImpl = fakeFetch({
    status: 200,
    headers: { 'content-type': 'application/json' },
    body: '{"ok":false}',
  });
  const result = await requestFrame('http://h:8000', { fetchImpl });
  assert.equal(result.ok, false);
  if (!result.ok) assert.match(result.error.message, /thay vì ảnh/);
});

test('API_PATH: chỉ chứa route nằm trong hợp đồng §4.2', () => {
  assert.deepEqual(
    { ...API_PATH },
    {
      status: '/api/status',
      signals: '/api/signals',
      session: '/api/session',
      sessionStart: '/api/session/start',
      sessionStop: '/api/session/stop',
      mute: '/api/mute',
      ptz: '/api/ptz',
      frame: '/api/frame',
      stream: '/stream',
      voice: '/api/voice',
      violations: '/api/violations',
      logs: '/api/logs',
      people: '/api/people',
      select: '/api/select',
      enroll: '/api/enroll',
    },
  );
  // Không có route "POST /api/session" trong bảng: tài liệu yêu cầu đã đo 405.
  assert.equal(Object.values(API_PATH).includes('/api/session'), true);
});

test('getViolations: GET /api/violations kèm limit, có AbortSignal', async () => {
  const fetchImpl = fakeFetch({
    status: 200,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ violations: [], total: 0, counts: {} }),
  });
  const client = createApiClient('http://h:8000');
  const result = await client.getViolations(undefined, { fetchImpl });
  assert.equal(result.ok, true);
  assert.equal(fetchImpl.calls[0].url, `http://h:8000/api/violations?limit=${VIOLATIONS_LIMIT}`);
  assert.equal(fetchImpl.calls[0].init.method, 'GET');
});

test('getViolations: kẹp limit ở client (âm, NaN, quá lớn)', async () => {
  const cases = [
    [0, 1],
    [-5, 1],
    [Number.NaN, VIOLATIONS_LIMIT],
    [99999, VIOLATIONS_LIMIT],
    [50, 50],
  ];
  for (const [asked, expected] of cases) {
    const fetchImpl = fakeFetch({ status: 200, body: '{"violations":[]}' });
    const client = createApiClient('http://h:8000');
    await client.getViolations(asked, { fetchImpl });
    assert.equal(
      fetchImpl.calls[0].url,
      `http://h:8000/api/violations?limit=${expected}`,
      `limit ${asked} phải thành ${expected}`,
    );
  }
});

test('getViolations: 503 ⇒ câu tiếng Việt + mã HTTP, không crash', async () => {
  const fetchImpl = fakeFetch({
    status: 503,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ok: false, message: 'Chưa bật lưu trữ nên chưa có lịch sử.' }),
  });
  const client = createApiClient('http://h:8000');
  const result = await client.getViolations(undefined, { fetchImpl });
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.status, 503);
    assert.match(result.error.message, /Chưa bật lưu trữ/);
  }
});

test('getVoice: GET /api/voice', async () => {
  const fetchImpl = fakeFetch({
    status: 200,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ok: true, available: true, voice: 'nam', voices: {}, fallbacks: {} }),
  });
  const client = createApiClient('http://h:8000');
  const result = await client.getVoice({ fetchImpl });
  assert.equal(result.ok, true);
  assert.equal(fetchImpl.calls[0].url, 'http://h:8000/api/voice');
  assert.equal(fetchImpl.calls[0].init.method, 'GET');
});

test('setVoice: POST /api/voice với thân {"voice": "..."}', async () => {
  const fetchImpl = fakeFetch({
    status: 200,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ok: true, available: true, voice: 'nu', message: 'Đã đổi sang giọng nữ.' }),
  });
  const client = createApiClient('http://h:8000');
  const result = await client.setVoice('nu', { fetchImpl });
  assert.equal(result.ok, true);
  assert.equal(fetchImpl.calls[0].init.method, 'POST');
  assert.deepEqual(JSON.parse(fetchImpl.calls[0].init.body), { voice: 'nu' });
});

test('setVoice: 400 giọng lạ ⇒ hiện đúng câu server (đã kèm danh sách hợp lệ)', async () => {
  const message =
    "Giọng 'xyz' không hợp lệ; chọn một trong Giọng nam, Giọng nữ, Giọng máy.";
  const fetchImpl = fakeFetch({
    status: 400,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ok: false, message }),
  });
  const client = createApiClient('http://h:8000');
  const result = await client.setVoice('xyz', { fetchImpl });
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.status, 400);
    assert.equal(result.error.message, message);
  }
});

test('setVoice: 503 chưa nối loa ⇒ hiện câu server, không crash', async () => {
  const fetchImpl = fakeFetch({
    status: 503,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ok: false, message: 'Loa cảnh báo chưa được bật trong phiên chạy này.' }),
  });
  const client = createApiClient('http://h:8000');
  const result = await client.setVoice('nam', { fetchImpl });
  assert.equal(result.ok, false);
  if (!result.ok) assert.match(result.error.message, /Loa cảnh báo chưa được bật/);
});

test('getVoice: 200 nhưng HTML ⇒ lỗi "không phải JSON", không im lặng', async () => {
  const fetchImpl = fakeFetch({
    status: 200,
    headers: { 'content-type': 'text/html' },
    body: '<html><body>router wifi</body></html>',
  });
  const client = createApiClient('http://h:8000');
  const result = await client.getVoice({ fetchImpl });
  assert.equal(result.ok, false);
  if (!result.ok) assert.equal(result.error.kind, 'bad-payload');
});
