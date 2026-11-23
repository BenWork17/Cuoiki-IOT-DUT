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
const { APP, act, calls, resetFetchLog, setScenario, mountScreen, sleep } = await import(
  './env.mjs'
);

const { CameraScreen } = require(path.join(APP, 'src/screens/CameraScreen.tsx'));
const { TabNavigator, TABS } = require(path.join(APP, 'src/navigation/TabNavigator.tsx'));
const { WebView } = require('./webview-stub.cjs');

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

test('Camera: chế độ Trực tiếp dựng đúng URL /stream và tự lùi sang Ảnh tĩnh khi WebView lỗi', async () => {
  resetFetchLog();
  setScenario({
    '/api/status': { status: 200, body: STATUS_OK },
    '/api/frame': { status: 503, body: { ok: false, message: 'Chưa có khung hình nào.' } },
  });
  await withCamera(async (ui) => {
    const webview = ui.host.querySelector('[data-testid="rn-webview"]');
    assert.ok(webview, 'mặc định mở ở chế độ Trực tiếp có WebView');
    assert.equal(webview.getAttribute('data-uri'), 'http://192.168.1.5:8000/stream');
    assert.ok(typeof WebView.__lastProps?.onError === 'function');

    await act(async () => {
      WebView.__lastProps.onError();
    });
    await ui.wait(120);

    assert.equal(
      ui.host.querySelector('[data-testid="rn-webview"]'),
      null,
      'khi WebView lỗi phải tự lùi khỏi /stream sang Ảnh tĩnh',
    );
    assert.match(ui.text(), /Không tải được luồng trực tiếp/);
    assert.ok(
      calls.some((c) => c.includes('/api/frame')),
      'sau khi lùi sang Ảnh tĩnh phải tự gọi /api/frame',
    );
    assert.deepEqual(ui.errors, []);
  });
});

test('Camera: stream_enabled=false từ /api/status ⇒ tự động lùi sang Ảnh tĩnh không cần bấm tay', async () => {
  resetFetchLog();
  setScenario({
    '/api/status': { status: 200, body: { ...STATUS_OK, stream_enabled: false } },
    '/api/frame': {
      status: 403,
      body: { ok: false, message: 'Tính năng xem trực tiếp đang tắt.' },
    },
  });
  await withCamera(async (ui) => {
    assert.equal(
      ui.host.querySelector('[data-testid="rn-webview"]'),
      null,
      'stream_enabled=false phải tự thoát chế độ WebView',
    );
    assert.ok(ui.text().includes('web.stream_enabled'));
    assert.deepEqual(ui.errors, []);
  });
});

test('Camera: hiển thị trực tiếp Trạng thái tư thế & lưới Bento 2×2 ngay trong tab Camera', async () => {
  resetFetchLog();
  let currentScore = 91.5;
  let currentState = 'GOOD';
  let currentLabels = [];
  setScenario((pathOnly) => {
    if (pathOnly === '/api/status') {
      return {
        status: 200,
        body: {
          state: currentState,
          label_texts: currentLabels,
          score: currentScore,
          sitting_s: 2520,
          distance_cm: 54,
          muted: false,
          stale: false,
          data_age_s: 0.2,
          stream_enabled: true,
        },
      };
    }
    return undefined;
  });

  await withCamera(async (ui) => {
    const text = ui.text();
    assert.ok(text.includes('Camera & Trạng thái'), `phải có tiêu đề gộp. Nhận: ${text}`);
    assert.ok(text.includes('Tư thế tốt'), `phải hiện trạng thái ngay dưới camera. Nhận: ${text}`);
    assert.ok(text.includes('✓ Đúng tư thế'), `phải hiện chip Đúng tư thế. Nhận: ${text}`);
    assert.ok(text.includes('91,5'), `phải hiện điểm tư thế 91,5. Nhận: ${text}`);
    assert.ok(text.includes('thang 100'), 'phải hiện thang 100');
    assert.ok(text.includes('42 phút'), `phải hiện thời lượng đã ngồi. Nhận: ${text}`);
    assert.ok(text.includes('54 cm'), `phải hiện khoảng cách. Nhận: ${text}`);
    assert.ok(text.includes('Đang bật'), `phải hiện trạng thái tiếng cảnh báo. Nhận: ${text}`);

    // Ở nhịp poll kế tiếp (~2 s), trạng thái đổi sang BAD -> màn Camera tự cập nhật trực tiếp.
    currentScore = 44.0;
    currentState = 'BAD';
    currentLabels = ['Cúi đầu quá thấp'];
    await ui.wait(2300);
    const nextText = ui.text();
    assert.ok(nextText.includes('Tư thế sai'), `phải tự cập nhật sang Tư thế sai. Nhận: ${nextText}`);
    assert.ok(nextText.includes('Cúi đầu quá thấp'), `phải hiện chip Cúi đầu quá thấp. Nhận: ${nextText}`);
    assert.equal(nextText.includes('✓ Đúng tư thế'), false, 'khi BAD không được còn chip Đúng tư thế');
    assert.ok(nextText.includes('44,0'), `phải tự cập nhật điểm mới. Nhận: ${nextText}`);
    assert.deepEqual(ui.errors, []);
  });
});

test('Camera: công tắc tiếng cảnh báo trong lưới Bento gọi POST /api/mute ngay tại chỗ', async () => {
  resetFetchLog();
  let serverMuted = false;
  setScenario((pathOnly) => {
    if (pathOnly === '/api/status') {
      return {
        status: 200,
        body: { ...STATUS_OK, score: 88, muted: serverMuted },
      };
    }
    if (pathOnly === '/api/mute') {
      serverMuted = true;
      return {
        status: 200,
        body: { ok: true, muted: true, message: 'Đã tắt tiếng cảnh báo.' },
      };
    }
    return undefined;
  });

  await withCamera(async (ui) => {
    assert.ok(ui.text().includes('Đang bật'));
    assert.equal(await ui.click('Tắt tiếng cảnh báo'), true);
    await sleep(60);
    assert.ok(ui.text().includes('Đang tắt'), `bấm xong phải chuyển sang Đang tắt. Nhận: ${ui.text()}`);
    assert.equal(calls.filter((c) => c.startsWith('POST /api/mute')).length, 1);
    assert.deepEqual(ui.errors, []);
  });
});

test('Camera: hiển thị 3 tín hiệu người học (Có mặt, Điện thoại, Người đang học) ngay dưới khung Camera', async () => {
  resetFetchLog();
  let phoneState = 'khong_dung';
  let phoneFresh = true;
  let identityState = 'MATCH';
  let identityName = 'Nguyễn Minh';

  setScenario((pathOnly) => {
    if (pathOnly === '/api/status') {
      return {
        status: 200,
        body: { ...STATUS_OK, state: 'GOOD', score: 92.0 },
      };
    }
    if (pathOnly === '/api/signals') {
      return {
        status: 200,
        body: {
          presence: { state: 'co_mat', age_s: 0.4, fresh: true },
          phone: { state: phoneState, age_s: 0.4, fresh: phoneFresh },
          identity: {
            state: identityState,
            name: identityName,
            age_s: 0.8,
            fresh: true,
          },
        },
      };
    }
    return undefined;
  });

  await withCamera(async (ui) => {
    const text = ui.text();
    assert.ok(text.includes('Tín hiệu người học'), `phải có cụm Tín hiệu người học. Nhận: ${text}`);
    assert.ok(text.includes('Đang trong khung hình'), `phải hiện Có mặt = Đang trong khung hình. Nhận: ${text}`);
    assert.ok(text.includes('Không dùng'), `phải hiện Điện thoại = Không dùng. Nhận: ${text}`);
    assert.ok(
      text.includes('Đúng người (Nguyễn Minh)'),
      `phải hiện tên người đang học. Nhận: ${text}`,
    );

    // Cụm 3 tín hiệu phải nằm NGAY DƯỚI khung Camera (trước khối Trạng thái tư thế)
    // để người dùng vừa xem camera vừa quan sát 3 thông số không phải kéo xuống.
    const idxCamera = text.indexOf('Mở trong trình duyệt');
    const idxSignals = text.indexOf('Tín hiệu người học');
    const idxPosture = text.indexOf('Tư thế tốt');
    assert.ok(
      idxCamera >= 0 && idxSignals > idxCamera && idxPosture > idxSignals,
      `thứ tự hiển thị phải là Camera -> 3 Tín hiệu -> Trạng thái tư thế (${idxCamera}, ${idxSignals}, ${idxPosture})`,
    );

    // Nhịp poll kế tiếp (~2 s): phát hiện dùng điện thoại + người lạ ngồi vào,
    // rồi nhịp nữa `phone.fresh = false` phải ghi "Chưa có dữ liệu mới".
    phoneState = 'dung';
    identityState = 'MISMATCH';
    identityName = '';
    await ui.wait(2300);
    const updatedText = ui.text();
    assert.ok(updatedText.includes('Đang dùng'), `phải báo Đang dùng điện thoại. Nhận: ${updatedText}`);
    assert.ok(updatedText.includes('Khác người'), `phải báo Khác người. Nhận: ${updatedText}`);

    phoneFresh = false;
    await ui.wait(2300);
    const staleSignalText = ui.text();
    assert.ok(
      staleSignalText.includes('Chưa có dữ liệu mới'),
      `khi fresh=false phải hiện "Chưa có dữ liệu mới" thay vì giữ trạng thái cũ. Nhận: ${staleSignalText}`,
    );
    assert.equal(
      staleSignalText.includes('Đang dùng'),
      false,
      'khi fresh=false tuyệt đối không được lặp lại "Đang dùng"',
    );
    assert.deepEqual(ui.errors, []);
  });
});

test('TabNavigator: gồm 6 tab gọn nhẹ và mở mặc định ở màn gộp Camera + 3 Tín hiệu + Trạng thái', async () => {
  resetFetchLog();
  setScenario({
    '/api/status': { status: 200, body: { ...STATUS_OK, state_text: 'Tư thế tốt', score: 95 } },
    '/api/signals': {
      status: 200,
      body: {
        presence: { state: 'co_mat', age_s: 0.3, fresh: true },
        phone: { state: 'khong_dung', age_s: 0.3, fresh: true },
        identity: { state: 'MATCH', name: 'Minh', age_s: 0.5, fresh: true },
      },
    },
  });
  assert.equal(TABS.length, 6, 'thanh điều hướng gọn thành 6 tab');
  assert.equal(TABS[0].key, 'camera', 'tab đầu tiên là camera');
  assert.equal(
    TABS.some((t) => t.key === 'status' || t.key === 'signals'),
    false,
    'không còn tab Trạng thái hay Tín hiệu tách rời',
  );

  const ui = await mountScreen(TabNavigator, {});
  try {
    const text = ui.text();
    assert.ok(text.includes('Camera & Trạng thái'));
    assert.ok(text.includes('Đang trong khung hình'));
    assert.ok(text.includes('Không dùng'));
    assert.ok(text.includes('Đúng người (Minh)'));
    assert.ok(text.includes('Tư thế tốt'));
    assert.ok(text.includes('95,0'));
    assert.deepEqual(ui.errors, []);
  } finally {
    await ui.unmount();
  }
});
