/**
 * Quản lý vòng đời cho một hành động bất đồng bộ do người dùng bấm nút
 * (bật/tắt tiếng, xoay PTZ, bắt đầu/dừng phiên, đổi giọng, kiểm tra kết nối).
 *
 * Gom hai quy tắc dễ quên khi viết lặp lại ở từng màn hình:
 * 1. **Huỷ lệnh trước nếu còn đang chạy:** bấm liên tiếp không được để hai
 *    request đua nhau rồi phản hồi cũ ghi đè phản hồi mới.
 * 2. **Không `setState` sau khi rời màn:** khi unmount, `AbortController` bị
 *    `abort()` thật sự (để Pi không tốn tài nguyên xử lý tiếp nếu huỷ kịp) và
 *    `isActive()` trả `false` ngay sau `await`.
 */
import { useCallback, useEffect, useMemo, useRef } from 'react';

export type AsyncActionContext = {
  /** Signal truyền xuống `api.*({ signal })`. */
  signal: AbortSignal;
  /** `true` khi màn hình vẫn đang mount **và** lượt này chưa bị thay thế/huỷ. */
  isActive: () => boolean;
};

export type AsyncActionHandle = {
  /** Bắt đầu một lượt mới (tự `abort()` lượt trước nếu còn chạy). */
  begin: () => AsyncActionContext;
  /** Tiện ích bọc `begin()` quanh hàm async của màn hình. */
  run: <T>(fn: (ctx: AsyncActionContext) => Promise<T>) => Promise<T>;
  /** Kiểm tra màn hình còn mount hay không (dùng cho thao tác ngoài mạng như AsyncStorage). */
  isMounted: () => boolean;
  /** Huỷ thủ công lượt đang chạy (nếu có). */
  abort: () => void;
};

export function useAsyncAction(): AsyncActionHandle {
  const mountedRef = useRef(true);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, []);

  const abort = useCallback((): void => {
    controllerRef.current?.abort();
    controllerRef.current = null;
  }, []);

  const begin = useCallback((): AsyncActionContext => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    return {
      signal: controller.signal,
      isActive: () => mountedRef.current && !controller.signal.aborted,
    };
  }, []);

  const run = useCallback(
    <T>(fn: (ctx: AsyncActionContext) => Promise<T>): Promise<T> => fn(begin()),
    [begin],
  );

  const isMounted = useCallback((): boolean => mountedRef.current, []);

  return useMemo(
    () => ({ begin, run, isMounted, abort }),
    [begin, run, isMounted, abort],
  );
}
