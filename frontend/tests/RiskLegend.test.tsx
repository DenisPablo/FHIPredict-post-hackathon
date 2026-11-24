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
          Extremo: 0.015,
          Alto: 0.005,
          Moderado: 0.002,
        }}
      />,
    );

    expect(screen.getByText('≥ 1.50%')).toBeTruthy();
    expect(screen.getByText('0.50 – 1.50%')).toBeTruthy();
    expect(screen.getByText('0.20 – 0.50%')).toBeTruthy();
    expect(screen.getByText('< 0.20%')).toBeTruthy();
    expect(
      screen.getByText('Umbral diario: Alerta Alto+ (top 0.4% / 0.05%) · Vigilancia Moderado (top 2.5%)'),
    ).toBeTruthy();
  });
});
