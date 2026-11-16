/**
 * Kiểm thử giao diện màn Giọng đọc — chạy app React Native **thật** trong jsdom.
 *
 * Chạy: `npm run verify` (cần `npm install` trước).
 *
 * Hai lỗi mà vòng review thứ 3 bắt được, và các bài dưới đây khoá lại:
 *
 * 1. **Đọc sai hình dạng `fallbacks`.** Server
 *    (`speaker_alert.voice_report()` + `_fallback_notes`) trả
 *    `{loại_cảnh_báo: "<câu tiếng Việt>"}`, không phải `{loại: mã_giọng}`.
 *    Bản trước lấy value làm mã giọng nên in ra câu app tự ghép, sai nghĩa.
 * 2. **Nút "Gửi lại" chỉ tải lại danh sách.** `setChangingTo(null)` chạy
 *    trước `setActionError`, nên `onRetry` luôn rơi về `refresh()`. Nay có
 *    `lastVoice`, và bài kiểm đếm đúng số lần `POST /api/voice`.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import { createRequire } from 'node:module';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { APP, calls, resetFetchLog, setScenario, mountScreen } = await import(
  './env.mjs'
);

const { VoiceScreen } = require(path.join(APP, 'src/screens/VoiceScreen.tsx'));

/** Câu server thật gán vào `fallbacks`, chép từ `speaker_alert.py:647-650`. */
const FALLBACK_SENTENCE =
  'Chưa có bản thu giọng nam cho câu này nên tạm dùng giọng máy.';

/**
 * Payload `GET /api/voice` đúng hình dạng server: `voices[ma]` có
 * `label/ready/missing`, `fallbacks` là `{loại: câu tiếng Việt}`.
 */
function voicePayload(overrides = {}) {
  return {
    ok: true,
    available: true,
    voice: 'nam',
    voices: {
      nam: { label: 'Giọng nam', ready: false, missing: ['phone'] },
      nu: { label: 'Giọng nữ', ready: true, missing: [] },
      espeak: { label: 'Giọng máy', ready: true, missing: [] },
    },
    fallbacks: { phone: FALLBACK_SENTENCE },
    ...overrides,
  };
}

/** Dựng màn hình, tự động unmount kể cả khi assertion hỏng (không treo test). */
async function withVoiceScreen(fn) {
  const ui = await mountScreen(VoiceScreen, { focused: true });
  try {
    await fn(ui);
  } finally {
    await ui.unmount();
  }
}

test('Giọng đọc: hiện nguyên văn câu server gửi trong `fallbacks`', async () => {
  resetFetchLog();
  setScenario({ '/api/voice': { status: 200, body: voicePayload() } });
  await withVoiceScreen(async (ui) => {
    const text = ui.text();
    assert.ok(
      text.includes(FALLBACK_SENTENCE),
      `phải hiện nguyên câu server gửi. Nhận: ${text.slice(0, 260)}`,
    );
    // Câu app tự ghép ở bản trước — không được xuất hiện nữa.
    assert.equal(
      text.includes('đang phát bằng'),
      false,
      'không được tự ghép câu "đang phát bằng <mã giọng>"',
    );
    assert.equal(text.includes('còn phải mượn:'), false);
    assert.deepEqual(ui.errors, []);
  });
});

test('Giọng đọc: chip "Thiếu bản thu" theo `missing` của TỪNG giọng', async () => {
  resetFetchLog();
  setScenario({ '/api/voice': { status: 200, body: voicePayload() } });
  await withVoiceScreen(async (ui) => {
    const text = ui.text();
    assert.match(text, /Thiếu bản thu/);
    assert.match(text, /Thiếu bản thu cho: phone/);
    // Đúng 1 chip: chỉ giọng nam thiếu bản thu (missing: ['phone']).
    const chips = (text.match(/Thiếu bản thu(?! cho:)/g) ?? []).length;
    assert.equal(chips, 1, `chỉ giọng nam được gắn chip, nhận ${chips}`);
    assert.deepEqual(ui.errors, []);
  });
});

test('Giọng đọc: không có fallbacks thì không hiện khối cảnh báo mượn giọng', async () => {
  resetFetchLog();
  setScenario({
    '/api/voice': {
      status: 200,
      body: voicePayload({
        voices: {
          nam: { label: 'Giọng nam', ready: true, missing: [] },
          espeak: { label: 'Giọng máy', ready: true, missing: [] },
        },
        fallbacks: {},
      }),
    },
  });
  await withVoiceScreen(async (ui) => {
    assert.equal(ui.text().includes('Còn câu phải mượn giọng khác'), false);
    assert.deepEqual(ui.errors, []);
  });
});

test('Giọng đọc: available=false ⇒ hiện câu server, KHÔNG hiện nút chọn', async () => {
  resetFetchLog();
  const disabledMessage = 'Loa cảnh báo chưa được bật trong phiên chạy này.';
  setScenario({
    '/api/voice': {
      status: 200,
      body: {
        ok: true,
        available: false,
        voice: null,
        voices: {},
        fallbacks: {},
        message: disabledMessage,
      },
    },
  });
  await withVoiceScreen(async (ui) => {
    assert.ok(ui.text().includes(disabledMessage));
    const hasChooseButton = [...ui.host.querySelectorAll('[role="button"], button')].some(
      (e) => (e.textContent ?? '').trim().startsWith('Chọn'),
    );
    assert.equal(hasChooseButton, false, 'không được hiện nút chọn giọng khi chưa nối loa');
    assert.deepEqual(ui.errors, []);
  });
});

test('Giọng đọc: bấm "Gửi lại" GỬI LẠI lệnh đổi giọng, không phải chỉ tải lại', async () => {
  resetFetchLog();
  const badMessage =
    "Giọng 'nu' không hợp lệ; chọn một trong Giọng nam, Giọng nữ, Giọng máy.";
  let postCount = 0;
  // Lời gọi đầu là GET (lúc mount); từ lần thứ hai là POST và hỏng 400.
  setScenario((u) => {
    if (u !== '/api/voice') return undefined;
    postCount += 1;
    if (postCount === 1) return { status: 200, body: voicePayload() };
    return { status: 400, body: { ok: false, message: badMessage } };
  });

  await withVoiceScreen(async (ui) => {
    assert.equal(await ui.click('Chọn Giọng nữ'), true, 'phải bấm được nút chọn giọng nữ');

    const textAfterFail = ui.text();
    assert.ok(
      textAfterFail.includes(badMessage),
      `lỗi 400 phải hiện câu server. Nhận: ${textAfterFail.slice(0, 220)}`,
    );
    assert.ok(textAfterFail.includes('Không đổi được giọng'));

    const postsBefore = calls.filter((c) => c.startsWith('POST /api/voice')).length;
    assert.equal(postsBefore, 1, 'đã có đúng 1 lần POST hỏng');

    // Điểm mấu chốt: nút phải GỬI LẠI lệnh, không phải refresh.
    assert.equal(await ui.click('Gửi lại'), true, 'phải có nút "Gửi lại" trong banner lỗi');

    const postsAfter = calls.filter((c) => c.startsWith('POST /api/voice')).length;
    assert.equal(
      postsAfter,
      postsBefore + 1,
      `bấm "Gửi lại" phải tạo ĐÚNG một POST nữa tới /api/voice (trước ${postsBefore}, sau ${postsAfter})`,
    );
    // Và gửi lại đúng giọng vừa hỏng.
    const lastPost = calls.filter((c) => c.startsWith('POST /api/voice')).at(-1);
    assert.equal(lastPost, 'POST /api/voice {"voice":"nu"}');
    assert.deepEqual(ui.errors, []);
  });
});

test('Giọng đọc: đổi giọng thành công ⇒ hiện câu server + không còn banner lỗi', async () => {
  resetFetchLog();
  let phase = 'initial';
  setScenario((u) => {
    if (u !== '/api/voice') return undefined;
    if (phase === 'initial') return { status: 200, body: voicePayload() };
    return {
      status: 200,
      body: voicePayload({
        voice: 'nu',
        message: 'Đã đổi sang giọng nữ.',
        voices: {
          nam: { label: 'Giọng nam', ready: false, missing: ['phone'] },
          nu: { label: 'Giọng nữ', ready: true, missing: [] },
          espeak: { label: 'Giọng máy', ready: true, missing: [] },
        },
      }),
    };
  });
  await withVoiceScreen(async (ui) => {
    phase = 'after';
    await ui.click('Chọn Giọng nữ');
    const text = ui.text();
    assert.ok(text.includes('Đã đổi sang giọng nữ.'));
    assert.equal(text.includes('Không đổi được giọng'), false, 'không còn banner lỗi');
    assert.deepEqual(ui.errors, []);
  });
});
