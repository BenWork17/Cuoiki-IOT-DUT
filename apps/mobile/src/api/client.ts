/**
 * **Lớp gọi mạng duy nhất** của app. Mọi màn hình đều đi qua đây.
 *
 * Vì sao gom về một tệp (yêu cầu §5.2 của tài liệu yêu cầu):
 * 1. Timeout bằng `AbortController` phải có ở **mọi** lời gọi, không phải chỉ
 *    ở lời gọi nào người viết màn hình nhớ ra. Không có timeout, một IP sai
 *    làm spinner quay vô hạn và người dùng tưởng app treo.
 * 2. Mọi mã lỗi phải thành **câu tiếng Việt**. Server trả lỗi dạng
 *    `{"ok": false, "message": ...}` (`app.py:1051-1055`) nhưng **405 và 404
 *    ngoài `/api/` là HTML** — nên không bao giờ được gọi `response.json()`
 *    vô điều kiện (xem `errors.ts`). Ở đây chỉ đọc `res.text()` rồi mới
 *    thử `JSON.parse` khi `content-type` nói đó là JSON.
 * 3. Trả **cả mã HTTP** cho người gọi, vì một số quyết định UI phụ thuộc
 *    đúng mã: 403 ở `/api/frame` = stream đang tắt, 404 = bản dashboard chưa
 *    có route, 503 ở `/api/session*` = phiên chưa được bật (không phải lỗi
 *    mạng, không được crash).
 * 4. Tệp này **không import `react-native`** nên Node chạy test được thẳng
 *    (`apps/mobile/test/*.test.mjs`) mà không cần Metro hay máy ảo.
 */
import {
  badPayloadError,
  cancelledError,
  configError,
  extractServerMessage,
  httpError,
  networkError,
  timeoutError,
  type ApiError,
} from './errors';
import { buildUrl, normalizeBaseUrl } from './url';
import { looksLikeStatus } from './payload';

/** Hạn chờ cho lời gọi JSON (yêu cầu: ≤ 5 s). */
export const JSON_TIMEOUT_MS = 5000;

/** Hạn chờ cho ảnh camera (yêu cầu: ≤ 10 s). */
export const FRAME_TIMEOUT_MS = 10000;

/** Kết quả một lời gọi: hoặc dữ liệu + mã 200, hoặc lỗi tiếng Việt + mã. */
export type ApiResult<T> =
  | { ok: true; data: T; status: number }
  | { ok: false; error: ApiError; status: number | null };

/**
 * Đường dẫn API **được phép gọi**, đối chiếu bảng §4.2 của tài liệu yêu cầu.
 *
 * Ghi thành hằng số thay vì rải chuỗi trong màn hình để một chỗ sai chính tả
 * không tạo ra 404 khó truy (404 ngoài `/api/` còn trả HTML).
 */
export const API_PATH = {
  status: '/api/status',
  signals: '/api/signals',
  session: '/api/session',
  sessionStart: '/api/session/start',
  sessionStop: '/api/session/stop',
  mute: '/api/mute',
  ptz: '/api/ptz',
  frame: '/api/frame',
  /** Luồng MJPEG trực tiếp cho `WebView` ở màn Camera & hộp quét khuôn mặt. */
  stream: '/stream',
  voice: '/api/voice',
  /** Lịch sử **vi phạm** (rời bàn / dùng điện thoại / sai người) từ bảng `events`. */
  violations: '/api/violations',
  /** Nhật ký sự kiện & lỗi hệ thống trong bộ nhớ (`GET /api/logs`). */
  logs: '/api/logs',
  /** Danh sách người học (`GET`), thêm người mới mở phiên quét (`POST`), xoá (`DELETE /api/people/<id>`). */
  people: '/api/people',
  /** Chọn hoặc bỏ chọn người đang học (`POST /api/select`). */
  select: '/api/select',
  /** Tiền tố tiến độ & huỷ phiên đăng ký khuôn mặt (`/api/enroll/<id>`). */
  enroll: '/api/enroll',
} as const;

/**
 * Số dòng vi phạm xin mỗi lần.
 *
 * Chặn trên ở client, không phải chỉ ở server: màn hình là `FlatList` nên số
 * dòng lớn chỉ tốn RAM vô ích, và một `limit` do người dùng gõ sai không được
 * biến thành lời gọi kéo cả bảng `events` về điện thoại.
 */
export const VIOLATIONS_LIMIT = 200;

/** Số bản ghi nhật ký hệ thống tối đa xin mỗi lần. */
export const LOGS_LIMIT = 150;

/** Mức lọc nhật ký hệ thống hợp lệ trên `/api/logs`. */
export type LogLevelFilter = 'INFO' | 'WARNING' | 'ERROR';

/** Bốn hướng PTZ hợp lệ; server từ chối mọi giá trị khác bằng 400 (`app.py:711`). */
export type PtzDirection = 'up' | 'down' | 'left' | 'right';

/** Phần thân gửi `/api/mute`: `{muted: true}` để đặt, `{}` để đảo trạng thái. */
export type MuteBody = { muted: boolean };

/** Thông tin một khung ảnh đã tải được, sẵn sàng cho `<Image source>`. */
export type FramePayload = {
  /** `data:image/jpeg;base64,...` — React Native vẽ được trực tiếp. */
  uri: string;
  /** Kích thước thật của khung (byte JPEG), để hiện trong nhãn. */
  byteLength: number;
  /** `Date.now()` lúc nhận xong, để hiện "cập nhật lúc …". */
  receivedAt: number;
};

/** Tuỳ chọn chung; `fetchImpl` và `now` để test thay được, không cần mạng. */
export type RequestOptions = {
  /** Huỷ từ ngoài (rời màn hình). */
  signal?: AbortSignal;
  /** Ghi đè hạn chờ mặc định. */
  timeoutMs?: number;
  /** Thay `fetch` (test). Mặc định dùng `globalThis.fetch`. */
  fetchImpl?: typeof fetch;
  /** Thay đồng hồ (test). */
  now?: () => number;
};

/** Ném ra bên trong để phân biệt timeout với huỷ và lỗi mạng. */
class RequestAborted extends Error {
  readonly reason: 'timeout' | 'external';

  constructor(reason: 'timeout' | 'external') {
    super(reason);
    this.reason = reason;
  }
}

/**
 * Bao một lời gọi `fetch` bằng `AbortController` có hạn chờ.
 *
 * Phân biệt hai nguyên nhân huỷ: hết giờ (phải hiện "máy chủ không trả lời")
 * và người dùng rời màn hình (không được hiện lỗi gì). Gộp hai ca này là lỗi
 * hay gặp: rời màn hình rồi quay lại sẽ thấy "máy chủ không trả lời" giả.
 */
async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  options: RequestOptions,
): Promise<Response> {
  const timeoutMs = options.timeoutMs ?? JSON_TIMEOUT_MS;
  const doFetch = options.fetchImpl ?? globalThis.fetch;
  const controller = new AbortController();
  let abortReason: 'timeout' | 'external' | null = null;

  const timer = setTimeout(() => {
    abortReason = 'timeout';
    controller.abort();
  }, timeoutMs);

  const external = options.signal;
  const onExternalAbort = () => {
    abortReason = 'external';
    controller.abort();
  };
  if (external) {
    if (external.aborted) {
      clearTimeout(timer);
      throw new RequestAborted('external');
    }
    external.addEventListener('abort', onExternalAbort);
  }

  try {
    return await doFetch(url, { ...init, signal: controller.signal });
  } catch (error) {
    if (abortReason === 'timeout') throw new RequestAborted('timeout');
    if (abortReason === 'external') throw new RequestAborted('external');
    // `fetch` ném TypeError khi không kết nối được. Câu gốc chỉ để ghi log.
    const cause =
      error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    throw networkError(cause);
  } finally {
    clearTimeout(timer);
    if (external) external.removeEventListener('abort', onExternalAbort);
  }
}

/** Đổi lỗi "đã chuẩn hoá" hoặc lỗi lạ thành `ApiResult` thất bại. */
function failure(error: unknown): { ok: false; error: ApiError; status: number | null } {
  if (error instanceof RequestAborted) {
    const apiError = error.reason === 'timeout' ? timeoutError() : cancelledError();
    return { ok: false, error: apiError, status: null };
  }
  if (error && typeof error === 'object' && 'kind' in error && 'message' in error) {
    const apiError = error as ApiError;
    return { ok: false, error: apiError, status: apiError.status };
  }
  return { ok: false, error: networkError(String(error)), status: null };
}

/**
 * Gọi một route JSON.
 *
 * Luôn đọc thân bằng `text()` trước, rồi mới `JSON.parse` — vì 405/404 có thể
 * là HTML và `res.json()` khi đó ném `SyntaxError` không nói được gì cho
 * người dùng.
 */
export async function requestJson<T>(
  baseUrl: string,
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<ApiResult<T>> {
  const normalized = normalizeBaseUrl(baseUrl);
  if (!normalized.ok) {
    return { ok: false, error: configError(normalized.message), status: null };
  }

  const url = buildUrl(normalized.baseUrl, path);
  const headers: Record<string, string> = { Accept: 'application/json' };
  const init: RequestInit = { method, headers, cache: 'no-store' };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetchWithTimeout(url, init, options);
  } catch (error) {
    return failure(error);
  }

  let text: string;
  try {
    text = await response.text();
  } catch (error) {
    // Hết giờ/abort giữa lúc đọc thân: vẫn là một thất bại, nhưng không phải
    // "sai định dạng" — người dùng cần biết là không có phản hồi trọn vẹn.
    void error;
    return {
      ok: false,
      error: networkError('Đọc không hết phản hồi từ máy chủ.'),
      status: response.status,
    };
  }

  if (!response.ok) {
    const serverMessage = extractServerMessage(
      text,
      response.headers?.get?.('content-type') ?? null,
    );
    const error = httpError(response.status, serverMessage, path);
    return { ok: false, error, status: response.status };
  }

  let parsed: unknown;
  try {
    parsed = text.trim() ? JSON.parse(text) : null;
  } catch {
    return { ok: false, error: badPayloadError(path), status: response.status };
  }

  return { ok: true, data: parsed as T, status: response.status };
}

/**
 * Tải **một** khung JPEG từ `GET /api/frame`.
 *
 * Vì sao không dùng `<Image source={{uri: '.../api/frame'}}>` trực tiếp:
 * component ảnh của React Native không cho biết mã HTTP, không có hạn chờ, và
 * không phân biệt được "stream đang tắt" (403) với "ảnh hỏng". Yêu cầu bắt
 * buộc phải nói được lý do, nên phải đi qua lớp client này.
 *
 * Ảnh được đọc thành `Blob` rồi đổi sang `data:` URI bằng `FileReader`
 * (đều có sẵn trong React Native). Cách này chỉ tải ảnh **một lần** cho mỗi
 * nhịp, khác với việc vừa `fetch` để lấy mã vừa để `<Image>` tải lại.
 */
export async function requestFrame(
  baseUrl: string,
  options: RequestOptions = {},
): Promise<ApiResult<FramePayload>> {
  const normalized = normalizeBaseUrl(baseUrl);
  if (!normalized.ok) {
    return { ok: false, error: configError(normalized.message), status: null };
  }

  const url = buildUrl(normalized.baseUrl, API_PATH.frame);
  const init: RequestInit = {
    method: 'GET',
    headers: { Accept: 'image/jpeg' },
    cache: 'no-store',
  };

  let response: Response;
  try {
    response = await fetchWithTimeout(url, init, {
      ...options,
      timeoutMs: options.timeoutMs ?? FRAME_TIMEOUT_MS,
    });
  } catch (error) {
    return failure(error);
  }

  if (!response.ok) {
    // Thân lỗi của route này là JSON tiếng Việt khi stream tắt (theo yêu cầu
    // §4.3), nhưng vẫn phải chịu được HTML nếu bản dashboard còn cũ.
    let text = '';
    try {
      text = await response.text();
    } catch {
      text = '';
    }
    const serverMessage = extractServerMessage(
      text,
      response.headers?.get?.('content-type') ?? null,
    );
    const error = httpError(response.status, serverMessage, API_PATH.frame);
    return { ok: false, error, status: response.status };
  }

  const contentType = (
    response.headers?.get?.('content-type') ?? ''
  ).toLowerCase();
  if (contentType && !contentType.startsWith('image/')) {
    return {
      ok: false,
      error: badPayloadError(`máy chủ trả ${contentType} thay vì ảnh`),
      status: response.status,
    };
  }

  const now = options.now ?? Date.now;
  try {
    const blob = await response.blob();
    const uri = await blobToDataUrl(blob);
    return {
      ok: true,
      data: { uri, byteLength: blob.size, receivedAt: now() },
      status: response.status,
    };
  } catch (error) {
    if (error instanceof RequestAborted) return failure(error);
    return {
      ok: false,
      error: badPayloadError('không đọc được dữ liệu ảnh'),
      status: response.status,
    };
  }
}

/**
 * `Blob` → `data:` URI bằng `FileReader`.
 *
 * Tách riêng và kiểm tra sự tồn tại của `FileReader` để một môi trường thiếu
 * nó (ví dụ Node trong lúc chạy test) báo lỗi rõ ràng thay vì `undefined is
 * not a function`.
 */
function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const Reader = (globalThis as { FileReader?: typeof FileReader }).FileReader;
    if (typeof Reader !== 'function') {
      reject(new Error('FileReader không có trong môi trường này'));
      return;
    }
    const reader = new Reader();
    reader.onerror = () => reject(new Error('FileReader lỗi khi đọc ảnh'));
    reader.onloadend = () => {
      const result = reader.result;
      if (typeof result === 'string') resolve(result);
      else reject(new Error('FileReader không trả chuỗi data URL'));
    };
    reader.readAsDataURL(blob);
  });
}

/** Kiểu dữ liệu thô server trả, chỉ khai báo phần app dùng. */
export type StatusPayload = Record<string, unknown>;
export type SignalsPayload = Record<string, unknown>;
export type SessionPayload = Record<string, unknown>;
export type VoicePayload = Record<string, unknown>;
/** Payload thô của `/api/violations`; chuẩn hoá ở `normalizeViolations`. */
export type ViolationsPayload = Record<string, unknown>;
/** Payload thô của `/api/logs`; chuẩn hoá ở `normalizeSystemLogs`. */
export type SystemLogsPayload = Record<string, unknown>;
/** Payload thô của `/api/people` & `/api/enroll*`; chuẩn hoá ở `payload.ts`. */
export type PeoplePayload = Record<string, unknown>;
export type SelectPersonPayload = {
  ok?: boolean;
  selected?: string | null;
  message?: string;
};
export type DeletePersonPayload = { ok?: boolean; message?: string };
export type EnrollStartPayload = Record<string, unknown>;
export type EnrollStatusPayload = Record<string, unknown>;
export type EnrollCancelPayload = { ok?: boolean; message?: string };

/** Một lớp mỏng gắn địa chỉ gốc, để màn hình không phải truyền `baseUrl` mỗi lần. */
export type ApiClient = {
  baseUrl: string;
  getStatus: (options?: RequestOptions) => Promise<ApiResult<StatusPayload>>;
  getSignals: (options?: RequestOptions) => Promise<ApiResult<SignalsPayload>>;
  getSession: (options?: RequestOptions) => Promise<ApiResult<SessionPayload>>;
  startSession: (
    minutes: number | null,
    options?: RequestOptions,
  ) => Promise<ApiResult<SessionPayload>>;
  stopSession: (options?: RequestOptions) => Promise<ApiResult<SessionPayload>>;
  setMuted: (
    muted: boolean | null,
    options?: RequestOptions,
  ) => Promise<ApiResult<{ muted?: boolean; message?: string }>>;
  movePtz: (
    direction: PtzDirection,
    duration: number,
    options?: RequestOptions,
  ) => Promise<ApiResult<{ message?: string; duration?: number }>>;
  getFrame: (options?: RequestOptions) => Promise<ApiResult<FramePayload>>;
  getViolations: (
    limit?: number,
    options?: RequestOptions,
  ) => Promise<ApiResult<ViolationsPayload>>;
  /** `GET /api/logs` — nhật ký sự kiện, cảnh báo và lỗi hệ thống theo thời gian. */
  getLogs: (
    level?: LogLevelFilter,
    limit?: number,
    options?: RequestOptions,
  ) => Promise<ApiResult<SystemLogsPayload>>;
  /** `GET /api/voice` — giọng đang dùng + tình trạng từng giọng. */
  getVoice: (options?: RequestOptions) => Promise<ApiResult<VoicePayload>>;
  /** `POST /api/voice` — đổi giọng đọc. */
  setVoice: (
    voice: string,
    options?: RequestOptions,
  ) => Promise<ApiResult<VoicePayload>>;
  /** `GET /api/people` — danh sách người học đã đăng ký và người đang chọn. */
  getPeople: (options?: RequestOptions) => Promise<ApiResult<PeoplePayload>>;
  /** `POST /api/select` — chọn hoặc bỏ chọn (`null`) người đang học. */
  selectPerson: (
    personId: string | null,
    options?: RequestOptions,
  ) => Promise<ApiResult<SelectPersonPayload>>;
  /** `DELETE /api/people/<person_id>` — xoá hồ sơ khuôn mặt của một người học. */
  deletePerson: (
    personId: string,
    options?: RequestOptions,
  ) => Promise<ApiResult<DeletePersonPayload>>;
  /** `POST /api/people` — mở một phiên quét khuôn mặt 5 bước cho người học mới. */
  startEnroll: (
    name: string,
    options?: RequestOptions,
  ) => Promise<ApiResult<EnrollStartPayload>>;
  /** `GET /api/enroll/<enroll_id>` — đọc tiến độ bước & số mẫu hợp lệ của phiên quét. */
  getEnrollStatus: (
    enrollId: string,
    options?: RequestOptions,
  ) => Promise<ApiResult<EnrollStatusPayload>>;
  /** `POST /api/enroll/<enroll_id>/cancel` — huỷ phiên quét đang chạy ở máy chủ. */
  cancelEnroll: (
    enrollId: string,
    options?: RequestOptions,
  ) => Promise<ApiResult<EnrollCancelPayload>>;
  checkConnection: (
    options?: RequestOptions,
  ) => Promise<ApiResult<{ status: StatusPayload }>>;
};

/**
 * Tạo client cho một địa chỉ gốc.
 *
 * Địa chỉ **rỗng** vẫn tạo được client: mọi lời gọi trả lỗi `config` kèm câu
 * "Chưa cấu hình địa chỉ máy chủ…". Nhờ vậy màn hình không phải rẽ nhánh
 * `if (!baseUrl)` ở mọi chỗ, và lần chạy đầu tiên vẫn hiện được hướng dẫn
 * thay vì màn hình trắng.
 */
export function createApiClient(baseUrl: string): ApiClient {
  const root = typeof baseUrl === 'string' ? baseUrl.trim() : '';
  return {
    baseUrl: root,
    getStatus: (options) => requestJson<StatusPayload>(root, 'GET', API_PATH.status, undefined, options),
    getSignals: (options) =>
      requestJson<SignalsPayload>(root, 'GET', API_PATH.signals, undefined, options),
    getSession: (options) =>
      requestJson<SessionPayload>(root, 'GET', API_PATH.session, undefined, options),
    startSession: (minutes, options) =>
      requestJson<SessionPayload>(
        root,
        'POST',
        API_PATH.sessionStart,
        // Thân rỗng khi chưa biết số phút: server dùng thời lượng mặc định của
        // cấu hình (`app.py:509-512`).
        minutes === null ? {} : { minutes },
        options,
      ),
    stopSession: (options) =>
      requestJson<SessionPayload>(root, 'POST', API_PATH.sessionStop, {}, options),
    setMuted: (muted, options) =>
      requestJson<{ muted?: boolean; message?: string }>(
        root,
        'POST',
        API_PATH.mute,
        muted === null ? {} : { muted },
        options,
      ),
    movePtz: (direction, duration, options) =>
      requestJson<{ message?: string; duration?: number }>(
        root,
        'POST',
        API_PATH.ptz,
        { direction, duration },
        options,
      ),
    getFrame: (options) => requestFrame(root, options),
    getVoice: (options) =>
      requestJson<VoicePayload>(root, 'GET', API_PATH.voice, undefined, options),
    setVoice: (voice, options) =>
      requestJson<VoicePayload>(root, 'POST', API_PATH.voice, { voice }, options),
    getPeople: (options) =>
      requestJson<PeoplePayload>(root, 'GET', API_PATH.people, undefined, options),
    selectPerson: (personId, options) =>
      requestJson<SelectPersonPayload>(
        root,
        'POST',
        API_PATH.select,
        { person_id: personId },
        options,
      ),
    deletePerson: (personId, options) =>
      requestJson<DeletePersonPayload>(
        root,
        'DELETE',
        `${API_PATH.people}/${encodeURIComponent(personId)}`,
        undefined,
        options,
      ),
    startEnroll: (name, options) =>
      requestJson<EnrollStartPayload>(
        root,
        'POST',
        API_PATH.people,
        { name },
        options,
      ),
    getEnrollStatus: (enrollId, options) =>
      requestJson<EnrollStatusPayload>(
        root,
        'GET',
        `${API_PATH.enroll}/${encodeURIComponent(enrollId)}`,
        undefined,
        options,
      ),
    cancelEnroll: (enrollId, options) =>
      requestJson<EnrollCancelPayload>(
        root,
        'POST',
        `${API_PATH.enroll}/${encodeURIComponent(enrollId)}/cancel`,
        {},
        options,
      ),
    getViolations: (limit, options) => {
      // Kẹp `limit` ở client: số âm hay `NaN` sẽ thành query rác, và một giá
      // trị khổng lồ sẽ kéo cả bảng `events` về máy. Server vẫn phải tự kẹp
      // lần nữa — đây chỉ là chặn đầu tiên.
      const asked = Number.isFinite(limit) ? Math.floor(Number(limit)) : VIOLATIONS_LIMIT;
      const safeLimit = Math.min(Math.max(asked, 1), VIOLATIONS_LIMIT);
      return requestJson<ViolationsPayload>(
        root,
        'GET',
        `${API_PATH.violations}?limit=${safeLimit}`,
        undefined,
        options,
      );
    },
    getLogs: (level = 'INFO', limit, options) => {
      const asked = Number.isFinite(limit) ? Math.floor(Number(limit)) : LOGS_LIMIT;
      const safeLimit = Math.min(Math.max(asked, 1), LOGS_LIMIT);
      const safeLevel: LogLevelFilter =
        level === 'ERROR' || level === 'WARNING' ? level : 'INFO';
      return requestJson<SystemLogsPayload>(
        root,
        'GET',
        `${API_PATH.logs}?level=${safeLevel}&limit=${safeLimit}`,
        undefined,
        options,
      );
    },
    async checkConnection(options) {
      const result = await requestJson<StatusPayload>(
        root,
        'GET',
        API_PATH.status,
        undefined,
        options,
      );
      if (!result.ok) return result;
      if (!looksLikeStatus(result.data)) {
        return {
          ok: false,
          error: badPayloadError('phản hồi không giống /api/status'),
          status: result.status,
        };
      }
      return { ok: true, data: { status: result.data }, status: result.status };
    },
  };
}
