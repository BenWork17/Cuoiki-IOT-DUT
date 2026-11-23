/**
 * Test cho phần chuẩn hoá payload (`src/api/payload.ts`).
 *
 * Trọng tâm là hai quy tắc dễ làm sai và rất khó thấy bằng mắt trên màn hình
 * nhỏ: `fresh: false` ⇒ "Chưa có dữ liệu mới" (không lặp lại kết luận cũ) và
 * `stale` ⇒ không trình bày `state_text` như kết luận mới.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  NO_FRESH_TEXT,
  PAUSED_TEXT,
  STALE_TEXT,
  formatAge,
  formatClock,
  formatCountdown,
  formatDecimal,
  formatDuration,
  looksLikeStatus,
  normalizeSession,
  normalizeSignal,
  normalizeSignals,
  normalizeStatus,
  normalizeVoice,
  normalizeViolations,
  VIOLATION_KIND_ORDER,
  unknownText,
} from '../src/api/payload.ts';

/* ------------------------------------------------------------------ status */

test('normalizeStatus: đọc đủ trường của /api/status', () => {
  const view = normalizeStatus({
    state: 'GOOD',
    state_text: 'Tư thế tốt',
    score: 8.47,
    labels: ['HEAD_DOWN'],
    label_texts: ['Cúi đầu'],
    sitting_s: 95,
    distance_cm: 52.4,
    alert: null,
    message: '',
    muted: false,
    data_age_s: 0.4,
    stale: false,
    stream_enabled: true,
  });

  assert.equal(view.stateText, 'Tư thế tốt');
  assert.equal(view.state, 'GOOD');
  assert.equal(view.stale, false);
  // Một chữ số thập phân, dấu phẩy kiểu Việt Nam.
  assert.equal(view.scoreText, '8,5');
  assert.deepEqual(view.labels, ['Cúi đầu']);
  assert.equal(view.distanceText, '52 cm');
  assert.equal(view.sittingText, '1 phút 35 giây');
  assert.equal(view.streamEnabled, true);
  assert.equal(view.muted, false);
  assert.equal(view.tone, 'good');
});

test('normalizeStatus: stale=true thì KHÔNG hiện state_text như kết luận mới', () => {
  const view = normalizeStatus({
    state: 'GOOD',
    state_text: 'Tư thế tốt',
    stale: true,
    data_age_s: 42.5,
  });
  assert.equal(view.stateText, STALE_TEXT);
  assert.equal(view.stateText, 'Không nhận được dữ liệu mới');
  assert.equal(view.tone, 'warn');
  assert.match(view.ageText, /42,5/);
});

test('normalizeStatus: tự suy stale từ data_age_s khi server thiếu trường stale', () => {
  const fresh = normalizeStatus({ state: 'GOOD', data_age_s: 5 });
  assert.equal(fresh.stale, false);

  const old = normalizeStatus({ state: 'GOOD', data_age_s: 30 });
  assert.equal(old.stale, true);
  assert.equal(old.stateText, STALE_TEXT);
});

test('normalizeStatus: chưa từng có dữ liệu (data_age_s null) là stale', () => {
  const view = normalizeStatus({ state: 'ABSENT', data_age_s: null });
  assert.equal(view.stale, true);
  assert.equal(view.stateText, STALE_TEXT);
  assert.equal(view.ageText, 'Chưa có dữ liệu');
});

test('normalizeStatus: PAUSED hiện "Chưa bắt đầu phiên học", KHÔNG phải "Không thấy người"', () => {
  const view = normalizeStatus({
    state: 'PAUSED',
    state_text: 'Chưa bắt đầu phiên học',
    stale: false,
    data_age_s: 0.2,
  });
  assert.equal(view.stateText, PAUSED_TEXT);
  assert.doesNotMatch(view.stateText, /Không thấy người/);
  assert.equal(view.tone, 'idle');
});

test('normalizeStatus: label_texts rỗng thì không có chip rỗng', () => {
  const view = normalizeStatus({ state: 'GOOD', label_texts: [], stale: false });
  assert.deepEqual(view.labels, []);
});

test('normalizeStatus: label_texts có phần tử rỗng hoặc trùng thì lọc sạch', () => {
  const view = normalizeStatus({
    state: 'WARN',
    label_texts: ['Cúi đầu', '', '  ', 'Cúi đầu', 'Ngồi quá gần'],
    stale: false,
  });
  assert.deepEqual(view.labels, ['Cúi đầu', 'Ngồi quá gần']);
});

test('normalizeStatus: state lạ hiện nguyên giá trị thô, không im lặng thành "Chưa rõ"', () => {
  const view = normalizeStatus({ state: 'NEW_STATE', stale: false });
  assert.equal(view.stateText, 'Chưa rõ (NEW_STATE)');
  assert.equal(view.tone, 'idle');
});

test('normalizeStatus: thiếu hẳn state thì nói rõ server không gửi', () => {
  const view = normalizeStatus({ stale: false });
  assert.match(view.stateText, /server không gửi giá trị/);
});

test('normalizeStatus: payload rỗng/null không làm crash', () => {
  for (const payload of [null, undefined, {}, [], 'x']) {
    const view = normalizeStatus(payload);
    assert.equal(view.stale, true);
    assert.equal(view.stateText, STALE_TEXT);
    assert.equal(view.scoreText, '–');
  }
});

test('normalizeStatus: điểm không phải số thì hiện "–", không hiện NaN', () => {
  const view = normalizeStatus({ state: 'GOOD', score: 'abc', stale: false });
  assert.equal(view.scoreText, '–');
  assert.doesNotMatch(view.scoreText, /NaN/);
});

test('normalizeStatus: distance_cm null thì không hiện "null cm"', () => {
  const view = normalizeStatus({ state: 'GOOD', distance_cm: null, stale: false });
  assert.equal(view.distanceText, null);
});

test('normalizeStatus: ABSENT có tông "bad" để không ai nhầm với tư thế tốt', () => {
  const view = normalizeStatus({ state: 'ABSENT', stale: false });
  assert.equal(view.tone, 'bad');
});

/* ------------------------------------------------------------- format phụ */

test('formatDecimal: dấu phẩy thập phân, làm tròn 1 chữ số', () => {
  assert.equal(formatDecimal(7.46), '7,5');
  assert.equal(formatDecimal(0), '0,0');
  assert.equal(formatDecimal(null), '–');
  assert.equal(formatDecimal(Number.NaN), '–');
});

test('formatAge: câu giống dashboard web', () => {
  assert.equal(formatAge(1.44), 'cập nhật 1,4 s trước');
  assert.equal(formatAge(null), '–');
});

test('unknownText: giữ nguyên giá trị thô để lỗi đánh máy còn thấy được', () => {
  assert.equal(unknownText('la_qua'), 'Chưa rõ (la_qua)');
  assert.match(unknownText(null), /server không gửi giá trị/);
  assert.match(unknownText(''), /server không gửi giá trị/);
});

test('formatDuration: đọc được bằng lời', () => {
  assert.equal(formatDuration(45), '45 giây');
  assert.equal(formatDuration(60), '1 phút');
  assert.equal(formatDuration(95), '1 phút 35 giây');
});

test('formatCountdown: hai chữ số, có số 0 dẫn đầu', () => {
  assert.equal(formatCountdown(300), '05:00');
  assert.equal(formatCountdown(59), '00:59');
  assert.equal(formatCountdown(0), '00:00');
  assert.equal(formatCountdown(null), '–');
  assert.equal(formatCountdown(-5), '–');
});

test('formatClock: luôn trả HH:MM:SS hai chữ số hoặc --:--:-- khi hỏng', async () => {
  const formatMod = await import('../src/api/format.ts');
  assert.equal(formatMod.formatClock, formatClock, 'payload.ts phải re-export format.ts');
  assert.equal(formatMod.formatDecimal, formatDecimal);
  const sample = new Date(2026, 4, 9, 7, 5, 3).getTime();
  assert.equal(formatClock(sample), '07:05:03');
  assert.equal(formatClock(Number.NaN), '--:--:--');
  assert.equal(formatClock(Number.POSITIVE_INFINITY), '--:--:--');
});

/* ---------------------------------------------------------------- session */

test('normalizeSession: phiên đang chạy có câu như dashboard web', () => {
  const view = normalizeSession({
    state: 'running',
    minutes: 45,
    remaining_s: 2699.4,
    elapsed_s: 0.6,
    ends_in_text: '44:59',
    finished_message: null,
    finish_text: null,
    default_minutes: 60,
    min_minutes: 1,
    max_minutes: 720,
  });
  assert.equal(view.state, 'running');
  assert.equal(view.running, true);
  assert.equal(view.stateText.includes('Đang trong phiên 45 phút'), true);
  assert.equal(view.countdownText, '44:59');
  assert.equal(view.countdownLabel, 'còn lại');
  assert.equal(view.finishText, null);
  assert.equal(view.defaultMinutes, 60);
  assert.equal(view.maxMinutes, 720);
});

test('normalizeSession: hết giờ dùng finish_text của server', () => {
  const view = normalizeSession({
    state: 'finished',
    minutes: 1,
    remaining_s: 0,
    elapsed_s: 60,
    finish_text: 'Đã hết giờ học. Nghỉ ngơi nhé.',
  });
  assert.equal(view.state, 'finished');
  assert.equal(view.finishText, 'Đã hết giờ học. Nghỉ ngơi nhé.');
  assert.equal(view.stateText, 'Đã hết giờ học. Nghỉ ngơi nhé.');
  assert.equal(view.countdownText, '00:00');
  assert.equal(view.countdownLabel, 'đã hết giờ');
});

test('normalizeSession: hết giờ mà server chỉ gửi finished_message thì vẫn dùng', () => {
  const view = normalizeSession({ state: 'finished', finished_message: 'Hết giờ.' });
  assert.equal(view.finishText, 'Hết giờ.');
});

test('normalizeSession: idle hiện "Chưa bắt đầu", đồng hồ "–"', () => {
  const view = normalizeSession({
    state: 'idle',
    minutes: 0,
    remaining_s: 0,
    elapsed_s: 0,
    default_minutes: 60,
  });
  assert.equal(view.running, false);
  assert.match(view.stateText, /Chưa bắt đầu/);
  assert.equal(view.countdownText, '–');
  assert.equal(view.countdownLabel, '');
  assert.equal(view.defaultMinutes, 60);
});

test('normalizeSession: state lạ không bị coi là đang chạy', () => {
  const view = normalizeSession({ state: 'paused' });
  assert.equal(view.state, 'unknown');
  assert.equal(view.running, false);
  assert.match(view.stateText, /Chưa rõ \(paused\)/);
});

test('normalizeSession: payload rỗng vẫn trả object dùng được', () => {
  const view = normalizeSession(null);
  assert.equal(view.state, 'unknown');
  assert.equal(view.running, false);
  assert.equal(view.defaultMinutes, null);
});

/* ---------------------------------------------------------------- signals */

test('normalizeSignal: presence co_mat, fresh ⇒ nhãn tiếng Việt của dashboard', () => {
  const row = normalizeSignal('presence', {
    state: 'co_mat',
    age_s: 0.2,
    age_limit_s: 3.0,
    fresh: true,
  });
  assert.equal(row.label, 'Có mặt');
  assert.equal(row.text, 'Đang trong khung hình');
  assert.equal(row.tone, 'good');
  assert.equal(row.glyph, '●');
  assert.match(row.ageText, /0,2/);
});

test('normalizeSignal: presence vang_mat ⇒ "Không thấy ai", tông bad', () => {
  const row = normalizeSignal('presence', { state: 'vang_mat', fresh: true, age_s: 1 });
  assert.equal(row.text, 'Không thấy ai');
  assert.equal(row.tone, 'bad');
});

test('normalizeSignal: phone dùng nhãn "Đang dùng"/"Không dùng"', () => {
  assert.equal(normalizeSignal('phone', { state: 'dung', fresh: true }).text, 'Đang dùng');
  assert.equal(normalizeSignal('phone', { state: 'khong_dung', fresh: true }).text, 'Không dùng');
});

test('normalizeSignal: identity MATCH kèm tên người', () => {
  const row = normalizeSignal('identity', {
    state: 'MATCH',
    age_s: 1.2,
    age_limit_s: 10,
    fresh: true,
    name: 'Minh',
    reason: 'khuôn mặt khớp',
  });
  assert.equal(row.text, 'Đúng người (Minh)');
  assert.equal(row.personName, 'Minh');
  assert.equal(row.reason, 'khuôn mặt khớp');
  assert.equal(row.tone, 'good');
});

test('normalizeSignal: identity MISMATCH/UNKNOWN', () => {
  assert.equal(normalizeSignal('identity', { state: 'MISMATCH', fresh: true }).text, 'Khác người');
  assert.equal(normalizeSignal('identity', { state: 'UNKNOWN', fresh: true }).text, 'Chưa nhận ra');
  assert.equal(normalizeSignal('identity', { state: 'unknown', fresh: true }).text, 'Chưa nhận ra');
});

test('normalizeSignal: fresh=false thì KHÔNG lặp lại state cũ — quy tắc quan trọng nhất', () => {
  const row = normalizeSignal('presence', {
    state: 'co_mat',
    age_s: 99,
    age_limit_s: 3,
    fresh: false,
  });
  assert.equal(row.text, NO_FRESH_TEXT);
  assert.equal(row.text, 'Chưa có dữ liệu mới');
  assert.equal(row.ageText, '–');
  assert.equal(row.fresh, false);
  assert.doesNotMatch(row.text, /Đang trong khung hình/);
});

test('normalizeSignal: thiếu hẳn trường fresh bị coi là cũ, không phải mới', () => {
  const row = normalizeSignal('presence', { state: 'co_mat' });
  assert.equal(row.fresh, false);
  assert.equal(row.text, NO_FRESH_TEXT);
});

test('normalizeSignal: `fresh: "true"` (chuỗi) không được coi là mới', () => {
  const row = normalizeSignal('presence', { state: 'co_mat', fresh: 'true' });
  assert.equal(row.fresh, false);
});

test('normalizeSignal: state lạ khi fresh hiện nguyên giá trị thô', () => {
  const row = normalizeSignal('presence', { state: 'dang_xu_ly', fresh: true });
  assert.equal(row.text, 'Chưa rõ (dang_xu_ly)');
});

test('normalizeSignal: payload null ⇒ dòng "chưa có dữ liệu mới", không crash', () => {
  const row = normalizeSignal('identity', null);
  assert.equal(row.text, NO_FRESH_TEXT);
  assert.equal(row.label, 'Danh tính');
});

test('normalizeSignals: luôn trả đủ 3 dòng đúng thứ tự', () => {
  const rows = normalizeSignals({
    presence: { state: 'co_mat', fresh: true },
    phone: { state: 'khong_dung', fresh: true },
    identity: { state: 'UNKNOWN', fresh: true },
  });
  assert.equal(rows.length, 3);
  assert.deepEqual(rows.map((r) => r.kind), ['presence', 'phone', 'identity']);
  assert.deepEqual(rows.map((r) => r.label), ['Có mặt', 'Điện thoại', 'Danh tính']);
});

test('normalizeSignals: thiếu mục nào thì mục đó "chưa có dữ liệu mới"', () => {
  const rows = normalizeSignals({});
  assert.equal(rows.length, 3);
  for (const row of rows) {
    assert.equal(row.text, NO_FRESH_TEXT);
    assert.equal(row.fresh, false);
  }
});

/* ------------------------------------------------------- kiểm tra kết nối */

test('looksLikeStatus: chỉ 200 thôi chưa đủ — phải đúng hình dạng /api/status', () => {
  assert.equal(looksLikeStatus({ state: 'GOOD', muted: false }), true);
  assert.equal(looksLikeStatus({ state: 'PAUSED', muted: true, score: 0 }), true);
  // Trang HTML của router wifi parse thành object không có `state`:
  assert.equal(looksLikeStatus({}), false);
  assert.equal(looksLikeStatus({ muted: false }), false);
  assert.equal(looksLikeStatus({ state: 'GOOD' }), false);
  assert.equal(looksLikeStatus(null), false);
  assert.equal(looksLikeStatus([]), false);
  assert.equal(looksLikeStatus('ok'), false);
});

/* ------------------------------------------------------------------- voice */

// Hình dạng payload dưới đây chép từ mã nguồn server, không tự nghĩ ra:
//   speaker_alert.voice_report()  → {"voices": available_voices(...),
//                                    "fallbacks": dict(self._fallback_notes)}
//   voice_library.available_voices() → {voice: {"label", "dir", "clips",
//                                        "ready": bool, "missing": [kind]}}
//   speaker_alert:647-650, :665-668 → _fallback_notes[kind] = "Chưa có bản thu
//                                        <giọng> cho câu này nên tạm dùng giọng máy."
// Tức `fallbacks` là {loại câu cảnh báo: CÂU TIẾNG VIỆT}, KHÔNG phải {loại: mã giọng}.

/** Câu server thật sự gán vào `fallbacks`, dùng lại nguyên văn cho test. */
const FALLBACK_SENTENCE =
  'Chưa có bản thu giọng nam cho câu này nên tạm dùng giọng máy.';

test('normalizeVoice: đọc giọng đang dùng + danh sách có nhãn từ server', () => {
  const view = normalizeVoice({
    ok: true,
    available: true,
    voice: 'nu',
    voices: {
      nam: { label: 'Giọng nam', ready: true, missing: [] },
      nu: { label: 'Giọng nữ', ready: true, missing: [] },
      espeak: { label: 'Giọng máy', ready: true, missing: [] },
    },
    fallbacks: {},
  });
  assert.equal(view.available, true);
  assert.equal(view.currentVoice, 'nu');
  assert.equal(view.currentLabel, 'Giọng nữ');
  assert.deepEqual(
    view.voices.map((v) => v.id),
    ['nam', 'nu', 'espeak'],
  );
  assert.deepEqual(
    view.voices.map((v) => v.selected),
    [false, true, false],
  );
  assert.deepEqual(view.fallbackKinds, []);
  assert.equal(view.fallbackCount, 0);
  assert.equal(view.fallbackNote, null);
});

test('normalizeVoice: available=false KHÔNG dựng danh sách giọng', () => {
  const view = normalizeVoice({
    ok: true,
    available: false,
    voice: null,
    voices: { nam: { label: 'Giọng nam' } },
    fallbacks: {},
    message: 'Loa cảnh báo chưa được bật trong phiên chạy này.',
  });
  assert.equal(view.available, false);
  assert.deepEqual(view.voices, []);
  assert.equal(view.currentLabel, '–');
  assert.match(view.message, /Loa cảnh báo chưa được bật/);
});

test('normalizeVoice: thiếu bản thu đọc từ voices[ma].missing, KHÔNG suy từ fallbacks', () => {
  const view = normalizeVoice({
    available: true,
    voice: 'nam',
    voices: {
      nam: { label: 'Giọng nam', ready: false, missing: ['phone'] },
      espeak: { label: 'Giọng máy', ready: true, missing: [] },
    },
    fallbacks: { phone: FALLBACK_SENTENCE },
  });

  const nam = view.voices.find((v) => v.id === 'nam');
  const espeak = view.voices.find((v) => v.id === 'espeak');
  assert.equal(nam?.hasMissingClips, true, 'nam thiếu bản thu theo `missing`');
  assert.deepEqual(nam?.missingKinds, ['phone']);
  assert.equal(espeak?.hasMissingClips, false, 'espeak đủ bản thu nên không bị gắn chip');
});

test('normalizeVoice: fallbacks là {loại cảnh báo: CÂU TIẾNG VIỆT} — không phải mã giọng', () => {
  const view = normalizeVoice({
    available: true,
    voice: 'nam',
    voices: { nam: { label: 'Giọng nam', ready: false, missing: ['phone'] } },
    fallbacks: { phone: FALLBACK_SENTENCE },
  });
  // Key là loại câu cảnh báo.
  assert.deepEqual(view.fallbackKinds, ['phone']);
  assert.equal(view.fallbackCount, 1);
  // Value là câu tiếng Việt, hiện NGUYÊN VĂN.
  assert.equal(view.fallbackNote, FALLBACK_SENTENCE);
  // Và tuyệt đối không bị đọc thành mã giọng.
  assert.equal(
    view.voices.some((v) => v.id === FALLBACK_SENTENCE),
    false,
    'không được biến câu giải thích thành một giọng',
  );
  assert.doesNotMatch(view.fallbackNote, /^espeak$/);
});

test('normalizeVoice: nhiều fallbacks ⇒ fallbackNote lấy câu đầu, đếm đúng số', () => {
  const view = normalizeVoice({
    available: true,
    voice: 'nam',
    voices: { nam: { label: 'Giọng nam', ready: false, missing: ['phone', 'good'] } },
    fallbacks: {
      phone: FALLBACK_SENTENCE,
      good: 'Chưa có bản thu giọng nam cho câu này nên tạm dùng giọng máy.',
    },
  });
  assert.deepEqual(view.fallbackKinds, ['good', 'phone']);
  assert.equal(view.fallbackCount, 2);
  assert.equal(view.fallbackNote, FALLBACK_SENTENCE);
});

test('normalizeVoice: ready=false một mình cũng đủ báo thiếu bản thu', () => {
  const view = normalizeVoice({
    available: true,
    voice: 'nam',
    voices: { nam: { label: 'Giọng nam', ready: false } },
    fallbacks: {},
  });
  assert.equal(view.voices[0]?.hasMissingClips, true);
  assert.deepEqual(view.voices[0]?.missingKinds, []);
});

test('normalizeVoice: server thiếu label thì dùng nhãn dự phòng, không hiện mã thô', () => {
  const view = normalizeVoice({
    available: true,
    voice: 'espeak',
    voices: { espeak: {} },
    fallbacks: {},
  });
  assert.equal(view.currentLabel, 'Giọng máy');
  assert.equal(view.voices[0]?.label, 'Giọng máy');
});

test('normalizeVoice: mã giọng lạ hiện nguyên giá trị thô (không im lặng)', () => {
  const view = normalizeVoice({
    available: true,
    voice: 'gio_la',
    voices: {},
    fallbacks: {},
  });
  assert.match(view.currentLabel, /Chưa rõ \(gio_la\)/);
});

test('normalizeVoice: payload rỗng/null không crash', () => {
  for (const payload of [null, undefined, {}, 'x', []]) {
    const view = normalizeVoice(payload);
    assert.equal(view.available, false);
    assert.deepEqual(view.voices, []);
    assert.equal(view.currentVoice, null);
    assert.deepEqual(view.fallbackKinds, []);
    assert.equal(view.fallbackCount, 0);
    assert.equal(view.fallbackNote, null);
  }
});

test('normalizeVoice: voices sai kiểu (mảng) bị bỏ qua thay vì crash', () => {
  const view = normalizeVoice({ available: true, voice: 'nam', voices: ['nam'], fallbacks: {} });
  assert.deepEqual(view.voices, []);
});

test('normalizeVoice: missing sai kiểu bị bỏ qua, không crash', () => {
  const view = normalizeVoice({
    available: true,
    voice: 'nam',
    voices: { nam: { label: 'Giọng nam', missing: 'phone' } },
    fallbacks: {},
  });
  assert.deepEqual(view.voices[0]?.missingKinds, []);
  // `missing` sai kiểu nhưng không có `ready` ⇒ không kết luận thiếu.
  assert.equal(view.voices[0]?.hasMissingClips, false);
});

/* -------------------------------------------------------------- violations */

/** Payload đúng hình dạng server: `{violations, total, counts}`. */
function violationsPayload(overrides = {}) {
  return {
    violations: [
      {
        ts: 1763000000.5, // epoch GIÂY, như bảng `events` lưu
        kind: 'ABSENT',
        kind_text: 'Rời khỏi bàn học',
        duration_s: 8.2,
      },
      {
        ts: 1762990000,
        kind: 'PHONE_USE',
        kind_text: 'Dùng điện thoại',
        duration_s: 3,
      },
      {
        ts: 1762980000,
        kind: 'IMPOSTOR',
        kind_text: 'Không phải người đăng ký',
        duration_s: 0,
      },
    ],
    total: 3,
    counts: { ABSENT: 1, PHONE_USE: 1, IMPOSTOR: 1 },
    ...overrides,
  };
}

test('normalizeViolations: đọc đúng shape và quy ts giây → mili giây', () => {
  const view = normalizeViolations(violationsPayload());
  assert.equal(view.violations.length, 3);
  assert.equal(view.total, 3);

  const first = view.violations[0];
  assert.equal(first.kind, 'ABSENT');
  // Nhãn lấy NGUYÊN VĂN từ server, không tự dịch.
  assert.equal(first.kindText, 'Rời khỏi bàn học');
  assert.equal(first.durationS, 8.2);
  // 1763000000,5 giây ⇒ 1763000000500 ms.
  assert.equal(first.ts, 1763000000500);
  // Phải dựng được Date thật (màn hình dùng `new Date(ts)`).
  assert.equal(Number.isNaN(new Date(first.ts).getTime()), false);
});

test('normalizeViolations: ts dạng CHUỖI cũng đọc được', () => {
  const view = normalizeViolations({
    violations: [{ ts: '1763000000.5', kind: 'ABSENT', kind_text: 'Rời khỏi bàn học' }],
    total: 1,
    counts: { ABSENT: 1 },
  });
  assert.equal(view.violations.length, 1);
  assert.equal(view.violations[0].ts, 1763000000500);
});

test('normalizeViolations: ts đã là mili giây thì giữ nguyên', () => {
  const view = normalizeViolations({
    violations: [{ ts: 1763000000500, kind: 'ABSENT', kind_text: 'Rời khỏi bàn học' }],
  });
  assert.equal(view.violations[0].ts, 1763000000500);
});

test('normalizeViolations: bỏ bản ghi thiếu ts hoặc thiếu kind, KHÔNG ném', () => {
  const view = normalizeViolations({
    violations: [
      { ts: 1763000000, kind: 'ABSENT', kind_text: 'Rời khỏi bàn học' },
      { kind: 'PHONE_USE' }, // thiếu ts
      { ts: 1762990000 }, // thiếu kind
      { ts: null, kind: 'ABSENT' }, // ts null
      { ts: 'khong-phai-so', kind: 'ABSENT' }, // ts không phải số
      null,
      'chuoi',
      42,
      [],
    ],
    total: 9,
    counts: {},
  });
  // Chỉ một bản ghi đọc được — phần còn lại bị bỏ, không làm mất cả danh sách.
  assert.equal(view.violations.length, 1);
  assert.equal(view.violations[0].kind, 'ABSENT');
});

test('normalizeViolations: thiếu kind_text ⇒ kindText null, KHÔNG tự bịa nhãn', () => {
  const view = normalizeViolations({
    violations: [{ ts: 1763000000, kind: 'ABSENT' }],
  });
  assert.equal(view.violations[0].kindText, null);
  // Mã thô vẫn còn để màn hình hiện kèm dấu hiệu.
  assert.equal(view.violations[0].kind, 'ABSENT');
});

test('normalizeViolations: kind lạ giữ nguyên chuỗi, không crash', () => {
  const view = normalizeViolations({
    violations: [{ ts: 1763000000, kind: 'NEW_KIND', kind_text: 'Loại mới', duration_s: 2 }],
    total: 1,
    counts: { NEW_KIND: 1 },
  });
  assert.equal(view.violations[0].kind, 'NEW_KIND');
  assert.equal(view.violations[0].kindText, 'Loại mới');
  // Mã lạ vẫn hiện trong phân loại, xếp sau các mã đã biết.
  assert.equal(view.counts.some((c) => c.kind === 'NEW_KIND'), true);
});

test('normalizeViolations: duration_s thiếu hoặc sai kiểu ⇒ 0 (một lần bấm)', () => {
  const view = normalizeViolations({
    violations: [
      { ts: 1763000000, kind: 'ABSENT' },
      { ts: 1762990000, kind: 'ABSENT', duration_s: 'chuoi' },
      { ts: 1762980000, kind: 'ABSENT', duration_s: -5 },
      { ts: 1762970000, kind: 'ABSENT', duration_s: null },
    ],
  });
  assert.deepEqual(
    view.violations.map((v) => v.durationS),
    [0, 0, 0, 0],
  );
});

test('normalizeViolations: duration_s dạng chuỗi số vẫn đọc được', () => {
  const view = normalizeViolations({
    violations: [{ ts: 1763000000, kind: 'ABSENT', duration_s: '12.5' }],
  });
  assert.equal(view.violations[0].durationS, 12.5);
});

test('normalizeViolations: counts sắp theo thứ tự cố định, mã lạ xếp sau', () => {
  const view = normalizeViolations({
    violations: [],
    total: 6,
    counts: { NEW_KIND: 1, IMPOSTOR: 2, ABSENT: 3 },
  });
  const known = VIOLATION_KIND_ORDER.filter((k) => view.counts.some((c) => c.kind === k));
  assert.deepEqual(
    view.counts.slice(0, known.length).map((c) => c.kind),
    ['ABSENT', 'IMPOSTOR'],
  );
  // Mã lạ nằm cuối, không bị nuốt.
  assert.equal(view.counts.at(-1)?.kind, 'NEW_KIND');
});

test('normalizeViolations: thiếu counts thì tự đếm từ danh sách', () => {
  const view = normalizeViolations({
    violations: [
      { ts: 1763000000, kind: 'ABSENT', kind_text: 'Rời khỏi bàn học' },
      { ts: 1762990000, kind: 'ABSENT', kind_text: 'Rời khỏi bàn học' },
      { ts: 1762980000, kind: 'PHONE_USE', kind_text: 'Dùng điện thoại' },
    ],
  });
  const absent = view.counts.find((c) => c.kind === 'ABSENT');
  assert.equal(absent?.count, 2);
  assert.equal(absent?.kindText, 'Rời khỏi bàn học');
  assert.equal(view.counts.find((c) => c.kind === 'PHONE_USE')?.count, 1);
});

test('normalizeViolations: countsNonZero bỏ các mã bằng 0 (đầu màn không đầy chip 0)', () => {
  const view = normalizeViolations({
    violations: [],
    total: 2,
    counts: { ABSENT: 2, PHONE_USE: 0, IMPOSTOR: 0 },
  });
  assert.deepEqual(
    view.countsNonZero.map((c) => c.kind),
    ['ABSENT'],
  );
});

test('normalizeViolations: payload rỗng/null/sai kiểu ⇒ view rỗng hợp lệ, không ném', () => {
  for (const payload of [null, undefined, {}, 'chuoi', 42, [], { violations: 'khong-phai-mang' }]) {
    const view = normalizeViolations(payload);
    assert.deepEqual(view.violations, []);
    assert.equal(view.total, 0);
    assert.deepEqual(view.counts, []);
    assert.deepEqual(view.countsNonZero, []);
  }
});

test('normalizeViolations: total sai kiểu thì rơi về số dòng đọc được', () => {
  const view = normalizeViolations({
    violations: [
      { ts: 1763000000, kind: 'ABSENT' },
      { ts: 1762990000, kind: 'PHONE_USE' },
    ],
    total: 'nhieu',
  });
  assert.equal(view.total, 2);
});

test('normalizeViolations: counts sai kiểu (mảng) bị bỏ qua, tự đếm lại', () => {
  const view = normalizeViolations({
    violations: [{ ts: 1763000000, kind: 'ABSENT' }],
    counts: ['ABSENT'],
  });
  assert.equal(view.counts.find((c) => c.kind === 'ABSENT')?.count, 1);
});

test('normalizeViolations: dùng ĐÚNG nhãn server trả, không tự dịch mã', () => {
  // Ba chuỗi dưới đây là `VIOLATION_KIND_TEXT` của `web/app.py`, và đã được
  // xác nhận bằng cách gọi thật `GET /api/violations` trên Flask test_client
  // rồi đưa payload đó qua hàm này. Nếu ai đổi nhãn ở server mà không đổi ở
  // đây (hoặc ngược lại) thì test này đỏ — đó là mục đích của nó.
  const view = normalizeViolations({
    violations: [
      { ts: 1763000000, kind: 'ABSENT', kind_text: 'Rời khỏi bàn học' },
      { ts: 1762990000, kind: 'PHONE_USE', kind_text: 'Dùng điện thoại' },
      { ts: 1762980000, kind: 'IMPOSTOR', kind_text: 'Không phải người đăng ký' },
    ],
    total: 3,
    counts: { ABSENT: 1, PHONE_USE: 1, IMPOSTOR: 1 },
  });
  assert.deepEqual(
    view.violations.map((v) => v.kindText),
    ['Rời khỏi bàn học', 'Dùng điện thoại', 'Không phải người đăng ký'],
  );
});

test('normalizeViolations: ts epoch GIÂY của server đổi đúng sang mili giây', () => {
  // Giá trị thật lấy từ `events.ts` (Storage._clock = time.time). Nếu đổi nhầm
  // chiều (coi giây là ms) thì năm ra 1970 — test này bắt được.
  const view = normalizeViolations({
    violations: [{ ts: 1794587495.4890862, kind: 'ABSENT', kind_text: 'Rời khỏi bàn học' }],
  });
  const d = new Date(view.violations[0].ts);
  assert.equal(d.getFullYear() > 2020 && d.getFullYear() < 2100, true, `năm ${d.getFullYear()}`);
});
