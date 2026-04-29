# HANDOFF — Cris (Tarea 3) — Estado del trabajo

> **Cómo usar este documento:** este archivo condensa todo el estado del trabajo
> de Cris en la Tarea 3 del proyecto NASA, para que un nuevo chat de Cowork
> retome el contexto sin perder información. Pegalo en la primera respuesta de
> la nueva sesión o pedile a Claude que lo lea: él tiene acceso al archivo en
> `C:\AITinketers\Tinketers\HANDOFF_CRIS.md`.

---

## 1. Quién soy y qué hago

- **Cris**, encargada de la **Tarea 3** del proyecto **NASA — Marketplace SA Paraguay**
- Mi rol según *Especificaciones Técnicas v2*: **servicio de forecasting + Monte Carlo consciente de incertidumbre**
- Mis 3 entregables troncales:
  1. Cargar `:VentaSemanal` al Neo4j del equipo desde Pegasus
  2. `forecast()` con Holt-Winters + intervalos + metadata decisional
  3. Motor Monte Carlo deóntico-aware (acepta restricciones de Abi)

**Documento de spec autoritativo:** `Especificaciones_CRIS.pdf` v2 (NO la consigna PDF original).
La v2 es decisional: mi forecast es **insumo del razonador formal de Abi**, no un cálculo aislado.

---

## 2. Equipo y arquitectura

- **Abi** — Tarea 1: ontología (Neo4j) + RAG + bridge OWL/RDF + razonador HermiT + similarity engine. **Bloques 1-5 completados.**
- **Mateo** — Tarea 2: web research + tendencias virales (`:TrendSignal`)
- **Mauri/Mati** — Tarea 4: optimización lineal entera mixta + razonamiento contrafactual + backend
- **Cris (yo)** — Tarea 3: forecasting + Monte Carlo
- **(Tarea 5)** — Multi-agente, crítico adversarial, negociación, preference learning
- **(Tarea 6 / Franky)** — Frontend, grafo causal, conversacional contrafactual

**Patrón de integración:** scripts idempotentes en Git + Neo4j local por persona.
- Repo: `https://github.com/bimarketplacepy/NASA.git`, branch `main`
- Workspace local: `C:\AITinketers\Tinketers`
- Cada uno tiene su propio Neo4j Docker en localhost:7687

**Flujo de decisión end-to-end:**
1. Mateo detecta tendencia → `:TrendSignal` al graph
2. Abi (similarity engine) cruza con productos existentes → top-K similares
3. Abi (capa deóntica) evalúa permisión/prohibición/obligación
4. Abi (dispatcher) llama a **mi `forecast(sku, sku_donante=...)`**
5. **Yo devuelvo `ForecastResult`** con media + intervalos + metadata
6. Mati optimiza con mi forecast + restricciones deónticas
7. Decisión vuelve a la ontología con PROV-O
8. LLM enriquece la explicación humana

---

## 3. Estado del setup (✅ Fase 1 completada)

| Componente | Estado | Notas |
|---|---|---|
| Docker Desktop | ✅ instalado y corriendo | v29.4.1 |
| Python 3.12.4 | ✅ instalado | con `py -3.12` launcher |
| Git 2.45.2 | ✅ instalado | repo clonado |
| Cursor | ✅ instalado con plugins Python + Docker | |
| VPN a Pegasus | ✅ funcionando | confirmado por queries SSMS |
| Repo `bimarketplacepy/NASA` | ✅ clonado en `C:\AITinketers\Tinketers` | branch main, Bloques 1-5 de Abi pulled |
| `.env` con credenciales | ✅ presente y gitignored | Neo4j + Pegasus |
| `venv/` Python 3.12 | ✅ recreado limpio | el original de Abi tenía paths absolutos rotos |
| Deps mínimas | ✅ instaladas | neo4j, pandas, pyodbc, python-dotenv, pydantic, statsmodels, numpy, scipy, PyYAML |
| Neo4j Docker (`neo4j-marketplace`) | ✅ corriendo | puerto 7474/7687, pass `marketplace2026` |
| **Microsoft C++ Build Tools** | 🟡 **en instalación / pendiente** | necesario para `chromadb` y `chroma-hnswlib` |

**Pendiente del setup completo:**
- Build Tools en background → cuando termine: `pip install -r requirements.txt` para completar el resto (chromadb, sentence-transformers, owlready2, rdflib, pyshacl, pypdf, fpdf2)
- Ejecutar `python tests\test_smoke.py` para validar que todo el repo de Abi funciona en mi máquina

---

## 4. Datos extraídos de Pegasus

**Filtros aplicados (jerarquía Pegasus):**
- `Cod_seccion = 55` → FESTIVIDADES (1er nivel)
- `Cod_sub_seccion = 306` → NAVIDAD (2do nivel)
- `DESACTIVADO = 0` → solo activos
- `TIPO_DOCUMEN <> 225` → excluye sucursal San Bernardino
- `desde_vta_anular = 0` → excluye anuladas
- `FECHA >= '2024-01-01'` → ventana de 24 meses

**Archivos generados en `C:\AITinketers\Tinketers\data\`:**

### `ventas_semanales_navidad.csv` (~50.000 filas)
Columnas: `sku, anio, semana, unidades_vendidas, importe_total_pyg`
- Agregación por SKU + año-semana ISO
- `unidades_vendidas` cast a INT, `importe_total_pyg` cast a BIGINT (en guaraníes)
- Filtra `HAVING SUM(...) > 0` (excluye semanas con neto cero o negativo por devoluciones)

### `productos_navidad.csv` (~7.300 filas)
Columnas: `sku, ean13, descripcion, descripcion_corta, section_id, subsection_id, group_id, category_id, subcategory_id, brand_id, supplier_id_default, country_origin, unit_of_measure, unit_cost_local, retail_price_a, weight_kg, volume_cc, perishable, shelf_days, units_on_hand, reorder_point, last_purchase_date`
- EAN13 obtenido de `productos_codigos.codigo_alternativo` vía OUTER APPLY (priorizando código de mayor longitud)
- Productos sin EAN13 → `ean13 = NULL`

---

## 5. Insight crítico — Tiering de SKUs

Diagnóstico ejecutado contra Pegasus:

| Tier | Criterio | n_SKUs | Unidades 24m |
|---|---|---|---|
| **A** | `weeks_with_sales >= 52 AND total_units >= 100` | 2 | 943 |
| **B** | `weeks_with_sales >= 52 AND total_units < 100` | 0 | — |
| **C** | `weeks_with_sales BETWEEN 12 AND 51` | 274 | 37.695 |
| **D** | `weeks_with_sales BETWEEN 1 AND 11` | 4.106 | **215.195 (85% del volumen)** |
| **E** | `weeks_with_sales = 0` | 2.924 | 0 |

**Conclusiones operativas:**
- **95% de los SKUs van por cold-start** vía `sku_donante` del similarity engine de Abi
- Solo ~280 SKUs (Tier A + C) ameritan **Holt-Winters individual**
- Tier D (4.106 SKUs) es el **núcleo del negocio**: estrictamente estacionales (8-22 semanas, octubre-diciembre)
- La consigna del PDF original asumía 52+ semanas como bar mayoritario; **para productos navideños es imposible** (solo venden en temporada). El criterio realista pasa a "apariciones en al menos 2 picos navideños"

---

## 6. Tareas y estado

| # | Tarea | Estado |
|---|---|---|
| 16 | Setup Neo4j local + repo Git del equipo | ✅ completed |
| **17** | **Script `cargar_ventas_semanales.py` (BLOQUEANTE)** | **🔄 in_progress (próximo paso)** |
| 18 | `ForecastResult` Pydantic con metadata decisional | ⬜ pending |
| 19 | `forecast()` async con `sku_donante` (Holt-Winters) | ⬜ pending |
| 20 | `caracterizar_serie()` pública para dispatcher | ⬜ pending |
| 21 | Monte Carlo deóntico-aware | ⬜ pending |
| 22 | Tests + benchmarks (forecast<100ms, sim 10k<5s) | ⬜ pending |
| 23 | Coordinación con Abi (30min agenda + aviso post-:VentaSemanal) | ⬜ pending |

---

## 7. Próxima acción concreta

**Crear `C:\AITinketers\Tinketers\cargar_ventas_semanales.py`** según spec sección 4.1.

### Estructura prevista del script

```
cargar_ventas_semanales.py
│
├── Modo dev (default): lee ventas_semanales_navidad.csv local
├── Modo prod: conecta directo a Pegasus con pyodbc
│
├── 1. Cargar .env (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, SQLSERVER_*)
├── 2. Leer datos (CSV o SQL)
├── 3. Validar tipos: sku str, anio int, semana int 1-53, unidades > 0
├── 4. Conectar a Neo4j con neo4j.GraphDatabase.driver
├── 5. UNWIND batches → MERGE :VentaSemanal idempotente
├── 6. Recalcular :Producto.velocidad = avg(unidades últimas 12 semanas)
├── 7. Recalcular :Producto.tieneHistorial = (count(VentaSemanal) >= 12)
├── 8. Reporte final: nodos creados, productos actualizados
└── 9. Test idempotencia (re-correr no debe duplicar)
```

### Cypher de carga (literal del spec)

```cypher
UNWIND $records AS r
MATCH (p:Producto {sku: r.sku})
MERGE (v:VentaSemanal {sku: r.sku, anio: r.anio, semana: r.semana})
SET v.unidades = r.unidades_vendidas,
    v.importe_pyg = r.importe_total_pyg
MERGE (p)-[:TIENE_VENTAS]->(v)
```

### Una vez cargado, avisar a Abi
> "Subí `cargar_ventas_semanales.py`. Ya están los `:VentaSemanal` en el graph.
> Podés recalcular `:velocidad` y `:tieneHistorial` con datos reales."

---

## 8. Decisiones técnicas tomadas

1. **Filtros Pegasus:** `Cod_seccion=55 + Cod_sub_seccion=306` (descubierto tras varios intentos — los códigos numéricos del árbol UI **no eran IDs sino conteos de items** en algunas pantallas)
2. **CSVs separados:** ventas (timeseries) y productos (master) en archivos distintos para no duplicar descripciones por cada semana
3. **Stack del forecast:** Holt-Winters (`statsmodels.tsa.holtwinters.ExponentialSmoothing`), no Prophet (que era una propuesta inicial mía pero el spec v2 pide Holt-Winters)
4. **Cold-start:** vía `sku_donante` que pasa Abi (NO vía categoría agregada como decía la consigna original)
5. **Dispatcher pattern:** mi forecast NO decide qué algoritmo usar — Abi lo decide y me llama con los parámetros adecuados

---

## 9. Gotchas y lecciones aprendidas

1. **CRLF en Windows + Git:** primer pull marca todos los archivos como modified. Solución: `git checkout .` y opcionalmente `git config core.autocrlf true`
2. **venv portable no existe:** el venv que vino en el repo (de Abi) tenía paths absolutos a su máquina. Solución: borrar y recrear con `py -3.12 -m venv venv`
3. **`ensurepip` falla a veces** al crear venv. Workaround: `py -3.12 -m venv venv --without-pip` + `get-pip.py` manual
4. **`chroma-hnswlib` requiere C++ Build Tools** de Microsoft (~7 GB). Solución: instalarlo en background, mientras tanto trabajar con deps mínimas
5. **Pegasus en `10.51.80.104,1402`:** server name con coma (no es typo, separa host y puerto en SQL Server)
6. **EAN13 en `productos_codigos.codigo_alternativo`** — los flags `principal` y `PRIMARIO` no se usan en este Pegasus (siempre 0 o ID), solución: usar `OUTER APPLY` para tomar uno cualquiera
7. **`UNIDADES` y `TOT_PRECIO` son `DECIMAL`** en Pegasus — para navideños conviene `CAST AS INT/BIGINT`

---

## 10. Estructura del workspace actual

```
C:\AITinketers\Tinketers\
├── .env                           ✅ credenciales (gitignored)
├── .gitignore                     ✅ excluye venv/, .env, chroma_db/, __pycache__/
├── requirements.txt               ✅ deps definidas
├── venv/                          ✅ entorno Python 3.12 (gitignored)
│
├── ontology/                      ← Abi: cliente Neo4j v1
│   ├── client.py                     OntologyClient (producto, proveedores_de_sku, etc.)
│   ├── aplicar_esquema.py
│   └── cargar_datos.py
│
├── ontology_semantic/             ← Abi: capa OWL/RDF (Bloques 1-5)
│   ├── bridge.py                     init_n10s, exportar_a_rdf, query_sparql
│   ├── reasoner.py                   HermiT
│   ├── client_v2.py                  OntologyClientV2
│   ├── similarity/                   engine para cold-start (sku_donante)
│   ├── marketplace.owl/.ttl
│   └── shapes.ttl                    SHACL constraints
│
├── rag/                           ← Abi: cliente RAG (catálogos PDF)
│   └── client.py                     RAGClient.buscar()
│
├── deontic/                       ← Abi: capa deóntica (en construcción)
│
├── tests/
│   ├── test_smoke.py                 valida ontology + RAG end-to-end
│   ├── test_bridge.py
│   ├── test_reasoner.py
│   └── test_similarity.py
│
├── data/                          ← datos del proyecto
│   ├── ventas_semanales_navidad.csv  ★ MIO ★ ~50K filas
│   ├── productos_navidad.csv         ★ MIO ★ ~7.3K filas
│   ├── CATALOGOS/                    PDFs + CSVs de proveedores
│   ├── proveedores.csv
│   ├── eventos_comerciales.csv
│   ├── snapshot.ttl                  snapshot del knowledge graph
│   └── ...                           (.nt de debug, otros CSVs)
│
├── chroma_db/                     ← vector store del RAG (gitignored)
│
├── HANDOFF_BLOQUE_5.md            ← contexto Bloque 5 (deóntica)
├── HANDOFF_BLOQUE_6.md            ← contexto Bloque 6 (similitud)
├── HANDOFF_CRIS.md                ★ ESTE ARCHIVO ★
└── README.md
```

---

## 11. Lo que falta crear (mis archivos)

```
C:\AITinketers\Tinketers\
├── cargar_ventas_semanales.py     ⬜ próximo paso (#17)
├── forecast/
│   ├── __init__.py
│   ├── forecast.py                ⬜ #18-#20: ForecastResult + forecast() + caracterizar_serie()
│   └── monte_carlo.py             ⬜ #21: simular() con restricciones
└── tests/
    └── test_forecast.py           ⬜ #22: tests + benchmarks
```

---

## 12. Cómo retomar en un chat nuevo

1. **Abrir un chat nuevo de Cowork** apuntando al mismo workspace `C:\AITinketers\Tinketers`
2. **Primera instrucción al nuevo chat:**

> "Soy Cris, Tarea 3 del proyecto NASA. Leé el archivo `HANDOFF_CRIS.md` en mi
> workspace para tomar contexto. Después decime qué información adicional
> necesitás antes de seguir con el item #17 (escribir `cargar_ventas_semanales.py`)."

3. **Documento de spec autoritativo a tener a mano:** `Especificaciones_CRIS.pdf`
   (subido en chats anteriores como contexto)
