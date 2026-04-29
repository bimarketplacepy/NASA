"""engine.py - SimilarityEngine: scorers + composite.

Tarea 1 v2 - Bloque 5 - Stage 3.

Esta clase NO computa embeddings ni Gower-matrix masivamente: para eso
estan ``embeddings.py`` (precompute one-shot) y ``precompute.py`` (matriz
top-K). ``SimilarityEngine`` opera par-a-par usando los artefactos
ya persistidos.

Construccion conveniente desde disco:
    eng = SimilarityEngine.from_disk()
    res = eng.composite_score("247329", "215773")
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import numpy as np

from ontology_semantic.similarity.config import (
    SimilarityConfig,
    load_config,
)
from ontology_semantic.similarity.types import (
    BehavioralFlag,
    SimilarityResult,
)


EmbedFn = Callable[[str], np.ndarray]


class SimilarityEngine:
    """Motor par-a-par que combina lexical + structural + behavioral + trend."""

    def __init__(
        self,
        cfg: SimilarityConfig,
        embeddings: Optional[np.ndarray] = None,
        sku_to_row: Optional[dict[str, int]] = None,
        attrs_by_sku: Optional[dict[str, dict[str, object]]] = None,
        monthly_sales_by_sku: Optional[dict[str, np.ndarray]] = None,
        trend_signal_text: Optional[str] = None,
        embed_fn: Optional[EmbedFn] = None,
    ) -> None:
        self.cfg = cfg
        self.embeddings = embeddings
        self.sku_to_row = sku_to_row or {}
        self.attrs_by_sku = attrs_by_sku or {}
        self.monthly_sales_by_sku = monthly_sales_by_sku or {}
        self.trend_signal_text = (trend_signal_text or "").strip()
        self._embed_fn = embed_fn
        self._text_emb_cache: dict[str, np.ndarray] = {}

    @classmethod
    def from_disk(
        cls,
        cfg: Optional[SimilarityConfig] = None,
        npy_path: Optional[Path] = None,
        index_path: Optional[Path] = None,
        trend_signal_text: Optional[str] = None,
    ) -> "SimilarityEngine":
        """Carga embeddings + atributos persistidos y devuelve un engine listo."""
        from ontology_semantic.similarity.embeddings import (
            EMBEDDINGS_INDEX,
            EMBEDDINGS_NPY,
            load_embeddings,
        )

        if cfg is None:
            cfg = load_config()
        if npy_path is None:
            npy_path = EMBEDDINGS_NPY
        if index_path is None:
            index_path = EMBEDDINGS_INDEX

        matrix, _, sku_to_row, productos, _ = load_embeddings(npy_path, index_path)
        attrs_by_sku = {p["sku"]: p["attrs"] for p in productos}
        return cls(
            cfg=cfg,
            embeddings=matrix,
            sku_to_row=sku_to_row,
            attrs_by_sku=attrs_by_sku,
            trend_signal_text=trend_signal_text,
        )

    def _ensure_embed_fn(self) -> EmbedFn:
        """Devuelve la funcion de embedding, cargando el modelo si hace falta."""
        if self._embed_fn is None:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(self.cfg.embedding_model_name)
            expected_dim = self.cfg.embedding_dim

            def _fn(text: str) -> np.ndarray:
                v = model.encode(
                    [text],
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )[0]
                v = v.astype(np.float32)
                if v.shape[0] != expected_dim:
                    raise RuntimeError(
                        f"embed_fn devolvio dim={v.shape[0]}, "
                        f"esperaba {expected_dim}"
                    )
                return v

            self._embed_fn = _fn
        return self._embed_fn

    def embed_text(self, text: str) -> np.ndarray:
        """Embeddea un texto arbitrario con el mismo modelo del catalogo."""
        key = text.strip()
        if key in self._text_emb_cache:
            return self._text_emb_cache[key]
        fn = self._ensure_embed_fn()
        v = fn(key)
        self._text_emb_cache[key] = v
        return v

    def score_lexical(self, sku_a: str, sku_b: str) -> float:
        """Cosine sobre embeddings de texto entre dos SKUs."""
        if sku_a == sku_b:
            return 1.0
        if self.embeddings is None:
            raise RuntimeError(
                "score_lexical: la matriz de embeddings no fue inyectada."
            )
        if sku_a not in self.sku_to_row:
            raise KeyError(f"SKU {sku_a!r} no esta en sku_to_row")
        if sku_b not in self.sku_to_row:
            raise KeyError(f"SKU {sku_b!r} no esta en sku_to_row")

        ra = self.sku_to_row[sku_a]
        rb = self.sku_to_row[sku_b]
        val = float(np.dot(self.embeddings[ra], self.embeddings[rb]))
        return float(np.clip(val, 0.0, 1.0))

    def score_structural(self, sku_a: str, sku_b: str) -> float:
        """Distancia de Gower invertida sobre atributos categoricos."""
        if sku_a == sku_b:
            return 1.0

        a = self.attrs_by_sku.get(sku_a)
        b = self.attrs_by_sku.get(sku_b)
        if not a or not b:
            return 0.0

        sum_w = 0.0
        sum_match = 0.0
        for attr in self.cfg.structural_attributes:
            va = a.get(attr.name)
            vb = b.get(attr.name)
            if va is None or vb is None or va == "" or vb == "":
                continue
            match = 1.0 if va == vb else 0.0
            sum_match += match * attr.weight
            sum_w += attr.weight

        if sum_w == 0.0:
            return 0.0
        return sum_match / sum_w

    def score_behavioral(
        self,
        sku_a: str,
        sku_b: str,
    ) -> tuple[float, BehavioralFlag]:
        """Cosine sobre vector de ventas mensuales."""
        if not self.cfg.behavioral_available:
            return 0.0, BehavioralFlag.UNAVAILABLE_GLOBAL

        sa = self.monthly_sales_by_sku.get(sku_a)
        sb = self.monthly_sales_by_sku.get(sku_b)
        a_missing = sa is None or len(sa) == 0
        b_missing = sb is None or len(sb) == 0
        if a_missing and b_missing:
            return 0.0, BehavioralFlag.MISSING_BOTH
        if a_missing:
            return 0.0, BehavioralFlag.MISSING_A
        if b_missing:
            return 0.0, BehavioralFlag.MISSING_B

        sa = np.asarray(sa, dtype=np.float32)
        sb = np.asarray(sb, dtype=np.float32)
        na = float(np.linalg.norm(sa))
        nb = float(np.linalg.norm(sb))
        if na == 0 and nb == 0:
            return 0.0, BehavioralFlag.MISSING_BOTH
        if na == 0:
            return 0.0, BehavioralFlag.MISSING_A
        if nb == 0:
            return 0.0, BehavioralFlag.MISSING_B

        val = float(np.dot(sa, sb) / (na * nb))
        return float(np.clip(val, 0.0, 1.0)), BehavioralFlag.AVAILABLE

    def score_trend(
        self,
        sku: str,
        trend_signal: Optional[str] = None,
    ) -> float:
        """Similitud lexica entre la descripcion del SKU y un trend signal."""
        text = (trend_signal if trend_signal is not None
                else self.trend_signal_text)
        if not text or not text.strip():
            return 0.0
        if self.embeddings is None or sku not in self.sku_to_row:
            return 0.0

        sku_emb = self.embeddings[self.sku_to_row[sku]]
        trend_emb = self.embed_text(text)
        val = float(np.dot(sku_emb, trend_emb))
        return float(np.clip(val, 0.0, 1.0))

    def _trend_disponible(self) -> bool:
        return bool(self.trend_signal_text and self.trend_signal_text.strip())

    def _structural_disponible(self, sku_a: str, sku_b: str) -> bool:
        return (sku_a in self.attrs_by_sku
                and sku_b in self.attrs_by_sku
                and bool(self.attrs_by_sku[sku_a])
                and bool(self.attrs_by_sku[sku_b]))

    def composite_score(
        self,
        sku_a: str,
        sku_b: str,
        weights_override: Optional[dict[str, float]] = None,
    ) -> SimilarityResult:
        """Combina los 4 scorers en un score ponderado renormalizado."""
        if sku_a == sku_b:
            return SimilarityResult(
                sku_a=sku_a, sku_b=sku_b,
                score_lexical=1.0, score_structural=1.0,
                score_behavioral=1.0, score_trend=1.0,
                score_total=1.0, confidence=1.0,
                behavioral_flag=BehavioralFlag.AVAILABLE,
                flags=("identity",),
            )

        weights = dict(self.cfg.weights)
        if weights_override:
            for k, v in weights_override.items():
                if k not in weights:
                    raise ValueError(
                        f"weights_override contiene clave desconocida: {k!r}."
                    )
                if v < 0:
                    raise ValueError(
                        f"weights_override[{k!r}]={v} debe ser >= 0"
                    )
                weights[k] = float(v)

        s_lex = self.score_lexical(sku_a, sku_b)
        s_str = self.score_structural(sku_a, sku_b)
        s_beh, beh_flag = self.score_behavioral(sku_a, sku_b)
        s_trd = self.score_trend(sku_a)

        flags: list[str] = []
        disponibles: dict[str, float] = {"lexical": weights["lexical"]}

        if self._structural_disponible(sku_a, sku_b):
            disponibles["structural"] = weights["structural"]
        else:
            flags.append("structural_missing")

        if beh_flag == BehavioralFlag.AVAILABLE:
            disponibles["behavioral"] = weights["behavioral"]
        else:
            flags.append(f"behavioral_{beh_flag.value}")

        if self._trend_disponible():
            disponibles["trend"] = weights["trend"]
        else:
            flags.append("trend_no_signal")

        confidence = float(sum(disponibles.values()))
        confidence_clip = float(np.clip(confidence, 0.0, 1.0))

        if confidence > 0:
            eff = {k: v / confidence for k, v in disponibles.items()}
        else:
            eff = {}

        score_total = (
            eff.get("lexical", 0.0) * s_lex
            + eff.get("structural", 0.0) * s_str
            + eff.get("behavioral", 0.0) * s_beh
            + eff.get("trend", 0.0) * s_trd
        )
        score_total = float(np.clip(score_total, 0.0, 1.0))

        return SimilarityResult(
            sku_a=sku_a, sku_b=sku_b,
            score_lexical=float(s_lex),
            score_structural=float(s_str),
            score_behavioral=float(s_beh),
            score_trend=float(s_trd),
            score_total=score_total,
            confidence=confidence_clip,
            behavioral_flag=beh_flag,
            flags=tuple(flags),
        )
