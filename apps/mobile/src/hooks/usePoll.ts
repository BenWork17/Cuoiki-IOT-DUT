/**
 * Vòng tự làm mới tuần tự cho một màn hình.
 *
 * Ba quy tắc của tài liệu yêu cầu §5.2 được cài ở đây, **một lần cho mọi
 * màn** — viết lại ở từng màn là cách chắc chắn nhất để có màn quên:
 * 1. **Không chồng request:** nhịp nào request trước chưa xong thì bỏ nhịp đó
 *    (`setInterval` + cờ `busyRef`). Máy Pi phải lo camera, không được nhận
 *    hai request dồn dập vì một màn hình chậm.
 * 2. **Không setState sau unmount:** `mountedRef` + `AbortController` huỷ
 *    request đang chờ khi rời màn.
 * 3. **Chỉ chạy khi màn đang hiện:** người gọi truyền `enabled` = kết quả của
 *    `useIsFocused()`, nhờ vậy chuyển tab là ngừng hỏi (tiết kiệm pin và
 *    không làm bẩn log của máy chủ).
 */
import { useCallback, useEffect, useRef, useState } from 'react';

/** Kết quả một lượt tải; `null` khi chưa có lượt nào xong. */
export type PollState<T> = {
  data: T | null;
  /** Lỗi của lượt gần nhất; `null` khi lượt đó thành công. */
  error: import('../api/errors').ApiError | null;
  /** `true` đang có request chạy (lượt đầu hoặc lượt làm mới). */
  loading: boolean;
  /** `Date.now()` của lượt thành công gần nhất, để hiện "cập nhật lúc …". */
  updatedAt: number | null;
};

export type PollResult<T> = {
  /** Lượt tải xong (hoặc lỗi) và trả dữ liệu mới. */
  ok: boolean;
  data?: T;
  error?: import('../api/errors').ApiError;
  /** `true` khi lượt này không được áp vì màn đã unmount — không phải lỗi. */
  ignored: boolean;
};

/** Nhịp làm mới được phép: không nhanh hơn dashboard web (`app.js:1708-1709`). */
export const MIN_POLL_MS = 1000;

/** Nhịp mặc định của app: chậm hơn web để tiết kiệm pin (yêu cầu §5.2). */
export const DEFAULT_POLL_MS = 2000;

/**
 * Chạy `fetcher` mỗi `intervalMs` khi `enabled`, trả dữ liệu + lỗi + nút thử lại.
 *
 * `fetcher` phải nhận `AbortSignal` và chuyển nó xuống lớp client, nếu không
 * việc huỷ khi rời màn chỉ là hình thức.
 */
export function usePoll<T>(
  fetcher: (signal: AbortSignal) => Promise<PollResult<T>>,
  options: { enabled: boolean; intervalMs?: number },
): PollState<T> & { refresh: () => void } {
  const intervalMs = Math.max(
    MIN_POLL_MS,
    options.intervalMs ?? DEFAULT_POLL_MS,
  );
  const [state, setState] = useState<PollState<T>>({
    data: null,
    error: null,
    loading: true,
    updatedAt: null,
  });

  const mountedRef = useRef(true);
  const busyRef = useRef(false);
  const controllerRef = useRef<AbortController | null>(null);
  // `fetcher` đổi mỗi lần render (closure mới) — giữ trong ref để effect
  // không bị khởi động lại, nếu không vòng làm mới sẽ reset liên tục.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const run = useCallback(async (): Promise<void> => {
    if (busyRef.current) return;
    busyRef.current = true;
    // Bật cờ "đang tải" **ngay khi** bắt đầu, trước khi chờ máy chủ.
    //
    // Không có dòng này, nút "Thử lại"/"Làm mới ngay" bấm xong trông như không
    // có gì xảy ra: nút chỉ quay khi `loading` bật, mà trước đây `loading` chỉ
    // được đặt trong nhánh kết quả — tức sau khi request đã xong. Trên mạng
    // LAN tới Pi chậm (và timeout tới 5 s), người dùng sẽ bấm lại nhiều lần.
    // Vẫn giữ nguyên tắc không chồng request: cửa `busyRef` ở trên chặn nhịp
    // đến khi lượt trước kết thúc.
    setState((prev) => ({ ...prev, loading: true }));
    const controller = new AbortController();
    controllerRef.current = controller;
    try {
      const result = await fetcherRef.current(controller.signal);
      if (!mountedRef.current) return;
      if (result.ignored) {
        // Lượt bị huỷ (rời màn hoặc đổi địa chỉ): không phải lỗi, nhưng phải
        // hạ cờ "đang tải" — nếu không, lần vào lại màn sẽ thấy nút quay mãi.
        setState((prev) => (prev.loading ? { ...prev, loading: false } : prev));
        return;
      }
      if (result.ok) {
        setState({
          data: result.data ?? null,
          error: null,
          loading: false,
          updatedAt: Date.now(),
        });
      } else {
        // Giữ dữ liệu cũ khi lỗi: mất mạng một nhịp không được làm màn hình
        // trắng. Nhưng lỗi thì **phải** hiện, kèm nút thử lại.
        setState((prev) => ({
          data: prev.data,
          error: result.error ?? null,
          loading: false,
          updatedAt: prev.updatedAt,
        }));
      }
    } finally {
      busyRef.current = false;
      controllerRef.current = null;
    }
  }, []);

  const refresh = useCallback((): void => {
    void run();
  }, [run]);

  useEffect(() => {
    mountedRef.current = true;
    if (!options.enabled) {
      return () => {
        mountedRef.current = false;
      };
    }

    void run();
    const timer = setInterval(() => {
      void run();
    }, intervalMs);

    return () => {
      mountedRef.current = false;
      clearInterval(timer);
      // Huỷ request đang chờ: nếu không, máy chủ vẫn phải xử lý nó và
      // promise sẽ cố setState sau unmount.
      controllerRef.current?.abort();
      busyRef.current = false;
    };
  }, [options.enabled, intervalMs, run]);

  return { ...state, refresh };
}
