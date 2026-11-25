/**
 * Màn Kết nối & Giao diện (địa chỉ máy chủ LAN + chọn chế độ Sáng / Tối).
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { createApiClient } from '../api/client';
import { normalizeStatus, type StatusView } from '../api/payload';
import { displayHost, normalizeBaseUrl } from '../api/url';
import {
  Button,
  Card,
  Divider,
  Label,
  LoadingCard,
  Notice,
  Screen,
} from '../components/ui';
import { useApp, useTheme } from '../context/AppContext';
import { useAsyncAction } from '../hooks/useAsyncAction';
import type { ThemeMode } from '../storage/theme';
import { monoFamily, radius, spacing } from '../theme';

type CheckResult =
  | { kind: 'idle' }
  | { kind: 'running' }
  | { kind: 'ok'; view: StatusView }
  | { kind: 'error'; message: string };

export function SettingsScreen(): React.ReactElement {
  const { baseUrl, setBaseUrl, clear, loading } = useApp();
  const { mode: themeMode, setThemeMode, palette, typo } = useTheme();
  const { run: runCheck, isMounted, abort: abortCheck } = useAsyncAction();
  const [text, setText] = useState(baseUrl);
  const [result, setResult] = useState<CheckResult>({ kind: 'idle' });
  const [saveNote, setSaveNote] = useState('');

  useEffect(() => {
    setText(baseUrl);
  }, [baseUrl]);

  const warnings = (() => {
    const parsed = normalizeBaseUrl(text);
    return parsed.ok ? parsed.warnings : [];
  })();

  const save = useCallback(async (): Promise<void> => {
    setSaveNote('');
    const parsed = normalizeBaseUrl(text);
    if (!parsed.ok) {
      setResult({ kind: 'error', message: parsed.message });
      return;
    }
    abortCheck();
    const written = await setBaseUrl(parsed.baseUrl);
    if (!isMounted()) return;
    if (!written) {
      setResult({
        kind: 'error',
        message:
          'Không ghi được địa chỉ vào bộ nhớ máy. Địa chỉ sẽ mất khi đóng app — hãy thử lại.',
      });
      return;
    }
    setText(parsed.baseUrl);
    setSaveNote(`Đã lưu ${displayHost(parsed.baseUrl)}.`);
    setResult({ kind: 'idle' });
  }, [abortCheck, isMounted, setBaseUrl, text]);

  const check = useCallback(async (): Promise<void> => {
    const parsed = normalizeBaseUrl(text);
    if (!parsed.ok) {
      setResult({ kind: 'error', message: parsed.message });
      return;
    }
    await runCheck(async ({ signal, isActive }) => {
      setResult({ kind: 'running' });
      const client = createApiClient(parsed.baseUrl);
      const response = await client.checkConnection({ signal });
      if (!isActive()) return;
      if (response.ok) {
        setResult({ kind: 'ok', view: normalizeStatus(response.data.status) });
        return;
      }
      if (response.error.kind === 'cancelled') {
        setResult({ kind: 'idle' });
        return;
      }
      setResult({ kind: 'error', message: response.error.message });
    });
  }, [runCheck, text]);

  const forget = useCallback(async (): Promise<void> => {
    abortCheck();
    const cleared = await clear();
    if (!isMounted()) return;
    setText('');
    setResult({ kind: 'idle' });
    setSaveNote(cleared ? 'Đã xoá địa chỉ đã lưu.' : 'Không xoá được địa chỉ đã lưu.');
  }, [abortCheck, clear, isMounted]);

  const chooseTheme = useCallback(
    (next: ThemeMode) => {
      void setThemeMode(next);
    },
    [setThemeMode],
  );

  return (
    <Screen title="Kết nối" subtitle="Địa chỉ máy chủ LAN và chế độ hiển thị">
      {/* Thẻ chọn giao diện Sáng / Tối */}
      <Card>
        <Label>Giao diện hiển thị</Label>
        <View style={[styles.themeSegmentTrack, { backgroundColor: palette.surfaceRaised }]}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Giao diện sáng"
            accessibilityState={{ selected: themeMode === 'light' }}
            onPress={() => chooseTheme('light')}
            style={[
              styles.themeSegmentBtn,
              themeMode === 'light'
                ? { backgroundColor: palette.accent }
                : null,
            ]}
          >
            <Text
              style={[
                styles.themeSegmentText,
                {
                  color:
                    themeMode === 'light' ? palette.onAccent : palette.textMuted,
                  fontWeight: themeMode === 'light' ? '700' : '600',
                },
              ]}
            >
              ☀ Giao diện sáng
            </Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Giao diện tối"
            accessibilityState={{ selected: themeMode === 'dark' }}
            onPress={() => chooseTheme('dark')}
            style={[
              styles.themeSegmentBtn,
              themeMode === 'dark'
                ? { backgroundColor: palette.accent }
                : null,
            ]}
          >
            <Text
              style={[
                styles.themeSegmentText,
                {
                  color:
                    themeMode === 'dark' ? palette.onAccent : palette.textMuted,
                  fontWeight: themeMode === 'dark' ? '700' : '600',
                },
              ]}
            >
              ☾ Giao diện tối
            </Text>
          </Pressable>
        </View>
        <Text style={[typo.caption, { color: palette.textMuted }]}>
          {themeMode === 'light'
            ? 'Đang dùng chế độ Sáng (đồng bộ tông sáng với Web Dashboard, dễ nhìn ban ngày).'
            : 'Đang dùng chế độ Tối (Nocturne Telemetry, dịu mắt khi học buổi tối).'}
        </Text>
      </Card>

      <Card>
        <Label>Địa chỉ máy chạy dashboard</Label>
        <TextInput
          value={text}
          onChangeText={(next) => {
            setText(next);
            setSaveNote('');
          }}
          placeholder="http://192.168.x.x:8000"
          placeholderTextColor={palette.textFaint}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          returnKeyType="done"
          style={[
            styles.input,
            {
              backgroundColor: palette.background,
              borderColor: palette.borderStrong,
              color: palette.text,
            },
          ]}
          accessibilityLabel="Địa chỉ máy chạy dashboard"
          editable={!loading}
        />
        <Text style={[typo.caption, { color: palette.textMuted }]}>
          Đây <Text style={[styles.strong, { color: palette.text }]}>KHÔNG phải IP của camera</Text>{' '}
          — camera chỉ là nguồn ảnh của dashboard, không liên quan. Nhập IP LAN của{' '}
          <Text style={[styles.strong, { color: palette.text }]}>máy đang chạy lệnh</Text>{' '}
          <Text style={[styles.code, { color: palette.accent }]}>
            python -m posture_monitor run
          </Text>{' '}
          (laptop hay Pi đều được), kèm cổng 8000. Lấy IP bằng{' '}
          <Text style={[styles.code, { color: palette.accent }]}>ipconfig</Text> trên Windows.
        </Text>

        <View style={styles.actions}>
          <Button
            label="Lưu địa chỉ"
            onPress={() => void save()}
            variant="secondary"
            style={styles.action}
          />
          <Button
            label="Kiểm tra kết nối"
            onPress={() => void check()}
            variant="primary"
            busy={result.kind === 'running'}
            style={styles.action}
          />
        </View>

        {saveNote ? (
          <Text style={[typo.caption, { color: palette.good }]}>{saveNote}</Text>
        ) : null}
        {baseUrl ? (
          <Text style={[typo.caption, { color: palette.textMuted }]}>
            Đang lưu:{' '}
            <Text style={[styles.code, { color: palette.accent }]}>
              {displayHost(baseUrl)}
            </Text>
          </Text>
        ) : (
          <Text style={[typo.caption, { color: palette.textMuted }]}>
            Chưa lưu địa chỉ nào.
          </Text>
        )}
        {baseUrl ? (
          <Button label="Xoá địa chỉ đã lưu" onPress={() => void forget()} variant="quiet" />
        ) : null}
      </Card>

      {warnings.map((warning) => (
        <Notice key={warning} title="Lưu ý về địa chỉ" body={warning} tone="warn" />
      ))}

      <Divider />

      <CheckPanel result={result} />

      <Card>
        <Label>Vì sao phải nhập IP LAN</Label>
        <Text style={[typo.body, { color: palette.text }]}>
          Dashboard chỉ phục vụ trong LAN. Trên iPhone, “localhost” trỏ vào chính chiếc
          điện thoại chứ không phải máy chạy dashboard, nên mọi request sẽ hỏng ngay. Lấy
          IP bằng <Text style={[styles.code, { color: palette.accent }]}>ipconfig</Text> trên
          Windows hoặc{' '}
          <Text style={[styles.code, { color: palette.accent }]}>hostname -I</Text> trên Pi.
        </Text>
        <Text style={[typo.body, { color: palette.text }]}>
          Điện thoại và máy chủ phải cùng một mạng Wi-Fi. Nếu mở được dashboard bằng
          Safari trên chính máy điện thoại mà app không gọi được, thì vấn đề nằm ở địa
          chỉ/ATS chứ không phải mạng.
        </Text>
      </Card>
    </Screen>
  );
}

function CheckPanel({ result }: { result: CheckResult }): React.ReactElement {
  const { palette, typo } = useTheme();

  if (result.kind === 'running') {
    return <LoadingCard label="Đang gọi /api/status…" />;
  }

  if (result.kind === 'ok') {
    return (
      <Card style={{ borderColor: palette.goodBorder, gap: spacing.sm }}>
        <Text style={[typo.heading, { color: palette.good }]}>Kết nối tốt</Text>
        <Text style={[typo.body, { color: palette.text }]}>
          Máy chủ trả trạng thái:{' '}
          <Text style={[styles.code, { color: palette.accent }]}>
            {result.view.stateText}
          </Text>
        </Text>
        <Text style={[typo.caption, { color: palette.textMuted }]}>
          Xem trực tiếp đang {result.view.streamEnabled ? 'bật' : 'tắt'}. Tiếng cảnh báo
          đang {result.view.muted ? 'tắt' : 'bật'}.
        </Text>
      </Card>
    );
  }

  if (result.kind === 'error') {
    return (
      <Card style={{ borderColor: palette.badBorder, gap: spacing.sm }}>
        <Text style={[typo.heading, { color: palette.bad }]}>Chưa kết nối được</Text>
        <Text style={[typo.body, { color: palette.text }]}>{result.message}</Text>
        <Text style={[typo.caption, { color: palette.textMuted }]}>
          Kiểm tra lần lượt: điện thoại cùng Wi-Fi với máy chủ · IP đúng · dashboard đang
          chạy · không có tường lửa chặn cổng.
        </Text>
      </Card>
    );
  }

  return (
    <Card>
      <Text style={[typo.caption, { color: palette.textMuted }]}>
        Bấm “Kiểm tra kết nối” để thử gọi GET /api/status bằng địa chỉ đang gõ.
      </Text>
    </Card>
  );
}

const styles = StyleSheet.create({
  themeSegmentTrack: {
    flexDirection: 'row',
    borderRadius: radius.md,
    padding: 3,
    gap: 4,
  },
  themeSegmentBtn: {
    flex: 1,
    minHeight: 40,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.sm,
  },
  themeSegmentText: {
    fontSize: 13,
  },
  input: {
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    fontSize: 16,
  },
  actions: {
    flexDirection: 'row',
    gap: spacing.md,
  },
  action: {
    flex: 1,
  },
  code: {
    fontFamily: monoFamily,
  },
  strong: {
    fontWeight: '600',
  },
});
