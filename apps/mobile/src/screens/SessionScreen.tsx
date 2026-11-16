/**
 * Màn 3 — Phiên học.
 *
 * Route: `GET /api/session`, `POST /api/session/start`, `POST /api/session/stop`
 * (`app.py:483-533`).
 *
 * **Không có `POST /api/session`** — tài liệu yêu cầu §4.1 đã đo: gọi vào đó
 * nhận **405** kèm thân HTML. Dùng đúng ba route trên.
 *
 * Ca bắt buộc phải chịu được: máy chủ **chưa bật** phiên (503, câu
 * "Phiên học chưa được bật trong lần chạy này…"). Đây không phải lỗi mạng và
 * không phải lỗi tạm thời: app phải hiện đúng câu của server, **vô hiệu nút**
 * và không crash. Vì vậy nút bấm bị khoá khi `sessionEnabled === false`, chứ
 * không phải để người dùng bấm rồi nhận lỗi mãi.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, TextInput, View } from 'react-native';

import { normalizeSession, type SessionView } from '../api/payload';
import type { ApiError } from '../api/errors';
import { Button, Card, Chip, Divider, ErrorBanner, Label, Notice, Screen } from '../components/ui';
import { useApp } from '../context/AppContext';
import { usePoll, type PollResult } from '../hooks/usePoll';
import { colors, radius, spacing, type as typo } from '../theme';

/**
 * `focused` do thanh tab truyền vào: màn chỉ hỏi máy chủ khi đang được hiện.
 *
 * Không có hằng câu "Phiên học chưa bật" ở đây: câu đó thuộc về **server**
 * (`app.py` `_session_unavailable`), và app chỉ hiện lại `message` server gửi.
 * Viết lại câu ấy trong app là tạo nguồn sự thật thứ hai — sửa một bên thì
 * bên kia lệch, mà người đọc không biết bên nào đúng. `SignalsScreen` đã làm
 * đúng mẫu này; đây là chỗ cuối cùng còn lặp.
 */
export function SessionScreen({ focused }: { focused: boolean }): React.ReactElement {
  const { api, baseUrl, loading: configLoading } = useApp();

  const [minutesText, setMinutesText] = useState<string>('');
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [actionMessage, setActionMessage] = useState<string>('');
  const [busy, setBusy] = useState<'start' | 'stop' | null>(null);
  /** `true` khi server đã trả 503 — khoá nút và hiện câu giải thích. */
  const [sessionEnabled, setSessionEnabled] = useState<boolean | null>(null);

  /** Đã unmount chưa — mọi setState sau `await` phải kiểm cờ này. */
  const mounted = useRef(true);
  /** Request lệnh đang chạy, để huỷ khi rời màn. */
  const actionController = useRef<AbortController | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      actionController.current?.abort();
      actionController.current = null;
    };
  }, []);

  const fetcher = useCallback(
    async (signal: AbortSignal): Promise<PollResult<SessionView>> => {
      const result = await api.getSession({ signal });
      if (result.ok) {
        // Đọc được phiên nghĩa là server **có** bật phiên. Phải ghi lại điều
        // đó, nếu không một lần 503 (ví dụ máy chủ đang khởi động lại) sẽ khoá
        // nút vĩnh viễn cho tới khi đóng app — người dùng sẽ tưởng app hỏng.
        setSessionEnabled(true);
        return { ok: true, data: normalizeSession(result.data), ignored: false };
      }
      if (result.error.kind === 'cancelled') {
        return { ok: false, error: result.error, ignored: true };
      }
      if (result.status === 503) setSessionEnabled(false);
      return { ok: false, error: result.error, ignored: false };
    },
    [api],
  );

  const { data, error, loading, refresh } = usePoll(fetcher, { enabled: focused && !configLoading && !!baseUrl });

  // 503 ⇒ phiên chưa bật. Suy ra từ lỗi của vòng làm mới, để màn hình không
  // phải gọi thêm một request nữa chỉ để biết điều đã biết.
  const pollDisabled = error?.status === 503;
  const enabled = pollDisabled ? false : sessionEnabled ?? true;

  const sendStart = useCallback(async (): Promise<void> => {
    actionController.current?.abort();
    const controller = new AbortController();
    actionController.current = controller;
    setBusy('start');
    setActionError(null);
    setActionMessage('');
    // Chưa nhập gì ⇒ gửi thân rỗng để server dùng thời lượng mặc định
    // (`app.py:509-512`), thay vì app tự đoán một con số.
    const parsed = minutesText.trim() ? Number(minutesText.trim()) : null;
    if (parsed !== null && (!Number.isFinite(parsed) || !Number.isInteger(parsed))) {
      setBusy(null);
      setActionError({
        kind: 'config',
        status: null,
        message: 'Số phút phải là số nguyên. Ví dụ: 45.',
        retryable: false,
      });
      return;
    }
    const result = await api.startSession(parsed, { signal: controller.signal });
    if (!mounted.current || controller.signal.aborted) return;
    setBusy(null);
    if (result.ok) {
      setSessionEnabled(true);
      setActionMessage(
        typeof result.data?.message === 'string'
          ? result.data.message
          : 'Đã bắt đầu phiên học.',
      );
      refresh();
      return;
    }
    if (result.error.kind === 'cancelled') return;
    if (result.status === 503) setSessionEnabled(false);
    // 400 (số phút ngoài 1–720) hiện **đúng** câu server gửi, không tự đoán.
    setActionError(result.error);
  }, [api, minutesText, refresh]);

  const sendStop = useCallback(async (): Promise<void> => {
    actionController.current?.abort();
    const controller = new AbortController();
    actionController.current = controller;
    setBusy('stop');
    setActionError(null);
    setActionMessage('');
    const result = await api.stopSession({ signal: controller.signal });
    if (!mounted.current || controller.signal.aborted) return;
    setBusy(null);
    if (result.ok) {
      setActionMessage(
        typeof result.data?.message === 'string' ? result.data.message : 'Đã dừng phiên học.',
      );
      refresh();
      return;
    }
    if (result.error.kind === 'cancelled') return;
    if (result.status === 503) setSessionEnabled(false);
    setActionError(result.error);
  }, [api, refresh]);

  const running = data?.running === true;
  const disabled = !enabled || pollDisabled;

  return (
    <Screen title="Phiên học" subtitle="Bật/tắt việc phân tích tư thế trên Pi">
      {!baseUrl ? (
        <Notice
          title="Chưa cấu hình máy chủ"
          body="Mở tab Kết nối, nhập IP LAN của máy chạy dashboard rồi lưu lại."
          tone="warn"
        />
      ) : null}

      {pollDisabled ? (
        <Notice
          title="Phiên học chưa bật"
          body={
            error?.message ??
            'Máy chủ báo phiên học chưa được bật trong lần chạy này.'
          }
          tone="warn"
        />
      ) : null}

      {error && !pollDisabled ? (
        <ErrorBanner message={error.message} onRetry={refresh} retrying={loading} />
      ) : null}

      {actionError ? (
        <ErrorBanner
          title="Không gửi được lệnh"
          message={actionError.message}
          retryLabel="Gửi lại"
          onRetry={running ? () => void sendStop() : () => void sendStart()}
          retrying={busy !== null}
        />
      ) : null}

      {actionMessage ? (
        <View style={styles.success}>
          <Text style={[typo.body, { color: colors.good }]}>{actionMessage}</Text>
        </View>
      ) : null}

      <Card>
        <View style={styles.headRow}>
          <Label>Trạng thái phiên</Label>
          {running ? <Chip text="Đang học" tone="good" /> : null}
        </View>

        <Text style={[typo.display, { color: data?.running ? colors.good : colors.text }]}>
          {data?.countdownText ?? '–'}
        </Text>
        <Text style={[typo.caption, styles.muted]}>
          {data?.countdownLabel ? data.countdownLabel : 'chưa chạy'}
        </Text>

        <Divider />

        {loading && !data ? (
          <View style={styles.loadingRow}>
            <ActivityIndicator color={colors.accent} />
            <Text style={[typo.caption, styles.muted]}>Đang hỏi máy chủ…</Text>
          </View>
        ) : (
          <Text style={[typo.body, styles.stateText]}>
            {data?.stateText ?? 'Chưa đọc được trạng thái phiên.'}
          </Text>
        )}

        {data?.finishText ? (
          <Text style={[typo.caption, { color: colors.warn }]}>{data.finishText}</Text>
        ) : null}
      </Card>

      <Card>
        <Label>Số phút</Label>
        <TextInput
          value={minutesText}
          onChangeText={setMinutesText}
          editable={!running && !disabled}
          placeholder={
            data?.defaultMinutes ? String(data.defaultMinutes) : 'ví dụ 45'
          }
          placeholderTextColor={colors.textFaint}
          keyboardType="number-pad"
          returnKeyType="done"
          style={[styles.input, (running || disabled) && styles.inputDisabled]}
          accessibilityLabel="Số phút của phiên học"
        />
        <Text style={[typo.caption, styles.muted]}>
          {data?.minMinutes != null && data.maxMinutes != null
            ? `Từ ${data.minMinutes} đến ${data.maxMinutes} phút. Để trống dùng mặc định của máy chủ.`
            : 'Để trống dùng thời lượng mặc định của máy chủ (1–720 phút).'}
        </Text>

        <View style={styles.actions}>
          <Button
            label={running ? 'Bắt đầu lại' : 'Bắt đầu học'}
            onPress={() => void sendStart()}
            variant={running ? 'quiet' : 'primary'}
            disabled={disabled}
            busy={busy === 'start'}
            style={styles.actionButton}
          />
          <Button
            label="Dừng học"
            onPress={() => void sendStop()}
            variant={running ? 'danger' : 'quiet'}
            disabled={!running || disabled}
            busy={busy === 'stop'}
            style={styles.actionButton}
          />
        </View>

        {running ? (
          <Text style={[typo.caption, styles.muted]}>
            Đang chạy thì ô số phút bị khoá — máy chủ đã chốt giờ kết thúc. Muốn đổi, bấm
            “Bắt đầu lại”.
          </Text>
        ) : null}
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({
  headRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  stateText: {
    color: colors.text,
  },
  actions: {
    flexDirection: 'row',
    gap: spacing.md,
  },
  actionButton: {
    flex: 1,
  },
  input: {
    backgroundColor: colors.background,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.borderStrong,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    color: colors.text,
    fontSize: 18,
  },
  inputDisabled: {
    color: colors.textMuted,
    borderColor: colors.border,
  },
  success: {
    backgroundColor: 'rgba(95,224,176,0.10)',
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(95,224,176,0.35)',
    padding: spacing.lg,
  },
  loadingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  muted: {
    color: colors.textMuted,
  },
});


