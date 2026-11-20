export type RiskCategory = 'Bajo' | 'Moderado' | 'Alto' | 'Extremo';
export type ConfidenceLevel = 'Alta' | 'Media' | 'Baja';

export interface CellProperties {
  cell_id: number;
  riesgo_pct: number;
  categoria: RiskCategory;
  confianza_pct?: number;
  confianza_nivel?: ConfidenceLevel;
  tmax_c: number;
  rh_pct: number;
  wind_kmh: number;
  rain_mm: number;
  rain_30d_mm?: number;
  dry_days: number;
  vpd_kpa?: number;
  elev_m?: number;
  years_since_fire?: number;
}

export interface ForecastFeature {
  type: 'Feature';
  geometry: {
    type: 'Point';
    coordinates: [number, number];
  };
  properties: CellProperties;
}

export interface RiskCutoffsMeta {
  mode: 'daily_percentile' | 'static';
  Extremo: number;
  Alto: number;
  Moderado: number;
}

export interface ForecastResponse {
  type: 'FeatureCollection';
  meta: {
    model_version: string;
    generated_at: string;
    mode: 'window' | 'day';
    fecha_desde: string;
    fecha_hasta: string;
    dates_available: string[];
    counts: Record<RiskCategory, number>;
    cutoffs?: RiskCutoffsMeta;
    returned: number;
  };
  features: ForecastFeature[];
}

export interface ForecastQuery {
  mode: 'window' | 'day';
  days: number;
  dayOffset: number;
  minRisk: RiskCategory;
  refresh?: boolean;
}

export async function fetchForecast(q: ForecastQuery, signal?: AbortSignal): Promise<ForecastResponse> {
  const params = new URLSearchParams({
    mode: q.mode,
    days: String(q.days),
    day_offset: String(q.dayOffset),
    min_risk: q.minRisk,
  });
  if (q.refresh) params.set('refresh', 'true');

  const res = await fetch(`/api/v1/forecast?${params.toString()}`, { signal });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `API error (${res.status})`);
  }
  return res.json() as Promise<ForecastResponse>;
}

export type SpreadHorizonHours = 24 | 48 | 72;

export interface SpreadProperties {
  cell_id: number;
  propagacion_pct: number;
  riesgo_base_pct: number;
  riesgo_fusionado_pct: number;
  categoria: RiskCategory;
  confianza_pct?: number;
  confianza_nivel?: ConfidenceLevel;
  horizon_hours: number;
}

export interface SpreadFeature {
  type: 'Feature';
  geometry: {
    type: 'Point';
    coordinates: [number, number];
  };
  properties: SpreadProperties;
}

export interface SpreadResponse {
  type: 'FeatureCollection';
  meta: {
    model_version: string;
    baseline_model_version: string;
    generated_at: string;
    horizon_hours: number;
    fecha_desde: string;
    fecha_hasta: string;
    active_source_cells: number;
    counts: Record<RiskCategory, number>;
    returned: number;
  };
  features: SpreadFeature[];
}

export interface SpreadQuery {
  horizonHours: SpreadHorizonHours;
  dayOffset: number;
  minRisk: RiskCategory;
  refresh?: boolean;
}

export async function fetchSpread(q: SpreadQuery, signal?: AbortSignal): Promise<SpreadResponse> {
  const params = new URLSearchParams({
    horizon_hours: String(q.horizonHours),
    day_offset: String(q.dayOffset),
    min_risk: q.minRisk,
  });
  if (q.refresh) params.set('refresh', 'true');

  const res = await fetch(`/api/v1/spread?${params.toString()}`, { signal });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `API error (${res.status})`);
  }
  return res.json() as Promise<SpreadResponse>;
}
