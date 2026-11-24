import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, ArrowLeft, Download, Globe, HelpCircle, Loader2, Play } from 'lucide-react';
import {
  buildMonitorCsv,
  fetchMonitorMetrics,
  fetchMonitorStatus,
  fetchThresholdComparison,
  triggerMonitorRun,
  type MonitorMetricItem,
  type ThresholdComparisonResponse,
} from '../api/monitor';
import type { RiskCategory } from '../api/forecast';
import type { Lang } from '../i18n';

interface MonitorDashboardProps {
  lang: Lang;
  onToggleLang: () => void;
  onBackToMap: () => void;
}

const CATEGORIES: RiskCategory[] = ['Extremo', 'Alto', 'Moderado', 'Bajo'];

const CAT_COLOR: Record<RiskCategory, string> = {
  Extremo: '#FF6759',
  Alto: '#FF9C55',
  Moderado: '#68D9D0',
  Bajo: '#64748B',
};

function fmt(val: number | null | undefined, digits = 3): string {
  if (val === null || val === undefined || Number.isNaN(val)) return '—';
  return val.toFixed(digits);
}

function fmtPct(val: number | null | undefined): string {
  if (val === null || val === undefined || Number.isNaN(val)) return '—';
  return `${(val * 100).toFixed(2)}%`;
}

function rocBadge(roc: number | null, isEs: boolean): { text: string; tone: string } {
  if (roc === null) return { text: isEs ? 'Sin focos' : 'No fires', tone: 'text-fcText-secondary' };
  if (roc >= 0.85) return { text: isEs ? 'Excelente' : 'Excellent', tone: 'text-lime-brand' };
  if (roc >= 0.7) return { text: isEs ? 'Bueno' : 'Good', tone: 'text-[#68D9D0]' };
  return { text: isEs ? 'A mejorar' : 'Needs work', tone: 'text-[#FF9C55]' };
}

function calibBadge(cal: number | null, isEs: boolean): { text: string; tone: string } {
  if (cal === null) return { text: isEs ? 'Sin focos' : 'No fires', tone: 'text-fcText-secondary' };
  if (cal >= 0.7 && cal <= 1.5) return { text: isEs ? 'Bien calibrado' : 'Well calibrated', tone: 'text-lime-brand' };
  if (cal > 1.5) return { text: isEs ? 'Sobreestima / día en curso' : 'Overestimates / partial day', tone: 'text-[#FF9C55]' };
  return { text: isEs ? 'Subestima' : 'Underestimates', tone: 'text-[#FF6759]' };
}

export function MonitorDashboard({ lang, onToggleLang, onBackToMap }: MonitorDashboardProps) {
  const isEs = lang === 'es';
  const queryClient = useQueryClient();
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [isTriggering, setIsTriggering] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [showGuide, setShowGuide] = useState(true);

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

  const comparisonQuery = useQuery({
    queryKey: ['monitor-threshold-comparison'],
    queryFn: ({ signal }) => fetchThresholdComparison(14, signal),
    staleTime: 60 * 1000,
  });

  async function handleRun() {
    setRunError(null);
    setIsTriggering(true);
    try {
      await triggerMonitorRun(1);
      await queryClient.invalidateQueries({ queryKey: ['monitor-status'] });
      await queryClient.invalidateQueries({ queryKey: ['monitor-metrics'] });
      await queryClient.invalidateQueries({ queryKey: ['monitor-threshold-comparison'] });
    } catch (err) {
      setRunError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsTriggering(false);
    }
  }

  function handleDownloadCsv() {
    if (items.length === 0) return;
    const csv = buildMonitorCsv(items);
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'fhipredict-monitoreo-viirs.csv';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  const items: MonitorMetricItem[] = metricsQuery.data?.items ?? [];
  const activeItem =
    (selectedDate ? items.find((i) => i.target_date === selectedDate) : undefined) ?? items[0];
  const isRunning = Boolean(statusQuery.data?.running || isTriggering);

  const rocInfo = activeItem ? rocBadge(activeItem.roc_auc, isEs) : null;
  const calInfo = activeItem ? calibBadge(activeItem.calibration_ratio, isEs) : null;

  return (
    <div className="h-screen w-full overflow-y-auto bg-space-base text-fcText-primary">
      <header className="sticky top-0 z-20 border-b border-space-border bg-space-surface/95 px-6 py-4 backdrop-blur-md">
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

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setShowGuide((prev) => !prev)}
              className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 font-mono text-xs font-semibold transition ${
                showGuide
                  ? 'border-lime-brand/40 bg-lime-brand/10 text-lime-brand'
                  : 'border-space-border bg-space-elevated text-fcText-primary hover:border-space-borderLight'
              }`}
            >
              <HelpCircle className="h-3.5 w-3.5" />
              {isEs ? 'Guía' : 'Guide'}
            </button>

            <button
              type="button"
              onClick={handleDownloadCsv}
              disabled={items.length === 0}
              className="inline-flex items-center gap-1.5 rounded-lg border border-space-border bg-space-elevated px-3 py-1.5 font-mono text-xs font-semibold text-fcText-primary hover:border-space-borderLight disabled:opacity-40 transition"
            >
              <Download className="h-3.5 w-3.5 text-fcText-secondary" />
              {isEs ? 'Descargar CSV' : 'Download CSV'}
            </button>

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

        {showGuide && <QuickInterpretationGuide isEs={isEs} onHide={() => setShowGuide(false)} />}

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
            <PlainLanguageSummary item={activeItem} isEs={isEs} />

            <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <MetricCard
                label="ROC-AUC"
                value={fmt(activeItem.roc_auc)}
                badge={rocInfo?.text}
                badgeTone={rocInfo?.tone}
                hint={isEs ? 'Prioridad territorial (1.0 = ideal)' : 'Spatial ranking (1.0 = ideal)'}
              />
              <MetricCard
                label="PR-AUC"
                value={fmt(activeItem.pr_auc)}
                hint={isEs ? 'Precisión en zonas de alerta' : 'Alert precision-recall area'}
              />
              <MetricCard
                label={isEs ? 'Calibración' : 'Calibration'}
                value={fmt(activeItem.calibration_ratio, 2)}
                badge={calInfo?.text}
                badgeTone={calInfo?.tone}
                hint={isEs ? 'Esperado / Real (1.0 = exacto)' : 'Expected / Real (1.0 = exact)'}
              />
              <MetricCard
                label="Brier"
                value={fmt(activeItem.brier_score, 5)}
                hint={isEs ? 'Error cuadrático (menor = mejor)' : 'Squared prob. error (lower = better)'}
              />
              <MetricCard
                label="Hits / Misses"
                value={`${activeItem.hits_count} / ${activeItem.misses_count}`}
                accent="text-lime-brand"
                hint={isEs ? 'Focos en alerta vs. fuera de alerta' : 'Caught vs. missed fires'}
              />
              <MetricCard
                label={isEs ? 'Falsas Alarmas' : 'False Alarms'}
                value={String(activeItem.false_alarms_count)}
                accent="text-[#FF9C55]"
                hint={isEs ? 'Celdas en alerta sin fuego hoy' : 'Alerted cells without fire'}
              />
            </section>

            <section className="grid gap-6 lg:grid-cols-2">
              <CategoryCaptureChart item={activeItem} isEs={isEs} />
              <DailyHistoryChart
                items={items}
                selectedDate={activeItem.target_date}
                onSelectDate={setSelectedDate}
                isEs={isEs}
              />
            </section>

            {comparisonQuery.data && comparisonQuery.data.items.length > 0 && (
              <>
                <ThresholdComparisonChart
                  data={comparisonQuery.data}
                  selectedDate={activeItem.target_date}
                  onSelectDate={setSelectedDate}
                  isEs={isEs}
                />
                <StockComparisonLineChart
                  data={comparisonQuery.data}
                  selectedDate={activeItem.target_date}
                  onSelectDate={setSelectedDate}
                  isEs={isEs}
                />
              </>
            )}

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

function PlainLanguageSummary({ item, isEs }: { item: MonitorMetricItem; isEs: boolean }) {
  const alertCells =
    (item.categories?.Extremo?.cells_count ?? 0) + (item.categories?.Alto?.cells_count ?? 0);
  const watchCells = item.categories?.Moderado?.cells_count ?? 0;
  const watchHits = item.categories?.Moderado?.positives_count ?? 0;
  const alertSharePct = item.n_cells > 0 ? ((alertCells / item.n_cells) * 100).toFixed(2) : '0.00';
  const watchSharePct = item.n_cells > 0 ? ((watchCells / item.n_cells) * 100).toFixed(2) : '0.00';
  const capturePct = item.n_positives > 0 ? ((item.hits_count / item.n_positives) * 100).toFixed(1) : '0.0';
  const expectedPos = (item.mean_predicted_prob * item.n_cells).toFixed(1);

  return (
    <section className="rounded-2xl border border-space-border bg-space-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-title text-sm font-bold text-fcText-primary">
          {isEs
            ? `Resumen en lenguaje simple (${item.target_date})`
            : `Plain-language summary (${item.target_date})`}
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-space-border bg-space-elevated px-2.5 py-0.5 font-mono text-[11px] text-fcText-secondary">
            {isEs
              ? `Alerta accionable (Alto+): ${alertCells} / ${item.n_cells.toLocaleString('es-AR')} (${alertSharePct}%)`
              : `Actionable alert (High+): ${alertCells} / ${item.n_cells.toLocaleString('en-US')} (${alertSharePct}%)`}
          </span>
          <span className="rounded-full border border-[#68D9D0]/30 bg-[#68D9D0]/10 px-2.5 py-0.5 font-mono text-[11px] text-[#68D9D0]">
            {isEs
              ? `Vigilancia (Moderado): ${watchCells} (${watchSharePct}%)`
              : `Watch (Moderate): ${watchCells} (${watchSharePct}%)`}
          </span>
        </div>
      </div>

      <div className="mt-3 grid gap-4 md:grid-cols-2">
        <div className="space-y-2 text-xs leading-relaxed text-fcText-secondary">
          <p>
            {item.n_positives === 0 ? (
              isEs ? (
                'El satélite VIIRS no registró incendios confirmados (≥ 10 MW) en esta fecha.'
              ) : (
                'The VIIRS satellite recorded zero confirmed fires (≥ 10 MW) on this date.'
              )
            ) : isEs ? (
              <>
                Se detectaron <strong className="text-fcText-primary">{item.n_positives}</strong> zonas con
                incendio real en el país. La alerta accionable (Alto+) capturó el{' '}
                <strong className="text-lime-brand">{capturePct}%</strong> ({item.hits_count} aciertos y{' '}
                {item.misses_count} fuera de alerta) vigilando solo el{' '}
                <strong className="text-fcText-primary">{alertSharePct}%</strong> del territorio
                {watchHits > 0
                  ? `, más ${watchHits} foco(s) en la capa de vigilancia Moderado.`
                  : '.'}
              </>
            ) : (
              <>
                Satellites detected <strong className="text-fcText-primary">{item.n_positives}</strong> active
                fire zones nationwide. Actionable alerts (High+) captured{' '}
                <strong className="text-lime-brand">{capturePct}%</strong> ({item.hits_count} hits and{' '}
                {item.misses_count} misses) while monitoring only{' '}
                <strong className="text-fcText-primary">{alertSharePct}%</strong> of the territory
                {watchHits > 0
                  ? `, plus ${watchHits} fire(s) inside the Moderate watch layer.`
                  : '.'}
              </>
            )}
          </p>
          <p>
            {isEs ? (
              <>
                El modelo estimaba <strong className="text-fcText-primary">~{expectedPos}</strong> focos para
                las 24 h completas (contra <strong className="text-fcText-primary">{item.n_positives}</strong>{' '}
                observados).
                {item.calibration_ratio !== null && item.calibration_ratio > 2.0
                  ? ' Si la fecha es hoy, la diferencia es normal porque faltan pasadas satelitales de la tarde.'
                  : ''}
              </>
            ) : (
              <>
                The model expected <strong className="text-fcText-primary">~{expectedPos}</strong> fire zones
                for the full 24h window (vs.{' '}
                <strong className="text-fcText-primary">{item.n_positives}</strong> observed).
                {item.calibration_ratio !== null && item.calibration_ratio > 2.0
                  ? ' For an in-progress day, this gap is expected until afternoon satellite passes arrive.'
                  : ''}
              </>
            )}
          </p>
        </div>

        <div className="flex flex-col justify-center rounded-xl border border-space-border bg-space-elevated/50 p-3.5">
          <div className="flex items-center justify-between font-mono text-xs">
            <span className="text-fcText-secondary">
              {isEs ? 'Cobertura de focos reales en alerta' : 'Real fires captured in alert'}
            </span>
            <span className="font-bold text-lime-brand">{capturePct}%</span>
          </div>
          <div className="mt-2 h-3 w-full overflow-hidden rounded-full bg-space-base">
            <div
              className="h-full rounded-full bg-lime-brand transition-all duration-500"
              style={{
                width: `${item.n_positives > 0 ? Math.min(100, (item.hits_count / item.n_positives) * 100) : 0}%`,
              }}
            />
          </div>
          <div className="mt-2 flex justify-between font-mono text-[11px] text-fcText-secondary">
            <span>
              {isEs ? `Aciertos (Hits): ${item.hits_count}` : `Hits: ${item.hits_count}`}
            </span>
            <span>
              {isEs ? `No alertados (Misses): ${item.misses_count}` : `Misses: ${item.misses_count}`}
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}

function CategoryCaptureChart({ item, isEs }: { item: MonitorMetricItem; isEs: boolean }) {
  return (
    <div className="rounded-2xl border border-space-border bg-space-surface p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-title text-sm font-bold">
          {isEs ? 'Captura de incendios por nivel de riesgo' : 'Fire capture by risk level'}
        </h2>
        <span className="rounded-md border border-space-border bg-space-elevated px-2 py-0.5 font-mono text-[11px] text-fcText-secondary">
          {item.target_date}
        </span>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-fcText-secondary">
        {isEs
          ? 'Porcentaje de focos reales detectados dentro de cada categoría y cuántas veces supera al azar (Lift).'
          : 'Share of real fires falling inside each risk category and improvement over random (Lift).'}
      </p>

      <div
        role="img"
        aria-label={isEs ? 'Gráfico de captura por nivel de riesgo' : 'Risk level capture chart'}
        className="mt-4 space-y-3"
      >
        {CATEGORIES.map((cat) => {
          const row = item.categories?.[cat];
          const recall = row?.recall ?? 0;
          const pct = Math.max(0, Math.min(100, recall * 100));
          const liftText =
            row?.lift !== null && row?.lift !== undefined ? `${row.lift.toFixed(1)}x` : '—';
          return (
            <div key={cat} className="space-y-1.5">
              <div className="flex flex-wrap items-center justify-between gap-2 font-mono text-xs">
                <div className="flex items-center gap-2">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: CAT_COLOR[cat] }}
                  />
                  <span className="font-semibold text-fcText-primary">{cat}</span>
                  <span className="text-[11px] text-fcText-secondary">
                    ({(row?.cells_count ?? 0).toLocaleString(isEs ? 'es-AR' : 'en-US')}{' '}
                    {isEs ? 'celdas' : 'cells'})
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-fcText-primary">
                    {pct.toFixed(0)}% ({row?.positives_count ?? 0} {isEs ? 'focos' : 'fires'})
                  </span>
                  <span className="rounded-md border border-space-border bg-space-elevated px-1.5 py-0.5 text-[10px] text-fcText-secondary">
                    Lift {liftText}
                  </span>
                </div>
              </div>
              <div className="h-2.5 w-full overflow-hidden rounded-full bg-space-elevated">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${pct > 0 ? Math.max(3, pct) : 0}%`,
                    backgroundColor: CAT_COLOR[cat],
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DailyHistoryChart({
  items,
  selectedDate,
  onSelectDate,
  isEs,
}: {
  items: MonitorMetricItem[];
  selectedDate: string;
  onSelectDate: (d: string) => void;
  isEs: boolean;
}) {
  const chronological = items.slice(0, 14).reverse();
  const maxPos = Math.max(1, ...chronological.map((d) => d.n_positives));

  return (
    <div className="rounded-2xl border border-space-border bg-space-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-title text-sm font-bold">
          {isEs ? 'Evolución diaria: Aciertos vs. Omitidos' : 'Daily trend: Hits vs. Misses'}
        </h2>
        <div className="flex items-center gap-3 font-mono text-[10px] text-fcText-secondary">
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-lime-brand" /> Hits
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-[#FF6759]" /> Misses
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-[#68D9D0]" /> ROC-AUC
          </span>
        </div>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-fcText-secondary">
        {isEs
          ? 'Hacé clic en un día para ver su detalle. Cada barra compara aciertos vs. omitidos y muestra su ROC-AUC.'
          : 'Click any day to inspect details. Each bar compares hits vs. misses and shows its ROC-AUC.'}
      </p>

      <div
        role="img"
        aria-label={isEs ? 'Gráfico de evolución diaria' : 'Daily evolution chart'}
        className="mt-4 flex items-end gap-2 overflow-x-auto pb-1"
      >
        {chronological.map((d) => {
          const isSel = d.target_date === selectedDate;
          const hitPct = (d.hits_count / maxPos) * 100;
          const missPct = (d.misses_count / maxPos) * 100;
          return (
            <button
              key={d.target_date}
              type="button"
              onClick={() => onSelectDate(d.target_date)}
              className={`flex min-w-[68px] flex-1 flex-col items-center rounded-xl border p-2.5 transition ${
                isSel
                  ? 'border-lime-brand/50 bg-space-elevated/90'
                  : 'border-space-border/60 bg-space-elevated/35 hover:border-space-borderLight'
              }`}
            >
              <span className="font-mono text-[10px] text-fcText-secondary">
                <span className="text-lime-brand">{d.hits_count}</span> /{' '}
                <span className="text-[#FF6759]">{d.misses_count}</span>
              </span>

              <div className="mt-2 flex h-24 w-7 flex-col justify-end overflow-hidden rounded-md bg-space-base/80">
                {missPct > 0 && (
                  <div
                    className="w-full bg-[#FF6759]"
                    style={{ height: `${Math.max(4, missPct)}%` }}
                  />
                )}
                {hitPct > 0 && (
                  <div
                    className="w-full bg-lime-brand"
                    style={{ height: `${Math.max(4, hitPct)}%` }}
                  />
                )}
              </div>

              <span className="mt-2 font-mono text-[11px] font-semibold text-fcText-primary">
                {d.target_date.slice(5)}
              </span>
              <span className="mt-1 rounded bg-space-base px-1.5 py-0.5 font-mono text-[10px] text-[#68D9D0]">
                {d.roc_auc !== null ? d.roc_auc.toFixed(3) : '—'}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function QuickInterpretationGuide({ isEs, onHide }: { isEs: boolean; onHide: () => void }) {
  return (
    <section className="rounded-2xl border border-lime-brand/25 bg-space-surface/95 p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-title text-sm font-bold text-fcText-primary">
            {isEs ? '¿Cómo leer estos datos? Los 3 números clave' : 'How to read this: the 3 key numbers'}
          </h2>
          <p className="mt-0.5 text-xs text-fcText-secondary">
            {isEs
              ? 'Evaluá siempre días ya cerrados (ayer o anteriores), no el día de hoy porque faltan pasadas de satélite.'
              : 'Always evaluate completed days (yesterday or earlier), not today while satellite passes are still incoming.'}
          </p>
        </div>
        <button
          type="button"
          onClick={onHide}
          className="rounded-lg border border-space-border bg-space-elevated px-2.5 py-1 font-mono text-[11px] text-fcText-secondary hover:text-fcText-primary transition"
        >
          {isEs ? 'Ocultar guía' : 'Hide guide'}
        </button>
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <div className="rounded-xl border border-space-border bg-space-elevated/50 p-3">
          <div className="font-mono text-xs font-bold text-lime-brand">
            1. {isEs ? '¿Acertó dónde hubo fuego?' : 'Did it catch real fires?'}
          </div>
          <p className="mt-1 text-xs leading-relaxed text-fcText-secondary">
            {isEs ? (
              <>
                Mirá <strong className="text-fcText-primary">Hits / Misses</strong> y la barra verde: indica
                cuántos incendios reales estaban dentro de las zonas en alerta previa (utilidad operativa real).
              </>
            ) : (
              <>
                Check <strong className="text-fcText-primary">Hits / Misses</strong> and the green bar: how
                many real fires fell inside pre-alerted zones (real operational value).
              </>
            )}
          </p>
        </div>

        <div className="rounded-xl border border-space-border bg-space-elevated/50 p-3">
          <div className="font-mono text-xs font-bold text-[#68D9D0]">
            2. {isEs ? '¿Ordena bien el peligro?' : 'Does it rank danger well?'}
          </div>
          <p className="mt-1 text-xs leading-relaxed text-fcText-secondary">
            {isEs ? (
              <>
                Mirá <strong className="text-fcText-primary">ROC-AUC</strong> (0.5 = azar, 1.0 = perfecto).
                Arriba de <strong className="text-fcText-primary">0.85</strong> confirma que el modelo distingue
                bien las zonas más peligrosas.
              </>
            ) : (
              <>
                Check <strong className="text-fcText-primary">ROC-AUC</strong> (0.5 = random, 1.0 = perfect).
                Above <strong className="text-fcText-primary">0.85</strong> confirms the model ranks danger well.
              </>
            )}
          </p>
        </div>

        <div className="rounded-xl border border-space-border bg-space-elevated/50 p-3">
          <div className="font-mono text-xs font-bold text-[#FF9C55]">
            3. {isEs ? '¿Son creíbles los porcentajes?' : 'Are probabilities on scale?'}
          </div>
          <p className="mt-1 text-xs leading-relaxed text-fcText-secondary">
            {isEs ? (
              <>
                Mirá <strong className="text-fcText-primary">Calibración</strong> (esperado / real). Cerca de{' '}
                <strong className="text-fcText-primary">1.0</strong> es ideal; debajo de 0.5 indica que el
                umbral de alerta está muy estricto.
              </>
            ) : (
              <>
                Check <strong className="text-fcText-primary">Calibration</strong> (expected / real). Near{' '}
                <strong className="text-fcText-primary">1.0</strong> is ideal; below 0.5 means alert thresholds
                are too strict.
              </>
            )}
          </p>
        </div>
      </div>
    </section>
  );
}

function MetricCard({
  label,
  value,
  accent,
  badge,
  badgeTone,
  hint,
}: {
  label: string;
  value: string;
  accent?: string;
  badge?: string;
  badgeTone?: string;
  hint?: string;
}) {
  return (
    <div className="rounded-2xl border border-space-border bg-space-surface p-4">
      <div className="font-mono text-[11px] text-fcText-secondary">{label}</div>
      <div className="mt-1.5 flex flex-wrap items-baseline justify-between gap-2">
        <div className={`font-mono text-2xl font-bold tracking-tight ${accent ?? 'text-fcText-primary'}`}>
          {value}
        </div>
        {badge && (
          <span
            className={`rounded-full border border-space-border bg-space-elevated px-2 py-0.5 font-mono text-[10px] font-semibold ${badgeTone}`}
          >
            {badge}
          </span>
        )}
      </div>
      {hint && <p className="mt-2 text-xs leading-snug text-fcText-secondary">{hint}</p>}
    </div>
  );
}

function ThresholdComparisonChart({
  data,
  selectedDate,
  onSelectDate,
  isEs,
}: {
  data: ThresholdComparisonResponse;
  selectedDate: string;
  onSelectDate: (date: string) => void;
  isEs: boolean;
}) {
  const [metric, setMetric] = useState<'false_alarms' | 'hits'>('false_alarms');
  const ordered = [...data.items].reverse();
  const maxVal = Math.max(
    1,
    ...ordered.flatMap((d) =>
      metric === 'false_alarms'
        ? [d.previous.false_alarms_count, d.current.false_alarms_count]
        : [d.previous.hits_count, d.current.hits_count],
    ),
  );
  const { summary } = data;
  const redPct = summary.false_alarm_reduction_pct;

  return (
    <section
      className="rounded-2xl border border-space-border bg-space-surface p-4 sm:p-5"
      aria-label={
        isEs
          ? 'Gráfico comparativo de umbrales: Anterior vs. Actual (Alerta Alto+)'
          : 'Threshold comparison chart: Previous vs. Current (High+ Alert)'
      }
      role="img"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-title text-sm font-bold text-fcText-primary">
            {isEs
              ? 'Comparación de umbrales: Anterior vs. Actual (Alerta Alto+)'
              : 'Threshold comparison: Previous vs. Current (High+ Alert)'}
          </h2>
          <p className="mt-0.5 text-xs text-fcText-secondary">
            {isEs
              ? 'Compara el perfil anterior (Moderado+ 0.1% / 1% / 5%) contra la alerta accionable actual (Alto+ 0.05% / 0.4%); Moderado (2.5%) queda solo como vigilancia visual.'
              : 'Compares the previous profile (Moderate+ 0.1% / 1% / 5%) against current actionable alerts (High+ 0.05% / 0.4%); Moderate (2.5%) stays as visual watch only.'}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {redPct !== null && (
            <span className="rounded-full border border-lime-brand/30 bg-lime-brand/10 px-2.5 py-0.5 font-mono text-[11px] font-semibold text-lime-brand">
              {isEs ? `-${redPct.toFixed(1)}% falsas alarmas` : `-${redPct.toFixed(1)}% false alarms`}
            </span>
          )}
          <span className="rounded-full border border-space-border bg-space-elevated px-2.5 py-0.5 font-mono text-[11px] text-fcText-secondary">
            {isEs
              ? `Aciertos: ${summary.previous_total_hits}/${summary.total_positives} → ${summary.current_total_hits}/${summary.total_positives}`
              : `Hits: ${summary.previous_total_hits}/${summary.total_positives} → ${summary.current_total_hits}/${summary.total_positives}`}
          </span>
          {summary.current_total_watch_hits !== undefined &&
            summary.current_total_combined_hits !== undefined && (
              <span className="rounded-full border border-[#68D9D0]/30 bg-[#68D9D0]/10 px-2.5 py-0.5 font-mono text-[11px] text-[#68D9D0]">
                {isEs
                  ? `Vigilancia Moderado: +${summary.current_total_watch_hits} focos (total ${summary.current_total_combined_hits}/${summary.total_positives})`
                  : `Moderate Watch: +${summary.current_total_watch_hits} fires (total ${summary.current_total_combined_hits}/${summary.total_positives})`}
              </span>
            )}
          <div className="inline-flex rounded-lg border border-space-border bg-space-elevated p-0.5 font-mono text-[11px]">
            <button
              type="button"
              onClick={() => setMetric('false_alarms')}
              className={`rounded-md px-2 py-1 transition ${
                metric === 'false_alarms'
                  ? 'bg-space-surface text-fcText-primary shadow-sm'
                  : 'text-fcText-secondary hover:text-fcText-primary'
              }`}
            >
              {isEs ? 'Falsas alarmas' : 'False alarms'}
            </button>
            <button
              type="button"
              onClick={() => setMetric('hits')}
              className={`rounded-md px-2 py-1 transition ${
                metric === 'hits'
                  ? 'bg-space-surface text-fcText-primary shadow-sm'
                  : 'text-fcText-secondary hover:text-fcText-primary'
              }`}
            >
              {isEs ? 'Aciertos' : 'Hits'}
            </button>
          </div>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 font-mono text-[11px] text-fcText-secondary">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm bg-[#FF9C55]/85" />
          {isEs ? 'Anterior (Moderado+ 0.1% / 1% / 5%)' : 'Previous (Moderate+ 0.1% / 1% / 5%)'}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm bg-lime-brand" />
          {isEs ? 'Actual (Alerta Alto+ 0.05% / 0.4%)' : 'Current (High+ Alert 0.05% / 0.4%)'}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-7 lg:grid-cols-14">
        {ordered.map((d) => {
          const prevVal = metric === 'false_alarms' ? d.previous.false_alarms_count : d.previous.hits_count;
          const currVal = metric === 'false_alarms' ? d.current.false_alarms_count : d.current.hits_count;
          const prevH = Math.max(4, Math.round((prevVal / maxVal) * 84));
          const currH = Math.max(4, Math.round((currVal / maxVal) * 84));
          const isSelected = d.target_date === selectedDate;
          return (
            <button
              key={d.target_date}
              type="button"
              onClick={() => onSelectDate(d.target_date)}
              title={`${d.target_date}: ${prevVal} → ${currVal}`}
              className={`flex flex-col items-center rounded-xl border px-1.5 py-2 transition ${
                isSelected
                  ? 'border-lime-brand/60 bg-space-elevated'
                  : 'border-space-border/60 bg-space-elevated/30 hover:border-space-border'
              }`}
            >
              <div className="flex h-24 w-full items-end justify-center gap-1">
                <div className="flex flex-col items-center">
                  <span className="mb-1 font-mono text-[9px] text-[#FF9C55]">{prevVal}</span>
                  <div
                    className="w-3 rounded-t bg-[#FF9C55]/85 transition-all"
                    style={{ height: `${prevH}px` }}
                  />
                </div>
                <div className="flex flex-col items-center">
                  <span className="mb-1 font-mono text-[9px] text-lime-brand">{currVal}</span>
                  <div
                    className="w-3 rounded-t bg-lime-brand transition-all"
                    style={{ height: `${currH}px` }}
                  />
                </div>
              </div>
              <span className="mt-1.5 font-mono text-[10px] text-fcText-secondary">
                {d.target_date.slice(5)}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function StockComparisonLineChart({
  data,
  selectedDate,
  onSelectDate,
  isEs,
}: {
  data: ThresholdComparisonResponse;
  selectedDate: string;
  onSelectDate: (date: string) => void;
  isEs: boolean;
}) {
  const [mode, setMode] = useState<'hits' | 'alerts_log'>('hits');
  const [hoveredDate, setHoveredDate] = useState<string | null>(null);

  const ordered = [...data.items].reverse();
  const focusDate = hoveredDate ?? selectedDate;
  const focusedItem = ordered.find((d) => d.target_date === focusDate) ?? ordered[ordered.length - 1];

  const width = 720;
  const height = 230;
  const padLeft = 48;
  const padRight = 20;
  const padTop = 16;
  const padBottom = 30;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  const getSeries = (d: ThresholdComparisonResponse['items'][number]) =>
    mode === 'hits'
      ? { viirs: d.n_positives, prev: d.previous.hits_count, curr: d.current.hits_count }
      : { viirs: d.n_positives, prev: d.previous.alerts_count, curr: d.current.alerts_count };

  const allVals = ordered.flatMap((d) => {
    const s = getSeries(d);
    return [s.viirs, s.prev, s.curr];
  });
  const rawMax = Math.max(1, ...allVals);
  const maxY = mode === 'hits' ? Math.max(4, rawMax) : Math.max(100, rawMax);

  const xAt = (i: number) =>
    ordered.length <= 1 ? padLeft + plotW / 2 : padLeft + (i / (ordered.length - 1)) * plotW;

  const yAt = (v: number) => {
    const ratio =
      mode === 'hits'
        ? Math.max(0, v) / maxY
        : Math.log10(Math.max(0, v) + 1) / Math.log10(maxY + 1);
    return padTop + plotH * (1 - Math.min(1, ratio));
  };

  const yTicks =
    mode === 'hits'
      ? [0, Math.round(maxY / 3), Math.round((2 * maxY) / 3), maxY].filter(
          (v, i, arr) => arr.indexOf(v) === i,
        )
      : [0, 10, 100, 1000, 3500].filter((v) => v <= maxY * 1.15);

  const buildPolyline = (pick: (d: ThresholdComparisonResponse['items'][number]) => number) =>
    ordered.map((d, i) => `${xAt(i).toFixed(1)},${yAt(pick(d)).toFixed(1)}`).join(' ');

  const viirsPoints = buildPolyline((d) => getSeries(d).viirs);
  const prevPoints = buildPolyline((d) => getSeries(d).prev);
  const currPoints = buildPolyline((d) => getSeries(d).curr);

  const viirsArea =
    ordered.length > 1
      ? `${xAt(0).toFixed(1)},${(padTop + plotH).toFixed(1)} ${viirsPoints} ${xAt(ordered.length - 1).toFixed(1)},${(padTop + plotH).toFixed(1)}`
      : '';

  const focusedIdx = Math.max(
    0,
    ordered.findIndex((d) => d.target_date === focusedItem.target_date),
  );
  const focusedSeries = getSeries(focusedItem);

  return (
    <section
      className="rounded-2xl border border-space-border bg-space-surface p-4 sm:p-5"
      aria-label={
        isEs
          ? 'Gráfico lineal comparativo: VIIRS real vs. modelo previo y actual (Alerta Alto+)'
          : 'Comparative line chart: Real VIIRS vs. previous and current (High+ Alert)'
      }
      role="img"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-title text-sm font-bold text-fcText-primary">
            {isEs
              ? 'Serie temporal: VIIRS real vs. Modelo previo y Actual (Alerta Alto+)'
              : 'Time series: Real VIIRS vs. Previous and Current (High+ Alert)'}
          </h2>
          <p className="mt-0.5 text-xs text-fcText-secondary">
            {isEs
              ? 'Seguimiento diario estilo acciones entre incendios reales (VIIRS), modelo previo y alerta accionable actual (Alto+).'
              : 'Stock-style daily tracking across real fires (VIIRS), previous profile, and current actionable alerts (High+).'}
          </p>
        </div>

        <div className="inline-flex rounded-lg border border-space-border bg-space-elevated p-0.5 font-mono text-[11px]">
          <button
            type="button"
            onClick={() => setMode('hits')}
            className={`rounded-md px-2.5 py-1 transition ${
              mode === 'hits'
                ? 'bg-space-surface text-fcText-primary shadow-sm'
                : 'text-fcText-secondary hover:text-fcText-primary'
            }`}
          >
            {isEs ? 'Aciertos vs. VIIRS' : 'Hits vs. VIIRS'}
          </button>
          <button
            type="button"
            onClick={() => setMode('alerts_log')}
            className={`rounded-md px-2.5 py-1 transition ${
              mode === 'alerts_log'
                ? 'bg-space-surface text-fcText-primary shadow-sm'
                : 'text-fcText-secondary hover:text-fcText-primary'
            }`}
          >
            {isEs ? 'Alertas vs. VIIRS (log)' : 'Alerts vs. VIIRS (log)'}
          </button>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-space-border/70 bg-space-elevated/40 px-3 py-2 font-mono text-xs">
        <div className="flex flex-wrap items-center gap-4">
          <span className="font-semibold text-fcText-primary">{focusedItem.target_date}</span>
          <span className="inline-flex items-center gap-1.5 text-[#C084FC]">
            <span className="h-2 w-2 rounded-full bg-[#A855F7]" />
            {isEs ? 'VIIRS real' : 'Real VIIRS'}: <strong>{focusedSeries.viirs}</strong>
          </span>
          <span className="inline-flex items-center gap-1.5 text-[#FF6759]">
            <span className="h-2 w-2 rounded-full bg-[#FF6759]" />
            {isEs ? 'Modelo previo' : 'Previous model'}: <strong>{focusedSeries.prev}</strong>
          </span>
          <span className="inline-flex items-center gap-1.5 text-lime-brand">
            <span className="h-2 w-2 rounded-full bg-lime-brand" />
            {isEs ? 'Actual (Alerta Alto+)' : 'Current (High+ Alert)'}: <strong>{focusedSeries.curr}</strong>
            {mode === 'hits' &&
              focusedItem.current.watch_hits_count !== undefined &&
              focusedItem.current.watch_hits_count > 0 && (
                <span className="text-[11px] text-[#68D9D0]">
                  (+{focusedItem.current.watch_hits_count} {isEs ? 'vig.' : 'watch'})
                </span>
              )}
          </span>
        </div>
        {mode === 'alerts_log' && (
          <span className="text-[11px] text-fcText-secondary">
            {isEs ? 'Escala logarítmica' : 'Logarithmic scale'}
          </span>
        )}
      </div>

      <div className="mt-3 w-full overflow-x-auto">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-56 w-full min-w-[420px] select-none"
          onMouseLeave={() => setHoveredDate(null)}
        >
          {yTicks.map((tick) => {
            const y = yAt(tick);
            return (
              <g key={tick}>
                <line
                  x1={padLeft}
                  y1={y}
                  x2={width - padRight}
                  y2={y}
                  stroke="rgba(148, 163, 184, 0.16)"
                  strokeDasharray="3 3"
                />
                <text
                  x={padLeft - 8}
                  y={y + 3}
                  textAnchor="end"
                  fill="#94A3B8"
                  fontSize="10"
                  fontFamily="monospace"
                >
                  {tick}
                </text>
              </g>
            );
          })}

          <line
            x1={xAt(focusedIdx)}
            y1={padTop}
            x2={xAt(focusedIdx)}
            y2={padTop + plotH}
            stroke="rgba(184, 238, 104, 0.35)"
            strokeDasharray="4 3"
          />

          {viirsArea && <polygon points={viirsArea} fill="#A855F7" fillOpacity="0.09" />}

          {ordered.length > 1 && (
            <>
              <polyline
                fill="none"
                stroke="#A855F7"
                strokeWidth="2.5"
                strokeLinejoin="round"
                strokeLinecap="round"
                points={viirsPoints}
              />
              <polyline
                fill="none"
                stroke="#FF6759"
                strokeWidth="2.2"
                strokeLinejoin="round"
                strokeLinecap="round"
                points={prevPoints}
              />
              <polyline
                fill="none"
                stroke="#B8EE68"
                strokeWidth="2.5"
                strokeLinejoin="round"
                strokeLinecap="round"
                points={currPoints}
              />
            </>
          )}

          {ordered.map((d, i) => {
            const s = getSeries(d);
            const cx = xAt(i);
            const colW = ordered.length <= 1 ? plotW : plotW / ordered.length;
            const isFocus = d.target_date === focusedItem.target_date;
            return (
              <g key={d.target_date}>
                <circle cx={cx} cy={yAt(s.viirs)} r={isFocus ? 4.5 : 3.2} fill="#A855F7" />
                <circle cx={cx} cy={yAt(s.prev)} r={isFocus ? 4.2 : 3} fill="#FF6759" />
                <circle cx={cx} cy={yAt(s.curr)} r={isFocus ? 4.5 : 3.2} fill="#B8EE68" />
                <text
                  x={cx}
                  y={height - 8}
                  textAnchor="middle"
                  fill={isFocus ? '#F8FAFC' : '#94A3B8'}
                  fontSize="10"
                  fontFamily="monospace"
                  fontWeight={isFocus ? 'bold' : 'normal'}
                >
                  {d.target_date.slice(5)}
                </text>
                <rect
                  x={cx - colW / 2}
                  y={padTop}
                  width={Math.max(colW, 20)}
                  height={plotH + padBottom}
                  fill="transparent"
                  className="cursor-pointer"
                  onMouseEnter={() => setHoveredDate(d.target_date)}
                  onClick={() => onSelectDate(d.target_date)}
                />
              </g>
            );
          })}
        </svg>
      </div>
    </section>
  );
}
