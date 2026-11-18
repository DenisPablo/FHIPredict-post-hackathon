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
