# Spec: Build, Runtime Constraints & Deployment (`deployment`)

## Scope
Defines the multi-stage container build, GitHub Actions GHCR CI/CD pipeline, native `systemd` production deployment on `DonWeb1` VPS, 1 GB RAM memory constraints, SPA static serving rules, and secret management hygiene.

Primary implementation files:
- `Dockerfile`
- `.github/workflows/deploy.yml`
- `backend/app/main.py`
- `backend/app/config.py`
- `backend/pyproject.toml`

---

## Requirements

### Requirement DEP-1: Multi-Stage Docker Image & GHCR CI/CD
`Dockerfile` SHALL build the Vite/React frontend in Stage 1 (`node:20-alpine` -> `dist/`) and run FastAPI in Stage 2 (`python:3.12-slim` with `libgomp1` for LightGBM, `STATIC_DIR=/app/static`, `MODELS_DIR=/app/models`, port `8000`, and `HEALTHCHECK` against `http://127.0.0.1:8000/api/v1/health`).
`.github/workflows/deploy.yml` MUST build and push `ghcr.io/<owner>/fhipredict:latest` on pushes to `main` or `workflow_dispatch`. When repository variable `ENABLE_VPS_DEPLOY == 'true'`, the `deploy` job SHALL deploy over SSH using GitHub Secrets, mounting `/opt/fhipredict/monitor_data:/app/monitor_data`, enforcing `--memory="850m"`, writing `/opt/fhipredict/.env` (`chmod 600`), and exposing port `80:8000`.

#### Scenario: Docker image passes healthcheck and serves SPA + API
- **GIVEN** a built container image from `Dockerfile`
- **WHEN** the container starts with `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- **THEN** `GET /api/v1/health` MUST respond with HTTP `200` within healthcheck grace period and unmatched non-API paths MUST serve `STATIC_DIR/index.html`.

---

### Requirement DEP-2: Native `systemd` Production Topology (`DonWeb1` VPS)
Production deployment on `DonWeb1` (~1 GB RAM + 1 GB swap Ubuntu VPS) SHALL support running natively via `systemd` (`fhipredict.service`) without Docker or Node installed on the server, using:
- Application clone in `/opt/fhipredict/app` (`main` branch)
- Isolated Python virtualenv in `/opt/fhipredict/venv`
- Prebuilt frontend assets in `/opt/fhipredict/static` (`STATIC_DIR`)
- Runtime environment configuration in `/opt/fhipredict/.env` (`STATIC_DIR`, `MODELS_DIR`, `MONITOR_DIR`, `FIRMS_MAP_KEY`)
- Persistent DuckDB database in `/opt/fhipredict/monitor_data/monitor.duckdb`

Because the live process periodically rewrites `backend/models/.forecast_cache.joblib`, production pulls on `DonWeb1` MUST back up `.forecast_cache.joblib`, reset tracked changes before `git pull --ff-only origin main`, restore `.forecast_cache.joblib`, restart `fhipredict.service` without altering `.env` or `monitor.duckdb`, and verify `GET /api/v1/health` and `GET /api/v1/spread`.

#### Scenario: Live server update preserves forecast cache and DuckDB monitor history
- **GIVEN** a running `DonWeb1` instance with updated `backend/models/.forecast_cache.joblib` and accumulated rows in `monitor.duckdb`
- **WHEN** an operator deploys a new `main` commit via SSH
- **THEN** `.forecast_cache.joblib` MUST be backed up and restored around `git pull --ff-only origin main`
- **AND** `.env` and `monitor.duckdb` MUST remain untouched across `systemctl restart fhipredict.service`.

---

### Requirement DEP-3: 1 GB RAM Budget & SPA Fallback Security
Default runtime configuration MUST keep memory consumption safe on 1 GB RAM hosts:
- `MONITOR_DUCKDB_MEMORY_LIMIT="256MB"` with `threads=1` on every DuckDB connection (`snapshots.py`, `firms.py`, `evaluator.py`).
- `CHUNK_SIZE=100` and `MAX_CONCURRENCY=1` for Open-Meteo batch fetching.
- Static SPA serving in `backend/app/main.py` MUST validate `candidate.is_relative_to(static_root)` to prevent path traversal and MUST return HTTP `404` for any unmatched `api/*` path rather than falling back to `index.html`.

#### Scenario: Unknown API route returns 404 even when SPA static serving is enabled
- **GIVEN** `STATIC_DIR` points to a built frontend bundle
- **WHEN** a client requests `GET /api/v1/nonexistent` vs `GET /monitor`
- **THEN** `/api/v1/nonexistent` MUST return HTTP `404` while `/monitor` MUST serve `index.html`.

---

### Requirement DEP-4: Secret & Credential Hygiene
All sensitive values (`FIRMS_MAP_KEY`, SSH host/user/private keys, registry tokens) MUST be provided strictly via environment variables, local `.env` files (gitignored), or GitHub Actions Secrets. No secret values, tokens, passwords, or SSH keys SHALL ever be committed to Git or placed inside documentation/specification files.
