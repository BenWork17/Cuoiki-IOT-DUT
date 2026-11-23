/**
 * Màn Trạng thái độc lập (giữ tương thích cho kiểm thử đơn vị; trên thanh tab
 * chính, cụm này đã được tích hợp trực tiếp vào `CameraScreen`).
 */
import React, { useMemo } from 'react';
import { Text } from 'react-native';

import { normalizeStatus } from '../api/payload';
import { PostureStatusSection } from '../components/PostureStatusSection';
import {
  Button,
  Card,
  ErrorBanner,
  LoadingCard,
  Screen,
  UnconfiguredNotice,
} from '../components/ui';
import { useApp } from '../context/AppContext';
import { toPollFetcher, usePoll } from '../hooks/usePoll';
import { type as typo } from '../theme';

export function StatusScreen({ focused }: { focused: boolean }): React.ReactElement {
  const { api, baseUrl, loading: configLoading } = useApp();

  const fetcher = useMemo(
    () => toPollFetcher((signal) => api.getStatus({ signal }), normalizeStatus),
    [api],
  );

  const { data, error, loading, updatedAt, refresh } = usePoll(fetcher, {
    enabled: focused && !configLoading && !!baseUrl,
  });

  return (
    <Screen title="Trạng thái" subtitle="Tư thế hiện tại do Pi đo và gửi lên">
      {!baseUrl ? (
        <UnconfiguredNotice />
      ) : (
        <>
          {error ? <ErrorBanner message={error.message} onRetry={refresh} retrying={loading} /> : null}
          {data ? (
            <PostureStatusSection view={data} updatedAt={updatedAt} />
          ) : loading ? (
            <LoadingCard />
          ) : null}
          {!data && !loading && !error ? (
            <Card>
              <Text style={typo.body}>Chưa có dữ liệu. Bấm Thử lại để hỏi lại máy chủ.</Text>
              <Button label="Thử lại" onPress={refresh} variant="quiet" />
            </Card>
          ) : null}
          <Button label="Làm mới ngay" onPress={refresh} variant="quiet" busy={loading && !!data} />
        </>
      )}
    </Screen>
  );
}
