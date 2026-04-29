"""Convierte la ontologia fuente Turtle a RDF formato cargable por owlready2.

Owlready2 0.50 NO soporta carga directa de archivos .ttl (solo RDF/XML,
OWL/XML, NTriples). Por eso mantenemos `marketplace.ttl` como single source
of truth humano y derivamos `marketplace.owl` automaticamente con rdflib.

IMPORTANTE - eleccion de formato (Bloque 4):

Inicialmente usabamos format="pretty-xml". Descubrimos que ese serializer
de rdflib drop-ea silenciosamente axiomas que involucran RDF Lists
(intersectionOf, unionOf, equivalentClass complejos). Tambien probamos
format="xml" basic - el problema persiste.

NTriples (format="nt") es el formato mas robusto: cada tripleta en su propia
linea, sin construcciones de listas que se pierdan. Es lo que usamos.
owlready2 carga NTriples nativamente.
"""

from __future__ import annotations

import sys
from pathlib import Path

import rdflib

HERE: Path = Path(__file__).resolve().parent
TTL_SOURCE: Path = HERE / "marketplace.ttl"
OWL_TARGET: Path = HERE / "marketplace.owl"


def build(ttl_path: Path = TTL_SOURCE, owl_path: Path = OWL_TARGET) -> Path:
    """Parsea el .ttl con rdflib y serializa a NTriples (extension .owl).

    Args:
        ttl_path: Ruta al archivo Turtle fuente.
        owl_path: Ruta destino del archivo (NTriples, extension .owl por
            convencion del proyecto).

    Returns:
        Ruta absoluta del archivo generado.

    Raises:
        FileNotFoundError: Si el .ttl fuente no existe.
        RuntimeError: Si parse o serialize fallan, con contexto.
    """
    if not ttl_path.exists():
        raise FileNotFoundError(
            f"Archivo Turtle fuente no encontrado: {ttl_path}. "
            f"Verifica que ontology_semantic/marketplace.ttl exista."
        )

    graph = rdflib.Graph()
    try:
        graph.parse(source=str(ttl_path), format="turtle")
    except Exception as exc:
        raise RuntimeError(
            f"Error parseando {ttl_path} como Turtle. "
            f"Causa: {type(exc).__name__}: {exc}"
        ) from exc

    try:
        # NTriples preserva todas las triples sin perder RDF Lists.
        graph.serialize(destination=str(owl_path), format="nt")
    except Exception as exc:
        raise RuntimeError(
            f"Error serializando a NTriples en {owl_path}. "
            f"Causa: {type(exc).__name__}: {exc}"
        ) from exc

    return owl_path.resolve()


def _count_triples(owl_path: Path) -> int:
    """Cuenta tripletas en el archivo recien generado."""
    g = rdflib.Graph()
    g.parse(source=str(owl_path), format="nt")
    return len(g)


def main() -> int:
    """Entry point CLI. Imprime resumen y devuelve exit code 0 si todo OK."""
    print(f"[build] TTL fuente : {TTL_SOURCE}")
    print(f"[build] OWL destino: {OWL_TARGET}")
    out = build()
    triple_count = _count_triples(out)
    print(f"[build] OK. Generado {out} con {triple_count} tripletas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
