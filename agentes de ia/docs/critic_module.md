# Modulo `services/critic`

## Objetivo

Ejecutar red-teaming sobre una `Recomendacion` para detectar vulnerabilidades
materiales antes de aprobación operativa.

## Componentes

- `attack_strategies.py`: estrategias iniciales (aduana, caida de demanda, FX).
- `critic_service.py`: orquestación y ordenamiento por severidad/impacto.

## Trazabilidad

- Cada vulnerabilidad incluye:
  - probabilidad estimada
  - impacto esperado y p95
  - severidad
  - mitigación sugerida
