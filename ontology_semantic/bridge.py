"""Bridge Neo4j <-> RDF via Neosemantics (n10s).

Tres operaciones publicas:

1. exportar_a_rdf(salida_ttl): vuelca el grafo Neo4j actual a Turtle usando
   n10s.rdf.export.cypher. El archivo resultante carga limpio en rdflib.

2. importar_owl_a_neo4j(input_ttl): importa la TBox de marketplace.ttl al
   Neo4j vía n10s.rdf.import.inline. Idempotente: re-importar no duplica
   meta-nodos (n10s usa MERGE internamente sobre URIs).

3. query_sparql(query): exporta Neo4j -> rdflib (cache opcional via
   snapshot_path), corre SPARQL en rdflib, devuelve pandas.DataFrame.
   (n10s 5.x no traduce SPARQL a Cypher; export+rdflib es la
   arquitectura limpia documentada en README_n10s.md.)

Tambien hay helpers internos:
- init_n10s: aplica graphconfig.init y los mappings OWL<->Neo4j de forma
  idempotente.
- _Bridge: la clase con context manager y manejo de driver lazy.

Las credenciales de Neo4j se leen del .env del proyecto raiz (NEO4J_URI,
NEO4J_USER, NEO4J_PASSWORD). El cliente reusa el patron del v1
ontology/client.py para que Mauri/Mati/Cris no aprendan dos APIs distintas.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import rdflib
from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase

# ----------------------------------------------------------------------------
# Constantes del namespace marketplace y mappings OWL <-> Neo4j.
# ----------------------------------------------------------------------------

MKT_NS: str = "http://marketplace.com.py/onto/v1#"
MKT_PREFIX: str = "mkt"

# Mapeos OWL URI -> Neo4j label/property/relationship.
# Si Neo4j ya tiene labels en CamelCase mismos que OWL (ej Producto), el mapeo
# es identidad pero igual lo registramos para que n10s lo aplique
# explicitamente en imports/exports.
DEFAULT_MAPPINGS: list[tuple[str, str]] = [
    # Clases -> labels
    (f"{MKT_NS}Producto",        "Producto"),
    (f"{MKT_NS}Categoria",       "Categoria"),
    (f"{MKT_NS}Grupo",           "Grupo"),
    (f"{MKT_NS}SubSeccion",      "SubSeccion"),
    (f"{MKT_NS}Seccion",         "Seccion"),
    (f"{MKT_NS}Proveedor",       "Proveedor"),
    (f"{MKT_NS}EventoComercial", "EventoComercial"),
    # Object properties -> tipos de relacion
    (f"{MKT_NS}perteneceA",      "PERTENECE_A"),
    (f"{MKT_NS}suministradoPor", "SUMINISTRADO_POR"),
    # Data properties OWL camelCase -> Neo4j snake_case
    (f"{MKT_NS}sku",                  "sku"),
    (f"{MKT_NS}cantidadStock",        "cantidad_stock"),
    (f"{MKT_NS}enStock",              "en_stock"),
    (f"{MKT_NS}fechaUltimaCompra",    "fecha_ultima_compra"),
    (f"{MKT_NS}pais",                 "pais"),
    # Bloque 4: features para razonamiento HermiT
    (f"{MKT_NS}perecedero",           "perecedero"),
    (f"{MKT_NS}esExterior",           "proveedor_exterior"),
]

DEFAULT_GRAPH_CONFIG: dict[str, object] = {
    "handleVocabUris":  "SHORTEN",
    "handleMultival":   "ARRAY",
    "handleRDFTypes":   "LABELS",
    "applyNeo4jNaming":  True,
    "keepLangTag":       True,
}

HERE: Path = Path(__file__).resolve().parent


# ----------------------------------------------------------------------------
# Estructuras de retorno.
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class InitResult:
    """Resultado de inicializar n10s en la base.

    Attributes:
        graphconfig_created: True si fue creado ahora; False si ya existia.
        constraint_created: True si el unique constraint sobre Resource.uri
            fue creado ahora.
        n_mappings_applied: Cantidad de mappings registrados (incluye los
            que ya existian — n10s.mapping.add es idempotente).
    """

    graphconfig_created: bool
    constraint_created: bool
    n_mappings_applied: int


@dataclass(frozen=True)
class ImportResult:
    """Resultado de importar una ontologia OWL a Neo4j.

    Attributes:
        terminationStatus: 'OK' si fue exitoso, otro string si fallo parcial.
        triplesLoaded: Cantidad de tripletas cargadas (puede ser menor al
            archivo origen si n10s ignora algunos por configuracion).
        triplesParsed: Cantidad de tripletas parseadas del input.
        extraInfo: Mensaje detallado adicional, si lo hubo.
    """

    terminationStatus: str
    triplesLoaded: int
    triplesParsed: int
    extraInfo: str = ""


@dataclass(frozen=True)
class ExportResult:
    """Resultado de exportar Neo4j a un archivo RDF/Turtle.

    Attributes:
        salida_ttl: Path absoluto del archivo escrito.
        n_triples: Cantidad de tripletas exportadas.
    """

    salida_ttl: Path
    n_triples: int


# ----------------------------------------------------------------------------
# Cliente principal.
# ----------------------------------------------------------------------------


class _Bridge:
    """Cliente de bajo nivel para hablar con Neo4j a traves de n10s.

    Usar via las funciones publicas (init_n10s, exportar_a_rdf, etc.) o como
    context manager:

        with _Bridge() as br:
            br.init_n10s()
            br.exportar_a_rdf(Path("snapshot.ttl"))

    La conexion al driver de Neo4j es lazy. Las credenciales se leen del .env.
    """

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        load_dotenv()
        self.uri = uri or os.getenv("NEO4J_URI")
        self.user = user or os.getenv("NEO4J_USER")
        self.password = password or os.getenv("NEO4J_PASSWORD")
        if not all([self.uri, self.user, self.password]):
            raise RuntimeError(
                "Faltan credenciales Neo4j. Verifica que .env tiene "
                "NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD."
            )
        self._driver: Optional[Driver] = None

    @property
    def driver(self) -> Driver:
        """Driver lazy. Verifica connectivity la primera vez."""
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self.uri, auth=(self.user, self.password)
            )
            try:
                self._driver.verify_connectivity()
            except Exception as exc:
                raise RuntimeError(
                    f"No se pudo conectar a Neo4j en {self.uri!r}. "
                    f"Causa: {type(exc).__name__}: {exc}. "
                    f"Verifica que el contenedor neo4j-marketplace este "
                    f"corriendo y las credenciales del .env sean correctas."
                ) from exc
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def __enter__(self) -> "_Bridge":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Setup idempotente
    # ------------------------------------------------------------------

    def init_n10s(
        self,
        graph_config: Optional[dict[str, object]] = None,
        mappings: Optional[list[tuple[str, str]]] = None,
        ns_prefix: str = MKT_PREFIX,
        ns_uri: str = MKT_NS,
    ) -> InitResult:
        """Inicializa n10s en la base de forma idempotente.

        Crea el unique constraint sobre Resource.uri (requerido por n10s),
        ejecuta n10s.graphconfig.init si no existe ya, registra el namespace
        y aplica los mappings OWL <-> Neo4j.

        Args:
            graph_config: Config para graphconfig.init. Default: DEFAULT_GRAPH_CONFIG.
            mappings: Lista (uri_owl, neo4j_name). Default: DEFAULT_MAPPINGS.
            ns_prefix: Prefijo corto del namespace marketplace. Default 'mkt'.
            ns_uri: URI base del namespace marketplace.

        Returns:
            InitResult con booleans de "fue creado ahora vs ya existia".

        Raises:
            RuntimeError: Si la conexion a Neo4j falla o si n10s no esta
                instalado en el server (procedures n10s.* no encontradas).
        """
        cfg = graph_config or DEFAULT_GRAPH_CONFIG
        maps = mappings or DEFAULT_MAPPINGS

        with self.driver.session() as session:
            # 1. Constraint unique sobre Resource.uri (n10s lo requiere).
            constraint_created = self._ensure_resource_uri_constraint(session)

            # 2. graphconfig.init - idempotente: si ya existe, capturamos.
            graphconfig_created = self._ensure_graphconfig(session, cfg)

            # 3. Namespace prefix (idempotente).
            session.run(
                "CALL n10s.nsprefixes.add($prefix, $uri)",
                prefix=ns_prefix, uri=ns_uri,
            )

            # 4. Mappings (n10s.mapping.add es idempotente sobre el par).
            for uri, neo4j_name in maps:
                session.run(
                    "CALL n10s.mapping.add($uri, $neo4j_name)",
                    uri=uri, neo4j_name=neo4j_name,
                )

        return InitResult(
            graphconfig_created=graphconfig_created,
            constraint_created=constraint_created,
            n_mappings_applied=len(maps),
        )

    @staticmethod
    def _ensure_resource_uri_constraint(session: object) -> bool:
        """Crea el constraint Resource.uri unique si no existe. Devuelve True
        si lo creo ahora; False si ya estaba.
        """
        # SHOW CONSTRAINTS YIELD name WHERE ...
        existing = session.run(  # type: ignore[attr-defined]
            "SHOW CONSTRAINTS YIELD name WHERE name = 'n10s_unique_uri' "
            "RETURN count(name) AS n"
        ).single()
        if existing and existing["n"] > 0:
            return False
        session.run(  # type: ignore[attr-defined]
            "CREATE CONSTRAINT n10s_unique_uri IF NOT EXISTS "
            "FOR (r:Resource) REQUIRE r.uri IS UNIQUE"
        )
        return True

    @staticmethod
    def _ensure_graphconfig(session: object, cfg: dict[str, object]) -> bool:
        """Corre graphconfig.init si no existe ya. Devuelve True si creo,
        False si ya existia.
        """
        # graphconfig esta en el nodo singleton _GraphConfig.
        existing = session.run(  # type: ignore[attr-defined]
            "MATCH (gc:_GraphConfig) RETURN count(gc) AS n"
        ).single()
        if existing and existing["n"] > 0:
            return False
        session.run(  # type: ignore[attr-defined]
            "CALL n10s.graphconfig.init($cfg)", cfg=cfg
        )
        return True

    # ------------------------------------------------------------------
    # Import OWL TBox -> Neo4j
    # ------------------------------------------------------------------

    def importar_owl(self, input_ttl: Path) -> ImportResult:
        """Importa una ontologia OWL/Turtle al Neo4j vía n10s.rdf.import.inline.

        Asume que init_n10s ya fue corrido. n10s deduplica via MERGE sobre
        URIs, asi que re-importar el mismo .ttl no genera duplicados.

        Args:
            input_ttl: Path al archivo .ttl con TBox (o ABox) a importar.

        Returns:
            ImportResult con conteo de tripletas y status.

        Raises:
            FileNotFoundError: Si input_ttl no existe.
            RuntimeError: Si n10s reporta error parseando o cargando.
        """
        input_ttl = Path(input_ttl).resolve()
        if not input_ttl.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {input_ttl}")

        content = input_ttl.read_text(encoding="utf-8")

        with self.driver.session() as session:
            try:
                rec = session.run(
                    "CALL n10s.rdf.import.inline($payload, $format) "
                    "YIELD terminationStatus, triplesLoaded, triplesParsed, "
                    "extraInfo "
                    "RETURN terminationStatus, triplesLoaded, triplesParsed, extraInfo",
                    payload=content, format="Turtle",
                ).single()
            except Exception as exc:
                raise RuntimeError(
                    f"n10s.rdf.import.inline fallo importando {input_ttl.name}. "
                    f"Causa: {type(exc).__name__}: {exc}"
                ) from exc

        if rec is None:
            raise RuntimeError("n10s.rdf.import.inline no devolvio resultado.")

        return ImportResult(
            terminationStatus=str(rec["terminationStatus"]),
            triplesLoaded=int(rec["triplesLoaded"] or 0),
            triplesParsed=int(rec["triplesParsed"] or 0),
            extraInfo=str(rec["extraInfo"] or ""),
        )

    # ------------------------------------------------------------------
    # Export Neo4j -> RDF/Turtle
    # ------------------------------------------------------------------

    def exportar(
        self,
        salida_ttl: Path,
        cypher: str = "MATCH (n) OPTIONAL MATCH (n)-[r]->(m) RETURN n, r, m",
    ) -> ExportResult:
        """Exporta el grafo Neo4j (entero o subgrafo) a un archivo Turtle.

        Usa n10s.rdf.export.cypher que stream-yieldea tripletas. Las acumula
        en un rdflib.Graph y lo serializa.

        Args:
            salida_ttl: Path destino del archivo .ttl.
            cypher: Cypher que selecciona el subgrafo. Default: TODO el grafo.

        Returns:
            ExportResult con path resuelto y conteo de tripletas.

        Raises:
            RuntimeError: Si n10s.rdf.export.cypher falla o no esta instalado.
        """
        salida_ttl = Path(salida_ttl).resolve()
        salida_ttl.parent.mkdir(parents=True, exist_ok=True)

        graph = self._collect_triples(cypher)
        graph.bind(MKT_PREFIX, rdflib.Namespace(MKT_NS))
        graph.serialize(destination=str(salida_ttl), format="turtle")

        return ExportResult(salida_ttl=salida_ttl, n_triples=len(graph))

    def _collect_triples(self, cypher: str) -> rdflib.Graph:
        """Exporta Neo4j a rdflib.Graph via Cypher directo + mappings invertidos.

        NO usa n10s.rdf.export.cypher por dos razones documentadas:
        1. El procedure tiene quirks con URIs que tienen '/' interno bajo
           handleVocabUris=SHORTEN (devuelve 0 tripletas para
           mkt:Producto/<sku>).
        2. Mas robusto: control total sobre traducciones Neo4j -> RDF.

        El parametro `cypher` se ignora en favor de un export completo de
        nodos con .uri y sus relaciones. Se mantiene en la firma para
        compatibilidad. Si necesitamos sub-grafos en el futuro, se filtra
        a nivel SPARQL post-export (no Cypher).

        n10s sigue siendo util en este flujo para IMPORTS (importar_owl)
        y para el management de namespaces/mappings que reutilizamos aqui.
        """
        graph = rdflib.Graph()
        # Mappings invertidos: neo4j_name -> owl_uri.
        name_to_uri = {neo4j_name: uri for uri, neo4j_name in DEFAULT_MAPPINGS}
        # Properties que el TBox declara como xsd:string. Si Neo4j las
        # tiene como int (sku numerico) o algo, las forzamos a str para
        # respetar el range declarado y evitar inconsistency en HermiT.
        force_string_props = {"sku", "proveedorId", "pais", "ruc", "email",
                              "nombre", "telefono", "razonamiento"}

        def _to_literal(value: object) -> "Optional[rdflib.Literal]":
            """Convierte un valor Neo4j a rdflib.Literal con datatype xsd."""
            if value is None:
                return None
            # bool antes que int (en Python bool ES int)
            if isinstance(value, bool):
                return rdflib.Literal(value, datatype=rdflib.XSD.boolean)
            if isinstance(value, int):
                return rdflib.Literal(value, datatype=rdflib.XSD.integer)
            if isinstance(value, float):
                return rdflib.Literal(value, datatype=rdflib.XSD.decimal)
            # neo4j.time.Date / DateTime tienen .iso_format()
            # Siempre forzamos xsd:dateTime: HermiT no soporta xsd:date.
            # Si el valor es solo Date (sin hora), agregamos T00:00:00.
            if hasattr(value, "iso_format"):
                s = value.iso_format()
                if "T" not in s:
                    s = s + "T00:00:00"
                return rdflib.Literal(s, datatype=rdflib.XSD.dateTime)
            if isinstance(value, list):
                # n10s con handleMultival=ARRAY puede dar listas. Aplanamos
                # devolviendo None aqui y manejando arriba: emitimos una triple
                # por valor.
                return None
            return rdflib.Literal(str(value))

        with self.driver.session() as session:
            # Fase 1: nodos con labels + propiedades.
            try:
                nodes_q = (
                    "MATCH (n) "
                    "WHERE n.uri IS NOT NULL "
                    "AND NOT 'n10s_GraphConfig' IN labels(n) "
                    "AND NOT '_GraphConfig' IN labels(n) "
                    "AND NOT '_NsPrefDef' IN labels(n) "
                    "AND NOT '_MapDef' IN labels(n) "
                    "AND NOT '_MapNs' IN labels(n) "
                    "RETURN n.uri AS uri, labels(n) AS labels, properties(n) AS props"
                )
                for row in session.run(nodes_q):
                    subj = rdflib.URIRef(row["uri"])
                    for label in row["labels"]:
                        if label == "Resource":
                            continue
                        class_uri = name_to_uri.get(label, f"{MKT_NS}{label}")
                        graph.add((subj, rdflib.RDF.type, rdflib.URIRef(class_uri)))
                    for prop_name, value in row["props"].items():
                        if prop_name == "uri":
                            continue
                        prop_uri = name_to_uri.get(prop_name, f"{MKT_NS}{prop_name}")
                        # Force string para properties declaradas xsd:string
                        # en TBox. Evita conflicto datatype range vs valor.
                        if prop_name in force_string_props and not isinstance(value, (str, list)):
                            value = str(value)
                        if isinstance(value, list):
                            for item in value:
                                if prop_name in force_string_props and not isinstance(item, str):
                                    item = str(item)
                                lit = _to_literal(item)
                                if lit is not None:
                                    graph.add((subj, rdflib.URIRef(prop_uri), lit))
                        else:
                            lit = _to_literal(value)
                            if lit is not None:
                                graph.add((subj, rdflib.URIRef(prop_uri), lit))
            except Exception as exc:
                raise RuntimeError(
                    f"Export de nodos fallo. Causa: {type(exc).__name__}: {exc}"
                ) from exc

            # Fase 2: relaciones entre nodos con .uri.
            try:
                rels_q = (
                    "MATCH (a)-[r]->(b) "
                    "WHERE a.uri IS NOT NULL AND b.uri IS NOT NULL "
                    "RETURN a.uri AS a_uri, type(r) AS rel_type, b.uri AS b_uri"
                )
                for row in session.run(rels_q):
                    subj = rdflib.URIRef(row["a_uri"])
                    obj = rdflib.URIRef(row["b_uri"])
                    rel_type = row["rel_type"]
                    rel_uri = name_to_uri.get(rel_type, f"{MKT_NS}{rel_type}")
                    graph.add((subj, rdflib.URIRef(rel_uri), obj))
            except Exception as exc:
                raise RuntimeError(
                    f"Export de relaciones fallo. Causa: {type(exc).__name__}: {exc}"
                ) from exc

            # Fase 3: features para razonamiento HermiT (Bloque 4).
            # Materializa :tieneHistorial, :velocidad, :altaRotacion en cada
            # Producto. La velocidad es proxy provisorio:
            # velocidad = sum(SUMINISTRADO_POR.total_cantidad_historica).
            # Cuando integremos VENTAS_DET reales, refinamos la formula.
            try:
                features_q = (
                    "MATCH (p:Producto) WHERE p.uri IS NOT NULL "
                    "OPTIONAL MATCH (p)-[r:SUMINISTRADO_POR]->() "
                    "WITH p, coalesce(sum(r.total_cantidad_historica), 0) AS vel, "
                    "     (p.fecha_ultima_compra IS NOT NULL) AS has_hist "
                    "RETURN p.uri AS uri, vel AS velocidad, has_hist AS has_hist"
                )
                feat_rows = list(session.run(features_q))
            except Exception as exc:
                raise RuntimeError(
                    f"Materializacion de features fallo. "
                    f"Causa: {type(exc).__name__}: {exc}"
                ) from exc

            # Calcular percentil 75 sobre velocidades > 0 (excluir cold-start
            # de la distribucion para que no la sesgue hacia abajo).
            velocities = sorted(
                float(r["velocidad"]) for r in feat_rows if float(r["velocidad"]) > 0
            )
            if velocities:
                idx = int(0.75 * (len(velocities) - 1))
                p75 = velocities[idx]
            else:
                p75 = 0.0

            tieneHistorial_uri = rdflib.URIRef(f"{MKT_NS}tieneHistorial")
            velocidad_uri      = rdflib.URIRef(f"{MKT_NS}velocidad")
            altaRotacion_uri   = rdflib.URIRef(f"{MKT_NS}altaRotacion")

            for r in feat_rows:
                subj = rdflib.URIRef(r["uri"])
                v = float(r["velocidad"])
                has_hist = bool(r["has_hist"])
                graph.add((
                    subj, tieneHistorial_uri,
                    rdflib.Literal(has_hist, datatype=rdflib.XSD.boolean),
                ))
                graph.add((
                    subj, velocidad_uri,
                    rdflib.Literal(v, datatype=rdflib.XSD.decimal),
                ))
                is_alta = (v > 0 and v >= p75)
                graph.add((
                    subj, altaRotacion_uri,
                    rdflib.Literal(is_alta, datatype=rdflib.XSD.boolean),
                ))

        return graph

    @staticmethod
    def _add_row(graph: rdflib.Graph, row: object) -> None:
        """Convierte una row de n10s a una triple rdflib y la agrega."""
        s = rdflib.URIRef(row["subject"])  # type: ignore[index]
        p = rdflib.URIRef(row["predicate"])  # type: ignore[index]
        if row["isLiteral"]:  # type: ignore[index]
            datatype = row["literalType"]  # type: ignore[index]
            lang = row["literalLang"]  # type: ignore[index]
            kwargs: dict[str, object] = {}
            if datatype:
                kwargs["datatype"] = rdflib.URIRef(datatype)
            if lang:
                kwargs["lang"] = lang
            o: rdflib.term.Identifier = rdflib.Literal(
                row["object"], **kwargs  # type: ignore[arg-type,index]
            )
        else:
            o = rdflib.URIRef(row["object"])  # type: ignore[index]
        graph.add((s, p, o))

    # ------------------------------------------------------------------
    # SPARQL query -> pandas DataFrame
    # ------------------------------------------------------------------

    def query_sparql(
        self,
        query: str,
        snapshot_path: Optional[Path] = None,
        cypher_subgraph: str = "MATCH (n) OPTIONAL MATCH (n)-[r]->(m) RETURN n, r, m",
    ) -> pd.DataFrame:
        """Ejecuta SPARQL contra el grafo Neo4j (export en memoria + rdflib).

        Args:
            query: String SPARQL (SELECT / ASK / CONSTRUCT).
            snapshot_path: Si se pasa, se carga el grafo desde ese archivo
                en vez de re-exportar Neo4j (mas rapido si ya hay snapshot).
            cypher_subgraph: Cypher para definir que subgrafo exportar si
                no hay snapshot. Default: TODO.

        Returns:
            pd.DataFrame con columnas = variables del SELECT y filas = bindings.
            Para ASK devuelve un DataFrame con una fila columna 'answer'
            booleana. CONSTRUCT no esta soportado en este wrapper.

        Raises:
            RuntimeError: Si SPARQL falla en rdflib (con contexto del query).
        """
        if snapshot_path and Path(snapshot_path).exists():
            graph = rdflib.Graph()
            graph.parse(source=str(snapshot_path), format="turtle")
        else:
            graph = self._collect_triples(cypher_subgraph)

        graph.bind(MKT_PREFIX, rdflib.Namespace(MKT_NS))

        try:
            qres = graph.query(query)
        except Exception as exc:
            raise RuntimeError(
                f"SPARQL query fallo. "
                f"Query: {query[:200]!r}{'...' if len(query) > 200 else ''}. "
                f"Causa: {type(exc).__name__}: {exc}"
            ) from exc

        return _sparql_result_to_df(qres)


def _sparql_result_to_df(qres: object) -> pd.DataFrame:
    """Convierte un rdflib.query.Result a pandas.DataFrame.

    - SELECT: columnas = variables; filas = bindings (URIs como string,
      Literals como su valor python si es posible).
    - ASK: DataFrame con columna 'answer' (bool) y una fila.
    """
    res_type = getattr(qres, "type", None)
    if res_type == "ASK":
        return pd.DataFrame({"answer": [bool(qres.askAnswer)]})  # type: ignore[attr-defined]

    cols = [str(v) for v in getattr(qres, "vars", [])]
    rows: list[dict[str, object]] = []
    for row in qres:  # type: ignore[union-attr]
        record: dict[str, object] = {}
        for var in cols:
            val = row[var] if var in row.labels else None  # type: ignore[index, attr-defined]
            record[var] = _decode_rdf_term(val)
        rows.append(record)
    return pd.DataFrame(rows, columns=cols)


def _decode_rdf_term(term: object) -> object:
    """Convierte un termino rdflib (URIRef/Literal/BNode/None) a tipo Python."""
    if term is None:
        return None
    if isinstance(term, rdflib.Literal):
        try:
            return term.toPython()
        except Exception:
            return str(term)
    return str(term)


# ----------------------------------------------------------------------------
# Migracion v1 -> n10s-friendly
# ----------------------------------------------------------------------------
#
# Los nodos del v1 (Producto, Proveedor, etc.) fueron creados sin .uri property.
# Con handleVocabUris=SHORTEN, n10s.rdf.export.cypher solo serializa nodos que
# tienen URIs con namespaces registrados. Esta migracion asigna URIs siguiendo
# el patron http://marketplace.com.py/onto/v1#<Label>/<id> a cada nodo.
#
# Es idempotente: solo SETea donde uri IS NULL. Re-correrla no rompe nada y no
# duplica datos. NO modifica las properties existentes del v1 (sku, nombre,
# cantidad_stock, etc.) ni el OntologyClient sigue funcionando igual.

URI_MIGRATIONS: list[dict[str, str]] = [
    # (label, propiedad-id, plantilla URI). Si propiedad-id no existe en algun
    # nodo, ese nodo se saltea (WHERE coalesce IS NOT NULL).
    {"label": "Producto",        "id_prop": "sku", "stringify": "false"},
    {"label": "Proveedor",       "id_prop": "id",  "stringify": "true"},
    {"label": "Categoria",       "id_prop": "id",  "stringify": "true"},
    {"label": "Grupo",           "id_prop": "id",  "stringify": "true"},
    {"label": "SubSeccion",      "id_prop": "id",  "stringify": "true"},
    {"label": "Seccion",         "id_prop": "id",  "stringify": "true"},
    {"label": "EventoComercial", "id_prop": "id",  "stringify": "true"},
]


@dataclass(frozen=True)
class MigrationResult:
    """Resultado por-label de la migracion de URIs v1.

    Attributes:
        label: La etiqueta Neo4j migrada.
        nodes_total: Cantidad total de nodos con ese label.
        nodes_actualizados: Cantidad de nodos que recibieron uri NUEVA.
        nodes_ya_con_uri: Cantidad que ya tenia uri (skip por idempotencia).
    """

    label: str
    nodes_total: int
    nodes_actualizados: int
    nodes_ya_con_uri: int


def _bridge_migrar_uris(br: "_Bridge") -> list[MigrationResult]:
    """Implementacion. Itera URI_MIGRATIONS y aplica SET .uri donde falta."""
    out: list[MigrationResult] = []
    with br.driver.session() as session:
        for spec in URI_MIGRATIONS:
            label = spec["label"]
            id_prop = spec["id_prop"]
            stringify = spec["stringify"] == "true"

            id_expr = f"toString(n.{id_prop})" if stringify else f"n.{id_prop}"

            # Conteos antes
            total_rec = session.run(
                f"MATCH (n:{label}) RETURN count(n) AS n"
            ).single()
            total = int(total_rec["n"]) if total_rec else 0

            ya_con_uri_rec = session.run(
                f"MATCH (n:{label}) WHERE n.uri IS NOT NULL RETURN count(n) AS n"
            ).single()
            ya_con_uri = int(ya_con_uri_rec["n"]) if ya_con_uri_rec else 0

            # SET donde falta uri y donde id_prop existe
            update_query = (
                f"MATCH (n:{label}) "
                f"WHERE n.uri IS NULL AND n.{id_prop} IS NOT NULL "
                f"SET n.uri = '{MKT_NS}{label}/' + {id_expr} "
                f"RETURN count(n) AS n"
            )
            updated_rec = session.run(update_query).single()
            updated = int(updated_rec["n"]) if updated_rec else 0

            out.append(MigrationResult(
                label=label,
                nodes_total=total,
                nodes_actualizados=updated,
                nodes_ya_con_uri=ya_con_uri,
            ))
    return out


def migrar_uris_v1() -> list[MigrationResult]:
    """Asigna .uri a nodos del v1 para que n10s pueda exportarlos.

    Returns:
        Lista de MigrationResult, uno por label, con conteos de actualizados
        vs ya-con-uri. Re-correr la funcion produce 0 actualizados (idempotente).
    """
    with _Bridge() as br:
        return _bridge_migrar_uris(br)


# ----------------------------------------------------------------------------
# API publica (funciones wrapper)
# ----------------------------------------------------------------------------


def init_n10s(
    graph_config: Optional[dict[str, object]] = None,
    mappings: Optional[list[tuple[str, str]]] = None,
) -> InitResult:
    """Wrapper publico de _Bridge.init_n10s. Ver _Bridge.init_n10s para detalles."""
    with _Bridge() as br:
        return br.init_n10s(graph_config=graph_config, mappings=mappings)


def importar_owl_a_neo4j(input_ttl: str | Path) -> ImportResult:
    """Importa ontologia OWL al Neo4j. Ver _Bridge.importar_owl."""
    with _Bridge() as br:
        return br.importar_owl(Path(input_ttl))


def exportar_a_rdf(
    salida_ttl: str | Path,
    cypher: str = "MATCH (n) OPTIONAL MATCH (n)-[r]->(m) RETURN n, r, m",
) -> ExportResult:
    """Exporta Neo4j a Turtle. Ver _Bridge.exportar."""
    with _Bridge() as br:
        return br.exportar(Path(salida_ttl), cypher=cypher)


def query_sparql(
    query: str,
    snapshot_path: Optional[str | Path] = None,
    cypher_subgraph: str = "MATCH (n) OPTIONAL MATCH (n)-[r]->(m) RETURN n, r, m",
) -> pd.DataFrame:
    """Corre SPARQL. Ver _Bridge.query_sparql."""
    with _Bridge() as br:
        return br.query_sparql(
            query,
            snapshot_path=Path(snapshot_path) if snapshot_path else None,
            cypher_subgraph=cypher_subgraph,
        )


# ----------------------------------------------------------------------------
# CLI: python -m ontology_semantic.bridge <subcomando>
# ----------------------------------------------------------------------------


def _cli_init() -> int:
    """python -m ontology_semantic.bridge init"""
    res = init_n10s()
    print(f"[init_n10s] graphconfig_created = {res.graphconfig_created}")
    print(f"[init_n10s] constraint_created  = {res.constraint_created}")
    print(f"[init_n10s] n_mappings_applied  = {res.n_mappings_applied}")
    return 0


def _cli_migrar_uris() -> int:
    """python -m ontology_semantic.bridge migrar-uris"""
    results = migrar_uris_v1()
    print(f"{'Label':<18} {'Total':>8} {'Actualizados':>14} {'Ya tenian uri':>15}")
    print("-" * 60)
    for r in results:
        print(f"{r.label:<18} {r.nodes_total:>8} {r.nodes_actualizados:>14} {r.nodes_ya_con_uri:>15}")
    return 0


def _cli_importar(input_ttl: str) -> int:
    """python -m ontology_semantic.bridge importar <ttl>"""
    res = importar_owl_a_neo4j(input_ttl)
    print(f"[importar_owl] terminationStatus = {res.terminationStatus}")
    print(f"[importar_owl] triplesLoaded     = {res.triplesLoaded}")
    print(f"[importar_owl] triplesParsed     = {res.triplesParsed}")
    if res.extraInfo:
        print(f"[importar_owl] extraInfo        = {res.extraInfo}")
    return 0 if res.terminationStatus == "OK" else 1


def _cli_exportar(salida_ttl: str) -> int:
    """python -m ontology_semantic.bridge exportar <salida.ttl>"""
    res = exportar_a_rdf(salida_ttl)
    print(f"[exportar_a_rdf] archivo   = {res.salida_ttl}")
    print(f"[exportar_a_rdf] n_triples = {res.n_triples}")
    return 0


def _cli_sparql(query: str, snapshot_path: Optional[str] = None) -> int:
    """python -m ontology_semantic.bridge sparql '<query>' [<snapshot.ttl>]"""
    df = query_sparql(query, snapshot_path=snapshot_path)
    print(df.to_string(index=False))
    print(f"\n({len(df)} filas)")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(
            "Uso:\n"
            "  python -m ontology_semantic.bridge init\n"
            "  python -m ontology_semantic.bridge migrar-uris\n"
            "  python -m ontology_semantic.bridge importar <archivo.ttl>\n"
            "  python -m ontology_semantic.bridge exportar <salida.ttl>\n"
            "  python -m ontology_semantic.bridge sparql '<query>' [<snapshot.ttl>]"
        )
        return 2

    cmd, *rest = args
    if cmd == "init":
        return _cli_init()
    if cmd == "migrar-uris":
        return _cli_migrar_uris()
    if cmd == "importar" and len(rest) == 1:
        return _cli_importar(rest[0])
    if cmd == "exportar" and len(rest) == 1:
        return _cli_exportar(rest[0])
    if cmd == "sparql" and len(rest) >= 1:
        snap = rest[1] if len(rest) >= 2 else None
        return _cli_sparql(rest[0], snapshot_path=snap)

    print(f"Subcomando o args invalidos: {cmd!r} {rest!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
