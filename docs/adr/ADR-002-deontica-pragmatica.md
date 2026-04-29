# ADR-002 — Deóntica pragmática (no SDL formal, no Nute completo)

**Status**: Accepted (Bloque 6)

## Context

El sistema necesita razonamiento normativo: hay obligaciones (O), permisos (P)
y prohibiciones (F) que aplican a las decisiones de compra/reposición. Las
opciones formales tienen problemas conocidos:

1. **Standard Deontic Logic (SDL)** sufre paradojas:
   - Paradoja de Ross: `O(p) ⊨ O(p ∨ q)` permite derivar "obligatorio mandar
     reporte O quemar el depósito" desde "obligatorio mandar reporte".
   - Paradoja del Buen Samaritano: `O(ayudar(x) ∧ asaltado(x)) ⊨ O(asaltado(x))`
     deriva la obligación del prerrequisito fáctico.
   - En un sistema con dinero real, esas inferencias son legalmente
     indefendibles.
2. **Defeasible Deontic Logic completa** (Nute, Governatori) resuelve las
   paradojas pero las herramientas Python son inmaduras (proyectos académicos
   sin mantenimiento, dependencias rotas, latencia alta).
3. **Hardcoded en Python** (if/else): no auditable por compliance, no editable
   sin redeploy, no diff-friendly.

El operador del marketplace navideño y el equipo de auditoría/compliance
necesitan algo que: (a) sea rápido (decisiones por minuto, no por segundo),
(b) sea auditable, (c) maneje excepciones documentadas, (d) levante errores
en lugar de silenciar conflictos.

## Decision

**Middle ground pragmático**: vocabulario OWL para las normas + resolver
Python imperativo con prioridades + relación `:defeats` explícita.

- **Vocabulario en TBox** (`marketplace.ttl`):
  `:Obligation`, `:Permission`, `:Prohibition` como subclases de `:Norm`,
  declaradas `owl:AllDisjointClasses`. Propiedades: `:priority` (int 0-100),
  `:validFrom`, `:validTo`, `:defeasible`, `:defeats` (asimétrica).
- **ABox de normas** en `normas_marketplace.ttl`: 11 normas instanciadas
  con campos custom `:appliesWhen` (string que apunta a un predicado Python
  registrado), `:target` (etiqueta de conflicto), `:source` (justificación
  de negocio).
- **Resolver imperativo** en `deontic/resolver.py` con pipeline de 5 pasos:
  filtrar por vigencia (`validFrom <= now <= validUntil`) → filtrar por
  aplicabilidad (predicado Python) → aplicar `:defeats` explícitos → detectar
  conflictos por `target` compartido (O-F y F-P) → resolver por prioridad
  numérica.
- **Anti-paradoja**: NO hay cierre lógico — el resolver evalúa solo las
  normas aplicables al contexto concreto. La paradoja de Ross requiere que el
  sistema derive `O(p ∨ q)` desde `O(p)`, lo cual nuestro resolver no hace.
- **Conflictos irresolubles** (empate de prioridad sin `:defeats`) levantan
  `UnresolvedDeonticConflict` explícita. NO se silencian.
- **Predicados sandbox**: registry pattern con `@register_predicate("nombre")`
  decorator. El TTL referencia por nombre, NUNCA `eval()` sobre código del
  TTL.

## Consequences

**Positivas:**

- 11 normas reales del dominio (perecederos, presupuesto, proveedor exterior
  nuevo, cold-start, temporada pico, etc) modeladas y testeadas con 24 tests
  verdes.
- Compliance officer puede leer `normas_marketplace.ttl` y entender la
  política sin saber Python.
- Conflictos como "norma N1 prohíbe X pero P5 permite excepción" se resuelven
  via `:defeats` explícito documentado en TTL — auditable en git diff.
- Latencia de evaluación: `evaluar(decision, contexto)` corre en <5ms para
  el catálogo actual.
- Audit JSONL append-only del resolver (`data/deontic_audit.jsonl`) registra
  cada evaluación con razonamiento legible.

**Negativas:**

- No capturamos toda la riqueza de DDL: por ejemplo, la noción de "razón a
  favor vs razón en contra" de Carneades, o conflictos de tres-vías
  (O-F-P simultáneo) más allá de los pares O-F y F-P.
- El operador puede agregar normas que técnicamente generan paradojas
  conceptuales (ej: una P que defeats una F estricta, generando ambigüedad
  sobre si una decisión está permitida). El resolver las cacha con
  `UnresolvedDeonticConflict` pero no previene la situación a priori.
- Las prioridades numéricas (0-100) son arbitrarias y requieren disciplina
  del equipo para mantener la escala coherente. Documentado como TODO en el
  HANDOFF.

**Trade-off aceptado**: completitud teórica por predictibilidad operacional.

## Alternatives Considered

1. **SDL completo via razonador OWL** (ej: con DL-Safe rules en HermiT):
   técnicamente posible pero hereda las paradojas y no escala.
2. **deontica-engine, Carneades, ASPIC+**: investigación académica pura;
   Python wrappers inmaduros; latencia 1-10s por evaluación.
3. **Reglas en código Python con if/else**: rápido y testeable pero la
   política queda ofuscada en la implementación; cambiar una norma requiere
   PR y deploy.
4. **YAML solo (sin OWL TBox)**: pierde la integración con el resto del
   ecosistema semántico (SHACL, razonador, queries SPARQL del audit).

La elección actual mantiene las normas como "datos primera clase" en el
ecosistema RDF (consultables, validables) **y** las hace evaluables en
runtime con un resolver predecible.

## Pointers al código

- `deontic/norm.py` — dataclasses `Norm/Obligation/Permission/Prohibition` frozen.
- `deontic/predicates.py` — registry `@register_predicate`.
- `deontic/predicados_marketplace.py` — 11 predicados concretos del dominio.
- `deontic/resolver.py` — `DeonticResolver.evaluar()`.
- `ontology_semantic/normas_marketplace.ttl` — 11 normas + 1 par `:defeats`.
- `tests/test_deontic.py` — 24 tests cubriendo conflicto, defeasibility, vigencia.
