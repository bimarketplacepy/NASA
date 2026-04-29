# Ontología Marketplace SA Paraguay — Justificación de la TBox (v1.0.0-bloque1)

> Este documento acompaña a `marketplace.ttl`. Para cada clase y propiedad explica
> **qué razonamiento habilita** y, donde aplica, **por qué NO se incluyeron otras**
> que podrían parecer obvias. Es la documentación que Mauri/Mati (Tarea 4) y Cris
> (Tarea 3) deberían leer antes de extender la ontología.

## URI base y versionado

`http://marketplace.com.py/onto/v1#`

El sufijo `/v1` es deliberado: cualquier cambio incompatible debe vivir en `/v2`
para no romper consumidores existentes. El header `owl:versionInfo "1.0.0-bloque1"`
permite trazabilidad fina dentro de la misma versión mayor.

## Capa de dominio retail

### `:Producto`
SKU comercializable. Identificado unívocamente por `:sku` (FunctionalProperty).
**Razonamiento habilitado**: clasificación automática en subclases derivables
(`:ProductoCritico`, `:ProductoAltaRotacion`, etc.) según axiomas que se definirán
en bloques de reglas.

### `:Seccion`, `:SubSeccion`, `:Grupo`, `:Categoria`
Jerarquía merceológica de cuatro niveles, igual a la del Neo4j v1. Se modelan
como clases separadas (no como una sola clase con un atributo `nivel`) para
permitir restricciones distintas en cada nivel sin contorsiones.
**Razonamiento habilitado**: la propiedad `:perteneceA` es transitiva, así que
un razonador puede inferir que un Producto pertenece al Grupo y a la SubSección
y a la Sección a partir de su Categoría directa.

### `:Proveedor`
Entidad que provee productos. Disjunto con `:Producto` (un individuo no puede
ser ambos a la vez).
**Razonamiento habilitado**: detección de inconsistencias si alguien por error
asocia un proveedor a una jerarquía de productos.

### `:EventoComercial`
Período temporal con características comerciales (Navidad 2026, Black Friday,
etc.). Se modela como clase de primera categoría porque las normas y los
algoritmos pueden ser específicos de un evento.

### `:Stock`
Reificación del estado de inventario. **Decisión deliberada**: en vez de poner
`cantidadStock` directamente como data property de Producto, lo hicimos entidad
separada. Razón: en bloques posteriores vamos a querer historial de stock,
y reificar permite agregar `:fechaSnapshot`, `:proveedorOrigen`, etc. sin
romper el modelo.

## Subclases derivables (vacías ahora — las llena el razonador)

| Clase | Padre | Cuándo será inferida |
|---|---|---|
| `:ProductoCritico` | `:Producto` | Producto con alta rotación + sin sustituto + impacto alto en facturación. Definición exacta en Bloque 5. |
| `:ProductoAltaRotacion` | `:Producto` | Velocidad de venta superior a umbral del Grupo. |
| `:ProductoPerecedero` | `:Producto` | Producto con vencimiento o degradación temporal. |
| `:ProveedorExterior` | `:Proveedor` | Proveedor con sede fuera de Paraguay. Activa normas aduaneras. |
| `:ProductoColdStart` | `:Producto` | Producto sin histórico suficiente. Activa similitud ponderada. |

**Por qué no se pueblan en este bloque**: si las llenamos ahora a mano, perdemos
la propiedad de que el razonador las deriva. La idea es que las **reglas** de
inferencia produzcan la membresía.

## Capa decisional

### `:Decision` y `:AlgorithmRecommendation`
`:Decision` es la superclase de todo acto decisional registrado. Una
`:AlgorithmRecommendation` es la subclase concreta para "decidí usar el algoritmo X".
**Razonamiento habilitado**: trazabilidad PROV-O en bloques posteriores
(Tarea 3 de Cris la consume).

### `:DecisionContext`
Snapshot de variables del entorno cuando se decide. Contiene referencias al
Producto, al EventoComercial, al Stock vigente, etc. Es el **input** del
algoritmo de selección de algoritmo.
**Por qué no es solo un dict de Python**: porque queremos consultarlo con
SPARQL para hacer auditoría retroactiva ("¿qué decisiones se tomaron cuando
había stock < 10?").

### `:Algorithm`
Catálogo de algoritmos candidatos. Cada algoritmo será un `owl:NamedIndividual`
de esta clase en Bloque 3 (ABox), no una subclase. Esto evita pasarse a OWL Full.

### `:SimilarityScore` y `:TrendSignal`
Reificaciones de un valor numérico contextualizado. Igual que `:Stock`, las
reificamos para soportar metadata (qué método produjo el score, cuándo, etc.).

### Disjunción `:Decision owl:disjointWith :Algorithm`
Una decisión NO es un algoritmo: una es el acto, otro la herramienta. Esto
detecta errores de modelado donde alguien confundiera ambos conceptos.

## Capa deóntica

### `:Norm` y sus tres modalidades
`:Obligation`, `:Permission`, `:Prohibition` son subclases disjuntas de `:Norm`
(via `owl:AllDisjointClasses`). Una norma concreta es **exactamente** una de las
tres modalidades clásicas de la lógica deóntica.

**Sutileza importante para el equipo**: la disjunción es a nivel de **clase**.
No contradice la **derrotabilidad** (`:defeats`): una `Obligation` puede ser
derrotada por otra norma de mayor `:priority`, pero sigue siendo una `Obligation`
(no se transforma en `Permission`). La derrotabilidad opera sobre la *vigencia*
de la norma en un contexto, no sobre su modalidad.

### `:defeats`
Object property asimétrica de `:Norm` a `:Norm`. Si A defeats B, entonces NO
puede ser B defeats A.
**Razonamiento habilitado**: en Bloque 5 vamos a usar SHACL + reglas para
implementar lógica deóntica defeasible (ej: "Permission de liquidación derrota
a Obligation de margen mínimo durante último mes del año").

## Object Properties — notas clave

| Propiedad | Característica OWL | Por qué |
|---|---|---|
| `:perteneceA` | Transitive | Permite que el razonador derive pertenencia a niveles superiores. |
| `:tieneStock` | Functional | Cada Producto tiene a lo sumo un Stock activo (snapshot vigente). |
| `:similarA` | Symmetric | Si A es similar a B, B es similar a A (simetría natural). |
| `:defeats` | Asymmetric | Si A derrota a B, B no derrota a A (anti-circularidad). |

## Data Properties — todas Functional

Casi todas las data properties son `owl:FunctionalProperty` porque cada
individuo debería tener a lo sumo un valor para cada una. La única excepción
podría ser `:enStock` si quisiéramos historial, pero como es snapshot vigente
también lo hicimos functional.

## Restricciones de cardinalidad

Solo restricciones **mínimas** para no sobre-comprometer la TBox:

- `:Producto` ⊑ `:sku` min 1 — un producto sin SKU no tiene sentido.
- `:Stock` ⊑ `:cantidadStock` exactly 1 — si es un Stock, tiene cantidad.
- `:Norm` ⊑ `:priority` exactly 1 — toda norma tiene prioridad para resolver conflictos.
- `:AlgorithmRecommendation` ⊑ `:derivadaDe` min 1 — toda recomendación traza a un contexto.

**Por qué no más restricciones ahora**: las restricciones fuertes (ej: cardinalidad
exactly 1 sobre `:perteneceA`) pueden generar inconsistencias en cold-start cuando
un Producto recién llega sin categorización completa. Eso lo resolveremos con
SHACL (Bloque 2), que permite advertir sin invalidar.

## Qué quedó AFUERA y por qué

### Clases del dominio transaccional excluidas
- **`:Compra`**, **`:Pedido`**, **`:LineaDePedido`**, **`:Cliente`**, **`:Carrito`**.
- **Razón**: esta ontología es **decisional**, no transaccional. No queremos
  modelar el flujo de compra-venta. Eso vive en el ERP. Aquí solo importan los
  inputs/outputs de las decisiones de optimización (qué stock tener, qué
  algoritmo usar, qué normas aplicar).

### Atributos de marketing excluidos
- **`:Marca`**, **`:Promocion`**, **`:Descuento`** como clases de primera categoría.
- **Razón**: pueden modelarse como `:EventoComercial` o como instancias dentro
  de `:DecisionContext`. Crear clases dedicadas las elevaría a ciudadanas de
  primera sin razón decisional clara hoy.

### Data properties excluidas
- `:precioVenta`, `:costoUnitario`: van en `:DecisionContext` cuando se necesiten,
  no como atributos del Producto. Razón: cambian todo el tiempo, asociarlos a
  Producto los vuelve volátiles y rompe la idea de TBox estable.
- `:descripcion` de productos: ya está en ChromaDB (RAG layer). Duplicarlo en la
  ontología es lo contrario de single-source-of-truth.

### Razonamiento ABoxiano excluido
- **No hay individuos** (`owl:NamedIndividual`) en este archivo. Eso es ABox y va
  en Bloque 3.

## Disciplina OWL 2 DL (qué se evitó deliberadamente)

1. **No se usó punning**: ninguna clase es también individuo. Esto mantiene
   compatibilidad estricta con OWL 2 DL.
2. **No hay propiedades que sean simultáneamente object y data**: `:enStock` es
   datatype (booleano), `:tieneStock` es object property a `:Stock`. Nombres
   distintos para conceptos distintos.
3. **`unionOf` solo en domain/range, no como superclase de individuos**: usar
   `owl:unionOf` para domain/range es DL-safe; usarlo para clasificar individuos
   directamente requiere cuidado.
4. **No se redefinieron términos del namespace `owl:` ni `rdf:`**: prevenir
   `OWL Full` por accidente.

## Qué se construye encima de esto

- **Bloque 2**: SHACL shapes que validan datos de la ABox (cardinalidades fuertes
  de validación, no axiomas TBox).
- **Bloque 3**: ABox — instancias concretas de algoritmos, normas iniciales,
  eventos comerciales conocidos.
- **Bloque 4**: razonamiento con HermiT — derivar `:ProductoCritico`, etc.
- **Bloque 5**: lógica deóntica defeasible operando sobre `:defeats` y `:priority`.
- **Bloque 6+**: integración con Neo4j vía Neosemantics (sincronizar ABox).
