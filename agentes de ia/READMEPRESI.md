# Hackathon Retail Navideño — Estado del Proyecto

Sistema de soporte de decisión para compras de retail navideño. Sugiere qué comprar, cuánto y a qué proveedor; un humano siempre aprueba la decisión final.

**Última actualización:** 28 de abril de 2026
**Tareas a cargo:** Tarea 4 (optimización + backend) y Tarea 5 (agentes con Claude)

---

## Índice

1. [Contexto del proyecto](#contexto-del-proyecto)
2. [Stack tecnológico](#stack-tecnológico)
3. [Tarea 4 — Estado y archivos](#tarea-4--estado-y-archivos)
4. [Tarea 5 — Plan](#tarea-5--plan)
5. [Coordinación con otros equipos](#coordinación-con-otros-equipos)
6. [Cómo retomar el trabajo](#cómo-retomar-el-trabajo)

---

## Contexto del proyecto

Sistema multi-componente que combina:

- **Tarea 1:** Ontología (base de datos de grafos) + RAG sobre catálogos de proveedores
- **Tarea 2:** Web research + monitoreo de tendencias en redes sociales
- **Tarea 3:** Datos sintéticos + forecast de demanda con Monte Carlo
- **Tarea 4:** Optimización estocástica + motor contrafactual + backend HTTP ← **NOSOTROS**
- **Tarea 5:** Multi-agente, crítico adversarial, negociación, preference learning ← **NOSOTROS**
- **Tarea 6:** Frontend con grafo causal y experiencia conversacional

El humano siempre aprueba la decisión final. El sistema sugiere, explica y deja todo listo.

---

## Stack tecnológico

- **Lenguaje:** Python 3.10+
- **Optimización:** PuLP con solver HiGHS (fallback a CBC)
- **API:** FastAPI + Uvicorn
- **LLM (tarea 5):** Claude (API de Anthropic) — Sonnet para crítico adversarial, Haiku para orquestador y negociador
- **Editor:** Cursor (con asistente de IA)

---

## Tarea 4 — Estado y archivos

**Estado:** ✅ Core completo y funcionando

### Qué hace

Recibe productos, proveedores y presupuesto. Devuelve plan óptimo de compra que minimiza costo + penalización por demanda no cubierta. Soporta análisis contrafactual ("¿qué pasa si X?").

### Estructura de archivos

```
hackathon-navidad/
├── datos_prueba.json    ← datos de prueba (5 productos, 3 proveedores)
├── contexto.py          ← clases de datos + OptimizationContext
├── solver.py            ← solver matemático con PuLP
└── main.py              ← API HTTP con FastAPI
```

### Comandos clave

```bash
# Instalar dependencias (una sola vez)
pip install pulp fastapi uvicorn pydantic

# Probar el solver desde terminal
python solver.py

# Levantar la API
uvicorn main:app --reload

# Acceder a la API en el navegador
http://127.0.0.1:8000/docs
```

### Endpoints de la API

| Método | Endpoint | Body | Devuelve |
|---|---|---|---|
| GET | `/health` | (ninguno) | `{"status": "ok", "servicio": "..."}` |
| POST | `/recommend` | JSON con productos, proveedores, presupuesto, evento_comercial | Plan de compra con costo, cobertura, líneas |
| POST | `/counterfactual` | `{"datos_input": {...}, "perturbacion": {...}}` | Plan modificado + comparación vs original |

**Perturbaciones soportadas en `/counterfactual`:**

- `excluir_proveedor: "PROV-A"` (o el id que sea)
- `cambiar_presupuesto: 30000`
- `adelantar_evento_dias: 10`

### Resultados validados

**Caso base (con todos los proveedores disponibles):**

- Costo total: $47,816.35
- Cobertura: 100%
- Presupuesto usado: 95.63%
- Plan: 4 SKUs comprados a PROV-A (Importadora Asiática, el más barato), papá noel inflable a PROV-C

**Contrafactual "excluir PROV-A":**

- Costo total: $50,000 (sube $2,183.65)
- Cobertura: 98.78%
- Presupuesto usado: 100%
- Faltante: INF-001 (papá noel inflable)
- Plan: redistribuye entre PROV-B y PROV-C

### Lo que cubre del documento del hackathon

- ✅ Solver matemático con PuLP + HiGHS
- ✅ Cobertura del 95% como soft constraint con penalización
- ✅ Restricción MOQ con técnica Big M
- ✅ Filtro de lead time + buffer de seguridad
- ✅ Estructura modular para contrafactuales rápidos
- ✅ Backend HTTP con endpoints expuestos
- 🟡 Integración con tarea 1 (datos vendrán de ontología) y tarea 3 (demanda P75 vendrá del Monte Carlo) — hoy se mockean con `datos_prueba.json`

### Deuda técnica menor (puede esperar)

- Endpoint `POST /negotiate` para que tarea 5 genere borradores de email a proveedores
- Endpoint `POST /preferences/update` para preference learning
- Más tipos de perturbaciones contrafactuales (shock de tipo de cambio, retraso de lead time)
- Reemplazar `datos_prueba.json` por llamadas reales a tarea 1 y tarea 3 cuando estén listas

---

### Código completo

#### `datos_prueba.json`

```json
{
  "evento_comercial": {
    "nombre": "Navidad 2026",
    "dias_hasta_evento": 35
  },
  "presupuesto_total": 50000,
  "productos": [
    {"sku": "LED-001", "nombre": "Luces LED", "demanda_esperada": 900, "demanda_p75": 1050, "precio_venta": 24.9, "margen_perdido_por_quiebre": 7.5},
    {"sku": "ARB-001", "nombre": "Arbol artificial", "demanda_esperada": 180, "demanda_p75": 220, "precio_venta": 169.9, "margen_perdido_por_quiebre": 45.0},
    {"sku": "GUI-001", "nombre": "Guirnalda", "demanda_esperada": 620, "demanda_p75": 760, "precio_venta": 13.9, "margen_perdido_por_quiebre": 4.2},
    {"sku": "ESF-001", "nombre": "Esferas", "demanda_esperada": 500, "demanda_p75": 620, "precio_venta": 19.9, "margen_perdido_por_quiebre": 5.8},
    {"sku": "INF-001", "nombre": "Papa noel inflable", "demanda_esperada": 95, "demanda_p75": 130, "precio_venta": 199.9, "margen_perdido_por_quiebre": 52.0}
  ],
  "proveedores": [
    {
      "id": "PROV-A",
      "nombre": "Importadora Asiatica",
      "lead_time_dias": 25,
      "ofertas": [
        {"sku": "LED-001", "precio_unitario": 8.3, "moq": 300},
        {"sku": "ARB-001", "precio_unitario": 78.0, "moq": 120},
        {"sku": "GUI-001", "precio_unitario": 4.9, "moq": 400},
        {"sku": "ESF-001", "precio_unitario": 8.7, "moq": 280}
      ]
    },
    {
      "id": "PROV-B",
      "nombre": "Distribuidora Local",
      "lead_time_dias": 7,
      "ofertas": [
        {"sku": "LED-001", "precio_unitario": 11.2, "moq": 60},
        {"sku": "ARB-001", "precio_unitario": 99.0, "moq": 25},
        {"sku": "GUI-001", "precio_unitario": 6.8, "moq": 80},
        {"sku": "ESF-001", "precio_unitario": 11.5, "moq": 70},
        {"sku": "INF-001", "precio_unitario": 132.0, "moq": 15}
      ]
    },
    {
      "id": "PROV-C",
      "nombre": "Mayorista Premium",
      "lead_time_dias": 12,
      "ofertas": [
        {"sku": "LED-001", "precio_unitario": 9.8, "moq": 140},
        {"sku": "ARB-001", "precio_unitario": 89.5, "moq": 60},
        {"sku": "ESF-001", "precio_unitario": 9.9, "moq": 130},
        {"sku": "INF-001", "precio_unitario": 118.0, "moq": 35}
      ]
    }
  ]
}
```

#### `contexto.py`

```python
"""Modelos de datos y contexto de optimizacion para compras navidenas."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import List


@dataclass
class Producto:
    sku: str
    nombre: str
    demanda_esperada: float
    demanda_p75: float
    precio_venta: float
    margen_perdido_por_quiebre: float


@dataclass
class Oferta:
    sku: str
    precio_unitario: float
    moq: int


@dataclass
class Proveedor:
    id: str
    nombre: str
    lead_time_dias: int
    ofertas: List[Oferta]


@dataclass
class OptimizationContext:
    productos: List[Producto]
    proveedores: List[Proveedor]
    presupuesto_total: float
    dias_hasta_evento: int
    buffer_seguridad_dias: int = 5
    cobertura_objetivo: float = 0.95
    peso_costo: float = 1.0
    peso_penalizacion_quiebre: float = 1.0

    @classmethod
    def desde_json(cls, ruta: str) -> "OptimizationContext":
        # IMPORTANTE: utf-8-sig para evitar problemas con BOM en archivos JSON
        with open(ruta, "r", encoding="utf-8-sig") as archivo:
            datos = json.load(archivo)

        productos = [Producto(**producto_json) for producto_json in datos["productos"]]

        proveedores: List[Proveedor] = []
        for proveedor_json in datos["proveedores"]:
            ofertas = [Oferta(**oferta_json) for oferta_json in proveedor_json["ofertas"]]
            proveedores.append(
                Proveedor(
                    id=proveedor_json["id"],
                    nombre=proveedor_json["nombre"],
                    lead_time_dias=proveedor_json["lead_time_dias"],
                    ofertas=ofertas,
                )
            )

        return cls(
            productos=productos,
            proveedores=proveedores,
            presupuesto_total=datos["presupuesto_total"],
            dias_hasta_evento=datos["evento_comercial"]["dias_hasta_evento"],
        )

    def copiar(self) -> "OptimizationContext":
        return copy.deepcopy(self)

    def excluir_proveedor(self, proveedor_id: str) -> "OptimizationContext":
        nuevo_ctx = self.copiar()
        nuevo_ctx.proveedores = [prov for prov in nuevo_ctx.proveedores if prov.id != proveedor_id]
        return nuevo_ctx

    def cambiar_presupuesto(self, nuevo_presupuesto: float) -> "OptimizationContext":
        nuevo_ctx = self.copiar()
        nuevo_ctx.presupuesto_total = nuevo_presupuesto
        return nuevo_ctx

    def adelantar_evento(self, dias: int) -> "OptimizationContext":
        nuevo_ctx = self.copiar()
        nuevo_ctx.dias_hasta_evento = max(0, nuevo_ctx.dias_hasta_evento - dias)
        return nuevo_ctx
```

#### `solver.py`

```python
"""Solver de optimizacion de compras con PuLP y fallback de solucionador."""

from __future__ import annotations

import os
from typing import Dict, List, Tuple

import pulp

from contexto import OptimizationContext


def _seleccionar_solver() -> pulp.LpSolver:
    """Intenta HiGHS y, si falla, usa CBC."""
    highs = pulp.HiGHS_CMD(msg=False)
    if highs.available():
        return highs
    return pulp.PULP_CBC_CMD(msg=False)


def resolver(ctx: OptimizationContext) -> Dict:
    """Resuelve el plan de compra minimizando costo y faltantes."""
    productos_por_sku = {producto.sku: producto for producto in ctx.productos}

    pares_viables: List[Tuple[str, str]] = []
    info_oferta: Dict[Tuple[str, str], Dict[str, float]] = {}
    proveedores_por_id = {proveedor.id: proveedor for proveedor in ctx.proveedores}

    for proveedor in ctx.proveedores:
        llega_a_tiempo = proveedor.lead_time_dias + ctx.buffer_seguridad_dias <= ctx.dias_hasta_evento
        if not llega_a_tiempo:
            continue
        for oferta in proveedor.ofertas:
            if oferta.sku not in productos_por_sku:
                continue
            par = (oferta.sku, proveedor.id)
            pares_viables.append(par)
            info_oferta[par] = {
                "precio_unitario": float(oferta.precio_unitario),
                "moq": float(oferta.moq),
                "lead_time_dias": float(proveedor.lead_time_dias),
            }

    skus = list(productos_por_sku.keys())
    modelo = pulp.LpProblem("PlanComprasNavidad", pulp.LpMinimize)

    x = pulp.LpVariable.dicts("x", pares_viables, lowBound=0, cat="Continuous")
    y = pulp.LpVariable.dicts("y", pares_viables, lowBound=0, upBound=1, cat="Binary")
    shortfall = pulp.LpVariable.dicts("shortfall", skus, lowBound=0, cat="Continuous")

    costo_compra = pulp.lpSum(
        x[par] * info_oferta[par]["precio_unitario"]
        for par in pares_viables
    )
    penalizacion_quiebre = pulp.lpSum(
        shortfall[sku] * productos_por_sku[sku].margen_perdido_por_quiebre * 10.0
        for sku in skus
    )
    modelo += (
        costo_compra * ctx.peso_costo
        + penalizacion_quiebre * ctx.peso_penalizacion_quiebre
    )

    for sku in skus:
        demanda_objetivo_sku = productos_por_sku[sku].demanda_p75 * 0.95
        pares_sku = [par for par in pares_viables if par[0] == sku]
        modelo += (
            pulp.lpSum(x[par] for par in pares_sku) + shortfall[sku] >= demanda_objetivo_sku
        ), f"cobertura_soft_{sku}"

    for par in pares_viables:
        sku, proveedor_id = par
        moq = info_oferta[par]["moq"]
        big_m = productos_por_sku[sku].demanda_p75 * 2.0
        modelo += x[par] >= moq * y[par], f"moq_min_{sku}_{proveedor_id}"
        modelo += x[par] <= big_m * y[par], f"moq_max_{sku}_{proveedor_id}"

    modelo += costo_compra <= ctx.presupuesto_total, "presupuesto_total"

    solver = _seleccionar_solver()
    modelo.solve(solver)

    status_lp = pulp.LpStatus.get(modelo.status, "Unknown")
    status = "optimo" if status_lp == "Optimal" else status_lp.lower()

    lineas_compra = []
    for par in pares_viables:
        cantidad = x[par].value() or 0.0
        if cantidad <= 1e-6:
            continue
        sku, proveedor_id = par
        proveedor = proveedores_por_id[proveedor_id]
        precio = info_oferta[par]["precio_unitario"]
        costo_linea = cantidad * precio
        lineas_compra.append(
            {
                "sku": sku,
                "proveedor_id": proveedor_id,
                "proveedor_nombre": proveedor.nombre,
                "cantidad": round(cantidad, 2),
                "precio_unitario": precio,
                "costo_total": round(costo_linea, 2),
                "lead_time_dias": proveedor.lead_time_dias,
            }
        )

    costo_total = round(
        sum(linea["costo_total"] for linea in lineas_compra), 2
    )

    demanda_objetivo_total = sum(productos_por_sku[sku].demanda_p75 * 0.95 for sku in skus)
    shortfall_total = sum((shortfall[sku].value() or 0.0) for sku in skus)
    cobertura_demanda = 1.0 if demanda_objetivo_total <= 0 else max(
        0.0, 1.0 - (shortfall_total / demanda_objetivo_total)
    )

    skus_descubiertos = [
        sku for sku in skus if (shortfall[sku].value() or 0.0) > 1e-6
    ]

    presupuesto_usado_pct = (
        0.0 if ctx.presupuesto_total <= 0 else (costo_total / ctx.presupuesto_total) * 100.0
    )

    return {
        "status": status,
        "lineas_compra": lineas_compra,
        "costo_total": costo_total,
        "cobertura_demanda": round(cobertura_demanda, 4),
        "skus_descubiertos": skus_descubiertos,
        "presupuesto_usado_pct": round(presupuesto_usado_pct, 2),
    }


def _imprimir_resultado(titulo: str, resultado: Dict) -> None:
    print("\n" + "=" * 72)
    print(titulo)
    print("=" * 72)
    print(f"Status: {resultado['status']}")
    print(f"Costo total: {resultado['costo_total']:.2f}")
    print(f"Cobertura demanda: {resultado['cobertura_demanda'] * 100:.2f}%")
    print(f"Presupuesto usado: {resultado['presupuesto_usado_pct']:.2f}%")
    print("Lineas de compra:")
    if not resultado["lineas_compra"]:
        print("  (sin compras)")
    for linea in resultado["lineas_compra"]:
        print(
            "  - "
            f"{linea['sku']} | {linea['proveedor_id']} ({linea['proveedor_nombre']}) | "
            f"cant={linea['cantidad']} | precio={linea['precio_unitario']} | "
            f"costo={linea['costo_total']} | LT={linea['lead_time_dias']} dias"
        )
    if resultado["skus_descubiertos"]:
        print(f"SKUs con faltante: {', '.join(resultado['skus_descubiertos'])}")
    else:
        print("SKUs con faltante: ninguno")


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    ruta_json = os.path.join(base_dir, "datos_prueba.json")

    contexto_base = OptimizationContext.desde_json(ruta_json)
    resultado_base = resolver(contexto_base)
    _imprimir_resultado("CASO BASE", resultado_base)

    contexto_sin_prov_a = contexto_base.excluir_proveedor("PROV-A")
    resultado_sin_prov_a = resolver(contexto_sin_prov_a)
    _imprimir_resultado("CONTRAFACTUAL: EXCLUIR PROV-A", resultado_sin_prov_a)
```

#### `main.py`

> **Nota:** este archivo lo generó Cursor con el prompt que armamos. Si lo perdés, regenerarlo con Cursor toma 2 minutos usando el prompt guardado más abajo. Los puntos clave: FastAPI con CORS abierto, modelos Pydantic para validación, los 3 endpoints definidos en la sección "Endpoints de la API".

**Prompt original para regenerar `main.py` con Cursor (si se pierde):**

```
Tengo un solver de optimizacion funcionando en solver.py que toma un OptimizationContext
de contexto.py y devuelve un plan de compra. Ya esta probado y funciona.

Ahora necesito envolverlo en una API HTTP con FastAPI para que el frontend y otros
servicios lo puedan llamar.

Crea un archivo main.py con FastAPI que tenga estos endpoints:

1) GET /health
   Devuelve: {"status": "ok", "servicio": "optimizador-compras-navidad"}

2) POST /recommend
   Recibe en el body: el JSON completo de datos_prueba.json (con campos productos,
   proveedores, presupuesto_total, evento_comercial)
   - Construye un OptimizationContext desde el JSON recibido
   - Llama a resolver(ctx) del solver.py
   - Devuelve el resultado del solver tal cual

3) POST /counterfactual
   Recibe en el body un objeto con dos campos:
   - "datos_input": el mismo JSON de productos/proveedores/presupuesto
   - "perturbacion": un objeto con campos OPCIONALES:
     * "excluir_proveedor": str (id del proveedor a quitar)
     * "cambiar_presupuesto": float (nuevo presupuesto)
     * "adelantar_evento_dias": int (cuantos dias adelantar)

   Logica:
   - Construye el contexto base
   - Aplica las perturbaciones que vengan (las que no vengan, no las aplica)
     usando los metodos de OptimizationContext: excluir_proveedor,
     cambiar_presupuesto, adelantar_evento
   - Resuelve con el contexto modificado
   - Devuelve un dict con dos campos:
     {
       "resultado_perturbado": <salida del solver>,
       "comparacion_vs_original": {
         "costo_original": ...,
         "costo_perturbado": ...,
         "diferencia_costo": ...,
         "diferencia_cobertura_pct": ...
       }
     }
   - Para la comparacion, tambien resuelve el caso original (sin perturbacion)
     y compara

REQUISITOS:
- Usa Pydantic models para validar los inputs (define modelos PerturbacionRequest
  y CounterfactualRequest).
- Configura CORS abierto (allow_origins=["*"]) para que el frontend pueda llamar
  desde otro puerto durante desarrollo.
- Agrega manejo basico de errores: si el solver falla, devuelve HTTP 500 con un
  mensaje claro.
- No modifiques contexto.py ni solver.py, solo crea main.py.
```

---

## Tarea 5 — Plan

**Estado:** 🟡 No iniciada (siguiente paso)

### Plan acordado

Construir un agente con la API de Anthropic (Claude) que use **tool use** para decidir qué hacer. Versión simple y demoable, sin LangGraph (demasiada curva de aprendizaje en el tiempo disponible).

### Componentes planeados

1. **Orquestador (Claude Haiku):** clasifica intención del usuario y decide qué tool llamar.
2. **Tools registradas:**
   - `consultar_productos()`: lista productos del catálogo
   - `generar_recomendacion()`: llama a `POST /recommend` de tarea 4
   - `ejecutar_contrafactual(perturbacion)`: llama a `POST /counterfactual`
3. **Crítico Adversarial (Claude Sonnet):** después de cada recomendación, otra llamada a Claude que ataca el plan buscando vulnerabilidades (retrasos, quiebre de proveedor, demanda baja).
4. **Negociador (Claude Haiku):** cuando se aprueba una compra, redacta email al proveedor.
5. **Preference learning de cartón:** dict en memoria con `stockout_aversion` y `capital_aversion`, se actualiza con feedback del operador, persiste en JSON.

### Endpoint a agregar en `main.py`

`POST /chat` que recibe `{"mensaje_usuario": str}` y devuelve respuesta del agente con plan estructurado.

### Pre-requisitos antes de arrancar

- API key de Anthropic creada en `console.anthropic.com/settings/keys`
- Verificar crédito en `/settings/billing` (con $5 USD sobra)
- Crear archivo `.env` en la carpeta del proyecto con: `ANTHROPIC_API_KEY=sk-ant-...`
- Crear archivo `.gitignore` con: `.env`
- Instalar dependencias: `pip install anthropic python-dotenv requests`

---

## Coordinación con otros equipos

| Tarea | Persona | Estado | Acción pendiente |
|---|---|---|---|
| 1 - Ontología y RAG | (compañero) | en progreso | Pasar formato de datos cuando esté listo |
| 2 - Web research y tendencias | (compañero) | parcialmente hecho con Gemini | Decidir si migrar a Claude o dejar híbrido |
| 3 - Datos sintéticos + Monte Carlo | (compañero) | en progreso | Coordinar formato de demanda P75 |
| 4 - Optimización + backend | **YO + pareja** | ✅ core listo | Conectar con tarea 1 y 3 cuando entreguen |
| 5 - Agentes con Claude | **YO + pareja** | 🟡 siguiente | Arrancar después de guardar este resumen |
| 6 - Frontend | (compañero) | en progreso | Ya pueden integrar contra `localhost:8000` |

### Mensaje listo para enviar al equipo

> Equipo, tarea 4 (optimizador de compras) está corriendo. La API está en `http://localhost:8000` con tres endpoints:
>
> - `GET /health` para verificar que está viva
> - `POST /recommend` recibe productos+proveedores+presupuesto y devuelve el plan óptimo de compra
> - `POST /counterfactual` recibe los mismos datos + una perturbación (ej: `excluir_proveedor: PROV-A`) y devuelve el plan recompuesto con comparación vs el original
>
> Documentación interactiva con ejemplos en `http://localhost:8000/docs`.
>
> Frontend (tarea 6) ya pueden integrar.
> Tarea 1 (ontología) y tarea 3 (forecast) cuando me pasen los datos los conecto en lugar del JSON de prueba.
> Tarea 5 (agentes) los endpoints están listos para usar como tools.

---

## Cómo retomar el trabajo

### Si se cierra la terminal o se reinicia la computadora

1. Abrir Cursor en la carpeta del proyecto.
2. Abrir terminal en Cursor (Ctrl + ñ o Ctrl + `).
3. Verificar que las dependencias están instaladas: `python -c "import pulp; import fastapi; print('ok')"`. Si falla, reinstalar con `pip install pulp fastapi uvicorn pydantic`.
4. Levantar el servidor: `uvicorn main:app --reload`.
5. Abrir navegador en `http://127.0.0.1:8000/docs` para verificar que funciona.

### Reglas importantes

- La terminal de uvicorn **no se debe cerrar** mientras tarea 5 o tarea 6 estén usando la API.
- Si tu pareja necesita usar la terminal para otra cosa, abrir una **segunda terminal** (`Ctrl+Shift+ñ` en Cursor o el botón "+" arriba).
- Los datos de productos están hardcodeados en `datos_prueba.json`. Cuando tarea 1 y tarea 3 entreguen datos reales, se reemplaza la fuente sin tocar el solver.
- El BOM en archivos JSON puede causar errores. La línea `encoding="utf-8-sig"` en `desde_json()` lo previene.

### Backup recomendado

Subir todo a un repositorio de GitHub privado. Pedirle a Cursor: "inicializa este proyecto como repo de Git, crea un .gitignore que excluya .env y __pycache__, y subilo a GitHub". Cursor lo hace solo y vale 5 minutos.

---

## Hitos del proyecto

- [x] **28/04** — Setup del entorno (Python, Cursor, dependencias)
- [x] **28/04** — Solver matemático funcionando (caso base + contrafactual)
- [x] **28/04** — API HTTP con 3 endpoints validados
- [ ] Tarea 5 — Agente con tool use, crítico adversarial y negociador
- [ ] Integración con tarea 1 y tarea 3
- [ ] Demo final
