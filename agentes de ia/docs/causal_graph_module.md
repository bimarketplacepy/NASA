# Modulo `services/causal_graph`

## Objetivo

Construir una representacion explicable de la recomendacion para consumo
de frontend (grafo de nodos y aristas causales).

## Componentes

- `graph_builder.py`: transforma `Recomendacion` en `GrafoCausal`.
- `graph_service.py`: persiste/carga grafos cacheados por recomendacion.

## Trazabilidad

- El `grafo_id` se deriva de `recomendacion_id`.
- Cada nodo guarda `metadata` con contexto de negocio.
