/**
 * Ngữ cảnh dùng chung: địa chỉ máy chủ + client + chế độ giao diện Sáng/Tối.
 *
 * Vì sao cần: địa chỉ nhập ở màn Kết nối nhưng mọi màn khác phải dùng ngay,
 * và chế độ Sáng/Tối phải đổi đồng bộ từ thanh trạng thái, các thẻ, tới thanh tab.
 */
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { createApiClient, type ApiClient } from '../api/client';
import { clearBaseUrl, loadBaseUrl, saveBaseUrl } from '../storage/baseUrl';
import {
  loadThemeMode,
  saveThemeMode,
  type ThemeMode,
} from '../storage/theme';
import {
  createTypography,
  darkColors,
  getPalette,
  type ThemePalette,
  type ThemeTypography,
} from '../theme';

type AppContextValue = {
  /** Địa chỉ gốc đã chuẩn hoá; `''` khi chưa cấu hình. */
  baseUrl: string;
  /** Client gắn địa chỉ hiện tại; đổi địa chỉ là đổi client. */
  api: ApiClient;
  /**
   * `true` cho tới khi đọc xong AsyncStorage.
   *
   * Màn hình **phải** chờ cờ này rồi mới hỏi máy chủ.
   */
  loading: boolean;
  /** Đặt địa chỉ mới (đã chuẩn hoá) và ghi xuống bộ nhớ. */
  setBaseUrl: (next: string) => Promise<boolean>;
  /** Xoá địa chỉ đã lưu. */
  clear: () => Promise<boolean>;
  /** Chế độ giao diện hiện tại (`'dark'` | `'light'`). */
  themeMode: ThemeMode;
  /** Đặt chế độ giao diện và lưu bền vững vào AsyncStorage. */
  setThemeMode: (next: ThemeMode) => Promise<boolean>;
  /** Đảo nhanh giữa giao diện Sáng và Tối. */
  toggleThemeMode: () => Promise<boolean>;
};

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: React.ReactNode }): React.ReactElement {
  const [baseUrl, setBaseUrlState] = useState('');
  const [themeMode, setThemeModeState] = useState<ThemeMode>('dark');
  const themeModeRef = useRef<ThemeMode>('dark');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    Promise.all([loadBaseUrl(), loadThemeMode()])
      .then(([storedUrl, storedTheme]) => {
        if (!mounted) return;
        setBaseUrlState(storedUrl);
        if (storedTheme) {
          themeModeRef.current = storedTheme;
          setThemeModeState(storedTheme);
        }
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

  const setThemeMode = useCallback(async (next: ThemeMode) => {
    themeModeRef.current = next;
    setThemeModeState(next);
    return saveThemeMode(next);
  }, []);

  const toggleThemeMode = useCallback(async () => {
    const nextMode: ThemeMode = themeModeRef.current === 'dark' ? 'light' : 'dark';
    themeModeRef.current = nextMode;
    setThemeModeState(nextMode);
    return saveThemeMode(nextMode);
  }, []);

  const api = useMemo(() => createApiClient(baseUrl), [baseUrl]);

  const value = useMemo<AppContextValue>(
    () => ({
      baseUrl,
      api,
      loading,
      setBaseUrl,
      clear,
      themeMode,
      setThemeMode,
      toggleThemeMode,
    }),
    [baseUrl, api, loading, setBaseUrl, clear, themeMode, setThemeMode, toggleThemeMode],
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

export type ThemeContextSnapshot = {
  mode: ThemeMode;
  isDark: boolean;
  palette: ThemePalette;
  typo: ThemeTypography;
  setThemeMode: (next: ThemeMode) => Promise<boolean>;
  toggleThemeMode: () => Promise<boolean>;
};

const FALLBACK_TYPO = createTypography(darkColors);

/**
 * Đọc bảng màu và kiểu chữ theo chế độ Sáng / Tối hiện hành.
 * Nếu được gọi ngoài `<AppProvider>` (ví dụ bài test đơn lẻ), rơi an toàn về `dark`.
 */
export function useTheme(): ThemeContextSnapshot {
  const ctx = useContext(AppContext);
  const mode: ThemeMode = ctx?.themeMode ?? 'dark';
  return useMemo(() => {
    const palette = getPalette(mode);
    return {
      mode,
      isDark: mode === 'dark',
      palette,
      typo: mode === 'dark' ? FALLBACK_TYPO : createTypography(palette),
      setThemeMode: ctx?.setThemeMode ?? (async () => false),
      toggleThemeMode: ctx?.toggleThemeMode ?? (async () => false),
    };
  }, [ctx?.setThemeMode, ctx?.toggleThemeMode, mode]);
}
