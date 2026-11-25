/**
 * Kiểm thử logic thuần cho nhóm Người học & Đăng ký khuôn mặt (`payload.ts`, `client.ts`, `errors.ts`).
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  DEFAULT_ENROLL_STEPS,
  normalizeEnrollStart,
  normalizeEnrollStatus,
  normalizePeople,
} from '../src/api/payload.ts';
import { createApiClient } from '../src/api/client.ts';
import { httpError, routeKey } from '../src/api/errors.ts';

function fakeFetch(handler) {
  const calls = [];
  const impl = async (url, init) => {
    calls.push({ url, method: init?.method, body: init?.body ?? null });
    const res = handler(url, init);
    return {
      ok: res.status >= 200 && res.status < 300,
      status: res.status,
      headers: { get: () => 'application/json' },
      text: async () => JSON.stringify(res.body),
    };
  };
  impl.calls = calls;
  return impl;
}

test('normalizePeople: danh sách hợp lệ + người đang chọn khớp id', () => {
  const view = normalizePeople({
    people: [
      { id: 'Huy', name: 'Nguyễn Huy', created_ts: 1763000000 },
      { id: 'Bao', name: 'Bảo', created_ts: null },
    ],
    selected: 'Huy',
  });
  assert.equal(view.people.length, 2);
  assert.equal(view.people[0].initial, 'H');
  assert.equal(view.people[1].initial, 'B');
  assert.equal(view.selectedId, 'Huy');
  assert.equal(view.selectedPerson?.name, 'Nguyễn Huy');
  assert.equal(view.selectedText, 'Nguyễn Huy');
});

test('normalizePeople: selected=null và selected mồ côi hiện đúng câu như Web Dashboard', () => {
  const none = normalizePeople({ people: [{ id: 'Huy', name: 'Huy' }], selected: null });
  assert.equal(none.selectedId, null);
  assert.equal(none.selectedText, 'Chưa chọn người đang học');

  const orphan = normalizePeople({ people: [{ id: 'Huy', name: 'Huy' }], selected: 'AiDo' });
  assert.equal(orphan.selectedPerson, null);
  assert.equal(orphan.selectedText, 'mã AiDo (không có trong danh sách)');
});

test('normalizePeople: bỏ qua bản ghi hỏng mà không vỡ cả danh sách', () => {
  const view = normalizePeople({
    people: [null, 'rac', { id: '  ' }, { id: 'Minh', name: 'Minh' }],
    selected: null,
  });
  assert.equal(view.people.length, 1);
  assert.equal(view.people[0].id, 'Minh');
});

test('normalizeEnrollStart: trả enrollId và rơi về 5 bước mặc định khi thiếu steps', () => {
  const s1 = normalizeEnrollStart({ ok: true, enroll_id: 'abc123', name: 'Minh', steps: ['Bước 1', 'Bước 2'] });
  assert.equal(s1.enrollId, 'abc123');
  assert.deepEqual(s1.steps, ['Bước 1', 'Bước 2']);

  const s2 = normalizeEnrollStart({ ok: true, enroll_id: 'xyz' });
  assert.deepEqual(s2.steps, [...DEFAULT_ENROLL_STEPS]);
});

test('normalizeEnrollStatus: running -> done -> failed xử lý đúng chấm tiến độ', () => {
  const running = normalizeEnrollStatus(
    { state: 'running', step_index: 2, samples: 1, samples_needed: 3 },
    DEFAULT_ENROLL_STEPS,
    'Minh',
  );
  assert.equal(running.headlineText, 'Quay sang trái');
  assert.equal(running.steps[0].done, true);
  assert.equal(running.steps[1].done, true);
  assert.equal(running.steps[2].current, true);
  assert.equal(running.steps[3].done, false);

  const done = normalizeEnrollStatus(
    { state: 'done', step_index: 4, samples: 3, samples_needed: 3 },
    DEFAULT_ENROLL_STEPS,
    'Minh',
  );
  assert.equal(done.progressRatio, 1);
  assert.equal(done.steps.every((s) => s.done && !s.current), true);
  assert.match(done.samplesText, /Minh/);

  const failed = normalizeEnrollStatus(
    { state: 'failed', step_index: 2, samples: 1, samples_needed: 3, error: 'Không đủ mẫu hợp lệ (1/3).' },
    DEFAULT_ENROLL_STEPS,
    'Minh',
  );
  // Phiên đã dừng: không còn chấm nào mang `current = true`.
  assert.equal(failed.steps.some((s) => s.current), false);
  assert.equal(failed.steps[0].done, true);
  assert.equal(failed.steps[1].done, true);
  assert.equal(failed.steps[2].done, false);
  assert.match(failed.hintText, /Không đủ mẫu hợp lệ/);
});

test('ApiClient people & enroll: gọi đúng phương thức, URL đã mã hoá và thân JSON', async () => {
  const fetchImpl = fakeFetch((url) => {
    if (url.endsWith('/api/people')) return { status: 201, body: { ok: true, enroll_id: 'e1' } };
    return { status: 200, body: { ok: true } };
  });
  const client = createApiClient('http://192.168.17.111:8000');

  await client.getPeople({ fetchImpl });
  await client.selectPerson('Bảo Anh', { fetchImpl });
  await client.selectPerson(null, { fetchImpl });
  await client.deletePerson('Bảo Anh', { fetchImpl });
  await client.startEnroll('Minh', { fetchImpl });
  await client.getEnrollStatus('e-01', { fetchImpl });
  await client.cancelEnroll('e-01', { fetchImpl });

  assert.deepEqual(fetchImpl.calls, [
    { url: 'http://192.168.17.111:8000/api/people', method: 'GET', body: null },
    { url: 'http://192.168.17.111:8000/api/select', method: 'POST', body: '{"person_id":"Bảo Anh"}' },
    { url: 'http://192.168.17.111:8000/api/select', method: 'POST', body: '{"person_id":null}' },
    { url: 'http://192.168.17.111:8000/api/people/B%E1%BA%A3o%20Anh', method: 'DELETE', body: null },
    { url: 'http://192.168.17.111:8000/api/people', method: 'POST', body: '{"name":"Minh"}' },
    { url: 'http://192.168.17.111:8000/api/enroll/e-01', method: 'GET', body: null },
    { url: 'http://192.168.17.111:8000/api/enroll/e-01/cancel', method: 'POST', body: '{}' },
  ]);
});

test('routeKey & httpError: gom đường dẫn động của /api/people/<id> và /api/enroll/<id>', () => {
  assert.equal(routeKey('/api/people/Minh'), '/api/people');
  assert.equal(routeKey('/api/enroll/abc123/cancel'), '/api/enroll');
  assert.match(httpError(503, null, '/api/people/Minh').message, /Tính năng người học/);
  assert.match(httpError(404, null, '/api/enroll/abc123').message, /phiên đăng ký khuôn mặt/);
});
