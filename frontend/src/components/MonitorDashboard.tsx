import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, ArrowLeft, Globe, Loader2, Play } from 'lucide-react';
import {
  fetchMonitorMetrics,
  fetchMonitorStatus,
  triggerMonitorRun,
  type MonitorMetricItem,
} from '../api/monitor';
import type { RiskCategory } from '../api/forecast';
import type { Lang } from '../i18n';

interface MonitorDashboardProps {
  lang: Lang;
  onToggleLang: () => void;
  onBackToMap: () => void;
}

const CATEGORIES: RiskCategory[] = ['Extremo', 'Alto', 'Moderado', 'Bajo'];

function fmt(val: number | null | undefined, digits = 3): string {
  if (val === null || val === undefined || Number.isNaN(val)) return '—';
  return val.toFixed(digits);
}

function fmtPct(val: number | null | undefined): string {
  if (val === null || val === undefined || Number.isNaN(val)) return '—';
  return `${(val * 100).toFixed(2)}%`;
}

export function MonitorDashboard({ lang, onToggleLang, onBackToMap }: MonitorDashboardProps) {
  const isEs = lang === 'es';
  const queryClient = useQueryClient();
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [isTriggering, setIsTriggering] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const metricsQuery = useQuery({
    queryKey: ['monitor-metrics'],
    queryFn: ({ signal }) => fetchMonitorMetrics(30, signal),
    staleTime: 60 * 1000,
  });

  const statusQuery = useQuery({
    queryKey: ['monitor-status'],
    queryFn: ({ signal }) => fetchMonitorStatus(signal),
    refetchInterval: (q) => (q.state.data?.running ? 2000 : false),
  });

  async function handleRun() {
    setRunError(null);
    setIsTriggering(true);
    try {
      await triggerMonitorRun(1);
      await queryClient.invalidateQueries({ queryKey: ['monitor-status'] });
      await queryClient.invalidateQueries({ queryKey: ['monitor-metrics'] });
    } catch (err) {
      setRunError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsTriggering(false);
    }
  }

  const items: MonitorMetricItem[] = metricsQuery.data?.items ?? [];
  const activeItem =
    (selectedDate ? items.find((i) => i.target_date === selectedDate) : undefined) ?? items[0];
  const isRunning = Boolean(statusQuery.data?.running || isTriggering);

  return (
    <div className="min-h-screen bg-space-base text-fcText-primary">
      <header className="border-b border-space-border bg-space-surface/90 px-6 py-4 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onBackToMap}
              className="inline-flex items-center gap-1.5 rounded-lg border border-space-border bg-space-elevated px-3 py-1.5 font-mono text-xs text-fcText-primary hover:border-space-borderLight transition"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              {isEs ? 'Mapa' : 'Map'}
            </button>
            <div className="flex items-center gap-2">
              <Activity className="h-5 w-5 text-lime-brand" />
              <div>
                <h1 className="font-title text-base font-extrabold tracking-tight">
                  {isEs ? 'Monitor Empírico VIIRS' : 'VIIRS Empirical Monitor'}
                </h1>
                <p className="font-mono text-[11px] text-fcText-secondary">
                  {isEs
                    ? 'Validación diaria de snapshots 24 h contra focos NASA FIRMS VIIRS'
                    : 'Daily 24h snapshot validation against NASA FIRMS VIIRS hotspots'}
                </p>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleRun}
              disabled={isRunning}
              className="inline-flex items-center gap-1.5 rounded-lg border border-lime-brand/40 bg-lime-brand/15 px-3 py-1.5 font-mono text-xs font-semibold text-lime-brand hover:bg-lime-brand/25 disabled:opacity-50 transition"
            >
              {isRunning ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              {isRunning ? (isEs ? 'Procesando...' : 'Running...') : isEs ? 'Validar VIIRS' : 'Run VIIRS'}
            </button>

            <button
              type="button"
              onClick={onToggleLang}
              aria-label="Cambiar idioma / Switch language"
              className="inline-flex items-center gap-1 rounded-lg border border-space-border bg-space-elevated px-2.5 py-1.5 font-mono text-xs font-semibold hover:border-space-borderLight transition"
            >
              <Globe className="h-3.5 w-3.5 text-fcText-secondary" />
              {lang.toUpperCase()}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-6 p-6">
        {(runError || statusQuery.data?.last_error) && (
          <div className="rounded-xl border border-sensor-high/50 bg-sensor-high/10 px-4 py-2.5 font-mono text-xs text-sensor-high">
            {runError || statusQuery.data?.last_error}
          </div>
        )}

        {metricsQuery.isLoading ? (
          <div className="flex items-center gap-2 font-mono text-sm text-fcText-secondary">
            <Loader2 className="h-4 w-4 animate-spin" />
            {isEs ? 'Cargando métricas empíricas...' : 'Loading empirical metrics...'}
          </div>
        ) : !activeItem ? (
          <div className="rounded-2xl border border-space-border bg-space-surface p-6 text-sm text-fcText-secondary">
            {isEs
              ? 'Todavía no hay evaluaciones registradas. Cuando exista un snapshot diario de 24 h y una corrida de VIIRS para la misma fecha, vas a ver aquí la calibración y precisión.'
              : 'No evaluations recorded yet. Once a 24h snapshot and a VIIRS ingestion exist for the same date, calibration and precision metrics will appear here.'}
          </div>
        ) : (
          <>
            <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <MetricCard label="PR-AUC" value={fmt(activeItem.pr_auc)} />
              <MetricCard label="ROC-AUC" value={fmt(activeItem.roc_auc)} />
              <MetricCard label={isEs ? 'Calibración' : 'Calibration'} value={fmt(activeItem.calibration_ratio, 2)} />
              <MetricCard label="Brier" value={fmt(activeItem.brier_score, 5)} />
              <MetricCard
                label="Hits / Misses"
                value={`${activeItem.hits_count} / ${activeItem.misses_count}`}
                accent="text-lime-brand"
              />
              <MetricCard
                label={isEs ? 'Falsas Alarmas' : 'False Alarms'}
                value={String(activeItem.false_alarms_count)}
                accent="text-[#FF9C55]"
              />
            </section>

            <section className="grid gap-6 lg:grid-cols-2">
              <div className="rounded-2xl border border-space-border bg-space-surface p-4">
                <h2 className="font-title text-sm font-bold">
                  {isEs
                    ? `Desglose por categoría (${activeItem.target_date})`
                    : `Category breakdown (${activeItem.target_date})`}
                </h2>
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full text-left font-mono text-xs">
                    <thead className="border-b border-space-border text-fcText-secondary">
                      <tr>
                        <th className="py-2 pr-3">{isEs ? 'Categoría' : 'Category'}</th>
                        <th className="py-2 px-2">{isEs ? 'Celdas' : 'Cells'}</th>
                        <th className="py-2 px-2">Pos</th>
                        <th className="py-2 px-2">Precision</th>
                        <th className="py-2 px-2">Recall</th>
                        <th className="py-2 pl-2">Lift</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-space-border/60">
                      {CATEGORIES.map((cat) => {
                        const row = activeItem.categories?.[cat];
                        return (
                          <tr key={cat}>
                            <td className="py-2 pr-3 font-semibold">{cat}</td>
                            <td className="py-2 px-2">{row?.cells_count ?? 0}</td>
                            <td className="py-2 px-2">{row?.positives_count ?? 0}</td>
                            <td className="py-2 px-2">{fmtPct(row?.precision)}</td>
                            <td className="py-2 px-2">{fmtPct(row?.recall)}</td>
                            <td className="py-2 pl-2">{fmt(row?.lift, 1)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="rounded-2xl border border-space-border bg-space-surface p-4">
                <h2 className="font-title text-sm font-bold">
                  {isEs ? 'Histórico diario' : 'Daily history'}
                </h2>
                <div className="mt-3 max-h-72 overflow-y-auto">
                  <table className="w-full text-left font-mono text-xs">
                    <thead className="border-b border-space-border text-fcText-secondary">
                      <tr>
                        <th className="py-2 pr-2">{isEs ? 'Fecha' : 'Date'}</th>
                        <th className="py-2 px-2">Pos</th>
                        <th className="py-2 px-2">Hits</th>
                        <th className="py-2 px-2">Miss</th>
                        <th className="py-2 px-2">PR-AUC</th>
                        <th className="py-2 pl-2">ROC-AUC</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-space-border/60">
                      {items.map((item) => {
                        const isSelected = item.target_date === activeItem.target_date;
                        return (
                          <tr
                            key={`${item.target_date}-${item.issued_date}`}
                            onClick={() => setSelectedDate(item.target_date)}
                            className={`cursor-pointer transition hover:bg-space-elevated/60 ${
                              isSelected ? 'bg-space-elevated/80' : ''
                            }`}
                          >
                            <td className="py-2 pr-2 font-semibold">{item.target_date}</td>
                            <td className="py-2 px-2">{item.n_positives}</td>
                            <td className="py-2 px-2 text-lime-brand">{item.hits_count}</td>
                            <td className="py-2 px-2 text-[#FF6759]">{item.misses_count}</td>
                            <td className="py-2 px-2">{fmt(item.pr_auc)}</td>
                            <td className="py-2 pl-2">{fmt(item.roc_auc)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  );
}

function MetricCard({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-2xl border border-space-border bg-space-surface p-3.5">
      <div className="font-mono text-[11px] text-fcText-secondary">{label}</div>
      <div className={`mt-1 font-mono text-lg font-bold ${accent ?? 'text-fcText-primary'}`}>
        {value}
      </div>
    </div>
  );
}
