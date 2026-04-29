# ADR-004 — Rules declarativas en YAML, no en código

**Status**: Accepted (Bloque 7)

## Context

El dispatcher de algoritmos (`dispatcher/dispatcher.py`) mapea cada
`DecisionContext` a una combinación de descriptores de algoritmos del paper
de robust optimization. Esa lógica de selección — qué regla dispara para qué
perfil de SKU — cambia con frecuencia operativa:

- Equipo de Mauri/Mati (Tarea 4) calibra parámetros de EWMA y descubre que
  `α=0.20` da mejores resultados para SKUs volátiles que el `0.25` original.
- Compliance pide que los SKUs nuevos con cold-start confianza < 0.5 vayan
  obligatoriamente a revisión humana — esto requiere agregar una nueva
  regla.
- En temporada navideña el operador quiere relajar el threshold de evento
  próximo de 28 a 35 días.

Si la lógica vive en código Python (if/else):

- Cada cambio requiere un PR con review técnico, build, test, deploy.
- El compliance officer no puede leer ni firmar la lógica.
- Cambios en hot-path requieren restart del servicio.
- El audit del cambio queda en `git log` del repo de código, separado del
  audit del comportamiento del sistema.

## Decision

**`config/dispatcher_rules.yaml`** es la fuente de verdad declarativa.
Esquema validado con **Pydantic v2**. Condiciones evaluadas con un
**AST evaluator restringido** (sin `eval()`). 9 reglas iniciales cubriendo
los escenarios del proyecto: SKU establecido estable/volátil/historia
corta, cold-start con/sin similar, trend signal alta/baja confianza, evento
próximo, fallback.

Estructura de cada regla:

```yaml
- id: regla_001_existing_estable
  nombre: "SKU establecido con baja volatilidad..."
  prioridad: 90
  cuando:
    - "context.tipo_sku == 'existing'"
    - "context.semanas_historia >= 52"
    - "context.volatilidad_forecast < 0.3"
  algoritmo: "affine_ordering_policy + ewma_smoothing + bounded_deviations + simple_absolute_deviation + dynamic_control_framing"
  parametros:
    ewma_smoothing:
      alpha: 0.15
    bounded_deviations:
      epsilon_factor: 1.5
  confianza: 0.90
```

**Decisiones de diseño**:

- **Schema con Pydantic** (`dispatcher/rules.py:RuleSchema`): valida tipos,
  rangos (`prioridad ∈ [0, 100]`, `confianza ∈ [0, 1]`), `extra="forbid"`
  rechaza fields desconocidos.
- **Validación semántica adicional**: descriptor inexistente, dos
  descriptores del mismo `kind`, expresiones inseguras. Errores agrupados
  (no fail-on-first) — el operador ve TODOS los problemas en una pasada.
- **Sintaxis tipo Python en `cuando`** (`context.tipo_sku == 'existing'`):
  familiar para el equipo, expresiva, pero **NO se ejecuta con `eval()`**.
  El `SafeExpressionEvaluator` (`dispatcher/conditions.py`) parsea con
  `ast.parse(mode='eval')`, valida que solo haya nodos del whitelist
  (`Compare`, `BoolOp`, `Attribute`, `Subscript`, `Call` solo a `len/min/max/...`),
  y recorre el AST manualmente con dispatch por tipo. Rechaza dunders
  (`context.__class__`), lambdas, comprehensions, imports.
- **Templates en parámetros** (`heredar_de_sku: "{{ context.similar_top_sku }}"`):
  resueltos en runtime con el mismo evaluator seguro.
- **Forma B de combinación** (lista de stages tipados por `kind`): el
  shorthand `"a + b + c"` se parsea a `[a, b, c]` y se valida que cada uno
  exista en el catálogo y que no haya dos del mismo `kind`.
- **First-match-wins por prioridad descendente**: orden estable; en empate
  gana el que aparece primero en YAML.

## Consequences

**Positivas:**

- Compliance/product owner puede leer las 9 reglas en `config/dispatcher_rules.yaml`
  sin saber Python.
- Cambiar `epsilon_factor` de 1.5 a 1.8 es editar una línea + commit. No
  requiere build ni redeploy si el dispatcher se reinicia con `--reload`
  (TODO: hot-reload pendiente, deuda documentada).
- Audit del cambio: `git log config/dispatcher_rules.yaml` muestra
  exactamente cuándo y quién cambió qué regla.
- Tests de rules (`tests/test_dispatcher.py::TestRulesYAMLValidacion`): 8
  casos verifican que id duplicado, descriptor inexistente, condición
  insegura, template inseguro, prioridad fuera de rango, etc levantan
  `RulesYAMLInvalido` con mensaje accionable.
- Rule explosions controladas: el schema previene que un YAML malo lleve
  el dispatcher a un estado inconsistente.

**Negativas:**

- Curva de aprendizaje: el equipo tiene que conocer la sintaxis de
  expresiones permitidas (no es Python completo).
- El validator tiene su propia complejidad (~200 LOC en
  `dispatcher/conditions.py`). Compensado: cubierto por 10 tests
  (`TestSafeExpressionEvaluator`).
- Las reglas pueden ser difíciles de testear individualmente — un
  cambio en `regla_001` puede afectar SKUs que antes caían en `regla_002`
  por orden de prioridad. Mitigación: `tests/test_dispatcher.py`
  verifica los 3 escenarios canónicos del proyecto + casos edge de
  prioridad.

**Trade-off aceptado**: agregamos una capa de schema/parser por la
flexibilidad operativa. Vale la pena cuando hay >5 reglas y >2 equipos
tocando el sistema.

## Alternatives Considered

1. **Reglas en Python (if/else)**: rápido de implementar, pero ya
   discutido — bloquea a compliance, requiere deploy.
2. **JSON Logic** (jsonlogic / JEXL / similares): sintaxis prefix
   funcional (`{">=": [{"var": "context.semanas_historia"}, 52]}`) menos
   legible que `context.semanas_historia >= 52`.
3. **Drools / Decision Tables**: industria-estándar pero overhead de
   integrar JVM en stack Python; el proyecto ya estaba 100% Python.
4. **DSL custom**: overkill para 9 reglas iniciales; reinventar pydantic
   + AST.
5. **simpleeval o asteval**: librerías de safe-eval más maduras que mi
   implementación. Descartadas por agregar dep externa cuando un AST
   visitor de 200 LOC alcanza y queda completamente bajo nuestro control.

## Pointers al código

- `config/dispatcher_rules.yaml` — 9 reglas declarativas.
- `dispatcher/rules.py` — `RuleSchema` Pydantic + `load_rules()` con
  validación semántica.
- `dispatcher/conditions.py` — `SafeExpressionEvaluator` AST whitelist.
- `dispatcher/algorithms.py` — catálogo de descriptores con `Kind` enum.
- `tests/test_dispatcher.py` — 42 tests cubriendo schema, evaluator,
  templates, first-match.
