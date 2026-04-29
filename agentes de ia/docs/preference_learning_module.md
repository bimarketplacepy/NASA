# Modulo `services/preference_learning`

## Objetivo

Actualizar el perfil del operador a partir de señales de feedback para
personalizar recomendaciones futuras.

## Componentes

- `update_rules.py`: reglas determinísticas incrementales.
- `preference_service.py`:
  - carga perfil
  - aplica reglas
  - persistencia atómica (`tmp -> rename`)
  - append a `feedback_log.jsonl`

## Trazabilidad

- Cada feedback queda en log append-only.
- El perfil incrementa `version` en cada update.
- Historial de feedback persiste IDs aplicados.
