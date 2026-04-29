# Catálogo de algoritmos — Biblioteca de Optimización (Tarea 4)

Documentación de los 6 algoritmos disponibles en `optimization/algorithms/`.

El **dispatcher de Abi (Bloque 7)** consulta este catálogo y elige cuál invocar
según el contexto del SKU. Cada algoritmo cumple el contrato común
`IAlgorithm` (definido en `optimization/schemas.py`) y devuelve siempre una
`RecomendacionCompra` con uncertainty intervals (p5/p50/p95), VaR y CVaR.

> **Importante:** ningún algoritmo decide qué invocar. La decisión vive en la
> capa de razonamiento formal de Abi. Esta biblioteca solo provee las
> herramientas.

---

## Resumen rápido

| ID | Nombre | Cuándo se usa | Semanas mín. | Complejidad | Paper sec. |
|---|---|---|---|---|---|
| `open_loop` | Open-Loop Baseline | Baseline trivial, fallback universal | 0 | baja | 1.0 |
| `cold_inherit` | Cold-start Heredado | SKU nuevo con `sku_donante` del similarity engine | 0 | baja | 4.0 |
| `inv_buffer` | Inventory Buffer Robusto | Historial moderado, perecederos | 8 | media | 3.2 |
| `safety_stock` | Safety Stock heurístico | Alta criticidad, fallback conservador | 4 | baja | 1.0 |
| `affine_simple` | Affine Policy + EWMA | Historial extenso (≥52) y volatilidad ≤ 0.45 | 52 | alta | 2.1, 2.4, 3.2 |
| `robust_satisficing` | Robust Satisficing | Restricción de cash | 8 | media | 3.4 |

---

## 1. `open_loop` — Open-Loop Baseline

**Cuándo se usa.** Es el baseline universal. Aplica siempre (sus precondiciones
devuelven `True`). Sirve como línea base para comparar el resto y como fallback
si ningún otro algoritmo aplica.

**Qué hace.**
1. Toma la suma de la media del horizonte como cantidad central.
2. Aplica `buffer_minimo` si hay restricción deóntica.
3. Elige proveedor con score (confiabilidad, lead time, precio, región preferida).
4. Capea cantidad por presupuesto disponible.
5. Calcula VaR/CVaR a partir de p5/p50/p95.

**Inputs.** `DecisionContext` (forecast + proveedores + presupuesto).
**Outputs.** `RecomendacionCompra` con `algoritmo_id="open_loop"`.

**Referencia paper.** Sección 1 (heurística baseline).

---

## 2. `cold_inherit` — Cold-start Heredado

**Cuándo se usa.** SKU nuevo del que no hay historial propio, pero el
similarity engine de Abi (Bloque 6) identificó un `sku_donante` similar. El
forecast viene marcado con `fuente="inherited"`.

**Qué hace.**
1. Hereda la media/p5/p95 del donante con un factor de descuento (0.7 default)
   para no sobrecomprar en un SKU del que no sabemos casi nada.
2. Aplica buffer si hay restricción deóntica.
3. Elige proveedor y capea por presupuesto.
4. La confianza del resultado es menor (`confianza_global * 0.7`) porque el
   forecast es heredado.

**Precondición.** `ctx.sku_donante is not None` o `forecast.fuente == "inherited"`.

**Parámetros opcionales.**
- `factor_descuento_herencia` (default 0.7): multiplicador sobre las cantidades
  heredadas.

**Referencia paper.** Sección 4 (cold-start estructurado).

---

## 3. `inv_buffer` — Inventory Buffer Robusto

**Cuándo se usa.** SKU con historial moderado (≥8 semanas), donde los
percentiles del Monte Carlo de Cris son confiables. Caso ideal: perecederos
con horizonte corto.

**Qué hace.**
1. Cantidad central = mediana (p50). Si `nivel_servicio ≥ 0.9`, mezcla entre
   p50 y p95 según el nivel deseado.
2. Si es perecedero, aplica ajuste hacia abajo (factor 0.85) para no tirar
   producto vencido.
3. Buffer deóntico, proveedor, cap presupuesto, VaR/CVaR.

**Parámetros opcionales.**
- `nivel_servicio` (default 0.9): nivel de servicio objetivo.

**Referencia paper.** Sección 3.2 (robust constraints con chance constraints).

---

## 4. `safety_stock` — Safety Stock heurístico

**Cuándo se usa.** Cuando se prioriza no quebrar stock por sobre minimizar
costo: alta criticidad, productos donde el costo de stock-out >> costo de
sobre-stock. También sirve de fallback simple.

**Qué hace.**
1. Cantidad central = `p95_demanda` (cubre 95% de la demanda).
2. Opcionalmente p99 aproximado (`p95 + 0.5*std`).
3. Buffer deóntico, proveedor, cap presupuesto.

**Parámetros opcionales.**
- `usar_p99` (default `False`): usar p99 aproximado en vez de p95.

**Referencia paper.** Sección 1 (heurística conservadora clásica).

---

## 5. `affine_simple` — Affine Policy + EWMA Bounded

**Cuándo se usa.** Caso "feliz": SKU con ≥52 semanas de historial efectivo
(un año completo) y volatilidad acotada (≤0.45). Es el algoritmo más sofisticado
de la biblioteca.

**Qué hace.**
1. Suaviza la media del horizonte con EWMA (α=0.3 default).
2. Aplica policy afín: ajusta la cantidad por la `tendencia_local` detectada
   en la serie. Bounded: factor entre 0.5 y 2.0.
3. Cantidad = media_suavizada × horizonte × ajuste_tendencia.
4. Buffer deóntico, proveedor, cap presupuesto.

**Precondición.**
- `caracteristicas_serie.semanas_efectivas ≥ 52`
- `caracteristicas_serie.volatilidad ≤ 0.45`

**Parámetros opcionales.**
- `ewma_alpha` (default 0.3): smoothing factor del EWMA.
- `beta_tendencia` (default 1.0): peso del término de tendencia.

**Referencia paper.** Secciones 2.1, 2.4, 3.2 (affine policy + EWMA bounded).

---

## 6. `robust_satisficing` — Robust Satisficing cash-constrained

**Cuándo se usa.** Presupuesto ajustado (cash-constrained) donde necesitamos
maximizar el service level dado el cash disponible.

**Qué hace.**
1. Prioriza el proveedor más barato si cabe ≥ p50 con el presupuesto.
2. Calcula la cantidad máxima que cabe en presupuesto.
3. Toma `min(cantidad_objetivo_p95, cantidad_max_presupuesto)`.
4. Calcula el "service level efectivo" interpolando p5/p50/p95.
5. La confianza del resultado escala con el SL alcanzable.

**Parámetros opcionales.**
- `objetivo_servicio` (default 0.95): SL deseado. Si no cabe en presupuesto,
  el algoritmo reporta el SL realmente alcanzable.

**Referencia paper.** Sección 3.4 (robust satisficing).

---

## Cómo se integran al sistema completo

Flujo end-to-end de una decisión de compra (visión decisional v2):

1. **Mateo** detecta tendencia → inyecta `:TrendSignal` validado.
2. **Abi** (similarity + deóntica + dispatcher) procesa y elige algoritmo.
3. **Abi** llama a **Cris** para forecast con el contexto correcto.
4. **Abi** llama al algoritmo de la biblioteca de Mati que el dispatcher eligió,
   pasándole `forecast` + `restricciones_deonticas`.
5. La biblioteca devuelve `RecomendacionCompra` con intervalos.
6. Resultado vuelve a la ontología con PROV-O. LLM enriquece la explicación.

---

## Cómo agregar un algoritmo nuevo

1. Crear `optimization/algorithms/<nombre>.py` heredando de `BaseAlgorithm`.
2. Definir atributos de clase: `id`, `nombre`, `paper_seccion`,
   `requiere_semanas_minimas`, `complejidad`.
3. Implementar `precondiciones(ctx)` (default: comparar `semanas_efectivas`).
4. Implementar `run(ctx, restricciones, parametros)`.
5. Registrar en `optimization/algorithms/__init__.py` (`ALGORITMOS_DISPONIBLES`).
6. Agregar entrada al catálogo OWL (`optimization/owl/algorithms_catalog.ttl`).
7. Agregar test paramétrico en `optimization/tests/test_optimizers.py`.
8. Avisar a Abi para que el dispatcher actualice sus reglas.

---

## Helpers compartidos (`optimization/algorithms/base.py`)

- `elegir_proveedor(proveedores, restricciones, cantidad_objetivo)` — ranking
  con score = 0.5*confiabilidad + 0.3*lead_time + 0.2*precio_norm. Bonus para
  región preferida si hay restricción.
- `aplicar_buffer_minimo(cantidad, restricciones)` — aplica `factor_seguridad`.
- `cap_por_presupuesto(cantidad, precio, presupuesto)` — reduce si excede.
- `respeta_min_proveedores(restricciones, disponibles)` — valida la restricción
  de doble proveedor.
- `calcular_var_cvar(p5, central, p95, precio)` — VaR y CVaR aproximados.

---

## Estado de integración

| Pieza | Estado |
|---|---|
| Schemas Pydantic v2 alineados a specs | Listo |
| Stubs de forecast/deontic/bridge | Listos (devuelven forma final) |
| 6 algoritmos con interfaz IAlgorithm | Listos |
| Catálogo OWL en Turtle | Listo |
| Script idempotente de carga | Listo |
| Tests end-to-end | Listos |
| Performance 100 SKUs < 30s | Validado en tests |
| Integración real con Abi/Cris | Pendiente (`USAR_STUBS=False` en `integrations.py`) |

Cuando Cris/Abi suban sus módulos: cambiar `USAR_STUBS=False` (o set
`OPT_USAR_STUBS=0` en `.env`). Los algoritmos no necesitan ningún cambio.
