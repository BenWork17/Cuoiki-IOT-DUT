/**
 * Màn Người học — Chọn người đang học, Thêm người mới (quét khuôn mặt 5 bước kiểu Face ID)
 * và Xoá hồ sơ khuôn mặt.
 *
 * Các nguyên tắc vận hành đồng bộ với Web Dashboard (`src/posture_monitor/web/static/app.js`):
 * 1. **Chọn / Bỏ chọn người học** (`POST /api/select` với `{"person_id": id | null}`):
 *    cập nhật tức thì danh sách từ máy chủ để 3 Tín hiệu nhận diện đúng chủ nhân.
 * 2. **Thêm người mới** (`POST /api/people` → `201 {enroll_id, steps}`):
 *    mở khung quét trực tiếp có vòng tròn căn mặt + 5 bước hướng dẫn + đếm mẫu hợp lệ,
 *    hỏi `GET /api/enroll/<id>` mỗi 450 ms.
 * 3. **Quét lại mở phiên MỚI**: khi `state === 'failed'`, nút "Quét lại" gọi lại
 *    `POST /api/people` tạo `enroll_id` mới (không bao giờ poll lại phiên đã `failed`).
 * 4. **Đóng / rời màn khi đang quét phải huỷ phiên trên Pi**: gọi
 *    `POST /api/enroll/<id>/cancel` và ngắt ngay luồng `/stream` để giải phóng CPU cho Pi.
 * 5. **Không lưu sinh trắc học ở client**: app chỉ giữ danh sách tên trong RAM khi mở màn.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { WebView } from 'react-native-webview';

import { API_PATH, FRAME_TIMEOUT_MS, type FramePayload } from '../api/client';
import type { ApiError } from '../api/errors';
import {
  DEFAULT_ENROLL_STEPS,
  normalizeEnrollStart,
  normalizeEnrollStatus,
  normalizePeople,
  type EnrollStatusView,
  type PeopleView,
  type PersonEntry,
} from '../api/payload';
import { buildUrl } from '../api/url';
import {
  Button,
  Card,
  Chip,
  Divider,
  ErrorBanner,
  Label,
  LoadingCard,
  Notice,
  Screen,
  SuccessBanner,
  UnconfiguredNotice,
} from '../components/ui';
import { useApp, useTheme } from '../context/AppContext';
import { useAsyncAction } from '../hooks/useAsyncAction';
import { toPollFetcher, usePoll } from '../hooks/usePoll';
import { monoFamily, radius, spacing } from '../theme';

const ENROLL_POLL_MS = 450;
const SCAN_STILL_REFRESH_MS = 400;

type ScanSession = {
  name: string;
  enrollId: string | null;
  steps: string[];
  phase: 'starting' | 'running' | 'done' | 'failed';
  statusView: EnrollStatusView | null;
};

type LastPeopleAction =
  | { kind: 'select'; personId: string | null }
  | { kind: 'delete'; personId: string }
  | { kind: 'enroll'; name: string };

export function PeopleScreen({ focused }: { focused: boolean }): React.ReactElement {
  const { api, baseUrl, loading: configLoading } = useApp();
  const { palette, typo } = useTheme();
  const { run: runAction } = useAsyncAction();

  const [newName, setNewName] = useState('');
  const [selectingId, setSelectingId] = useState<string | '__clear__' | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [startingEnroll, setStartingEnroll] = useState(false);

  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [actionMessage, setActionMessage] = useState('');
  const [lastAction, setLastAction] = useState<LastPeopleAction | null>(null);

  const [scan, setScan] = useState<ScanSession | null>(null);
  const [scanLiveFailed, setScanLiveFailed] = useState(false);
  const [scanStillFrame, setScanStillFrame] = useState<FramePayload | null>(null);

  const mountedRef = useRef(true);
  const activeEnrollIdRef = useRef<string | null>(null);
  const enrollPollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const enrollPollAbortRef = useRef<AbortController | null>(null);

  const fetcher = useMemo(
    () => toPollFetcher((signal) => api.getPeople({ signal }), normalizePeople),
    [api],
  );

  const {
    data: view,
    error: pollError,
    loading,
    refresh,
  } = usePoll<PeopleView>(fetcher, {
    enabled: focused && !configLoading && !!baseUrl,
  });

  const peopleDisabled = pollError?.status === 503;

  const stopEnrollLoop = useCallback(() => {
    if (enrollPollTimerRef.current !== null) {
      clearTimeout(enrollPollTimerRef.current);
      enrollPollTimerRef.current = null;
    }
    enrollPollAbortRef.current?.abort();
    enrollPollAbortRef.current = null;
  }, []);

  const cancelRunningOnServer = useCallback(
    (enrollId: string | null) => {
      if (!enrollId) return;
      activeEnrollIdRef.current = null;
      void api.cancelEnroll(enrollId);
    },
    [api],
  );

  // Huỷ phiên quét đang chạy nếu người dùng chuyển sang tab khác hoặc rời màn hình.
  useEffect(() => {
    mountedRef.current = true;
    if (!focused && activeEnrollIdRef.current) {
      const runningId = activeEnrollIdRef.current;
      stopEnrollLoop();
      cancelRunningOnServer(runningId);
      setScan(null);
    }
    return () => {
      mountedRef.current = false;
      const runningId = activeEnrollIdRef.current;
      stopEnrollLoop();
      if (runningId) {
        activeEnrollIdRef.current = null;
        void api.cancelEnroll(runningId);
      }
    };
  }, [api, cancelRunningOnServer, focused, stopEnrollLoop]);

  // Ảnh tĩnh dự phòng cho khung quét khi WebView `/stream` không đọc được.
  const scanCameraActive =
    focused &&
    !!baseUrl &&
    scan !== null &&
    (scan.phase === 'starting' || scan.phase === 'running');

  useEffect(() => {
    if (!scanCameraActive || !scanLiveFailed) {
      setScanStillFrame(null);
      return;
    }
    let stopped = false;
    let busy = false;
    const ctrl = new AbortController();

    const pull = async () => {
      if (stopped || busy) return;
      busy = true;
      try {
        const res = await api.getFrame({
          signal: ctrl.signal,
          timeoutMs: FRAME_TIMEOUT_MS,
        });
        if (!stopped && res.ok) {
          setScanStillFrame(res.data);
        }
      } finally {
        busy = false;
      }
    };

    void pull();
    const timer = setInterval(() => void pull(), SCAN_STILL_REFRESH_MS);
    return () => {
      stopped = true;
      clearInterval(timer);
      ctrl.abort();
    };
  }, [api, scanCameraActive, scanLiveFailed]);

  const pollEnrollOnce = useCallback(
    async (enrollId: string, personName: string, steps: string[]) => {
      if (!mountedRef.current || activeEnrollIdRef.current !== enrollId) return;
      const controller = new AbortController();
      enrollPollAbortRef.current = controller;

      const res = await api.getEnrollStatus(enrollId, { signal: controller.signal });
      if (!mountedRef.current || activeEnrollIdRef.current !== enrollId) return;

      if (!res.ok) {
        if (res.error.kind === 'cancelled') return;
        activeEnrollIdRef.current = null;
        stopEnrollLoop();
        const failedView = normalizeEnrollStatus(
          { state: 'failed', error: res.error.message },
          steps,
          personName,
        );
        setScan({
          name: personName,
          enrollId: null,
          steps,
          phase: 'failed',
          statusView: failedView,
        });
        return;
      }

      const statusView = normalizeEnrollStatus(res.data, steps, personName);
      if (statusView.state === 'running') {
        setScan({
          name: personName,
          enrollId,
          steps,
          phase: 'running',
          statusView,
        });
        enrollPollTimerRef.current = setTimeout(() => {
          void pollEnrollOnce(enrollId, personName, steps);
        }, ENROLL_POLL_MS);
        return;
      }

      activeEnrollIdRef.current = null;
      stopEnrollLoop();

      if (statusView.state === 'done') {
        setScan({
          name: personName,
          enrollId: null,
          steps,
          phase: 'done',
          statusView,
        });
        setActionMessage(`Đã thêm người học "${personName}".`);
        refresh();
        return;
      }

      if (statusView.state === 'cancelled') {
        setScan(null);
        setActionMessage(statusView.hintText);
        return;
      }

      setScan({
        name: personName,
        enrollId: null,
        steps,
        phase: 'failed',
        statusView,
      });
    },
    [api, refresh, stopEnrollLoop],
  );

  const startEnrollment = useCallback(
    (rawName: string): Promise<void> =>
      runAction(async ({ signal, isActive }) => {
        const trimmed = rawName.trim();
        if (!trimmed) {
          setActionError({
            kind: 'config',
            status: null,
            message: 'Tên người học không được để trống.',
            retryable: false,
          });
          return;
        }

        // Nếu đang có phiên cũ, dọn sạch trước khi mở phiên mới.
        if (activeEnrollIdRef.current) {
          const prevId = activeEnrollIdRef.current;
          stopEnrollLoop();
          cancelRunningOnServer(prevId);
        }

        setStartingEnroll(true);
        setActionError(null);
        setActionMessage('');
        setLastAction({ kind: 'enroll', name: trimmed });
        setScanLiveFailed(false);
        setScan({
          name: trimmed,
          enrollId: null,
          steps: [...DEFAULT_ENROLL_STEPS],
          phase: 'starting',
          statusView: null,
        });

        const res = await api.startEnroll(trimmed, { signal });
        if (!isActive()) return;
        setStartingEnroll(false);

        if (!res.ok) {
          setScan(null);
          if (res.error.kind === 'cancelled') return;
          setActionError(res.error);
          return;
        }

        const started = normalizeEnrollStart(res.data);
        if (!started.enrollId) {
          setScan(null);
          setActionError({
            kind: 'bad-payload',
            status: res.status,
            message: 'Máy chủ không trả về mã phiên đăng ký khuôn mặt.',
            retryable: true,
          });
          return;
        }

        setLastAction(null);
        setNewName('');
        activeEnrollIdRef.current = started.enrollId;
        setScan({
          name: started.name ?? trimmed,
          enrollId: started.enrollId,
          steps: started.steps,
          phase: 'running',
          statusView: normalizeEnrollStatus(
            { state: 'running', step_index: 0, samples: 0, samples_needed: 3 },
            started.steps,
            started.name ?? trimmed,
          ),
        });
        void pollEnrollOnce(
          started.enrollId,
          started.name ?? trimmed,
          started.steps,
        );
      }),
    [api, cancelRunningOnServer, pollEnrollOnce, runAction, stopEnrollLoop],
  );

  const handleCancelScan = useCallback(async () => {
    const runningId = activeEnrollIdRef.current;
    stopEnrollLoop();
    activeEnrollIdRef.current = null;
    setScan(null);
    if (!runningId) return;
    const res = await api.cancelEnroll(runningId);
    if (!mountedRef.current) return;
    if (res.ok) {
      setActionMessage(res.data.message || 'Đã huỷ phiên đăng ký.');
    }
  }, [api, stopEnrollLoop]);

  const handleCloseScan = useCallback(() => {
    if (activeEnrollIdRef.current) {
      void handleCancelScan();
      return;
    }
    stopEnrollLoop();
    setScan(null);
  }, [handleCancelScan, stopEnrollLoop]);

  const handleSelectPerson = useCallback(
    (personId: string | null): Promise<void> =>
      runAction(async ({ signal, isActive }) => {
        setSelectingId(personId === null ? '__clear__' : personId);
        setConfirmDeleteId(null);
        setActionError(null);
        setActionMessage('');
        setLastAction({ kind: 'select', personId });

        const res = await api.selectPerson(personId, { signal });
        if (!isActive()) return;
        setSelectingId(null);

        if (res.ok) {
          setLastAction(null);
          setActionMessage(
            res.data.message ||
              (personId === null
                ? 'Đã bỏ chọn người đang học.'
                : 'Đã chọn người đang học.'),
          );
          refresh();
          return;
        }
        if (res.error.kind === 'cancelled') return;
        setActionError(res.error);
      }),
    [api, refresh, runAction],
  );

  const handleDeletePerson = useCallback(
    (personId: string): Promise<void> =>
      runAction(async ({ signal, isActive }) => {
        setDeletingId(personId);
        setActionError(null);
        setActionMessage('');
        setLastAction({ kind: 'delete', personId });

        const res = await api.deletePerson(personId, { signal });
        if (!isActive()) return;
        setDeletingId(null);
        setConfirmDeleteId(null);

        if (res.ok) {
          setLastAction(null);
          setActionMessage(res.data.message || 'Đã xoá người học.');
          refresh();
          return;
        }
        if (res.error.kind === 'cancelled') return;
        setActionError(res.error);
      }),
    [api, refresh, runAction],
  );

  const retryLastAction = useCallback(() => {
    if (!lastAction) {
      refresh();
      return;
    }
    if (lastAction.kind === 'select') {
      void handleSelectPerson(lastAction.personId);
    } else if (lastAction.kind === 'delete') {
      void handleDeletePerson(lastAction.personId);
    } else {
      void startEnrollment(lastAction.name);
    }
  }, [handleDeletePerson, handleSelectPerson, lastAction, refresh, startEnrollment]);

  const streamUrl = baseUrl ? `${buildUrl(baseUrl, API_PATH.stream)}?scan=1` : '';
  const anyBusy =
    selectingId !== null || deletingId !== null || startingEnroll || scan?.phase === 'running';

  return (
    <Screen
      title="Người học"
      subtitle="Chọn người đang ngồi học hoặc quét khuôn mặt thêm người mới"
    >
      {!baseUrl ? <UnconfiguredNotice /> : null}

      {peopleDisabled ? (
        <Notice
          title="Nhận diện người học chưa bật"
          body={
            pollError?.message ??
            'Tính năng người học chưa được bật trong phiên chạy này trên máy chủ.'
          }
          tone="warn"
        />
      ) : null}

      {pollError && !peopleDisabled ? (
        <ErrorBanner
          message={pollError.message}
          onRetry={refresh}
          retrying={loading}
        />
      ) : null}

      {actionError ? (
        <ErrorBanner
          title="Không thực hiện được thao tác"
          message={actionError.message}
          retryLabel="Gửi lại"
          onRetry={retryLastAction}
          retrying={anyBusy}
        />
      ) : null}

      {actionMessage ? <SuccessBanner message={actionMessage} /> : null}

      {/* Khung quét khuôn mặt 5 bước kiểu Face ID (chỉ xuất hiện khi đang thêm người) */}
      {scan ? (
        <Card
          style={[
            styles.scanCard,
            {
              borderColor:
                scan.phase === 'done'
                  ? palette.goodBorder
                  : scan.phase === 'failed'
                    ? palette.badBorder
                    : palette.accentBorder,
            },
          ]}
        >
          <View style={styles.scanHeader}>
            <View style={styles.scanHeaderTitleCol}>
              <Label>Quét khuôn mặt 5 bước</Label>
              <Text style={typo.heading}>{scan.name}</Text>
            </View>
            <Chip
              text={
                scan.phase === 'done'
                  ? 'Đã quét xong'
                  : scan.phase === 'failed'
                    ? 'Quét không đạt'
                    : scan.phase === 'starting'
                      ? 'Đang chuẩn bị'
                      : 'Đang quét'
              }
              tone={
                scan.phase === 'done'
                  ? 'good'
                  : scan.phase === 'failed'
                    ? 'bad'
                    : 'warn'
              }
            />
          </View>

          {scanCameraActive ? (
            <View
              style={[
                styles.scanViewport,
                { backgroundColor: palette.surfaceLowest, borderColor: palette.border },
              ]}
            >
              {!scanLiveFailed ? (
                <WebView
                  source={{ uri: streamUrl }}
                  style={styles.scanCamera}
                  originWhitelist={['*']}
                  scalesPageToFit={false}
                  javaScriptEnabled={false}
                  mixedContentMode="always"
                  domStorageEnabled={false}
                  accessibilityLabel="Khung camera quét khuôn mặt"
                  onError={() => setScanLiveFailed(true)}
                  onHttpError={() => setScanLiveFailed(true)}
                />
              ) : scanStillFrame ? (
                <Image
                  source={{ uri: scanStillFrame.uri }}
                  style={styles.scanCamera}
                  resizeMode="contain"
                  accessibilityLabel="Ảnh tĩnh quét khuôn mặt"
                />
              ) : (
                <View style={styles.scanCameraPlaceholder}>
                  <ActivityIndicator color={palette.accent} />
                  <Text style={[typo.caption, { color: palette.hudText, opacity: 0.8 }]}>
                    Đang kết nối camera…
                  </Text>
                </View>
              )}

              {/* Vòng tròn căn khuôn mặt kiểu Face ID */}
              <View pointerEvents="none" style={styles.faceGuideWrap}>
                <View
                  style={[
                    styles.faceGuideRing,
                    {
                      borderColor:
                        (scan.statusView?.samples ?? 0) > 0 ? '#34D399' : '#60A5FA',
                    },
                  ]}
                />
              </View>
            </View>
          ) : (
            <View
              style={[
                styles.scanResultBanner,
                {
                  backgroundColor:
                    scan.phase === 'done' ? palette.goodWash : palette.badWash,
                  borderColor:
                    scan.phase === 'done' ? palette.goodBorder : palette.badBorder,
                },
              ]}
            >
              <Text
                style={[
                  styles.scanResultIcon,
                  { color: scan.phase === 'done' ? palette.good : palette.bad },
                ]}
              >
                {scan.phase === 'done' ? '✓' : '!'}
              </Text>
              <View style={styles.scanResultTextCol}>
                <Text
                  style={[
                    typo.heading,
                    { color: scan.phase === 'done' ? palette.good : palette.bad },
                  ]}
                >
                  {scan.statusView?.headlineText ??
                    (scan.phase === 'done' ? 'Đã đăng ký' : 'Chưa đạt')}
                </Text>
                <Text style={[typo.body, { color: palette.text }]}>
                  {scan.statusView?.samplesText ?? ''}
                </Text>
              </View>
            </View>
          )}

          {/* Bước hiện tại & thanh tiến độ mẫu */}
          {scan.phase === 'running' || scan.phase === 'starting' ? (
            <View style={styles.scanInstructionBlock}>
              <Text style={[typo.title, { color: palette.accent }]}>
                {scan.statusView?.headlineText ?? 'Đang chuẩn bị camera…'}
              </Text>
              <Text style={[styles.samplesMono, { color: palette.textMuted }]}>
                {scan.statusView?.samplesText ?? 'Mẫu hợp lệ: 0 / 3'}
              </Text>
            </View>
          ) : null}

          <View style={[styles.progressTrack, { backgroundColor: palette.surfaceRaised }]}>
            <View
              style={[
                styles.progressFill,
                {
                  width: `${Math.round((scan.statusView?.progressRatio ?? 0) * 100)}%`,
                  backgroundColor:
                    scan.phase === 'done'
                      ? palette.good
                      : scan.phase === 'failed'
                        ? palette.bad
                        : palette.accent,
                },
              ]}
            />
          </View>

          {/* Năm chấm tiến độ tương ứng 5 góc mặt */}
          <View style={styles.stepsList}>
            {(scan.statusView?.steps ??
              scan.steps.map((label, index) => ({
                index,
                label,
                done: false,
                current: index === 0 && scan.phase === 'running',
              }))
            ).map((step) => (
              <View
                key={`${step.index}-${step.label}`}
                style={[
                  styles.stepChip,
                  {
                    backgroundColor: step.done
                      ? palette.goodWash
                      : step.current
                        ? palette.accentWash
                        : palette.surfaceRaised,
                    borderColor: step.done
                      ? palette.goodBorder
                      : step.current
                        ? palette.accentBorder
                        : palette.border,
                  },
                ]}
              >
                <Text
                  style={[
                    styles.stepChipText,
                    {
                      color: step.done
                        ? palette.good
                        : step.current
                          ? palette.accent
                          : palette.textFaint,
                      fontWeight: step.current || step.done ? '700' : '500',
                    },
                  ]}
                >
                  {step.done ? '✓ ' : step.current ? '● ' : `${step.index + 1}. `}
                  {step.label}
                </Text>
              </View>
            ))}
          </View>

          <Text style={[typo.caption, { color: palette.textMuted }]}>
            {scan.statusView?.hintText ??
              'Giữ mặt trong vòng tròn, nhìn thẳng vào camera và đủ sáng.'}
          </Text>

          <View style={styles.scanActions}>
            {scan.phase === 'running' || scan.phase === 'starting' ? (
              <Button
                label="Huỷ quét"
                onPress={() => void handleCancelScan()}
                variant="quiet"
                style={styles.scanActionBtn}
              />
            ) : null}

            {scan.phase === 'done' ? (
              <>
                <Button
                  label="Chọn làm người đang học"
                  accessibilityLabel={`Chọn ${scan.name} làm người đang học`}
                  onPress={() => {
                    const targetName = scan.name;
                    setScan(null);
                    void handleSelectPerson(targetName);
                  }}
                  variant="primary"
                  style={styles.scanActionBtn}
                />
                <Button
                  label="Đóng"
                  onPress={handleCloseScan}
                  variant="quiet"
                />
              </>
            ) : null}

            {scan.phase === 'failed' ? (
              <>
                <Button
                  label="Quét lại"
                  onPress={() => void startEnrollment(scan.name)}
                  variant="primary"
                  busy={startingEnroll}
                  style={styles.scanActionBtn}
                />
                <Button
                  label="Đóng"
                  onPress={handleCloseScan}
                  variant="quiet"
                />
              </>
            ) : null}
          </View>
        </Card>
      ) : null}

      {loading && !view && !peopleDisabled ? <LoadingCard /> : null}

      {/* 1. Người đang học hiện tại */}
      {baseUrl && !peopleDisabled ? (
        <Card>
          <View style={styles.currentHead}>
            <Label>Người đang học hiện tại</Label>
            {view?.selectedId ? (
              <Chip text="Đang theo dõi danh tính" tone="good" />
            ) : (
              <Chip text="Chưa chọn" tone="idle" />
            )}
          </View>

          <View style={styles.currentRow}>
            <View
              style={[
                styles.avatarCircleLarge,
                {
                  backgroundColor: view?.selectedPerson
                    ? palette.goodWash
                    : palette.surfaceRaised,
                  borderColor: view?.selectedPerson
                    ? palette.goodBorder
                    : palette.border,
                },
              ]}
            >
              <Text
                style={[
                  styles.avatarLargeText,
                  {
                    color: view?.selectedPerson ? palette.good : palette.textMuted,
                  },
                ]}
              >
                {view?.selectedPerson ? view.selectedPerson.initial : '•'}
              </Text>
            </View>
            <View style={styles.currentInfoCol}>
              <Text
                style={[
                  typo.heading,
                  {
                    color: view?.selectedPerson
                      ? palette.good
                      : view?.selectedId
                        ? palette.warn
                        : palette.text,
                  },
                ]}
              >
                {view ? view.selectedText : 'Đang tải…'}
              </Text>
              <Text style={[typo.caption, { color: palette.textMuted }]}>
                {view?.selectedId
                  ? 'Nếu người lạ ngồi thay quá 5 giây trong phiên học, loa sẽ phát nhắc nhở.'
                  : 'Chọn một người bên dưới để hệ thống kiểm tra đúng người đang ngồi học.'}
              </Text>
            </View>
          </View>

          {view?.selectedId ? (
            <Button
              label="Bỏ chọn người đang học"
              onPress={() => void handleSelectPerson(null)}
              variant="quiet"
              busy={selectingId === '__clear__'}
              disabled={selectingId !== null && selectingId !== '__clear__'}
            />
          ) : null}
        </Card>
      ) : null}

      {/* 2. Thêm người mới */}
      {baseUrl && !peopleDisabled ? (
        <Card>
          <Label>Thêm người mới</Label>
          <Text style={[typo.caption, { color: palette.textMuted }]}>
            Ngồi trước camera của Raspberry Pi ở nơi đủ sáng, nhập tên rồi bấm quét khuôn
            mặt 5 bước (khoảng 7,5 giây).
          </Text>
          <TextInput
            value={newName}
            onChangeText={(val) => {
              setNewName(val);
              if (actionError?.kind === 'config') setActionError(null);
            }}
            placeholder="Nhập tên người học (ví dụ: Minh)"
            placeholderTextColor={palette.textFaint}
            autoCapitalize="words"
            autoCorrect={false}
            returnKeyType="done"
            editable={!startingEnroll && scan?.phase !== 'running'}
            onSubmitEditing={() => void startEnrollment(newName)}
            accessibilityLabel="Tên người học mới"
            style={[
              styles.input,
              {
                backgroundColor: palette.background,
                borderColor: palette.borderStrong,
                color: palette.text,
              },
            ]}
          />
          <Button
            label="Thêm & Quét khuôn mặt"
            onPress={() => void startEnrollment(newName)}
            variant="primary"
            busy={startingEnroll}
            disabled={scan?.phase === 'running' || !newName.trim()}
          />
        </Card>
      ) : null}

      {/* 3. Danh sách người học đã đăng ký */}
      {baseUrl && !peopleDisabled && view ? (
        <>
          <Divider />
          <Card>
            <View style={styles.listHeaderRow}>
              <View style={styles.listHeaderLeft}>
                <Label>Danh sách đã đăng ký</Label>
                <Chip text={`${view.people.length} người`} tone="idle" />
              </View>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Làm mới danh sách người học"
                onPress={refresh}
                style={({ pressed }) => [
                  styles.refreshLink,
                  pressed ? { opacity: 0.7 } : null,
                ]}
              >
                <Text style={[styles.refreshLinkText, { color: palette.accent }]}>
                  Làm mới
                </Text>
              </Pressable>
            </View>

            {view.people.length === 0 ? (
              <Text style={[typo.body, { color: palette.textMuted }]}>
                Chưa có người học nào được đăng ký. Nhập tên ở mục “Thêm người mới” phía trên
                để quét khuôn mặt lần đầu.
              </Text>
            ) : (
              view.people.map((person, index) => (
                <PersonRow
                  key={person.id}
                  person={person}
                  isSelected={person.id === view.selectedId}
                  isFirst={index === 0}
                  selectingId={selectingId}
                  confirmingDelete={confirmDeleteId === person.id}
                  deleting={deletingId === person.id}
                  disableActions={anyBusy}
                  onSelect={() => void handleSelectPerson(person.id)}
                  onRequestDelete={() => setConfirmDeleteId(person.id)}
                  onCancelDelete={() => setConfirmDeleteId(null)}
                  onConfirmDelete={() => void handleDeletePerson(person.id)}
                />
              ))
            )}
          </Card>
        </>
      ) : null}

      <Text style={[typo.caption, { color: palette.textFaint }]}>
        Quyền riêng tư: máy chủ chỉ lưu vector đặc trưng khuôn mặt trong kho nội bộ của Pi,
        không lưu ảnh mặt và không truyền vector sinh trắc học ra mạng.
      </Text>
    </Screen>
  );
}

function PersonRow({
  person,
  isSelected,
  isFirst,
  selectingId,
  confirmingDelete,
  deleting,
  disableActions,
  onSelect,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
}: {
  person: PersonEntry;
  isSelected: boolean;
  isFirst: boolean;
  selectingId: string | '__clear__' | null;
  confirmingDelete: boolean;
  deleting: boolean;
  disableActions: boolean;
  onSelect: () => void;
  onRequestDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}): React.ReactElement {
  const { palette, typo } = useTheme();
  const isSelectingThis = selectingId === person.id;

  return (
    <View
      style={[
        styles.personBlock,
        !isFirst
          ? { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: palette.border }
          : null,
      ]}
    >
      <View style={styles.personMainRow}>
        <View
          style={[
            styles.avatarCircle,
            {
              backgroundColor: isSelected ? palette.goodWash : palette.surfaceRaised,
              borderColor: isSelected ? palette.goodBorder : palette.border,
            },
          ]}
        >
          <Text
            style={[
              styles.avatarText,
              { color: isSelected ? palette.good : palette.text },
            ]}
          >
            {person.initial}
          </Text>
        </View>

        <View style={styles.personNameCol}>
          <View style={styles.personTitleRow}>
            <Text style={typo.heading} numberOfLines={1}>
              {person.name}
            </Text>
            {isSelected ? <Chip text="Đang học" tone="good" /> : null}
          </View>
          {person.id !== person.name ? (
            <Text style={[typo.caption, { color: palette.textFaint }]}>
              Mã: {person.id}
            </Text>
          ) : null}
        </View>

        {!confirmingDelete ? (
          <View style={styles.personBtnGroup}>
            <Button
              label={isSelected ? 'Đang học' : 'Chọn'}
              accessibilityLabel={
                isSelected ? `${person.name} đang được chọn` : `Chọn ${person.name}`
              }
              onPress={onSelect}
              variant={isSelected ? 'quiet' : 'secondary'}
              busy={isSelectingThis}
              disabled={isSelected || (disableActions && !isSelectingThis)}
              style={styles.compactBtn}
            />
            <Button
              label="Xoá"
              accessibilityLabel={`Xoá ${person.name}`}
              onPress={onRequestDelete}
              variant="quiet"
              disabled={disableActions}
              style={styles.deleteTriggerBtn}
            />
          </View>
        ) : null}
      </View>

      {confirmingDelete ? (
        <View
          style={[
            styles.confirmRow,
            { backgroundColor: palette.badWash, borderColor: palette.badBorder },
          ]}
        >
          <Text style={[typo.caption, { color: palette.text, flex: 1 }]}>
            Xoá hồ sơ khuôn mặt của “{person.name}”? Thao tác này không hoàn tác được.
          </Text>
          <View style={styles.confirmBtns}>
            <Button
              label="Xác nhận xoá"
              accessibilityLabel={`Xác nhận xoá ${person.name}`}
              onPress={onConfirmDelete}
              variant="danger"
              busy={deleting}
              style={styles.compactBtn}
            />
            <Button
              label="Huỷ xoá"
              accessibilityLabel={`Huỷ xoá ${person.name}`}
              onPress={onCancelDelete}
              variant="quiet"
              disabled={deleting}
              style={styles.compactBtn}
            />
          </View>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  scanCard: {
    gap: spacing.md,
  },
  scanHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  scanHeaderTitleCol: {
    flex: 1,
    gap: 2,
  },
  scanViewport: {
    position: 'relative',
    aspectRatio: 4 / 3,
    borderRadius: radius.md,
    overflow: 'hidden',
    borderWidth: StyleSheet.hairlineWidth,
  },
  scanCamera: {
    width: '100%',
    height: '100%',
  },
  scanCameraPlaceholder: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
  },
  faceGuideWrap: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    alignItems: 'center',
    justifyContent: 'center',
  },
  faceGuideRing: {
    width: 168,
    height: 168,
    borderRadius: 84,
    borderWidth: 3,
    borderStyle: 'dashed',
  },
  scanResultBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
  },
  scanResultIcon: {
    fontSize: 24,
    fontWeight: '800',
  },
  scanResultTextCol: {
    flex: 1,
    gap: 2,
  },
  scanInstructionBlock: {
    gap: 2,
  },
  samplesMono: {
    fontFamily: monoFamily,
    fontSize: 13,
    fontWeight: '600',
    fontVariant: ['tabular-nums'],
  },
  progressTrack: {
    height: 6,
    borderRadius: radius.pill,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    borderRadius: radius.pill,
  },
  stepsList: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
  },
  stepChip: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
  },
  stepChipText: {
    fontSize: 11,
  },
  scanActions: {
    flexDirection: 'row',
    gap: spacing.sm,
    flexWrap: 'wrap',
  },
  scanActionBtn: {
    flex: 1,
  },
  currentHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  currentRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  avatarCircleLarge: {
    width: 48,
    height: 48,
    borderRadius: 24,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  avatarLargeText: {
    fontSize: 18,
    fontWeight: '800',
  },
  currentInfoCol: {
    flex: 1,
    gap: 2,
  },
  input: {
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    fontSize: 16,
  },
  listHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  listHeaderLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  refreshLink: {
    paddingVertical: 4,
    paddingHorizontal: 6,
  },
  refreshLinkText: {
    fontSize: 13,
    fontWeight: '700',
  },
  personBlock: {
    paddingTop: spacing.sm,
    gap: spacing.sm,
  },
  personMainRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  avatarCircle: {
    width: 38,
    height: 38,
    borderRadius: 19,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  avatarText: {
    fontSize: 15,
    fontWeight: '800',
  },
  personNameCol: {
    flex: 1,
    gap: 2,
  },
  personTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    flexWrap: 'wrap',
  },
  personBtnGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    flexShrink: 0,
  },
  compactBtn: {
    minHeight: 40,
    paddingHorizontal: spacing.md,
  },
  deleteTriggerBtn: {
    minHeight: 40,
    paddingHorizontal: spacing.sm,
  },
  confirmRow: {
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    padding: spacing.md,
    gap: spacing.sm,
  },
  confirmBtns: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
});
