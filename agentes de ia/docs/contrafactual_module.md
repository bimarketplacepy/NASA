# Modulo `services/contrafactual`

## Objetivo

Permitir analizar escenarios "que pasa si..." reoptimizando el plan bajo
perturbaciones controladas y comparando contra la recomendacion base.

## Componentes

- `nl_parser.py`
  - Parser rule-based de lenguaje natural a `Perturbacion`.
- `perturbations.py`
  - Aplica cambios al contexto (proveedores excluidos, presupuesto, demanda).
- `reoptimizer.py`
  - Reusa `OptimizerService` con contexto perturbado.
  - Construye `EscenarioContrafactual`.
- `diff_engine.py`
  - Calcula cambios estructurados entre plan base y alterno.

## Trazabilidad

- Cada escenario genera:
  - `escenario_id`
  - `recomendacion_base_id`
  - diff de items y metricas (`delta_costo_total`, `delta_retorno_esperado`, `delta_var`)
- El parser mantiene compatibilidad futura con version LLM al conservar
  contrato `parse_perturbacion(texto) -> Perturbacion`.
