/**
 * Màn 2 — Ảnh camera.
 *
 * Có **hai chế độ xem**, người dùng chuyển bằng nút trong màn:
 *
 * 1. **Trực tiếp (MJPEG qua WebView)** — mượt như dashboard web. `GET /stream`
 *    trả `multipart/x-mixed-replace`; `<Image>` của React Native **không** đọc
 *    được luồng vô hạn (nó tải một URL **một** lần), nhưng `WebView` thì đọc
 *    được vì đó là trình duyệt thật. Đây là chế độ mặc định khi
 *    `stream_enabled` bật.
 * 2. **Khung tĩnh (`GET /api/frame`)** — dự phòng. Mỗi lượt là một ảnh JPEG
 *    trọn vẹn nên **không** phụ thuộc WebView; chậm hơn (tải theo nhịp
 *    `FRAME_REFRESH_MS`), nhưng vẫn xem được khi WebView không dùng được
 *    (ví dụ chính sách mạng chặn, hoặc cần tiết kiệm pin).
 *
 * Vì sao giữ cả hai thay vì chỉ MJPEG: `/api/frame` là đường duy nhất còn lại
 * khi WebView hỏng, và nó cho biết chính xác lỗi HTTP (403/404/503) bằng câu
 * tiếng Việt — WebView chỉ hiện một trang trắng, không phân biệt được nguyên
 * nhân. Bỏ nó đi là mất khả năng chẩn đoán.
 *
 * Ba trạng thái phải phân biệt được, và đây là chỗ dễ làm ẩu nhất:
 * - **403** — `web.stream_enabled: false`. Đây là *cấu hình*, không phải sự
 *   cố: hiện hướng dẫn bật, **không** tự thử lại liên tục.
 * - **404** — bản dashboard đang chạy **chưa có** route này (nhiệm vụ thêm
 *   route có thể chưa xong). Nói đúng là "máy chủ chưa có route", không nói
 *   "lỗi mạng", và không được crash.
 * - **503** — route có, nhưng chưa có khung nào trong RAM (camera chưa mở).
 *   Tự thử lại vì khung sẽ tới khi camera chạy.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Linking,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { WebView } from 'react-native-webview';

import { FRAME_TIMEOUT_MS, type FramePayload } from '../api/client';
import {
  INITIAL_RETRY_STATE,
  afterFrameFailure,
  shouldPollAgain,
  type FrameRetryState,
} from '../api/framePolicy';
import type { ApiError } from '../api/errors';
import { normalizeStatus } from '../api/payload';
import { Button, Card, Chip, ErrorBanner, Label, Notice, Screen } from '../components/ui';
import { useApp } from '../context/AppContext';
import { colors, radius, spacing, type as typo } from '../theme';

/**
 * Nhịp tải khung ở chế độ ảnh tĩnh.
 *
 * 300 ms ≈ 3,3 lượt/giây — đủ để thấy chuyển động, không phải 0,5 lượt/giây
 * như giá trị 2000 ms ban đầu (chậm gấp 4 lần và là lý do người dùng báo
 * "app chậm" trong khi web mượt).
 *
 * Không hạ thấp hơn nữa: mỗi lượt là một request HTTP mới (bắt tay + header +
 * JPET vài chục KB), nên sàn thực tế của cách này quanh 5–10 lượt/giây tuỳ
 * LAN. Muốn mượt hơn thì dùng chế độ **Trực tiếp**, không phải poll dày hơn.
 */
const FRAME_REFRESH_MS = 300;

type FrameState = {
  data: FramePayload | null;
  error: ApiError | null;
  loading: boolean;
  /** Lỗi 403 (stream tắt) — dừng tự làm mới, hiện hướng dẫn. */
  streamDisabled: boolean;
  /** Lỗi 404 — bản dashboard chưa có route `/api/frame`. */
  routeMissing: boolean;
  /** Lỗi 503 — route có nhưng chưa có khung; tự thử lại. */
  noFrameYet: boolean;
};

/** Cách xem: luồng trực tiếp (mượt) hay ảnh tĩnh (dự phòng). */
type ViewMode = 'live' | 'still';

const INITIAL: FrameState = {
  data: null,
  error: null,
  loading: true,
  streamDisabled: false,
  routeMissing: false,
  noFrameYet: false,
};

/** `focused` do thanh tab truyền vào: rời tab là dừng tải ảnh. */
export function CameraScreen({ focused }: { focused: boolean }): React.ReactElement {
  const { api, baseUrl, loading: configLoading } = useApp();
  const [state, setState] = useState<FrameState>(INITIAL);
  /** `stream_enabled` từ `/api/status` — công bố ở `app.py:427`. */
  const [streamEnabled, setStreamEnabled] = useState<boolean | null>(null);
  /**
   * Cách xem hiện tại. Mặc định `live` vì đó là thứ người dùng mong đợi
   * ("web mượt thì app cũng phải mượt"). Tự lùi về `still` khi biết chắc
   * `stream_enabled = false` hoặc khi WebView báo lỗi tải.
   */
  const [mode, setMode] = useState<ViewMode>('live');
  /** WebView báo không tải được luồng — hiện gợi ý chuyển sang ảnh tĩnh. */
  const [liveFailed, setLiveFailed] = useState(false);

  const mountedRef = useRef(true);
  const busyRef = useRef(false);
  const controllerRef = useRef<AbortController | null>(null);
  /**
   * Bộ đếm + lý do dừng, giữ trong ref thay vì đọc `state` bên trong effect.
   *
   * Lý do quan trọng: `state.error` là một object mới sau mỗi lần lỗi, nên
   * nếu effect phụ thuộc nó thì mỗi lần lỗi sẽ **khởi động lại cả vòng** —
   * `clearInterval` rồi `loadFrame()` ngay. Một máy chủ đang lỗi sẽ bị hỏi dồn
   * dập hơn cả khi mọi thứ bình thường, ngược hẳn ý định. Quyết định "có thử
   * lại hay không" nằm trong `framePolicy.ts` (thuần, có test).
   */
  const retryRef = useRef<FrameRetryState>(INITIAL_RETRY_STATE);
  /** Đếm lượt bấm "Thử lại" để effect khởi động lại vòng tải. */
  const [attempt, setAttempt] = useState(0);

  const loadFrame = useCallback(async (): Promise<void> => {
    if (busyRef.current) return;
    busyRef.current = true;
    const controller = new AbortController();
    controllerRef.current = controller;
    try {
      const result = await api.getFrame({
        signal: controller.signal,
        timeoutMs: FRAME_TIMEOUT_MS,
      });
      if (!mountedRef.current) return;
      if (result.ok) {
        retryRef.current = INITIAL_RETRY_STATE;
        setState({
          data: result.data,
          error: null,
          loading: false,
          streamDisabled: false,
          routeMissing: false,
          noFrameYet: false,
        });
        return;
      }
      // Rời màn: không phải lỗi, không hiện gì, không đổi bộ đếm.
      if (result.error.kind === 'cancelled') return;
      retryRef.current = afterFrameFailure(
        { kind: result.error.kind, status: result.error.status },
        retryRef.current,
      );
      // **Giữ khung cuối** khi lỗi (setState dạng hàm, giống `usePoll`).
      //
      // Trước đây nhánh này đặt `data: null`, tức một nhịp 503 hay một lần
      // mất mạng xoá luôn ảnh đang xem — màn hình nhảy về ô trống dù khung
      // vừa tải vẫn còn đúng. Ảnh cũ **có** nhãn thời gian riêng nên người
      // dùng biết nó cũ; xoá nó chỉ làm mất thông tin.
      setState((prev) => ({
        data: prev.data,
        error: result.error,
        loading: false,
        streamDisabled: result.status === 403,
        routeMissing: result.status === 404,
        noFrameYet: result.status === 503,
      }));
    } finally {
      busyRef.current = false;
      controllerRef.current = null;
    }
  }, [api]);

  // Hỏi `/api/status` một lần khi mở màn để biết `stream_enabled`; nếu tắt
  // thì hiện hướng dẫn ngay, khỏi phải chờ một lời gọi ảnh chắc chắn 403.
  useEffect(() => {
    if (!focused || !baseUrl || configLoading) return;
    let cancelled = false;
    // Huỷ thật khi rời màn, không chỉ bỏ qua kết quả: một lời gọi `/api/status`
    // treo tới hết hạn chờ vẫn chiếm một khe trên máy chủ Pi (thứ đang phải lo
    // camera), và promise của nó sẽ giữ closure cho tới khi xong.
    const controller = new AbortController();
    api
      .getStatus({ signal: controller.signal })
      .then((result) => {
        if (cancelled || !mountedRef.current) return;
        if (result.ok) setStreamEnabled(normalizeStatus(result.data).streamEnabled);
      })
      .catch(() => {
        // Không lấy được status thì cứ thử ảnh; lỗi thật sẽ hiện ở vòng ảnh.
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [api, baseUrl, focused, configLoading]);

  useEffect(() => {
    mountedRef.current = true;
    // Chế độ Trực tiếp không cần vòng poll: WebView tự đọc luồng. Chỉ chạy
    // poll khi đang ở chế độ ảnh tĩnh, nếu không sẽ tải hai thứ cùng lúc.
    if (!focused || !baseUrl || configLoading || mode !== 'still') {
      return () => {
        mountedRef.current = false;
      };
    }
    // Mỗi lần effect chạy lại (mở tab, đổi địa chỉ, bấm Thử lại) là một vòng
    // mới: đặt lại bộ đếm, nếu không vòng mới sẽ tự tắt ngay từ nhịp đầu.
    retryRef.current = INITIAL_RETRY_STATE;

    let stopped = false;
    void loadFrame();
    const timer = setInterval(() => {
      if (stopped) return;
      // Dừng hẳn khi nguyên nhân là cấu hình/bản cũ/hết số lần thử: tự hỏi
      // lại mỗi 2 s chỉ làm nóng máy và che mất hướng dẫn người dùng cần đọc.
      if (!shouldPollAgain(retryRef.current)) return;
      void loadFrame();
    }, FRAME_REFRESH_MS);

    return () => {
      stopped = true;
      mountedRef.current = false;
      clearInterval(timer);
      controllerRef.current?.abort();
      busyRef.current = false;
    };
  }, [focused, baseUrl, loadFrame, attempt, mode]);

  const onRetry = useCallback(() => {
    retryRef.current = INITIAL_RETRY_STATE;
    setLiveFailed(false);
    setState((prev) => ({ ...prev, error: null, loading: true }));
    setAttempt((n) => n + 1);
  }, []);

  const header = state.data ? (
    <Chip text={`${formatClock(state.data.receivedAt)}`} tone="good" />
  ) : null;

  /** Địa chỉ luồng MJPEG — cùng máy chủ, khác route. */
  const streamUrl = baseUrl ? `${baseUrl}/stream` : '';

  return (
    <Screen
      title="Camera"
      subtitle={
        mode === 'live'
          ? 'Luồng trực tiếp (mượt như dashboard web)'
          : `Ảnh tĩnh, tải lại mỗi ${(FRAME_REFRESH_MS / 1000).toFixed(1)} giây`
      }
      right={header}
    >
      {!baseUrl ? (
        <Notice
          title="Chưa cấu hình máy chủ"
          body="Mở tab Kết nối và nhập IP LAN của máy chạy dashboard trước khi xem camera."
          tone="warn"
        />
      ) : null}

      {baseUrl && streamEnabled === false && !state.data ? (
        <Notice
          title="Xem trực tiếp đang tắt"
          body={
            'Máy chủ báo stream_enabled = false. Bật "web.stream_enabled: true" trong ' +
            'config.yaml rồi khởi động lại dashboard để xem ảnh.'
          }
          tone="warn"
        />
      ) : null}

      {baseUrl && state.routeMissing ? (
        <Notice
          title="Máy chủ chưa có route ảnh"
          body={
            'Dashboard đang chạy trả 404 cho GET /api/frame — bản đó chưa có route ảnh tĩnh. ' +
            'Cập nhật máy chủ lên bản có GET /api/frame rồi bấm Thử lại. App vẫn dùng được các màn khác.'
          }
          tone="warn"
        />
      ) : null}

      {baseUrl && state.streamDisabled ? (
        <Notice
          title="Không xem được ảnh"
          body={
            state.error?.message ??
            'Máy chủ từ chối (403). Tính năng xem trực tiếp đang tắt trong config.yaml.'
          }
          tone="warn"
        />
      ) : null}

      {baseUrl && state.error && !state.streamDisabled && !state.routeMissing ? (
        <ErrorBanner
          message={state.error.message}
          hint={state.noFrameYet ? 'Máy chủ chưa có khung nào trong bộ nhớ — thử lại sau vài giây.' : undefined}
          onRetry={onRetry}
          retrying={state.loading}
        />
      ) : null}

      {/* Ảnh vẫn còn nhưng lượt tải mới nhất hỏng: nói rõ đây là ảnh **cũ**,
          kèm mốc thời gian. Không có nhãn này, người dùng nhìn ảnh đứng yên và
          tưởng camera vẫn đang trực tiếp. */}
      {state.data && state.error ? (
        <Text style={[typo.caption, styles.staleNote]}>
          Ảnh cuối lúc {formatClock(state.data.receivedAt)} — chưa tải được khung mới.
        </Text>
      ) : null}

      <Card style={styles.frameCard}>
        <View style={styles.frameHead}>
          <Label>{mode === 'live' ? 'Luồng trực tiếp' : 'Khung mới nhất'}</Label>
          {mode === 'still' && state.data ? (
            <Text style={[typo.caption, styles.muted]}>
              {(state.data.byteLength / 1024).toFixed(0)} KB · cập nhật{' '}
              {formatClock(state.data.receivedAt)}
            </Text>
          ) : null}
        </View>

        <View style={styles.modeRow}>
          <Button
            label="Trực tiếp"
            onPress={() => {
              setLiveFailed(false);
              setMode('live');
            }}
            variant={mode === 'live' ? 'primary' : 'secondary'}
            style={styles.modeButton}
          />
          <Button
            label="Ảnh tĩnh"
            onPress={() => setMode('still')}
            variant={mode === 'still' ? 'primary' : 'secondary'}
            style={styles.modeButton}
          />
        </View>

        <View style={styles.frameBox}>
          {mode === 'live' && baseUrl ? (
            <WebView
              source={{ uri: streamUrl }}
              style={styles.frame}
              originWhitelist={['*']}
              // Không cho zoom: luồng là ảnh camera, pinch làm nhoè.
              scalesPageToFit={false}
              javaScriptEnabled={false}
              // Android cần bật để hiển thị nội dung http:// trong WebView.
              mixedContentMode="always"
              // `domStorage` tắt: trang chỉ có một thẻ <img> của luồng.
              domStorageEnabled={false}
              accessibilityLabel="Luồng camera trực tiếp"
              onError={() => setLiveFailed(true)}
              onHttpError={() => setLiveFailed(true)}
            />
          ) : mode === 'live' ? (
            <View style={styles.framePlaceholder}>
              <Text style={[typo.caption, styles.muted]}>
                Chưa cấu hình máy chủ — mở tab Kết nối trước.
              </Text>
            </View>
          ) : state.data ? (
            <Image
              source={{ uri: state.data.uri }}
              style={styles.frame}
              resizeMode="contain"
              accessibilityLabel="Khung hình mới nhất từ camera phòng học"
            />
          ) : (
            <View style={styles.framePlaceholder}>
              {state.loading ? (
                <>
                  <ActivityIndicator color={colors.accent} />
                  <Text style={[typo.caption, styles.muted]}>Đang tải khung đầu tiên…</Text>
                </>
              ) : (
                <Text style={[typo.caption, styles.muted]}>
                  {state.routeMissing
                    ? 'Máy chủ chưa có route ảnh.'
                    : state.streamDisabled
                      ? 'Xem trực tiếp đang tắt.'
                      : 'Chưa có khung hình.'}
                </Text>
              )}
            </View>
          )}
        </View>

        {mode === 'live' && liveFailed ? (
          <Notice
            title="Không tải được luồng trực tiếp"
            body={
              'WebView không đọc được /stream. Nguyên nhân thường gặp: tường lửa chặn cổng, ' +
              'hoặc web.stream_enabled = false trong config.yaml. Bấm "Ảnh tĩnh" để xem bằng ' +
              'đường dự phòng — đường đó báo được lỗi HTTP cụ thể.'
            }
            tone="warn"
          />
        ) : null}

        {mode === 'still' ? (
          <>
            <Button
              label="Tải khung mới"
              onPress={onRetry}
              variant="quiet"
              busy={state.loading && !!state.data}
            />
            <Text style={[typo.caption, styles.muted]}>
              Chế độ ảnh tĩnh chậm hơn Trực tiếp vì mỗi lượt là một request HTTP
              riêng, không phải một luồng liên tục.
            </Text>
          </>
        ) : null}
      </Card>

      {mode === 'live' && baseUrl ? (
        <Button
          label="Mở luồng trong trình duyệt"
          onPress={() => void Linking.openURL(streamUrl)}
          variant="quiet"
        />
      ) : null}

      <Text style={[typo.caption, styles.footnote]}>
        Ảnh chỉ đi qua bộ nhớ của máy chủ và tới điện thoại trong LAN; dashboard không lưu ảnh.
      </Text>
    </Screen>
  );
}

/** "14:07:31" theo giờ máy — đọc được ngay, không cần bảng màu. */
function formatClock(epochMs: number): string {
  return new Date(epochMs).toLocaleTimeString('vi-VN');
}

const styles = StyleSheet.create({
  frameCard: {
    gap: spacing.md,
  },
  frameHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: spacing.sm,
  },
  modeRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  modeButton: {
    flex: 1,
  },
  frameBox: {
    aspectRatio: 4 / 3,
    backgroundColor: '#0A0E12',
    borderRadius: radius.md,
    overflow: 'hidden',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  frame: {
    width: '100%',
    height: '100%',
  },
  framePlaceholder: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    padding: spacing.lg,
  },
  muted: {
    color: colors.textMuted,
  },
  staleNote: {
    color: colors.warn,
  },
  footnote: {
    color: colors.textFaint,
  },
});


