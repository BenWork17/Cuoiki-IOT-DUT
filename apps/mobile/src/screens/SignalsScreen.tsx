/**
 * Màn 4 — Tín hiệu.
 *
 * Dùng `GET /api/signals` (`app.py:897-909`), trả ba mục `presence`, `phone`,
 * `identity`, mỗi mục `{state, age_s, age_limit_s, fresh}`; `identity` thêm
 * `name`, `reason` (`people_service.py:1368-1397`).
 *
 * Quy tắc quan trọng nhất của màn này (`app.js:145-149`): `fresh === false`
 * nghĩa là **hết dữ liệu**, không phải "vẫn như cũ". Dòng đó phải nói
 * "Chưa có dữ liệu mới" và tuổi là "–"; lặp lại `state` cũ là làm người dùng
 * tin hệ thống vừa đo. Việc quyết định câu chữ nằm trong `normalizeSignal()`
 * (thuần, test được), màn hình chỉ vẽ.
 */
import React, { useMemo } from 'react';
import { StyleSheet, Text } from 'react-native';

import { normalizeSignals } from '../api/payload';
import { LearnerSignalsSection } from '../components/LearnerSignalsSection';
import {
  Button,
  ErrorBanner,
  LoadingCard,
  Screen,
  UnconfiguredNotice,
} from '../components/ui';
import { useApp } from '../context/AppContext';
import { toPollFetcher, usePoll } from '../hooks/usePoll';
import { colors, type as typo } from '../theme';

/** `focused` do thanh tab truyền vào: màn chỉ hỏi máy chủ khi đang được hiện. */
export function SignalsScreen({ focused }: { focused: boolean }): React.ReactElement {
  const { api, baseUrl, loading: configLoading } = useApp();

  const fetcher = useMemo(
    () => toPollFetcher((signal) => api.getSignals({ signal }), normalizeSignals),
    [api],
  );

  const { data, error, loading, refresh } = usePoll(fetcher, {
    enabled: focused && !configLoading && !!baseUrl,
  });
  const peopleDisabled = error?.status === 503;

  return (
    <Screen title="Tín hiệu" subtitle="Dấu hiệu thô gần nhất mà Pi ghi nhận">
      {!baseUrl ? <UnconfiguredNotice /> : null}

      {error && !peopleDisabled ? (
        <ErrorBanner message={error.message} onRetry={refresh} retrying={loading} />
      ) : null}

      {loading && !data && !peopleDisabled ? <LoadingCard /> : null}

      {baseUrl && (data || peopleDisabled) ? (
        <LearnerSignalsSection
          rows={data ?? null}
          peopleDisabledMessage={
            peopleDisabled
              ? (error?.message ??
                'Máy chủ chưa bật dịch vụ người học trong lần chạy này.')
              : null
          }
        />
      ) : null}

      {data ? (
        <Button label="Làm mới ngay" onPress={refresh} variant="quiet" busy={loading} />
      ) : null}

      <Text style={[typo.caption, styles.footnote]}>
        Tín hiệu chỉ có hạn trong vài giây. Dòng ghi “Chưa có dữ liệu mới” nghĩa là lần đo
        gần nhất đã cũ — không phải kết luận hiện tại.
      </Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  footnote: {
    color: colors.textFaint,
  },
});
