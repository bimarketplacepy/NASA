# Bridge Neo4j ↔ RDF con Neosemantics (n10s)

> Documenta la instalación del plugin **Neosemantics 5.20.0** sobre el contenedor
> `neo4j-marketplace`, la configuración inicial (`graphconfig.init`), los mapeos
> OWL → Neo4j, y la arquitectura del módulo `bridge.py`.

## Versión

| Componente | Versión | Por qué |
|---|---|---|
| Neo4j | 5.20.0 | La que ya corre el equipo. |
| Neosemantics | **5.20.0** | El plugin debe matchear major.minor de Neo4j EXACTAMENTE. La release 5.20.0 fue publicada 2024-06-05 con notas que dicen "Update to Neo4j 5.20.0". Cualquier otra versión rompe. |
| Driver Python `neo4j` | 5.20.0 (ya instalado) | Sin cambios. |

---

## Arquitectura del bridge — decisión clave

La spec original del bloque pedía `query_sparql()` "vía n10s". Investigación contra docs oficiales reveló que **n10s 5.x no traduce SPARQL → Cypher**. Lo que ofrece n10s es:

1. **Importar RDF a Neo4j** (`n10s.rdf.import.fetch`, `n10s.onto.import.fetch`).
2. **Exportar Neo4j a RDF** (`n10s.rdf.export.cypher`).
3. **HTTP endpoint** que sirve Turtle/N-Triples si configurás
   `server.unmanaged_extension_classes=n10s.endpoint=/rdf`.

**Decisión arquitectónica adoptada (best practice profesional):**

```text
                 ┌──────────────┐
                 │  Neo4j 5.20  │ ← fuente de verdad operacional (4644 SKUs).
                 └──────┬───────┘
                        │ export via n10s.rdf.export.cypher
                        ▼
              ┌────────────────────┐
              │ rdflib.Graph       │ ← grafo en memoria, derivado.
              └─────────┬──────────┘
                        │ rdflib.Graph.query(sparql)
                        ▼
              ┌────────────────────┐
              │ pandas.DataFrame   │
              └────────────────────┘
```

Justificación: la única forma honesta de correr SPARQL contra una base Neo4j es exportarla (o un subgrafo relevante) a un grafo RDF in-memory y consultarla ahí. **Importante:** la base de verdad sigue siendo Neo4j; rdflib es un cache temporario. Documentamos esto para que Mauri/Mati (Tarea 4) y Cris (Tarea 3) no esperen consultas SPARQL "live" sobre Neo4j — sería caro y poco útil.

---

## Pasos de instalación (ejecutar EN POWERSHELL desde la carpeta del proyecto)

> ⚠️ **Backup primero.** Si algo sale mal con el restart, querés poder volver atrás.

### 1. Backup del volumen Docker (idempotente, no destructivo)

```powershell
# Crear carpeta de backups si no existe
New-Item -ItemType Directory -Force -Path .\backups | Out-Null

# Identificar el volumen de datos del contenedor neo4j-marketplace
$volName = (docker inspect neo4j-marketplace --format '{{ range .Mounts }}{{ if eq .Type "volume" }}{{ .Name }}{{ end }}{{ end }}' | Select-Object -First 1)
Write-Host "Volumen Neo4j detectado: $volName"

# Tar del volumen a un archivo timestamped
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
docker run --rm -v ${volName}:/source -v ${PWD}\backups:/backup alpine `
    tar czf /backup/neo4j_volume_$ts.tar.gz -C /source .
Write-Host "Backup creado en backups\neo4j_volume_$ts.tar.gz"
```

### 2. Detener el contenedor

```powershell
docker stop neo4j-marketplace
```

### 3. Descargar el .jar de neosemantics 5.20.0

URL exacta:
`https://github.com/neo4j-labs/neosemantics/releases/download/5.20.0/neosemantics-5.20.0.jar`

```powershell
# Crear carpeta donde guardamos plugins de Neo4j (si no existe ya)
New-Item -ItemType Directory -Force -Path .\neo4j_plugins | Out-Null

# Descargar el .jar (idempotente: si ya existe, no descarga de nuevo)
$jarPath = ".\neo4j_plugins\neosemantics-5.20.0.jar"
if (-Not (Test-Path $jarPath)) {
    Invoke-WebRequest `
      -Uri "https://github.com/neo4j-labs/neosemantics/releases/download/5.20.0/neosemantics-5.20.0.jar" `
      -OutFile $jarPath
    Write-Host "Descargado neosemantics-5.20.0.jar"
} else {
    Write-Host "Ya existe $jarPath; skip download"
}
```

### 4. Copiar el .jar dentro del contenedor

Hay dos caminos según cómo se haya creado tu contenedor:

**Camino A — el contenedor existente tiene el directorio `/plugins` montado a un volumen Docker:**

```powershell
# Inspeccionar el contenedor para ver el volume de plugins
docker inspect neo4j-marketplace --format '{{ range .Mounts }}{{ if eq .Destination "/plugins" }}{{ .Source }}{{ "`n" }}{{ end }}{{ end }}'
# Si imprime un path local: copiar el .jar ahi.
# Si imprime un volume name: hacer el copy via `docker cp` mientras el container esta detenido.

docker cp .\neo4j_plugins\neosemantics-5.20.0.jar neo4j-marketplace:/plugins/neosemantics-5.20.0.jar
```

**Camino B — recrear el contenedor con el plugin como bind mount:**

Si tu contenedor original no tenía `/plugins` montado, lo más limpio es recrearlo (los datos persisten porque están en el volumen de data, no en /plugins):

```powershell
# Recordar el comando docker run original. Tipico para Neo4j 5:
docker rm neo4j-marketplace

docker run -d --name neo4j-marketplace `
  -p 7474:7474 -p 7687:7687 `
  -e NEO4J_AUTH=neo4j/<password> `
  -e NEO4J_PLUGINS='["apoc"]' `
  -e NEO4J_dbms_security_procedures_unrestricted='apoc.*,n10s.*' `
  -e NEO4J_dbms_security_procedures_allowlist='apoc.*,n10s.*' `
  -v neo4j-marketplace-data:/data `
  -v ${PWD}\neo4j_plugins:/plugins `
  neo4j:5.20.0
```

> Reemplazá `<password>` por el password real de tu `.env` (NEO4J_PASSWORD). Y verificá que estás usando el mismo nombre de volumen que ya tenías para no perder datos.

### 5. Encender el contenedor (si lo paraste sin recrear) y verificar

```powershell
docker start neo4j-marketplace
Start-Sleep -Seconds 15

# Verificar que n10s cargo. Esperado: una linea por cada procedure del namespace n10s.
docker exec neo4j-marketplace cypher-shell -u neo4j -p <password> `
  "SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'n10s' RETURN count(name) AS n_procs"
```

Esperado: `n_procs` >= 50 aprox. Si `n_procs = 0`, el plugin no se cargó — revisar logs:

```powershell
docker logs --tail 100 neo4j-marketplace | Select-String -Pattern "n10s|neosemantics|ERROR"
```

---

## Inicialización de n10s (idempotente desde Python)

`bridge.init_n10s()` corre estos cyphers **solo si no fueron corridos antes**:

```cypher
-- 1. Constraint requerido por n10s para identificar Resources unicos
CREATE CONSTRAINT n10s_unique_uri IF NOT EXISTS
FOR (r:Resource) REQUIRE r.uri IS UNIQUE;

-- 2. Configuracion del grafo (singleton _GraphConfig). Si ya existe, n10s
-- devuelve un error que capturamos y tratamos como idempotente.
CALL n10s.graphconfig.init({
    handleVocabUris:   'SHORTEN',
    handleMultival:    'ARRAY',
    handleRDFTypes:    'LABELS',
    applyNeo4jNaming:   true,
    keepLangTag:        true
});
```

### Justificación de cada flag

| Flag | Valor | Por qué |
|---|---|---|
| `handleVocabUris` | `'SHORTEN'` | Usa prefijos para acortar URIs en labels y propiedades. Más legible que `KEEP` (URIs completas) y más estándar que `MAP` (que requiere mapeo explícito por cada término). |
| `handleMultival` | `'ARRAY'` | Si una propiedad tiene múltiples valores en RDF, los guardamos como Neo4j array property en vez de pisar el último (`OVERWRITE`). Critico para no perder datos. |
| `handleRDFTypes` | `'LABELS'` | `rdf:type :Producto` se vuelve label `:Producto` en Neo4j (idiomático). Alternativa `LABELS_AND_NODES` también crea nodo Resource — más overhead, no lo necesitamos. |
| `applyNeo4jNaming` | `true` | Aplica conventions Neo4j (labels en CamelCase, relaciones en SCREAMING_SNAKE) automáticamente. |
| `keepLangTag` | `true` | Preserva `@es` en literales como nuestros `rdfs:label "Producto"@es`. |

### Mappings explícitos OWL ↔ Neo4j

Nuestra ontología usa camelCase (`:cantidadStock`) y la base Neo4j v1 usa snake_case (`cantidad_stock`). Los puenteamos con `n10s.mapping.add`:

```cypher
-- Prefijo de namespace
CALL n10s.nsprefixes.add('mkt', 'http://marketplace.com.py/onto/v1#');

-- Mapeos clase OWL -> label Neo4j (mismo nombre, cubre ambos sentidos)
CALL n10s.mapping.add('http://marketplace.com.py/onto/v1#Producto',        'Producto');
CALL n10s.mapping.add('http://marketplace.com.py/onto/v1#Categoria',       'Categoria');
CALL n10s.mapping.add('http://marketplace.com.py/onto/v1#Grupo',           'Grupo');
CALL n10s.mapping.add('http://marketplace.com.py/onto/v1#SubSeccion',      'SubSeccion');
CALL n10s.mapping.add('http://marketplace.com.py/onto/v1#Seccion',         'Seccion');
CALL n10s.mapping.add('http://marketplace.com.py/onto/v1#Proveedor',       'Proveedor');
CALL n10s.mapping.add('http://marketplace.com.py/onto/v1#EventoComercial', 'EventoComercial');

-- Mapeos relacion OWL -> tipo de arista Neo4j
CALL n10s.mapping.add('http://marketplace.com.py/onto/v1#perteneceA',     'PERTENECE_A');
CALL n10s.mapping.add('http://marketplace.com.py/onto/v1#suministradoPor','SUMINISTRADO_POR');

-- Mapeos data property OWL camelCase -> Neo4j snake_case
CALL n10s.mapping.add('http://marketplace.com.py/onto/v1#sku',                  'sku');
CALL n10s.mapping.add('http://marketplace.com.py/onto/v1#cantidadStock',        'cantidad_stock');
CALL n10s.mapping.add('http://marketplace.com.py/onto/v1#enStock',              'en_stock');
CALL n10s.mapping.add('http://marketplace.com.py/onto/v1#fechaUltimaCompra',    'fecha_ultima_compra');
CALL n10s.mapping.add('http://marketplace.com.py/onto/v1#pais',                 'pais');
```

`bridge.init_n10s()` aplica estos mappings vía Python automáticamente.

---

## Anti-patterns a evitar

1. **No correr `MATCH (n) DETACH DELETE n` por accidente.** El bridge nunca borra nodos. Si necesitás resetear: `bridge.reset_n10s_config()` (que borraría solo el `_GraphConfig` y los `_NsPrefDef`/`_MapDef`/`_MapNs`, NO los datos).
2. **No mezclar URIs `:Producto` (RDF) con label `:Producto` (Cypher) sin namespace explícito.** En Cypher el `:` es separador de label; en Turtle, el `:` es prefijo del namespace default. Confundirlos lleva a queries que parecen razonables y no devuelven nada. Cuando estés en SPARQL siempre usá `mkt:Producto` (o full URI).
3. **No re-importar la ontología completa cada vez.** `importar_owl_a_neo4j()` es idempotente por diseño, pero igual: solo correlo cuando cambia el `marketplace.ttl`.

---

## Troubleshooting frecuente

| Síntoma | Causa probable | Solución |
|---|---|---|
| `Neo.ClientError.Procedure.ProcedureNotFound` para `n10s.*` | Plugin no cargó. | Verificar logs del contenedor (paso 5). Usualmente: jar version no matchea Neo4j 5.20.0, o falta `dbms.security.procedures.unrestricted=n10s.*`. |
| `n10s.graphconfig.init` falla con "GraphConfig already exists" | Ya inicializado (idempotencia). | El bridge captura este error como OK. Si insistís en re-init: `bridge.reset_n10s_config()`. |
| Export SPARQL devuelve 0 filas pero hay datos | URI usado en SPARQL no coincide con URI generada por n10s SHORTEN. | Mirá el output de `exportar_a_rdf` y usa los prefijos exactos que n10s asignó. |
| `n10s.rdf.export.cypher` tira error sobre "showOnlyMapped" | Versión vieja del plugin. | Confirmar n10s 5.20.0 (no 5.14 ni anteriores). |

---

## Sources

- [neosemantics GitHub releases](https://github.com/neo4j-labs/neosemantics/releases)
- [neosemantics installation docs](https://neo4j.com/labs/neosemantics/installation/)
- [neosemantics config (handleVocabUris, handleMultival)](https://neo4j.com/labs/neosemantics/4.0/config/)
- [neosemantics export RDF](https://neo4j.com/labs/neosemantics/4.3/export/)
- [neosemantics mapping](https://neo4j.com/labs/neosemantics/4.3/mapping/)
