/**
 * Màn Vi phạm (`GET /api/violations?limit=200`), thích ứng Sáng & Tối.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { FlatList, StyleSheet, Text, View } from 'react-native';

import type { ApiError } from '../api/errors';
import { formatClock, formatDecimal, formatDuration } from '../api/format';
import {
  VIOLATION_KIND_ORDER,
  normalizeViolations,
  type ViolationCount,
  type ViolationEntry,
  type ViolationsView,
} from '../api/payload';
import {
  Button,
  Card,
  Chip,
  ErrorBanner,
  Label,
  LoadingCard,
  Screen,
  UnconfiguredNotice,
  toneColor,
} from '../components/ui';
import { useApp, useTheme } from '../context/AppContext';
import { radius, spacing } from '../theme';

const KIND_FALLBACK_LABEL: Record<string, string> = {
  ABSENT: 'Rời khỏi bàn học',
  PHONE_USE: 'Dùng điện thoại',
  IMPOSTOR: 'Không phải người đăng ký',
};

function violationDurationText(seconds: number): string | null {
  if (!Number.isFinite(seconds) || seconds <= 0) return null;
  if (seconds < 10) return `kéo dài ${formatDecimal(seconds, 1)} giây`;
  return `kéo dài ${formatDuration(seconds)}`;
}

export function ViolationsScreen({ focused }: { focused: boolean }): React.ReactElement {
  const { api, baseUrl, loading: configLoading } = useApp();
  const { palette, typo } = useTheme();

  const [view, setView] = useState<ViolationsView | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);

  const mounted = useRef(true);
  const controllerRef = useRef<AbortController | null>(null);
  const busyRef = useRef(false);

  const load = useCallback(async (): Promise<void> => {
    if (busyRef.current) return;
    busyRef.current = true;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    try {
      const result = await api.getViolations(undefined, { signal: controller.signal });
      if (!mounted.current || controller.signal.aborted) return;
      if (result.ok) {
        setView(normalizeViolations(result.data));
        setError(null);
      } else if (result.error.kind !== 'cancelled') {
        setError(result.error);
      }
    } finally {
      busyRef.current = false;
      if (mounted.current) setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controllerRef.current?.abort();
      controllerRef.current = null;
      busyRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!focused || !baseUrl || configLoading) return;
    void load();
  }, [focused, baseUrl, configLoading, load]);

  const rows = view?.violations ?? [];
  const showSpinner = loading && rows.length === 0;
  const showEmpty = !loading && !error && view !== null && rows.length === 0;

  return (
    <Screen
      title="Vi phạm"
      subtitle="Lịch sử rời bàn, dùng điện thoại và sai người học"
      scroll={false}
    >
      {!baseUrl ? <UnconfiguredNotice /> : null}

      {error ? (
        <ErrorBanner
          message={error.message}
          onRetry={() => void load()}
          retrying={loading}
        />
      ) : null}

      {view ? <Summary view={view} /> : null}

      {showSpinner ? <LoadingCard label="Đang tải lịch sử…" /> : null}

      {showEmpty ? (
        <Card style={[styles.emptyCard, { borderColor: palette.goodBorder }]}>
          <Text style={[typo.heading, { color: palette.good }]}>Chưa có vi phạm nào</Text>
          <Text style={[typo.body, { color: palette.textMuted }]}>
            Chưa ghi nhận lần rời bàn, dùng điện thoại hay sai người học nào. Cứ học
            bình thường nhé.
          </Text>
        </Card>
      ) : null}

      {rows.length > 0 ? (
        <FlatList
          data={rows}
          keyExtractor={(item, index) => `${item.ts}-${item.kind}-${index}`}
          renderItem={({ item }) => <ViolationRow entry={item} />}
          ItemSeparatorComponent={() => (
            <View style={[styles.separator, { backgroundColor: palette.border }]} />
          )}
          style={styles.list}
          contentContainerStyle={styles.listContent}
          refreshing={loading}
          onRefresh={() => void load()}
        />
      ) : null}

      <View style={styles.footer}>
        <Button
          label="Làm mới"
          onPress={() => void load()}
          variant="quiet"
          busy={loading}
          disabled={!baseUrl}
        />
      </View>
    </Screen>
  );
}

function Summary({ view }: { view: ViolationsView }): React.ReactElement {
  const { palette, typo } = useTheme();
  if (view.total === 0 && view.countsNonZero.length === 0) return <></>;
  return (
    <Card style={styles.summaryCard}>
      <View style={styles.summaryHead}>
        <Label>Tổng vi phạm</Label>
        <Text style={[typo.number, { color: palette.text }]}>{view.total}</Text>
      </View>
      {view.countsNonZero.length > 0 ? (
        <View style={styles.chips}>
          {view.countsNonZero.map((c) => (
            <Chip
              key={c.kind}
              text={`${countLabel(c)} · ${c.count}`}
              tone={toneForKind(c.kind)}
            />
          ))}
        </View>
      ) : null}
    </Card>
  );
}

function countLabel(c: ViolationCount): string {
  if (c.kindText) return c.kindText;
  const fallback = KIND_FALLBACK_LABEL[c.kind];
  if (fallback) return fallback;
  return c.kind;
}

function toneForKind(kind: string): 'bad' | 'warn' | 'idle' {
  if (kind === 'IMPOSTOR') return 'bad';
  if (kind === 'PHONE_USE') return 'warn';
  if (kind === 'ABSENT') return 'warn';
  return 'idle';
}

function ViolationRow({ entry }: { entry: ViolationEntry }): React.ReactElement {
  const { palette, typo } = useTheme();
  const duration = violationDurationText(entry.durationS);
  const label = entry.kindText ?? KIND_FALLBACK_LABEL[entry.kind] ?? entry.kind;
  const isUnknownKind =
    !entry.kindText &&
    !Object.prototype.hasOwnProperty.call(KIND_FALLBACK_LABEL, entry.kind);
  return (
    <View style={styles.row}>
      <Text style={[typo.number, styles.clock]}>{formatClock(entry.ts)}</Text>
      <View style={styles.rowBody}>
        <Text style={[typo.body, { color: toneColor(toneForKind(entry.kind), palette) }]}>
          {label}
          {isUnknownKind ? ` (${entry.kind})` : ''}
        </Text>
        {duration ? (
          <Text style={[typo.caption, { color: palette.textMuted }]}>{duration}</Text>
        ) : null}
      </View>
    </View>
  );
}

export const KNOWN_VIOLATION_KINDS = VIOLATION_KIND_ORDER;

const styles = StyleSheet.create({
  list: {
    flex: 1,
  },
  listContent: {
    paddingBottom: spacing.sm,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.md,
    paddingVertical: spacing.sm,
  },
  clock: {
    minWidth: 78,
  },
  rowBody: {
    flex: 1,
    gap: 2,
  },
  separator: {
    height: StyleSheet.hairlineWidth,
  },
  summaryCard: {
    gap: spacing.sm,
  },
  summaryHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'baseline',
  },
  chips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  emptyCard: {
    gap: spacing.sm,
    borderRadius: radius.lg,
  },
  footer: {
    paddingTop: spacing.sm,
  },
});
