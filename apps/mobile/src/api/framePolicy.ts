/**
 * Quyết định **có tự hỏi lại** `GET /api/frame` hay không, sau một lượt thất
 * bại. Không import react-native — test được bằng Node.
 *
 * Vì sao tách khỏi màn hình: đây là chỗ dễ sai nhất của màn camera, và sai
 * theo kiểu rất khó thấy khi chỉ nhìn mã. Bốn kiểu sai đã tránh được nhờ tách
 * ra và test:
 *
 * 1. **Hỏi lại khi không thể thành công.** `403` (stream tắt trong
 *    `config.yaml`) và `404` (bản dashboard chưa có route) không tự khỏi.
 *    Hỏi lại mỗi 2 giây làm nóng máy và — tệ hơn — làm hướng dẫn sửa cấu hình
 *    nhấp nháy, người dùng không kịp đọc.
 * 2. **Hỏi lại vô hạn khi máy chủ đang hỏng.** Lỗi mạng, `timeout`, `500`,
 *    `502` không có chặn trên thì app thành máy dò lỗi liên tục;
 *    `MAX_AUTO_RETRY` lượt là đủ để vượt một lần camera khởi động lại, sau đó
 *    phải để người dùng bấm.
 * 3. **Không bao giờ hỏi lại.** `503` nghĩa là route **có** nhưng chưa có
 *    khung nào trong bộ nhớ — khung sẽ tới khi camera chạy, nên phải tiếp tục
 *    thử; bỏ qua ca này là màn hình đứng ở "Chưa có khung hình" mãi dù camera
 *    đã lên.
 * 4. **Đếm `503` vào nhóm kiệt.** Đây là lỗi tinh vi: nếu `503` bị đếm như lỗi
 *    mạng thì sau `MAX_AUTO_RETRY` nhịp (6 giây) app **dừng tự tải ảnh** chỉ
 *    vì camera khởi động chậm — đúng lúc cần kiên nhẫn nhất. Vì vậy `503`
 *    **không** cộng vào bộ đếm và **không** làm dừng vòng; nó khác hẳn `403`
 *    ở chỗ tình trạng sẽ tự khỏi mà không ai phải sửa cấu hình.
 */

/** Số lần tự thử lại liên tiếp trước khi dừng và chờ người dùng bấm. */
export const MAX_AUTO_RETRY = 3;

/** Vì sao vòng tải dừng; `none` = còn chạy. */
export type FrameStopReason =
  /** Còn tiếp tục hỏi lại theo nhịp. */
  | 'none'
  /** 403 — `web.stream_enabled: false`. Sửa cấu hình rồi thử lại. */
  | 'disabled'
  /** 404 — bản dashboard chưa có route `/api/frame`. */
  | 'missing'
  /** Chưa cấu hình địa chỉ, hoặc đã thử đủ `MAX_AUTO_RETRY` lần. */
  | 'exhausted';

/** Trạng thái bộ đếm sau khi xử lý một lượt thất bại. */
export type FrameRetryState = {
  /** Số lần thất bại liên tiếp (đã cộng lượt vừa rồi nếu có tính). */
  retryCount: number;
  /** Lý do dừng vòng; `none` nghĩa là nhịp sau vẫn hỏi tiếp. */
  stopReason: FrameStopReason;
};

/** Thông tin tối thiểu của một lượt thất bại. */
export type FrameFailure = {
  /** `kind` của `ApiError`. */
  kind: 'network' | 'timeout' | 'cancelled' | 'config' | 'http' | 'bad-payload';
  /** Mã HTTP, `null` khi không có phản hồi. */
  status: number | null;
};

/**
 * Tính trạng thái bộ đếm sau một lượt thất bại.
 *
 * `previous` là trạng thái **trước** lượt này (ban đầu `{retryCount: 0,
 * stopReason: 'none'}`).
 *
 * Lượt bị huỷ (`cancelled`) không tính là thất bại và không đổi gì: người
 * dùng rời màn hình không phải lỗi của máy chủ.
 */
export function afterFrameFailure(
  failure: FrameFailure,
  previous: FrameRetryState,
): FrameRetryState {
  if (failure.kind === 'cancelled') return previous;

  // Chưa cấu hình / địa chỉ sai: không có nhịp nào tự sửa được.
  if (failure.kind === 'config') {
    return { retryCount: previous.retryCount, stopReason: 'exhausted' };
  }

  // 403: stream đang tắt. 404: bản dashboard chưa có route. Cả hai là cấu
  // hình/bản cài, không phải sự cố tạm thời.
  if (failure.status === 403) {
    return { retryCount: previous.retryCount, stopReason: 'disabled' };
  }
  if (failure.status === 404) {
    return { retryCount: previous.retryCount, stopReason: 'missing' };
  }

  // 503: route có, chỉ là chưa có khung nào trong bộ nhớ. Camera chậm khởi
  // động là chuyện bình thường, và tình trạng này tự khỏi — nên KHÔNG đếm và
  // KHÔNG dừng. Đếm vào đây sẽ làm app bỏ ảnh sau 3 nhịp (6 giây) đúng lúc
  // cần kiên nhẫn nhất. Giữ nguyên `retryCount` cũ thay vì reset về 0: nếu
  // trước đó đã có lỗi mạng thật thì không được xoá dấu vết của nó.
  if (failure.status === 503) {
    return { retryCount: previous.retryCount, stopReason: 'none' };
  }

  // Còn lại: lỗi mạng, timeout, 500, 502, và payload hỏng. Đều có thể khỏi
  // nhưng cũng có thể không, nên đếm và dừng khi đã thử đủ.
  const retryCount = previous.retryCount + 1;
  return {
    retryCount,
    stopReason: retryCount >= MAX_AUTO_RETRY ? 'exhausted' : 'none',
  };
}

/** `true` khi nhịp kế tiếp được phép gọi `GET /api/frame`. */
export function shouldPollAgain(state: FrameRetryState): boolean {
  return state.stopReason === 'none';
}

/** Trạng thái ban đầu của bộ đếm. */
export const INITIAL_RETRY_STATE: FrameRetryState = { retryCount: 0, stopReason: 'none' };
