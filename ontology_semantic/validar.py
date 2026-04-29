"""Validacion SHACL de grafos RDF contra shapes del marketplace.

Pipeline:
    1. Asegurar que la ontologia OWL este construida (build.py).
    2. Cargar el grafo de datos a validar.
    3. Cargar las shapes (shapes.ttl).
    4. Cargar la ontologia como ont_graph para inferencia rdfs (subclases de
       :Norm cuentan como :Norm para targetClass).
    5. Llamar pyshacl.validate() y devolver un ValidationReport con detalle.

Uso:
    # Validar un archivo RDF/Turtle:
    python -m ontology_semantic.validar tests/data/datos_validos.ttl
    # Exit code: 0 si conforma, 1 si hay violaciones.

API publica:
    validar_grafo(rdf_path, shapes_path=None) -> ValidationReport

Anti-patterns evitados:
    - Sin paths absolutos hardcodeados (Path(__file__).parent).
    - Sin imprimir secretos o info de configuracion.
    - Excepciones re-elevadas con contexto.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import rdflib
from pyshacl import validate as _pyshacl_validate

# Importar build/load helpers de forma robusta.
try:
    from ontology_semantic.build import OWL_TARGET, build  # type: ignore
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ontology_semantic.build import OWL_TARGET, build  # type: ignore  # noqa: E402


HERE: Path = Path(__file__).resolve().parent
DEFAULT_SHAPES: Path = HERE / "shapes.ttl"


@dataclass(frozen=True)
class ValidationReport:
    """Resultado de validar un grafo RDF contra shapes SHACL.

    Attributes:
        conforms: True si el grafo conforma con todas las shapes.
        n_violations: Numero de violaciones encontradas (por mensaje).
        report_text: Reporte textual humano-legible producido por pyshacl.
        rdf_path: Ruta al grafo de datos validado.
        shapes_path: Ruta a las shapes usadas.
    """

    conforms: bool
    n_violations: int
    report_text: str
    rdf_path: Path
    shapes_path: Path

    def pretty(self) -> str:
        """Devuelve un string formateado para imprimir en terminal."""
        header = "=" * 70
        status = "CONFORMA" if self.conforms else "NO CONFORMA"
        marker = "OK" if self.conforms else "FAIL"
        body = (
            f"{header}\n"
            f"[{marker}] {status} -> {self.rdf_path.name}\n"
            f"  Shapes : {self.shapes_path.name}\n"
            f"  Violaciones: {self.n_violations}\n"
            f"{header}\n"
            f"{self.report_text}"
        )
        return body


def validar_grafo(
    rdf_path: str | Path,
    shapes_path: Optional[str | Path] = None,
) -> ValidationReport:
    """Valida un grafo RDF contra shapes SHACL.

    Args:
        rdf_path: Ruta al archivo de datos (Turtle).
        shapes_path: Ruta a shapes.ttl. Si es None usa el default
            ontology_semantic/shapes.ttl.

    Returns:
        Un ValidationReport con conforms, conteo, y texto humano.

    Raises:
        FileNotFoundError: Si rdf_path o shapes_path no existen.
        RuntimeError: Si pyshacl falla (con contexto del archivo y la causa).
    """
    rdf_path = Path(rdf_path).resolve()
    shapes_path = Path(shapes_path or DEFAULT_SHAPES).resolve()

    if not rdf_path.exists():
        raise FileNotFoundError(f"Grafo de datos no encontrado: {rdf_path}")
    if not shapes_path.exists():
        raise FileNotFoundError(f"Archivo de shapes no encontrado: {shapes_path}")

    # Asegurar que la ontologia OWL este construida (rebuild idempotente).
    owl_path = build()

    # Cargar grafos.
    data_graph = rdflib.Graph()
    data_graph.parse(source=str(rdf_path), format="turtle")

    shapes_graph = rdflib.Graph()
    shapes_graph.parse(source=str(shapes_path), format="turtle")

    ont_graph = rdflib.Graph()
    ont_graph.parse(source=str(owl_path), format="xml")

    try:
        conforms, _report_graph, report_text = _pyshacl_validate(
            data_graph,
            shacl_graph=shapes_graph,
            ont_graph=ont_graph,
            inference="rdfs",        # propaga subclases (Obligation -> Norm).
            advanced=True,           # habilita SHACL-AF (sh:lessThanOrEquals).
            meta_shacl=True,         # valida que las shapes mismas esten bien.
            abort_on_first=False,
            allow_warnings=False,
            debug=False,
        )
    except Exception as exc:
        raise RuntimeError(
            f"pyshacl.validate fallo. "
            f"Datos: {rdf_path.name}, Shapes: {shapes_path.name}. "
            f"Causa: {type(exc).__name__}: {exc}"
        ) from exc

    n_violations = _count_violations(_report_graph)

    return ValidationReport(
        conforms=bool(conforms),
        n_violations=n_violations,
        report_text=str(report_text),
        rdf_path=rdf_path,
        shapes_path=shapes_path,
    )


def _count_violations(report_graph: rdflib.Graph) -> int:
    """Cuenta nodos sh:ValidationResult en el reporte."""
    SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")
    return sum(1 for _ in report_graph.subjects(rdflib.RDF.type, SH.ValidationResult))


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint.

    Args:
        argv: Lista de args (excluye nombre del script). Si None usa sys.argv[1:].

    Returns:
        0 si conforma, 1 si hay violaciones, 2 si error de uso.
    """
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 1:
        print("Uso: python -m ontology_semantic.validar <ruta_rdf> [<ruta_shapes>]")
        return 2

    rdf_path = args[0]
    shapes_path = args[1] if len(args) >= 2 else None

    report = validar_grafo(rdf_path, shapes_path)
    print(report.pretty())
    return 0 if report.conforms else 1


if __name__ == "__main__":
    sys.exit(main())
