"""Bridge Neo4j <-> RDF via Neosemantics (n10s).

Tres operaciones publicas:

1. exportar_a_rdf(salida_ttl): vuelca el grafo Neo4j actual a Turtle.
2. importar_owl_a_neo4j(input_ttl): importa la TBox al Neo4j via n10s.
3. query_sparql(query): export Neo4j -> rdflib + SPARQL en rdflib.

Las credenciales de Neo4j se leen del .env (NEO4J_URI, NEO4J_USER,
NEO4J_PASSWORD).
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

DEFAULT_MAPPINGS: list[tuple[str, str]] = [
    (f"{MKT_NS}Producto",        "Producto"),
    (f"{MKT_NS}Categoria",       "Categoria"),
    (f"{MKT_NS}Grupo",           "Grupo"),
    (f"{MKT_NS}SubSeccion",      "SubSeccion"),
    (f"{MKT_NS}Seccion",         "Seccion"),
    (f"{MKT_NS}Proveedor",       "Proveedor"),
    (f"{MKT_NS}EventoComercial", "EventoComercial"),
    (f"{MKT_NS}perteneceA",      "PERTENECE_A"),
    (f"{MKT_NS}suministradoPor", "SUMINISTRADO_POR"),
    (f"{MKT_NS}sku",                  "sku"),
    (f"{MKT_NS}cantidadStock",        "cantidad_stock"),
    (f"{MKT_NS}enStock",              "en_stock"),
    (f"{MKT_NS}fechaUltimaCompra",    "fecha_ultima_compra"),
    (f"{MKT_NS}pais",                 "pais"),
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
    graphconfig_created: bool
    constraint_created: bool
    n_mappings_applied: int


@dataclass(frozen=True)
class ImportResult:
    terminationStatus: str
    triplesLoaded: int
    triplesParsed: int
    extraInfo: str = ""


@dataclass(frozen=True)
class ExportResult:
    salida_ttl: Path
    n_triples: int


# ----------------------------------------------------------------------------
# Cliente principal.
# ----------------------------------------------------------------------------


class _Bridge:
    """Cliente de bajo nivel para hablar con Neo4j a traves de n10s."""

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
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self.uri, auth=(self.user, self.password)
            )
            try:
                self._driver.verify_connectivity()
            except Exception as exc:
                raise RuntimeError(
                    f"No se pudo conectar a Neo4j en {self.uri!r}. "
                    f"Causa: {type(exc).__name__}: {exc}."
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

    def init_n10s(
        self,
        graph_config: Optional[dict[str, object]] = None,
        mappings: Optional[list[tuple[str, str]]] = None,
        ns_prefix: str = MKT_PREFIX,
        ns_uri: str = MKT_NS,
    ) -> InitResult:
        """Inicializa n10s en la base de forma idempotente."""
        cfg = graph_config or DEFAULT_GRAPH_CONFIG
        maps = mappings or DEFAULT_MAPPINGS

        with self.driver.session() as session:
            constraint_created = self._ensure_resource_uri_constraint(session)
            graphconfig_created = self._ensure_graphconfig(session, cfg)

            session.run(
                "CALL n10s.nsprefixes.add($prefix, $uri)",
                prefix=ns_prefix, uri=ns_uri,
            )

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
        existing = session.run(
            "SHOW CONSTRAINTS YIELD name WHERE name = 'n10s_unique_uri' "
            "RETURN count(name) AS n"
        ).single()
        if existing and existing["n"] > 0:
            return False
        session.run(
            "CREATE CONSTRAINT n10s_unique_uri IF NOT EXISTS "
            "FOR (r:Resource) REQUIRE r.uri IS UNIQUE"
        )
        return True

    @staticmethod
    def _ensure_graphconfig(session: object, cfg: dict[str, object]) -> bool:
        existing = session.run(
            "MATCH (gc:_GraphConfig) RETURN count(gc) AS n"
        ).single()
        if existing and existing["n"] > 0:
            return False
        session.run("CALL n10s.graphconfig.init($cfg)", cfg=cfg)
        return True

    def importar_owl(self, input_ttl: Path) -> ImportResult:
        """Importa una ontologia OWL/Turtle al Neo4j via n10s.rdf.import.inline."""
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


# ----------------------------------------------------------------------------
# API publica (funciones wrapper)
# ----------------------------------------------------------------------------


def init_n10s(
    graph_config: Optional[dict[str, object]] = None,
    mappings: Optional[list[tuple[str, str]]] = None,
) -> InitResult:
    """Wrapper publico de _Bridge.init_n10s."""
    with _Bridge() as br:
        return br.init_n10s(graph_config=graph_config, mappings=mappings)


def importar_owl_a_neo4j(input_ttl) -> ImportResult:
    """Importa ontologia OWL al Neo4j. Acepta str o Path."""
    with _Bridge() as br:
        return br.importar_owl(Path(input_ttl))


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


def _cli_init() -> int:
    res = init_n10s()
    print(f"[init_n10s] graphconfig_created = {res.graphconfig_created}")
    print(f"[init_n10s] constraint_created  = {res.constraint_created}")
    print(f"[init_n10s] n_mappings_applied  = {res.n_mappings_applied}")
    return 0


def _cli_importar(input_ttl: str) -> int:
    res = importar_owl_a_neo4j(input_ttl)
    print(f"[importar_owl] terminationStatus = {res.terminationStatus}")
    print(f"[importar_owl] triplesLoaded     = {res.triplesLoaded}")
    print(f"[importar_owl] triplesParsed     = {res.triplesParsed}")
    if res.extraInfo:
        print(f"[importar_owl] extraInfo        = {res.extraInfo}")
    return 0 if res.terminationStatus == "OK" else 1


def main(argv: Optional[list[str]] = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(
            "Uso:\n"
            "  python -m ontology_semantic.bridge init\n"
            "  python -m ontology_semantic.bridge importar <archivo.ttl>"
        )
        return 2

    cmd, *rest = args
    if cmd == "init":
        return _cli_init()
    if cmd == "importar" and len(rest) == 1:
        return _cli_importar(rest[0])

    print(f"Subcomando o args invalidos: {cmd!r} {rest!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
