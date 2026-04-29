# Handoff — Tarea 1 v2 — Bloques 1 a 4 completados

> Este documento condensa todo el trabajo hecho desde Bloque 1 a Bloque 4 de la
> Tarea 1 v2 del sistema retail navideño de Marketplace SA Paraguay. Está
> pensado para que un nuevo chat de Cowork tome contexto y continúe en el
> Bloque 5 sin perder información.

---

## 1. Contexto del proyecto

**Tarea 1 v2** del sistema retail navideño de Marketplace SA Paraguay (proyecto
NASA, según el PDF). Construyo, bloque por bloque, una **ontología semántica
decisional** que:

- Decide qué algoritmo de optimización usar según el contexto.
- Razona deónticamente sobre normas (obligación / permisión / prohibición).
- Maneja cold-start de SKUs nuevos vía similitud ponderada.

**v1 (NO se toca)** ya entregada: `C:\Users\Usuario\Documents\ABIGAIL\NASA\tarea1-ontologia-rag\`
con Neo4j 5 + ChromaDB + ~4.643 productos navideños + ~61 proveedores + clientes
`OntologyClient` y `RAGClient` estables. La capa nueva vive en
`ontology_semantic/` (subcarpeta nueva, paralela a `ontology/` y `rag/` v1).

Equipo: Yo (Tarea 1), Mauri/Mati (Tarea 4 — optimización), Cris (Tarea 3 —
forecasting). Los tres consumen mi `OntologyClient` v1 y van a consumir
`bridge.py` + `reasoner.py` v2.

---

## 2. Stack tecnológico actual

| Componente | Versión | Estado |
|---|---|---|
| Python (venv en `venv/`) | 3.12 | ya estaba |
| Windows + PowerShell | — | entorno usuaria |
| Java | OpenJDK 21 (Temurin) | instalado en Bloque 4 (HermiT lo necesita) |
| Neo4j | **5.26.25** (community) en Docker `neo4j-marketplace` | recreado en Bloque 3 |
| Neosemantics (n10s) | **5.26.0** (`/plugins/neosemantics-5.26.0.jar`) | instalado Bloque 3 |
| ChromaDB | 0.5.23 | ya estaba |
| neo4j Python driver | 5.20.0 | ya estaba |
| owlready2 | 0.50 | Bloque 1 |
| rdflib | 7.6.0 | Bloque 1 |
| pyshacl | 0.31.0 | Bloque 2 |
| pandas, python-dotenv, sentence-transformers, etc. | — | ya estaban |

### Variables de entorno (`.env`)
- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` (Neo4j local Docker)
- `SQLSERVER_*` (Pegasus, no se usa en bloques 1-4)

---

## 3. Reglas de trabajo inviolables (recordatorio)

1. **Paso a paso**, un bloque por vez. Nunca adelantarse al siguiente bloque sin
   confirmación explícita.
2. **Verificar antes de afirmar.** No decir "X funciona" sin haber corrido el
   comando y mostrado la salida real.
3. **Leer antes de modificar.**
4. **No inventar APIs.** Si no estoy 100% seguro de una firma, leer docs antes.
5. **Idempotencia siempre.**
6. **Type hints + docstrings Google.**
7. **Errores con contexto** (re-elevar con info útil).
8. **No tocar la v1 existente** — solo extender.
9. **Nada de mocks silenciosos.**
10. **Asumime ingeniera intermedia.** Sé Python, Docker, SQL, Neo4j básico. NO sé
    OWL, SHACL, SPARQL, lógica deóntica formal. **Primer paso de cada bloque:
    enseñar el concepto en ~2 párrafos antes de ejecutar.**
11. **Anti-alucinación en código.** Verificar contra docs oficiales antes de
    codear.

### Cómo responder a cada nuevo bloque
1. Confirmar lectura del contexto.
2. Mostrar pre-condiciones a verificar.
3. **Esperar mi go.**
4. Ejecutar paso a paso mostrando salidas reales.
5. Mostrar criterios de aceptación cumplidos.
6. Esperar confirmación antes de avanzar.

---

## 4. Estado de la infraestructura

### Neo4j en Docker (post-Bloque 3)

```
docker container: neo4j-marketplace
image:            neo4j:5 (resolved a 5.26.25-community)
puertos:          7474:7474 (HTTP), 7687:7687 (Bolt)
volumen datos:    neo4j-data → /data
bind mount plugins: ${PWD}/neo4j_plugins → /plugins
env vars seguridad:
  NEO4J_AUTH=neo4j/<password>
  NEO4J_dbms_security_procedures_unrestricted=n10s.*,apoc.*
  NEO4J_dbms_security_procedures_allowlist=n10s.*,apoc.*
```

### Datos en Neo4j (todos con `.uri` agregada en Bloque 3)

| Label | Cantidad | Notas |
|---|---:|---|
| Producto | 4.643 | con `:sku`, `:nombre`, `:perecedero`, etc. |
| Proveedor | 61 | con `:proveedor_exterior` (boolean) derivado de Pegasus TIPO_DOCUMEN=20 |
| Categoria | 64 | |
| Grupo | 22 | |
| SubSeccion | 1 | (Navidad) |
| Seccion | 1 | (Festividades) |
| EventoComercial | 8 | |
| `_GraphConfig`, `_NsPrefDef`, `_MapDef`, `_MapNs` | 1, 1, 14, 1 | metadata n10s |

**Relaciones:** `PERTENECE_A` (jerarquía), `SUMINISTRADO_POR` (con properties
`total_cantidad_historica`, `total_lineas_compra`, etc).

### Backup
- `backups/neo4j_data_20260428_232410.tar.gz` (9.78 MB) — backup pre-Bloque 3.

---

## 5. Resumen bloque por bloque

### Bloque 0 — Verificación v1
Solo verificación de salud. Sin cambios al código. (Ejecutado por la usuaria
sin compartir output completo, asumido OK.)

### Bloque 1 — Vocabulario OWL del dominio (TBox)
Construí `marketplace.ttl` con:
- **Clases dominio retail**: `:Producto`, `:Categoria`, `:Grupo`, `:SubSeccion`,
  `:Seccion`, `:Proveedor`, `:EventoComercial`, `:Stock`.
- **Subclases derivables**: `:ProductoCritico`, `:ProductoAltaRotacion`,
  `:ProductoPerecedero`, `:ProveedorExterior`, `:ProductoColdStart`,
  `:ProveedorLocal`.
- **Capa decisional**: `:Decision`, `:DecisionContext`, `:Algorithm`,
  `:AlgorithmRecommendation`, `:SimilarityScore`, `:TrendSignal`.
- **Capa deóntica**: `:Norm`, `:Obligation`, `:Permission`, `:Prohibition`
  (disjuntas vía `owl:AllDisjointClasses`).
- **Object properties** (con dom/rng + characteristics): `:perteneceA`
  (Transitive), `:suministradoPor`, `:tieneStock` (Functional), `:similarA`
  (Symmetric), `:aplicableA`, `:requiere`, `:prohibe`, `:permite`, `:obliga`,
  `:invocaAlgoritmo`, `:derivadaDe`, `:defeats` (Asymmetric).
- **Data properties** (con xsd types + Functional): `:sku`, `:cantidadStock`,
  `:enStock`, `:fechaUltimaCompra`, `:priority`, `:validFrom`, `:validTo`,
  `:defeasible`, `:similarityValue`, `:trendValue`.
- **Disjointness**: `:Producto disjointWith :Proveedor`,
  `:Decision disjointWith :Algorithm`, `:ProveedorLocal disjointWith :ProveedorExterior`.
- **Restricciones cardinality**: `:Producto sku min 1`, `:Stock cantidadStock exactly 1`,
  `:Norm priority exactly 1`, `:AlgorithmRecommendation derivadaDe min 1`.

**URI base**: `http://marketplace.com.py/onto/v1#` (versionada).
**Header**: `dcterms:created`, `dcterms:creator`, `owl:versionInfo`.

**Decisión clave de implementación**: `marketplace.ttl` (Turtle, fuente humana)
+ `marketplace.owl` (build artifact NTriples, generado por `build.py` con
rdflib). Owlready2 NO carga Turtle, solo RDF/XML / OWL/XML / NTriples.
Originalmente usé `pretty-xml` pero descubrí en Bloque 4 que drop-ea RDF Lists
silenciosamente — cambié a NTriples (`format="nt"`).

**Archivos**:
- `ontology_semantic/marketplace.ttl` (v1.2.0-bloque4 al cierre)
- `ontology_semantic/marketplace.owl` (build artifact NT)
- `ontology_semantic/build.py` (idempotente)
- `ontology_semantic/load_check.py` (smoke test reusable)
- `ontology_semantic/marketplace.owl.md` (justificación de cada clase + qué
  quedó afuera y por qué)
- `ontology_semantic/__init__.py`

### Bloque 2 — SHACL Shapes para validación
Creé 5 NodeShapes en `shapes.ttl` para validar grafos contra restricciones
runtime que OWL no expresa (regex, rangos numéricos, comparaciones cruzadas):

- `:ProductoShape` — `:sku` minCount 1 + datatype string + pattern
  alfanumérico `^[A-Z0-9_-]+$`; `:perteneceA` minCount 1 + sh:class
  `:Categoria`.
- `:ProveedorShape` — `:proveedorId` minCount 1, datatype string, minLength 1;
  `:pais` ISO-3166 alpha-2 `^[A-Z]{2}$`.
- `:NormShape` — `:priority` 0–100; `:validFrom` ≤ `:validTo`; modalidad ∈
  {Obligation, Permission, Prohibition} via `sh:or` con `sh:class`.
- `:DecisionShape` — requiere `prov:atTime` (xsd:dateTime), `:invocaAlgoritmo`
  (sh:class :Algorithm), `:razonamiento` (xsd:string, minLength 10).
- `:TrendSignalShape` — `:confianzaExtraccion` ∈ [0, 1].

**4 props nuevas en `marketplace.ttl`** para soportar las shapes: `:proveedorId`,
`:pais`, `:razonamiento`, `:confianzaExtraccion`. Bumpe a v1.1.0-bloque2.

**`validar.py`** con función `validar_grafo(rdf_path, shapes_path) -> ValidationReport`
+ CLI con exit codes (0 conforme, 1 violación, 2 args inválidos). Usa
`pyshacl.validate(..., inference='rdfs', advanced=True, meta_shacl=True)`.

**3 grafos de prueba** en `tests/data/`:
- `datos_validos.ttl` → conforme
- `datos_invalidos_producto.ttl` → 1 violación (sku faltante)
- `datos_invalidos_norma.ttl` → 1 violación (priority=200 fuera de rango)

Todos con outputs esperados, mensajes en español.

### Bloque 3 — Bridge Neo4j ↔ RDF con Neosemantics
Instalé n10s 5.26.0 en el Docker. Recreé el contenedor con env vars de seguridad
(antes no tenía `n10s.*` en allowlist). Datos preservados en volume nombrado.

**Decisión arquitectónica clave**: n10s 5.x **NO traduce SPARQL → Cypher**.
La arquitectura limpia es exportar Neo4j a un grafo rdflib in-memory y correr
SPARQL ahí. La fuente de verdad sigue siendo Neo4j; rdflib es cache derivado.

**`bridge.py`** con:
- `init_n10s()` — graphconfig.init + nsprefixes + 14 mappings OWL ↔ Neo4j
  (camelCase ↔ snake_case). Idempotente.
- `migrar_uris_v1()` — agrega `.uri` a los nodos existentes del v1 con patrón
  `mkt:<Label>/<id>`. Idempotente. Necesario para que n10s exporte. NO modifica
  properties existentes — `OntologyClient` v1 sigue funcionando igual.
- `importar_owl_a_neo4j(input_ttl)` — importa TBox OWL via `n10s.rdf.import.inline`.
- `exportar_a_rdf(salida_ttl)` — exporta el grafo Neo4j a Turtle.
  **Originalmente usaba `n10s.rdf.export.cypher`** pero el procedure tiene
  quirks con URIs que tienen `/` interno bajo SHORTEN. **Lo reemplacé por
  export manual** vía Cypher directo + mappings invertidos (más robusto, control
  total). En Bloque 4 agregué la **fase 3 de materialización**: para cada
  Producto emite `:tieneHistorial` (boolean), `:velocidad` (proxy =
  `total_cantidad_historica` sumado sobre aristas SUMINISTRADO_POR), y
  `:altaRotacion` (boolean = velocidad ≥ percentil 75 dinámico).
- `query_sparql(query, snapshot_path=None)` → `pd.DataFrame`. Si `snapshot_path`
  existe, parsea desde ahí; si no, exporta on-the-fly.

**`tests/test_bridge.py`** con 18 tests (mocks de Neo4j driver), todos OK:
decode RDF terms, SPARQL→DataFrame, credenciales faltantes, init idempotency,
export triples assembly, mapping constants.

**Resultados del Bloque 3**:
- snapshot.ttl: 73.701 tripletas (después del Bloque 4 con features
  materializadas: 87.630).
- SPARQL count `mkt:Producto` = 4.643 = Cypher count (coincidencia exacta).

**Mappings registrados en n10s** (OWL camelCase → Neo4j snake_case/SCREAMING):
```
:Producto         ↔ Producto
:Categoria        ↔ Categoria
:Grupo            ↔ Grupo
:SubSeccion       ↔ SubSeccion
:Seccion          ↔ Seccion
:Proveedor        ↔ Proveedor
:EventoComercial  ↔ EventoComercial
:perteneceA       ↔ PERTENECE_A
:suministradoPor  ↔ SUMINISTRADO_POR
:sku              ↔ sku
:cantidadStock    ↔ cantidad_stock
:enStock          ↔ en_stock
:fechaUltimaCompra ↔ fecha_ultima_compra
:pais             ↔ pais
:perecedero       ↔ perecedero          (agregado Bloque 4)
:esExterior       ↔ proveedor_exterior  (agregado Bloque 4)
```

**Documentación**: `ontology_semantic/README_n10s.md` con comandos Docker
exactos, justificación de graphconfig flags, troubleshooting.

### Bloque 4 — Razonador HermiT y enriquecimiento por inferencia
Extendí `marketplace.ttl` (v1.2.0-bloque4) con:
- **5 data properties**: `:perecedero`, `:altaRotacion`, `:velocidad` (decimal),
  `:tieneHistorial`, `:esExterior`. Todas Functional.
- **1 clase**: `:ProveedorLocal` (subClass `:Proveedor`).
- **6 axiomas equivalentClass** (necesarios para que HermiT clasifique):
  - `:ProductoPerecedero ≡ :Producto ⊓ ∃:perecedero.{true}`
  - `:ProductoAltaRotacion ≡ :Producto ⊓ ∃:altaRotacion.{true}`
  - `:ProductoCritico ≡ :Producto ⊓ (:ProductoPerecedero ⊔ :ProductoAltaRotacion)`
  - `:ProductoColdStart ≡ :Producto ⊓ ∃:tieneHistorial.{false}`
  - `:ProveedorExterior ≡ :Proveedor ⊓ ∃:esExterior.{true}`
  - `:ProveedorLocal ≡ :Proveedor ⊓ ∃:esExterior.{false}`
- **Disjointness**: `:ProveedorLocal disjointWith :ProveedorExterior`.

**`reasoner.py`** con:
- `cargar_onto_con_abox(snapshot_ttl, abox_data)` — carga TBox + ABox en un
  World owlready2.
- `run_hermit(world, infer_property_values=False)` → `ReasoningResult` con
  tiempo, consistencia, mensaje opcional.
- `listar_inferencias(world)` → `InferenceReport` con counts por clase derivada
  (usa `cls.instances()` de owlready2, NO `as_rdflib_graph()` que no refleja
  inferencias).
- `persist_to_neo4j(world)` — escribe inferencias de vuelta a Neo4j marcando
  `is_inferred_<Clase>=true` en cada nodo.
- CLI: `run`, `run-and-persist`.

**Tests `tests/test_reasoner.py` — 6/6 OK con HermiT real**:
1. 5 productos sintéticos → 5 ProductoCritico ✓
2. 3 ProductoPerecedero + 3 ProductoAltaRotacion (con 1 overlap) ✓
3. 1 producto sin historial → 1 ProductoColdStart ✓
4. Los otros 3 NO son ColdStart ✓
5. Proveedor con `:ProveedorLocal` + `esExterior=true` → `OwlReadyInconsistentOntologyError` ✓
6. Timing < 30s sobre 5 productos ✓

**Resultados sobre datos reales (subset 10 productos = 238 tripletas)**:
| Clase | Cantidad |
|---|---:|
| ProductoCritico | 3 |
| ProductoPerecedero | 1 |
| ProductoAltaRotacion | 3 |
| ProductoColdStart | 10 |
| ProveedorExterior | 2 |
| ProveedorLocal | 1 |

**Tiempo subset**: 2.33s. **Full run cancelado** (HermiT escala mal sobre 87k
tripletas + SROIQ). Para producción se recomienda razonador EL++ o SHACL rules
(Bloque 5).

### Bugs encontrados durante Bloque 4 (importante para no repetir)

1. **`xsd:date` no soportado por HermiT** → cambiar todo a `xsd:dateTime`.
   `bridge.py` agrega `T00:00:00` a fechas Date sin hora antes de emitir.
2. **rdflib `pretty-xml`/`xml` drop-ean RDF Lists** silenciosamente → solo 1 de
   6 equivalentClass sobrevivían. Cambié `build.py` a `format="nt"`.
3. **Owlready2 require `with onto:` para parsear ABox via rdflib** → envolví
   los parses.
4. **`:sku` declared `xsd:string` pero Neo4j lo trae como integer** → set
   `force_string_props = {"sku", "proveedorId", "pais", "ruc", "email", "nombre", "telefono", "razonamiento"}` en `bridge.py` que convierte a `str()` antes de
   emitir.

---

## 6. Arquitectura del sistema (al final del Bloque 4)

```
                    ┌─────────────────────────────────┐
                    │   Pegasus (SQL Server, v1)      │  ← fuente original
                    └────────────┬────────────────────┘
                                 │ ETL v1 (CSVs + cargar_datos.py)
                                 ▼
                    ┌─────────────────────────────────┐
                    │   Neo4j 5.26.25 (Docker)        │  ← fuente de verdad operacional
                    │   + Neosemantics 5.26.0         │
                    │   - 4643 productos + grafo      │
                    │   - .uri en cada nodo           │
                    │   - _GraphConfig, _MapDef,...   │
                    └─────┬───────────────────────────┘
                          │ bridge.exportar_a_rdf()
                          │ (Cypher + mappings + materialización fase 3)
                          ▼
                    ┌─────────────────────────────────┐
                    │   data/snapshot.ttl             │
                    │   87.630 tripletas RDF/Turtle   │
                    │   (ABox derivada)               │
                    └─────┬───────────────────────────┘
                          │ rdflib parse
                          │ + owlready2 load TBox marketplace.owl
                          ▼
                    ┌─────────────────────────────────┐
                    │   World owlready2               │
                    │   (TBox + ABox)                 │
                    └─────┬───────────────────────────┘
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
       ┌─────────────┐        ┌─────────────┐
       │ HermiT       │        │ rdflib      │
       │ (inferencia) │        │ SPARQL      │
       └──────┬───────┘        └──────┬──────┘
              │                       │
              │  reasoner.persist     │  query_sparql() → pd.DataFrame
              ▼                       ▼
       ┌─────────────────────────────────────┐
       │   Vuelve a Neo4j marcado            │
       │   is_inferred_ProductoCritico=true  │
       │   is_inferred_ProveedorExterior=... │
       └─────────────────────────────────────┘

Validación SHACL paralela:
       data/* + shapes.ttl ──► pyshacl.validate ──► ValidationReport
```

### Capas conceptuales

1. **Capa fuente** (NO se toca): Pegasus → Neo4j v1 con `OntologyClient`.
2. **Capa semántica TBox** (Bloque 1+4): `marketplace.ttl` define vocabulario
   formal OWL 2 DL.
3. **Capa de validación SHACL** (Bloque 2): `shapes.ttl` valida datos runtime.
4. **Capa de bridge** (Bloque 3): `bridge.py` traduce Neo4j ↔ RDF.
5. **Capa de razonamiento** (Bloque 4): `reasoner.py` corre HermiT y materializa
   inferencias en Neo4j.
6. **Capa deóntica defeasible** (Bloque 5 — pendiente).

---

## 7. APIs públicas estables (para consumidores)

```python
# Cliente v1 (NO TOCAR — Mauri/Mati/Cris ya lo usan)
from ontology import OntologyClient

# Capa semántica nueva
from ontology_semantic.bridge import (
    init_n10s, migrar_uris_v1,
    importar_owl_a_neo4j, exportar_a_rdf, query_sparql,
)
from ontology_semantic.reasoner import (
    cargar_onto_con_abox, run_hermit,
    listar_inferencias, persist_to_neo4j,
)
from ontology_semantic.validar import validar_grafo
```

### CLIs disponibles

```powershell
# Build TBox (cuando se modifica marketplace.ttl)
python -m ontology_semantic.build

# Smoke test de la TBox
python -m ontology_semantic.load_check

# Validar grafo SHACL
python -m ontology_semantic.validar tests\data\datos_validos.ttl

# Bridge Neo4j
python -m ontology_semantic.bridge init
python -m ontology_semantic.bridge migrar-uris
python -m ontology_semantic.bridge importar ontology_semantic\marketplace.ttl
python -m ontology_semantic.bridge exportar data\snapshot.ttl
python -m ontology_semantic.bridge sparql "<query>" data\snapshot.ttl

# Razonador
python -m ontology_semantic.reasoner run data\snapshot.ttl
python -m ontology_semantic.reasoner run-and-persist data\snapshot.ttl
```

### Tests

```powershell
python -m unittest tests.test_bridge -v       # 18/18 OK
python -m unittest tests.test_reasoner -v     # 6/6 OK
python -m ontology_semantic.validar tests\data\datos_validos.ttl    # exit 0
python -m ontology_semantic.validar tests\data\datos_invalidos_producto.ttl  # exit 1
python -m ontology_semantic.validar tests\data\datos_invalidos_norma.ttl     # exit 1
```

---

## 8. Convenciones de naming y URIs

- **Namespace OWL**: `http://marketplace.com.py/onto/v1#` (prefix `:` o `mkt:`).
- **Clases**: PascalCase (`:Producto`, `:ProductoCritico`).
- **Object properties / Data properties**: camelCase (`:perteneceA`, `:cantidadStock`).
- **URIs de individuos**: `mkt:<Label>/<id>` (ej. `mkt:Producto/107966`).
- **Neo4j labels**: PascalCase (`Producto`).
- **Neo4j relationships**: SCREAMING_SNAKE (`PERTENECE_A`).
- **Neo4j properties**: snake_case (`cantidad_stock`).
- Los **mappings n10s** puentean camelCase ↔ snake_case automáticamente.

---

## 9. Estructura de archivos al final del Bloque 4

```
tarea1-ontologia-rag/
├── .env                           # NEO4J_*, SQLSERVER_*
├── README.md                      # del v1
├── requirements.txt               # con owlready2==0.50, rdflib==7.6.0,
│                                  #      pyshacl==0.31.0, neo4j==5.20.0
├── backups/
│   └── neo4j_data_20260428_232410.tar.gz   # backup pre-Bloque 3
├── neo4j_plugins/
│   └── neosemantics-5.26.0.jar
├── ontology/                      # v1 — NO TOCAR
│   ├── client.py                  # OntologyClient (estable)
│   ├── schema.cypher
│   └── ...
├── rag/                           # v1 — NO TOCAR
│   └── client.py                  # RAGClient (estable)
├── data/
│   ├── *.csv                      # del v1
│   ├── snapshot.ttl               # 87.630 triples (último export)
│   ├── snapshot_subset10.ttl      # subset 10 productos para tests rápidos
│   └── _dbg_*.nt, _no_*.ttl       # archivos de debug (se pueden borrar)
├── ontology_semantic/             # NUEVA capa (Bloques 1-4)
│   ├── __init__.py
│   ├── marketplace.ttl            # v1.2.0-bloque4 (TBox fuente humana)
│   ├── marketplace.owl            # build artifact NTriples
│   ├── marketplace.owl.md         # documentación de cada clase
│   ├── shapes.ttl                 # 5 NodeShapes SHACL
│   ├── build.py                   # ttl → NT
│   ├── load_check.py              # smoke test TBox
│   ├── validar.py                 # API SHACL + CLI
│   ├── bridge.py                  # API Neo4j↔RDF + CLI (5 subcomandos)
│   ├── reasoner.py                # API HermiT + CLI (2 subcomandos)
│   └── README_n10s.md             # docs Docker + n10s setup
├── tests/
│   ├── test_smoke.py              # del v1
│   ├── test_bridge.py             # 18 tests con mocks (Bloque 3)
│   ├── test_reasoner.py           # 6 tests con HermiT real (Bloque 4)
│   └── data/
│       ├── datos_validos.ttl
│       ├── datos_invalidos_producto.ttl
│       └── datos_invalidos_norma.ttl
├── debug_axioms.py, debug_axioms2.py, debug_props.py   # scripts de debug
│                                                       # (se pueden borrar)
└── venv/                          # Python 3.12 venv
```

---

## 10. Lo que falta (Bloque 5 y posteriores)

- **Bloque 5** — lógica deóntica defeasible: `:defeats`, prioridades,
  resolución de conflictos entre normas. Probable uso de **SHACL rules**
  (más rápido que HermiT para production batch).
- **Bloque 6+** — similitud ponderada para cold-start (ChromaDB +
  sentence-transformers reusados del v1).
- **Bloque 7** — dispatcher que conecta DecisionContext → Algorithm
  recommendation usando todo lo anterior.
- **PROV-O** integration para trazabilidad completa.

---

## 11. Limitaciones / TODOs conocidos

1. **HermiT no escala al full grafo (4643 productos / 87k tripletas)**.
   Recomendación: precomputar inferencias batch (ya está implementado en
   `persist_to_neo4j`) + opción EL++ en Bloque 5.
2. **`:velocidad` es proxy provisorio** (`total_cantidad_historica` sumado).
   Cuando Cris/Mauri integren VENTAS_DET reales al grafo, refinar la fórmula
   sin tocar reasoning.
3. **`force_string_props` es lista hardcoded** en `bridge.py`. Mejor: leer el
   TBox para inferir datatypes esperados automáticamente.
4. **El sandbox de mi entorno tenía sync issues con archivos** — la usuaria a
   veces vio truncamientos parciales. En su Windows es estable. Si pasa
   parcialmente, re-correr el comando suele arreglar.

---

## 12. Para arrancar Bloque 5 con contexto fresco

Confirmá al nuevo chat:
1. Que leyó este handoff y tiene contexto.
2. Que va a respetar las reglas de trabajo (ítem 3 arriba).
3. Que va a empezar con la enseñanza didáctica antes de codear.
4. Que va a verificar pre-condiciones y esperar tu go antes de cada acción.

Después le pegás el prompt del Bloque 5.

---

**Fin del handoff. Última actualización: cierre del Bloque 4.**
