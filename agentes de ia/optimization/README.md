# Biblioteca de Optimización — Tarea 4 (Mati)

Biblioteca despachable de algoritmos para decisión de compra. El **dispatcher
de Abi** (Bloque 7) consulta este catálogo y elige cuál invocar según el
contexto del SKU.

> **Importante**: ningún algoritmo decide qué invocar. La decisión vive en la
> capa de razonamiento formal de Abi. Esta biblioteca solo provee las
> herramientas (Strategy pattern).

---

## Estructura

```
optimization/
├── schemas.py              # Pydantic v2: ForecastResult, Restriccion, ...
├── integrations.py         # Switch unico stubs <-> modulos reales del equipo
├── demo.py                 # Demo end-to-end de los 6 algoritmos
├── dispatcher_ref.py       # Dispatcher de referencia (NO sustituye al de Abi)
│
├── algorithms/
│   ├── base.py             # BaseAlgorithm + helpers compartidos
│   ├── open_loop.py
│   ├── cold_inherit.py
│   ├── inv_buffer.py
│   ├── safety_stock.py
│   ├── affine_simple.py
│   └── robust_satisficing.py
│
├── stubs/
│   ├── forecast_stub.py    # Reemplaza al modulo de Cris (Tarea 3)
│   ├── deontic_stub.py     # Reemplaza al deontic resolver de Abi (Bloque 5)
│   └── bridge_stub.py      # Reemplaza al bridge OWL de Abi
│
├── owl/
│   ├── algorithms_catalog.ttl  # 6 algoritmos como :Algorithm individuos
│   └── cargar_catalogo.py      # Script idempotente de carga al grafo
│
└── tests/
    └── test_optimizers.py  # Tests end-to-end con escenarios criticos
```

---

## Quickstart

```python
from optimization.algorithms import crear_algoritmo
from optimization.dispatcher_ref import DispatcherReferencia
from optimization.schemas import DecisionContext, ProveedorCandidato
from optimization.integrations import obtener_forecast, DeonticResolver

# Construir contexto
forecast = obtener_forecast("SKU_001")
proveedores = [
    ProveedorCandidato(
        proveedor_id="PROV_NAC_01",
        nombre="Norte Festivo SA",
        precio_unitario=12.5,
        moq=100,
        lead_time_dias=7,
        confiabilidad=0.92,
    ),
]
ctx = DecisionContext(
    sku="SKU_001",
    forecast=forecast,
    proveedores_candidatos=proveedores,
    presupuesto_disponible=15000.0,
)

# Opcion A: usar el dispatcher de referencia
disp = DispatcherReferencia()
rec = disp.decidir(ctx)
print(f"Algoritmo: {rec.algoritmo_id}, cant={rec.cantidad_central}")

# Opcion B: invocar un algoritmo especifico
alg = crear_algoritmo("inv_buffer")
restricciones = DeonticResolver().evaluar_restricciones(ctx)
rec = alg.run(ctx, restricciones=restricciones)
```

---

## Demo

```bash
python -m optimization.demo
python -m optimization.demo SKU_001 SKU_004 SKU_NUEVO_999 SKU_002
```

Corre los 6 algoritmos sobre SKUs de muestra y muestra recomendaciones
lado a lado.

---

## Tests

```bash
pytest optimization/tests/test_optimizers.py -v
```

Cubre:

- Cada algoritmo devuelve una `RecomendacionCompra` válida.
- Cold-start usa `sku_donante`.
- Restricción de buffer mínimo se respeta.
- Cash-constrained baja la cantidad.
- Perecedero inviable está bloqueado.
- Forecast con la nueva forma (listas).
- Performance: 100 SKUs en menos de 30s.

---

## Integración con el resto del equipo

| Pieza | Responsable | Estado | Path real |
|---|---|---|---|
| `OntologyClient` (Bloque 1) | Abi | ✅ Disponible | `from ontology import OntologyClient` |
| Bridge OWL (Bloque 3) | Abi | ✅ Disponible | `from ontology_semantic.bridge import importar_owl_a_neo4j` |
| SHACL validar | Abi | ✅ Disponible | `from ontology_semantic.validar import validar_grafo` |
| Reasoner HermiT (Bloque 4) | Abi | ✅ Disponible | `from ontology_semantic.reasoner import ...` |
| Similarity Engine (Bloque 5) | Abi | ✅ Disponible | `from ontology_semantic.client_v2 import OntologyClientV2` |
| `DeonticResolver` | Abi | ⏳ Pendiente | (usando stub) |
| Forecast Monte Carlo (Tarea 3) | Cris | ⏳ Pendiente | (usando stub) |

### Switch stubs ↔ módulos reales

```bash
# Por defecto (stubs)
python -m optimization.demo

# Activar módulos reales
$env:OPT_USAR_STUBS = "0"   # PowerShell
python -m optimization.demo
```

`integrations.py` hace **fallback automático** al stub si la librería real
no está instalada o no está disponible. Logguea un warning. Nunca rompe.

---

## Cargar el catálogo OWL al grafo de Abi

```bash
python -m optimization.owl.cargar_catalogo
```

Carga `algorithms_catalog.ttl` con los 6 algoritmos como individuos
`:Algorithm` para que el dispatcher de Abi los consulte.

---

## Cómo agregar un algoritmo nuevo

1. Crear `optimization/algorithms/<nombre>.py` heredando de `BaseAlgorithm`.
2. Definir atributos de clase: `id`, `nombre`, `paper_seccion`,
   `requiere_semanas_minimas`, `complejidad`.
3. Implementar `precondiciones(ctx)` (default: comparar `semanas_efectivas`).
4. Implementar `run(ctx, restricciones, parametros)`.
5. Registrar en `optimization/algorithms/__init__.py`.
6. Agregar entrada al catálogo OWL (`optimization/owl/algorithms_catalog.ttl`).
7. Agregar test paramétrico en `optimization/tests/test_optimizers.py`.
8. Avisar a Abi para que el dispatcher actualice sus reglas.

---

## Estado de la entrega (Mati - Tarea 4)

- [x] Schemas Pydantic v2 alineados a specs Cris/Mateo
- [x] Stubs de forecast, deontic, bridge
- [x] 6 algoritmos con interfaz `IAlgorithm`
- [x] Helpers compartidos (proveedor ranking, VaR/CVaR, buffer, cap presupuesto)
- [x] Catálogo OWL en Turtle declarando los algoritmos
- [x] Script idempotente de carga al grafo
- [x] Tests end-to-end (incluye performance < 30s)
- [x] Documentación `docs/algorithms_catalog.md`
- [x] Demo runner end-to-end
- [x] Dispatcher de referencia (para que Abi tenga el contrato)
- [x] Integración con bridge + similarity reales de Abi (Bloques 1, 3, 5)
- [ ] Integración con `DeonticResolver` real de Abi (cuando lo entregue)
- [ ] Integración con módulo de forecast real de Cris (cuando lo entregue)
