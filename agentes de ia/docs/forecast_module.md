# Modulo `services/forecast`

## Objetivo

Proveer pronosticos de demanda para cada SKU con dos estrategias:

1. ETS (Holt-Winters) para historiales largos (>=52 semanas).
2. Cold-start por categoria para historiales cortos o nulos.

## Componentes

- `seasonal_decompose.py`
  - Utilidades de soporte para semana-anio, clipping de demanda y resumen estadistico.
- `cold_start.py`
  - Nivel base por SKU/categoria.
  - Penalizacion de desvio para incertidumbre.
  - Simulacion normal con truncado a no-negativos.
- `ets_model.py`
  - Fit de `ExponentialSmoothing`.
  - Bootstrap de residuos para intervalos calibrados.
- `forecast_service.py`
  - Punto de entrada unico.
  - Seleccion automatica de estrategia.
  - Validacion de cuantiles.

## Trazabilidad de decisiones

- Se usa ETS aditivo estacional (`seasonal_periods=52`) por alineacion con datos semanales.
- Intervalos via bootstrap para evitar asumir normalidad estricta de residuos.
- En cold-start se multiplica desviacion por `1.5` para reflejar incertidumbre adicional.
- Se preserva reproducibilidad con `seed` en todos los caminos.

## Riesgos y mejoras posteriores

- Ajustar outlier handling previo al ETS.
- Incluir `prophet_model.py` opcional cuando el stack lo requiera.
- Integrar tendencia externa como ajuste de media.
