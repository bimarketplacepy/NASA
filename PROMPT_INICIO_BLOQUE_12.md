# BLOQUE 12 — Integración final: Tarea 3 (forecast), Tarea 5 (agentes IA), APEX frontend

## Contexto del proyecto (Marketplace SA Paraguay, retail navideño)

Sistema decisional semántico end-to-end para optimización de inventario navideño.
Equipo: Tarea 1 v2 (yo, Abi), Tarea 3 (forecast), Tarea 4 (Mauri/Mati - algoritmos
del paper), Tarea 5 (Mateo - agentes IA / scraper). Frontend en Oracle APEX
ya construido por otro equipo, conectándose como cliente HTTP.

**Path absoluto del proyecto**: `C:\Users\Usuario\Documents\ABIGAIL\NASA\tarea1-ontologia-rag\`
**Python**: 3.12 en `venv/`. **Neo4j**: 5.26.25 en Docker `neo4j-marketplace`.
**.env** ya tiene: `NEO4J_*`, `SQLSERVER_*`, `GEMINI_API_KEY`.

## Estado actual (qué YA está construido y funcional)

### Bloques 0-11 completados — 148 tests verdes + smoke 12/12

| Bloque | Qué hace | API pública | Path |
|---|---|---|---|
| 0 | v1 baseline (NO TOCAR) | `OntologyClient` (Neo4j legacy) | `ontology/` |
| 1 | TBox OWL + clases dominio + clases decisionales + clases deónticas | `marketplace.ttl` con `:Producto`, `:Norm`, `:Decision`, `:Algorithm`, `:Agent`, etc | `ontology_semantic/marketplace.ttl` |
| 2 | SHACL shapes (5 NodeShapes) + validador CLI | `python -m ontology_semantic.validar tests/data/datos_validos.ttl` | `ontology_semantic/shapes.ttl`, `validar.py` |
| 3 | Bridge Neo4j↔RDF via neosemantics 5.26 | `bridge.init_n10s`, `_Bridge.importar_owl`, `_Bridge.exportar`, `query_sparql` | `ontology_semantic/bridge.py` |
| 4 | Razonador HermiT + 6 axiomas equivalentClass | `cargar_onto_con_abox`, `run_hermit`, `persist_to_neo4j` | `ontology_semantic/reasoner.py` |
| 5 | Motor de similitud multidimensional (4 ejes: lex+struct+behav+trend) + 32861 `:SIMILAR_A` precomputadas + cold-start desde texto | `SimilarityEngine`, `OntologyClientV2.productos_similares()`, `productos_similares_a_descripcion()` | `ontology_semantic/similarity/` |
| 6 | Capa deóntica defeasible: 11 normas (4F+3O+4P) con `:defeats` + prioridad + vigencia temporal | `DeonticResolver.from_ttl(...)`, `evaluar(decision, contexto) -> EvaluacionDeontica` | `deontic/`, `ontology_semantic/normas_marketplace.ttl` |
| 7 | AlgorithmDispatcher con 9 reglas YAML declarativas + 18 descriptores formales del paper de robust optimization | `AlgorithmDispatcher.from_yaml(...)`, `decidir(context) -> AlgorithmRecommendation` | `dispatcher/`, `config/dispatcher_rules.yaml` |
| 8 | Audit trail PROV-O W3C en TTL append-only + 5 queries SPARQL + replay contrafactual | `AuditStore.log_decision()`, `replay()`, `QUERIES["..."]` | `audit/`, `data/audit_log_v1.ttl` |
| 9 | ACL para Tarea 5: TrendSignal pydantic + jsonschema + stop-words + triage + scraper_runner que orquesta TrendsService de Mateo → ACL | `process_trend_signal()`, `batch_process()`, `run_scraper_pipeline()` | `integrations/`, `trends/` (Mateo), `clients/` |
| 10 | LLM Explainer con detector de alucinación + fallback determinístico. Anthropic Claude o Gemini, auto-pick | `explicar(decision_id, store) -> ExplicacionHumana` | `llm/`, `llm/templates/explainer.txt` |
| 11 | Tests integrados v2 (4 escenarios e2e) + 4 ADRs + README v2 + smoke v2 cascada | `tests/test_integracion_v2.py`, `tests/test_smoke_v2.py`, `docs/adr/`, `README_v2.md` |

### APIs públicas estables que el código nuevo debe consumir

```python
# Cliente unificado para datos del catálogo (Pegasus → Neo4j)
from ontology_semantic import OntologyClientV2

# Resolver deóntico (Bloque 6)
from deontic import DeonticResolver, EvaluacionDeontica, UnresolvedDeonticConflict

# Dispatcher de algoritmos (Bloque 7)
from dispatcher import (
    AlgorithmDispatcher, AlgorithmRecommendation, AlgorithmStage,
    DecisionContext, SimilarRef, TipoSku, TrendSignal,
)

# Audit PROV-O (Bloque 8)
from audit import AuditStore, replay, QUERIES

# ACL trends (Bloque 9)
from integrations import (
    TrendSignalIn, ProductoSimilarIn, FuenteTrend, TrendIntakeResult,
    process_trend_signal, batch_process,
)
from integrations.scraper_runner import run_scraper_pipeline

# LLM explainer (Bloque 10)
from llm import explicar, ExplicacionHumana
```

### Pipeline canónico de UNA decisión

```
DecisionContext
  → DeonticResolver.evaluar() → context.eval_deontica
  → AlgorithmDispatcher.decidir(context) → AlgorithmRecommendation
  → AuditStore.log_decision(...) → decision_id
  → llm.explicar(decision_id, store) → ExplicacionHumana
```

### Convenciones inviolables (heredadas de los 11 bloques)

1. **No tocar `ontology/` (v1)** — bug latente con sku string conocido y encapsulado en V2.
2. **TBox separada de ABox**: `marketplace.ttl` (clases) ≠ `normas_marketplace.ttl` (instancias).
3. **No `eval()` builtin** sobre datos externos: `dispatcher/conditions.py` tiene AST visitor restringido; `deontic/predicates.py` tiene registry-by-name.
4. **Audit log append-only**: nunca borrar entradas, idempotente por `decisionId`.
5. **LLM solo como traductor**: nunca decisor. Detector de alucinación + fallback determinístico siempre.
6. **Frozen dataclasses** para inmutabilidad de configuración (normas, descriptores, reglas).
7. **Type hints + docstrings Google style** en todo módulo nuevo.
8. **Tests unittest** (consistencia con bloques previos), nunca pytest.
9. **Errores con contexto** (re-raise con info útil), nunca silenciar.

### Stack instalado en `venv/`

`Python 3.12`, `rdflib 7.6`, `owlready2 0.50`, `pyshacl 0.31`, `neo4j 5.20`,
`sentence-transformers 2.7`, `PyYAML 6.0`, `pydantic 2.13`, `jsonschema 3.2`,
`google-genai 1.73`, `anthropic` (opcional), `loguru`, `python-dotenv`,
`scikit-learn`, `numpy`, `pandas`.

---

## TAREAS DEL BLOQUE 12

Tres componentes externos ya están construidos por otros equipos. Tu trabajo
es integrarlos con el sistema de los 11 bloques anteriores y exponer todo
como una API consumible por el frontend APEX. **No diseñar desde cero — solo
adaptar e integrar.**

### Componente A: Agentes IA (Tarea 5 - Mateo) — `agentes de ia/`

**Path absoluto**: `C:\Users\Usuario\Documents\ABIGAIL\NASA\tarea1-ontologia-rag\agentes de ia\`

**Qué se espera ahí**: implementación final de los agentes IA del scraper de
tendencias. La carpeta `trends/` (versión anterior) ya está integrada vía
`integrations/scraper_runner.py` con un cliente Gemini real auto-detectado
(`clients/llm_client.py:GeminiLLMClient`). La carpeta nueva `agentes de ia/`
puede tener:
- LLM client mejorado o múltiples agentes especializados.
- Pipeline de scraping real (no solo simulado desde JSON).
- Otros formatos de output.

**Tu trabajo**:
1. Inspeccionar el contenido real de `agentes de ia/` antes de hacer nada (los
   archivos pueden tener imports rotos, dependencias faltantes, etc — replicar
   el patrón usado para `trends/`: crear shims en `services/`, completar
   `clients/`, agregar `schemas/` si hace falta).
2. Si los agentes producen TrendSignals (o cualquier estructura mapeable):
   - Extender `integrations/scraper_runner.py` o crear
     `integrations/agentes_runner.py` que invoque los agentes y mapee a
     `TrendSignalIn` del ACL del Bloque 9.
   - Reutilizar TODO el pipeline ACL → Dispatcher → Audit → Explainer.
3. Si los agentes producen otra cosa (ej. recomendaciones directas, análisis
   de catálogo, etc):
   - Definir un nuevo ACL en `integrations/` con el mismo patrón
     (schema validation + pydantic + triage + dispatcher hookup).
4. Conservar el auto-pick `clients/llm_client.py`: si los nuevos agentes
   también usan Gemini, no romper el cliente existente — extenderlo.
5. Tests unittest mínimos en `tests/test_agentes_ia.py` (3-5 casos cubriendo
   integración + fallback offline cuando Gemini no está disponible).

### Componente B: Forecast (Tarea 3) — `forecast/`

**Path absoluto**: `C:\Users\Usuario\Documents\ABIGAIL\NASA\tarea1-ontologia-rag\forecast\`

**Qué se espera ahí**: sistema de forecast de demanda/ventas implementado por
Tarea 3. Probablemente:
- Modelos entrenados (LSTM, ARIMA, Holt-Winters, Prophet, lo que sea).
- API: `forecast(sku, horizonte_semanas) -> ForecastResult` con punto +
  intervalos de confianza.
- Histórico de ventas integrado.

**Tu trabajo**:
1. Inspeccionar `forecast/` y entender el contrato real de output (probablemente
   un dataclass o pydantic con `sku`, `forecast_punto`, `intervalo_inferior`,
   `intervalo_superior`, `volatilidad`, `n_semanas_historia`).
2. Crear `integrations/forecast_intake.py` que:
   - Llame al sistema de forecast vía su API (sin replicar lógica).
   - Mapee la salida a campos del `DecisionContext` del Bloque 7
     (`semanas_historia`, `volatilidad_forecast`, etc).
   - Si el forecast detecta tipo de SKU (existing/cold-start/trending), lo
     setee como `tipo_sku`.
3. Reutilizar el pipeline existente — el dispatcher ya consume estos campos.
   Lo nuevo es solo el adapter.
4. Si forecast tiene su propio sistema de logging/persistencia, NO duplicarlo;
   apuntar el audit log PROV-O a referenciar el `forecast_id` con
   `prov:wasInformedBy` (Bloque 8 ya soporta esto vía `:consultedNorma` —
   crear análogamente `:consultedForecast` si aplica).
5. Tests `tests/test_forecast_intake.py` (3-5 casos).

### Componente C: API REST para Oracle APEX

**Tu trabajo**:
1. Crear `api/` con FastAPI (no Flask — async, type hints nativos, mejor docs).
   Endpoints mínimos:
   - `POST /api/v2/decidir` — body: `{sku?, raw_post?, forecast_input?}` →
     pipeline completo → response con `recomendacion`, `bloqueada_por_deontica`,
     `confianza`, `audit_decision_id`, `explicacion_humana`.
   - `GET /api/v2/decisiones/{decision_id}` — recupera decisión del audit log
     con su explicación.
   - `GET /api/v2/decisiones?desde=&hasta=&agente=&bloqueada_por=` — query
     SPARQL del Bloque 8 expuesta como REST.
   - `POST /api/v2/replay/{decision_id}` — replay contrafactual.
   - `GET /api/v2/normas` — lista las 11 normas del catálogo (para que el
     operador APEX vea qué normas están vigentes).
   - `GET /api/v2/algoritmos` — lista los 18 descriptores del catálogo.
   - `GET /api/v2/healthcheck` — Neo4j up, audit log accesible, dependencias.
2. CORS configurado para que APEX pueda consumir desde su origen.
3. Pydantic models para request/response (reusar los del Bloque 7 y 9).
4. OpenAPI docs auto-generados en `/docs` (FastAPI lo da gratis).
5. Tests `tests/test_api.py` con `httpx.AsyncClient` (5-8 endpoints).

### Componente D: Smoke test v3 + handoff

1. Extender `tests/test_smoke_v2.py` a `tests/test_smoke_v3.py` que agregue
   los bloques de agentes IA, forecast y API REST.
2. Crear `HANDOFF_BLOQUE_12.md` con el estado final consolidado (mismo formato
   que `HANDOFF_BLOQUE_6.md` que ya existe — usalo de referencia).
3. Smoke debe quedar verde 100% antes de cierre.

---

## REGLAS OPERATIVAS DEL CHAT (críticas)

1. **NO pedir go**. Cada vez que termines una etapa, pasá a la siguiente
   automáticamente. La usuaria no quiere confirmar entre stages.
2. **Usar TodoWrite/TaskCreate** desde el inicio para que se vea el progreso
   sin esperar respuestas.
3. **Optimizar créditos**:
   - NO releer archivos que ya leíste (mantener el contexto).
   - NO redescubrir convenciones (este prompt te las da).
   - NO escribir más código del necesario para la tarea — best practices
     pero **funcional > sofisticado**.
   - Si algo ya está resuelto en otro bloque, reusarlo, no replicar.
4. **Best practices profesionales**: type hints, docstrings, tests unittest,
   error con contexto, idempotencia, frozen dataclasses para config inmutable,
   AST safe en lugar de eval, audit append-only, LLM solo como traductor.
5. **Si el Edit tool trunca archivos** (problema conocido en este proyecto en
   archivos > 8KB), reparar via `python -c` heredoc en bash. Verificar después
   de cada Write/Edit con `wc -l` y `tail -5`.
6. **Tests deben pasar**. Si un test falla por algo del entorno (Neo4j no
   corriendo en el sandbox), marcarlo como skip con razón documentada,
   no remover el test.
7. **No-regresión**: después de cada bloque integrado, correr el test suite
   completo (`python -m unittest discover tests`) y verificar que los 148
   tests previos siguen verdes.
8. **Idempotencia**: re-correr cualquier comando del sistema dos veces debe
   dejar el estado igual.

## CRITERIOS DE ACEPTACIÓN

- `python tests\test_smoke_v3.py` → 14+ checks verdes (los 12 del v2 + agentes
  IA + forecast + API).
- `python -m unittest discover tests` → todos los tests verdes (148 previos +
  los nuevos de agentes/forecast/api).
- `uvicorn api.main:app --reload` levanta el servidor sin errores y
  `curl http://localhost:8000/api/v2/healthcheck` devuelve `{"status": "ok"}`.
- `curl http://localhost:8000/docs` muestra OpenAPI con todos los endpoints
  documentados.
- `HANDOFF_BLOQUE_12.md` existe y describe el estado final.
- README v2 actualizado con sección "Cómo correr la API REST".

## QUÉ DEJAR PARA OTRO MOMENTO

- NO migrar las 148 tests a pytest (mantener unittest).
- NO refactorizar bloques anteriores que ya están verdes — solo agregar
  capas nuevas encima.
- NO conectar a Neo4j cloud / managed instance — seguir con Docker local
  como hasta ahora.
- NO implementar autenticación/JWT en la API REST — ese es problema de APEX
  que se conecta vía VPN interno. Documentar como TODO en el HANDOFF.
- NO tocar el código de `ontology/` (v1) ni `trends/` (Mateo, ya integrado).

---

## EMPEZAR YA

Como primer acción del próximo chat: leer este documento, hacer un `ls` de
`agentes de ia/` y `forecast/` para ver qué hay, crear todos los Tasks del
plan, y arrancar a integrar. Sin preguntar nada al usuario hasta tener algo
funcional para mostrar.

El sistema actual ya tiene smoke v2 verde. La meta es: smoke v3 verde +
API REST funcional + handoff escrito, en el mínimo número de iteraciones
posibles, con código limpio y profesional.
