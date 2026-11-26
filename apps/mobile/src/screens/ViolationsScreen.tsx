/**
 * Màn Vi phạm & Nhật ký lỗi (`GET /api/violations` + `GET /api/logs`), thích ứng Sáng & Tối.
 *
 * Hiển thị rõ ràng cho từng bản ghi:
 * 1. Vào thời gian nào (`HH:MM:SS · DD/MM/YYYY` theo giờ địa phương).
 * 2. Lỗi / vi phạm gì (nhãn tiếng Việt, mã lỗi, mô tả nguyên nhân cụ thể và thời lượng kéo dài).
 * 3. Nhật ký sự kiện & lỗi hệ thống từ Raspberry Pi (camera RTSP, loa cảnh báo, phiên học, AI).
 */
import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';

import type { ApiError } from '../api/errors';
import {
  formatClock,
  formatDate,
  formatDateTime,
  formatDecimal,
  formatDuration,
} from '../api/format';
import {
  VIOLATION_KIND_ORDER,
  normalizeSystemLogs,
  normalizeViolations,
  type SystemLogEntry,
  type SystemLogsView,
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

const POLL_INTERVAL_MS = 4000;

type TabMode = 'violations' | 'system_logs';
type ViolationFilter = 'ALL' | 'PHONE_USE' | 'ABSENT' | 'IMPOSTOR';
type SystemLogFilter = 'ALL' | 'WARN_ERR' | 'ERROR';

const KIND_FALLBACK_LABEL: Record<string, string> = {
  ABSENT: 'Rời khỏi bàn học',
  PHONE_USE: 'Dùng điện thoại',
  IMPOSTOR: 'Không phải người đăng ký',
};

const KIND_DETAIL_TEXT: Record<string, string> = {
  PHONE_USE: 'Phát hiện người học cầm hoặc sử dụng điện thoại trong phiên học.',
  ABSENT: 'Không thấy người học trước bàn quá thời gian cho phép trong phiên học.',
  IMPOSTOR: 'Khuôn mặt trước camera không khớp với hồ sơ người học đang chọn.',
};

const FILTER_OPTIONS: Array<{ id: ViolationFilter; shortLabel: string }> = [
  { id: 'ALL', shortLabel: 'Tất cả' },
  { id: 'PHONE_USE', shortLabel: 'Điện thoại' },
  { id: 'ABSENT', shortLabel: 'Rời bàn' },
  { id: 'IMPOSTOR', shortLabel: 'Sai người' },
];

const LOG_FILTER_OPTIONS: Array<{ id: SystemLogFilter; label: string }> = [
  { id: 'ALL', label: 'Tất cả log' },
  { id: 'WARN_ERR', label: 'Cảnh báo & Lỗi' },
  { id: 'ERROR', label: 'Chỉ lỗi' },
];

function violationDurationText(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return 'Phát cảnh báo tại thời điểm ghi nhận';
  if (seconds < 10) return `Thời lượng: kéo dài ${formatDecimal(seconds, 1)} giây`;
  return `Thời lượng: kéo dài ${formatDuration(seconds)}`;
}

function loggerSourceLabel(logger: string, message: string): string {
  if (message.startsWith('SPEAK_OK') || logger.includes('audio') || logger.includes('speaker')) {
    return 'Loa cảnh báo';
  }
  if (logger.includes('camera.capture') || logger.includes('rtsp')) return 'Camera RTSP';
  if (logger.includes('onvif') || logger.includes('ptz')) return 'Điều khiển PTZ';
  if (logger.includes('faces') || logger.includes('people')) return 'Nhận diện khuôn mặt';
  if (logger.includes('phone')) return 'Model điện thoại';
  if (logger.includes('storage') || logger.includes('sqlite')) return 'Kho dữ liệu';
  if (logger.includes('web')) return 'Bảng điều khiển';
  return 'Giám sát AI';
}

export function ViolationsScreen({ focused }: { focused: boolean }): React.ReactElement {
  const { api, baseUrl, loading: configLoading } = useApp();
  const { palette, typo } = useTheme();

  const [tabMode, setTabMode] = useState<TabMode>('violations');
  const [kindFilter, setKindFilter] = useState<ViolationFilter>('ALL');
  const [logFilter, setLogFilter] = useState<SystemLogFilter>('ALL');

  const [view, setView] = useState<ViolationsView | null>(null);
  const [logsView, setLogsView] = useState<SystemLogsView | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastUpdatedMs, setLastUpdatedMs] = useState<number | null>(null);

  const mounted = useRef(true);
  const controllerRef = useRef<AbortController | null>(null);
  const busyRef = useRef(false);

  const load = useCallback(
    async (silent = false): Promise<void> => {
      if (busyRef.current) return;
      busyRef.current = true;
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      if (!silent) setLoading(true);
      try {
        const [violRes, logsRes] = await Promise.all([
          api.getViolations(undefined, { signal: controller.signal }),
          api.getLogs('INFO', undefined, { signal: controller.signal }),
        ]);
        if (!mounted.current || controller.signal.aborted) return;

        if (violRes.ok) {
          setView(normalizeViolations(violRes.data));
        }
        if (logsRes.ok) {
          setLogsView(normalizeSystemLogs(logsRes.data));
        }

        const activeErr = tabMode === 'violations' ? violRes : logsRes;
        if (!activeErr.ok && activeErr.error.kind !== 'cancelled') {
          setError(activeErr.error);
        } else if (violRes.ok || logsRes.ok) {
          setError(null);
          setLastUpdatedMs(Date.now());
        }
      } finally {
        busyRef.current = false;
        if (mounted.current && !silent) setLoading(false);
      }
    },
    [api, tabMode],
  );

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
    if (!focused || !baseUrl || configLoading) {
      controllerRef.current?.abort();
      return;
    }
    void load(false);
    const timer = setInterval(() => {
      void load(true);
    }, POLL_INTERVAL_MS);
    return () => {
      clearInterval(timer);
      controllerRef.current?.abort();
    };
  }, [focused, baseUrl, configLoading, load]);

  const allViolations = view?.violations ?? [];
  const filteredViolations = useMemo(() => {
    if (kindFilter === 'ALL') return allViolations;
    return allViolations.filter((item) => item.kind === kindFilter);
  }, [allViolations, kindFilter]);

  const countMap = useMemo(() => {
    const map: Record<string, number> = { ABSENT: 0, PHONE_USE: 0, IMPOSTOR: 0 };
    for (const c of view?.counts ?? []) {
      map[c.kind] = c.count;
    }
    return map;
  }, [view]);

  const allLogs = logsView?.logs ?? [];
  const filteredLogs = useMemo(() => {
    if (logFilter === 'ERROR') return allLogs.filter((item) => item.level === 'ERROR');
    if (logFilter === 'WARN_ERR') {
      return allLogs.filter((item) => item.level === 'ERROR' || item.level === 'WARNING');
    }
    return allLogs;
  }, [allLogs, logFilter]);

  const warnPlusErrCount = (logsView?.errorCount ?? 0) + (logsView?.warningCount ?? 0);

  const renderViolationItem = useCallback(
    ({ item }: { item: ViolationEntry }) => <ViolationRow entry={item} />,
    [],
  );

  const renderSystemLogItem = useCallback(
    ({ item }: { item: SystemLogEntry }) => <SystemLogRow entry={item} />,
    [],
  );

  return (
    <Screen
      title="Nhật ký vi phạm"
      subtitle="Thời gian ghi nhận chi tiết các lỗi trong phiên học và hệ thống"
      scroll={false}
    >
      {!baseUrl ? <UnconfiguredNotice /> : null}

      {/* Thanh chuyển 2 chế độ: Nhật ký vi phạm học tập & Log sự kiện/lỗi hệ thống */}
      <View
        style={[
          styles.segmented,
          { backgroundColor: palette.surfaceRaised, borderColor: palette.border },
        ]}
      >
        <Pressable
          accessibilityRole="button"
          accessibilityState={{ selected: tabMode === 'violations' }}
          onPress={() => setTabMode('violations')}
          style={[
            styles.segmentBtn,
            tabMode === 'violations' && {
              backgroundColor: palette.surface,
              borderColor: palette.accentBorder,
            },
          ]}
        >
          <Text
            style={[
              typo.button,
              { color: tabMode === 'violations' ? palette.accent : palette.textMuted },
            ]}
          >
            Vi phạm học ({view?.total ?? 0})
          </Text>
        </Pressable>

        <Pressable
          accessibilityRole="button"
          accessibilityState={{ selected: tabMode === 'system_logs' }}
          onPress={() => setTabMode('system_logs')}
          style={[
            styles.segmentBtn,
            tabMode === 'system_logs' && {
              backgroundColor: palette.surface,
              borderColor: palette.accentBorder,
            },
          ]}
        >
          <Text
            style={[
              typo.button,
              {
                color:
                  tabMode === 'system_logs'
                    ? palette.accent
                    : warnPlusErrCount > 0
                      ? palette.warn
                      : palette.textMuted,
              },
            ]}
          >
            Log hệ thống ({allLogs.length})
          </Text>
        </Pressable>
      </View>

      {error ? (
        <ErrorBanner
          message={error.message}
          onRetry={() => void load(false)}
          retrying={loading}
        />
      ) : null}

      {tabMode === 'violations' ? (
        <FlatList
          data={filteredViolations}
          keyExtractor={(item, index) => `${item.ts}-${item.kind}-${index}`}
          renderItem={renderViolationItem}
          initialNumToRender={12}
          maxToRenderPerBatch={12}
          windowSize={7}
          ListHeaderComponent={
            <View style={styles.headerBlock}>
              <Summary
                view={view}
                kindFilter={kindFilter}
                countMap={countMap}
                onSelectFilter={setKindFilter}
                lastUpdatedMs={lastUpdatedMs}
              />
              {filteredViolations.length > 0 ? (
                <Label>Danh sách log chi tiết ({filteredViolations.length} bản ghi)</Label>
              ) : null}
            </View>
          }
          ListEmptyComponent={
            loading && view === null ? (
              <LoadingCard label="Đang tải nhật ký vi phạm…" />
            ) : !error && view !== null ? (
              <Card style={[styles.emptyCard, { borderColor: palette.goodBorder }]}>
                <Text style={[typo.heading, { color: palette.good }]}>
                  {kindFilter === 'ALL'
                    ? 'Chưa có vi phạm nào'
                    : 'Không có bản ghi cho bộ lọc này'}
                </Text>
                <Text style={[typo.body, { color: palette.textMuted }]}>
                  {kindFilter === 'ALL'
                    ? 'Chưa ghi nhận lần rời bàn, dùng điện thoại hay sai người học nào. Khi có vi phạm, giờ và lỗi chi tiết sẽ hiện ngay tại đây.'
                    : 'Chọn “Tất cả” ở thanh lọc phía trên để xem toàn bộ lịch sử vi phạm.'}
                </Text>
              </Card>
            ) : undefined
          }
          ItemSeparatorComponent={() => <View style={styles.itemGap} />}
          style={styles.list}
          contentContainerStyle={styles.listContent}
          refreshing={loading}
          onRefresh={() => void load(false)}
        />
      ) : (
        <FlatList
          data={filteredLogs}
          keyExtractor={(item, index) => `${item.ts}-${item.level}-${index}`}
          renderItem={renderSystemLogItem}
          initialNumToRender={15}
          maxToRenderPerBatch={15}
          windowSize={7}
          ListHeaderComponent={
            <View style={styles.headerBlock}>
              <SystemLogToolbar
                logsView={logsView}
                logFilter={logFilter}
                onSelectFilter={setLogFilter}
                lastUpdatedMs={lastUpdatedMs}
              />
              {filteredLogs.length > 0 ? (
                <Label>Chi tiết sự kiện & lỗi ({filteredLogs.length} dòng)</Label>
              ) : null}
            </View>
          }
          ListEmptyComponent={
            loading && logsView === null ? (
              <LoadingCard label="Đang tải log hệ thống…" />
            ) : !error && logsView !== null ? (
              <Card style={[styles.emptyCard, { borderColor: palette.border }]}>
                <Text style={[typo.heading, { color: palette.text }]}>
                  Không có bản ghi log phù hợp
                </Text>
                <Text style={[typo.body, { color: palette.textMuted }]}>
                  Hệ thống chưa ghi nhận cảnh báo hoặc lỗi nào ở mức lọc đang chọn.
                </Text>
              </Card>
            ) : undefined
          }
          ItemSeparatorComponent={() => <View style={styles.itemGap} />}
          style={styles.list}
          contentContainerStyle={styles.listContent}
          refreshing={loading}
          onRefresh={() => void load(false)}
        />
      )}

      <View style={styles.footer}>
        <Button
          label="Làm mới"
          onPress={() => void load(false)}
          variant="quiet"
          busy={loading}
          disabled={!baseUrl}
        />
      </View>
    </Screen>
  );
}

function Summary({
  view,
  kindFilter,
  countMap,
  onSelectFilter,
  lastUpdatedMs,
}: {
  view: ViolationsView | null;
  kindFilter: ViolationFilter;
  countMap: Record<string, number>;
  onSelectFilter: (next: ViolationFilter) => void;
  lastUpdatedMs: number | null;
}): React.ReactElement {
  const { palette, typo } = useTheme();
  const total = view?.total ?? 0;

  return (
    <Card style={styles.summaryCard}>
      <View style={styles.summaryHead}>
        <View style={styles.summaryTitleCol}>
          <Label>Tổng vi phạm</Label>
          {lastUpdatedMs ? (
            <Text style={[typo.caption, { color: palette.textFaint }]}>
              Tự cập nhật mỗi 4 s
            </Text>
          ) : null}
        </View>
        <Text style={[typo.number, { color: palette.text }]}>{total}</Text>
      </View>

      <View style={styles.filterRow}>
        {FILTER_OPTIONS.map((opt) => {
          const active = kindFilter === opt.id;
          const count = opt.id === 'ALL' ? total : (countMap[opt.id] ?? 0);
          return (
            <Pressable
              key={opt.id}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
              onPress={() => onSelectFilter(opt.id)}
              style={[
                styles.filterPill,
                {
                  backgroundColor: active ? palette.accentWash : palette.surfaceRaised,
                  borderColor: active ? palette.accentBorder : palette.border,
                },
              ]}
            >
              <Text
                style={[
                  typo.caption,
                  styles.filterPillText,
                  { color: active ? palette.accent : palette.textMuted },
                ]}
              >
                {opt.shortLabel} · {count}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </Card>
  );
}

function SystemLogToolbar({
  logsView,
  logFilter,
  onSelectFilter,
  lastUpdatedMs,
}: {
  logsView: SystemLogsView | null;
  logFilter: SystemLogFilter;
  onSelectFilter: (next: SystemLogFilter) => void;
  lastUpdatedMs: number | null;
}): React.ReactElement {
  const { palette, typo } = useTheme();
  const errCount = logsView?.errorCount ?? 0;
  const warnCount = logsView?.warningCount ?? 0;

  return (
    <Card style={styles.summaryCard}>
      <View style={styles.summaryHead}>
        <View style={styles.summaryTitleCol}>
          <Label>Nhật ký sự kiện & lỗi Raspberry Pi</Label>
          {lastUpdatedMs ? (
            <Text style={[typo.caption, { color: palette.textFaint }]}>
              Tự cập nhật · {formatClock(lastUpdatedMs)}
            </Text>
          ) : null}
        </View>
        <View style={styles.chips}>
          <Chip text={`Lỗi · ${errCount}`} tone={errCount > 0 ? 'bad' : 'idle'} />
          <Chip text={`Cảnh báo · ${warnCount}`} tone={warnCount > 0 ? 'warn' : 'idle'} />
        </View>
      </View>

      <View style={styles.filterRow}>
        {LOG_FILTER_OPTIONS.map((opt) => {
          const active = logFilter === opt.id;
          return (
            <Pressable
              key={opt.id}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
              onPress={() => onSelectFilter(opt.id)}
              style={[
                styles.filterPill,
                {
                  backgroundColor: active ? palette.accentWash : palette.surfaceRaised,
                  borderColor: active ? palette.accentBorder : palette.border,
                },
              ]}
            >
              <Text
                style={[
                  typo.caption,
                  styles.filterPillText,
                  { color: active ? palette.accent : palette.textMuted },
                ]}
              >
                {opt.label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </Card>
  );
}

export function countLabel(c: ViolationCount): string {
  if (c.kindText) return c.kindText;
  const fallback = KIND_FALLBACK_LABEL[c.kind];
  if (fallback) return fallback;
  return c.kind;
}

function toneForKind(kind: string): 'bad' | 'warn' | 'idle' {
  if (kind === 'IMPOSTOR') return 'bad';
  if (kind === 'PHONE_USE') return 'bad';
  if (kind === 'ABSENT') return 'warn';
  return 'idle';
}

const ViolationRow = memo(function ViolationRow({
  entry,
}: {
  entry: ViolationEntry;
}): React.ReactElement {
  const { palette, typo } = useTheme();
  const tone = toneForKind(entry.kind);
  const accentColor = toneColor(tone, palette);
  const label = entry.kindText ?? KIND_FALLBACK_LABEL[entry.kind] ?? entry.kind;
  const detail =
    KIND_DETAIL_TEXT[entry.kind] ??
    `Hệ thống ghi nhận sự kiện vi phạm (${entry.kind}) trong phiên học.`;
  const duration = violationDurationText(entry.durationS);

  return (
    <View
      style={[
        styles.logCard,
        {
          backgroundColor: palette.surface,
          borderColor: palette.border,
          borderLeftColor: accentColor,
        },
      ]}
    >
      <View style={styles.logHeader}>
        <View style={styles.timeWrap}>
          <Text style={[typo.body, styles.timePrimary, { color: palette.text }]}>
            {formatClock(entry.ts)}
          </Text>
          <Text style={[typo.caption, { color: palette.textMuted }]}>
            · {formatDate(entry.ts)}
          </Text>
        </View>
        <Chip text={entry.kind} tone={tone} />
      </View>

      <Text style={[typo.heading, { color: accentColor }]}>{label}</Text>
      <Text style={[typo.body, { color: palette.text }]}>{detail}</Text>
      <Text style={[typo.caption, { color: palette.textMuted }]}>{duration}</Text>
    </View>
  );
});

const SystemLogRow = memo(function SystemLogRow({
  entry,
}: {
  entry: SystemLogEntry;
}): React.ReactElement {
  const { palette, typo } = useTheme();
  const tone: 'bad' | 'warn' | 'good' | 'idle' =
    entry.level === 'ERROR'
      ? 'bad'
      : entry.level === 'WARNING'
        ? 'warn'
        : entry.message.startsWith('SPEAK_OK')
          ? 'good'
          : 'idle';
  const levelLabel =
    entry.level === 'ERROR'
      ? 'LỖI'
      : entry.level === 'WARNING'
        ? 'CẢNH BÁO'
        : 'SỰ KIỆN';
  const borderColor =
    tone === 'bad'
      ? palette.bad
      : tone === 'warn'
        ? palette.warn
        : tone === 'good'
          ? palette.good
          : palette.accent;
  const source = loggerSourceLabel(entry.logger, entry.message);

  return (
    <View
      style={[
        styles.logCard,
        {
          backgroundColor: palette.surface,
          borderColor: palette.border,
          borderLeftColor: borderColor,
        },
      ]}
    >
      <View style={styles.logHeader}>
        <Text style={[typo.caption, styles.timeMono, { color: palette.textMuted }]}>
          {formatDateTime(entry.ts)}
        </Text>
        <View style={styles.chips}>
          <Chip text={source} tone="idle" />
          <Chip text={levelLabel} tone={tone} />
        </View>
      </View>
      <Text style={[typo.body, { color: palette.text }]}>{entry.message}</Text>
    </View>
  );
});

export const KNOWN_VIOLATION_KINDS = VIOLATION_KIND_ORDER;

const styles = StyleSheet.create({
  segmented: {
    flexDirection: 'row',
    borderRadius: radius.md,
    borderWidth: 1,
    padding: 3,
    gap: 4,
  },
  segmentBtn: {
    flex: 1,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: 'transparent',
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerBlock: {
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  list: {
    flex: 1,
  },
  listContent: {
    paddingBottom: spacing.md,
  },
  itemGap: {
    height: spacing.sm,
  },
  logCard: {
    borderWidth: 1,
    borderLeftWidth: 4,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: 4,
  },
  logHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: spacing.xs,
  },
  timeWrap: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 4,
  },
  timePrimary: {
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
  },
  timeMono: {
    fontWeight: '600',
    fontVariant: ['tabular-nums'],
  },
  summaryCard: {
    gap: spacing.sm,
  },
  summaryHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: spacing.sm,
  },
  summaryTitleCol: {
    gap: 2,
    flexShrink: 1,
  },
  filterRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
  },
  filterPill: {
    paddingHorizontal: spacing.sm + 2,
    paddingVertical: 5,
    borderRadius: radius.pill,
    borderWidth: 1,
  },
  filterPillText: {
    fontWeight: '600',
  },
  chips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
  },
  emptyCard: {
    gap: spacing.sm,
    borderRadius: radius.lg,
  },
  footer: {
    paddingTop: spacing.xs,
  },
});
