/**
 * Kiểm thử giao diện & hook cho các màn hình đã sửa lỗi và gom logic dùng chung:
 * - StatusScreen: thang điểm 100 + đồng hồ HH:MM:SS.
 * - ControlScreen: đồng bộ lại `mutedOverride` khi vòng poll nhận trạng thái mới từ web.
 * - SettingsScreen: kiểm tra kết nối qua `createApiClient` tĩnh + lưu địa chỉ.
 * - `toPollFetcher`: phân biệt `cancelled` (`ignored: true`) với lỗi thật.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import { createRequire } from 'node:module';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { APP, calls, resetFetchLog, setScenario, mountScreen } = await import(
  './env.mjs'
);

const { StatusScreen } = require(path.join(APP, 'src/screens/StatusScreen.tsx'));
const { ControlScreen } = require(path.join(APP, 'src/screens/ControlScreen.tsx'));
const { SettingsScreen } = require(path.join(APP, 'src/screens/SettingsScreen.tsx'));
const { toPollFetcher } = require(path.join(APP, 'src/hooks/usePoll.ts'));
const { cancelledError, networkError } = require(path.join(APP, 'src/api/errors.ts'));

test('Trạng thái: hiện điểm trên "thang 100" và mốc giờ HH:MM:SS', async () => {
  resetFetchLog();
  setScenario({
    '/api/status': {
      status: 200,
      body: {
        state: 'GOOD',
        state_text: 'Tư thế tốt',
        score: 88.4,
        muted: false,
        stale: false,
        data_age_s: 0.3,
      },
    },
  });
  const ui = await mountScreen(StatusScreen, { focused: true });
  try {
    const text = ui.text();
    assert.ok(text.includes('88,4'), `phải hiện điểm 88,4. Nhận: ${text}`);
    assert.ok(text.includes('thang 100'), `phải ghi "thang 100". Nhận: ${text}`);
    assert.equal(/\bthang 10\b/.test(text), false, 'không còn ghi "thang 10"');
    assert.match(text, /Lần tải này: \d{2}:\d{2}:\d{2}/);
    assert.deepEqual(ui.errors, []);
  } finally {
    await ui.unmount();
  }
});

test('Điều khiển: mutedOverride tự xoá khi vòng poll nhận dữ liệu mới từ dashboard web', async () => {
  resetFetchLog();
  let serverMuted = false;
  setScenario((pathOnly) => {
    if (pathOnly === '/api/status') {
      return {
        status: 200,
        body: { state: 'GOOD', muted: serverMuted, stale: false, data_age_s: 0.2 },
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

  const ui = await mountScreen(ControlScreen, { focused: true });
  try {
    assert.ok(ui.text().includes('Đang bật tiếng'));

    // Bấm tắt tiếng trên điện thoại -> cập nhật tức thì nhờ `mutedOverride`.
    assert.equal(await ui.click('Tắt tiếng cảnh báo'), true);
    assert.ok(ui.text().includes('Đang tắt tiếng'));
    assert.ok(ui.text().includes('Đã tắt tiếng cảnh báo.'));
    assert.equal(calls.filter((c) => c.startsWith('POST /api/mute')).length, 1);

    // Người dùng bật lại tiếng trên dashboard web (`serverMuted = false`).
    // Ở nhịp poll kế tiếp (~2 s), điện thoại phải bỏ `mutedOverride` cũ và theo máy chủ.
    serverMuted = false;
    await ui.wait(2300);
    assert.ok(
      ui.text().includes('Đang bật tiếng'),
      `sau nhịp poll mới phải đồng bộ theo máy chủ. Nhận: ${ui.text()}`,
    );
    assert.deepEqual(ui.errors, []);
  } finally {
    await ui.unmount();
  }
});

test('Kết nối: Kiểm tra kết nối hoạt động qua createApiClient tĩnh', async () => {
  resetFetchLog();
  setScenario({
    '/api/status': {
      status: 200,
      body: { state: 'GOOD', muted: false, stale: false, data_age_s: 0.2, stream_enabled: true },
    },
  });
  const ui = await mountScreen(SettingsScreen, {});
  try {
    assert.equal(await ui.click('Kiểm tra kết nối'), true);
    const text = ui.text();
    assert.ok(text.includes('Kết nối tốt'), `phải báo Kết nối tốt. Nhận: ${text}`);
    assert.ok(text.includes('Tư thế tốt'));
    assert.deepEqual(ui.errors, []);
  } finally {
    await ui.unmount();
  }
});

test('toPollFetcher: chuyển cancelled thành ignored=true và lỗi khác thành ignored=false', async () => {
  const controller = new AbortController();
  const okFetcher = toPollFetcher(
    async () => ({ ok: true, data: { x: 2 }, status: 200 }),
    (raw) => raw.x * 10,
  );
  assert.deepEqual(await okFetcher(controller.signal), {
    ok: true,
    data: 20,
    ignored: false,
  });

  const cancelFetcher = toPollFetcher(async () => ({
    ok: false,
    error: cancelledError(),
    status: null,
  }));
  const cancelledRes = await cancelFetcher(controller.signal);
  assert.equal(cancelledRes.ok, false);
  assert.equal(cancelledRes.ignored, true);

  const netFetcher = toPollFetcher(async () => ({
    ok: false,
    error: networkError(),
    status: null,
  }));
  const netRes = await netFetcher(controller.signal);
  assert.equal(netRes.ok, false);
  assert.equal(netRes.ignored, false);
});
