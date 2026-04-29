"""client_v2.py - OntologyClientV2 con similitud par-a-par y por descripcion.

Tarea 1 v2 - Bloque 5 - Stage 5.

Extiende :class:`ontology.OntologyClient` v1 SIN tocarlo (regla 8 del
proyecto: no modificar la v1). Usa composicion + ``__getattr__`` para
delegar cualquier metodo desconocido al v1, asi todo el codigo existente
de Mauri/Mati/Cris sigue funcionando llamando a OntologyClientV2.

Metodos nuevos:

- :meth:`productos_similares`: para un SKU, devuelve los top-K similares
  precomputados en Neo4j como aristas ``:SIMILAR_A`` (Stage 4).
- :meth:`productos_similares_a_descripcion`: dado un texto libre, devuelve
  los top-K SKUs del catalogo cuya descripcion lexica es mas cercana.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from ontology import OntologyClient
from ontology_semantic.similarity import (
    BehavioralFlag,
    SimilarityEngine,
    SimilarityResult,
)


# Sentinel SKU para representar el lado "query de texto libre"
QUERY_TEXT_SKU = "<text-query>"


class OntologyClientV2:
    """Cliente extendido con similitud multidimensional sobre la ontologia."""

    def __init__(
        self,
        ontology_client: Optional[OntologyClient] = None,
        similarity_engine: Optional[SimilarityEngine] = None,
    ) -> None:
        self._v1 = ontology_client or OntologyClient()
        self._engine = similarity_engine

    def __getattr__(self, name: str):
        """Delega cualquier atributo desconocido al cliente v1."""
        return getattr(self._v1, name)

    @staticmethod
    def _to_v1_sku(sku) -> object:
        """Normaliza un sku al tipo que el v1+Neo4j esperan internamente."""
        s = str(sku)
        return int(s) if s.isdigit() else s

    def producto(self, sku) -> Optional[dict]:
        """Override de v1.producto() que tolera sku como str o int."""
        result = self._v1.producto(self._to_v1_sku(sku))
        if result and "sku" in result:
            result["sku"] = str(result["sku"])
        return result

    def proveedores_de_sku(self, sku) -> list[dict]:
        """Override de v1.proveedores_de_sku() que tolera sku str o int."""
        return self._v1.proveedores_de_sku(self._to_v1_sku(sku))

    def categoria_de_sku(self, sku) -> Optional[dict]:
        """Override de v1.categoria_de_sku() que tolera sku str o int."""
        return self._v1.categoria_de_sku(self._to_v1_sku(sku))

    @property
    def engine(self) -> SimilarityEngine:
        """Engine lazy-loaded desde disco con embeddings + atributos."""
        if self._engine is None:
            self._engine = SimilarityEngine.from_disk()
        return self._engine

    def close(self) -> None:
        """Cierra el driver del v1 y libera el engine."""
        self._v1.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def productos_similares(
        self,
        sku: str,
        k: int = 10,
        umbral: float = 0.6,
    ) -> list[SimilarityResult]:
        """Devuelve los top-K productos similares a uno dado."""
        if k <= 0:
            raise ValueError(f"k debe ser > 0, recibido {k}")
        if not 0.0 <= umbral <= 1.0:
            raise ValueError(f"umbral debe estar en [0, 1], recibido {umbral}")

        sku_str = str(sku)
        query = """
        MATCH (p:Producto)-[r:SIMILAR_A]-(o:Producto)
        WHERE toString(p.sku) = $sku
          AND r.score_total >= $umbral
        RETURN toString(o.sku)  AS sku_b,
               r.score_lex      AS score_lex,
               r.score_str      AS score_str,
               r.score_total    AS score_total,
               r.confidence     AS confidence
        ORDER BY r.score_total DESC
        LIMIT $k
        """
        with self._v1.driver.session() as s:
            records = s.run(query, sku=sku_str, umbral=float(umbral), k=int(k))
            return [self._record_a_similarity_result(sku_str, r) for r in records]

    @staticmethod
    def _record_a_similarity_result(sku_a: str, record) -> SimilarityResult:
        """Convierte un record de Cypher en SimilarityResult."""
        return SimilarityResult(
            sku_a=sku_a,
            sku_b=str(record["sku_b"]),
            score_lexical=float(record["score_lex"]),
            score_structural=float(record["score_str"]),
            score_behavioral=0.0,
            score_trend=0.0,
            score_total=float(record["score_total"]),
            confidence=float(record["confidence"]),
            behavioral_flag=BehavioralFlag.UNAVAILABLE_GLOBAL,
            flags=("from_neo4j_edge",
                   "behavioral_unavailable_global",
                   "trend_no_signal"),
        )

    def productos_similares_a_descripcion(
        self,
        text: str,
        k: int = 10,
    ) -> list[SimilarityResult]:
        """Top-K SKUs cuya descripcion lexica se parece a un texto libre."""
        if not text or not text.strip():
            raise ValueError("text no puede ser vacio")
        if k <= 0:
            raise ValueError(f"k debe ser > 0, recibido {k}")

        eng = self.engine
        if eng.embeddings is None:
            raise RuntimeError(
                "Engine sin matriz de embeddings. Corre primero "
                "`python -m ontology_semantic.similarity.embeddings precompute`."
            )

        query_emb = eng.embed_text(text)
        scores = eng.embeddings @ query_emb
        np.clip(scores, 0.0, 1.0, out=scores)

        if k >= scores.shape[0]:
            top_idx = np.argsort(-scores)
        else:
            part = np.argpartition(-scores, k)[:k]
            top_idx = part[np.argsort(-scores[part])]

        row_to_sku = {row: sku for sku, row in eng.sku_to_row.items()}
        w_lex = float(eng.cfg.weights["lexical"])

        out: list[SimilarityResult] = []
        for idx in top_idx[:k]:
            sku_b = row_to_sku[int(idx)]
            score = float(scores[int(idx)])
            out.append(SimilarityResult(
                sku_a=QUERY_TEXT_SKU,
                sku_b=sku_b,
                score_lexical=score,
                score_structural=0.0,
                score_behavioral=0.0,
                score_trend=0.0,
                score_total=score,
                confidence=w_lex,
                behavioral_flag=BehavioralFlag.UNAVAILABLE_GLOBAL,
                flags=("query_text",
                       "structural_missing",
                       "behavioral_unavailable_global",
                       "trend_no_signal"),
            ))
        return out
