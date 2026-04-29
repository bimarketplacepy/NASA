"""embeddings.py - Precompute de embeddings de productos para similitud lexica.

Tarea 1 v2 - Bloque 5 - Stage 2.

Lee los 4643 productos de Neo4j junto con su categoria/grupo/pais,
construye el texto fuente segun la plantilla del YAML, y persiste:

- ``data/embeddings_productos.npy``: matriz ``(N, dim)`` float32, normalizada
  a norma 1 (asi cosine = producto punto en runtime).
- ``data/embeddings_index.json``: metadata + lista ordenada
  ``[{sku, row, texto, attrs: {...}}, ...]``.

Idempotente: si los archivos existen y el hash sha256 del dataset
``(sku, texto)`` coincide con el guardado, NO recomputa (a menos que
``force=True``). Tambien valida que ``model_name`` y ``text_template``
coincidan con la corrida previa.

Uso programatico:

    from ontology_semantic.similarity.embeddings import (
        precompute_embeddings, load_embeddings,
    )
    matrix, skus, meta = precompute_embeddings()
    matrix, skus, sku_to_row, productos, meta = load_embeddings()

Uso CLI:

    python -m ontology_semantic.similarity.embeddings precompute
    python -m ontology_semantic.similarity.embeddings precompute --force
    python -m ontology_semantic.similarity.embeddings show --n 5
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


# ============================================================================
# Paths por defecto.
# ============================================================================

# data/ vive en la raiz del proyecto, dos niveles arriba de este archivo:
#   ontology_semantic/similarity/embeddings.py -> ../../data
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
EMBEDDINGS_NPY = DATA_DIR / "embeddings_productos.npy"
EMBEDDINGS_INDEX = DATA_DIR / "embeddings_index.json"


# ============================================================================
# Cypher query: trae los productos con su contexto jerarquico.
# ============================================================================

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


# ============================================================================
# Conexion Neo4j helper.
# ============================================================================

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


# ============================================================================
# Carga de productos desde Neo4j.
# ============================================================================

def cargar_productos_desde_neo4j(
    driver: Optional[Driver] = None,
) -> list[dict]:
    """Lee todos los Productos con sus atributos textuales y categoricos.

    Args:
        driver: instancia de neo4j Driver. Si es ``None`` crea uno desde
            ``.env`` y lo cierra antes de retornar.

    Returns:
        Lista de dicts ordenada por SKU asc. Cada dict tiene keys:
        ``sku``, ``nombre``, ``nombre_corto``, ``pais_origen``,
        ``perecedero``, ``unidad``, ``categoria_id``, ``categoria_nombre``,
        ``grupo_id``, ``grupo_nombre``. Valores ``None`` se reemplazan por
        ``""`` (strings) o ``False`` (perecedero) para uniformidad.

    Raises:
        RuntimeError: si las credenciales no estan en .env.
    """
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


# ============================================================================
# Construccion del texto fuente.
# ============================================================================

def _normalizar_campo(valor: object) -> str:
    """Normaliza un campo textual para meter en la plantilla.

    - Convierte ``None`` a ``""``.
    - ``str.strip()`` para sacar whitespace.
    - Quita puntos finales (uno o varios) para evitar ``..`` cuando la
      plantilla concatena ``"{nombre}. "``.

    Args:
        valor: lo que viene del producto (puede ser ``None``, ``str``,
            otro tipo se convierte via ``str()``).

    Returns:
        String saneado, posiblemente vacio.
    """
    if valor is None:
        return ""
    s = str(valor).strip()
    # Elimina secuencia de puntos finales sin tocar puntos internos.
    while s.endswith("."):
        s = s[:-1].rstrip()
    return s


def construir_texto(template: str, producto: dict) -> str:
    """Aplica la plantilla del YAML a un producto, manejando Nones y duplicados.

    Reglas:
    - Reemplaza ``None`` o ``""`` por strings vacios.
    - Quita puntos finales de cada campo antes del format (evita ``..``).
    - Si ``nombre_corto`` es substring de ``nombre`` (case-insensitive),
      lo descarta para no duplicar info redundante.
    - Si ``nombre`` es substring de ``nombre_corto``, promueve
      ``nombre_corto`` al rol de ``nombre`` (mas informativo).
    - Compacta espacios dobles, secuencias ``. .``, ``..``, ``:.``.

    Args:
        template: string con placeholders ``{nombre}``, ``{nombre_corto}``,
            ``{categoria}``, ``{grupo}``, ``{pais_origen}``.
        producto: dict como el que devuelve
            :func:`cargar_productos_desde_neo4j`.

    Returns:
        Texto listo para embeddear, sin espacios redundantes ni info
        duplicada entre nombre/nombre_corto.

    Ejemplo:
        >>> construir_texto(
        ...     "{nombre}. {nombre_corto}. Categoria: {categoria}.",
        ...     {"nombre": "BOLA D/AGUA", "nombre_corto": "Esfera",
        ...      "categoria_nombre": "ESFERAS"})
        'BOLA D/AGUA. Esfera. Categoria: ESFERAS.'

        >>> construir_texto(
        ...     "{nombre}. {nombre_corto}. Categoria: {categoria}.",
        ...     {"nombre": "BOLSA NAV. 29570", "nombre_corto": "Bolsa NAV",
        ...      "categoria_nombre": "BAZAR"})
        'BOLSA NAV. 29570. Categoria: BAZAR.'
    """
    nombre = _normalizar_campo(producto.get("nombre"))
    nombre_corto = _normalizar_campo(producto.get("nombre_corto"))

    # Dedup nombre / nombre_corto (case-insensitive).
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

    # Compactacion iterativa - el orden importa para que ". ." se atrape
    # antes de que "  " lo separe.
    cambios = True
    while cambios:
        cambios = False
        for old, new in [("  ", " "), ("..", "."), (". .", "."), (":.", ":")]:
            if old in texto:
                texto = texto.replace(old, new)
                cambios = True

    return texto.strip()


def hash_dataset(productos: list[dict], textos: list[str]) -> str:
    """Calcula sha256 del dataset ``(sku, texto)`` para idempotencia.

    El hash se vuelve estable bajo reordenamiento porque ordenamos por
    sku antes de serializar. Cualquier cambio en un texto fuente, el
    alta de un SKU nuevo, o el baja de uno existente cambia el hash y
    obliga a recomputar.

    Args:
        productos: lista de dicts (del orden que sea).
        textos: lista paralela de textos por producto.

    Returns:
        Hash hex de 64 chars.
    """
    payload = [{"sku": p["sku"], "texto": t} for p, t in zip(productos, textos)]
    payload.sort(key=lambda x: x["sku"])
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ============================================================================
# Computo de embeddings.
# ============================================================================

def compute_embeddings(
    textos: list[str],
    model_name: str,
    batch_size: int = 64,
    show_progress: bool = True,
) -> np.ndarray:
    """Embeddea una lista de textos con sentence-transformers.

    Los embeddings se normalizan a norma L2 = 1, asi en runtime el
    cosine se vuelve un producto punto (mas rapido, mismo resultado).

    Args:
        textos: lista de strings, uno por producto.
        model_name: nombre del modelo HuggingFace, ej.
            ``paraphrase-multilingual-MiniLM-L12-v2``.
        batch_size: cuantos textos procesa el modelo de una. 64 es un
            buen compromiso CPU para 4643 docs.
        show_progress: si muestra barra tqdm. ``True`` en CLI, ``False``
            en tests para no contaminar output.

    Returns:
        Matriz numpy ``(len(textos), dim)`` float32, normalizada.
    """
    # Import deferred para que el smoke test del scaffolding no necesite
    # bajar el modelo.
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


# ============================================================================
# Persistencia.
# ============================================================================

def save_embeddings(
    embeddings: np.ndarray,
    productos: list[dict],
    textos: list[str],
    meta: dict,
    npy_path: Path = EMBEDDINGS_NPY,
    index_path: Path = EMBEDDINGS_INDEX,
) -> None:
    """Persiste matriz + index a disco con escritura atomica (tmp+rename).

    Args:
        embeddings: matriz ``(N, dim)`` float32.
        productos: lista de dicts (mismo orden que las filas de la matriz).
        textos: textos generados (mismo orden).
        meta: dict con model_name, dataset_hash, text_template, etc.
        npy_path: destino de la matriz.
        index_path: destino del JSON.
    """
    npy_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_npy = npy_path.with_suffix(npy_path.suffix + ".tmp")
    tmp_idx = index_path.with_suffix(index_path.suffix + ".tmp")

    # IMPORTANT: np.save(<path>) agrega ".npy" automaticamente si el path
    # no termina en ".npy" (asi pasa con ".npy.tmp"). Para que el rename
    # atomico despues funcione, escribimos con file handle abierto - asi
    # numpy NO toca el path.
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
        "Embeddings persistidos: %s (%.2f MB) + %s (%.2f KB)",
        npy_path, npy_path.stat().st_size / 1e6,
        index_path, index_path.stat().st_size / 1e3,
    )


def load_embeddings(
    npy_path: Path = EMBEDDINGS_NPY,
    index_path: Path = EMBEDDINGS_INDEX,
) -> tuple[np.ndarray, list[str], dict[str, int], list[dict], dict]:
    """Carga embeddings y metadata ya persistidos.

    Args:
        npy_path: ruta de la matriz.
        index_path: ruta del index JSON.

    Returns:
        Tupla ``(matrix, skus, sku_to_row, productos, meta)``:
        - ``matrix``: numpy ``(N, dim)`` float32 normalizada.
        - ``skus``: lista de SKUs en el mismo orden que las filas.
        - ``sku_to_row``: dict para O(1) lookup.
        - ``productos``: lista completa de dicts ``{sku, row, texto, attrs}``.
        - ``meta``: dict con model_name, dataset_hash, text_template, etc.

    Raises:
        FileNotFoundError: si los archivos no existen. Llama a
            :func:`precompute_embeddings` primero.
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


# ============================================================================
# Orquestador.
# ============================================================================

def precompute_embeddings(
    cfg: Optional[SimilarityConfig] = None,
    force: bool = False,
    npy_path: Path = EMBEDDINGS_NPY,
    index_path: Path = EMBEDDINGS_INDEX,
) -> tuple[np.ndarray, list[str], dict]:
    """Orquesta el pipeline: Neo4j -> texto -> embeddings -> persiste.

    Es idempotente: si los archivos ya existen y el ``dataset_hash``,
    el ``model_name`` y el ``text_template`` coinciden con la corrida
    previa, no recomputa. ``force=True`` saltea el check.

    Args:
        cfg: SimilarityConfig. Si es ``None`` carga el default.
        force: si ``True`` recomputa aunque el hash coincida.
        npy_path: destino de la matriz.
        index_path: destino del JSON.

    Returns:
        Tupla ``(matrix, skus, meta)``.

    Raises:
        RuntimeError: si el modelo devuelve una dim distinta a
            ``cfg.embedding_dim``.
    """
    if cfg is None:
        cfg = load_config()

    # 1. Lectura
    logger.info("Leyendo productos desde Neo4j...")
    t0 = time.time()
    productos = cargar_productos_desde_neo4j()
    logger.info("Productos leidos: %d en %.2fs",
                len(productos), time.time() - t0)

    # 2. Construccion de texto fuente
    textos = [construir_texto(cfg.text_template, p) for p in productos]
    if textos:
        logger.info("Sample texto[0]: %r", textos[0])
        logger.info("Sample texto[1]: %r", textos[1] if len(textos) > 1 else "")

    # 3. Hash de idempotencia
    new_hash = hash_dataset(productos, textos)
    logger.info("Hash del dataset: %s", new_hash[:16])

    # 4. Check idempotencia
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
            else:
                cambios = []
                if old_meta.get("dataset_hash") != new_hash:
                    cambios.append("dataset_hash")
                if old_meta.get("model_name") != cfg.embedding_model_name:
                    cambios.append("model_name")
                if old_meta.get("text_template") != cfg.text_template:
                    cambios.append("text_template")
                logger.info("Cambios detectados (%s) -> recomputo", cambios)
        except Exception as e:
            logger.warning("No pude leer index existente, recomputo: %s", e)

    # 5. Embeddings
    embs = compute_embeddings(textos, cfg.embedding_model_name)
    if embs.shape[1] != cfg.embedding_dim:
        raise RuntimeError(
            f"Dim mismatch: el modelo devolvio {embs.shape[1]} pero el "
            f"YAML dice {cfg.embedding_dim}. Ajusta config/similarity_weights.yaml "
            f"-> embeddings.dim, o usa otro modelo."
        )

    # 6. Persistencia
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


# ============================================================================
# CLI
# ============================================================================

def _cli() -> None:
    """Entry point: ``python -m ontology_semantic.similarity.embeddings``."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Precompute de embeddings de productos para similitud lexica."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub_pre = sub.add_parser(
        "precompute",
        help="Lee Neo4j, embeddea y persiste a data/embeddings_*.",
    )
    sub_pre.add_argument(
        "--force", action="store_true",
        help="Recomputa aunque dataset/modelo/template coincidan con la corrida previa.",
    )

    sub_show = sub.add_parser(
        "show",
        help="Muestra metadata + sample de los embeddings persistidos.",
    )
    sub_show.add_argument(
        "--n", type=int, default=3, help="Cuantos sample mostrar.",
    )

    args = parser.parse_args()

    if args.cmd == "precompute":
        precompute_embeddings(force=args.force)
    elif args.cmd == "show":
        m, skus, sku_to_row, prods, meta = load_embeddings()
        print(f"Modelo:    {meta['model_name']}")
        print(f"Dim:       {meta['embedding_dim']}")
        print(f"N:         {meta['n_productos']}")
        print(f"Hash:      {meta['dataset_hash'][:16]}...")
        print(f"Computed:  {meta['computed_at_utc']}")
        print(f"Matrix:    shape={m.shape} dtype={m.dtype} "
              f"norm[0]={float(np.linalg.norm(m[0])):.4f}")
        print(f"\nSample de {args.n} productos:")
        for p_ in prods[:args.n]:
            t = p_["texto"]
            t_short = t[:80] + "..." if len(t) > 80 else t
            print(f"  sku={p_['sku']:<10} row={p_['row']:<5} "
                  f"texto={t_short!r}")


if __name__ == "__main__":
    _cli()
