/** Test cho lớp dựng URL thuần (`src/api/url.ts`). */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildUrl,
  displayHost,
  normalizeBaseUrl,
} from '../src/api/url.ts';

test('normalizeBaseUrl: thêm http:// khi người dùng chỉ gõ IP và cổng', () => {
  const result = normalizeBaseUrl('192.168.1.5:8000');
  assert.equal(result.ok, true);
  if (result.ok) {
    assert.equal(result.baseUrl, 'http://192.168.1.5:8000');
    assert.deepEqual(result.warnings, []);
  }
});

test('normalizeBaseUrl: bỏ dấu "/" ở cuối và khoảng trắng thừa', () => {
  const result = normalizeBaseUrl('  http://192.168.1.5:8000/  ');
  assert.equal(result.ok, true);
  if (result.ok) assert.equal(result.baseUrl, 'http://192.168.1.5:8000');
});

test('normalizeBaseUrl: giữ https:// và cổng tuỳ chỉnh', () => {
  const result = normalizeBaseUrl('https://pi.local:8443');
  assert.equal(result.ok, true);
  if (result.ok) assert.equal(result.baseUrl, 'https://pi.local:8443');
});

test('normalizeBaseUrl: chuỗi rỗng bị từ chối kèm câu tiếng Việt', () => {
  const result = normalizeBaseUrl('   ');
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.match(result.message, /Chưa nhập địa chỉ máy chủ/);
  }
});

test('normalizeBaseUrl: scheme lạ bị từ chối', () => {
  const result = normalizeBaseUrl('ftp://192.168.1.5');
  assert.equal(result.ok, false);
  if (!result.ok) assert.match(result.message, /chỉ gọi được http:\/\/ hoặc https:\/\//);
});

test('normalizeBaseUrl: kèm đường dẫn bị từ chối vì app tự ghép /api', () => {
  const result = normalizeBaseUrl('http://192.168.1.5:8000/api/status');
  assert.equal(result.ok, false);
  if (!result.ok) assert.match(result.message, /không kèm đường dẫn/);
});

test('normalizeBaseUrl: kèm query bị từ chối', () => {
  const result = normalizeBaseUrl('http://192.168.1.5:8000?x=1');
  assert.equal(result.ok, false);
  if (!result.ok) assert.match(result.message, /\?/);
});

test('normalizeBaseUrl: localhost được nhận nhưng có cảnh báo trỏ vào chính điện thoại', () => {
  const result = normalizeBaseUrl('localhost:8000');
  assert.equal(result.ok, true);
  if (result.ok) {
    assert.equal(result.warnings.length, 1);
    assert.match(result.warnings[0], /trỏ vào chính chiếc điện thoại/);
  }
});

test('normalizeBaseUrl: 127.0.0.1 cũng bị cảnh báo', () => {
  const result = normalizeBaseUrl('http://127.0.0.1:8000');
  assert.equal(result.ok, true);
  if (result.ok) assert.equal(result.warnings.length, 1);
});

test('normalizeBaseUrl: IP LAN thường không có cảnh báo', () => {
  const result = normalizeBaseUrl('http://192.168.1.5:8000');
  assert.equal(result.ok, true);
  if (result.ok) assert.deepEqual(result.warnings, []);
});

test('buildUrl: ghép đường dẫn, tự thêm "/" khi thiếu', () => {
  assert.equal(
    buildUrl('http://192.168.1.5:8000', '/api/status'),
    'http://192.168.1.5:8000/api/status',
  );
  assert.equal(
    buildUrl('http://192.168.1.5:8000', 'api/status'),
    'http://192.168.1.5:8000/api/status',
  );
});

test('buildUrl: bỏ "/" thừa ở cuối địa chỉ gốc', () => {
  assert.equal(
    buildUrl('http://192.168.1.5:8000/', '/api/frame'),
    'http://192.168.1.5:8000/api/frame',
  );
});

test('buildUrl: query bỏ giá trị null/undefined thay vì in "undefined"', () => {
  assert.equal(
    buildUrl('http://h:8000', '/api/history', { range: '7d', x: undefined, y: null }),
    'http://h:8000/api/history?range=7d',
  );
});

test('buildUrl: query mã hoá ký tự đặc biệt', () => {
  assert.equal(
    buildUrl('http://h:8000', '/api/x', { q: 'a b&c' }),
    'http://h:8000/api/x?q=a%20b%26c',
  );
});

test('displayHost: bỏ scheme, giữ cổng', () => {
  assert.equal(displayHost('http://192.168.1.5:8000'), '192.168.1.5:8000');
  assert.equal(displayHost('https://pi.local:8443/'), 'pi.local:8443');
});
