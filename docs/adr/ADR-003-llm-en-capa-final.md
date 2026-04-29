# ADR-003 — LLM en la capa final, nunca en el path crítico

**Status**: Accepted (Bloque 9 scraper, Bloque 10 explainer)

## Context

Hay dos lugares donde un LLM podría intervenir en el sistema:

1. **Path crítico**: el LLM evalúa contexto, decide algoritmo, genera
   recomendación. Modelo *LLM-as-decisor*.
2. **Path final**: la decisión ya está tomada deterministicamente por
   deóntica + dispatcher + audit; el LLM SOLO traduce esa decisión formal
   a prosa legible para el operador. Modelo *LLM-as-traductor*.

Riesgos generales del LLM:

- **Alucinación**: inventa números, productos, normas. En retail con dinero
  real, eso es responsabilidad legal.
- **No determinismo**: misma input, distintos outputs (incluso con
  `temperature=0`, hay variación entre versiones del modelo). Rompe replay
  y contrafactual del Bloque 8.
- **Costo**: 1-10 centavos por call en tokens.
- **Latencia**: 1-5 segundos vs los 50ms del dispatcher.

## Decision

**LLM solo como traductor**, en la capa final, asíncrono y opcional.

Tres usos del LLM en este sistema, todos en la **capa de presentación**:

1. **Scraper de tendencias** (Bloque 9, vía cliente Mateo): LLM (Gemini 2.5
   Flash) extrae trends viralizables desde posts crudos de redes. Output =
   datos. Después la decisión sobre qué hacer con esos trends la toma el
   dispatcher determinista (Bloque 7).
2. **Explainer de decisiones** (Bloque 10): LLM (Anthropic Claude o
   Gemini, configurable) traduce una decisión PROV-O del audit log a 2-3
   oraciones legibles. La decisión NO cambia.
3. **Cold-start de SKU nuevo** (Bloque 5): el motor de similitud usa
   embeddings (`paraphrase-multilingual-MiniLM-L12-v2`) para encontrar
   productos similares. Esto NO es un LLM generativo — es vectorizado, sin
   alucinación posible.

**Garantías de seguridad** del explainer (`llm/explainer.py`):

- **Detector de alucinación de números**: extrae set de números del prompt
  vs set de números del output del LLM. Si `output \ prompt ≠ ∅`, rechaza
  la explicación y cae a fallback determinístico.
- **Fallback determinístico**: si el LLM falla (timeout, API error, alucina),
  `_fallback_prosa()` genera una explicación literal desde la decisión.
- **El LLM NO toca la base**: recibe solo el prompt construido por
  `PromptBuilder`. No tiene acceso a Neo4j, audit log, dispatcher.
- **Cap de tokens output**: 250 max para forzar concisión.
- **Temperatura 0**: minimiza variabilidad (no la elimina, pero la baja).

## Consequences

**Positivas:**

- Las decisiones del sistema siguen siendo deterministas, reproducibles,
  auditables. El LLM es UX, no responsabilidad.
- Si removés el explainer LLM, el sistema sigue tomando decisiones
  correctas — el operador solo pierde la explicación bonita, recupera la
  versión literal del fallback.
- El scraper LLM produce datos, que pasan después por capas
  deterministas de validación (SHACL, schema check, stop-words, triage de
  confianza). El LLM no tiene la última palabra.
- Test de alucinación (`tests/test_explainer.py::test_llm_alucina_numero_falso_se_rechaza`)
  inyecta un número falso ("5000 unidades inventadas") en una respuesta
  mockeada del LLM y verifica que el detector lo cacha y devuelve fallback.

**Negativas:**

- Costo recurrente: cada decisión que se explica vía LLM consume tokens.
  Mitigación: explainer es opt-in, se llama solo cuando el operador abre
  el dashboard.
- El detector de alucinación cubre números, no nombres. Si el LLM inventa
  una norma `F_inventada_xxx`, queda fuera de las citas pero no rechaza la
  explicación. Documentado como TODO en HANDOFF.
- El scraper LLM puede producir trends ambiguos. El triage por
  `confianza_extraccion < 0.4` los manda a `manual_review` en lugar de
  auto-procesar.

**Trade-off aceptado**: latencia y costo en el border layer por explicación
rica, manteniendo el core determinista.

## Alternatives Considered

1. **LLM como decisor central**: sería rápido de implementar pero pierde
   garantías de auditabilidad, reproducibilidad y compliance. Inviable
   en retail con dinero real y normativa DNCP/SET.
2. **Sin LLM, prosa solo por templates**: viable pero las explicaciones se
   vuelven repetitivas, no se adaptan al contexto, y ante decisiones
   complejas (cold-start con bloqueo deóntico parcial) los templates
   crecen mucho.
3. **LLM en una capa intermedia** (ej: ranking de algoritmos candidatos):
   contamina las garantías del Bloque 7. Si el LLM influye en qué
   algoritmo se elige, perdemos reproducibilidad del replay del Bloque 8.

## Pointers al código

- `llm/explainer.py` — `explicar()`, `PromptBuilder`, `detectar_alucinacion()`,
  `_fallback_prosa()`.
- `llm/templates/explainer.txt` — prompt template con sustitución
  `string.Template`.
- `clients/llm_client.py` — `GeminiLLMClient` real + `HeuristicLLMClient`
  fallback offline + retry exponencial para errores transitorios (503/429).
- `tests/test_explainer.py` — 19 tests incluyendo alucinación + fallback.
