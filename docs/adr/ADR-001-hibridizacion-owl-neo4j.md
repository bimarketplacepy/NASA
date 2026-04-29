# ADR-001 — Hibridización OWL + Neo4j

**Status**: Accepted (Bloque 3, refinado en Bloque 4 y 5)

## Context

El sistema decisional necesita dos cosas a la vez:

1. **Razonamiento formal** sobre clases (disjointness `:Producto ⊓ :Proveedor = ∅`,
   subsunción de `:ProductoCriterio` desde axiomas equivalentClass, validación
   SHACL de cardinalidades) — propiedades nativas de la familia OWL/RDF.
2. **Queries operacionales rápidas** sobre 4.643 productos + 32.861 aristas
   `:SIMILAR_A` + 61 proveedores en runtime, sin esperar 30+ segundos por
   cada pregunta — propiedad nativa del property graph.

Ningún sistema único satisface las dos restricciones bien:

- Triple stores puros (Apache Jena, GraphDB) razonan formalmente pero las
  queries SPARQL sobre millones de triples tienen latencia inaceptable
  para uso operacional sin tuning fuerte.
- Neo4j puro es muy rápido para queries Cypher, pero no entiende
  `owl:disjointWith` ni infiere clases derivadas.

## Decision

**Doble representación con sincronización via bridge n10s (neosemantics)**.

- **TBox** (clases, propiedades, axiomas) en Turtle: `ontology_semantic/marketplace.ttl`,
  versionado en git, editado a mano. Es la fuente de verdad del **schema**.
- **ABox** (instancias) primariamente en Neo4j: 4.643 productos + relaciones
  cargadas desde Pegasus. Es la fuente de verdad de los **datos operacionales**.
- **Bridge** `ontology_semantic/bridge.py` que sincroniza:
  - `importar_owl_a_neo4j(ttl_path)` materializa el TBox + features derivadas
    (`:altaRotacion`, `:tieneHistorial`, etc) como propiedades de los nodos.
  - `exportar_a_rdf(...)` produce un snapshot Turtle (87.630 triples) sobre el
    cual corre HermiT in-memory para razonamiento batch.
- **Razonamiento HermiT** (Bloque 4) se ejecuta sobre el snapshot RDF, no sobre
  Neo4j directo. Las clases inferidas (`:ProductoCritico`, `:ProductoColdStart`,
  etc) se persisten de vuelta a Neo4j como labels via `persist_to_neo4j`.

## Consequences

**Positivas:**

- El equipo de Tarea 4 (algoritmos) consulta Neo4j directo via `OntologyClient`
  y obtiene latencia sub-100ms por SKU, sin saber nada de OWL.
- El razonamiento formal ocurre offline en batches; el output (clases inferidas)
  alimenta runtime sin pagar el costo en cada query.
- SHACL valida el grafo periódicamente (`python -m ontology_semantic.validar`)
  detectando violaciones de schema antes de que rompan el dispatcher.
- El motor de similitud (Bloque 5) y el dispatcher (Bloque 7) acceden por
  `OntologyClientV2` que es drop-in del v1 — el equipo no se tiene que enterar
  de la complejidad interna.

**Negativas:**

- El bridge requiere mantenimiento: cada vez que cambia el TBox o se agrega
  feature derivada, hay que actualizar `bridge.py`. Documentado en el HANDOFF.
- HermiT no escala al full grafo (4.643 productos + relaciones). En el Bloque
  4 se documentó: el razonamiento se hace sobre subsets representativos o sobre
  el snapshot de un día específico.
- Doble representación implica doble lugar donde algo puede divergir. Se
  mitiga con: idempotencia en el import (n10s `MERGE`), tests SHACL en CI,
  y el HANDOFF explica las invariantes cross-store.

## Alternatives Considered

1. **GraphDB / Stardog** (triple stores con queries optimizadas): ambos son
   pagos para uso comercial; curva de aprendizaje del equipo más empinada;
   el equipo ya tenía Neo4j productivo.
2. **RDFox**: razonador rápido + queries OK, pero comercial, sin community
   edition práctica para nuestro caso.
3. **Solo Neo4j con GDS (Graph Data Science)**: cubre similarity y
   pathfinding, pero no infiere clases formales, y modelar disjointness vía
   constraints en Cypher es frágil.
4. **Solo OWL/Jena con cache de queries**: latencia se reduce con cache
   pero no llega al rango operacional (50-100ms); además, las consultas del
   dispatcher son muy variadas, mal candidato para cache.

La hibridización gana en costo total: el desarrollo del bridge y la deuda
técnica documentada son menores que el riesgo de elegir un único sistema
inadecuado para una de las dos cargas de trabajo.

## Pointers al código

- `ontology_semantic/marketplace.ttl` — TBox.
- `ontology_semantic/bridge.py` — `init_n10s`, `importar_owl_a_neo4j`, `exportar_a_rdf`, `query_sparql`.
- `ontology_semantic/reasoner.py` — `cargar_onto_con_abox`, `run_hermit`, `persist_to_neo4j`.
- `ontology_semantic/validar.py` — CLI SHACL.
- `tests/test_bridge.py`, `tests/test_reasoner.py`.
