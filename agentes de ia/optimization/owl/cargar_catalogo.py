"""Script idempotente para cargar el catalogo OWL al grafo de Abi.

Lee ``algorithms_catalog.ttl`` y lo importa via el bridge OWL/RDF
(``importar_owl_a_neo4j``). Si el bridge real de Abi no esta disponible,
hace fallback al stub que persiste a JSON.

Uso:
    python -m optimization.owl.cargar_catalogo

Es idempotente: re-correr no duplica triples (el bridge usa MERGE).
"""

from __future__ import annotations

import logging
from pathlib import Path

from optimization.integrations import importar_owl_a_neo4j

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CATALOG_PATH = Path(__file__).parent / "algorithms_catalog.ttl"


def cargar_catalogo() -> dict:
    """Carga el catalogo TTL al grafo de Abi.

    Returns:
        Diccionario con resultado del bridge (ok, tripletas_importadas, mensaje).

    Raises:
        FileNotFoundError: si no existe ``algorithms_catalog.ttl``.
    """
    if not CATALOG_PATH.exists():
        raise FileNotFoundError(f"No se encontro el catalogo OWL en {CATALOG_PATH}")

    ruta_absoluta = str(CATALOG_PATH.resolve())
    logger.info("Cargando catalogo OWL desde %s", ruta_absoluta)

    # El bridge real de Abi espera ruta de archivo (Path/str), no el texto TTL.
    # El stub acepta ruta o contenido (ver optimization/stubs/bridge_stub.py).
    resultado = importar_owl_a_neo4j(ruta_absoluta)

    if hasattr(resultado, "triplesLoaded"):
        logger.info(
            "Resultado bridge: status=%s triplesLoaded=%s",
            getattr(resultado, "terminationStatus", "?"),
            getattr(resultado, "triplesLoaded", "?"),
        )
        return {
            "ok": True,
            "terminationStatus": resultado.terminationStatus,
            "tripletas_importadas": resultado.triplesLoaded,
            "triplesParsed": resultado.triplesParsed,
            "mensaje": resultado.extraInfo or "",
        }
    logger.info("Resultado bridge: %s", resultado.get("mensaje", "ok"))
    return resultado


if __name__ == "__main__":
    res = cargar_catalogo()
    print(f"Catalogo cargado: {res}")
