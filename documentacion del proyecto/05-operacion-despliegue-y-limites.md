# 5. Operación, despliegue y limitaciones reales

Esta guía reúne los comandos reales para trabajar en local, la topología vigente en producción sobre el VPS **DonWeb1** y las limitaciones conocidas del sistema para evitar sorpresas al operar o extender el proyecto.

---

## Ejecución y pruebas en local

### Backend (Python >= 3.12)

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Para correr la suite completa de pruebas automatizadas del backend (`33` tests):

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

### Frontend (Node 20+)

```powershell
cd frontend
npm run dev
```

Abre `http://localhost:5173` para el mapa y `http://localhost:5173/monitor` para el tablero empírico (el proxy de Vite redirige `/api` hacia `http://127.0.0.1:8000`).

Para verificar tipos, ejecutar pruebas unitarias (`9` tests) y compilar producción:

```powershell
cd frontend
npm run typecheck
npm test
npm run build
```

---

## Despliegue actual en producción (`DonWeb1`)

Aunque el repositorio incluye un `Dockerfile` y un flujo de GitHub Actions (`.github/workflows/deploy.yml`) pensado para contenedores, **en producción sobre `DonWeb1` el servicio corre de forma nativa sin Docker ni Node en el servidor**, gestionado por `systemd`.

### Topología del servidor

| Elemento | Ruta / detalle en `DonWeb1` |
|---|---|
| **Acceso** | SSH por Tailscale (`root@100.125.31.84`). VPS Ubuntu con ~1 GB de RAM y 1 GB de swap. |
| **Servicio** | Unidad `fhipredict.service` ejecutando `uvicorn app.main:app --host 0.0.0.0 --port 80`. |
| **Código** | `/opt/fhipredict/app` (clon de la rama `main`). |
| **Entorno Python** | `/opt/fhipredict/venv`. |
| **Frontend compilado** | `/opt/fhipredict/static` (solo hace falta recompilar y subir si cambia código JS/UI en tiempo de ejecución). |
| **Base del monitor** | `/opt/fhipredict/monitor_data/monitor.duckdb`. |
| **Variables de entorno** | `/opt/fhipredict/.env` (`STATIC_DIR`, `MODELS_DIR`, `MONITOR_DIR`, `FIRMS_MAP_KEY`). |

### Regla de oro al actualizar `DonWeb1` por SSH

El servidor en vivo actualiza periódicamente el archivo `backend/models/.forecast_cache.joblib`. Antes de hacer `git pull` en `/opt/fhipredict/app`:

1. Hacer una copia temporal de `.forecast_cache.joblib`.
2. Limpiar el archivo trackeado en git, hacer `git pull --ff-only origin main` y restaurar la copia temporal.
3. Reiniciar `systemctl restart fhipredict.service` (sin tocar `.env` ni `monitor.duckdb`).
4. Verificar `GET /api/v1/health` y `GET /api/v1/spread`.

> [!NOTE]
> Si se trabaja desde Windows y OpenSSH rechaza leer `~/.ssh/config` por permisos ACL del archivo, se puede conectar directo con `ssh -F NUL root@100.125.31.84` (Tailscale SSH puede pedir una aprobación breve en el navegador).

---

## Variables de entorno principales

| Variable | Valor por defecto | Qué controla |
|---|---|---|
| `RISK_CUTOFF_MODE` | `daily_percentile` | Usa percentiles diarios acotados (`daily_percentile`) o umbrales fijos (`static`). |
| `FIRMS_MAP_KEY` | *(vacío)* | Clave de NASA FIRMS necesaria para el monitor VIIRS; si falta, `POST /api/v1/monitor/run` devuelve `400` y el ciclo periódico no corre. |
| `ENABLE_SPREAD` | `True` | Activa el modelo de propagación espacial `lgbm-spread-v2`. |
| `CACHE_TTL_S` / `REFRESH_INTERVAL_S` | `10800` (3h) | Vigencia de la caché en disco y frecuencia de actualización desde Open-Meteo. |
| `MONITOR_REFRESH_INTERVAL_S` | `21600` (6h) | Frecuencia de auditoría automática contra NASA FIRMS VIIRS. |
| `MONITOR_DUCKDB_MEMORY_LIMIT` | `256MB` | Límite de memoria asignado a DuckDB dentro del VPS de 1 GB. |

---

## Limitaciones conocidas y cuidados futuros

Conviene tener presentes estas cinco restricciones reales antes de tomar decisiones sobre el proyecto:

1. **Cobertura geográfica del modelo (`64.653` de `112.711` celdas):** las `48.058` celdas donde nunca se detectaron focos entre 2000 y 2026 quedaron fuera del modelo.
2. **Escala espacial y temporal (5 × 5 km y viento diario):** una celda de 5 km no captura cañadones locales ni micro-topografía, y un único viento dominante diario no refleja rotaciones bruscas de un frente frío hora a hora.
3. **Script de exportación acoplado a rutas locales:** `backend/scripts/export_baseline.py` conserva rutas absolutas de Windows de la máquina original del autor; si alguna vez se regenera `cell_baseline.parquet`, habrá que parametrizar esas rutas.
4. **Rango de días en el monitor:** el endpoint `POST /api/v1/monitor/run` valida `day_range` entre `1` y `10`, mientras que la API de NASA FIRMS acepta entre `1` y `5` días por consulta.
5. **Documentación histórica previa:** algunos documentos antiguos del repositorio (`README.md` y `specs/02-architecture.md`) todavía mencionan conteos viejos de pruebas (`29` y `7`) frente a los actuales (`33` en backend y `9` en frontend).

---

## Checklist de comprensión

- [ ] Sé cómo correr backend, frontend y sus suites de pruebas en local.
- [ ] Entiendo que `DonWeb1` corre nativo con `systemd` y por qué hay que resguardar `.forecast_cache.joblib` en cada `git pull`.
- [ ] Conozco las limitaciones reales de escala, cobertura de celdas y claves externas del sistema.

## Siguiente lectura

Vuelve al mapa general en [00-indice.md](00-indice.md) cuando necesites ubicar rápido cualquier módulo o repositorio.
