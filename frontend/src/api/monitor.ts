import type { RiskCategory } from './forecast';

export type MonitorOutcome = 'hit' | 'miss' | 'false_alarm';

export interface MonitorCategoryMetrics {
  cells_count: number;
  positives_count: number;
  precision: number | null;
  recall: number | null;
  lift: number | null;
}

export interface MonitorMetricItem {
  target_date: string;
  issued_date: string;
  min_frp_mw: number;
  n_cells: number;
  n_positives: number;
  observed_rate: number;
  mean_predicted_prob: number;
  calibration_ratio: number | null;
  brier_score: number;
  roc_auc: number | null;
  pr_auc: number | null;
  hits_count: number;
  misses_count: number;
  false_alarms_count: number;
  categories: Record<RiskCategory, MonitorCategoryMetrics>;
  evaluated_at: string;
}

export interface MonitorStatus {
  running: boolean;
  last_run_at: string | null;
  last_result: {
    sources: string[];
    ingested_rows: number;
    dates_seen: string[];
    evaluated_dates: string[];
  } | null;
  last_error: string | null;
}

export interface ThresholdProfileDayStats {
  alerts_count: number;
  hits_count: number;
  misses_count: number;
  false_alarms_count: number;
  capture_rate: number | null;
  precision: number | null;
  cutoffs: Record<'Extremo' | 'Alto' | 'Moderado', number>;
}

export interface ThresholdComparisonItem {
  target_date: string;
  issued_date: string;
  n_positives: number;
  previous: ThresholdProfileDayStats;
  current: ThresholdProfileDayStats;
}

export interface ThresholdComparisonSummary {
  days_compared: number;
  total_positives: number;
  previous_total_hits: number;
  current_total_hits: number;
  previous_total_false_alarms: number;
  current_total_false_alarms: number;
  false_alarm_reduction_pct: number | null;
}

export interface ThresholdComparisonResponse {
  profiles: {
    previous: Record<string, string | number>;
    current: Record<string, string | number>;
  };
  summary: ThresholdComparisonSummary;
  items: ThresholdComparisonItem[];
}

export async function fetchThresholdComparison(
  limit = 14,
  signal?: AbortSignal,
): Promise<ThresholdComparisonResponse> {
  const res = await fetch(`/api/v1/monitor/threshold-comparison?limit=${limit}`, { signal });
  if (!res.ok) {
    throw new Error((await res.text()) || `API error (${res.status})`);
  }
  return res.json() as Promise<ThresholdComparisonResponse>;
}

export async function fetchMonitorMetrics(
  limit = 30,
  signal?: AbortSignal,
): Promise<{ items: MonitorMetricItem[] }> {
  const res = await fetch(`/api/v1/monitor/metrics?limit=${limit}`, { signal });
  if (!res.ok) {
    throw new Error((await res.text()) || `API error (${res.status})`);
  }
  return res.json() as Promise<{ items: MonitorMetricItem[] }>;
}

export async function fetchMonitorStatus(signal?: AbortSignal): Promise<MonitorStatus> {
  const res = await fetch('/api/v1/monitor/status', { signal });
  if (!res.ok) {
    throw new Error((await res.text()) || `API error (${res.status})`);
  }
  return res.json() as Promise<MonitorStatus>;
}

export async function triggerMonitorRun(dayRange = 1): Promise<{ status: string } & MonitorStatus> {
  const res = await fetch(`/api/v1/monitor/run?day_range=${dayRange}`, { method: 'POST' });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `API error (${res.status})`);
  }
  return res.json() as Promise<{ status: string } & MonitorStatus>;
}

function csvCell(value: string | number | null | undefined): string {
  if (value === null || value === undefined || (typeof value === 'number' && Number.isNaN(value))) {
    return '';
  }
  const str = String(value);
  if (str.includes(',') || str.includes('"') || str.includes('\n')) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

export function buildMonitorCsv(items: MonitorMetricItem[]): string {
  const headers = [
    'target_date',
    'issued_date',
    'n_cells',
    'n_positives',
    'expected_positives',
    'hits_count',
    'misses_count',
    'capture_rate_pct',
    'false_alarms_count',
    'roc_auc',
    'pr_auc',
    'calibration_ratio',
    'brier_score',
    'extremo_cells',
    'extremo_pos',
    'alto_cells',
    'alto_pos',
    'moderado_cells',
    'moderado_pos',
    'bajo_cells',
    'bajo_pos',
    'evaluated_at',
  ];

  const rows = items.map((item) => {
    const expectedPositives = (item.mean_predicted_prob * item.n_cells).toFixed(2);
    const captureRatePct =
      item.n_positives > 0 ? ((item.hits_count / item.n_positives) * 100).toFixed(2) : '';
    const ext = item.categories?.Extremo;
    const alt = item.categories?.Alto;
    const mod = item.categories?.Moderado;
    const baj = item.categories?.Bajo;

    return [
      item.target_date,
      item.issued_date,
      item.n_cells,
      item.n_positives,
      expectedPositives,
      item.hits_count,
      item.misses_count,
      captureRatePct,
      item.false_alarms_count,
      item.roc_auc !== null ? item.roc_auc.toFixed(6) : '',
      item.pr_auc !== null ? item.pr_auc.toFixed(6) : '',
      item.calibration_ratio !== null ? item.calibration_ratio.toFixed(4) : '',
      item.brier_score.toFixed(6),
      ext?.cells_count ?? 0,
      ext?.positives_count ?? 0,
      alt?.cells_count ?? 0,
      alt?.positives_count ?? 0,
      mod?.cells_count ?? 0,
      mod?.positives_count ?? 0,
      baj?.cells_count ?? 0,
      baj?.positives_count ?? 0,
      item.evaluated_at,
    ]
      .map(csvCell)
      .join(',');
  });

  return [headers.join(','), ...rows].join('\n');
}
