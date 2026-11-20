import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RiskLegend } from '../src/components/RiskLegend';

describe('RiskLegend', () => {
  it('renders static fallback cutoffs when cutoffs prop is omitted', () => {
    render(<RiskLegend lang="es" />);

    expect(screen.getByText('≥ 5.79%')).toBeTruthy();
    expect(screen.getByText('1.29 – 5.79%')).toBeTruthy();
    expect(screen.getByText('0.35 – 1.29%')).toBeTruthy();
    expect(screen.getByText('< 0.35%')).toBeTruthy();
    expect(screen.queryByText(/percentil diario/i)).toBeNull();
  });

  it('renders dynamic daily percentile cutoffs and note when active', () => {
    render(
      <RiskLegend
        lang="es"
        cutoffs={{
          mode: 'daily_percentile',
          Extremo: 0.010208,
          Alto: 0.002737,
          Moderado: 0.001113,
        }}
      />,
    );

    expect(screen.getByText('≥ 1.02%')).toBeTruthy();
    expect(screen.getByText('0.27 – 1.02%')).toBeTruthy();
    expect(screen.getByText('0.11 – 0.27%')).toBeTruthy();
    expect(screen.getByText('< 0.11%')).toBeTruthy();
    expect(screen.getByText('Umbral por percentil diario (top 5% / 1% / 0.1%)')).toBeTruthy();
  });
});
