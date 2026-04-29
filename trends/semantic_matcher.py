"""Match semántico tendencia ↔ catálogo (TF-IDF o embeddings opcionales)."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

import numpy as np
from loguru import logger
from pydantic import BaseModel, Field
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from clients.data_loader import DataLoader
from schemas.productos import Producto


def _texto_producto(p: Producto) -> str:
    tags = " ".join(p.tags)
    return f"{p.nombre} {p.descripcion or ''} {tags} {p.categoria_id}".strip()


def _token_set(texto: str) -> set[str]:
    return {t for t in re.split(r"\W+", texto.lower()) if len(t) > 2}


def _bonus_dominio_navidad(descripcion: str, p: Producto) -> float:
    """Refuerzo léxico para retail navideño del hackathon (sin LLM)."""
    d = descripcion.lower()
    b = 0.0
    if any(k in d for k in ("vela", "velas", "led", "termocrom", "luz", "lumin")):
        catu = p.categoria_id.upper()
        nom = p.nombre.lower()
        if "LUCES" in catu or "LUZ" in catu or "led" in nom or "luz" in nom or "lumin" in nom:
            b += 0.2
    if any(k in d for k in ("cerámica", "ceramica", "japones", "japonesa", "japandi", "minimal")):
        if "ORNAMENT" in p.categoria_id.upper() or "adorno" in p.nombre.lower() or "ornament" in p.categoria_id.lower():
            b += 0.2
    if any(k in d for k in ("guirnalda", "flores secas", "cottagecore", "eucalipto", "lavanda")):
        if "ARBOL" in p.categoria_id.upper() or "guirn" in p.nombre.lower():
            b += 0.2
    return min(0.35, b)


class MatchSemantico(BaseModel):
    sku_similar: str
    nombre_producto: str
    categoria: str
    score_similitud: float = Field(..., ge=0, le=1)
    justificacion: str
    razon_descarte: Optional[str] = None


class ResultadoValidacionSemantica(BaseModel):
    tendencia_id: str
    descripcion_tendencia: str
    matches_encontrados: list[MatchSemantico]
    mejor_match: Optional[MatchSemantico]
    score_promedio: float
    aprobada: bool
    umbral_aplicado: float
    razon_rechazo: Optional[str] = None


class SemanticMatcher:
    """
    Cruza la descripción de la tendencia contra el catálogo.
    Por defecto usa TF-IDF (ligero); si está instalado sentence-transformers,
    puede usarse modelo multilingüe y umbral más alto (~0.85) para el pitch de precisión.
    """

    def __init__(
        self,
        data_loader: DataLoader,
        model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
        umbral_aprobacion: float | None = None,
    ) -> None:
        self.data = data_loader
        self._st_model = None
        self._mode = "tfidf"
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._st_model = SentenceTransformer(model_name)
            self._mode = "embeddings"
            self.umbral = float(umbral_aprobacion) if umbral_aprobacion is not None else 0.85
            logger.info(f"SemanticMatcher: embeddings ({model_name}), umbral={self.umbral}")
        except Exception as e:
            self.umbral = float(umbral_aprobacion) if umbral_aprobacion is not None else 0.22
            logger.info(f"SemanticMatcher: TF-IDF (sin ST: {e!s}), umbral={self.umbral}")

        self._catalogo: dict[str, Producto] = {}
        self._skus: list[str] = []
        self._textos: list[str] = []
        self._emb_matrix: np.ndarray | None = None
        self._vectorizer: TfidfVectorizer | None = None
        self._M: np.ndarray | None = None
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._catalogo = self.data.load_productos()
        self._skus = list(self._catalogo.keys())
        self._textos = [_texto_producto(self._catalogo[sku]) for sku in self._skus]
        if self._mode == "embeddings" and self._st_model is not None:
            self._emb_matrix = np.asarray(self._st_model.encode(self._textos, convert_to_numpy=True))
            self._vectorizer = None
            self._M = None
        else:
            self._emb_matrix = None
            self._vectorizer = TfidfVectorizer(max_features=8192, ngram_range=(1, 2), min_df=1)
            self._M = self._vectorizer.fit_transform(self._textos)

    def _scores_tfidf(self, descripcion: str) -> np.ndarray:
        assert self._vectorizer is not None and self._M is not None
        q = self._vectorizer.transform([descripcion])
        cos = cosine_similarity(q, self._M)[0]
        t_tokens = _token_set(descripcion)
        bonus = np.zeros(len(self._skus))
        for i, sku in enumerate(self._skus):
            p = self._catalogo[sku]
            p_tokens = _token_set(self._textos[i])
            inter = len(t_tokens & p_tokens)
            bonus[i] = min(0.3, 0.04 * inter) + _bonus_dominio_navidad(descripcion, p)
        raw = np.clip(cos + bonus, 0.0, 1.0)
        return raw

    def _scores_embeddings(self, descripcion: str) -> np.ndarray:
        assert self._st_model is not None and self._emb_matrix is not None
        v = np.asarray(self._st_model.encode([descripcion], convert_to_numpy=True))[0]
        num = self._emb_matrix @ v
        den = np.linalg.norm(self._emb_matrix, axis=1) * (np.linalg.norm(v) + 1e-9)
        cos = np.clip(num / den, 0.0, 1.0)
        bonus = np.array([_bonus_dominio_navidad(descripcion, self._catalogo[sku]) for sku in self._skus])
        return np.clip(cos + bonus, 0.0, 1.0)

    def validar_tendencia(self, tendencia: dict[str, Any], top_k: int = 5) -> ResultadoValidacionSemantica:
        descripcion = str(tendencia.get("descripcion", "")).strip()
        tendencia_id = str(tendencia.get("tendencia_id") or f"trend_{hashlib.sha256(descripcion.encode()).hexdigest()[:10]}")
        if len(descripcion) < 10:
            return ResultadoValidacionSemantica(
                tendencia_id=tendencia_id,
                descripcion_tendencia=descripcion,
                matches_encontrados=[],
                mejor_match=None,
                score_promedio=0.0,
                aprobada=False,
                umbral_aplicado=self.umbral,
                razon_rechazo="Descripción demasiado corta",
            )

        if self._mode == "embeddings":
            scores = self._scores_embeddings(descripcion)
        else:
            scores = self._scores_tfidf(descripcion)

        order = np.argsort(-scores)[:top_k]
        matches: list[MatchSemantico] = []
        for idx in order:
            i = int(idx)
            sku = self._skus[i]
            p = self._catalogo[sku]
            s = float(scores[i])
            matches.append(
                MatchSemantico(
                    sku_similar=sku,
                    nombre_producto=p.nombre,
                    categoria=p.categoria_id,
                    score_similitud=s,
                    justificacion=f"Similitud {'coseno (embeddings)' if self._mode == 'embeddings' else 'TF-IDF + keywords'}: {s:.2%}",
                )
            )

        mejor = matches[0] if matches else None
        prom = float(np.mean([m.score_similitud for m in matches])) if matches else 0.0
        aprobada = mejor is not None and mejor.score_similitud >= self.umbral
        razon = None
        if not aprobada and mejor:
            razon = f"Mejor score {mejor.score_similitud:.2%} < umbral {self.umbral:.2%} ({self._mode})"
        elif not aprobada:
            razon = "Sin candidatos"

        return ResultadoValidacionSemantica(
            tendencia_id=tendencia_id,
            descripcion_tendencia=descripcion,
            matches_encontrados=matches,
            mejor_match=mejor,
            score_promedio=prom,
            aprobada=aprobada,
            umbral_aplicado=self.umbral,
            razon_rechazo=razon,
        )

    def validar_batch(
        self,
        tendencias: list[dict[str, Any]],
        umbral_aprobacion: float | None = None,
    ) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], str]]]:
        umbral_prev = self.umbral
        if umbral_aprobacion is not None:
            self.umbral = float(umbral_aprobacion)
        aprobadas: list[dict[str, Any]] = []
        rechazadas: list[tuple[dict[str, Any], str]] = []
        try:
            for t in tendencias:
                r = self.validar_tendencia(t)
                if r.aprobada and r.mejor_match:
                    enr = {
                        **t,
                        "productos_existentes_similares": [m.sku_similar for m in r.matches_encontrados[:5]],
                        "score_match_semantico": r.mejor_match.score_similitud,
                        "validacion_semantica": "APROBADA",
                    }
                    aprobadas.append(enr)
                else:
                    rechazadas.append((t, r.razon_rechazo or "Rechazo semántico"))
        finally:
            self.umbral = umbral_prev
        return aprobadas, rechazadas
