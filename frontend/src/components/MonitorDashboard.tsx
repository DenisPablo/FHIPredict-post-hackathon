import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, ArrowLeft, Download, Globe, HelpCircle, Loader2, Play } from 'lucide-react';
import {
  buildMonitorCsv,
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
    (item.categories?.Extremo?.cells_count ?? 0) +
    (item.categories?.Alto?.cells_count ?? 0) +
    (item.categories?.Moderado?.cells_count ?? 0);
  const alertSharePct = item.n_cells > 0 ? ((alertCells / item.n_cells) * 100).toFixed(2) : '0.00';
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
        <span className="rounded-full border border-space-border bg-space-elevated px-2.5 py-0.5 font-mono text-[11px] text-fcText-secondary">
          {isEs
            ? `Territorio en alerta: ${alertCells} / ${item.n_cells.toLocaleString('es-AR')} celdas (${alertSharePct}%)`
            : `Alerted territory: ${alertCells} / ${item.n_cells.toLocaleString('en-US')} cells (${alertSharePct}%)`}
        </span>
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
                incendio real en el país. El sistema había puesto en alerta previa al{' '}
                <strong className="text-lime-brand">{capturePct}%</strong> ({item.hits_count} aciertos y{' '}
                {item.misses_count} fuera de alerta) vigilando solo el{' '}
                <strong className="text-fcText-primary">{alertSharePct}%</strong> del territorio.
              </>
            ) : (
              <>
                Satellites detected <strong className="text-fcText-primary">{item.n_positives}</strong> active
                fire zones nationwide. Pre-issued alerts captured{' '}
                <strong className="text-lime-brand">{capturePct}%</strong> ({item.hits_count} hits and{' '}
                {item.misses_count} misses) while monitoring only{' '}
                <strong className="text-fcText-primary">{alertSharePct}%</strong> of the territory.
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
