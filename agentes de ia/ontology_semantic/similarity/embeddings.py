"""embeddings.py - Precompute de embeddings de productos para similitud lexica.

Tarea 1 v2 - Bloque 5 - Stage 2.

Lee los productos de Neo4j junto con su categoria/grupo/pais, construye el
texto fuente segun la plantilla del YAML, y persiste:

- ``data/embeddings_productos.npy``: matriz ``(N, dim)`` float32, normalizada
  a norma 1.
- ``data/embeddings_index.json``: metadata + lista ordenada
  ``[{sku, row, texto, attrs: {...}}, ...]``.

Idempotente: si los archivos existen y el hash sha256 del dataset coincide
con el guardado, NO recomputa.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase

from ontology_semantic.similarity.config import (
    SimilarityConfig,
    load_config,
)


logger = logging.getLogger(__name__)
if not logger.handlers and not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
EMBEDDINGS_NPY = DATA_DIR / "embeddings_productos.npy"
EMBEDDINGS_INDEX = DATA_DIR / "embeddings_index.json"


CYPHER_PRODUCTOS_PARA_EMBEDDING = """
MATCH (p:Producto)
OPTIONAL MATCH (p)-[:PERTENECE_A]->(c:Categoria)
OPTIONAL MATCH (c)-[:PERTENECE_A]->(g:Grupo)
RETURN p.sku                AS sku,
       p.nombre              AS nombre,
       p.nombre_corto        AS nombre_corto,
       p.pais_origen         AS pais_origen,
       p.perecedero          AS perecedero,
       p.unidad              AS unidad,
       c.id                  AS categoria_id,
       c.nombre              AS categoria_nombre,
       g.id                  AS grupo_id,
       g.nombre              AS grupo_nombre
ORDER BY p.sku
"""


def _conexion_neo4j() -> Driver:
    """Crea un driver Neo4j leyendo credenciales del .env del proyecto."""
    load_dotenv()
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")
    if not all([uri, user, password]):
        raise RuntimeError(
            "Faltan NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD en el .env del proyecto"
        )
    return GraphDatabase.driver(uri, auth=(user, password))


def cargar_productos_desde_neo4j(
    driver: Optional[Driver] = None,
) -> list[dict]:
    """Lee todos los Productos con sus atributos textuales y categoricos."""
    own_driver = driver is None
    if own_driver:
        driver = _conexion_neo4j()
    try:
        with driver.session() as s:
            return [
                {
                    "sku": str(r["sku"]),
                    "nombre": r["nombre"] or "",
                    "nombre_corto": r["nombre_corto"] or "",
                    "pais_origen": r["pais_origen"] or "",
                    "perecedero": bool(r["perecedero"]) if r["perecedero"] is not None else False,
                    "unidad": r["unidad"] or "",
                    "categoria_id": r["categoria_id"],
                    "categoria_nombre": r["categoria_nombre"] or "",
                    "grupo_id": r["grupo_id"],
                    "grupo_nombre": r["grupo_nombre"] or "",
                }
                for r in s.run(CYPHER_PRODUCTOS_PARA_EMBEDDING)
            ]
    finally:
        if own_driver:
            driver.close()


def _normalizar_campo(valor: object) -> str:
    """Normaliza un campo textual para meter en la plantilla."""
    if valor is None:
        return ""
    s = str(valor).strip()
    while s.endswith("."):
        s = s[:-1].rstrip()
    return s


def construir_texto(template: str, producto: dict) -> str:
    """Aplica la plantilla del YAML a un producto."""
    nombre = _normalizar_campo(producto.get("nombre"))
    nombre_corto = _normalizar_campo(producto.get("nombre_corto"))

    if nombre and nombre_corto:
        nu, ncu = nombre.upper(), nombre_corto.upper()
        if ncu in nu:
            nombre_corto = ""
        elif nu in ncu:
            nombre = nombre_corto
            nombre_corto = ""

    sustituciones = {
        "nombre": nombre,
        "nombre_corto": nombre_corto,
        "categoria": _normalizar_campo(producto.get("categoria_nombre")),
        "grupo": _normalizar_campo(producto.get("grupo_nombre")),
        "pais_origen": _normalizar_campo(producto.get("pais_origen")),
    }
    texto = template.format(**sustituciones)

    cambios = True
    while cambios:
        cambios = False
        for old, new in [("  ", " "), ("..", "."), (". .", "."), (":.", ":")]:
            if old in texto:
                texto = texto.replace(old, new)
                cambios = True

    return texto.strip()


def hash_dataset(productos: list[dict], textos: list[str]) -> str:
    """Calcula sha256 del dataset (sku, texto) para idempotencia."""
    payload = [{"sku": p["sku"], "texto": t} for p, t in zip(productos, textos)]
    payload.sort(key=lambda x: x["sku"])
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_embeddings(
    textos: list[str],
    model_name: str,
    batch_size: int = 64,
    show_progress: bool = True,
) -> np.ndarray:
    """Embeddea una lista de textos con sentence-transformers."""
    from sentence_transformers import SentenceTransformer

    logger.info("Cargando modelo: %s", model_name)
    t0 = time.time()
    model = SentenceTransformer(model_name)
    logger.info("Modelo cargado en %.2fs", time.time() - t0)

    logger.info("Embeddeando %d textos (batch_size=%d)...",
                len(textos), batch_size)
    t0 = time.time()
    embs = model.encode(
        textos,
        batch_size=batch_size,
        convert_to_numpy=True,
        show_progress_bar=show_progress,
        normalize_embeddings=True,
    )
    elapsed = time.time() - t0
    logger.info("Embeddings completos en %.2fs (%.1f docs/s)",
                elapsed, len(textos) / max(elapsed, 1e-9))
    return embs.astype(np.float32)


def save_embeddings(
    embeddings: np.ndarray,
    productos: list[dict],
    textos: list[str],
    meta: dict,
    npy_path: Path = EMBEDDINGS_NPY,
    index_path: Path = EMBEDDINGS_INDEX,
) -> None:
    """Persiste matriz + index a disco con escritura atomica (tmp+rename)."""
    npy_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_npy = npy_path.with_suffix(npy_path.suffix + ".tmp")
    tmp_idx = index_path.with_suffix(index_path.suffix + ".tmp")

    with open(tmp_npy, "wb") as f:
        np.save(f, embeddings, allow_pickle=False)

    index = {
        "meta": meta,
        "productos": [
            {
                "sku": p["sku"],
                "row": i,
                "texto": t,
                "attrs": {
                    "pais_origen": p["pais_origen"],
                    "perecedero": p["perecedero"],
                    "unidad": p["unidad"],
                    "categoria_id": p["categoria_id"],
                    "grupo_id": p["grupo_id"],
                },
            }
            for i, (p, t) in enumerate(zip(productos, textos))
        ],
    }
    with tmp_idx.open("w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    tmp_npy.replace(npy_path)
    tmp_idx.replace(index_path)
    logger.info(
        "Embeddings persistidos: %s + %s",
        npy_path, index_path,
    )


def load_embeddings(
    npy_path: Path = EMBEDDINGS_NPY,
    index_path: Path = EMBEDDINGS_INDEX,
) -> tuple[np.ndarray, list[str], dict[str, int], list[dict], dict]:
    """Carga embeddings y metadata ya persistidos.

    Returns:
        (matrix, skus, sku_to_row, productos, meta)
    """
    if not npy_path.exists() or not index_path.exists():
        raise FileNotFoundError(
            f"No encontre embeddings en {npy_path} o {index_path}. "
            f"Corre primero: "
            f"python -m ontology_semantic.similarity.embeddings precompute"
        )
    matrix = np.load(npy_path)
    with index_path.open("r", encoding="utf-8") as f:
        idx = json.load(f)
    productos = idx["productos"]
    skus = [p["sku"] for p in productos]
    sku_to_row = {p["sku"]: int(p["row"]) for p in productos}
    return matrix, skus, sku_to_row, productos, idx["meta"]


def precompute_embeddings(
    cfg: Optional[SimilarityConfig] = None,
    force: bool = False,
    npy_path: Path = EMBEDDINGS_NPY,
    index_path: Path = EMBEDDINGS_INDEX,
) -> tuple[np.ndarray, list[str], dict]:
    """Orquesta el pipeline: Neo4j -> texto -> embeddings -> persiste."""
    if cfg is None:
        cfg = load_config()

    logger.info("Leyendo productos desde Neo4j...")
    t0 = time.time()
    productos = cargar_productos_desde_neo4j()
    logger.info("Productos leidos: %d en %.2fs",
                len(productos), time.time() - t0)

    textos = [construir_texto(cfg.text_template, p) for p in productos]
    new_hash = hash_dataset(productos, textos)
    logger.info("Hash del dataset: %s", new_hash[:16])

    if not force and npy_path.exists() and index_path.exists():
        try:
            with index_path.open("r", encoding="utf-8") as f:
                old_idx = json.load(f)
            old_meta = old_idx.get("meta", {})
            if (old_meta.get("dataset_hash") == new_hash
                    and old_meta.get("model_name") == cfg.embedding_model_name
                    and old_meta.get("text_template") == cfg.text_template):
                logger.info(
                    "IDEMPOTENTE: dataset/modelo/template iguales que la "
                    "corrida previa. No recomputo. (use --force para forzar)"
                )
                m, skus, _, _, meta = load_embeddings(npy_path, index_path)
                return m, skus, meta
        except Exception as e:
            logger.warning("No pude leer index existente, recomputo: %s", e)

    embs = compute_embeddings(textos, cfg.embedding_model_name)
    if embs.shape[1] != cfg.embedding_dim:
        raise RuntimeError(
            f"Dim mismatch: el modelo devolvio {embs.shape[1]} pero el "
            f"YAML dice {cfg.embedding_dim}."
        )

    meta = {
        "model_name": cfg.embedding_model_name,
        "embedding_dim": int(embs.shape[1]),
        "text_template": cfg.text_template,
        "dataset_hash": new_hash,
        "n_productos": len(productos),
        "computed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    save_embeddings(embs, productos, textos, meta, npy_path, index_path)

    return embs, [p["sku"] for p in productos], meta


def _cli() -> None:
    """Entry point: ``python -m ontology_semantic.similarity.embeddings``."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Precompute de embeddings de productos para similitud lexica."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub_pre = sub.add_parser("precompute", help="Lee Neo4j, embeddea y persiste.")
    sub_pre.add_argument("--force", action="store_true",
                         help="Recomputa aunque el hash coincida.")

    sub_show = sub.add_parser("show", help="Muestra metadata.")
    sub_show.add_argument("--n", type=int, default=3)

    args = parser.parse_args()

    if args.cmd == "precompute":
        precompute_embeddings(force=args.force)
    elif args.cmd == "show":
        m, skus, sku_to_row, prods, meta = load_embeddings()
        print(f"Modelo:    {meta['model_name']}")
        print(f"Dim:       {meta['embedding_dim']}")
        print(f"N:         {meta['n_productos']}")
        print(f"Hash:      {meta['dataset_hash'][:16]}...")
        print(f"Matrix:    shape={m.shape} dtype={m.dtype}")
        print(f"\nSample de {args.n} productos:")
        for p_ in prods[:args.n]:
            t = p_["texto"]
            t_short = t[:80] + "..." if len(t) > 80 else t
            print(f"  sku={p_['sku']:<10} row={p_['row']:<5} "
                  f"texto={t_short!r}")


if __name__ == "__main__":
    _cli()
