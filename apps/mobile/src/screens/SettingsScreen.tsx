/**
 * Màn 8 — Kết nối (bắt buộc theo tài liệu yêu cầu §5.1 hàng 7).
 *
 * Địa chỉ máy chủ **nhập trong app** và **lưu lại**; không có IP/cổng nào
 * hardcode trong mã nguồn.
 *
 * Kiểm tra kết nối gọi `GET /api/status` và chỉ báo thành công khi phản hồi
 * **đọc được như trạng thái** (`state` là chuỗi, `muted` là bool). Chỉ nhìn
 * mã 200 là chưa đủ: trang đăng nhập của router wifi, hay một index HTML của
 * Flask, cũng trả 200 — báo "kết nối tốt" lúc đó là nói dối người dùng và
 * khiến họ đi tìm lỗi ở chỗ khác.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';

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
import { useApp } from '../context/AppContext';
import { useAsyncAction } from '../hooks/useAsyncAction';
import { colors, monoFamily, radius, spacing, type as typo } from '../theme';

type CheckResult =
  | { kind: 'idle' }
  | { kind: 'running' }
  | { kind: 'ok'; view: StatusView }
  | { kind: 'error'; message: string };

export function SettingsScreen(): React.ReactElement {
  const { baseUrl, setBaseUrl, clear, loading } = useApp();
  const { run: runCheck, isMounted, abort: abortCheck } = useAsyncAction();
  const [text, setText] = useState(baseUrl);
  const [result, setResult] = useState<CheckResult>({ kind: 'idle' });
  const [saveNote, setSaveNote] = useState('');

  // Địa chỉ đọc từ bộ nhớ xong thì đổ vào ô nhập.
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
      // Kiểm tra trên địa chỉ **đang gõ**, chưa cần lưu: người dùng phải sửa
      // được IP sai mà không bị app ghi đè cấu hình cũ trước khi họ chắc chắn.
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

  return (
    <Screen title="Kết nối" subtitle="Địa chỉ máy chạy dashboard trong cùng mạng LAN">
      <Card>
        <Label>Địa chỉ máy chạy dashboard</Label>
        <TextInput
          value={text}
          onChangeText={(next) => {
            setText(next);
            setSaveNote('');
          }}
          placeholder="http://192.168.x.x:8000"
          placeholderTextColor={colors.textFaint}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          returnKeyType="done"
          style={styles.input}
          accessibilityLabel="Địa chỉ máy chạy dashboard"
          editable={!loading}
        />
        <Text style={[typo.caption, styles.muted]}>
          Đây <Text style={styles.strong}>KHÔNG phải IP của camera</Text> — camera chỉ là
          nguồn ảnh của dashboard, không liên quan. Nhập IP LAN của{' '}
          <Text style={styles.strong}>máy đang chạy lệnh</Text>{' '}
          <Text style={styles.code}>python -m posture_monitor run</Text> (laptop hay Pi đều
          được), kèm cổng 8000. Lấy IP bằng <Text style={styles.code}>ipconfig</Text> trên
          Windows.
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

        {saveNote ? <Text style={[typo.caption, styles.okText]}>{saveNote}</Text> : null}
        {baseUrl ? (
          <Text style={[typo.caption, styles.muted]}>
            Đang lưu: <Text style={styles.code}>{displayHost(baseUrl)}</Text>
          </Text>
        ) : (
          <Text style={[typo.caption, styles.muted]}>Chưa lưu địa chỉ nào.</Text>
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
        <Text style={[typo.body, styles.body]}>
          Dashboard chỉ phục vụ trong LAN. Trên iPhone, “localhost” trỏ vào chính chiếc
          điện thoại chứ không phải máy chạy dashboard, nên mọi request sẽ hỏng ngay. Lấy
          IP bằng <Text style={styles.code}>ipconfig</Text> trên Windows hoặc{' '}
          <Text style={styles.code}>hostname -I</Text> trên Pi.
        </Text>
        <Text style={[typo.body, styles.body]}>
          Điện thoại và máy chủ phải cùng một mạng Wi-Fi. Nếu mở được dashboard bằng
          Safari trên chính máy điện thoại mà app không gọi được, thì vấn đề nằm ở địa
          chỉ/ATS chứ không phải mạng.
        </Text>
      </Card>
    </Screen>
  );
}

function CheckPanel({ result }: { result: CheckResult }): React.ReactElement {
  if (result.kind === 'running') {
    return <LoadingCard label="Đang gọi /api/status…" />;
  }

  if (result.kind === 'ok') {
    return (
      <Card style={styles.checkOk}>
        <Text style={[typo.heading, { color: colors.good }]}>Kết nối tốt</Text>
        <Text style={[typo.body, styles.body]}>
          Máy chủ trả trạng thái: <Text style={styles.code}>{result.view.stateText}</Text>
        </Text>
        <Text style={[typo.caption, styles.muted]}>
          Xem trực tiếp đang {result.view.streamEnabled ? 'bật' : 'tắt'}. Tiếng cảnh báo
          đang {result.view.muted ? 'tắt' : 'bật'}.
        </Text>
      </Card>
    );
  }

  if (result.kind === 'error') {
    return (
      <Card style={styles.checkError}>
        <Text style={[typo.heading, { color: colors.bad }]}>Chưa kết nối được</Text>
        <Text style={[typo.body, styles.body]}>{result.message}</Text>
        <Text style={[typo.caption, styles.muted]}>
          Kiểm tra lần lượt: điện thoại cùng Wi-Fi với máy chủ · IP đúng · dashboard đang
          chạy · không có tường lửa chặn cổng.
        </Text>
      </Card>
    );
  }

  return (
    <Card>
      <Text style={[typo.caption, styles.muted]}>
        Bấm “Kiểm tra kết nối” để thử gọi GET /api/status bằng địa chỉ đang gõ.
      </Text>
    </Card>
  );
}

const styles = StyleSheet.create({
  input: {
    backgroundColor: colors.background,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.borderStrong,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    color: colors.text,
    fontSize: 16,
  },
  actions: {
    flexDirection: 'row',
    gap: spacing.md,
  },
  action: {
    flex: 1,
  },
  body: {
    color: colors.text,
  },
  muted: {
    color: colors.textMuted,
  },
  okText: {
    color: colors.good,
  },
  code: {
    color: colors.accent,
    fontFamily: monoFamily,
  },
  strong: {
    color: colors.text,
    fontWeight: '600',
  },
  checkOk: {
    borderColor: 'rgba(95,224,176,0.35)',
    gap: spacing.sm,
  },
  checkError: {
    borderColor: 'rgba(255,107,94,0.40)',
    gap: spacing.sm,
  },
});
