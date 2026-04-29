"""Punto unico de switch entre stubs y modulos reales del equipo.

Este modulo es la UNICA puerta de entrada de la biblioteca de Tarea 4 hacia
los modulos paralelos (Cris, Abi). Cuando los modulos reales esten listos,
solo se cambian los imports de este archivo y todo el resto del codigo sigue
funcionando sin tocar nada.

Estado de integracion (2026-04-29):

- ``ontology.OntologyClient`` (Abi - Bloque 1): DISPONIBLE.
- ``ontology_semantic.bridge.importar_owl_a_neo4j`` (Abi - Bloque 3): DISPONIBLE.
- ``ontology_semantic.validar.validar_grafo`` (Abi): DISPONIBLE.
- ``ontology_semantic.client_v2.OntologyClientV2`` con
  ``productos_similares`` (Abi - Bloque 5): DISPONIBLE.
- ``ontology_semantic.deontic.DeonticResolver`` (Abi - Bloque 5 deontico):
  NO ENTREGADO -> seguimos con stub.
- Forecast de Cris (Tarea 3): NO ENTREGADO -> seguimos con stub.

Variables expuestas (re-exports):
    obtener_forecast: funcion de forecast (de Cris o stub).
    tiene_historial: indicador de cold-start (de Cris o stub).
    caracterizar_serie: caracteristicas de la serie (de Cris o stub).
    DeonticResolver: razonador deontico (de Abi o stub).
    importar_owl_a_neo4j: bridge OWL (de Abi o stub).
    encontrar_similares: similarity engine (de Abi o stub).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# ============================================================
# SWITCH PRINCIPAL
# ============================================================
# Cambiar a False cuando todos los modulos reales esten en el repo principal.
# Tambien se puede forzar con la variable de entorno OPT_USAR_STUBS=0.
USAR_STUBS = os.getenv("OPT_USAR_STUBS", "1") == "1"


# ============================================================
# Forecast (Cris - Tarea 3) -- NO ENTREGADO AUN
# ============================================================

if USAR_STUBS:
    from optimization.stubs.forecast_stub import (  # type: ignore[no-redef]
        caracterizar_serie,
        obtener_forecast,
        tiene_historial,
    )
    logger.info("integrations: usando STUB de forecast (Cris)")
else:
    try:
        # Cuando Cris entregue, ajustar este import al path real:
        # ej. from forecast.cris_module import (...)
        from forecast.cris_module import (  # type: ignore[no-redef, import-not-found]
            caracterizar_serie,
            obtener_forecast,
            tiene_historial,
        )
        logger.info("integrations: usando modulo REAL de forecast (Cris)")
    except ImportError:
        logger.warning("integrations: modulo de Cris no disponible, fallback a STUB")
        from optimization.stubs.forecast_stub import (  # type: ignore[no-redef]
            caracterizar_serie,
            obtener_forecast,
            tiene_historial,
        )


# ============================================================
# Deontic Resolver (Abi - Bloque 5) -- NO ENTREGADO AUN
# ============================================================
# Abi tiene normas_marketplace.ttl pero el wrapper Python aun no.
# Cuando entregue, descomentar el import de ontology_semantic.deontic.

if USAR_STUBS:
    from optimization.stubs.deontic_stub import DeonticResolverStub as DeonticResolver  # type: ignore[no-redef]
    logger.info("integrations: usando STUB de deontic resolver (Abi)")
else:
    try:
        from ontology_semantic.deontic import DeonticResolver  # type: ignore[no-redef, import-not-found]
        logger.info("integrations: usando modulo REAL de deontic (Abi)")
    except ImportError:
        logger.warning("integrations: modulo deontic de Abi no disponible, fallback a STUB")
        from optimization.stubs.deontic_stub import DeonticResolverStub as DeonticResolver  # type: ignore[no-redef]


# ============================================================
# Bridge OWL/RDF (Abi - Bloque 3) -- DISPONIBLE
# ============================================================

try:
    from ontology_semantic.bridge import importar_owl_a_neo4j  # type: ignore[import-not-found]
    logger.info("integrations: usando modulo REAL de bridge (Abi)")
except ImportError:
    logger.warning("integrations: bridge de Abi no disponible, fallback a STUB")
    from optimization.stubs.bridge_stub import importar_owl_a_neo4j  # type: ignore[no-redef]


# ============================================================
# Similarity Engine (Abi - Bloque 5) -- DISPONIBLE
# ============================================================
# Abi expone OntologyClientV2.productos_similares(sku, k, umbral) que devuelve
# list[SimilarityResult] con sku_a, sku_b, score_total, confidence.
# Convertimos a la forma ProductoSimilar de la spec de Mati.

try:
    from ontology_semantic.client_v2 import OntologyClientV2  # type: ignore[import-not-found]
    _SIMILARITY_DISPONIBLE = True
    logger.info("integrations: usando modulo REAL de similarity (Abi - Bloque 5)")
except ImportError:
    _SIMILARITY_DISPONIBLE = False
    logger.warning("integrations: similarity engine de Abi no disponible, devuelve []")


def encontrar_similares(sku: str, k: int = 10, umbral: float = 0.6) -> list:
    """Wrapper sobre el similarity engine de Abi.

    Devuelve una lista de ``ProductoSimilar`` (forma definida por la spec
    de Mati). Si el modulo de Abi no esta disponible, devuelve [].

    Args:
        sku: SKU de referencia.
        k: cuantos similares devolver. Default 10.
        umbral: threshold minimo de score_total. Default 0.6.

    Returns:
        Lista de ``ProductoSimilar``. Vacia si el SKU no tiene aristas
        :SIMILAR_A precomputadas o si el engine no esta disponible.
    """
    from optimization.schemas import ProductoSimilar

    if not _SIMILARITY_DISPONIBLE:
        return []

    try:
        with OntologyClientV2() as ont:
            resultados = ont.productos_similares(sku, k=k, umbral=umbral)

        productos = []
        for r in resultados:
            # r es un SimilarityResult con sku_a, sku_b, score_total, ...
            sku_b = getattr(r, "sku_b", None)
            score = float(getattr(r, "score_total", 0.0))
            if not sku_b:
                continue

            # Pedir el nombre del producto si existe en el catalogo.
            nombre = ""
            try:
                with OntologyClientV2() as ont2:
                    info = ont2.producto(sku_b)
                    if info and "nombre" in info:
                        nombre = str(info["nombre"])
            except Exception:
                pass

            productos.append(ProductoSimilar(sku=str(sku_b), score=score, nombre=nombre))
        return productos
    except Exception as exc:
        logger.warning("encontrar_similares fallo: %s", exc)
        return []


def encontrar_similares_a_descripcion(text: str, k: int = 10) -> list:
    """Cold-start: SKUs cuya descripcion se parece a un texto libre.

    Util cuando se detecta una tendencia (TrendSignal de Mateo) y queremos
    saber a que productos del catalogo se parece.

    Returns:
        Lista de ``ProductoSimilar``. Vacia si el engine no esta disponible
        o si el texto es vacio.
    """
    from optimization.schemas import ProductoSimilar

    if not _SIMILARITY_DISPONIBLE or not text or not text.strip():
        return []

    try:
        with OntologyClientV2() as ont:
            resultados = ont.productos_similares_a_descripcion(text, k=k)

        productos = []
        for r in resultados:
            sku_b = getattr(r, "sku_b", None)
            score = float(getattr(r, "score_total", 0.0))
            if not sku_b:
                continue
            productos.append(ProductoSimilar(sku=str(sku_b), score=score, nombre=""))
        return productos
    except Exception as exc:
        logger.warning("encontrar_similares_a_descripcion fallo: %s", exc)
        return []


# ============================================================
# OntologyClient v1 (Abi - Bloque 1) -- DISPONIBLE
# ============================================================
# Re-export para que los algoritmos puedan consultar el grafo si necesitan
# (ej. proveedores reales en vez de los inyectados en DecisionContext).

try:
    from ontology import OntologyClient  # type: ignore[import-not-found]
    logger.info("integrations: usando OntologyClient v1 REAL (Abi)")
except ImportError:
    logger.warning("integrations: OntologyClient de Abi no disponible")
    OntologyClient = None  # type: ignore[assignment, misc]


__all__ = [
    "USAR_STUBS",
    "obtener_forecast",
    "tiene_historial",
    "caracterizar_serie",
    "DeonticResolver",
    "importar_owl_a_neo4j",
    "encontrar_similares",
    "encontrar_similares_a_descripcion",
    "OntologyClient",
]
