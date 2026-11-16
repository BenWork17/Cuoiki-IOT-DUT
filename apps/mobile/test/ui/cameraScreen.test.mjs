/**
 * Kiểm thử màn Ảnh camera — chạy app React Native thật trong jsdom.
 *
 * Chạy: `npm run verify` (cần `npm install` trước).
 *
 * Bài đáng chú ý nhất là bài cuối: lời gọi `/api/status` phụ của màn Camera
 * phải bị **huỷ thật** khi rời màn. Bản trước chỉ đặt cờ `cancelled = true`
 * rồi bỏ qua kết quả — request vẫn treo trên máy chủ Pi tới hết hạn chờ, mà
 * Pi là thứ đang phải lo camera. Đây là điều review vòng 3 bắt được.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import { createRequire } from 'node:module';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { APP, calls, resetFetchLog, setScenario, mountScreen, sleep } = await import(
  './env.mjs'
);

const { CameraScreen } = require(path.join(APP, 'src/screens/CameraScreen.tsx'));

const STATUS_OK = {
  state: 'GOOD',
  muted: false,
  stale: false,
  data_age_s: 0.2,
  stream_enabled: true,
};

/**
 * `requestFrame` cần `blob()` có `size` và một `FileReader`. Cài bản tối thiểu
 * quanh một lần chạy, rồi trả lại nguyên trạng.
 */
async function withFakeFileReader(fn) {
  const originalReader = globalThis.FileReader;
  const innerFetch = globalThis.fetch;
  globalThis.FileReader = class {
    constructor() {
      this.result = null;
      this.onloadend = null;
      this.onerror = null;
    }
    readAsDataURL() {
      this.result = 'data:image/jpeg;base64,AAAA';
      if (this.onloadend) this.onloadend();
    }
  };
  globalThis.fetch = async (url, init) => {
    const res = await innerFetch(url, init);
    if (String(url).includes('/api/frame') && res.ok) {
      return { ...res, blob: async () => ({ size: 4 }) };
    }
    return res;
  };
  try {
    await fn();
  } finally {
    globalThis.FileReader = originalReader;
    globalThis.fetch = innerFetch;
  }
}

/** Chạy thân bài kiểm rồi LUÔN unmount, kể cả khi assertion hỏng (không treo). */
async function withCamera(fn) {
  const ui = await mountScreen(CameraScreen, { focused: true });
  try {
    await fn(ui);
  } finally {
    await ui.unmount();
  }
}

/**
 * Mở màn Camera ở chế độ **Ảnh tĩnh**.
 *
 * Mặc định của màn là **Trực tiếp** (WebView đọc MJPEG). Ở chế độ đó KHÔNG có
 * vòng `setInterval` gọi `/api/frame`, nên mọi bài kiểm về poll/503/ảnh cũ
 * phải chuyển sang Ảnh tĩnh trước — nếu không chúng không còn kiểm đúng thứ
 * mình tuyên bố (đếm ra 0 request rồi kết luận sai).
 *
 * Nút chuyển chế độ nằm trong thẻ khung hình; `env.mjs` tìm nút theo nhãn.
 */
async function withCameraStill(fn) {
  const ui = await mountScreen(CameraScreen, { focused: true });
  try {
    await ui.click('Ảnh tĩnh');
    await sleep(50);
    await fn(ui);
  } finally {
    await ui.unmount();
  }
}

test('Camera: 503 liên tiếp KHÔNG làm dừng vòng tải ảnh', async () => {
  resetFetchLog();
  setScenario({
    '/api/status': { status: 200, body: STATUS_OK },
    '/api/frame': { status: 503, body: { ok: false, message: 'Chưa có khung hình nào.' } },
  });
  await withCameraStill(async (ui) => {
    const before = calls.filter((c) => c.includes('/api/frame')).length;
    await ui.wait(7000);
    const after = calls.filter((c) => c.includes('/api/frame')).length;
    assert.ok(
      after >= 4,
      `503 là "chưa có khung", không được dừng ở lần thứ 3 (trước ${before}, sau ${after})`,
    );
    assert.deepEqual(ui.errors, []);
  });
});

test('Camera: 403 (stream tắt) ⇒ hướng dẫn bật web.stream_enabled, không tự hỏi lại', async () => {
  resetFetchLog();
  setScenario({
    '/api/status': { status: 200, body: { ...STATUS_OK, stream_enabled: false } },
    '/api/frame': {
      status: 403,
      body: { ok: false, message: 'Tính năng xem trực tiếp đang tắt.' },
    },
  });
  await withCameraStill(async (ui) => {
    const text = ui.text();
    assert.ok(
      text.includes('web.stream_enabled'),
      `phải nhắc khoá cấu hình. Nhận: ${text.slice(0, 200)}`,
    );
    const before = calls.filter((c) => c.includes('/api/frame')).length;
    await ui.wait(2400);
    const after = calls.filter((c) => c.includes('/api/frame')).length;
    assert.equal(after, before, '403 là cấu hình: không được tự hỏi lại liên tục');
    assert.deepEqual(ui.errors, []);
  });
});

test('Camera: giữ khung cuối khi lượt sau lỗi + nhãn "Ảnh cuối lúc …"', async () => {
  resetFetchLog();
  let frameCount = 0;
  setScenario((u) => {
    if (u === '/api/status') return { status: 200, body: STATUS_OK };
    if (u === '/api/frame') {
      frameCount += 1;
      if (frameCount === 1) return { status: 200, body: 'JPEG', headers: 'image/jpeg' };
      return { status: 503, body: { ok: false, message: 'Chưa có khung hình nào.' } };
    }
    return undefined;
  });
  await withFakeFileReader(async () => {
    await withCameraStill(async (ui) => {
      await ui.wait(3000);
      const text = ui.text();
      assert.match(text, /Ảnh cuối lúc/, `phải nói rõ ảnh đang cũ. Nhận: ${text.slice(0, 200)}`);
      assert.deepEqual(ui.errors, []);
    });
  });
});

test('Camera: lời gọi /api/status bị HUỶ khi rời màn (không chỉ bỏ qua kết quả)', async () => {
  resetFetchLog();
  let statusSignal = null;
  let statusAborted = false;

  // Cài fetch riêng cho bài này để GIỮ được `signal`: treo mãi để mô phỏng máy
  // chủ không trả lời. Nếu màn không abort, promise này giữ nguyên tới hết hạn
  // chờ 5 s và máy chủ Pi vẫn phải phục vụ nó.
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    const u = String(url).replace(/^https?:\/\/[^/]+/, '');
    resetFetchLog();
    if (u === '/api/status' && init && init.signal) {
      statusSignal = init.signal;
      statusSignal.addEventListener('abort', () => {
        statusAborted = true;
      });
      return new Promise(() => {});
    }
    if (u === '/api/frame') {
      return {
        ok: false,
        status: 503,
        headers: { get: () => 'application/json' },
        text: async () => '{"ok":false}',
      };
    }
    return {
      ok: false,
      status: 404,
      headers: { get: () => 'application/json' },
      text: async () => '{}',
    };
  };

  try {
    const ui = await mountScreen(CameraScreen, { focused: true });
    await sleep(80);
    assert.ok(statusSignal !== null, 'phải bắt được signal của lời gọi /api/status');
    assert.equal(statusAborted, false, 'chưa rời màn thì chưa được huỷ');

    await ui.unmount();
    await sleep(80);

    assert.equal(
      statusAborted,
      true,
      'rời màn phải abort() lời gọi /api/status, không chỉ bỏ qua kết quả',
    );
  } finally {
    globalThis.fetch = previousFetch;
  }
});
