"""Inyector de TrendSignals validados al knowledge graph.

Adaptador estable entre el pipeline de tendencias (Mateo) y el bridge
RDF/Neo4j que entrega Abi. La firma publica ``inyectar_trend_validado``
no cambia segun la implementacion: usa el bridge OWL real si esta
instalado (``ontology_semantic.bridge``), sino cae al ``OntologiaClient``
mock que persiste a ``data/grafo_provisional.json``.

Convenciones criticas:
- Idempotencia: dos invocaciones con el mismo trend_id deben dejar el
  grafo en el mismo estado. Tanto el bridge OWL (MERGE en Cypher via
  n10s) como el mock (replace por nodo_id) lo respetan.
- Validacion SHACL OBLIGATORIA antes de inyectar. Si falla, el trend NO
  entra al grafo y se crea una alerta de revision manual.

Ejemplo:
    >>> from schemas.tendencias import TrendSignal
    >>> ok = inyectar_trend_validado(ts, shapes_path="ontology_semantic/shapes.ttl")

Author: Proyecto NASA - Tarea 2 (Mateo)
"""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from clients.ontologia_client import OntologiaClient
from schemas.tendencias import NodoProvisional, TrendSignal
from services.trends.shacl_validator import trend_a_rdf, validar_trend_con_shacl


_ALERTAS_PATH = Path(__file__).resolve().parents[2] / "data" / "alertas_trend_intake.jsonl"


def _import_bridge_si_existe() -> Callable[[str], Any] | None:
    """Importa ontology_semantic.bridge.importar_owl_a_neo4j si esta disponible.

    Returns:
        La funcion del bridge real de Abi, o None si el modulo todavia no
        esta instalado en el repo (caso normal antes de la entrega de Abi).
    """
    try:
        bridge = importlib.import_module("ontology_semantic.bridge")
    except ModuleNotFoundError:
        return None
    funcion = getattr(bridge, "importar_owl_a_neo4j", None)
    if not callable(funcion):
        logger.warning(
            "ontology_semantic.bridge existe pero no expone importar_owl_a_neo4j"
        )
        return None
    return funcion


def _persistir_via_mock(ts: TrendSignal) -> bool:
    """Fallback: usa el OntologiaClient mock cuando no hay bridge real.

    Convierte el TrendSignal a NodoProvisional y lo persiste en
    data/grafo_provisional.json. Idempotente por nodo_id = trend_id.

    Args:
        ts: TrendSignal a inyectar.

    Returns:
        True si se persistio correctamente.
    """
    cliente = OntologiaClient()
    nodo = NodoProvisional(
        nodo_id=ts.trend_id,
        tipo="tendencia",
        datos=ts.model_dump(mode="json"),
        origen="tendencia",
        confianza=ts.confianza_extraccion,
        fuentes=[ts.fuente],
        fecha_creacion=ts.fecha_deteccion,
        requiere_revision=ts.confianza_extraccion < 0.5,
    )
    return cliente.inyectar_nodo_provisional(nodo)


def inyectar_trend_validado(
    ts: TrendSignal,
    shapes_path: str | Path | None = None,
) -> bool:
    """Valida con SHACL e inyecta el TrendSignal al knowledge graph.

    Flujo:
    1. Valida con SHACL (shapes_path o inline default).
    2. Si falla: alerta de revision manual, retorna False.
    3. Si pasa: marca validado_shacl=True y persiste:
       a. Bridge OWL real de Abi si esta disponible e implementado.
       b. Si el bridge es stub (NotImplementedError): cae al mock.
       c. Si no hay bridge: OntologiaClient mock directo.

    Args:
        ts: TrendSignal canonico con productos_existentes_similares como list[ProductoSimilar].
        shapes_path: Ruta al shapes.ttl externo de Abi. None = inline default.

    Returns:
        True si inyectado. False si rechazado por SHACL o fallo de persistencia.
    """
    conforms, violations = validar_trend_con_shacl(ts, shapes_path)
    if not conforms:
        logger.error(
            f"Trend {ts.trend_id} rechazado por SHACL ({len(violations)} violaciones)"
        )
        crear_alerta_revision_manual(ts, violations)
        return False

    ts_validado = ts.model_copy(update={"validado_shacl": True, "provisional": True})
    bridge_fn = _import_bridge_si_existe()

    try:
        if bridge_fn is not None:
            grafo = trend_a_rdf(ts_validado)
            turtle_str = grafo.serialize(format="turtle")
            # IMPORTANTE: el bridge real de Abi toma una RUTA A ARCHIVO (.ttl),
            # no un string Turtle. Escribimos a un temp file y pasamos el Path.
            import tempfile, os
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".ttl", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(turtle_str)
                tmp_path = tmp.name
            try:
                bridge_fn(tmp_path)  # puede lanzar NotImplementedError si es stub
                logger.info(f"Trend {ts_validado.trend_id} inyectado via bridge OWL")
                return True
            finally:
                os.unlink(tmp_path)

        ok = _persistir_via_mock(ts_validado)
        if ok:
            logger.info(
                f"Trend {ts_validado.trend_id} inyectado via OntologiaClient mock"
            )
        return ok

    except NotImplementedError:
        # El bridge existe como stub (Abi aun no entrego Bloque 4).
        # Degradar al mock hasta que la implementacion real este disponible.
        logger.debug(
            f"Bridge OWL aun no implementado; usando mock para {ts_validado.trend_id}"
        )
        try:
            ok = _persistir_via_mock(ts_validado)
            if ok:
                logger.info(
                    f"Trend {ts_validado.trend_id} inyectado via OntologiaClient mock (fallback)"
                )
            return ok
        except Exception as exc2:
            logger.error(f"Fallback mock fallo para {ts_validado.trend_id}: {exc2}")
            crear_alerta_revision_manual(ts_validado, [f"Persistencia mock fallo: {exc2}"])
            return False

    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error al persistir trend {ts_validado.trend_id}: {exc}")
        crear_alerta_revision_manual(ts_validado, [f"Persistencia fallo: {exc}"])
        return False


def crear_alerta_revision_manual(
    ts: TrendSignal,
    violations: list[str],
) -> None:
    """Registra una alerta de revision manual para un trend rechazado.

    Append-only a data/alertas_trend_intake.jsonl. Cada linea es un
    JSON autocontenido para lectura concurrente segura.

    Args:
        ts: TrendSignal rechazado.
        violations: Mensajes de violacion devueltos por SHACL.
    """
    _ALERTAS_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "trend_id": ts.trend_id,
        "descripcion": ts.descripcion,
        "fuente": ts.fuente,
        "violations": violations,
        "timestamp_alerta": datetime.now(timezone.utc).isoformat(),
    }
    with _ALERTAS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.warning(
        f"Alerta de revision creada para trend {ts.trend_id} en {_ALERTAS_PATH}"
    )


__all__ = [
    "inyectar_trend_validado",
    "crear_alerta_revision_manual",
]
