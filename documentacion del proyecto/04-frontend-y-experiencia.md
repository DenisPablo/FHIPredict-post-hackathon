# 4. Frontend, mapa operativo y panel `/monitor`

La interfaz web es una aplicación ligera en **React 18 + TypeScript + Vite** sin librerías pesadas de enrutamiento, diseñada con la identidad visual de **FuegoContinuo** (fondo oscuro `#07100F` y acento verde lima `#B8EE68`) y soporte bilingüe (español por defecto con selector a inglés).

---

## Mapa de componentes (`frontend/src/`)

| Archivo | Función |
|---|---|
| `App.tsx` | Enrutamiento liviano por History API entre `/` (mapa) y `/monitor` (tablero empírico), con carga diferida (`React.lazy`) y caché de consultas de 10 minutos vía TanStack Query. |
| `i18n.ts` | Diccionario completo de textos de UI, popups, leyenda y explicaciones en español e inglés. |
| `api/forecast.ts` | Cliente HTTP y tipos para `/api/v1/forecast` y `/api/v1/spread`. |
| `api/monitor.ts` | Cliente HTTP y tipos para `/api/v1/monitor/status`, `/metrics`, `/comparison` y `POST /run`. |
| `components/RiskMap.tsx` | Mapa interactivo en **MapLibre GL** centrado en Argentina, con capas de riesgo, propagación, popups de detalle y enlaces directos a Google Maps. |
| `components/NavigationPanel.tsx` | Panel lateral para saltar rápido a cualquier provincia o al top 30 de celdas más críticas del momento. |
| `components/TimeRangeBar.tsx` | Selector de ventana temporal (`1`, `3`, `7`, `15` días) y deslizador por día individual. |
| `components/RiskLegend.tsx` | Leyenda dinámica que muestra los rangos porcentuales exactos de `Bajo`, `Moderado`, `Alto` y `Extremo` vigentes ese día. |
| `components/MonitorDashboard.tsx` | Tablero completo de `/monitor` con guía rápida, resumen en lenguaje natural, gráficos, tabla de 30 días y exportación a CSV. |

---

## Vista 1: Mapa operativo (`/`)

El mapa está pensado para ubicar rápido dónde concentrar la atención territorial:

- **Mapas base:** mapa oscuro del Instituto Geográfico Nacional (IGN `argenmap_oscuro`), con opciones para activar rutas/etiquetas híbridas y relieve 3D con sombreado topográfico.
- **Capa de ignición (`fire-risk-circles`):** muestra las celdas filtradas por nivel mínimo (por defecto `Moderado` hacia arriba). En ventanas de varios días (`3`, `7` o `15` días) refleja el **pico máximo diario** dentro de ese rango para mantener la misma escala de colores que la vista de 24 horas.
- **Capa de propagación (`fire-spread-circles`):** se activa o desactiva desde el mapa con botones para proyectar **24h**, **48h** o **72h** alrededor de focos activos o celdas de riesgo alto.
- **Popup de celda:** al hacer clic en un punto muestra su categoría, probabilidad, confianza heurística (`Alta`, `Media` o `Baja`), variables climáticas del día (temperatura, humedad, viento, lluvia, días secos) y un enlace externo para abrir las coordenadas en Google Maps.

### Escala visual de categorías

| Categoría | Color en mapa | Significado operativo |
|---|---|---|
| **Extremo** | `#FF6759` (coral/rojo) | Máxima prioridad de vigilancia (top `0,1 %` del día, acotado). |
| **Alto** | `#FF9C55` (naranja) | Prioridad alta (top `1 %` del día, acotado). |
| **Moderado** | `#68D9D0` (turquesa) | Condiciones favorables que requieren seguimiento (top `5 %` del día, acotado). |
| **Bajo** | `#3D786E` (verde oscuro) | Riesgo relativo bajo (oculto por defecto para mantener limpio el mapa). |

---

## Vista 2: Tablero empírico (`/monitor`)

El tablero `/monitor` permite auditar sin conocimientos estadísticos si el sistema está funcionando bien en el mundo real:

1. **Guía rápida de 3 pasos (visible por defecto):** explica qué mirar primero y recuerda **evaluar siempre días pasados ya cerrados** (el día actual puede mostrar muchos falsos positivos simplemente porque los satélites aún no terminaron de pasar).
2. **Resumen en lenguaje simple:** traduce automáticamente las métricas del día seleccionado a una lectura clara de aciertos, omisiones y contexto.
3. **6 tarjetas KPI:** resumen desempeño global, tasa base de incendios, aciertos (`Hits`), omisiones (`Misses`) y concentración de riesgo (*Lift*).
4. **Gráficos de barras responsivos:** captura por categoría y evolución histórica clicable de los últimos 14 días.
5. **Tabla de 30 días y exportación CSV:** descarga un reporte completo de 22 columnas (`fhipredict-monitoreo-viirs.csv`) compatible con Excel (UTF-8 con BOM).
6. **Botón de actualización manual (`Run VIIRS`):** dispara una corrida en el backend y consulta su progreso cada 2 segundos hasta completar.

---

## Checklist de comprensión

- [ ] Entiendo que en el mapa puedo alternar entre la ventana de días de ignición y la capa de propagación a 24h/48h/72h.
- [ ] Entiendo que la leyenda muestra porcentajes dinámicos cuando el sistema opera en modo percentil diario.
- [ ] Entiendo por qué en `/monitor` debo juzgar días pasados cerrados y no el día actual incompleto.

## Siguiente lectura

Continúa con [05-operacion-despliegue-y-limites.md](05-operacion-despliegue-y-limites.md) para ver cómo correr las pruebas en local, cómo está desplegado el proyecto en `DonWeb1` y qué limitaciones reales conviene tener presentes.
