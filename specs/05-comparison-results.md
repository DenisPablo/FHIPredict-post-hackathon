# Comparative Benchmark Results — `lgbm-risk-24h-v2` vs `lgbm-spread-v1` vs `lgbm-spread-v2`

- **Generated at**: `2026-11-15T19:54:14.041765+00:00`
- **Status**: **Merged to `main` & enabled by default** (`lgbm-spread-v2` active on `/api/v1/spread`)
- **Historical Benchmark Gate**: **REVIEW** (Offline benchmark threshold was ≥ +20% relative PR-AUC on Track B; observed `+11.01%` vs `v2`, `+4.47%` vs `spread-v1`, and `+34.68%` vs naive baseline; fused `v2 + spread-v2` achieved best per-horizon PR-AUC across 24h/48h/72h)

## 1. Model Overview & Global Baseline Reference (Track A)

| Model | Role | Horizons | Features | Val PR-AUC | Test PR-AUC | Test ROC-AUC |
|---|---|---|---:|---:|---:|---:|
| `lgbm-risk-24h-v2` | Global cell-day ignition risk | 24h | 20 | 0.0691 | 0.0785 | 0.9196 |
| `lgbm-spread-v1` | Conditional 8-neighbor propagation (v1) | 24h, 48h, 72h | 32 | 0.2919 | 0.3948 | 0.8751 |
| `lgbm-spread-v2` | Conditional 8-neighbor propagation + Fuel + Wind + Industrial filter | 24h, 48h, 72h | 47 | **0.3040** | **0.4114** | **0.8759** |

## 2. Track B — Conditional Neighbor Propagation (Unseen 2026 Holdout, All Horizons)

| Model | PR-AUC | ROC-AUC | Brier | Log-Loss | Calibration Ratio | Top-1% Precision | Top-1% Recall | Top-1% Lift |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `lgbm-spread-v2` (Fuel + Wind + Ind) | **0.4125** | 0.8760 | 0.0328 | 0.1275 | 0.879 | 0.7344 | 0.1667 | 16.66x |
| `v2 + spread-v2` (Fused Ensemble) | **0.4084** | 0.8740 | 0.0329 | 0.1279 | 1.156 | 0.7380 | 0.1675 | 16.74x |
| `lgbm-spread-v1` (Initial Spread) | **0.3948** | 0.8751 | 0.0333 | 0.1286 | 0.872 | 0.6968 | 0.1583 | 15.81x |
| `lgbm-risk-24h-v2` (Scaled to H) | **0.3716** | 0.8276 | 0.0340 | 0.1507 | 0.616 | 0.7091 | 0.1609 | 16.09x |
| Naive Spatial Heuristic | **0.3063** | 0.8060 | 0.0367 | 0.1481 | 0.971 | 0.5952 | 0.1351 | 13.50x |

## 3. Breakdown by Propagation Horizon (24h vs 48h vs 72h — 2026 Holdout)

| Horizon | Base Rate | `lgbm-spread-v2` PR-AUC | `v2 + spread-v2` PR-AUC | `lgbm-spread-v1` PR-AUC | `lgbm-risk-24h-v2` PR-AUC | Gain `spread-v2` vs `v2` | Gain `spread-v2` vs `v1` | `spread-v2` ROC-AUC |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **24h** | 3.52% | **0.4364** | 0.4443 | 0.4164 | 0.4084 | **+6.8%** | **+4.8%** | 0.8942 |
| **48h** | 4.54% | **0.4077** | 0.4155 | 0.3905 | 0.3875 | **+5.2%** | **+4.4%** | 0.8716 |
| **72h** | 5.16% | **0.4030** | 0.4082 | 0.3863 | 0.3815 | **+5.6%** | **+4.3%** | 0.8612 |

## 4. Validation Split Summary (2024–2025)

| Model | Val PR-AUC | Val ROC-AUC | Val Brier | Val Top-1% Lift |
|---|---:|---:|---:|---:|
| `lgbm-spread-v2` | **0.3041** | 0.8358 | 0.0416 | 11.69x |
| `v2 + spread-v2` (Fused) | 0.2875 | 0.8329 | 0.0441 | 10.81x |
| `lgbm-spread-v1` | 0.2919 | 0.8341 | 0.0419 | 11.21x |
| `lgbm-risk-24h-v2` (Scaled) | 0.2567 | 0.7971 | 0.0439 | 9.90x |
| Naive Spatial Heuristic | 0.2107 | 0.7597 | 0.0452 | 8.35x |

## 5. Inference Throughput Benchmark

- **Test candidate pairs evaluated**: `65,078`
- **`lgbm-spread-v2` latency**: `0.2146 s` (`303,253 rows/s`)
- **`lgbm-risk-24h-v2` latency**: `0.3212 s` (`202,589 rows/s`)
