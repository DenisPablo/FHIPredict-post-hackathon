import { Suspense, lazy, useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity, ExternalLink, Globe, Loader2 } from 'lucide-react';
import { fetchForecast, fetchSpread, type RiskCategory, type SpreadHorizonHours } from './api/forecast';
import type { FlyTarget } from './components/RiskMap';
import { RiskLegend } from './components/RiskLegend';
import { NavigationPanel } from './components/NavigationPanel';
import { TimeRangeBar } from './components/TimeRangeBar';
import { COPY, type Lang } from './i18n';

const RiskMap = lazy(() =>
  import('./components/RiskMap').then((mod) => ({ default: mod.RiskMap })),
);
const MonitorDashboard = lazy(() =>
  import('./components/MonitorDashboard').then((mod) => ({ default: mod.MonitorDashboard })),
);

export function App() {
  const [lang, setLang] = useState<Lang>('es');
  const [mode, setMode] = useState<'window' | 'day'>('window');
  const [days, setDays] = useState<number>(1);
  const [dayOffset, setDayOffset] = useState<number>(0);
  const [minRisk, setMinRisk] = useState<RiskCategory>('Moderado');
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [showSpread, setShowSpread] = useState(true);
  const [spreadHorizon, setSpreadHorizon] = useState<SpreadHorizonHours>(24);
  const [flyTarget, setFlyTarget] = useState<FlyTarget | null>(null);
  const [activeNavId, setActiveNavId] = useState<string>('arg');
  const [pathname, setPathname] = useState<string>(() => window.location.pathname);

  useEffect(() => {
    const onPop = () => setPathname(window.location.pathname);
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  function navigate(to: string) {
    if (window.location.pathname !== to) {
      window.history.pushState({}, '', to);
      setPathname(to);
    }
  }

  const isMonitorRoute = pathname.startsWith('/monitor');

  const t = COPY[lang];
  const locale = lang === 'es' ? 'es-AR' : 'en-US';

  const query = useQuery({
    queryKey: ['forecast', mode, days, dayOffset, minRisk, refreshNonce],
    queryFn: ({ signal }) =>
      fetchForecast(
        {
          mode,
          days,
          dayOffset,
          minRisk,
          refresh: refreshNonce > 0,
        },
        signal,
      ),
    enabled: !isMonitorRoute,
    staleTime: 10 * 60 * 1000,
    placeholderData: (prev) => prev,
  });

  const spreadDayOffset = mode === 'day' ? dayOffset : 0;
  const spreadQuery = useQuery({
    queryKey: ['spread', spreadHorizon, spreadDayOffset, minRisk, refreshNonce],
    queryFn: ({ signal }) =>
      fetchSpread(
        {
          horizonHours: spreadHorizon,
          dayOffset: spreadDayOffset,
          minRisk,
          refresh: refreshNonce > 0,
        },
        signal,
      ),
    enabled: !isMonitorRoute && showSpread,
    staleTime: 10 * 60 * 1000,
    placeholderData: (prev) => prev,
  });

  if (isMonitorRoute) {
    return (
      <Suspense fallback={<div className="min-h-screen bg-space-base" />}>
        <MonitorDashboard
          lang={lang}
          onToggleLang={() => setLang((prev) => (prev === 'es' ? 'en' : 'es'))}
          onBackToMap={() => navigate('/')}
        />
      </Suspense>
    );
  }

  const meta = query.data?.meta;

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-space-base">
      <Suspense fallback={<div className="h-full w-full bg-space-base" />}>
        <RiskMap
          data={query.data}
          spreadData={showSpread ? spreadQuery.data : undefined}
          showSpread={showSpread}
          spreadHorizon={spreadHorizon}
          onToggleSpread={() => setShowSpread((prev) => !prev)}
          onChangeSpreadHorizon={setSpreadHorizon}
          lang={lang}
          flyTarget={flyTarget}
        />
      </Suspense>

      {/* Top floating header */}
      <header className="pointer-events-none absolute inset-x-4 top-4 z-10 flex flex-wrap items-start justify-between gap-3">
        <div className="pointer-events-auto flex items-center gap-3 rounded-2xl border border-space-border bg-space-surface/95 px-4 py-2.5 shadow-xl backdrop-blur-md">
          <img
            src="/logo-fhi.png"
            alt="Fire History Interface"
            className="h-9 w-9 shrink-0 rounded-full object-cover"
          />
          <div>
            <h1 className="font-title text-sm font-extrabold tracking-tight text-fcText-primary">
              {t.title}
            </h1>
            <p className="font-mono text-[11px] text-fcText-secondary">
              {meta ? `${meta.model_version} · Open-Meteo (1–15d)` : t.loadingForecast}
            </p>
          </div>
        </div>

        {/* Summary chips + external link + language toggle */}
        <div className="pointer-events-auto flex flex-wrap items-center gap-2 rounded-2xl border border-space-border bg-space-surface/95 px-3.5 py-2 shadow-xl backdrop-blur-md">
          {(query.isFetching || (showSpread && spreadQuery.isFetching)) && (
            <span className="inline-flex items-center gap-1.5 font-mono text-xs text-lime-brand">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t.calculating}
            </span>
          )}
          {meta && (
            <>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-[#FF6759]/15 px-2.5 py-0.5 font-mono text-xs text-[#FF6759]">
                {t.categories.Extremo}: {meta.counts.Extremo.toLocaleString(locale)}
              </span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-[#FF9C55]/15 px-2.5 py-0.5 font-mono text-xs text-[#FF9C55]">
                {t.categories.Alto}: {meta.counts.Alto.toLocaleString(locale)}
              </span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-[#68D9D0]/15 px-2.5 py-0.5 font-mono text-xs text-[#68D9D0]">
                {t.categories.Moderado}: {meta.counts.Moderado.toLocaleString(locale)}
              </span>
            </>
          )}

          <div className="mx-1 h-4 w-px bg-space-border" />

          <a
            href="/monitor"
            onClick={(e) => {
              e.preventDefault();
              navigate('/monitor');
            }}
            className="inline-flex items-center gap-1.5 rounded-lg border border-space-border bg-space-elevated px-2.5 py-1 font-mono text-xs font-semibold text-fcText-primary hover:border-lime-brand/60 hover:text-lime-brand transition"
          >
            <Activity className="h-3 w-3" />
            Monitor
          </a>

          <a
            href="https://fhi.intercomputacion.com.ar"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg border border-space-border bg-space-elevated px-2.5 py-1 text-xs font-medium text-lime-brand hover:border-lime-brand/60 transition"
          >
            {t.historicalBtn}
            <ExternalLink className="h-3 w-3" />
          </a>

          <button
            type="button"
            onClick={() => setLang((prev) => (prev === 'es' ? 'en' : 'es'))}
            aria-label="Cambiar idioma / Switch language"
            className="inline-flex items-center gap-1 rounded-lg border border-space-border bg-space-elevated px-2.5 py-1 font-mono text-xs font-semibold text-fcText-primary hover:border-space-borderLight transition"
          >
            <Globe className="h-3 w-3 text-fcText-secondary" />
            {lang.toUpperCase()}
          </button>
        </div>
      </header>

      {/* Cold-start notice while initial forecast is being computed */}
      {query.isLoading && !query.data && !query.isError && (
        <div
          role="status"
          aria-live="polite"
          className="pointer-events-none absolute left-1/2 top-1/2 z-20 -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-space-border bg-space-surface/95 px-5 py-4 text-center shadow-2xl backdrop-blur-md max-w-sm"
        >
          <div className="flex items-center justify-center gap-2 font-title text-sm font-bold text-fcText-primary">
            <Loader2 className="h-4 w-4 animate-spin text-lime-brand" />
            <span>{t.firstLoadTitle}</span>
          </div>
          <p className="mt-1.5 text-xs text-fcText-secondary leading-relaxed">
            {t.firstLoadHint}
          </p>
        </div>
      )}

      {/* Error banner */}
      {query.isError && (
        <div className="absolute left-1/2 top-20 z-20 -translate-x-1/2 rounded-xl border border-sensor-high/50 bg-space-surface/95 px-4 py-2 text-xs text-sensor-high shadow-xl">
          {t.fetchError} {(query.error as Error).message}
        </div>
      )}

      {/* Left floating navigable panel (provinces + top risk cells) */}
      <div className="pointer-events-none absolute left-4 top-20 z-10 hidden sm:block">
        <NavigationPanel
          lang={lang}
          features={query.data?.features ?? []}
          activeId={activeNavId}
          onFlyTo={(center, zoom, id) => {
            setActiveNavId(id);
            setFlyTarget((prev) => ({ center, zoom, nonce: (prev?.nonce ?? 0) + 1 }));
          }}
        />
      </div>

      {/* Bottom-right floating risk scale legend */}
      <div className="pointer-events-none absolute bottom-10 right-4 z-10 hidden md:block">
        <RiskLegend lang={lang} cutoffs={meta?.cutoffs} />
      </div>

      {/* Bottom floating time-range bar */}
      <div className="pointer-events-none absolute inset-x-4 bottom-5 z-10 mx-auto max-w-3xl">
        <TimeRangeBar
          lang={lang}
          mode={mode}
          days={days}
          dayOffset={dayOffset}
          minRisk={minRisk}
          datesAvailable={meta?.dates_available ?? []}
          fechaDesde={meta?.fecha_desde}
          fechaHasta={meta?.fecha_hasta}
          isFetching={query.isFetching}
          onSelectWindow={(d) => {
            setMode('window');
            setDays(d);
          }}
          onSelectDay={(offset) => {
            setMode('day');
            setDayOffset(offset);
          }}
          onChangeMinRisk={setMinRisk}
          onRefresh={() => setRefreshNonce((n) => n + 1)}
        />
      </div>
    </div>
  );
}

export default App;
