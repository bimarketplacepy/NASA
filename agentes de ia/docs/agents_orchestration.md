# Orquestacion de agentes (iteracion inicial)

## Componentes

- `agents/state.py`: estado compartido por turno.
- `agents/intent_classifier.py`: clasificador por reglas.
- `agents/orchestrator.py`: ruteo a servicios por intención.

## Intents cubiertos

- `SALUDO`
- `SOLICITAR_RECOMENDACION`
- `CONTRAFACTUAL`
- `CONSULTAR_TENDENCIAS`
- `EXPLICAR_DECISION`
- fallback `OTRO`

## Integracion

El router `POST /api/v1/chat` delega la ejecución al orquestador y persiste
la conversación en `runtime.sesiones_chat`.
