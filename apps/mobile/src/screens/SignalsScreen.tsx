/**
 * Màn Tín hiệu độc lập, thích ứng Sáng & Tối.
 */
import React, { useMemo } from 'react';
import { Text } from 'react-native';

import { normalizeSignals } from '../api/payload';
import { LearnerSignalsSection } from '../components/LearnerSignalsSection';
import {
  Button,
  ErrorBanner,
  LoadingCard,
  Screen,
  UnconfiguredNotice,
} from '../components/ui';
import { useApp, useTheme } from '../context/AppContext';
import { toPollFetcher, usePoll } from '../hooks/usePoll';

export function SignalsScreen({ focused }: { focused: boolean }): React.ReactElement {
  const { api, baseUrl, loading: configLoading } = useApp();
  const { palette, typo } = useTheme();

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

      <Text style={[typo.caption, { color: palette.textFaint }]}>
        Tín hiệu chỉ có hạn trong vài giây. Dòng ghi “Chưa có dữ liệu mới” nghĩa là lần đo
        gần nhất đã cũ — không phải kết luận hiện tại.
      </Text>
    </Screen>
  );
}
