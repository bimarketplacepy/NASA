"""config.py - Carga y validacion del YAML de pesos.

Lee ``config/similarity_weights.yaml`` y devuelve un objeto tipado
``SimilarityConfig``. Falla rapido y con mensaje claro si el archivo
falta o tiene un campo invalido.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# Path por defecto del YAML, relativo a la raiz del proyecto.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "similarity_weights.yaml"


@dataclass(frozen=True)
class StructuralAttribute:
    """Definicion de un atributo categorico para Gower estructural."""

    name: str
    type: str
    weight: float


@dataclass(frozen=True)
class SimilarityConfig:
    """Vista tipada de ``config/similarity_weights.yaml``."""

    weights: dict[str, float]
    threshold_default: float
    top_k_default: int
    embedding_model_name: str
    embedding_dim: int
    text_template: str
    structural_attributes: tuple[StructuralAttribute, ...]
    behavioral_available: bool
    trend_available: bool


def load_config(path: Path | str | None = None) -> SimilarityConfig:
    """Carga el YAML de pesos y devuelve un :class:`SimilarityConfig`."""
    p = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"No encontre el config de similaridad en {p}. "
            f"Lo crea el Bloque 5; si no existe, re-corre el setup del bloque."
        )
    with p.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)

    # --- weights ----------------------------------------------------------
    w = raw.get("weights")
    if not isinstance(w, dict):
        raise ValueError("El YAML debe tener una seccion 'weights' dict.")
    expected = {"lexical", "structural", "behavioral", "trend"}
    missing = expected - set(w.keys())
    if missing:
        raise ValueError(f"Faltan pesos en el YAML: {sorted(missing)}")
    for k, v in w.items():
        if not isinstance(v, (int, float)) or v < 0:
            raise ValueError(f"Peso 'weights.{k}' invalido ({v!r}). Debe ser >= 0.")

    # --- structural attributes -------------------------------------------
    attrs_raw = raw.get("structural", {}).get("attributes", [])
    if not isinstance(attrs_raw, list) or not attrs_raw:
        raise ValueError(
            "Seccion 'structural.attributes' vacia o invalida en el YAML."
        )
    attrs: list[StructuralAttribute] = []
    for a in attrs_raw:
        if not all(k in a for k in ("name", "type", "weight")):
            raise ValueError(f"Atributo estructural mal formado: {a!r}")
        if a["type"] not in {"categorical", "boolean"}:
            raise ValueError(
                f"Tipo de atributo no soportado: {a['type']!r}. "
                f"Solo 'categorical' o 'boolean' por ahora."
            )
        attrs.append(StructuralAttribute(
            name=str(a["name"]),
            type=str(a["type"]),
            weight=float(a["weight"]),
        ))

    # --- embeddings -------------------------------------------------------
    emb = raw.get("embeddings", {})
    if "model_name" not in emb or "dim" not in emb or "text_template" not in emb:
        raise ValueError(
            "Seccion 'embeddings' debe tener model_name, dim y text_template."
        )

    return SimilarityConfig(
        weights={k: float(v) for k, v in w.items()},
        threshold_default=float(raw.get("threshold_default", 0.6)),
        top_k_default=int(raw.get("top_k_default", 10)),
        embedding_model_name=str(emb["model_name"]),
        embedding_dim=int(emb["dim"]),
        text_template=str(emb["text_template"]),
        structural_attributes=tuple(attrs),
        behavioral_available=bool(raw.get("behavioral", {}).get("available", False)),
        trend_available=bool(raw.get("trend", {}).get("available", False)),
    )
