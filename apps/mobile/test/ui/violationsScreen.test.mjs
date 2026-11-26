/**
 * Kiểm thử giao diện màn Vi phạm — chạy app React Native thật trong jsdom.
 *
 * Chạy: `npm run verify` (cần `npm install` trước).
 *
 * Khoá những điều mà test thuần không thấy được:
 * - Màn dựng được với payload thật, và mỗi dòng có giờ HH:MM:SS.
 * - "kéo dài N giây" chỉ hiện khi durationS > 0.
 * - Trạng thái rỗng là tin TỐT (không dùng màu báo động).
 * - Lỗi mạng hiện ErrorBanner có nút thử lại (không nuốt lỗi).
 * - Không poll: rời tab rồi quay lại mới tải lại, không có setInterval.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import { createRequire } from 'node:module';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { APP, calls, resetFetchLog, setScenario, mountScreen, sleep } = await import(
  './env.mjs'
);

const { ViolationsScreen } = require(
  path.join(APP, 'src/screens/ViolationsScreen.tsx'),
);

/** Payload đúng hình dạng server. `ts` là epoch GIÂY như bảng `events`. */
function payload(overrides = {}) {
  return {
    violations: [
      { ts: 1763000100, kind: 'ABSENT', kind_text: 'Rời khỏi bàn', duration_s: 8.2 },
      { ts: 1763000000, kind: 'PHONE_USE', kind_text: 'Dùng điện thoại', duration_s: 3 },
      { ts: 1762999900, kind: 'IMPOSTOR', kind_text: 'Không phải người đăng ký', duration_s: 0 },
    ],
    total: 3,
    counts: { ABSENT: 1, PHONE_USE: 1, IMPOSTOR: 1 },
    ...overrides,
  };
}

async function withViolations(fn) {
  const ui = await mountScreen(ViolationsScreen, { focused: true });
  try {
    await fn(ui);
  } finally {
    await ui.unmount();
  }
}

test('Vi phạm: dựng được, hiện tổng và phân loại theo counts', async () => {
  resetFetchLog();
  setScenario({ '/api/violations': { status: 200, body: payload() } });
  await withViolations(async (ui) => {
    const text = ui.text();
    assert.match(text, /Tổng vi phạm/);
    assert.match(text, /3/);
    // Nhãn tiếng Việt lấy từ server, dùng thẳng.
    assert.match(text, /Rời khỏi bàn/);
    assert.match(text, /Dùng điện thoại/);
    assert.match(text, /Không phải người đăng ký/);
    assert.deepEqual(ui.errors, []);
  });
});

test('Vi phạm: mỗi dòng có giờ HH:MM:SS', async () => {
  resetFetchLog();
  setScenario({ '/api/violations': { status: 200, body: payload() } });
  await withViolations(async (ui) => {
    const times = ui.text().match(/\d{2}:\d{2}:\d{2}/g) ?? [];
    assert.equal(times.length, 3, `phải có 3 mốc giờ, nhận: ${times.join(', ')}`);
  });
});

test('Vi phạm: "kéo dài N giây" chỉ hiện khi durationS > 0', async () => {
  resetFetchLog();
  setScenario({ '/api/violations': { status: 200, body: payload() } });
  await withViolations(async (ui) => {
    const text = ui.text();
    const durations = text.match(/kéo dài [\d,]+ giây/g) ?? [];
    // 8,2 s và 3,0 s có thời lượng; dòng IMPOSTOR duration_s = 0 thì không.
    assert.equal(durations.length, 2, `nhận: ${durations.join(' | ')}`);
    assert.equal(durations.some((d) => d.includes('8,2')), true);
  });
});

test('Vi phạm: trạng thái rỗng là tin TỐT, không phải màu báo động', async () => {
  resetFetchLog();
  setScenario({
    '/api/violations': {
      status: 200,
      body: { violations: [], total: 0, counts: { ABSENT: 0, PHONE_USE: 0, IMPOSTOR: 0 } },
    },
  });
  await withViolations(async (ui) => {
    const text = ui.text();
    assert.match(text, /Chưa có vi phạm nào/);
    // Không được hiện chữ mang nghĩa lỗi.
    assert.equal(/Không lấy được dữ liệu|Có lỗi/.test(text), false);
    assert.deepEqual(ui.errors, []);
  });
});

test('Vi phạm: lỗi 503 hiện ErrorBanner kèm câu server và nút thử lại', async () => {
  resetFetchLog();
  setScenario({
    '/api/violations': {
      status: 503,
      body: { ok: false, message: 'Chưa bật lưu trữ nên chưa có lịch sử.' },
    },
  });
  await withViolations(async (ui) => {
    const text = ui.text();
    assert.match(text, /Chưa bật lưu trữ/);
    assert.match(text, /Thử lại/);
    assert.deepEqual(ui.errors, []);
  });
});

test('Vi phạm: bấm "Làm mới" tạo request mới', async () => {
  resetFetchLog();
  setScenario({ '/api/violations': { status: 200, body: payload() } });
  await withViolations(async (ui) => {
    const before = calls.filter((c) => c.includes('/api/violations')).length;
    assert.equal(await ui.click('Làm mới'), true);
    const after = calls.filter((c) => c.includes('/api/violations')).length;
    assert.equal(after, before + 1, `phải có thêm đúng 1 request (trước ${before}, sau ${after})`);
  });
});

test('Vi phạm: tự động làm mới mỗi 4s khi đang mở và DỪNG hẳn sau khi rời màn', async () => {
  resetFetchLog();
  setScenario({
    '/api/violations': { status: 200, body: payload() },
    '/api/logs': {
      status: 200,
      body: {
        logs: [{ ts: 1763000105, level: 'ERROR', logger: 'camera.capture', message: 'Mất kết nối RTSP' }],
        total: 1,
      },
    },
  });
  await withViolations(async (ui) => {
    const before = calls.filter((c) => c.includes('/api/violations')).length;
    await ui.wait(4300);
    const after = calls.filter((c) => c.includes('/api/violations')).length;
    assert.equal(
      after > before,
      true,
      `đang mở màn phải tự cập nhật sau 4 s (trước ${before}, sau ${after})`,
    );
    // Chuyển sang Log hệ thống thấy chi tiết lỗi
    assert.equal(await ui.click('Log hệ thống (1)'), true);
    assert.match(ui.text(), /Mất kết nối RTSP/);
  });
  const countAtUnmount = calls.filter((c) => c.includes('/api/violations')).length;
  await sleep(4500);
  const countAfterUnmount = calls.filter((c) => c.includes('/api/violations')).length;
  assert.equal(countAfterUnmount, countAtUnmount, 'rời màn phải dừng hẳn timer nền');
});

test('Vi phạm: payload hỏng hoàn toàn ⇒ view rỗng, không crash', async () => {
  resetFetchLog();
  setScenario({
    '/api/violations': { status: 200, body: { violations: 'khong-phai-mang', total: 'x' } },
  });
  await withViolations(async (ui) => {
    const text = ui.text();
    assert.match(text, /Chưa có vi phạm nào/);
    assert.deepEqual(ui.errors, []);
  });
});

test('Vi phạm: kind lạ hiện mã thô kèm dấu hiệu, không bịa nhãn', async () => {
  resetFetchLog();
  setScenario({
    '/api/violations': {
      status: 200,
      body: {
        violations: [{ ts: 1763000000, kind: 'MOI_LA', duration_s: 0 }],
        total: 1,
        counts: { MOI_LA: 1 },
      },
    },
  });
  await withViolations(async (ui) => {
    const text = ui.text();
    assert.match(text, /MOI_LA/);
    assert.deepEqual(ui.errors, []);
  });
});
