/**
 * Kiểm thử giao diện thực trong jsdom cho:
 * 1. Màn hình Người học: chọn người học, bỏ chọn, xoá 2 bước an toàn,
 *    thêm người mới (quét khuôn mặt 5 bước -> hoàn tất -> chọn ngay),
 *    quét thất bại -> "Quét lại" mở phiên MỚI, và rời màn khi đang quét tự gửi `/cancel`.
 * 2. Giao diện Sáng / Tối: chuyển đổi qua nút gạt nhanh trên đầu trang & màn Kết nối,
 *    lưu bền vững xuống AsyncStorage (`posture-mobile/theme-mode/v1`) và cập nhật màu nền thật.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import { createRequire } from 'node:module';
import path from 'node:path';

const require = createRequire(import.meta.url);
const {
  APP,
  act,
  calls,
  primedStore,
  resetFetchLog,
  setScenario,
  mountScreen,
  sleep,
} = await import('./env.mjs');

const { PeopleScreen } = require(path.join(APP, 'src/screens/PeopleScreen.tsx'));
const { TabNavigator, TABS } = require(path.join(APP, 'src/navigation/TabNavigator.tsx'));
const { SettingsScreen } = require(path.join(APP, 'src/screens/SettingsScreen.tsx'));
const { lightColors, darkColors } = require(path.join(APP, 'src/theme.ts'));

function setInputText(host, ariaLabel, value) {
  const input = host.querySelector(`input[aria-label="${ariaLabel}"]`);
  assert.ok(input, `Phải tìm thấy ô nhập "${ariaLabel}"`);
  const nativeSetter = Object.getOwnPropertyDescriptor(
    globalThis.window.HTMLInputElement.prototype,
    'value',
  ).set;
  nativeSetter.call(input, value);
  input.dispatchEvent(new globalThis.Event('input', { bubbles: true }));
  input.dispatchEvent(new globalThis.Event('change', { bubbles: true }));
}

function hexToRgb(hex) {
  const clean = hex.replace('#', '');
  const num = parseInt(clean, 16);
  return `rgb(${(num >> 16) & 255}, ${(num >> 8) & 255}, ${num & 255})`;
}

test('TabNavigator: có tab Người học ngay cạnh Camera và lối tắt từ ô Danh tính chuyển sang Người học', async () => {
  primedStore.set('posture-mobile/theme-mode/v1', 'dark');
  resetFetchLog();
  setScenario({
    '/api/status': {
      status: 200,
      body: { state: 'GOOD', muted: false, stale: false, data_age_s: 0.2, stream_enabled: true },
    },
    '/api/signals': {
      status: 200,
      body: {
        presence: { state: 'co_mat', age_s: 0.3, fresh: true },
        phone: { state: 'khong_dung', age_s: 0.3, fresh: true },
        identity: { state: 'UNKNOWN', age_s: 0.5, fresh: true },
      },
    },
    '/api/people': {
      status: 200,
      body: { people: [{ id: 'Huy', name: 'Huy', created_ts: 1763000000 }], selected: null },
    },
  });

  assert.equal(TABS.some((t) => t.key === 'people'), true, 'phải có tab people trong TABS');
  const ui = await mountScreen(TabNavigator, {});
  try {
    assert.equal(await ui.click('Mở quản lý người học'), true, 'phải bấm được lối tắt Đổi / Thêm trên ô Danh tính');
    const text = ui.text();
    assert.ok(text.includes('Người đang học hiện tại'), `phải chuyển sang màn Người học. Nhận: ${text}`);
    assert.ok(text.includes('Huy'));
    assert.deepEqual(ui.errors, []);
  } finally {
    await ui.unmount();
  }
});

test('Người học: chọn người học, bỏ chọn và xoá xác nhận 2 bước', async () => {
  primedStore.set('posture-mobile/theme-mode/v1', 'dark');
  resetFetchLog();
  let people = [
    { id: 'Huy', name: 'Huy', created_ts: 1763000000 },
    { id: 'Bảo', name: 'Bảo', created_ts: 1763000100 },
  ];
  let selected = null;

  setScenario((pathOnly, _full, init) => {
    const method = init?.method ?? 'GET';
    if (pathOnly === '/api/people' && method === 'GET') {
      return { status: 200, body: { people, selected } };
    }
    if (pathOnly === '/api/select' && method === 'POST') {
      const body = JSON.parse(init.body);
      selected = body.person_id;
      return {
        status: 200,
        body: {
          ok: true,
          selected,
          message: selected ? 'Đã chọn người đang học.' : 'Đã bỏ chọn người đang học.',
        },
      };
    }
    if (pathOnly.startsWith('/api/people/') && method === 'DELETE') {
      const id = decodeURIComponent(pathOnly.slice('/api/people/'.length));
      people = people.filter((p) => p.id !== id);
      if (selected === id) selected = null;
      return { status: 200, body: { ok: true, message: 'Đã xoá người học.' } };
    }
    return undefined;
  });

  const ui = await mountScreen(PeopleScreen, { focused: true });
  try {
    assert.ok(ui.text().includes('Chưa chọn người đang học'));

    // 1. Chọn Bảo
    assert.equal(await ui.click('Chọn Bảo'), true);
    assert.ok(ui.text().includes('Đã chọn người đang học.'));
    assert.ok(calls.includes('POST /api/select {"person_id":"Bảo"}'));

    // 2. Bỏ chọn người đang học
    assert.equal(await ui.click('Bỏ chọn người đang học'), true);
    assert.ok(ui.text().includes('Đã bỏ chọn người đang học.'));
    assert.ok(calls.includes('POST /api/select {"person_id":null}'));

    // 3. Xoá Huy: bấm lần 1 hiện hộp xác nhận (chưa gửi DELETE), bấm Xác nhận mới xoá thật
    assert.equal(await ui.click('Xoá Huy'), true);
    assert.equal(
      calls.some((c) => c.startsWith('DELETE /api/people/')),
      false,
      'bấm Xoá lần đầu chỉ mở bước xác nhận, chưa được gọi DELETE ngay',
    );
    assert.equal(await ui.click('Xác nhận xoá Huy'), true);
    assert.ok(calls.some((c) => c.startsWith('DELETE /api/people/Huy')));
    assert.equal(ui.text().includes('Xoá hồ sơ khuôn mặt của “Huy”'), false);
    assert.ok(ui.text().includes('1 người'));
    assert.deepEqual(ui.errors, []);
  } finally {
    await ui.unmount();
  }
});

test('Người học: thêm người mới quét 5 bước -> thất bại bấm "Quét lại" mở phiên MỚI -> xong & chọn ngay', async () => {
  primedStore.set('posture-mobile/theme-mode/v1', 'dark');
  resetFetchLog();
  const people = [];
  let selected = null;
  let enrollCounter = 0;
  let pollTick = 0;

  setScenario((pathOnly, _full, init) => {
    const method = init?.method ?? 'GET';
    if (pathOnly === '/api/people' && method === 'GET') {
      return { status: 200, body: { people, selected } };
    }
    if (pathOnly === '/api/people' && method === 'POST') {
      const { name } = JSON.parse(init.body);
      enrollCounter += 1;
      pollTick = 0;
      return {
        status: 201,
        body: {
          ok: true,
          name,
          enroll_id: `enr-${enrollCounter}`,
          steps: ['Nhìn thẳng', 'Quay sang phải', 'Quay sang trái', 'Ngẩng lên', 'Cúi xuống'],
        },
      };
    }
    if (pathOnly === '/api/enroll/enr-1' && method === 'GET') {
      // Phiên 1 giả lập thiếu ánh sáng -> failed
      return {
        status: 200,
        body: {
          ok: true,
          enroll_id: 'enr-1',
          state: 'failed',
          step_index: 2,
          step_name: 'Quay sang trái',
          samples: 1,
          samples_needed: 3,
          error: 'Không đủ mẫu hợp lệ (1/3) sau 7.5 giây.',
        },
      };
    }
    if (pathOnly === '/api/enroll/enr-2' && method === 'GET') {
      pollTick += 1;
      if (pollTick === 1) {
        return {
          status: 200,
          body: {
            ok: true,
            enroll_id: 'enr-2',
            state: 'running',
            step_index: 1,
            step_name: 'Quay sang phải',
            samples: 2,
            samples_needed: 3,
            error: null,
          },
        };
      }
      if (!people.some((p) => p.id === 'Minh')) {
        people.push({ id: 'Minh', name: 'Minh', created_ts: 1763000200 });
      }
      return {
        status: 200,
        body: {
          ok: true,
          enroll_id: 'enr-2',
          state: 'done',
          step_index: 4,
          step_name: 'Cúi xuống',
          samples: 3,
          samples_needed: 3,
          error: null,
        },
      };
    }
    if (pathOnly === '/api/select' && method === 'POST') {
      selected = JSON.parse(init.body).person_id;
      return { status: 200, body: { ok: true, selected, message: 'Đã chọn người đang học.' } };
    }
    return undefined;
  });

  const ui = await mountScreen(PeopleScreen, { focused: true });
  try {
    await act(async () => {
      setInputText(ui.host, 'Tên người học mới', 'Minh');
    });
    assert.equal(await ui.click('Thêm & Quét khuôn mặt'), true);
    await ui.wait(200);

    // Phiên 1 failed -> hiện lý do từ server và nút Quét lại
    assert.ok(ui.text().includes('Không đủ mẫu hợp lệ (1/3)'));
    assert.equal(await ui.click('Quét lại'), true);

    // Đảm bảo Quét lại mở phiên MỚI (enr-2) chứ không poll lại enr-1
    await ui.wait(700);
    assert.ok(calls.some((c) => c.startsWith('GET /api/enroll/enr-2')));
    assert.ok(ui.text().includes('Khuôn mặt của Minh đã được lưu.'));

    // Chọn Minh ngay sau khi quét xong
    assert.equal(await ui.click('Chọn Minh làm người đang học'), true);
    assert.ok(calls.includes('POST /api/select {"person_id":"Minh"}'));
    assert.deepEqual(ui.errors, []);
  } finally {
    await ui.unmount();
  }
});

test('Người học: rời màn (unmount) khi đang quét tự động gọi POST /api/enroll/<id>/cancel', async () => {
  primedStore.set('posture-mobile/theme-mode/v1', 'dark');
  resetFetchLog();
  setScenario((pathOnly, _full, init) => {
    const method = init?.method ?? 'GET';
    if (pathOnly === '/api/people' && method === 'GET') {
      return { status: 200, body: { people: [], selected: null } };
    }
    if (pathOnly === '/api/people' && method === 'POST') {
      return {
        status: 201,
        body: { ok: true, name: 'Lan', enroll_id: 'enr-live', steps: ['Nhìn thẳng'] },
      };
    }
    if (pathOnly === '/api/enroll/enr-live' && method === 'GET') {
      return {
        status: 200,
        body: { ok: true, state: 'running', step_index: 0, samples: 0, samples_needed: 3 },
      };
    }
    if (pathOnly === '/api/enroll/enr-live/cancel' && method === 'POST') {
      return { status: 200, body: { ok: true, message: 'Đã huỷ.' } };
    }
    return undefined;
  });

  const ui = await mountScreen(PeopleScreen, { focused: true });
  await act(async () => {
    setInputText(ui.host, 'Tên người học mới', 'Lan');
  });
  assert.equal(await ui.click('Thêm & Quét khuôn mặt'), true);
  await ui.unmount();
  await sleep(50);

  assert.ok(
    calls.some((c) => c.startsWith('POST /api/enroll/enr-live/cancel')),
    `rời màn khi đang quét phải gửi cancel lên Pi. Calls: ${calls.join(' | ')}`,
  );
});

test('Giao diện Sáng / Tối: chuyển sang Giao diện sáng cập nhật màu nền thật và lưu AsyncStorage', async () => {
  primedStore.set('posture-mobile/theme-mode/v1', 'dark');
  resetFetchLog();
  setScenario({});

  const ui = await mountScreen(SettingsScreen, {});
  try {
    const screenRoot = ui.host.firstElementChild;
    assert.ok(screenRoot);
    assert.equal(
      globalThis.getComputedStyle(screenRoot).backgroundColor,
      hexToRgb(darkColors.background),
      'ban đầu ở chế độ Tối',
    );

    // Chuyển sang Giao diện sáng bằng nút chọn trong màn Kết nối
    assert.equal(await ui.click('Giao diện sáng'), true);
    assert.equal(primedStore.get('posture-mobile/theme-mode/v1'), 'light');
    assert.equal(
      globalThis.getComputedStyle(screenRoot).backgroundColor,
      hexToRgb(lightColors.background),
      'nền toàn màn phải đổi sang màu sáng #F0F2F5',
    );
    assert.ok(ui.text().includes('Đang dùng chế độ Sáng'));

    // Chuyển ngược về Tối bằng nút gạt nhanh góc trên màn hình
    assert.equal(await ui.click('Chuyển sang giao diện tối'), true);
    assert.equal(primedStore.get('posture-mobile/theme-mode/v1'), 'dark');
    assert.equal(
      globalThis.getComputedStyle(screenRoot).backgroundColor,
      hexToRgb(darkColors.background),
    );
    assert.deepEqual(ui.errors, []);
  } finally {
    await ui.unmount();
  }
});
