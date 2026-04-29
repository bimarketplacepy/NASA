"""client_v2.py - OntologyClientV2 con similitud par-a-par y por descripcion.

Tarea 1 v2 - Bloque 5 - Stage 5.

Extiende :class:`ontology.OntologyClient` v1 SIN tocarlo (regla 8 del
proyecto: no modificar la v1). Usa composicion + ``__getattr__`` para
delegar cualquier metodo desconocido al v1, asi todo el codigo existente
de Mauri/Mati/Cris sigue funcionando llamando a OntologyClientV2.

Metodos nuevos:

- :meth:`productos_similares`: para un SKU, devuelve los top-K similares
  precomputados en Neo4j como aristas ``:SIMILAR_A`` (Stage 4). Filtra
  por threshold opcional, ordena por score_total descendente.
- :meth:`productos_similares_a_descripcion`: dado un texto libre (ej.
  scrapeado de la web), devuelve los top-K SKUs del catalogo cuya
  descripcion lexica es mas cercana. Usado para el cold-start de SKUs
  nuevos donde no tenemos el SKU todavia.

Uso:

    from ontology_semantic.client_v2 import OntologyClientV2

    with OntologyClientV2() as ont:
        # Metodos del v1 funcionan normal:
        info = ont.producto("17629")
        proveedores = ont.proveedores_de_sku("17629")

        # Metodos nuevos del v2:
        similares = ont.productos_similares("17629", k=5, umbral=0.7)
        for r in similares:
            print(r.sku_b, r.score_total, r.confidence)

        # Cold-start: queremos saber a que producto del catalogo
        # se parece una descripcion arbitraria.
        cold = ont.productos_similares_a_descripcion(
            "esfera dorada navidena 8cm", k=3,
        )
        for r in cold:
            print(r.sku_b, r.score_total)  # confidence=0.5 (solo lexico)
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


# Sentinel SKU para representar el lado "query de texto libre" en un
# SimilarityResult de productos_similares_a_descripcion. Asi el shape
# del retorno sigue siendo SimilarityResult (cumple contrato del prompt).
QUERY_TEXT_SKU = "<text-query>"


class OntologyClientV2:
    """Cliente extendido con similitud multidimensional sobre la ontologia.

    Hereda funcionalmente todo el v1 :class:`ontology.OntologyClient` via
    composicion + delegacion (no via subclassing). Agrega dos consultas
    nuevas relacionadas con el motor de similaridad (Bloque 5).

    Args:
        ontology_client: instancia de :class:`OntologyClient` v1 a
            envolver. Si ``None`` se crea una con credenciales del .env.
        similarity_engine: instancia de :class:`SimilarityEngine`
            ya construida. Si ``None`` se carga lazy desde disco la
            primera vez que se necesite (via ``from_disk()``).
    """

    def __init__(
        self,
        ontology_client: Optional[OntologyClient] = None,
        similarity_engine: Optional[SimilarityEngine] = None,
    ) -> None:
        self._v1 = ontology_client or OntologyClient()
        self._engine = similarity_engine

    # =========================================================================
    # Delegacion al v1.
    # =========================================================================

    def __getattr__(self, name: str):
        """Delega cualquier atributo desconocido al cliente v1.

        Esto hace que ``OntologyClientV2`` sea drop-in compatible con
        codigo que ya usa la v1: ``client_v2.eventos_proximos(60)`` se
        resuelve en ``self._v1.eventos_proximos(60)``.

        ``__getattr__`` solo se invoca cuando el atributo NO esta en
        ``self.__dict__`` ni en la clase, asi que no captura los metodos
        nuevos de v2 (incluyendo los overrides de producto/proveedores/
        categoria que normalizan sku).
        """
        # NB: __getattr__ recibe llamadas para atributos que no existen
        # en self.__dict__. _v1 va a estar en __dict__ porque lo seteamos
        # en __init__, asi que no hay loop infinito.
        return getattr(self._v1, name)

    # =========================================================================
    # Overrides de v1 que normalizan sku (str <-> int).
    # =========================================================================
    # Razon: Neo4j guarda :Producto.sku como integer (100% del catalogo,
    # verificado en diag_sku_type.py). El v1 OntologyClient documenta
    # ``sku: str`` y usa ``MATCH (p:Producto {sku: $sku})`` directamente,
    # lo cual falla por strict type comparison cuando el caller pasa una
    # string. Para no tocar el v1 (regla 8 del proyecto), el v2 envuelve
    # los metodos sku-taking castean al tipo que el v1+Neo4j esperan
    # internamente, y normalizan el sku de salida a string.
    #
    # Cuando los SKUs cambien a alfanumericos en el futuro (la TBox
    # los declara xsd:string), este override sigue funcionando: si la
    # string no es numerica, _to_v1_sku la deja tal cual.

    @staticmethod
    def _to_v1_sku(sku) -> object:
        """Normaliza un sku al tipo que el v1+Neo4j esperan internamente.

        Si la representacion string es completamente numerica, casteamos
        a int (porque Neo4j guarda asi). En otro caso devolvemos string
        tal cual (preparado para SKUs alfanumericos futuros).
        """
        s = str(sku)
        return int(s) if s.isdigit() else s

    def producto(self, sku) -> Optional[dict]:
        """Override de v1.producto() que tolera sku como str o int.

        Args:
            sku: codigo del producto. Acepta string ("219814") o int.

        Returns:
            Mismo dict que v1 pero con ``sku`` normalizado a string.
            ``None`` si no existe.
        """
        result = self._v1.producto(self._to_v1_sku(sku))
        if result and "sku" in result:
            result["sku"] = str(result["sku"])
        return result

    def proveedores_de_sku(self, sku) -> list[dict]:
        """Override de v1.proveedores_de_sku() que tolera sku str o int.

        Args:
            sku: codigo del producto. Acepta string o int.

        Returns:
            Misma lista que v1 (proveedores no tienen sku, no
            necesitamos post-procesar).
        """
        return self._v1.proveedores_de_sku(self._to_v1_sku(sku))

    def categoria_de_sku(self, sku) -> Optional[dict]:
        """Override de v1.categoria_de_sku() que tolera sku str o int.

        Args:
            sku: codigo del producto. Acepta string o int.

        Returns:
            Mismo dict que v1.
        """
        return self._v1.categoria_de_sku(self._to_v1_sku(sku))

    # =========================================================================
    # Lifecycle.
    # =========================================================================

    @property
    def engine(self) -> SimilarityEngine:
        """Engine lazy-loaded desde disco con embeddings + atributos.

        La primera llamada construye :class:`SimilarityEngine` via
        :meth:`SimilarityEngine.from_disk` (lee data/embeddings_*.json
        + .npy). Subsiguientes llamadas reusan la misma instancia.
        """
        if self._engine is None:
            self._engine = SimilarityEngine.from_disk()
        return self._engine

    def close(self) -> None:
        """Cierra el driver del v1 y libera el engine."""
        self._v1.close()
        # El engine no tiene recursos que cerrar (matriz numpy + dict).

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # =========================================================================
    # Similitud par-a-par desde aristas precomputadas.
    # =========================================================================

    def productos_similares(
        self,
        sku: str,
        k: int = 10,
        umbral: float = 0.6,
    ) -> list[SimilarityResult]:
        """Devuelve los top-K productos similares a uno dado.

        Lee las aristas ``:SIMILAR_A`` precomputadas en Neo4j (por
        :func:`precompute_top_k`). El recorrido es no-dirigido (la
        arista se persistio una sola vez con ordenamiento ``a < b``,
        asi que ``MATCH (p)-[r]-(o)`` la trae desde cualquier lado).

        Args:
            sku: SKU de referencia. Acepta string o int (toString()
                en Cypher tolera ambos).
            k: cuantos similares devolver. Default 10.
            umbral: threshold minimo de ``score_total``. Default 0.6.

        Returns:
            Lista de :class:`SimilarityResult` ordenada por
            ``score_total`` descendente. Vacia si el SKU no tiene
            aristas ``:SIMILAR_A`` o si el umbral filtra todo.

        Raises:
            ValueError: si ``k <= 0`` o ``umbral`` fuera de [0, 1].
        """
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
    def _record_a_similarity_result(
        sku_a: str,
        record,
    ) -> SimilarityResult:
        """Convierte un record de Cypher en SimilarityResult.

        Reconstruye los flags y el behavioral_flag desde el estado
        global del Bloque 5 (behavioral + trend siempre unavailable).
        Cuando esos modulos se activen en el futuro, esta logica
        deberia leer flags persistidos en la arista.
        """
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

    # =========================================================================
    # Similitud por descripcion libre (cold-start desde scraper).
    # =========================================================================

    def productos_similares_a_descripcion(
        self,
        text: str,
        k: int = 10,
    ) -> list[SimilarityResult]:
        """Top-K SKUs cuya descripcion lexica se parece a un texto libre.

        Embeddea ``text`` con el mismo modelo del catalogo (lazy load
        primera vez), hace producto punto contra todos los embeddings
        precomputados (matmul N x dim), y extrae top-K con argpartition.

        Como el texto no tiene atributos categoricos ni ventas, SOLO
        la senal lexica esta disponible. ``confidence`` retornado es el
        peso lexico del YAML (default 0.5), no 1.0 - esa baja confianza
        es la senal honesta para el dispatcher de cold-start.

        Args:
            text: descripcion del producto (ej. titulo de listing, chunk
                de RAG sobre tendencia).
            k: cuantos resultados devolver. Default 10.

        Returns:
            Lista de :class:`SimilarityResult` con ``sku_a == "<text-query>"``,
            ``sku_b`` = SKU del catalogo, score_total = score_lexical
            (porque eff_lex = 1.0 cuando es el unico disponible),
            confidence = peso lexico del YAML.

        Raises:
            ValueError: si ``text`` es vacio o ``k <= 0``.
            RuntimeError: si el engine no tiene embeddings cargados.
        """
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
        # Producto punto: (N, dim) @ (dim,) -> (N,). Cosine porque
        # ambos lados estan normalizados L2.
        scores = eng.embeddings @ query_emb
        np.clip(scores, 0.0, 1.0, out=scores)

        # Top-K via argpartition (mas barato que sortear todo).
        if k >= scores.shape[0]:
            top_idx = np.argsort(-scores)
        else:
            part = np.argpartition(-scores, k)[:k]
            top_idx = part[np.argsort(-scores[part])]

        # Reverse map: row -> sku.
        row_to_sku = {row: sku for sku, row in eng.sku_to_row.items()}

        # confidence efectiva cuando solo lex esta disponible:
        # sum de pesos disponibles = w_lex.
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
                # Renormalizando con solo lex disponible:
                # eff_lex = w_lex / w_lex = 1.0  ->  score_total = score
                score_total=score,
                confidence=w_lex,
                behavioral_flag=BehavioralFlag.UNAVAILABLE_GLOBAL,
                flags=("query_text",
                       "structural_missing",
                       "behavioral_unavailable_global",
                       "trend_no_signal"),
            ))
        return out
