# FHIPredict OpenSpec Workspace

`openspec/` is the single source of truth for **Spec-Driven Development (SDD)** across all development machines working on `FHIPredict-post-hackathon`.

## Multi-Machine Workflow

Follow this sequence whenever switching machines or starting a task:

1. **Pull latest state**
   ```bash
   git pull --ff-only origin main
   ```
   *(If updating the live `DonWeb1` production clone, preserve and restore `backend/models/.forecast_cache.joblib` around the pull.)*
2. **Read living specs (`openspec/specs/`)**
   Review [openspec/config.yaml](config.yaml) and every domain spec affected by the task before editing code.
3. **Propose or update change (`openspec/changes/<name>/` or affected spec)**
   - For multi-step features or contract changes: create `openspec/changes/<change-name>/` containing `proposal.md`, delta spec(s) (`specs/<domain>/spec.md`), and `tasks.md`.
   - For small, self-contained fixes: update the affected `openspec/specs/<domain>/spec.md` directly in the same unit of work.
4. **Implement and test**
   Write code and tests together, then run the full checks:
   ```powershell
   # Backend (33 tests across 7 files baseline)
   cd backend && .\.venv\Scripts\python.exe -m pytest -q

   # Frontend (9 tests across 5 files baseline)
   cd frontend && npm run typecheck && npm test && npm run build
   ```
5. **Merge into `openspec/specs/`**
   Promote approved requirements and `#### Scenario:` blocks from `openspec/changes/<change-name>/` into `openspec/specs/<domain>/spec.md`, remove the completed change directory (keeping `openspec/changes/.gitkeep`), and update `specs/03-tasks.md` if adding a major milestone.
6. **Commit and push**
   Commit specs, implementation, and tests together using Conventional Commits (`feat(...)`, `fix(...)`, `docs(...)`) and push to `origin` so other machines pull a synchronized specification and codebase.

## Domain Specs Index

| Domain | Spec Path | Covers |
|---|---|---|
| Fire Risk Forecast | [openspec/specs/fire-risk-forecast/spec.md](specs/fire-risk-forecast/spec.md) | `lgbm-risk-24h-v2`, Open-Meteo ingestion, VIIRS fire-memory blending, disk/TTL cache, daily-percentile cutoffs, heuristic confidence, `/api/v1/health`, `/api/v1/forecast`. |
| Spatial Spread | [openspec/specs/spatial-spread/spec.md](specs/spatial-spread/spec.md) | `lgbm-spread-v2`, 8-neighbor graph, directional wind coupling, source selection cutoff alignment (`meta.source_cutoff`), probability fusion, static target categorization, `/api/v1/spread`. |
| VIIRS Monitor | [openspec/specs/viirs-monitor/spec.md](specs/viirs-monitor/spec.md) | `SnapshotStore`, NASA FIRMS CSV client & `ViirsStore`, pure-NumPy evaluator (`ROC-AUC`, `PR-AUC`, `Brier`, outcomes), `/api/v1/monitor/*`, `256MB` DuckDB limits. |
| Frontend UI | [openspec/specs/frontend-ui/spec.md](specs/frontend-ui/spec.md) | FuegoContinuo design system, `/` MapLibre risk & spread UI (`TimeRangeBar`, `NavigationPanel`, `RiskLegend`, popups), `/monitor` dashboard, CSV export, ES/EN i18n. |
| Deployment | [openspec/specs/deployment/spec.md](specs/deployment/spec.md) | Multi-stage `Dockerfile`, GHCR CI/CD (`.github/workflows/deploy.yml`), native `DonWeb1` `systemd` topology, 1 GB RAM constraints, env-var secret hygiene. |

## Related Reference Docs

- Consolidated baseline specs: [specs/01-spec.md](../specs/01-spec.md), [specs/02-architecture.md](../specs/02-architecture.md), [specs/03-tasks.md](../specs/03-tasks.md), [specs/04-propagation-proposal.md](../specs/04-propagation-proposal.md), [specs/05-comparison-results.md](../specs/05-comparison-results.md).
- Spanish onboarding & operations walkthrough: [documentacion del proyecto/00-indice.md](../documentacion%20del%20proyecto/00-indice.md).
