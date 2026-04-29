"""Valida que la ontologia carga sin errores y muestra un resumen estructural.

Pipeline:
    1. (Re)genera marketplace.owl desde marketplace.ttl via build.py.
    2. Carga el .owl con owlready2.
    3. Imprime listado de clases, object properties, data properties y
       cuenta de axiomas.

Es el smoke test del Bloque 1.

Uso:
    python -m ontology_semantic.load_check
    # o:
    python ontology_semantic/load_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

from owlready2 import (
    DataProperty,
    ObjectProperty,
    Thing,
    World,
)

# Importar build de forma robusta independientemente de como se ejecute el script.
try:
    from ontology_semantic.build import OWL_TARGET, build  # type: ignore
except ModuleNotFoundError:
    # Caso: ejecucion directa "python ontology_semantic/load_check.py"
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ontology_semantic.build import OWL_TARGET, build  # type: ignore  # noqa: E402


ONTO_IRI: str = "http://marketplace.com.py/onto/v1"


def load_ontology() -> tuple[object, World]:
    """Carga la ontologia desde el .owl generado por build.py.

    Crea un World aislado para evitar contaminar el default_world (mejor
    higiene en tests futuros).

    Returns:
        Tupla (onto, world) donde onto es el ontology object de owlready2.

    Raises:
        RuntimeError: Si la carga falla, con contexto del archivo y la causa.
    """
    # Asegurar artefacto fresco.
    owl_path = build()

    world = World()
    iri = f"file://{owl_path.as_posix()}"
    try:
        onto = world.get_ontology(iri).load()
    except Exception as exc:
        raise RuntimeError(
            f"owlready2 no pudo cargar {iri}. "
            f"Causa: {type(exc).__name__}: {exc}"
        ) from exc
    return onto, world


def _names(items: Iterable[object]) -> list[str]:
    """Extrae .name de una coleccion de entidades owlready2 (filtra None)."""
    out: list[str] = []
    for it in items:
        name = getattr(it, "name", None)
        if name:
            out.append(name)
    return sorted(out)


def summarize(onto: object) -> dict[str, list[str] | int]:
    """Construye un resumen estructural de la ontologia cargada.

    Returns:
        Dict con listas de nombres y conteos de axiomas.
    """
    classes = _names(onto.classes())  # type: ignore[attr-defined]
    obj_props = _names(onto.object_properties())  # type: ignore[attr-defined]
    data_props = _names(onto.data_properties())  # type: ignore[attr-defined]

    # Conteo de tripletas via el grafo subyacente del world.
    # owlready2 expone el grafo en world.as_rdflib_graph() pero hay que
    # contar lo del IRI especifico. Mas simple: rdflib directo.
    import rdflib
    g = rdflib.Graph()
    g.parse(source=str(OWL_TARGET), format="nt")
    total_triples = len(g)

    return {
        "classes": classes,
        "object_properties": obj_props,
        "data_properties": data_props,
        "n_classes": len(classes),
        "n_object_properties": len(obj_props),
        "n_data_properties": len(data_props),
        "n_triples": total_triples,
    }


def print_report(summary: dict[str, list[str] | int]) -> None:
    """Imprime el resumen en formato legible para humano."""
    print("=" * 70)
    print(f"Ontologia cargada: {ONTO_IRI}")
    print(f"Archivo fuente   : {OWL_TARGET}")
    print("=" * 70)

    print(f"\n[Clases] ({summary['n_classes']})")
    for c in summary["classes"]:  # type: ignore[union-attr]
        print(f"  - {c}")

    print(f"\n[Object Properties] ({summary['n_object_properties']})")
    for p in summary["object_properties"]:  # type: ignore[union-attr]
        print(f"  - {p}")

    print(f"\n[Data Properties] ({summary['n_data_properties']})")
    for p in summary["data_properties"]:  # type: ignore[union-attr]
        print(f"  - {p}")

    print(f"\n[Total tripletas RDF]: {summary['n_triples']}")
    print("=" * 70)
    print("OK")


def main() -> int:
    """Entry point. Devuelve 0 si la ontologia carga limpia."""
    onto, _world = load_ontology()
    summary = summarize(onto)
    print_report(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
