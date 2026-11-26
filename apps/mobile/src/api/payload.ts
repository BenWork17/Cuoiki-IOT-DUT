/**
 * Chuẩn hoá payload của `/api/status`, `/api/session`, `/api/signals` thành
 * kiểu dữ liệu mà màn hình vẽ được. **Không import react-native** — Node test
 * gọi thẳng các hàm ở đây.
 *
 * Vì sao phải có lớp này thay vì đọc `data.field` trong JSX:
 * 1. Nhãn tiếng Việt phải **khớp dashboard web**, không được tự đặt câu khác.
 *    Nguồn: `app.py` (`STATE_TEXT`, `LABEL_TEXT`) và
 *    `static/app.js` (`PRESENCE_TEXT`, `PHONE_TEXT`, `IDENTITY_TEXT`,
 *    `NO_FRESH_TEXT`). Gom về một chỗ để không có hai bảng lệch nhau.
 * 2. Hai quy tắc dễ làm sai và rất khó thấy khi chỉ đọc mã UI:
 *    - `fresh === false` ⇒ dòng đó phải nói **"Chưa có dữ liệu mới"**, tuyệt
 *      đối không lặp lại `state` cũ như vừa đo được (`people_service.py`
 *      docstring của `signals()`, `app.js:145-149`).
 *    - `stale === true` (hoặc `data_age_s > 10`) ⇒ **không** được trình bày
 *      `state_text` như kết luận mới; phải nói "Không nhận được dữ liệu mới".
 * 3. Thiếu trường không được suy diễn thành `ABSENT`/`MATCH`. Giá trị lạ cũng
 *      không được im lặng đổi thành "Chưa rõ": hiện nguyên giá trị thô kèm
 *      dấu hiệu, giống `unknownText()` của web — im lặng thì một lỗi đánh máy
 *      phía server trông y như "chưa đo được" và không ai sửa.
 */

import {
  formatAge,
  formatClock,
  formatCountdown,
  formatDate,
  formatDateTime,
  formatDecimal,
  formatDuration,
  unknownText,
} from './format';

export {
  formatAge,
  formatClock,
  formatCountdown,
  formatDate,
  formatDateTime,
  formatDecimal,
  formatDuration,
  unknownText,
};

/** Câu bắt buộc khi tín hiệu không còn mới (`app.js:124`). */
export const NO_FRESH_TEXT = 'Chưa có dữ liệu mới';

/** Câu bắt buộc khi dashboard không cập nhật (`index.html:112`). */
export const STALE_TEXT = 'Không nhận được dữ liệu mới';

/** Câu cho trạng thái `PAUSED` (`app.py:84`). */
export const PAUSED_TEXT = 'Chưa bắt đầu phiên học';

/** Ngưỡng "dữ liệu cũ" của server (`app.py:100`), dùng khi thiếu `stale`. */
export const STALE_AFTER_S = 10;

/** Nhãn trạng thái tư thế; khớp `STATE_TEXT` trong `app.py:77-85`. */
export const STATE_TEXT: Record<string, string> = {
  GOOD: 'Tư thế tốt',
  WARN: 'Cần chú ý',
  BAD: 'Tư thế sai',
  ABSENT: 'Không thấy người',
  PAUSED: PAUSED_TEXT,
};

/** Nhãn presence; khớp `PRESENCE_TEXT` trong `app.js:102-105`. */
export const PRESENCE_TEXT: Record<string, string> = {
  co_mat: 'Đang trong khung hình',
  vang_mat: 'Không thấy ai',
};

/** Nhãn phone; khớp `PHONE_TEXT` trong `app.js:112`. */
export const PHONE_TEXT: Record<string, string> = {
  khong_dung: 'Không dùng',
  dung: 'Đang dùng',
};

/** Nhãn identity; khớp `IDENTITY_TEXT` trong `app.js:115-119`. */
export const IDENTITY_TEXT: Record<string, string> = {
  MATCH: 'Đúng người',
  MISMATCH: 'Khác người',
  UNKNOWN: 'Chưa nhận ra',
};

/** Tông màu suy ra từ trạng thái; quyết định ở lớp dữ liệu, không ở JSX. */
export type Tone = 'good' | 'warn' | 'bad' | 'idle';

/** Một dòng tín hiệu đã sẵn sàng để vẽ. */
export type SignalRow = {
  /** `presence` | `phone` | `identity`. */
  kind: 'presence' | 'phone' | 'identity';
  /** Tên tiếng Việt của dòng: Có mặt / Điện thoại / Danh tính. */
  label: string;
  /** Câu kết luận, hoặc "Chưa có dữ liệu mới" khi `fresh === false`. */
  text: string;
  /** Tuổi tín hiệu dạng chữ ("cập nhật 1,4 s trước") hoặc "–". */
  ageText: string;
  /** `true` khi server nói tín hiệu còn mới. */
  fresh: boolean;
  /** Dấu hiệu hình học; không dùng emoji (đổi hình theo hệ điều hành). */
  glyph: string;
  tone: Tone;
  /** Tên người khi `identity.state === "MATCH"` có `name`. */
  personName?: string;
  /** Lý do server kèm theo cho identity (nếu có). */
  reason?: string;
};

/** Trạng thái sẵn sàng vẽ của màn 1. */
export type StatusView = {
  /** Nhãn trạng thái sẽ hiện; đã tính `stale` và `PAUSED`. */
  stateText: string;
  /** Mã thô của server, giữ để tra tone và để hiện khi cần. */
  state: string | null;
  /** `true` khi phải hiện cảnh báo dữ liệu cũ. */
  stale: boolean;
  /** "Cập nhật 1,4 s trước" hoặc "Đã cũ" hoặc "Chưa có dữ liệu". */
  ageText: string;
  /** `data_age_s` thô, `null` khi server chưa từng cập nhật. */
  dataAgeS: number | null;
  /** Điểm đã làm tròn 1 chữ số thập phân; `null` khi thiếu. */
  scoreText: string;
  /** Nhãn phân loại (`label_texts`), đã bỏ rỗng và trùng. */
  labels: string[];
  /** Khoảng cách (cm) đã format; `null` khi thiếu. */
  distanceText: string | null;
  /** True khi server bật xem trực tiếp (`stream_enabled`). */
  streamEnabled: boolean;
  /** Câu cảnh báo server đang phát (`message`), rỗng khi không có. */
  message: string;
  /** `alert` thô nếu server gửi. */
  alert: string | null;
  /** Số giây đã ngồi, đã format; `null` khi thiếu. */
  sittingText: string | null;
  muted: boolean;
  tone: Tone;
};

/** Trạng thái sẵn sàng vẽ của màn 3. */
export type SessionView = {
  state: 'running' | 'finished' | 'idle' | 'unknown';
  /** Câu mô tả trạng thái, ghép đúng như `app.js:614-634`. */
  stateText: string;
  running: boolean;
  /** Số phút đã đặt; `null` khi server không gửi. */
  minutes: number | null;
  /** "01:23" khi đang chạy/hết giờ, "–" khi nghỉ. */
  countdownText: string;
  /** Nhãn dưới đồng hồ: "còn lại" / "đã hết giờ" / "". */
  countdownLabel: string;
  /** `finish_text` của server khi đã hết giờ, `null` khi khác. */
  finishText: string | null;
  /** Giá trị mặc định/min/max cho ô nhập phút; `null` khi server không gửi. */
  defaultMinutes: number | null;
  minMinutes: number | null;
  maxMinutes: number | null;
};

/** Đọc một giá trị số hữu hạn; `null` cho mọi thứ khác (kể cả `NaN`). */
function finiteNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/** Đọc chuỗi đã trim; `null` khi không phải chuỗi hoặc rỗng. */
function trimmedString(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

/** Tông màu của `state` tư thế. */
function toneForState(state: string | null): Tone {
  switch (state) {
    case 'GOOD':
      return 'good';
    case 'WARN':
      return 'warn';
    case 'BAD':
    case 'ABSENT':
      return 'bad';
    default:
      return 'idle';
  }
}

/**
 * Chuẩn hoá `/api/status`.
 *
 * Quy tắc `stale`: server tự tính (`app.py:210`) và app tin server, nhưng nếu
 * vì lý do nào đó thiếu `stale` thì tự so `data_age_s` với ngưỡng 10 s. Khi
 * `stale` bật, `stateText` **không** được là kết luận mới — dùng đúng câu
 * "Không nhận được dữ liệu mới" như web (`index.html:112`).
 */
export function normalizeStatus(payload: unknown): StatusView {
  const data = (payload && typeof payload === 'object' ? payload : {}) as Record<
    string,
    unknown
  >;

  const rawState = trimmedString(data.state);
  const state = rawState ? rawState : null;
  const dataAgeS = finiteNumber(data.data_age_s);

  // `stale` do server quyết định; chỉ tự suy khi server không gửi trường này.
  const stale =
    typeof data.stale === 'boolean'
      ? data.stale
      : dataAgeS === null || dataAgeS > STALE_AFTER_S;

  const serverStateText = trimmedString(data.state_text);
  const knownStateText = state ? STATE_TEXT[state] : undefined;

  let stateText: string;
  if (stale) {
    stateText = STALE_TEXT;
  } else if (knownStateText) {
    stateText = knownStateText;
  } else if (serverStateText) {
    // Server có nhãn nhưng app chưa biết mã: tin nhãn server (nó là câu tiếng
    // Việt do chính server đặt), thay vì bịa.
    stateText = serverStateText;
  } else {
    stateText = unknownText(data.state);
  }

  let ageText: string;
  if (stale) {
    ageText = dataAgeS === null ? 'Chưa có dữ liệu' : `Đã cũ · ${formatAge(dataAgeS)}`;
  } else if (dataAgeS === null) {
    ageText = 'Chưa có dữ liệu';
  } else {
    ageText = formatAge(dataAgeS);
  }

  const score = finiteNumber(data.score);
  const distance = finiteNumber(data.distance_cm);
  const sitting = finiteNumber(data.sitting_s);

  const labels = Array.isArray(data.label_texts)
    ? Array.from(
        new Set(
          data.label_texts
            .map((item) => trimmedString(item))
            .filter((item): item is string => item !== null),
        ),
      )
    : [];

  return {
    stateText,
    state,
    stale,
    ageText,
    dataAgeS,
    scoreText: score === null ? '–' : formatDecimal(score),
    labels,
    distanceText: distance === null ? null : `${formatDecimal(distance, 0)} cm`,
    streamEnabled: data.stream_enabled === true,
    message: trimmedString(data.message) ?? '',
    alert: trimmedString(data.alert),
    sittingText: sitting === null ? null : formatDuration(sitting),
    muted: data.muted === true,
    tone: stale ? 'warn' : toneForState(state),
  };
}

/**
 * Chuẩn hoá `/api/session`.
 *
 * Câu chữ ghép đúng như `app.js:614-634`; `finish_text` của server được ưu
 * tiên hơn `finished_message` để app không bịa câu khác câu hệ thống vừa nói.
 */
export function normalizeSession(payload: unknown): SessionView {
  const data = (payload && typeof payload === 'object' ? payload : {}) as Record<
    string,
    unknown
  >;

  const rawState = trimmedString(data.state);
  const state: SessionView['state'] =
    rawState === 'running' || rawState === 'finished' || rawState === 'idle'
      ? rawState
      : 'unknown';
  const running = state === 'running';
  const minutes = finiteNumber(data.minutes);
  const remaining = finiteNumber(data.remaining_s);

  const finishText =
    trimmedString(data.finish_text) ?? trimmedString(data.finished_message);

  let stateText: string;
  if (running) {
    stateText =
      `Đang trong phiên ${minutes === null ? '–' : minutes} phút. ` +
      'Hệ thống đang theo dõi người học và điện thoại.';
  } else if (state === 'finished') {
    stateText =
      finishText ?? 'Đã hết giờ học. Bấm “Bắt đầu học” để vào phiên mới.';
  } else if (state === 'idle') {
    stateText = 'Chưa bắt đầu. Bấm “Bắt đầu học” để hệ thống theo dõi.';
  } else {
    stateText = unknownText(data.state);
  }

  let countdownText: string;
  let countdownLabel: string;
  if (running) {
    countdownText = trimmedString(data.ends_in_text) ?? formatCountdown(remaining);
    countdownLabel = 'còn lại';
  } else if (state === 'finished') {
    countdownText = '00:00';
    countdownLabel = 'đã hết giờ';
  } else {
    countdownText = '–';
    countdownLabel = '';
  }

  return {
    state,
    stateText,
    running,
    minutes,
    countdownText,
    countdownLabel,
    finishText: state === 'finished' ? finishText : null,
    defaultMinutes: finiteNumber(data.default_minutes),
    minMinutes: finiteNumber(data.min_minutes),
    maxMinutes: finiteNumber(data.max_minutes),
  };
}

/** Tên tiếng Việt của ba dòng tín hiệu (`index.html:186-204`). */
const SIGNAL_LABEL: Record<'presence' | 'phone' | 'identity', string> = {
  presence: 'Có mặt',
  phone: 'Điện thoại',
  identity: 'Danh tính',
};

/**
 * Dựng một dòng tín hiệu.
 *
 * Ba nhánh phải tách bạch, đúng thứ tự như `signalPresentation()` của
 * `app.js:145-184`:
 * 1. `fresh !== true` ⇒ "Chưa có dữ liệu mới", tuổi "–", **không** đọc
 *    `state` cũ (lỗi hay gặp nhất của app loại này).
 * 2. `fresh === true`, `state` đã biết ⇒ nhãn tiếng Việt **khớp dashboard**.
 * 3. Còn lại ⇒ hiện nguyên giá trị thô kèm "Chưa rõ (...)".
 */
export function normalizeSignal(
  kind: 'presence' | 'phone' | 'identity',
  payload: unknown,
): SignalRow {
  const data = (payload && typeof payload === 'object' ? payload : {}) as Record<
    string,
    unknown
  >;
  const label = SIGNAL_LABEL[kind];
  const fresh = data.fresh === true;

  if (!fresh) {
    return {
      kind,
      label,
      text: NO_FRESH_TEXT,
      ageText: '–',
      fresh: false,
      glyph: '…',
      tone: 'idle',
    };
  }

  const age = finiteNumber(data.age_s);
  const ageText = formatAge(age);
  const rawState = trimmedString(data.state);

  if (kind === 'identity') {
    const upper = (rawState ?? '').toUpperCase();
    const known = Object.prototype.hasOwnProperty.call(IDENTITY_TEXT, upper);
    const name = trimmedString(data.name);
    const base = known ? IDENTITY_TEXT[upper] : unknownText(data.state);
    return {
      kind,
      label,
      text: known && upper === 'MATCH' && name ? `${base} (${name})` : base,
      ageText,
      fresh: true,
      glyph: known ? (upper === 'MATCH' ? '●' : upper === 'MISMATCH' ? '○' : '?') : '•',
      tone: known ? (upper === 'MATCH' ? 'good' : upper === 'MISMATCH' ? 'bad' : 'warn') : 'idle',
      ...(known && upper === 'MATCH' && name ? { personName: name } : {}),
      ...(trimmedString(data.reason) ? { reason: trimmedString(data.reason) as string } : {}),
    };
  }

  const table = kind === 'presence' ? PRESENCE_TEXT : PHONE_TEXT;
  const state = (rawState ?? '').toLowerCase();
  const known = Object.prototype.hasOwnProperty.call(table, state);
  return {
    kind,
    label,
    text: known ? table[state] as string : unknownText(data.state),
    ageText,
    fresh: true,
    glyph: known ? (state === 'co_mat' || state === 'dung' ? '●' : '○') : '•',
    tone: known
      ? kind === 'presence'
        ? state === 'co_mat'
          ? 'good'
          : 'bad'
        : state === 'dung'
          ? 'warn'
          : 'good'
      : 'idle',
    ...(trimmedString(data.reason) ? { reason: trimmedString(data.reason) as string } : {}),
  };
}

/** Chuẩn hoá cả ba dòng của `/api/signals`; thiếu mục nào thì mục đó "chưa có". */
export function normalizeSignals(payload: unknown): SignalRow[] {
  const data = (payload && typeof payload === 'object' ? payload : {}) as Record<
    string,
    unknown
  >;
  return [
    normalizeSignal('presence', data.presence),
    normalizeSignal('phone', data.phone),
    normalizeSignal('identity', data.identity),
  ];
}

/**
 * Kiểm tra "kiểm tra kết nối" thành công: server trả 200 **và** payload đọc
 * được như một trạng thái. Chỉ 200 không đủ — một trang HTML của router wifi
 * cũng trả 200, và báo "kết nối tốt" lúc đó là nói dối người dùng.
 */
export function looksLikeStatus(payload: unknown): boolean {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return false;
  const data = payload as Record<string, unknown>;
  // `/api/status` luôn có `state` (chuỗi) và `muted` (bool) — `app.py:423-429`.
  return typeof data.state === 'string' && typeof data.muted === 'boolean';
}

/* ------------------------------------------------------------------- voice */

/** Một giọng đọc đã biết, kèm nhãn và tình trạng bản thu. */
export type VoiceOption = {
  /** Mã giọng (`nam` / `nu` / `espeak`) — đúng giá trị `POST /api/voice` nhận. */
  id: string;
  /** Nhãn tiếng Việt; lấy từ server (`VOICE_LABELS`), không tự đặt. */
  label: string;
  /** `true` khi giọng này đang được dùng. */
  selected: boolean;
  /**
   * `true` khi giọng này **thiếu bản thu** cho ít nhất một câu cảnh báo.
   *
   * Đọc từ `voices[ma].missing` / `voices[ma].ready` của server
   * (`voice_library.available_voices`), **không** suy từ `fallbacks` toàn cục.
   * Hai thứ trả lời hai câu hỏi khác nhau: `missing` nói giọng này thiếu gì,
   * còn `fallbacks` nói **câu nào đang phát** bằng giọng khác — và chỉ có nội
   * dung đó mới đúng cho giọng đang chọn.
   */
  hasMissingClips: boolean;
  /** Tên các câu còn thiếu bản thu cho giọng này (`missing` của server). */
  missingKinds: string[];
};

/** Trạng thái màn Giọng đọc. */
export type VoiceView = {
  /** `false` khi phiên chạy không nối loa cảnh báo (`app.py:664-674`). */
  available: boolean;
  /** Mã giọng đang dùng; `null` khi chưa rõ. */
  currentVoice: string | null;
  /** Nhãn của giọng đang dùng, để hiện to ngay trên cùng. */
  currentLabel: string;
  /** Danh sách giọng server báo có. Rỗng khi `available: false`. */
  voices: VoiceOption[];
  /** Câu giải thích của server khi `available: false`. */
  message: string;
  /**
   * Các **câu** đang phải mượn giọng khác — tức KEY của `fallbacks`.
   *
   * Không phải mã giọng: `fallbacks` của server là `{kind: "<câu tiếng Việt>"}`
   * (`speaker_alert._fallback_notes`), value là lời giải thích, không phải
   * `espeak`. Lấy value làm mã giọng là đọc sai hợp đồng.
   */
  fallbackKinds: string[];
  /** Số câu đang phải mượn giọng khác. */
  fallbackCount: number;
  /**
   * Câu giải thích **nguyên văn của server** cho ca mượn giọng, `null` khi
   * không có. Đây là câu tiếng Việt hoàn chỉnh server đã viết; app hiện thẳng
   * chứ không tự ghép câu của mình.
   */
  fallbackNote: string | null;
};

/** Tên tiếng Việt dự phòng khi server không gửi `label` cho một giọng. */
const VOICE_FALLBACK_LABEL: Record<string, string> = {
  nam: 'Giọng nam',
  nu: 'Giọng nữ',
  espeak: 'Giọng máy',
};

/**
 * Chuẩn hoá `GET/POST /api/voice`.
 *
 * Hình dạng **thật**, đối chiếu `speaker_alert.voice_report()` và
 * `voice_library.available_voices()`:
 *
 * ```jsonc
 * {
 *   "ok": true, "available": true, "voice": "nam",
 *   "voices": {
 *     "nam":    { "label": "Giọng nam", "ready": false, "missing": ["phone"] },
 *     "espeak": { "label": "Giọng máy", "ready": true,  "missing": [] }
 *   },
 *   // key = loại câu cảnh báo, value = CÂU TIẾNG VIỆT giải thích
 *   "fallbacks": { "phone": "Chưa có bản thu giọng nam cho câu này nên tạm dùng giọng máy." }
 * }
 * ```
 *
 * Bốn quy tắc:
 * 1. `available === false` ⇒ **không** dựng danh sách giọng. Server nói rõ
 *    "chưa nối loa"; hiện nút đổi giọng lúc đó là mời người dùng bấm vào một
 *    việc chắc chắn hỏng (yêu cầu §5.1 hàng 5).
 * 2. Nhãn giọng lấy **từ server**. Bảng dự phòng chỉ dùng khi server thiếu
 *    `label`, để không hiện mã thô `espeak` cho người dùng.
 * 3. Tình trạng thiếu bản thu đọc **từng giọng** (`missing`/`ready`), không
 *    suy từ `fallbacks` — xem `VoiceOption.hasMissingClips`.
 * 4. `fallbacks` cho biết **câu nào** đang mượn giọng, và value của nó là câu
 *    tiếng Việt hoàn chỉnh để hiện thẳng. Không tự ghép câu khác.
 */
export function normalizeVoice(payload: unknown): VoiceView {
  const data = (payload && typeof payload === 'object' ? payload : {}) as Record<
    string,
    unknown
  >;

  const available = data.available === true;
  const currentVoice = trimmedString(data.voice);
  const message = trimmedString(data.message) ?? '';

  const rawVoices = data.voices;
  const options: VoiceOption[] = [];
  if (available && rawVoices && typeof rawVoices === 'object' && !Array.isArray(rawVoices)) {
    for (const [id, value] of Object.entries(rawVoices as Record<string, unknown>)) {
      const info = (value && typeof value === 'object' ? value : {}) as Record<
        string,
        unknown
      >;
      const label =
        trimmedString(info.label) ?? VOICE_FALLBACK_LABEL[id] ?? unknownText(id);

      // `missing` là nguồn sự thật chính; `ready` là cờ tổng hợp server đã
      // tính sẵn. Dùng cả hai: thiếu `missing` thì `ready === false` vẫn phải
      // hiện cảnh báo, nếu không một đổi hình dạng nhỏ phía server sẽ làm
      // app im lặng bỏ qua tình trạng thiếu bản thu.
      const missingKinds = Array.isArray(info.missing)
        ? info.missing
            .map((kind) => trimmedString(kind))
            .filter((kind): kind is string => kind !== null)
        : [];
      const hasMissingClips = missingKinds.length > 0 || info.ready === false;

      options.push({
        id,
        label,
        selected: id === currentVoice,
        hasMissingClips,
        missingKinds,
      });
    }
  }

  // `fallbacks` = {loại câu → câu tiếng Việt giải thích}. Lấy KEY làm danh
  // sách câu đang mượn giọng, và lấy value ĐẦU TIÊN làm câu hiện cho người
  // dùng — đó là câu server đã viết, không phải câu app tự ghép.
  const fallbackKinds: string[] = [];
  let fallbackNote: string | null = null;
  const rawFallbacks = data.fallbacks;
  if (rawFallbacks && typeof rawFallbacks === 'object' && !Array.isArray(rawFallbacks)) {
    for (const [kind, value] of Object.entries(rawFallbacks as Record<string, unknown>)) {
      fallbackKinds.push(kind);
      const note = trimmedString(value);
      if (fallbackNote === null && note) fallbackNote = note;
    }
    fallbackKinds.sort();
  }

  const currentLabel = currentVoice
    ? (options.find((o) => o.id === currentVoice)?.label ??
      VOICE_FALLBACK_LABEL[currentVoice] ??
      unknownText(currentVoice))
    : '–';

  return {
    available,
    currentVoice,
    currentLabel,
    voices: options,
    message,
    fallbackKinds,
    fallbackCount: fallbackKinds.length,
    fallbackNote,
  };
}

/* -------------------------------------------------------------- violations */

/**
 * Một vi phạm đã hiển thị được.
 *
 * Đây là **lịch sử vi phạm** (người rời khỏi camera / dùng điện thoại / sai
 * người học), không phải log debug hệ thống — người dùng hỏi "hôm nay mình bị
 * nhắc mấy lần", không hỏi "tiến trình in ra gì".
 */
export type ViolationEntry = {
  /** Mốc thời gian, **epoch mili giây** — để dựng `Date` ở múi giờ máy. */
  ts: number;
  /** Mã vi phạm thô từ server (`ABSENT` / `PHONE_USE` / `IMPOSTOR`). */
  kind: string;
  /**
   * Nhãn tiếng Việt **do server gửi** (`kind_text`).
   *
   * App dùng thẳng, không tự map: dashboard web và app phải nói cùng một câu,
   * và bản dịch chỉ nên tồn tại ở một chỗ. `null` khi server không gửi — màn
   * hình sẽ rơi về `kind` thô kèm dấu hiệu, chứ không bịa nhãn.
   */
  kindText: string | null;
  /** Số giây kéo dài; `0` khi không có hoặc không đọc được (một lần bấm). */
  durationS: number;
};

/** Trạng thái màn Vi phạm đã sẵn sàng để vẽ. */
export type ViolationsView = {
  /** Danh sách, **mới nhất trước**. */
  violations: ViolationEntry[];
  /** Tổng số vi phạm server báo; rơi về `violations.length` khi thiếu. */
  total: number;
  /** Số vi phạm theo từng mã, thứ tự cố định; `0` cho mã server không báo. */
  counts: ViolationCount[];
  /** Chỉ những mã có số > 0, để đầu màn không đầy chip `0`. */
  countsNonZero: ViolationCount[];
};

/** Một dòng phân loại ở đầu màn. */
export type ViolationCount = {
  kind: string;
  /** Nhãn tiếng Việt; `null` khi server không gửi cho mã này. */
  kindText: string | null;
  count: number;
};

/**
 * Thứ tự hiển thị cố định của các mã đã biết.
 *
 * Cố định thay vì theo thứ tự khoá JSON: thứ tự khoá của `counts` do server
 * quyết định và có thể đổi, làm các chip nhảy chỗ giữa hai lần làm mới — người
 * dùng tưởng số liệu vừa thay đổi.
 */
export const VIOLATION_KIND_ORDER = ['ABSENT', 'PHONE_USE', 'IMPOSTOR'] as const;

/**
 * Đọc một mốc thời gian về epoch **mili giây**.
 *
 * Chấp nhận cả giây lẫn mili giây vì server có thể đổi đơn vị: `ts` trong bảng
 * `events` là `REAL` giây (`time.time()`), nhưng một route mới rất dễ trả ms.
 * Phân biệt bằng độ lớn: mốc mili giây của thời gian thực luôn > 1e12, còn
 * giây thì < 1e11 trong nhiều thế kỷ tới. Chuỗi số cũng được nhận.
 *
 * Trả `null` khi không đọc được — người gọi **bỏ** bản ghi đó thay vì đoán.
 */
function toEpochMs(raw: unknown): number | null {
  let value: number;
  if (typeof raw === 'number') {
    value = raw;
  } else if (typeof raw === 'string' && raw.trim() !== '') {
    value = Number(raw.trim());
  } else {
    return null;
  }
  if (!Number.isFinite(value) || value <= 0) return null;
  // < 1e11 ⇒ đang là giây (tới năm 5138 vẫn đúng). Lớn hơn ⇒ đã là mili giây.
  return value < 1e11 ? Math.round(value * 1000) : Math.round(value);
}

/** Đọc số giây kéo dài; âm hoặc không đọc được ⇒ 0 (một lần bấm, không kéo dài). */
function toDurationSeconds(raw: unknown): number {
  const value = typeof raw === 'number' ? raw : Number(raw);
  if (!Number.isFinite(value) || value <= 0) return 0;
  return value;
}

/**
 * Chuẩn hoá `GET /api/violations`.
 *
 * Hình dạng thật:
 * ```jsonc
 * {
 *   "violations": [
 *     { "ts": 1763000000.5, "kind": "ABSENT", "kind_text": "Rời khỏi bàn", "duration_s": 8.2 }
 *   ],
 *   "total": 12,
 *   "counts": { "ABSENT": 7, "PHONE_USE": 3, "IMPOSTOR": 2 }
 * }
 * ```
 *
 * Ba quy tắc, cùng tinh thần với các hàm trên:
 * 1. **Một bản ghi hỏng không được làm mất cả danh sách.** Bản ghi thiếu `ts`
 *    đọc được hoặc thiếu `kind` bị **bỏ** (không ném, không hiện dòng rác).
 * 2. **Nhãn lấy từ server** (`kind_text`). Không tự dịch ở app.
 * 3. **Payload lạ không crash**: `violations` không phải mảng, `counts` sai
 *    kiểu, hay cả payload là `null` đều cho ra view rỗng hợp lệ.
 *
 * Không sắp xếp lại theo `ts` trừ khi cần: server đã trả mới nhất trước, và
 * sắp xếp lại sẽ che mất một server trả sai thứ tự. Nhưng khi một bản ghi có
 * `ts` lệch hẳn (dữ liệu cũ trộn vào) thì người dùng vẫn đọc được vì mỗi dòng
 * có giờ riêng.
 */
export function normalizeViolations(payload: unknown): ViolationsView {
  const data = (payload && typeof payload === 'object' ? payload : {}) as Record<
    string,
    unknown
  >;

  const rawList = Array.isArray(data.violations) ? data.violations : [];
  const violations: ViolationEntry[] = [];
  for (const item of rawList) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue;
    const row = item as Record<string, unknown>;
    const ts = toEpochMs(row.ts);
    const kind = trimmedString(row.kind);
    // Thiếu mốc thời gian hoặc thiếu mã thì dòng đó **không đọc được**: bỏ.
    // Hiện nó với giờ bịa còn tệ hơn — người dùng sẽ tin mốc đó là thật.
    if (ts === null || kind === null) continue;
    violations.push({
      ts,
      kind,
      kindText: trimmedString(row.kind_text),
      durationS: toDurationSeconds(row.duration_s ?? row.durationS),
    });
  }

  // `counts` có thể thiếu (server cũ) hoặc sai kiểu. Dựng lại từ danh sách khi
  // thiếu để đầu màn vẫn có tổng đúng thay vì trống.
  const rawCounts = data.counts;
  const countsByKind = new Map<string, number>();
  if (rawCounts && typeof rawCounts === 'object' && !Array.isArray(rawCounts)) {
    for (const [kind, value] of Object.entries(rawCounts as Record<string, unknown>)) {
      const n = typeof value === 'number' ? value : Number(value);
      if (Number.isFinite(n) && n >= 0) countsByKind.set(kind, Math.floor(n));
    }
  }
  if (countsByKind.size === 0) {
    for (const v of violations) countsByKind.set(v.kind, (countsByKind.get(v.kind) ?? 0) + 1);
  }

  // Nhãn cho chip lấy từ dòng đầu tiên có cùng `kind` (server gửi kèm mỗi
  // dòng, không kèm trong `counts`).
  const labelByKind = new Map<string, string>();
  for (const v of violations) {
    if (v.kindText && !labelByKind.has(v.kind)) labelByKind.set(v.kind, v.kindText);
  }

  // Mã đã biết đứng trước theo thứ tự cố định; mã lạ (server mới thêm) xếp sau
  // theo alphabet — hiện ra chứ không nuốt, để lỗi đánh máy còn thấy được.
  const known = VIOLATION_KIND_ORDER.filter((k) => countsByKind.has(k));
  const unknownKinds = [...countsByKind.keys()]
    .filter((k) => !(VIOLATION_KIND_ORDER as readonly string[]).includes(k))
    .sort();

  const counts: ViolationCount[] = [...known, ...unknownKinds].map((kind) => ({
    kind,
    kindText: labelByKind.get(kind) ?? null,
    count: countsByKind.get(kind) ?? 0,
  }));

  const rawTotal = typeof data.total === 'number' ? data.total : Number(data.total);
  const total =
    Number.isFinite(rawTotal) && rawTotal >= 0
      ? Math.floor(rawTotal)
      : violations.length;

  return {
    violations,
    total,
    counts,
    countsNonZero: counts.filter((c) => c.count > 0),
  };
}

/* ----------------------------------------------------- people & enrollment */

/** Năm bước hướng dẫn mặc định khi máy chủ không đính kèm `steps` (`enrollment.py:23-29`). */
export const DEFAULT_ENROLL_STEPS = [
  'Nhìn thẳng',
  'Quay sang phải',
  'Quay sang trái',
  'Ngẩng lên',
  'Cúi xuống',
] as const;

export type PersonEntry = {
  id: string;
  name: string;
  /** Epoch mili giây khi có `created_ts` hợp lệ; `null` nếu thiếu. */
  createdAtMs: number | null;
  /** Chữ cái đại diện in hoa từ tên (từ cuối cùng theo cách gọi tên tiếng Việt). */
  initial: string;
};

export type PeopleView = {
  people: PersonEntry[];
  selectedId: string | null;
  selectedPerson: PersonEntry | null;
  /** Nhãn người đang học, khớp quy tắc `setSelected()` trong `web/static/app.js`. */
  selectedText: string;
};

function personInitial(name: string): string {
  const clean = name.trim();
  if (!clean) return '?';
  const parts = clean.split(/\s+/);
  const last = parts[parts.length - 1] ?? clean;
  return last.charAt(0).toUpperCase();
}

/**
 * Chuẩn hoá `GET /api/people` (`{"people": [{"id", "name", "created_ts"}], "selected": string | null}`).
 *
 * Bảo toàn quy tắc quyền riêng tư & ổn định:
 * - Bỏ qua phần tử hỏng mà không làm vỡ cả danh sách.
 * - `selected` khác `null` nhưng không nằm trong `people` phải báo rõ `"mã ... (không có trong danh sách)"`.
 */
export function normalizePeople(payload: unknown): PeopleView {
  const data = (payload && typeof payload === 'object' ? payload : {}) as Record<
    string,
    unknown
  >;

  const rawPeople = Array.isArray(data.people) ? data.people : [];
  const people: PersonEntry[] = [];
  for (const item of rawPeople) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue;
    const rec = item as Record<string, unknown>;
    const id = trimmedString(rec.id) ?? trimmedString(rec.name);
    if (!id) continue;
    const name = trimmedString(rec.name) ?? id;
    people.push({
      id,
      name,
      createdAtMs: toEpochMs(rec.created_ts),
      initial: personInitial(name),
    });
  }

  const selectedId = trimmedString(data.selected);
  const selectedPerson =
    selectedId !== null ? (people.find((p) => p.id === selectedId) ?? null) : null;

  let selectedText: string;
  if (selectedId === null) {
    selectedText = 'Chưa chọn người đang học';
  } else if (selectedPerson) {
    selectedText = selectedPerson.name;
  } else {
    selectedText = `mã ${selectedId} (không có trong danh sách)`;
  }

  return {
    people,
    selectedId,
    selectedPerson,
    selectedText,
  };
}

export type EnrollStartView = {
  enrollId: string | null;
  name: string | null;
  steps: string[];
};

/** Chuẩn hoá phản hồi `POST /api/people` (`201 Created`). */
export function normalizeEnrollStart(payload: unknown): EnrollStartView {
  const data = (payload && typeof payload === 'object' ? payload : {}) as Record<
    string,
    unknown
  >;
  const enrollId = trimmedString(data.enroll_id);
  const name = trimmedString(data.name);
  const rawSteps = Array.isArray(data.steps)
    ? data.steps
        .map((step) => trimmedString(step))
        .filter((step): step is string => step !== null)
    : [];
  const steps = rawSteps.length > 0 ? rawSteps : [...DEFAULT_ENROLL_STEPS];
  return { enrollId, name, steps };
}

export type EnrollStepDot = {
  index: number;
  label: string;
  done: boolean;
  current: boolean;
};

export type EnrollStatusView = {
  state: 'running' | 'done' | 'failed' | 'cancelled' | 'unknown';
  stepIndex: number;
  stepName: string;
  samples: number;
  samplesNeeded: number;
  progressRatio: number;
  steps: EnrollStepDot[];
  error: string | null;
  headlineText: string;
  samplesText: string;
  hintText: string;
};

/**
 * Chuẩn hoá `GET /api/enroll/<enroll_id>`.
 *
 * Hai quy tắc đồng bộ chặt với `web/static/app.js`:
 * 1. Khi `state === 'done'`: mọi chấm bước đều `done = true, current = false`, `progressRatio = 1`.
 * 2. Khi `state === 'failed'` hoặc `'cancelled'`: không còn chấm nào mang `current = true`
 *    (máy chủ đã dừng quét; chỉ giữ `done = true` cho các bước đã đi qua).
 */
export function normalizeEnrollStatus(
  payload: unknown,
  stepLabels: readonly string[] = DEFAULT_ENROLL_STEPS,
  personName?: string | null,
): EnrollStatusView {
  const data = (payload && typeof payload === 'object' ? payload : {}) as Record<
    string,
    unknown
  >;

  const rawState = (trimmedString(data.state) ?? '').toLowerCase();
  const state: EnrollStatusView['state'] =
    rawState === 'running' ||
    rawState === 'done' ||
    rawState === 'failed' ||
    rawState === 'cancelled'
      ? rawState
      : 'unknown';

  const labels = stepLabels.length > 0 ? stepLabels : DEFAULT_ENROLL_STEPS;
  const rawStepIdx = finiteNumber(data.step_index);
  const stepIndex = Math.max(
    0,
    Math.min(rawStepIdx === null ? 0 : Math.floor(rawStepIdx), labels.length - 1),
  );
  const stepName = trimmedString(data.step_name) ?? labels[stepIndex] ?? 'Nhìn thẳng';

  const rawSamples = finiteNumber(data.samples);
  const samples = Math.max(0, rawSamples === null ? 0 : Math.floor(rawSamples));
  const rawNeeded = finiteNumber(data.samples_needed);
  const samplesNeeded = Math.max(1, rawNeeded === null ? 3 : Math.floor(rawNeeded));

  const progressRatio =
    state === 'done' ? 1 : Math.max(0, Math.min(1, samples / samplesNeeded));

  const steps: EnrollStepDot[] = labels.map((label, index) => ({
    index,
    label,
    done: state === 'done' ? true : index < stepIndex,
    current: state === 'running' && index === stepIndex,
  }));

  const error = trimmedString(data.error);
  const cleanName = trimmedString(personName) ?? 'người học';

  let headlineText: string;
  let samplesText: string;
  let hintText: string;

  if (state === 'done') {
    headlineText = 'Đã đăng ký';
    samplesText = `Khuôn mặt của ${cleanName} đã được lưu.`;
    hintText =
      `Từ lần này hệ thống nhận ra ${cleanName} khi bạn chọn làm người đang học. ` +
      'Chỉ lưu đặc trưng khuôn mặt, không lưu ảnh.';
  } else if (state === 'failed') {
    headlineText = 'Chưa đạt';
    samplesText = `Mẫu hợp lệ: ${samples} / ${samplesNeeded}`;
    hintText =
      error ??
      'Không thu đủ mẫu khuôn mặt. Giữ mặt trong vòng tròn, đủ sáng rồi bấm Quét lại.';
  } else if (state === 'cancelled') {
    headlineText = 'Đã huỷ';
    samplesText = 'Phiên đăng ký đã dừng.';
    hintText = error ?? 'Đã huỷ phiên đăng ký khuôn mặt.';
  } else if (state === 'running') {
    headlineText = labels[stepIndex] ?? stepName;
    samplesText = `Mẫu hợp lệ: ${samples} / ${samplesNeeded}`;
    hintText =
      samples === 0
        ? 'Chưa nhận được khuôn mặt. Bỏ kính râm, đủ sáng và nhìn thẳng vào camera.'
        : 'Giữ mặt trong vòng tròn và xoay đầu nhẹ theo từng bước hướng dẫn.';
  } else {
    headlineText = unknownText(data.state);
    samplesText = `Mẫu hợp lệ: ${samples} / ${samplesNeeded}`;
    hintText = error ?? 'Trạng thái phiên đăng ký không xác định.';
  }

  return {
    state,
    stepIndex,
    stepName,
    samples,
    samplesNeeded,
    progressRatio,
    steps,
    error,
    headlineText,
    samplesText,
    hintText,
  };
}

/* ------------------------------------------------------------- system logs */

export type SystemLogSeverity = 'ERROR' | 'WARNING' | 'INFO' | 'DEBUG';

export type SystemLogEntry = {
  /** Mốc thời gian epoch mili giây. */
  ts: number;
  /** Mức độ chuẩn hoá (`ERROR`, `WARNING`, `INFO`, `DEBUG`). */
  level: SystemLogSeverity;
  /** Tên module ghi log (ví dụ `posture_monitor.camera.capture`). */
  logger: string;
  /** Nội dung thông báo / chi tiết lỗi tiếng Việt từ máy chủ. */
  message: string;
};

export type SystemLogsView = {
  /** Danh sách bản ghi **mới nhất trước**. */
  logs: SystemLogEntry[];
  total: number;
  errorCount: number;
  warningCount: number;
};

function normalizeLogSeverity(raw: unknown): SystemLogSeverity {
  const upper = (trimmedString(raw) ?? 'INFO').toUpperCase();
  if (upper === 'CRITICAL' || upper === 'ERROR') return 'ERROR';
  if (upper === 'WARNING' || upper === 'WARN') return 'WARNING';
  if (upper === 'DEBUG') return 'DEBUG';
  return 'INFO';
}

/**
 * Chuẩn hoá `GET /api/logs`, sắp bản ghi **mới nhất lên đầu** để người dùng
 * thấy ngay lỗi hoặc cảnh báo vừa xảy ra cùng mốc giờ & ngày chính xác.
 */
export function normalizeSystemLogs(payload: unknown): SystemLogsView {
  const data = (payload && typeof payload === 'object' ? payload : {}) as Record<
    string,
    unknown
  >;
  const rawList = Array.isArray(data.logs) ? data.logs : [];
  const indexed: Array<{ entry: SystemLogEntry; idx: number }> = [];

  for (let i = 0; i < rawList.length; i += 1) {
    const item = rawList[i];
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue;
    const row = item as Record<string, unknown>;
    const ts = toEpochMs(row.ts);
    const message = trimmedString(row.message);
    if (ts === null || message === null) continue;
    indexed.push({
      idx: i,
      entry: {
        ts,
        level: normalizeLogSeverity(row.level),
        logger: trimmedString(row.logger) ?? 'posture_monitor',
        message,
      },
    });
  }

  // Mới nhất đứng đầu; cùng mốc giây thì bản ghi ghi sau đứng trước.
  indexed.sort((a, b) => (b.entry.ts !== a.entry.ts ? b.entry.ts - a.entry.ts : b.idx - a.idx));
  const logs = indexed.map((item) => item.entry);

  let errorCount = 0;
  let warningCount = 0;
  for (const item of logs) {
    if (item.level === 'ERROR') errorCount += 1;
    else if (item.level === 'WARNING') warningCount += 1;
  }

  return {
    logs,
    total: logs.length,
    errorCount,
    warningCount,
  };
}
