# Tarea 1 — Ontología y RAG

Capa de conocimiento del sistema de retail navideño de Marketplace SA Paraguay.

Este módulo expone **dos clientes Python** que el resto del equipo usa para acceder al conocimiento del dominio sin tener que aprender Cypher ni manejar embeddings:

- **`OntologyClient`** — consulta el knowledge graph en Neo4j (productos, categorías, proveedores, eventos comerciales y sus relaciones).
- **`RAGClient`** — búsqueda semántica sobre catálogos PDF de proveedores (MOQ, lead times, condiciones comerciales).

## Quickstart para usar el módulo

```python
from ontology import OntologyClient
from rag import RAGClient

# Información estructurada del catálogo (Neo4j)
with OntologyClient() as ont:
    info = ont.producto("219814")
    proveedores = ont.proveedores_de_sku("219814")
    a_reponer = ont.productos_a_reponer(limit=10)

# Búsqueda semántica en catálogos PDF (ChromaDB)
with RAGClient() as rag:
    resultados = rag.buscar("MOQ típico desde China", k=5)
    solo_dalian = rag.buscar("lead time", k=3, proveedor_id="SUP-01")
```

Las credenciales (Neo4j) se leen del `.env`. Los embeddings se persisten en `chroma_db/`.

## Setup inicial (primera vez)

### Pre-requisitos

- **Python 3.12** (otras versiones tienen problemas con dependencias ML).
- **Docker Desktop** corriendo.
- Conectividad a tu base **SQL Server (Pegasus)** con usuario de solo lectura.
- Credenciales `.env` en la raíz del proyecto (ver formato abajo).

### Pasos

```powershell
# 1. Clonar / acceder al proyecto
cd tarea1-ontologia-rag

# 2. Crear entorno virtual con Python 3.12
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Levantar Neo4j (primera vez crea el contenedor)
docker run -d --name neo4j-marketplace `
  -p 7474:7474 -p 7687:7687 `
  -e NEO4J_AUTH=neo4j/marketplace2026 `
  -v neo4j-data:/data `
  neo4j:5

# 5. Aplicar el esquema (constraints + índices)
python ontology\aplicar_esquema.py

# 6. Exportar datos desde Pegasus a CSVs
python exportar_a_csv.py

# 7. Generar el CSV de eventos comerciales
python generar_eventos.py

# 8. Cargar los CSVs a Neo4j
python ontology\cargar_datos.py

# 9. Indexar los catálogos PDF en ChromaDB
python rag\ingesta.py

# 10. (opcional) Smoke test
python tests\test_smoke.py
```

### Archivo `.env` requerido

```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=marketplace2026

SQLSERVER_DRIVER=ODBC Driver 17 for SQL Server
SQLSERVER_HOST=<host_pegasus>
SQLSERVER_PORT=1433
SQLSERVER_DATABASE=pegasus
SQLSERVER_USER=<usuario_solo_lectura>
SQLSERVER_PASSWORD=<password>
```

### Uso día a día

Cuando reinicias la PC o cierras Docker, Neo4j se apaga. Para retomar:

```powershell
docker start neo4j-marketplace
.\venv\Scripts\Activate.ps1
```

Listo. Los datos persisten — no hay que re-cargar nada.

## Arquitectura

```
                  ┌─────────────────────────┐
                  │  Tu código (Tareas 3,   │
                  │  4, 5, 6 del proyecto)  │
                  └────────┬────────────────┘
                           │
          ┌────────────────┴────────────────┐
          ▼                                 ▼
  ┌───────────────┐                ┌────────────────┐
  │ OntologyClient│                │   RAGClient    │
  │   (Python)    │                │    (Python)    │
  └───────┬───────┘                └────────┬───────┘
          │                                 │
          ▼                                 ▼
  ┌───────────────┐                ┌────────────────┐
  │   Neo4j 5     │                │   ChromaDB     │
  │  (Docker)     │                │  (persistente  │
  │ knowledge     │                │   en disco)    │
  │  graph        │                │ vector store   │
  └───────┬───────┘                └────────┬───────┘
          │                                 │
   carga via                          ingesta via
   cargar_datos.py                    rag/ingesta.py
          │                                 │
          ▼                                 ▼
  ┌───────────────┐                ┌────────────────┐
  │  data/*.csv   │                │ data/CATALOGOS │
  │ exportados de │                │   *.pdf de     │
  │   Pegasus     │                │  proveedores   │
  └───────┬───────┘                └────────────────┘
          │
   exportar_a_csv.py
          │
          ▼
  ┌───────────────┐
  │  SQL Server   │
  │   Pegasus     │
  └───────────────┘
```

## Modelo de datos en Neo4j

Jerarquía de 4 niveles + producto + proveedor:

```
:Seccion (FESTIVIDADES)
  └── :SubSeccion (NAVIDAD)
        └── :Grupo (ADORNOS, BANDEJAS, ...)
              └── :Categoria (ESFERAS, FLORES, ...)
                    └── :Producto
                          └── :SUMINISTRADO_POR → :Proveedor
```

Plus `:EventoComercial` sueltos para el calendario comercial.

### Conteos típicos (a abril 2026)

| Tipo | Cantidad |
|---|---|
| Secciones | 1 |
| SubSecciones | 1 |
| Grupos | ~15 |
| Categorias | 64 |
| Productos | ~4,600 |
| ↳ en stock | ~2,100 |
| ↳ candidatos a restock | ~2,500 |
| Proveedores | ~60 |
| Eventos comerciales | 8 |
| Aristas SUMINISTRADO_POR | ~3,600 |

## API del `OntologyClient`

| Método | Devuelve | Usado por |
|---|---|---|
| `producto(sku)` | Ficha completa + jerarquía | Todos |
| `productos_en_categoria(cat_id)` | Lista de SKUs de la categoría | Tarea 4, 5 |
| `productos_a_reponer(limit)` | SKUs sin stock vendidos recientemente | Tarea 4 |
| `proveedor(id)` | Ficha del proveedor | Todos |
| `proveedores_de_sku(sku)` | Quién suministra + condiciones | Tarea 4, 5 |
| `proveedores_similares(id)` | Alternativas para sustituir | Tarea 5 |
| `categoria_de_sku(sku)` | Categoría + jerarquía + agregados | Tarea 3 |
| `categorias()` | Todas las categorías con conteos | UI |
| `sustitutos_de_sku(sku)` | Placeholder `[]` (futuro) | Tarea 4, 5 |
| `eventos_proximos(dias)` | Calendario comercial activo | Tarea 4, 5 |

Ver docstrings en `ontology/client.py` para detalles, ejemplos y formato de retorno.

## API del `RAGClient`

| Método | Devuelve |
|---|---|
| `buscar(query, k, proveedor_id)` | Top-k chunks más relevantes con score |
| `proveedores_indexados()` | Lista de catálogos disponibles |

Ver docstrings en `rag/client.py`.

## Filtros y decisiones aplicadas

- **Universo de productos**: solo navideños (`cod_sub_seccion = 306`) con actividad reciente: stock actual O ventas/compras desde 2024-01-01.
- **Stock negativo**: tratado como 0 al sumar entre depósitos.
- **`perecedero`**: derivado del nombre de la categoría (TURRONES, CHOCOLATES, ALFAJORES, PAN DULCE, GALLETITAS, CARAMELOS).
- **`proveedor_exterior`**: derivado de existir compras con `TIPO_DOCUMEN = 20` (importación) en Pegasus.
- **Precio de venta**: la venta más reciente desde 2024 en `VENTAS_DET.PRECIO_LISTA` (no la columna de Pegasus que está vacía).
- **Eventos comerciales**: hardcoded en `generar_eventos.py` (Pegasus no tiene tabla de eventos).

## Gaps conocidos

- **MOQ, lead time, descuentos por volumen**: no están en Pegasus de forma utilizable. Se llenan vía RAG (catálogos PDF) o estimación manual posterior.
- **Sustitutos automáticos** (`[:SUSTITUYE_A]`): la arista existe en el modelo pero no se llena. Iteración futura: similaridad por embeddings de descripción.
- **Atributos agregados de forecast** (factor estacional, demanda promedio): los va a poblar la Tarea 3 (Cris) sobre los nodos `:Categoria`.

## Cuándo refrescar los datos

- **Pegasus → Neo4j**: re-correr `python exportar_a_csv.py && python ontology\cargar_datos.py` cuando quieras un snapshot fresco. Tarda 1-2 minutos.
- **Catálogos PDF → ChromaDB**: drop nuevos PDFs en `data/CATALOGOS/` y correr `python rag\ingesta.py`. Idempotente.
- **Eventos comerciales**: editar la lista en `generar_eventos.py` y re-correr el script. La carga al grafo se hace con `cargar_datos.py`.

## Estructura del proyecto

```
tarea1-ontologia-rag/
├── ontology/
│   ├── __init__.py
│   ├── client.py            ← OntologyClient (producto entregable 1)
│   ├── schema.cypher        ← constraints e índices
│   ├── aplicar_esquema.py   ← aplica el schema a Neo4j
│   └── cargar_datos.py      ← lee CSVs y popula Neo4j
├── rag/
│   ├── __init__.py
│   ├── client.py            ← RAGClient (producto entregable 2)
│   ├── ingesta.py           ← lee PDFs, chunkea, guarda en ChromaDB
│   └── generar_pdfs_prueba.py  ← (legacy) PDFs sintéticos básicos
├── data/
│   ├── CATALOGOS/           ← PDFs y CSVs de catálogos de proveedores
│   ├── secciones.csv
│   ├── subsecciones.csv
│   ├── grupos.csv
│   ├── categorias.csv
│   ├── productos.csv
│   ├── proveedores.csv
│   ├── relaciones_comerciales.csv
│   ├── precios_venta.csv
│   └── eventos_comerciales.csv
├── tests/
│   └── test_smoke.py        ← smoke test integrado
├── chroma_db/               ← (gitignore) vector store persistido
├── venv/                    ← (gitignore) entorno virtual
├── .env                     ← (gitignore) credenciales
├── .gitignore
├── exportar_a_csv.py        ← Pegasus → CSVs
├── generar_eventos.py       ← regenera eventos_comerciales.csv
├── demo_cliente_ontologia.py ← demo del OntologyClient
├── demo_cliente_rag.py      ← demo del RAGClient
├── requirements.txt
└── README.md                ← este archivo
```

## Dependencias del equipo (qué consume Tarea 1)

| Tarea | Cliente | Métodos usados |
|---|---|---|
| 3 — Forecasting (Cris) | OntologyClient | `categoria_de_sku()` para cold-start, `productos_en_categoria()` |
| 4 — Optimizador (Mauri/Mati) | OntologyClient + RAGClient | `proveedores_de_sku()`, `productos_a_reponer()`, `eventos_proximos()`, `rag.buscar()` para MOQ/lead-time |
| 5 — Multi-agente (Mauri/Mati) | Ambos | Todos los métodos registrados como tools del orquestador |
| 6 — Frontend (Franky) | Indirecto vía Tarea 4 | (no toca este módulo directamente) |

## Contacto y mantenimiento

Tarea responsable: ABI. Ante dudas, preguntar antes de modificar el modelo del knowledge graph o el contrato de los clientes — esos son los puntos de coordinación con el resto del equipo.

Cualquier cambio en la API pública de `OntologyClient` o `RAGClient` requiere avisar a Tarea 5 antes (porque rompe los tools del LLM).
