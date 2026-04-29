# Marketplace SA Paraguay — Tarea 1 v2

Sistema decisional semántico para retail navideño: **ontología OWL + Neo4j +
deóntica defeasible + dispatcher de algoritmos + audit PROV-O + LLM
explainer + integración con scraper de tendencias**.

## Quickstart (5 líneas)

```powershell
cd C:\Users\Usuario\Documents\ABIGAIL\NASA\tarea1-ontologia-rag
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt          # rdflib, pyshacl, owlready2, pydantic, jsonschema, google-genai, loguru, etc
python -m unittest discover tests -v     # 148 tests verdes (deontic 24 + dispatcher 42 + audit 25 + trend_intake 31 + scraper_runner 3 + explainer 19 + integracion_v2 4)
python -m integrations.scraper_runner data\posts_simulados.json   # pipeline completo con Gemini real
```

## Arquitectura ASCII

```
                  ┌──────────────────────────────────────────────────┐
                  │   FUENTES DE DATOS                              │
                  │   - Pegasus (SQL Server, ETL v1)                │
                  │   - Redes sociales (Tarea 5: scraper LLM)       │
                  │   - APIs operativas                             │
                  └────────────────┬─────────────────────────────────┘
                                   │
            ┌──────────────────────┴────────────────────┐
            │                                           │
            ▼                                           ▼
  ┌──────────────────────┐                ┌─────────────────────────┐
  │  Bloque 1-4: TBox +  │                │  Bloque 9: ACL trends/  │
  │  ABox + Razonador    │                │  scraper_runner ->      │
  │  marketplace.ttl     │                │  TrendsService Mateo -> │
  │  HermiT clasifica    │                │  trend_intake (mio)     │
  │  ProductoCritico,    │                │  schema + stop-words +  │
  │  ProductoColdStart   │                │  triage por confianza   │
  └──────────┬───────────┘                └────────────┬────────────┘
             │                                         │
             │  Neo4j 5.26 + n10s                      │  TrendSignalIn
             │  4643 productos                         │  list[ProductoSimilarIn]
             ▼                                         ▼
  ┌────────────────────────────────────────────────────────────────┐
  │  Bloque 5: Motor de Similitud Multidimensional                 │
  │  4 ejes: lex (MiniLM) + struct (Gower) + behav + trend         │
  │  Top-K precomputado (32861 :SIMILAR_A) en Neo4j                │
  │  OntologyClientV2.productos_similares() / similares_a_descripcion()│
  └────────────────────────┬───────────────────────────────────────┘
                           │  DecisionContext rico
                           │  (sku, tipo, similar_top_k, trend_signal, ...)
                           ▼
  ┌────────────────────────────────────────────────────────────────┐
  │  Bloque 6: Capa Deóntica Defeasible                            │
  │  11 normas (4F + 3O + 4P) en normas_marketplace.ttl            │
  │  resolver.evaluar(decision, contexto) con :defeats + prioridad │
  │  EvaluacionDeontica{permitida, bloqueada_por, obligaciones, ...}│
  └────────────────────────┬───────────────────────────────────────┘
                           │
                           │  context.eval_deontica
                           ▼
  ┌────────────────────────────────────────────────────────────────┐
  │  Bloque 7: AlgorithmDispatcher                                 │
  │  9 reglas en config/dispatcher_rules.yaml (pydantic + AST safe)│
  │  18 descriptores formales mapeando 16 conceptos del paper      │
  │  AlgorithmRecommendation{stages, confianza, razonamiento}      │
  └────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
  ┌────────────────────────────────────────────────────────────────┐
  │  Bloque 8: Audit Trail PROV-O                                  │
  │  AuditStore append-only TTL (data/audit_log_v1.ttl)            │
  │  W3C PROV-O: Decision Activity + Context Entity + Agent        │
  │  5 queries SPARQL + replay() contrafactual                     │
  └────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
  ┌────────────────────────────────────────────────────────────────┐
  │  Bloque 10: LLM Explainer (capa final, opcional, asíncrona)    │
  │  Anthropic Claude / Gemini -> prosa 2-3 oraciones              │
  │  Detector alucinacion + fallback deterministico                │
  │  ExplicacionHumana{texto, cita_fuentes, fallback}              │
  └────────────────────────────────────────────────────────────────┘
```

## Cómo extender el sistema

### Agregar una norma nueva

1. Editar `ontology_semantic/normas_marketplace.ttl` agregando una instancia
   nueva de `:Obligation` / `:Permission` / `:Prohibition`:

```turtle
mkt:F_mi_norma_nueva a :Prohibition ;
    rdfs:label "F: descripcion humana"@es ;
    :appliesWhen "F_mi_norma_nueva" ;
    :target "compra_de_producto" ;
    :priority 75 ;
    :defeasible "true"^^xsd:boolean ;
    :validFrom "2026-01-01T00:00:00"^^xsd:dateTime ;
    :source "Justificacion de negocio que firma compliance." .
```

2. Registrar el predicado Python en `deontic/predicados_marketplace.py`:

```python
@register_predicate("F_mi_norma_nueva")
def _f_mi_norma_nueva(decision, contexto):
    if _str(decision, "tipo") != "compra":
        return False
    return _bool(contexto, "alguna_condicion_del_dominio")
```

3. Agregar test en `tests/test_deontic.py` que verifica el predicado dispara
   en su contexto.

4. Correr `python -m unittest tests.test_deontic` para verificar que la nueva
   norma no rompe las existentes (chequeo de conflictos por `target`).

### Agregar un algoritmo (descriptor) al catálogo

1. Editar `dispatcher/algorithms.py` agregando una entry al `_CATALOGO`:

```python
AlgorithmDescriptor(
    descriptor_id="mi_algoritmo_nuevo",
    kind=Kind.WEIGHTING,  # o uno de los 7 ejes
    nombre="Mi algoritmo (legible)",
    descripcion="Que hace en 1-2 lineas.",
    parametros=(
        ParameterSpec(nombre="alpha", tipo="float", default=0.2,
                      descripcion="...", rango=(0.0, 1.0)),
    ),
    referencia="Paper sec X.Y",
    concepto_paper=N,  # numero del concepto en la lista
),
```

2. Verificar que `dispatcher.algorithms.get("mi_algoritmo_nuevo")` lo encuentra.

3. Agregar test en `tests/test_dispatcher.py::TestCatalogoAlgoritmos`.

4. Tarea 4 (Mauri/Mati) implementa el algoritmo real cuando lo pidan en su rama.

### Agregar una regla del dispatcher

1. Editar `config/dispatcher_rules.yaml` agregando una entry nueva:

```yaml
- id: regla_NNN_mi_perfil
  nombre: "Descripcion humana del perfil"
  prioridad: 77   # entre 1 y 100; gana mayor primero
  cuando:
    - "context.tipo_sku == 'existing'"
    - "context.semanas_historia >= 26"
    - "context.volatilidad_forecast < 0.5"
  algoritmo: "affine_ordering_policy + ewma_smoothing + bounded_deviations + simple_absolute_deviation + dynamic_control_framing"
  parametros:
    ewma_smoothing:
      alpha: 0.18
    bounded_deviations:
      epsilon_factor: 1.7
  confianza: 0.75
```

2. Correr `python -m unittest tests.test_dispatcher::TestRulesYAMLValidacion`
   para verificar que el schema acepta la nueva regla.

3. Agregar test en `tests/test_dispatcher.py` con un `DecisionContext` que la
   dispara y verifica el resultado.

### Agregar una query SPARQL al audit

Editar `audit/queries.sparql`:

```sparql
## mi_query_nueva - Descripcion en una linea
# Parametros: $param1 ($param2 si hay)
SELECT ?x ?y WHERE {
  ?dec a mkt:Decision ;
       mkt:campo_X $param1 ;
       prov:used ?ctx .
  ?ctx a mkt:DecisionContext ;
       mkt:campo_Y ?y .
}
## /mi_query_nueva
```

Se carga automaticamente en `audit.QUERIES["mi_query_nueva"]`.

## Checklist de qué hace cada componente

| Componente | Responsabilidad | NO hace |
|---|---|---|
| `ontology/` (v1) | Cliente Neo4j operacional, ETL Pegasus | OWL formal, similitud, decisiones |
| `ontology_semantic/marketplace.ttl` | TBox: clases, propiedades, axiomas, agentes | Datos operacionales (van a Neo4j) |
| `ontology_semantic/normas_marketplace.ttl` | ABox de normas deónticas (11 normas) | Lógica de evaluación |
| `ontology_semantic/bridge.py` | Sincroniza Neo4j ↔ RDF (n10s) | Razonamiento, decisiones |
| `ontology_semantic/reasoner.py` | HermiT batch sobre snapshot | Queries operacionales |
| `ontology_semantic/validar.py` | SHACL validator CLI | Razonamiento, decisiones |
| `ontology_semantic/similarity/` | Motor 4-ejes (Bloque 5), top-K precompute | Decisiones, normas |
| `ontology_semantic/client_v2.py` | OntologyClientV2 drop-in v1 + similitud | Decisiones, normas |
| `deontic/` | Resolver normas O/P/F con :defeats + prioridad | Decidir algoritmo |
| `dispatcher/` | Selector regla → combo de descriptores | Ejecutar algoritmo (eso es Tarea 4) |
| `audit/` | Persiste decisiones como subgrafos PROV-O TTL | Modificar decisiones |
| `llm/` | Traduce decisión a prosa para operador | Decidir, calcular, modificar |
| `integrations/trend_intake.py` | ACL: scraper output → DecisionContext | Extraer trends (lo hace Tarea 5) |
| `integrations/scraper_runner.py` | Orquesta TrendsService (Mateo) → ACL | LLM real (lo hace Tarea 5) |
| `trends/` | Pipeline LLM Mateo (Tarea 5) | Decisiones del Marketplace |
| `clients/llm_client.py` | Auto-pick Gemini real / heurístico fallback | Validar, persistir, decidir |
| `config/dispatcher_rules.yaml` | 9 reglas declarativas pydantic-validadas | Lógica de norma deóntica |
| `data/audit_log_v1.ttl` | Audit trail append-only de todas las decisiones | Ser modificado a mano |
| `tests/` | 148 tests cubriendo cada bloque + 4 e2e | (test infrastructure) |

## ADRs

- [ADR-001: Hibridización OWL + Neo4j](docs/adr/ADR-001-hibridizacion-owl-neo4j.md)
- [ADR-002: Deóntica pragmática](docs/adr/ADR-002-deontica-pragmatica.md)
- [ADR-003: LLM en capa final](docs/adr/ADR-003-llm-en-capa-final.md)
- [ADR-004: Rules declarativas YAML](docs/adr/ADR-004-rules-declarativas-yaml.md)

## Componentes externos del proyecto NASA

- **Tarea 4 (Mauri / Mati)** — implementación real de los algoritmos del
  paper de robust optimization. Consume `AlgorithmRecommendation` de mi
  Bloque 7 y los `:SIMILAR_A` precomputados del Bloque 5.
- **Tarea 5 (Mateo)** — agente scraper LLM que produce TrendSignals desde
  redes sociales. Mi Bloque 9 los consume y enriquece con el ACL.
- **Tarea 6 (TBD)** — grafo causal sobre decisiones; consume audit log
  PROV-O de mi Bloque 8 para trazar shadow prices.

## Variables de entorno (`.env`)

```
# Neo4j (operacional)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=marketplace2026

# SQL Server Pegasus (ETL v1)
SQLSERVER_DRIVER=ODBC Driver 17 for SQL Server
SQLSERVER_HOST=...
...

# LLM (opcional - sin estos cae a heuristico/fallback determinista)
GEMINI_API_KEY=AIza...        # para scraper Tarea 5
GEMINI_MODEL=gemini-2.5-flash # default
ANTHROPIC_API_KEY=sk-ant-...  # para explainer Bloque 10
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022  # default
```

## Smoke test de cierre

```powershell
python tests\test_smoke_v2.py
```

Verifica los 11 bloques en cascada. Si todo verde, el sistema está listo
para que Tarea 4 enchufe los algoritmos reales y para handoff a operación.
