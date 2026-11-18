import '@testing-library/jest-dom/vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MonitorDashboard } from '../src/components/MonitorDashboard';
import type { MonitorMetricItem } from '../src/api/monitor';

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

describe('MonitorDashboard', () => {
  it('renders separate dashboard metrics and category breakdown', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes('/api/v1/monitor/metrics')) {
        return new Response(JSON.stringify({ items: [SAMPLE_ITEM] }), { status: 200 });
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
    expect(screen.getByText(/Desglose por categoría/i)).toBeInTheDocument();

    fetchSpy.mockRestore();
  });
});
