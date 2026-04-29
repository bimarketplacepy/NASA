"""precompute_top_k.py - Matriz N x N + top-K + persistencia :SIMILAR_A.

Tarea 1 v2 - Bloque 5 - Stage 4.

Pipeline:

1. Carga embeddings + atributos persistidos por
   :func:`embeddings.precompute_embeddings`.
2. Computa la matriz lexica ``lex = embs @ embs.T`` (cosine = dot product
   porque los embeddings estan normalizados L2).
3. Computa la matriz estructural via Gower vectorizado: para cada
   atributo, la matriz de igualdad y disponibilidad por broadcasting.
4. Combina con los pesos efectivos del YAML renormalizados segun los
   scorers globalmente disponibles (en este Bloque 5 inicial: solo
   lexical + structural; behavioral y trend estan desactivados).
5. Para cada SKU, extrae top-K via ``np.argpartition``.
6. Deduplica pares ``(min, max)`` lexicograficamente para no persistir
   la arista en ambas direcciones.
7. Persiste como aristas ``[:SIMILAR_A {score_lex, score_str, score_total,
   confidence, computed_at}]`` en Neo4j con UNWIND batched.

Loguea:
- Tiempos por etapa.
- Distribucion de scores composite (P50, P75, P90, P95, P99) sobre
  un sample de pares para no procesar 21M numeros.
- Distribucion del K-esimo score por SKU (umbral implicito).
- Cantidad de aristas pre-dedup, post-dedup, persistidas.

Uso CLI:
    python -m ontology_semantic.similarity.precompute_top_k run
    python -m ontology_semantic.similarity.precompute_top_k run --force
    python -m ontology_semantic.similarity.precompute_top_k stats
    python -m ontology_semantic.similarity.precompute_top_k run --k 5
    python -m ontology_semantic.similarity.precompute_top_k run --threshold 0.7

Idempotencia:
- Sin ``--force``: usa MERGE sobre (a)-[:SIMILAR_A]->(b). Re-corre
  actualiza properties pero no duplica aristas.
- Con ``--force``: borra todas las :SIMILAR_A primero y reescribe.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase

from ontology_semantic.similarity.config import (
    SimilarityConfig,
    StructuralAttribute,
    load_config,
)
from ontology_semantic.similarity.embeddings import (
    EMBEDDINGS_INDEX,
    EMBEDDINGS_NPY,
    load_embeddings,
)


logger = logging.getLogger(__name__)
if not logger.handlers and not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


# =============================================================================
# Matrices.
# =============================================================================

def compute_lexical_matrix(embeddings: np.ndarray) -> np.ndarray:
    """Calcula la matriz cosine ``(N, N)`` por producto punto.

    Como ``embeddings`` esta normalizada L2 (cada fila tiene norma 1),
    el producto punto entre dos filas es igual al cosine. Para evitar
    pequenios negativos por error numerico, clipeamos a ``[0, 1]``.

    Args:
        embeddings: matriz ``(N, dim)`` float32 normalizada.

    Returns:
        Matriz ``(N, N)`` float32 con ``mat[i, j] = cosine(emb_i, emb_j)``.
    """
    logger.info("Calculando matriz lexica %d x %d ...",
                embeddings.shape[0], embeddings.shape[0])
    t0 = time.time()
    mat = embeddings @ embeddings.T
    np.clip(mat, 0.0, 1.0, out=mat)
    logger.info("Matriz lexica lista en %.2fs (shape=%s, dtype=%s)",
                time.time() - t0, mat.shape, mat.dtype)
    return mat


def compute_structural_matrix(
    productos: list[dict],
    cfg: SimilarityConfig,
) -> np.ndarray:
    """Calcula la matriz de Gower estructural ``(N, N)`` vectorizada.

    Algoritmo:
    - Para cada atributo en ``cfg.structural_attributes``:
      * Encodear los valores como enteros con ``pandas.factorize`` con
        ``-1`` para Nones/vacios.
      * Matriz de igualdad por broadcasting: ``codes[:, None] == codes[None, :]``.
      * Matriz de disponibilidad: ``(codes != -1)`` broadcast.
      * Acumular ``num += w * (eq * avail)`` y ``denom += w * avail``.
    - Score = ``num / denom`` donde ``denom > 0``, sino ``0.0``.

    Args:
        productos: lista de dicts del index, con cada uno conteniendo
            ``attrs: {pais_origen, perecedero, unidad, categoria_id,
            grupo_id}``.
        cfg: SimilarityConfig con la lista de StructuralAttribute.

    Returns:
        Matriz ``(N, N)`` float32 simetrica con score Gower en ``[0, 1]``.
    """
    n = len(productos)
    logger.info("Calculando matriz estructural %d x %d (Gower vectorizado)...",
                n, n)
    t0 = time.time()

    num = np.zeros((n, n), dtype=np.float32)
    denom = np.zeros((n, n), dtype=np.float32)

    for attr in cfg.structural_attributes:
        # Extrae valores en orden, normaliza Nones/vacios -> NaN
        # antes de factorize.
        valores = []
        for p in productos:
            v = p["attrs"].get(attr.name)
            if v is None or v == "":
                valores.append(None)
            else:
                # boolean -> str para que True/False/None se factoricen bien.
                valores.append(str(v))

        # pandas.factorize: NaN/None -> -1, demas -> 0..k-1.
        # use_na_sentinel=True (default) usa -1.
        # Pasamos como ndarray dtype=object para silenciar FutureWarning
        # de pandas (recibir listas crudas se va a deprecar).
        codes, uniques = pd.factorize(
            np.asarray(valores, dtype=object),
            use_na_sentinel=True,
        )
        codes = codes.astype(np.int32)
        n_unique = len(uniques)
        logger.info("    attr %-15s w=%.2f n_unique=%d missing=%d",
                    attr.name, attr.weight, n_unique,
                    int((codes == -1).sum()))

        # Broadcasting:
        # avail: shape (n, n) bool, True donde ambos lados tienen valor.
        avail = (codes[:, None] != -1) & (codes[None, :] != -1)
        # eq: shape (n, n) bool, True donde codes coinciden Y ambos disponibles.
        eq = (codes[:, None] == codes[None, :]) & avail

        # Acumular en float32 para no explotar memoria.
        num += attr.weight * eq.astype(np.float32)
        denom += attr.weight * avail.astype(np.float32)

    # Evitar division por cero. Donde denom = 0 -> score = 0.
    score = np.zeros_like(num)
    mask = denom > 0
    score[mask] = num[mask] / denom[mask]
    np.clip(score, 0.0, 1.0, out=score)

    logger.info("Matriz estructural lista en %.2fs", time.time() - t0)
    return score


def compute_composite_matrix(
    lex: np.ndarray,
    struct: np.ndarray,
    cfg: SimilarityConfig,
) -> tuple[np.ndarray, float]:
    """Combina lexical + structural con renormalizacion global.

    Como ``cfg.behavioral_available`` y ``cfg.trend_available`` son
    globales (mismo flag para todos los pares en este Bloque 5), la
    renormalizacion es uniforme: confidence es constante y los pesos
    efectivos tambien.

    Args:
        lex: matriz lexica ``(N, N)``.
        struct: matriz estructural ``(N, N)``.
        cfg: SimilarityConfig.

    Returns:
        Tupla ``(composite_matrix, confidence)``. ``confidence`` es
        constante porque la disponibilidad global no varia entre pares.

    Raises:
        ValueError: si ningun scorer esta disponible (sumaria 0).
    """
    weights = dict(cfg.weights)

    disponibles: dict[str, float] = {"lexical": weights["lexical"]}
    # structural: lo consideramos siempre disponible si todos los
    # productos tienen attrs. Para Bloque 5 esto se cumple.
    disponibles["structural"] = weights["structural"]

    if cfg.behavioral_available:
        # Cuando este modulo se actualice para incluir behavioral matrix,
        # se suma aqui.
        logger.warning(
            "behavioral_available=True pero precompute_top_k no calcula "
            "matriz behavioral todavia. Excluido del composite."
        )
    if cfg.trend_available:
        logger.warning(
            "trend_available=True pero precompute_top_k no calcula "
            "matriz trend todavia. Excluido del composite."
        )

    confidence = float(sum(disponibles.values()))
    if confidence == 0:
        raise ValueError("Ningun scorer disponible para composite.")

    eff = {k: v / confidence for k, v in disponibles.items()}
    logger.info("Pesos efectivos del composite: %s (confidence=%.3f)",
                {k: round(v, 4) for k, v in eff.items()}, confidence)

    composite = (eff["lexical"] * lex) + (eff["structural"] * struct)
    np.clip(composite, 0.0, 1.0, out=composite)
    return composite, confidence


# =============================================================================
# Estadisticas y top-K.
# =============================================================================

def reportar_distribucion(
    composite: np.ndarray,
    sample_size: int = 200_000,
) -> dict[str, float]:
    """Loguea P50/P75/P90/P95/P99 sobre un sample de pares no diagonales.

    Args:
        composite: matriz ``(N, N)``.
        sample_size: cuantos pares aleatorios mirar. Si N*(N-1) <= sample_size
            usa todos.

    Returns:
        Dict con percentiles de los scores.
    """
    n = composite.shape[0]
    rng = np.random.default_rng(seed=42)

    # Generamos pares (i, j) con i != j.
    n_total = n * (n - 1)
    if n_total <= sample_size:
        # Todos los pares no-diagonales.
        ii, jj = np.where(~np.eye(n, dtype=bool))
        scores = composite[ii, jj]
    else:
        ii = rng.integers(0, n, size=sample_size, dtype=np.int64)
        jj = rng.integers(0, n, size=sample_size, dtype=np.int64)
        # Filtra diagonales.
        mask = ii != jj
        ii, jj = ii[mask], jj[mask]
        scores = composite[ii, jj]

    pcts = {
        "P50": float(np.percentile(scores, 50)),
        "P75": float(np.percentile(scores, 75)),
        "P90": float(np.percentile(scores, 90)),
        "P95": float(np.percentile(scores, 95)),
        "P99": float(np.percentile(scores, 99)),
        "mean": float(np.mean(scores)),
        "max_off_diag": float(np.max(scores)),
        "min": float(np.min(scores)),
        "n_sample": int(scores.shape[0]),
    }
    logger.info("Distribucion composite (sample=%d):", pcts["n_sample"])
    logger.info("  min=%.3f  P50=%.3f  P75=%.3f  P90=%.3f  P95=%.3f  P99=%.3f  max=%.3f  mean=%.3f",
                pcts["min"], pcts["P50"], pcts["P75"], pcts["P90"],
                pcts["P95"], pcts["P99"], pcts["max_off_diag"], pcts["mean"])
    return pcts


def extract_top_k_edges(
    composite: np.ndarray,
    lex: np.ndarray,
    struct: np.ndarray,
    skus: list[str],
    confidence: float,
    k: int,
    threshold: Optional[float] = None,
) -> list[dict]:
    """Para cada SKU, extrae sus top-K similares (excluyendo self).

    Genera lista de aristas dirigidas (sku_a -> sku_b). El dedup posterior
    se ocupa de la simetria.

    Args:
        composite: matriz composite ``(N, N)``.
        lex: matriz lexica.
        struct: matriz estructural.
        skus: lista de SKUs (mismo orden que filas de las matrices).
        confidence: confidence uniforme calculada en
            :func:`compute_composite_matrix`.
        k: cuantos top mantener por SKU.
        threshold: si no es ``None``, descarta scores ``< threshold``.
            Aplica DESPUES del top-K (asi K es el limite superior).

    Returns:
        Lista de dicts ``{sku_a, sku_b, score_lex, score_str, score_total,
        confidence}``. Posiblemente con duplicados (la dedup viene despues).
    """
    n = composite.shape[0]
    logger.info("Extrayendo top-%d por SKU (N=%d)...", k, n)
    t0 = time.time()

    # Excluir self: enmascaramos la diagonal con -inf.
    composite_local = composite.copy()
    np.fill_diagonal(composite_local, -1.0)

    # argpartition es O(N) por fila; mucho mas rapido que sortear todo.
    # Tomamos los K mas grandes (los ultimos K despues de partition).
    if k >= n - 1:
        # Si k >= n-1, devolvemos todos.
        top_k_idx = np.argsort(-composite_local, axis=1)[:, :k]
    else:
        part = np.argpartition(-composite_local, k, axis=1)[:, :k]
        # Ordenar dentro de los K para presentacion.
        top_k_idx = np.empty_like(part)
        for i in range(n):
            order = np.argsort(-composite_local[i, part[i]])
            top_k_idx[i] = part[i][order]

    edges: list[dict] = []
    for i in range(n):
        for j in top_k_idx[i]:
            if i == j:
                continue
            score_t = float(composite[i, j])
            if threshold is not None and score_t < threshold:
                continue
            edges.append({
                "sku_a": skus[i],
                "sku_b": skus[int(j)],
                "score_lex": float(lex[i, j]),
                "score_str": float(struct[i, j]),
                "score_total": score_t,
                "confidence": float(confidence),
            })

    logger.info("Top-K extraidos en %.2fs (n_edges_pre_dedup=%d)",
                time.time() - t0, len(edges))
    return edges


def dedupe_pairs(edges: list[dict]) -> list[dict]:
    """Dedupea aristas usando ordenamiento lexicografico ``(min, max)``.

    Para cada par ``{a, b}``, conserva una sola arista con
    ``sku_a < sku_b`` y los scores correspondientes.

    Args:
        edges: lista posiblemente con duplicados.

    Returns:
        Lista deduplicada con sku_a < sku_b lexicograficamente.
    """
    seen: dict[tuple[str, str], dict] = {}
    for e in edges:
        a, b = e["sku_a"], e["sku_b"]
        if a == b:
            continue
        # Ordenar lexicograficamente (string compare).
        if a > b:
            a, b = b, a
        key = (a, b)
        # Si ya esta, conservamos el primero (los scores son simetricos
        # asi que da igual).
        if key not in seen:
            seen[key] = {
                "sku_a": a,
                "sku_b": b,
                "score_lex": e["score_lex"],
                "score_str": e["score_str"],
                "score_total": e["score_total"],
                "confidence": e["confidence"],
            }
    out = list(seen.values())
    logger.info("Dedup: %d -> %d aristas", len(edges), len(out))
    return out


def reportar_distribucion_top_k(edges: list[dict]) -> dict[str, float]:
    """Loguea distribucion de los scores en las aristas finales (post-dedup)."""
    if not edges:
        logger.warning("Sin aristas para reportar.")
        return {}
    scores = np.array([e["score_total"] for e in edges], dtype=np.float32)
    stats = {
        "n_edges": int(len(scores)),
        "min": float(scores.min()),
        "P50": float(np.percentile(scores, 50)),
        "P75": float(np.percentile(scores, 75)),
        "P90": float(np.percentile(scores, 90)),
        "max": float(scores.max()),
        "mean": float(scores.mean()),
    }
    logger.info("Distribucion scores aristas finales:")
    logger.info("  n=%d  min=%.3f  P50=%.3f  P75=%.3f  P90=%.3f  max=%.3f  mean=%.3f",
                stats["n_edges"], stats["min"], stats["P50"],
                stats["P75"], stats["P90"], stats["max"], stats["mean"])
    return stats


# =============================================================================
# Persistencia en Neo4j.
# =============================================================================

def _conexion_neo4j() -> Driver:
    load_dotenv()
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")
    if not all([uri, user, password]):
        raise RuntimeError(
            "Faltan NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD en el .env"
        )
    return GraphDatabase.driver(uri, auth=(user, password))


# Cypher de upsert con MERGE - idempotente.
# Usamos toString() para tolerar que sku este como integer en Neo4j.
CYPHER_UPSERT_SIMILAR_A = """
UNWIND $batch AS row
MATCH (a:Producto) WHERE toString(a.sku) = row.sku_a
MATCH (b:Producto) WHERE toString(b.sku) = row.sku_b
MERGE (a)-[r:SIMILAR_A]->(b)
SET r.score_lex   = row.score_lex,
    r.score_str   = row.score_str,
    r.score_total = row.score_total,
    r.confidence  = row.confidence,
    r.computed_at = datetime()
"""

CYPHER_BORRAR_SIMILAR_A = "MATCH ()-[r:SIMILAR_A]->() DELETE r"

CYPHER_COUNT_SIMILAR_A = "MATCH ()-[r:SIMILAR_A]->() RETURN count(r) AS n"


def persist_edges_to_neo4j(
    edges: list[dict],
    driver: Optional[Driver] = None,
    batch_size: int = 500,
    force: bool = False,
) -> int:
    """Persiste las aristas en Neo4j con UNWIND batched.

    Args:
        edges: lista de aristas dedupeadas con sku_a < sku_b.
        driver: driver Neo4j. Si None se crea desde .env.
        batch_size: tamanio de UNWIND. 500 es razonable.
        force: si ``True`` borra todas las :SIMILAR_A antes de insertar
            (clean slate). Si ``False``, MERGE actualiza properties.

    Returns:
        Cantidad final de aristas en Neo4j.
    """
    own_driver = driver is None
    if own_driver:
        driver = _conexion_neo4j()
    try:
        with driver.session() as s:
            if force:
                logger.info("FORCE: borrando todas las :SIMILAR_A previas...")
                t0 = time.time()
                s.run(CYPHER_BORRAR_SIMILAR_A)
                logger.info("Borrado en %.2fs", time.time() - t0)

            # Batches.
            t0 = time.time()
            n_batches = (len(edges) + batch_size - 1) // batch_size
            for i in range(0, len(edges), batch_size):
                batch = edges[i:i + batch_size]
                s.run(CYPHER_UPSERT_SIMILAR_A, batch=batch)
                if (i // batch_size) % 10 == 0 or i + batch_size >= len(edges):
                    logger.info("  Batch %d/%d (%d aristas escritas)",
                                i // batch_size + 1, n_batches,
                                min(i + batch_size, len(edges)))
            logger.info("Persistencia completa en %.2fs", time.time() - t0)

            # Count final.
            n_final = s.run(CYPHER_COUNT_SIMILAR_A).single()["n"]
            logger.info("Aristas :SIMILAR_A en Neo4j: %d", n_final)
            return int(n_final)
    finally:
        if own_driver:
            driver.close()


# =============================================================================
# Orquestador.
# =============================================================================

def precompute_top_k(
    cfg: Optional[SimilarityConfig] = None,
    k: Optional[int] = None,
    threshold: Optional[float] = None,
    force: bool = False,
    persist: bool = True,
) -> dict:
    """Ejecuta el pipeline completo: matrices -> top-K -> Neo4j.

    Args:
        cfg: SimilarityConfig. Si None carga el default.
        k: cuantos similares por SKU. Default ``cfg.top_k_default``.
        threshold: descarta scores ``< threshold``. Default ``None``
            (no descarta - usa K como unico criterio).
        force: si True borra :SIMILAR_A antes de insertar.
        persist: si False solo computa y reporta stats, sin tocar Neo4j.

    Returns:
        Dict con resultado: ``{n_edges, distribucion, tiempo_total}``.
    """
    if cfg is None:
        cfg = load_config()
    if k is None:
        k = cfg.top_k_default

    t_start = time.time()

    logger.info("=" * 60)
    logger.info("PRECOMPUTE TOP-K - Bloque 5 Stage 4")
    logger.info("k=%d, threshold=%s, force=%s, persist=%s",
                k, threshold, force, persist)
    logger.info("=" * 60)

    # 1. Carga embeddings + atributos
    logger.info("Cargando embeddings + atributos del Stage 2...")
    matrix, skus, sku_to_row, productos, meta = load_embeddings()
    logger.info("Cargados: N=%d, dim=%d, model=%s",
                len(skus), matrix.shape[1], meta["model_name"])

    # 2. Matriz lexica
    lex = compute_lexical_matrix(matrix)

    # 3. Matriz estructural
    struct = compute_structural_matrix(productos, cfg)

    # 4. Composite
    composite, confidence = compute_composite_matrix(lex, struct, cfg)
    logger.info("confidence (uniforme) = %.3f", confidence)

    # 5. Distribucion global
    pcts = reportar_distribucion(composite, sample_size=200_000)

    # 6. Top-K por SKU
    edges_dirigidas = extract_top_k_edges(
        composite, lex, struct, skus, confidence, k, threshold,
    )

    # 7. Dedup
    edges = dedupe_pairs(edges_dirigidas)

    # 8. Distribucion final
    stats_finales = reportar_distribucion_top_k(edges)

    n_persisted = 0
    if persist:
        n_persisted = persist_edges_to_neo4j(edges, force=force)
    else:
        logger.info("persist=False: NO escribimos en Neo4j.")

    elapsed = time.time() - t_start
    logger.info("=" * 60)
    logger.info("TOTAL: %.2fs (n_edges=%d, n_persisted=%d)",
                elapsed, len(edges), n_persisted)
    logger.info("=" * 60)

    return {
        "n_edges": len(edges),
        "n_persisted": n_persisted,
        "distribucion_global": pcts,
        "distribucion_finales": stats_finales,
        "elapsed_s": elapsed,
        "k": k,
        "threshold": threshold,
        "confidence": confidence,
    }


# =============================================================================
# CLI
# =============================================================================

def _cli() -> None:
    import argparse

    p = argparse.ArgumentParser(
        description="Precompute top-K + persiste :SIMILAR_A en Neo4j."
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub_run = sub.add_parser("run", help="Pipeline completo + persiste.")
    sub_run.add_argument("--k", type=int, default=None,
                         help="Top-K por SKU. Default = cfg.top_k_default.")
    sub_run.add_argument("--threshold", type=float, default=None,
                         help="Descarta scores < threshold.")
    sub_run.add_argument("--force", action="store_true",
                         help="Borra :SIMILAR_A previas antes de insertar.")

    sub_stats = sub.add_parser("stats",
                               help="Computa matrices y reporta sin persistir.")
    sub_stats.add_argument("--k", type=int, default=None)
    sub_stats.add_argument("--threshold", type=float, default=None)

    args = p.parse_args()

    if args.cmd == "run":
        precompute_top_k(k=args.k, threshold=args.threshold,
                         force=args.force, persist=True)
    elif args.cmd == "stats":
        precompute_top_k(k=args.k, threshold=args.threshold,
                         force=False, persist=False)


if __name__ == "__main__":
    _cli()
