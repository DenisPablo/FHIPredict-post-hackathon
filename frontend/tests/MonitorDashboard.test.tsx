import '@testing-library/jest-dom/vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MonitorDashboard } from '../src/components/MonitorDashboard';
import { buildMonitorCsv, type MonitorMetricItem, type ThresholdComparisonResponse } from '../src/api/monitor';

const SAMPLE_ITEM: MonitorMetricItem = {
  target_date: '2026-11-18',
  issued_date: '2026-11-18',
  min_frp_mw: 10,
  n_cells: 64653,
  n_positives: 12,
  observed_rate: 0.00018,
  mean_predicted_prob: 0.0002,
  calibration_ratio: 1.08,
  brier_score: 0.0002,
  roc_auc: 0.912,
  pr_auc: 0.145,
  hits_count: 8,
  misses_count: 4,
  false_alarms_count: 120,
  categories: {
    Extremo: { cells_count: 50, positives_count: 5, precision: 0.1, recall: 0.41, lift: 500 },
    Alto: { cells_count: 78, positives_count: 3, precision: 0.038, recall: 0.25, lift: 200 },
    Moderado: { cells_count: 500, positives_count: 2, precision: 0.004, recall: 0.16, lift: 20 },
    Bajo: { cells_count: 64025, positives_count: 2, precision: 0.00003, recall: 0.16, lift: 0.16 },
  },
  evaluated_at: '2026-11-18T15:00:00+00:00',
};

const SAMPLE_COMPARISON: ThresholdComparisonResponse = {
  profiles: {
    previous: { label: 'previous_0.1_1_5pct' },
    current: { label: 'current_2B_selective' },
  },
  summary: {
    days_compared: 1,
    total_positives: 12,
    previous_total_hits: 8,
    current_total_hits: 6,
    previous_total_false_alarms: 3200,
    current_total_false_alarms: 544,
    false_alarm_reduction_pct: 83.0,
  },
  items: [
    {
      target_date: '2026-11-18',
      issued_date: '2026-11-18',
      n_positives: 12,
      previous: {
        alerts_count: 3208,
        hits_count: 8,
        misses_count: 4,
        false_alarms_count: 3200,
        capture_rate: 8 / 12,
        precision: 8 / 3208,
        cutoffs: { Extremo: 0.01, Alto: 0.003, Moderado: 0.001 },
      },
      current: {
        alerts_count: 550,
        hits_count: 6,
        misses_count: 6,
        false_alarms_count: 544,
        capture_rate: 0.5,
        precision: 6 / 550,
        cutoffs: { Extremo: 0.015, Alto: 0.005, Moderado: 0.002 },
      },
    },
  ],
};

describe('buildMonitorCsv', () => {
  it('formats headers and metric rows cleanly', () => {
    const csv = buildMonitorCsv([SAMPLE_ITEM]);
    const lines = csv.split('\n');
    expect(lines).toHaveLength(2);
    expect(lines[0]).toContain('target_date,issued_date,n_cells,n_positives,expected_positives');
    expect(lines[1]).toContain('2026-11-18,2026-11-18,64653,12,12.93,8,4,66.67,120');
  });
});

describe('MonitorDashboard', () => {
  it('renders plain-language summary, SVG charts, KPI explanations, and enabled CSV button', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes('/api/v1/monitor/metrics')) {
        return new Response(JSON.stringify({ items: [SAMPLE_ITEM] }), { status: 200 });
      }
      if (url.includes('/api/v1/monitor/threshold-comparison')) {
        return new Response(JSON.stringify(SAMPLE_COMPARISON), { status: 200 });
      }
      return new Response(
        JSON.stringify({ running: false, last_run_at: null, last_result: null, last_error: null }),
        { status: 200 },
      );
    });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MonitorDashboard lang="es" onToggleLang={vi.fn()} onBackToMap={vi.fn()} />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getAllByText('0.145').length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.getByText('8 / 4')).toBeInTheDocument();
    expect(screen.getByText('120')).toBeInTheDocument();
    expect(screen.getByText(/¿Cómo leer estos datos\?/i)).toBeInTheDocument();
    expect(screen.getByText(/Resumen en lenguaje simple/i)).toBeInTheDocument();
    expect(screen.getAllByText(/66\.7%/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Desglose por categoría/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Gráfico de captura por nivel de riesgo/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Gráfico de evolución diaria/i)).toBeInTheDocument();

    const csvButton = screen.getByRole('button', { name: /Descargar CSV/i });
    expect(csvButton).toBeEnabled();

    expect(screen.getByText(/Comparación de umbrales: Anterior vs\. Actual \(2B\)/i)).toBeInTheDocument();
    expect(screen.getByText(/-83\.0% falsas alarmas/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Gráfico comparativo de umbrales/i)).toBeInTheDocument();
    expect(screen.getByText('3200')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /^Aciertos$/i }));
    expect(screen.queryByText('3200')).not.toBeInTheDocument();
    expect(screen.getByText('6')).toBeInTheDocument();

    fetchSpy.mockRestore();
  });
});
