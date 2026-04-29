"""Razonador HermiT sobre TBox + ABox del marketplace.

Pipeline:

1. cargar_onto_con_abox(snapshot_ttl): carga marketplace.owl (TBox) en un
   World owlready2 + parsea snapshot.ttl (ABox) en el mismo grafo.
2. run_hermit(world): corre sync_reasoner_hermit, captura
   OwlReadyInconsistentOntologyError, mide tiempo.
3. listar_inferencias(...): identifica que rdf:types nuevos quedaron
   despues del razonamiento (clasificaciones derivadas).
4. persist_to_neo4j(...): escribe los hechos inferidos de vuelta a Neo4j
   con propiedad :isInferred true para distinguirlos de los originales.

Diseño:
- ignore_unsupported_datatypes=True (HermiT no soporta xsd:date, que tenemos
  en :validFrom/:validTo).
- infer_property_values=False por default (ahorra tiempo). Activar solo si
  necesitamos derivar transitividades, etc.
- Tiempo de razonamiento se logea explicitamente.

Uso CLI:
    python -m ontology_semantic.reasoner run data\snapshot.ttl
    python -m ontology_semantic.reasoner run-and-persist data\snapshot.ttl
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import owlready2
import rdflib

# Imports robustos.
try:
    from ontology_semantic.build import OWL_TARGET, build  # type: ignore
    from ontology_semantic.bridge import MKT_NS, _Bridge  # type: ignore
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ontology_semantic.build import OWL_TARGET, build  # type: ignore  # noqa: E402
    from ontology_semantic.bridge import MKT_NS, _Bridge  # type: ignore  # noqa: E402


HERE: Path = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)


# =============================================================================
# Estructuras de salida
# =============================================================================


@dataclass
class ReasoningResult:
    """Resultado de un run de HermiT.

    Attributes:
        elapsed_s: Tiempo total de razonamiento en segundos.
        consistent: True si la ontologia es consistente.
        inconsistency_message: Mensaje de OwlReadyInconsistentOntologyError
            si consistent=False, else "".
        n_classes: Cantidad de clases en el world post-razonamiento.
        n_individuals: Cantidad de individuos.
        infer_property_values: Si se pidieron property values inferidos.
    """

    elapsed_s: float
    consistent: bool
    inconsistency_message: str = ""
    n_classes: int = 0
    n_individuals: int = 0
    infer_property_values: bool = False


@dataclass
class InferenceReport:
    """Conteo de inferencias derivadas (nuevos rdf:types) por clase.

    Attributes:
        counts: Dict label_clase -> cantidad de individuos clasificados.
        sample_uris: Para cada clase, muestra primeros N URIs (debug).
    """

    counts: dict[str, int] = field(default_factory=dict)
    sample_uris: dict[str, list[str]] = field(default_factory=dict)


# =============================================================================
# Carga de ontologia + ABox
# =============================================================================


def cargar_onto_con_abox(
    snapshot_ttl: Optional[Path] = None,
    abox_data: Optional[str] = None,
) -> tuple[object, owlready2.World]:
    """Carga marketplace.owl (TBox) + ABox en un World owlready2.

    El ABox puede venir de:
    - snapshot_ttl: archivo Turtle exportado por bridge.exportar_a_rdf.
    - abox_data: string Turtle (utilidad para tests).
    Si ambos None, se carga solo la TBox (util para sanity checks).

    Args:
        snapshot_ttl: Path al snapshot.ttl con datos exportados de Neo4j.
        abox_data: String Turtle con ABox sintetica (para tests).

    Returns:
        Tupla (onto, world). El World contiene tanto TBox como ABox cargados.

    Raises:
        FileNotFoundError: Si snapshot_ttl no existe.
        RuntimeError: Si la carga falla con contexto del archivo.
    """
    # 1. Asegurar que marketplace.owl este construido.
    owl_path = build()

    # 2. Cargar TBox en world owlready2.
    world = owlready2.World()
    iri = f"file://{owl_path.as_posix()}"
    onto = world.get_ontology(iri).load()

    # 3. Inyectar ABox via rdflib subyacente del world.
    # Owlready2 requiere `with onto:` block para agregar triples al world.
    if snapshot_ttl is not None:
        snapshot_ttl = Path(snapshot_ttl).resolve()
        if not snapshot_ttl.exists():
            raise FileNotFoundError(f"snapshot.ttl no encontrado: {snapshot_ttl}")
        rdflib_graph = world.as_rdflib_graph()
        try:
            with onto:
                rdflib_graph.parse(source=str(snapshot_ttl), format="turtle")
        except Exception as exc:
            raise RuntimeError(
                f"Parse de ABox fallo: {snapshot_ttl}. "
                f"Causa: {type(exc).__name__}: {exc}"
            ) from exc

    if abox_data is not None:
        rdflib_graph = world.as_rdflib_graph()
        with onto:
            rdflib_graph.parse(data=abox_data, format="turtle")

    return onto, world


# =============================================================================
# Run del razonador
# =============================================================================


def run_hermit(
    world: owlready2.World,
    infer_property_values: bool = False,
    debug: int = 0,
) -> ReasoningResult:
    """Ejecuta sync_reasoner_hermit con manejo de inconsistencia y timing.

    Args:
        world: World owlready2 con TBox + ABox cargados.
        infer_property_values: Si True, HermiT deriva tambien valores de
            propiedades (transitividad, etc.). Mas lento. Default False.
        debug: Verbosity de owlready2 para HermiT. Default 0 (silencioso).

    Returns:
        ReasoningResult con tiempo, consistencia, mensaje opcional.
    """
    n_indiv = sum(1 for _ in world.individuals())
    n_classes = sum(1 for _ in world.classes())

    t0 = time.time()
    try:
        with world:
            owlready2.sync_reasoner_hermit(
                world,
                infer_property_values=infer_property_values,
                debug=debug,
                ignore_unsupported_datatypes=True,
            )
        elapsed = time.time() - t0
        return ReasoningResult(
            elapsed_s=elapsed,
            consistent=True,
            n_classes=n_classes,
            n_individuals=n_indiv,
            infer_property_values=infer_property_values,
        )
    except owlready2.OwlReadyInconsistentOntologyError as exc:
        elapsed = time.time() - t0
        return ReasoningResult(
            elapsed_s=elapsed,
            consistent=False,
            inconsistency_message=str(exc),
            n_classes=n_classes,
            n_individuals=n_indiv,
            infer_property_values=infer_property_values,
        )


# =============================================================================
# Listado de inferencias
# =============================================================================


# Clases derivables por HermiT (las que tienen owl:equivalentClass en el TBox).
DERIVED_CLASSES: list[str] = [
    "ProductoCritico",
    "ProductoPerecedero",
    "ProductoAltaRotacion",
    "ProductoColdStart",
    "ProveedorExterior",
    "ProveedorLocal",
]


def listar_inferencias(
    world: owlready2.World,
    sample_size: int = 5,
) -> InferenceReport:
    """Cuenta cuantos individuos quedaron clasificados en cada clase derivada.

    Despues de run_hermit, el world tiene los rdf:type inferidos. Esta funcion
    los cuenta por clase y devuelve muestras de URIs para debug.

    Args:
        world: World owlready2 post-razonamiento.
        sample_size: Cantidad de URIs sample por clase. Default 5.

    Returns:
        InferenceReport con counts por clase y sample_uris.
    """
    # Obtener la ontologia marketplace cargada en el world. Usamos owlready2
    # API (cls.instances()) que SI refleja las inferencias post-reasoning.
    # NO usamos as_rdflib_graph() porque el grafo rdflib no se sincroniza con
    # el internal store de owlready2 despues del reasoning.
    ontos = [
        o for o in world.ontologies.values()
        if str(o.base_iri).startswith("http://marketplace.com.py/onto/v1")
    ]
    onto_target = ontos[0] if ontos else list(world.ontologies.values())[0]

    report = InferenceReport()
    for cls_name in DERIVED_CLASSES:
        cls = getattr(onto_target, cls_name, None)
        if cls is None:
            report.counts[cls_name] = 0
            report.sample_uris[cls_name] = []
            continue
        # cls.instances() devuelve individuos clasificados (inferidos incluidos).
        instances = list(cls.instances())
        report.counts[cls_name] = len(instances)
        report.sample_uris[cls_name] = [str(i.iri) for i in instances[:sample_size]]
    return report


# =============================================================================
# Persistencia de inferencias a Neo4j
# =============================================================================


def persist_to_neo4j(
    world: owlready2.World,
    only_classes: Optional[list[str]] = None,
) -> dict[str, int]:
    """Escribe los rdf:type inferidos de vuelta a Neo4j marcandolos como inferidos.

    Para cada individuo clasificado en una clase derivada, agrega:
    - Label adicional <Clase> en el nodo correspondiente.
    - Property is_inferred_<Clase> = true.

    Args:
        world: World post-razonamiento.
        only_classes: Lista de clases a persistir. Default: DERIVED_CLASSES.

    Returns:
        Dict label -> cantidad de nodos actualizados.

    Raises:
        RuntimeError: Si la conexion a Neo4j falla.
    """
    classes = only_classes or DERIVED_CLASSES
    g = world.as_rdflib_graph()
    out: dict[str, int] = {}

    with _Bridge() as br:
        with br.driver.session() as session:
            for cls_name in classes:
                cls_uri = rdflib.URIRef(f"{MKT_NS}{cls_name}")
                uris = [str(u) for u in g.subjects(rdflib.RDF.type, cls_uri)]
                if not uris:
                    out[cls_name] = 0
                    continue

                # Aplicar label + flag is_inferred a todos los nodos.
                # Usar UNWIND para batchear la actualizacion.
                update_q = (
                    "UNWIND $uris AS u "
                    "MATCH (n {uri: u}) "
                    f"SET n:{cls_name}, n.is_inferred_{cls_name} = true "
                    "RETURN count(n) AS n"
                )
                rec = session.run(update_q, uris=uris).single()
                out[cls_name] = int(rec["n"]) if rec else 0
    return out


# =============================================================================
# CLI
# =============================================================================


def _cli_run(snapshot_ttl: str, infer_property_values: bool = False) -> int:
    """python -m ontology_semantic.reasoner run <snapshot.ttl> [--prop-values]"""
    print(f"[reasoner] cargando ontologia + ABox desde {snapshot_ttl} ...")
    onto, world = cargar_onto_con_abox(Path(snapshot_ttl))
    print(f"[reasoner] world cargado. Clases={len(list(world.classes()))}, "
          f"individuos={sum(1 for _ in world.individuals())}")

    print(f"[reasoner] corriendo HermiT (infer_property_values="
          f"{infer_property_values}) ...")
    result = run_hermit(world, infer_property_values=infer_property_values)

    print()
    print("=" * 60)
    print(f"[reasoner] HermiT termino en {result.elapsed_s:.2f}s")
    print(f"[reasoner] consistent          = {result.consistent}")
    if not result.consistent:
        print(f"[reasoner] inconsistency_msg   = {result.inconsistency_message}")
        return 1
    print(f"[reasoner] n_classes (post)    = {sum(1 for _ in world.classes())}")
    print(f"[reasoner] n_individuals       = {result.n_individuals}")
    print()

    report = listar_inferencias(world)
    print("[reasoner] Inferencias por clase derivada:")
    print(f"{'Clase':<25} {'Cantidad':>10}")
    print("-" * 40)
    for cls_name, cnt in report.counts.items():
        print(f"{cls_name:<25} {cnt:>10}")
    return 0


def _cli_run_and_persist(snapshot_ttl: str) -> int:
    """python -m ontology_semantic.reasoner run-and-persist <snapshot.ttl>"""
    print(f"[reasoner] cargando ontologia + ABox desde {snapshot_ttl} ...")
    onto, world = cargar_onto_con_abox(Path(snapshot_ttl))

    print("[reasoner] corriendo HermiT ...")
    result = run_hermit(world)
    print(f"[reasoner] HermiT termino en {result.elapsed_s:.2f}s "
          f"(consistent={result.consistent})")
    if not result.consistent:
        print(f"[reasoner] inconsistency: {result.inconsistency_message}")
        return 1

    print("[reasoner] persistiendo inferencias a Neo4j ...")
    persisted = persist_to_neo4j(world)
    print(f"{'Clase':<25} {'Persisted':>10}")
    print("-" * 40)
    for cls_name, cnt in persisted.items():
        print(f"{cls_name:<25} {cnt:>10}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(
            "Uso:\n"
            "  python -m ontology_semantic.reasoner run <snapshot.ttl>\n"
            "  python -m ontology_semantic.reasoner run-and-persist <snapshot.ttl>"
        )
        return 2

    cmd, *rest = args
    if cmd == "run" and len(rest) == 1:
        return _cli_run(rest[0])
    if cmd == "run-and-persist" and len(rest) == 1:
        return _cli_run_and_persist(rest[0])
    print(f"Subcomando o args invalidos: {cmd!r} {rest!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
