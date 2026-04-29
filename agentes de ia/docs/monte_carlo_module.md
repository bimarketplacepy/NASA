# Modulo `services/monte_carlo`

## Objetivo

Cuantificar incertidumbre y riesgo de un plan de compra usando simulacion
de demanda por SKU y evaluacion financiera por escenario.

## Componentes

- `risk_metrics.py`
  - VaR, CVaR, Sharpe, probabilidad de perdida.
- `correlations.py`
  - Estimacion de matriz de correlacion por historial.
  - Proyeccion a matriz PSD para robustez numerica.
- `simulator.py`
  - Simulacion vectorizada de:
    - vendido, sobrante, faltante
    - ingreso, costo compra, costo stock muerto, costo oportunidad
    - retorno total por simulacion
  - Construccion de `ResultadoMonteCarlo`.

## Trazabilidad de decisiones

- Convencion: VaR/CVaR se expresan como magnitud positiva de perdida.
- Se usa truncado de demanda en 0 para evitar escenarios fisicamente invalidos.
- Para perecederos, factor de perdida de stock muerto = 1.0; no perecederos = 0.7.
- Implementacion vectorizada (numpy) por performance y simplicidad de mantenimiento.

## Ejecucion

Se puede usar desde `MonteCarloSimulator.simular(...)` y pasarle:

- `items`: plan de compra.
- `forecasts`: distribuciones resumidas por SKU.
- `n_sims`: cantidad de corridas.
- `correlaciones` opcional.
