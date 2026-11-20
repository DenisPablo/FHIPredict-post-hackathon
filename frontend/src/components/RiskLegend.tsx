import { COPY, type Lang } from '../i18n';
import type { RiskCategory, RiskCutoffsMeta } from '../api/forecast';

const STATIC_CUTOFFS = {
  Extremo: 0.05785066,
  Alto: 0.01292018,
  Moderado: 0.00354965,
};

const RISK_META: { key: RiskCategory; color: string }[] = [
  { key: 'Extremo', color: '#FF6759' },
  { key: 'Alto', color: '#FF9C55' },
  { key: 'Moderado', color: '#68D9D0' },
  { key: 'Bajo', color: '#3D786E' },
];

export function RiskLegend({ lang, cutoffs }: { lang: Lang; cutoffs?: RiskCutoffsMeta }) {
  const t = COPY[lang];
  const c = cutoffs ?? STATIC_CUTOFFS;
  const fmt = (p: number) => (p * 100).toFixed(2);
  const ranges: Record<RiskCategory, string> = {
    Extremo: `≥ ${fmt(c.Extremo)}%`,
    Alto: `${fmt(c.Alto)} – ${fmt(c.Extremo)}%`,
    Moderado: `${fmt(c.Moderado)} – ${fmt(c.Alto)}%`,
    Bajo: `< ${fmt(c.Moderado)}%`,
  };

  return (
    <aside
      aria-label={t.legendTitle}
      className="pointer-events-auto max-w-[260px] rounded-2xl border border-space-border bg-space-surface/95 px-3.5 py-2.5 shadow-xl backdrop-blur-md"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="font-mono text-[10px] uppercase tracking-wider text-fcText-secondary">
          {t.legendTitle}
        </p>
        <span className="rounded-full border border-[#FF9C55]/40 bg-[#FF9C55]/10 px-2 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-wide text-[#FF9C55]">
          {t.demoBadge}
        </span>
      </div>
      {cutoffs?.mode === 'daily_percentile' && (
        <p className="mb-2 font-mono text-[10px] text-fcText-muted">
          {t.legendDailyPercentileNote}
        </p>
      )}
      <ul className="space-y-1.5">
        {RISK_META.map((item) => (
          <li key={item.key} className="flex items-center justify-between gap-4 text-xs">
            <span className="inline-flex items-center gap-2 text-fcText-primary">
              <span
                className="h-2.5 w-2.5 rounded-full ring-1 ring-space-base"
                style={{ backgroundColor: item.color }}
              />
              {t.categories[item.key]}
            </span>
            <span className="font-mono text-[11px] text-fcText-secondary">{ranges[item.key]}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2.5 border-t border-space-border pt-2 text-[10px] leading-relaxed text-fcText-muted">
        {t.disclaimer}
      </p>
    </aside>
  );
}
