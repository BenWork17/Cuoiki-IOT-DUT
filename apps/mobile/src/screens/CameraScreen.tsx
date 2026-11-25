/**
 * Màn chính gộp — Camera, 3 Tín hiệu người học & Trạng thái tư thế,
 * hỗ trợ cả hai chế độ Sáng & Tối và lối tắt chuyển nhanh sang quản lý Người học.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Linking,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { WebView } from 'react-native-webview';

import { API_PATH, FRAME_TIMEOUT_MS, type FramePayload } from '../api/client';
import type { ApiError } from '../api/errors';
import { formatClock, formatDecimal } from '../api/format';
import {
  INITIAL_RETRY_STATE,
  afterFrameFailure,
  shouldPollAgain,
  type FrameRetryState,
} from '../api/framePolicy';
import { normalizeSignals, normalizeStatus } from '../api/payload';
import { buildUrl } from '../api/url';
import { LearnerSignalsSection } from '../components/LearnerSignalsSection';
import { PostureStatusSection } from '../components/PostureStatusSection';
import {
  Button,
  ErrorBanner,
  LoadingCard,
  Notice,
  Screen,
  UnconfiguredNotice,
} from '../components/ui';
import { useApp, useTheme } from '../context/AppContext';
import { useAsyncAction } from '../hooks/useAsyncAction';
import { toPollFetcher, usePoll } from '../hooks/usePoll';
import { monoFamily, radius, spacing } from '../theme';

const FRAME_REFRESH_MS = 300;

type FrameState = {
  data: FramePayload | null;
  error: ApiError | null;
  loading: boolean;
  streamDisabled: boolean;
  routeMissing: boolean;
  noFrameYet: boolean;
};

type ViewMode = 'live' | 'still';

const INITIAL: FrameState = {
  data: null,
  error: null,
  loading: true,
  streamDisabled: false,
  routeMissing: false,
  noFrameYet: false,
};

export function CameraScreen({
  focused,
  onOpenPeople,
}: {
  focused: boolean;
  /** Khi đặt trong `TabNavigator`, bấm vào ô Danh tính mở thẳng tab Người học. */
  onOpenPeople?: () => void;
}): React.ReactElement {
  const { api, baseUrl, loading: configLoading } = useApp();
  const { palette, typo } = useTheme();
  const [state, setState] = useState<FrameState>(INITIAL);
  const [mode, setMode] = useState<ViewMode>('live');
  const [liveFailed, setLiveFailed] = useState(false);
  const [mutedOverride, setMutedOverride] = useState<boolean | null>(null);
  const [muteBusy, setMuteBusy] = useState(false);
  const muteAction = useAsyncAction();

  const statusFetcher = useMemo(
    () => toPollFetcher((signal) => api.getStatus({ signal }), normalizeStatus),
    [api],
  );
  const {
    data: statusView,
    error: statusError,
    loading: statusLoading,
    updatedAt: statusUpdatedAt,
    refresh: refreshStatus,
  } = usePoll(statusFetcher, {
    enabled: focused && !configLoading && !!baseUrl,
  });

  const [signalsRouteMissing, setSignalsRouteMissing] = useState(false);
  useEffect(() => {
    setSignalsRouteMissing(false);
  }, [baseUrl]);

  const signalsFetcher = useMemo(
    () => toPollFetcher((signal) => api.getSignals({ signal }), normalizeSignals),
    [api],
  );
  const {
    data: signalsRows,
    error: signalsError,
    loading: signalsLoading,
    refresh: refreshSignals,
  } = usePoll(signalsFetcher, {
    enabled: focused && !configLoading && !!baseUrl && !signalsRouteMissing,
  });

  useEffect(() => {
    if (signalsError?.status === 404) {
      setSignalsRouteMissing(true);
    }
  }, [signalsError]);

  const streamEnabled = statusView ? statusView.streamEnabled : null;

  useEffect(() => {
    if (streamEnabled === false) {
      setMode('still');
    }
  }, [streamEnabled]);

  useEffect(() => {
    if (statusUpdatedAt !== null) {
      setMutedOverride(null);
    }
  }, [statusUpdatedAt]);

  const mountedRef = useRef(true);
  const busyRef = useRef(false);
  const controllerRef = useRef<AbortController | null>(null);
  const retryRef = useRef<FrameRetryState>(INITIAL_RETRY_STATE);
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
      if (result.error.kind === 'cancelled') return;
      retryRef.current = afterFrameFailure(
        { kind: result.error.kind, status: result.error.status },
        retryRef.current,
      );
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

  useEffect(() => {
    mountedRef.current = true;
    if (!focused || !baseUrl || configLoading || mode !== 'still') {
      return () => {
        mountedRef.current = false;
      };
    }
    retryRef.current = INITIAL_RETRY_STATE;

    let stopped = false;
    void loadFrame();
    const timer = setInterval(() => {
      if (stopped) return;
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
  }, [focused, baseUrl, configLoading, loadFrame, attempt, mode]);

  const onRetry = useCallback(() => {
    retryRef.current = INITIAL_RETRY_STATE;
    setLiveFailed(false);
    setSignalsRouteMissing(false);
    setState((prev) => ({ ...prev, error: null, loading: true }));
    setAttempt((n) => n + 1);
    refreshStatus();
    refreshSignals();
  }, [refreshSignals, refreshStatus]);

  const handleLiveFailure = useCallback(() => {
    setLiveFailed(true);
    setMode('still');
  }, []);

  const handleToggleMute = useCallback(() => {
    if (!statusView) return;
    const currentMuted = mutedOverride ?? statusView.muted;
    const nextMuted = !currentMuted;
    setMuteBusy(true);
    void muteAction.run(async ({ signal, isActive }) => {
      try {
        const res = await api.setMuted(nextMuted, { signal });
        if (!isActive()) return;
        if (res.ok) {
          setMutedOverride(typeof res.data.muted === 'boolean' ? res.data.muted : nextMuted);
        }
      } finally {
        if (isActive()) {
          setMuteBusy(false);
        }
      }
    });
  }, [api, muteAction, mutedOverride, statusView]);

  const badgeClockTs =
    mode === 'still' && state.data ? state.data.receivedAt : statusUpdatedAt;

  const liveBadge = baseUrl ? (
    <View
      style={[
        styles.livePill,
        { backgroundColor: palette.surfaceElevated, borderColor: palette.border },
      ]}
    >
      <View
        style={[
          styles.liveDot,
          {
            backgroundColor:
              statusView?.stale || state.error ? palette.warn : palette.good,
          },
        ]}
      />
      <Text
        style={[
          styles.livePillTag,
          {
            color: statusView?.stale || state.error ? palette.warn : palette.good,
          },
        ]}
      >
        {mode === 'live' ? 'LIVE' : 'TĨNH'}
      </Text>
      {badgeClockTs ? (
        <>
          <Text style={[styles.livePillSep, { color: palette.textFaint }]}>·</Text>
          <Text style={[styles.livePillClock, { color: palette.textMuted }]}>
            {formatClock(badgeClockTs)}
          </Text>
        </>
      ) : null}
    </View>
  ) : null;

  const streamUrl = baseUrl ? buildUrl(baseUrl, API_PATH.stream) : '';

  return (
    <Screen
      title="Camera & Trạng thái"
      subtitle={
        mode === 'live'
          ? 'Luồng trực tiếp từ Raspberry Pi'
          : `Ảnh tĩnh, tải lại mỗi ${formatDecimal(FRAME_REFRESH_MS / 1000, 1)} giây`
      }
      right={liveBadge}
    >
      {!baseUrl ? (
        <UnconfiguredNotice body="Mở tab Kết nối và nhập IP LAN của máy chạy dashboard trước khi xem camera và trạng thái." />
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
          hint={
            state.noFrameYet
              ? 'Máy chủ chưa có khung nào trong bộ nhớ — thử lại sau vài giây.'
              : undefined
          }
          onRetry={onRetry}
          retrying={state.loading}
        />
      ) : null}

      {state.data && state.error ? (
        <Text style={[typo.caption, { color: palette.warn }]}>
          Ảnh cuối lúc {formatClock(state.data.receivedAt)} — chưa tải được khung mới.
        </Text>
      ) : null}

      {/* 1. Camera Viewport Card (Hero) */}
      <View
        style={[
          styles.cameraCard,
          { backgroundColor: palette.surface, borderColor: palette.border },
        ]}
      >
        <View style={styles.cameraToolbar}>
          <View
            style={[styles.segmentedTrack, { backgroundColor: palette.surfaceRaised }]}
          >
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Trực tiếp"
              onPress={() => {
                setLiveFailed(false);
                setMode('live');
              }}
              style={[
                styles.segmentBtn,
                mode === 'live' ? { backgroundColor: palette.accent } : null,
              ]}
            >
              <Text
                style={[
                  styles.segmentText,
                  { color: mode === 'live' ? palette.onAccent : palette.textMuted },
                  mode === 'live' ? styles.segmentTextActive : null,
                ]}
              >
                Trực tiếp
              </Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Ảnh tĩnh"
              onPress={() => setMode('still')}
              style={[
                styles.segmentBtn,
                mode === 'still' ? { backgroundColor: palette.accent } : null,
              ]}
            >
              <Text
                style={[
                  styles.segmentText,
                  { color: mode === 'still' ? palette.onAccent : palette.textMuted },
                  mode === 'still' ? styles.segmentTextActive : null,
                ]}
              >
                Ảnh tĩnh
              </Text>
            </Pressable>
          </View>

          {mode === 'live' && baseUrl ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Mở luồng trong trình duyệt"
              onPress={() => void Linking.openURL(streamUrl)}
              style={({ pressed }) => [
                styles.browserLink,
                pressed ? { opacity: 0.7 } : null,
              ]}
            >
              <Text style={[styles.browserLinkText, { color: palette.accent }]}>
                Mở trong trình duyệt ↗
              </Text>
            </Pressable>
          ) : mode === 'still' && state.data ? (
            <Text style={[styles.kbCaption, { color: palette.textMuted }]}>
              {(state.data.byteLength / 1024).toFixed(0)} KB
            </Text>
          ) : null}
        </View>

        <View
          style={[
            styles.frameBox,
            { backgroundColor: palette.surfaceLowest, borderColor: palette.border },
          ]}
        >
          {mode === 'live' && baseUrl ? (
            <WebView
              source={{ uri: streamUrl }}
              style={styles.frame}
              originWhitelist={['*']}
              scalesPageToFit={false}
              javaScriptEnabled={false}
              mixedContentMode="always"
              domStorageEnabled={false}
              accessibilityLabel="Luồng camera trực tiếp"
              onError={handleLiveFailure}
              onHttpError={handleLiveFailure}
            />
          ) : mode === 'live' ? (
            <View style={styles.framePlaceholder}>
              <Text style={[typo.caption, { color: palette.hudText, opacity: 0.75 }]}>
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
                  <ActivityIndicator color={palette.accent} />
                  <Text style={[typo.caption, { color: palette.hudText, opacity: 0.75 }]}>
                    Đang tải khung đầu tiên…
                  </Text>
                </>
              ) : (
                <Text style={[typo.caption, { color: palette.hudText, opacity: 0.75 }]}>
                  {state.routeMissing
                    ? 'Máy chủ chưa có route ảnh.'
                    : state.streamDisabled
                      ? 'Xem trực tiếp đang tắt.'
                      : 'Chưa có khung hình.'}
                </Text>
              )}
            </View>
          )}

          {/* HUD Overlay góc trên khung hình */}
          {baseUrl ? (
            <View pointerEvents="none" style={styles.hudOverlay}>
              <View
                style={[
                  styles.hudBadge,
                  { backgroundColor: palette.hudBg, borderColor: palette.hudBorder },
                ]}
              >
                <Text style={[styles.hudBadgeText, { color: palette.hudText }]}>
                  {mode === 'live' ? '▣ MJPEG STREAM' : '▣ JPEG SNAPSHOT'}
                </Text>
              </View>
              {statusView && statusView.dataAgeS !== null ? (
                <View
                  style={[
                    styles.hudBadge,
                    { backgroundColor: palette.hudBg, borderColor: palette.hudBorder },
                  ]}
                >
                  <View
                    style={[
                      styles.hudDot,
                      { backgroundColor: statusView.stale ? '#FBBF24' : '#34D399' },
                    ]}
                  />
                  <Text
                    style={[
                      styles.hudBadgeText,
                      { color: statusView.stale ? '#FBBF24' : '#34D399' },
                    ]}
                  >
                    {formatDecimal(statusView.dataAgeS, 1)} s
                  </Text>
                </View>
              ) : null}
            </View>
          ) : null}
        </View>

        {liveFailed && !state.streamDisabled && !state.routeMissing ? (
          <Notice
            title="Không tải được luồng trực tiếp"
            body={
              'WebView không đọc được /stream nên đã tự chuyển sang chế độ Ảnh tĩnh dự phòng — ' +
              'đường đó báo được lỗi HTTP cụ thể. Bấm "Trực tiếp" nếu muốn thử lại luồng.'
            }
            tone="warn"
          />
        ) : null}

        {mode === 'still' ? (
          <Button
            label="Tải khung mới"
            onPress={onRetry}
            variant="quiet"
            busy={state.loading && !!state.data}
          />
        ) : null}
      </View>

      {/* 2. Cụm 3 Tín hiệu người học đặt ngay dưới khung Camera */}
      {baseUrl ? (
        signalsRows || signalsError?.status === 503 || (signalsLoading && !signalsError) ? (
          <LearnerSignalsSection
            rows={signalsRows}
            onOpenPeople={onOpenPeople}
            peopleDisabledMessage={
              signalsError?.status === 503
                ? (signalsError.message ||
                  'Máy chủ chưa bật dịch vụ nhận diện người học trong lần chạy này.')
                : null
            }
          />
        ) : signalsError && signalsError.status !== 404 && !statusError ? (
          <ErrorBanner
            title="Chưa đọc được tín hiệu người học"
            message={signalsError.message}
            onRetry={refreshSignals}
            retrying={signalsLoading}
          />
        ) : null
      ) : null}

      {/* 3. Integrated Posture Status Banner + 2x2 Bento Telemetry Grid */}
      {baseUrl ? (
        statusView ? (
          <PostureStatusSection
            view={statusView}
            updatedAt={statusUpdatedAt}
            mutedOverride={mutedOverride}
            muteBusy={muteBusy}
            onToggleMute={handleToggleMute}
          />
        ) : statusError ? (
          <ErrorBanner
            title="Chưa đọc được trạng thái tư thế"
            message={statusError.message}
            onRetry={refreshStatus}
            retrying={statusLoading}
          />
        ) : statusLoading ? (
          <LoadingCard label="Đang đồng bộ trạng thái tư thế từ Raspberry Pi…" />
        ) : null
      ) : null}

      <Text style={[typo.caption, { color: palette.textFaint }]}>
        Ảnh chỉ đi qua bộ nhớ của máy chủ và tới điện thoại trong LAN; dashboard không lưu ảnh.
      </Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  livePill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
  },
  liveDot: {
    width: 7,
    height: 7,
    borderRadius: 3.5,
  },
  livePillTag: {
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 0.6,
  },
  livePillSep: {
    fontSize: 11,
  },
  livePillClock: {
    fontFamily: monoFamily,
    fontSize: 11,
    fontVariant: ['tabular-nums'],
  },
  cameraCard: {
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: spacing.sm,
    gap: spacing.sm,
  },
  cameraToolbar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
    paddingHorizontal: 2,
  },
  segmentedTrack: {
    flexDirection: 'row',
    borderRadius: radius.sm,
    padding: 3,
    gap: 2,
  },
  segmentBtn: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
  },
  segmentText: {
    fontSize: 12,
    fontWeight: '600',
  },
  segmentTextActive: {
    fontWeight: '700',
  },
  browserLink: {
    paddingVertical: 4,
    paddingHorizontal: 4,
  },
  browserLinkText: {
    fontSize: 12,
    fontWeight: '600',
  },
  kbCaption: {
    fontFamily: monoFamily,
    fontSize: 11,
  },
  frameBox: {
    position: 'relative',
    aspectRatio: 4 / 3,
    borderRadius: radius.md,
    overflow: 'hidden',
    borderWidth: StyleSheet.hairlineWidth,
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
  hudOverlay: {
    position: 'absolute',
    top: 8,
    left: 8,
    right: 8,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  hudBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
    borderWidth: StyleSheet.hairlineWidth,
  },
  hudDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  hudBadgeText: {
    fontFamily: monoFamily,
    fontSize: 10,
    fontWeight: '600',
    fontVariant: ['tabular-nums'],
  },
});
