/**
 * Đổi mọi kiểu thất bại của một lời gọi mạng thành **một câu tiếng Việt**.
 * Không import react-native — chạy được bằng Node thuần trong test.
 *
 * Nguyên tắc lấy từ hợp đồng API (`docs/REQUIREMENTS_MOBILE_AND_PRESENCE_FIX.md`
 * §4.1, §4.4):
 * 1. Server trả lỗi dạng `{"ok": false, "message": "<câu tiếng Việt>"}` thì
 *    hiện thẳng `message` — đó là câu người viết server đã chọn.
 * 2. **405 và 404 ngoài tiền tố `/api/` là HTML**, không có `message`. Vì vậy
 *    tuyệt đối không được gọi `response.json()` vô điều kiện; phải xem
 *    content-type trước và vẫn phải nói được một câu tiếng Việt dễ hiểu khi
 *    thân là HTML.
 * 3. Mã lỗi không nằm trong bảng nào thì vẫn phải có câu: "Máy chủ trả lỗi
 *    HTTP <mã>" — im lặng nuốt lỗi là điều cấm.
 */

/** Các kiểu thất bại mà lớp client phân biệt được. */
export type ApiErrorKind =
  /** Không kết nối được (sai IP, khác LAN, máy chủ tắt, ATS chặn). */
  | 'network'
  /** Quá thời gian chờ (AbortController bắn `abort`). */
  | 'timeout'
  /** Người dùng rời màn hình nên request bị huỷ — không phải lỗi. */
  | 'cancelled'
  /** Địa chỉ trong Cài đặt chưa nhập hoặc không hợp lệ. */
  | 'config'
  /** Có phản hồi nhưng mã HTTP là lỗi. */
  | 'http'
  /** 200 nhưng thân không phải JSON hợp lệ / không phải ảnh. */
  | 'bad-payload';

/** Lỗi đã chuẩn hoá, mang đủ dữ kiện để màn hình quyết định cách hiện. */
export type ApiError = {
  kind: ApiErrorKind;
  /** Mã HTTP; `null` khi không có phản hồi nào (mạng, timeout, huỷ). */
  status: number | null;
  /** Câu tiếng Việt hiện thẳng cho người dùng. */
  message: string;
  /** Câu server gửi (nếu có), giữ riêng để test và để tránh dịch hai lần. */
  serverMessage?: string;
  /** Mã lỗi mạng gốc của React Native, chỉ để ghi log. */
  cause?: string;
  /** `true` khi lỗi do cấu hình phía app, không phải do máy chủ. */
  retryable: boolean;
};

/** Câu dùng chung khi máy chủ trả 200 nhưng thân không đọc được. */
export const INVALID_JSON_MESSAGE =
  'Máy chủ trả dữ liệu không phải JSON. Kiểm tra lại địa chỉ máy chủ trong tab Kết nối.';

/** Câu dùng chung khi không có kết nối nào tới máy chủ. */
export const NETWORK_MESSAGE =
  'Không kết nối được tới máy chủ. Kiểm tra: điện thoại và máy chủ có cùng mạng LAN, ' +
  'địa chỉ IP đúng, và chương trình dashboard đang chạy.';

/** Câu khi request quá hạn chờ. */
export const TIMEOUT_MESSAGE =
  'Máy chủ không trả lời trong thời gian chờ. Máy có thể đang bận xử lý camera — thử lại.';

/** Câu khi chưa cấu hình địa chỉ. */
export const NOT_CONFIGURED_MESSAGE =
  'Chưa cấu hình địa chỉ máy chủ. Mở tab Kết nối, nhập http://<IP-LAN>:8000 rồi lưu lại.';

/**
 * Câu mặc định cho từng mã HTTP mà app gặp, khi server **không** kèm `message`.
 *
 * Chỉ là lưới an toàn: server thật luôn gửi `message` cho các mã dưới đây
 * (`app.py:1051-1055`). Nhưng 405/502/504 có thể do hạ tầng (reverse proxy,
 * Flask mặc định) sinh ra với thân HTML, nên client phải tự nói được.
 */
const HTTP_FALLBACK_TEXT: Record<number, string> = {
  400: 'Máy chủ từ chối yêu cầu: dữ liệu gửi lên không hợp lệ.',
  401: 'Máy chủ yêu cầu đăng nhập. Dashboard trong LAN thường không bật mục này.',
  403: 'Máy chủ từ chối thực hiện: tính năng này đang bị tắt trong cấu hình.',
  404: 'Máy chủ không có API này. Có thể bản dashboard đang chạy là bản cũ hơn app.',
  405: 'Sai phương thức gọi API. Đây là lỗi của app — hãy báo lại để sửa.',
  409: 'Máy chủ đang bận thực hiện một việc khác. Đợi một chút rồi thử lại.',
  500: 'Máy chủ gặp lỗi không lường trước khi xử lý yêu cầu.',
  501: 'Camera không hỗ trợ chức năng này (ví dụ PTZ).',
  502: 'Máy chủ không nói chuyện được với camera.',
  503: 'Tính năng này chưa được bật trong lần chạy hiện tại của máy chủ.',
  504: 'Máy chủ phản hồi quá chậm (quá hạn chờ của cổng trung gian).',
};

/**
 * Câu tiếng Việt cho một mã HTTP, dùng khi không có `message` từ server.
 *
 * Mã lạ vẫn có câu: bỏ qua là nuốt lỗi.
 */
export function httpStatusMessage(status: number): string {
  const known = HTTP_FALLBACK_TEXT[status];
  if (known) return known;
  if (status >= 500) {
    return `Máy chủ gặp sự cố (HTTP ${status}). Xem log của dashboard để biết chi tiết.`;
  }
  if (status >= 400) {
    return `Máy chủ từ chối yêu cầu (HTTP ${status}).`;
  }
  return `Máy chủ trả mã bất thường (HTTP ${status}).`;
}

/**
 * Gợi ý thêm theo ngữ cảnh route — chỉ nối vào khi server không nói gì.
 *
 * `403` ở `/api/frame` là "stream đang tắt", còn `404` ở cùng route là "bản
 * dashboard chưa có route này". Hai câu này khác hẳn nghĩa chung của mã, nên
 * phải nói theo ngữ cảnh thay vì để người dùng đoán.
 */
const ROUTE_HINTS: Record<string, Partial<Record<number, string>>> = {
  '/api/frame': {
    403: 'Tính năng xem trực tiếp đang tắt. Bật "web.stream_enabled: true" trong config.yaml rồi khởi động lại dashboard.',
    404: 'Máy chủ chưa có route ảnh tĩnh này. Cập nhật dashboard lên bản có GET /api/frame rồi thử lại.',
    503: 'Máy chủ chưa có khung hình nào trong bộ nhớ. Kiểm tra camera còn chạy không.',
  },
  '/api/session': {
    503: 'Phiên học chưa được bật trong lần chạy này nên chưa điều khiển được.',
  },
  '/api/session/start': {
    503: 'Phiên học chưa được bật trong lần chạy này nên chưa bắt đầu được.',
  },
  '/api/session/stop': {
    503: 'Phiên học chưa được bật trong lần chạy này nên chưa dừng được.',
  },
  '/api/signals': {
    503: 'Tính năng người học chưa được bật trong lần chạy này.',
  },
  '/api/ptz': {
    501: 'Camera không hỗ trợ PTZ (không điều khiển được hướng xoay).',
    502: 'Máy chủ không kết nối được tới camera để xoay.',
  },
};

/** Câu cho một mã lỗi, ưu tiên `message` của server, rồi gợi ý theo route. */
export function messageForStatus(
  status: number,
  serverMessage?: string | null,
  path?: string,
): string {
  const fromServer = typeof serverMessage === 'string' ? serverMessage.trim() : '';
  if (fromServer) return fromServer;
  const hint = path ? ROUTE_HINTS[path]?.[status] : undefined;
  if (hint) return hint;
  return httpStatusMessage(status);
}

/** Tên route chuẩn hoá: bỏ query và `?`, để tra `ROUTE_HINTS`. */
export function routeKey(path: string): string {
  const withoutQuery = String(path ?? '').split('?')[0] ?? '';
  return withoutQuery || '/';
}

/**
 * Lấy `message` từ thân lỗi mà **không giả định là JSON**.
 *
 * Trả `null` khi thân không phải JSON, không phải object, hoặc không có
 * `message` dùng được. Người gọi phải tự rơi về `messageForStatus`.
 */
export function extractServerMessage(body: string, contentType?: string | null): string | null {
  const type = String(contentType ?? '').toLowerCase();
  const trimmed = String(body ?? '').trim();
  if (!trimmed) return null;

  // HTML (405/404/502 của Flask và của proxy) : tuyệt đối không thử JSON.parse
  // rồi coi thất bại là "không có lỗi". Nhưng cũng không trả về nguyên khối
  // HTML cho người dùng đọc.
  const looksJson = type.includes('json') || trimmed.startsWith('{') || trimmed.startsWith('[');
  if (!looksJson) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
  const message = (parsed as { message?: unknown }).message;
  if (typeof message !== 'string') return null;
  const clean = message.trim();
  return clean || null;
}

/** Lỗi cấu hình (chưa nhập địa chỉ / địa chỉ sai định dạng). */
export function configError(message: string): ApiError {
  return { kind: 'config', status: null, message, retryable: false };
}

/** Lỗi không kết nối được. */
export function networkError(cause?: string): ApiError {
  return {
    kind: 'network',
    status: null,
    message: NETWORK_MESSAGE,
    retryable: true,
    ...(cause ? { cause } : {}),
  };
}

/** Lỗi quá hạn chờ. */
export function timeoutError(): ApiError {
  return { kind: 'timeout', status: null, message: TIMEOUT_MESSAGE, retryable: true };
}

/** Lỗi do người dùng rời màn hình; màn hình không cần hiện gì. */
export function cancelledError(): ApiError {
  return { kind: 'cancelled', status: null, message: 'Đã huỷ yêu cầu.', retryable: false };
}

/** Lỗi HTTP đã có phản hồi. */
export function httpError(
  status: number,
  serverMessage?: string | null,
  path?: string,
): ApiError {
  return {
    kind: 'http',
    status,
    message: messageForStatus(status, serverMessage, path ? routeKey(path) : undefined),
    ...(serverMessage ? { serverMessage } : {}),
    // 4xx do người dùng gõ sai thì thử lại y nguyên không giúp gì; 5xx và 405
    // thì có thể do bản dashboard cũ / đang khởi động.
    retryable: status >= 500 || status === 403 || status === 404 || status === 408,
  };
}

/** Lỗi 200 nhưng thân không đúng định dạng mong đợi. */
export function badPayloadError(detail?: string): ApiError {
  return {
    kind: 'bad-payload',
    status: 200,
    message: detail ? `${INVALID_JSON_MESSAGE} (${detail})` : INVALID_JSON_MESSAGE,
    retryable: true,
  };
}

/** Câu hiện cho người dùng, đã tính cả trường hợp lỗi không xác định. */
export function describeError(error: ApiError | null | undefined): string {
  if (!error) return '';
  return error.message;
}
