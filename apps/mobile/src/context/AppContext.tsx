/**
 * Ngữ cảnh dùng chung: địa chỉ máy chủ + client.
 *
 * Vì sao cần: địa chỉ nhập ở màn Kết nối nhưng **năm màn khác** phải dùng
 * ngay. Truyền qua props xuống từng màn sẽ phải luồn qua thanh tab, và mỗi
 * màn lại tự dựng client riêng là chỗ dễ nảy sinh lời gọi mạng thứ hai không
 * qua lớp client.
 */
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

import { createApiClient, type ApiClient } from '../api/client';
import { clearBaseUrl, loadBaseUrl, saveBaseUrl } from '../storage/baseUrl';

type AppContextValue = {
  /** Địa chỉ gốc đã chuẩn hoá; `''` khi chưa cấu hình. */
  baseUrl: string;
  /** Client gắn địa chỉ hiện tại; đổi địa chỉ là đổi client. */
  api: ApiClient;
  /**
   * `true` cho tới khi đọc xong AsyncStorage.
   *
   * Màn hình **phải** chờ cờ này rồi mới hỏi máy chủ. Nếu không, lượt làm mới
   * đầu tiên chạy với `baseUrl` rỗng và hiện "Chưa nhập địa chỉ máy chủ" —
   * một lỗi giả, chỉ nháy một nhịp, nhưng đủ để người dùng tưởng mất cấu hình
   * (và với màn camera thì nó còn dựng cả khối hướng dẫn sai).
   */
  loading: boolean;
  /** Đặt địa chỉ mới (đã chuẩn hoá) và ghi xuống bộ nhớ. */
  setBaseUrl: (next: string) => Promise<boolean>;
  /** Xoá địa chỉ đã lưu. */
  clear: () => Promise<boolean>;
};

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: React.ReactNode }): React.ReactElement {
  const [baseUrl, setBaseUrlState] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    loadBaseUrl()
      .then((stored) => {
        if (!mounted) return;
        setBaseUrlState(stored);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const setBaseUrl = useCallback(async (next: string) => {
    const written = await saveBaseUrl(next);
    if (written) {
      setBaseUrlState(next);
    }
    return written;
  }, []);

  const clear = useCallback(async () => {
    const cleared = await clearBaseUrl();
    if (cleared) {
      setBaseUrlState('');
    }
    return cleared;
  }, []);

  const api = useMemo(() => createApiClient(baseUrl), [baseUrl]);

  const value = useMemo<AppContextValue>(
    () => ({ baseUrl, api, loading, setBaseUrl, clear }),
    [baseUrl, api, loading, setBaseUrl, clear],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

/** Lấy ngữ cảnh; ném lỗi rõ ràng nếu ai đó quên bọc `<AppProvider>`. */
export function useApp(): AppContextValue {
  const value = useContext(AppContext);
  if (!value) {
    throw new Error('useApp() phải nằm trong <AppProvider>.');
  }
  return value;
}
