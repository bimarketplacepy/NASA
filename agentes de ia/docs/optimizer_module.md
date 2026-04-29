# Modulo `services/optimizer`

## Objetivo

Producir una `Recomendacion` ejecutable y trazable a partir de:

- SKUs objetivo
- forecasts de demanda
- evento comercial
- perfil del operador

## Estado actual (iteracion incremental)

- `heuristic_fallback.py`:
  - construye plan factible por regla greedy
  - respeta MOQ
  - aplica descuento por tramo
  - recorta por presupuesto
- `optimizer_service.py`:
  - orquesta heuristica
  - ejecuta Monte Carlo para metricas de riesgo
  - calcula confianza global
  - persiste recomendacion en `data/recomendaciones/*.json`
- `milp_solver.py`:
  - interfaz/stub para migrar a MILP exacto sin romper API
- `robust_affine_policy.py`:
  - formulacion robusta con politica afin exponencial (EWMA + A_uiw)
  - precomputo vectorizado con numpy/scipy
  - restricciones robustas y financieras en solver PuLP

## Trazabilidad de decisiones

- Se prioriza "funciona y es medible" antes del solver exacto.
- Todo plan queda persistido en JSON con timestamp e identificador.
- Se incluye texto de justificacion con:
  - metodo solicitado
  - timeout nominal
  - VaR95
  - observaciones de heuristica

## Siguientes pasos de evolucion

1. Endurecer calibracion de parametros (`epsilon`, `sigma`, `service_rate_r`) con datos reales.
2. Agregar cutting-plane para conjuntos de incertidumbre grandes.
3. Integrar fully-fledged MILP/SAA como benchmark comparativo.
