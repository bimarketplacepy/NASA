"""precompute_top_k.py - Matriz N x N + top-K + persistencia :SIMILAR_A.

Tarea 1 v2 - Bloque 5 - Stage 4.

Pipeline:
1. Carga embeddings + atributos persistidos.
2. Computa la matriz lexica.
3. Computa la matriz estructural via Gower vectorizado.
4. Combina con los pesos efectivos del YAML renormalizados.
5. Para cada SKU, extrae top-K via np.argpartition.
6. Deduplica pares (min, max) lexicograficamente.
7. Persiste como aristas :SIMILAR_A en Neo4j con UNWIND batched.

Uso CLI:
    python -m ontology_semantic.similarity.precompute_top_k run
    python -m ontology_semantic.similarity.precompute_top_k run --force
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


def compute_lexical_matrix(embeddings: np.ndarray) -> np.ndarray:
    """Calcula la matriz cosine (N, N) por producto punto."""
    logger.info("Calculando matriz lexica %d x %d ...",
                embeddings.shape[0], embeddings.shape[0])
    t0 = time.time()
    mat = embeddings @ embeddings.T
    np.clip(mat, 0.0, 1.0, out=mat)
    logger.info("Matriz lexica lista en %.2fs", time.time() - t0)
    return mat


def compute_structural_matrix(
    productos: list[dict],
    cfg: SimilarityConfig,
) -> np.ndarray:
    """Calcula la matriz de Gower estructural (N, N) vectorizada."""
    n = len(productos)
    logger.info("Calculando matriz estructural %d x %d (Gower vectorizado)...",
                n, n)
    t0 = time.time()

    num = np.zeros((n, n), dtype=np.float32)
    denom = np.zeros((n, n), dtype=np.float32)

    for attr in cfg.structural_attributes:
        valores = []
        for p in productos:
            v = p["attrs"].get(attr.name)
            if v is None or v == "":
                valores.append(None)
            else:
                valores.append(str(v))

        codes, uniques = pd.factorize(
            np.asarray(valores, dtype=object),
            use_na_sentinel=True,
        )
        codes = codes.astype(np.int32)

        avail = (codes[:, None] != -1) & (codes[None, :] != -1)
        eq = (codes[:, None] == codes[None, :]) & avail

        num += attr.weight * eq.astype(np.float32)
        denom += attr.weight * avail.astype(np.float32)

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
    """Combina lexical + structural con renormalizacion global."""
    weights = dict(cfg.weights)
    disponibles: dict[str, float] = {"lexical": weights["lexical"]}
    disponibles["structural"] = weights["structural"]

    confidence = float(sum(disponibles.values()))
    if confidence == 0:
        raise ValueError("Ningun scorer disponible para composite.")

    eff = {k: v / confidence for k, v in disponibles.items()}
    composite = (eff["lexical"] * lex) + (eff["structural"] * struct)
    np.clip(composite, 0.0, 1.0, out=composite)
    return composite, confidence


def extract_top_k_edges(
    composite: np.ndarray,
    lex: np.ndarray,
    struct: np.ndarray,
    skus: list[str],
    confidence: float,
    k: int,
    threshold: Optional[float] = None,
) -> list[dict]:
    """Para cada SKU, extrae sus top-K similares (excluyendo self)."""
    n = composite.shape[0]
    logger.info("Extrayendo top-%d por SKU (N=%d)...", k, n)

    composite_local = composite.copy()
    np.fill_diagonal(composite_local, -1.0)

    if k >= n - 1:
        top_k_idx = np.argsort(-composite_local, axis=1)[:, :k]
    else:
        part = np.argpartition(-composite_local, k, axis=1)[:, :k]
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

    logger.info("Top-K extraidos (n_edges_pre_dedup=%d)", len(edges))
    return edges


def dedupe_pairs(edges: list[dict]) -> list[dict]:
    """Dedupea aristas usando ordenamiento lexicografico (min, max)."""
    seen: dict[tuple[str, str], dict] = {}
    for e in edges:
        a, b = e["sku_a"], e["sku_b"]
        if a == b:
            continue
        if a > b:
            a, b = b, a
        key = (a, b)
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


def _conexion_neo4j() -> Driver:
    load_dotenv()
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")
    if not all([uri, user, password]):
        raise RuntimeError("Faltan NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD en el .env")
    return GraphDatabase.driver(uri, auth=(user, password))


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
    """Persiste las aristas en Neo4j con UNWIND batched."""
    own_driver = driver is None
    if own_driver:
        driver = _conexion_neo4j()
    try:
        with driver.session() as s:
            if force:
                logger.info("FORCE: borrando todas las :SIMILAR_A previas...")
                s.run(CYPHER_BORRAR_SIMILAR_A)

            n_batches = (len(edges) + batch_size - 1) // batch_size
            for i in range(0, len(edges), batch_size):
                batch = edges[i:i + batch_size]
                s.run(CYPHER_UPSERT_SIMILAR_A, batch=batch)

            n_final = s.run(CYPHER_COUNT_SIMILAR_A).single()["n"]
            logger.info("Aristas :SIMILAR_A en Neo4j: %d", n_final)
            return int(n_final)
    finally:
        if own_driver:
            driver.close()


def precompute_top_k(
    cfg: Optional[SimilarityConfig] = None,
    k: Optional[int] = None,
    threshold: Optional[float] = None,
    force: bool = False,
    persist: bool = True,
) -> dict:
    """Ejecuta el pipeline completo: matrices -> top-K -> Neo4j."""
    if cfg is None:
        cfg = load_config()
    if k is None:
        k = cfg.top_k_default

    t_start = time.time()

    logger.info("Cargando embeddings + atributos del Stage 2...")
    matrix, skus, sku_to_row, productos, meta = load_embeddings()
    logger.info("Cargados: N=%d, dim=%d", len(skus), matrix.shape[1])

    lex = compute_lexical_matrix(matrix)
    struct = compute_structural_matrix(productos, cfg)
    composite, confidence = compute_composite_matrix(lex, struct, cfg)

    edges_dirigidas = extract_top_k_edges(
        composite, lex, struct, skus, confidence, k, threshold,
    )
    edges = dedupe_pairs(edges_dirigidas)

    n_persisted = 0
    if persist:
        n_persisted = persist_edges_to_neo4j(edges, force=force)

    elapsed = time.time() - t_start
    logger.info("TOTAL: %.2fs (n_edges=%d, n_persisted=%d)",
                elapsed, len(edges), n_persisted)

    return {
        "n_edges": len(edges),
        "n_persisted": n_persisted,
        "elapsed_s": elapsed,
        "k": k,
        "threshold": threshold,
        "confidence": confidence,
    }


def _cli() -> None:
    import argparse

    p = argparse.ArgumentParser(
        description="Precompute top-K + persiste :SIMILAR_A en Neo4j."
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub_run = sub.add_parser("run", help="Pipeline completo + persiste.")
    sub_run.add_argument("--k", type=int, default=None)
    sub_run.add_argument("--threshold", type=float, default=None)
    sub_run.add_argument("--force", action="store_true")

    sub_stats = sub.add_parser("stats", help="Computa sin persistir.")
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
