"""ontology_semantic.similarity - Motor de similaridad multidimensional.

Tarea 1 v2 - Bloque 5.

Este paquete implementa la similaridad entre SKUs descomponiendola en cuatro
senales ortogonales (lexica, estructural, comportamental, tendencia) y
combinandolas en un composite ponderado. Los pesos viven en
``config/similarity_weights.yaml`` y se cargan via
:func:`similarity.config.load_config`.

Componentes publicos:

- :class:`SimilarityEngine` (engine.py): clase principal con los 4 scorers
  y ``composite_score``.
- :class:`SimilarityResult` (types.py): resultado tipado de cualquier
  comparacion par-a-par.
- :func:`load_config` (config.py): lee el YAML y devuelve un dict tipado.
- :func:`precompute_embeddings` (embeddings.py - Stage 2): persiste embeddings
  de los 4643 productos a ``data/embeddings_productos.npy``.
- :func:`precompute_top_k` (precompute.py - Stage 4): persiste aristas
  ``[:SIMILAR_A]`` en Neo4j.

Ejemplo de uso de alto nivel (post Bloque 5 completo):

    from ontology_semantic.similarity import SimilarityEngine, load_config
    cfg = load_config()
    eng = SimilarityEngine(cfg)
    res = eng.composite_score("247329", "215773")
    print(res.score, res.confidence, res.flags)
"""

from ontology_semantic.similarity.types import (
    BehavioralFlag,
    SimilarityResult,
)
from ontology_semantic.similarity.config import (
    SimilarityConfig,
    load_config,
)
from ontology_semantic.similarity.engine import SimilarityEngine

__all__ = [
    "SimilarityEngine",
    "SimilarityResult",
    "BehavioralFlag",
    "SimilarityConfig",
    "load_config",
]
