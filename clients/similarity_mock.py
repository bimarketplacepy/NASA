"""SimilarityEngineMock: cae cuando el SimilarityEngine real (Bloque 5)
no esta disponible.

Mateo lo importa en trends_service.py como fallback. El motor real
requiere precompute de embeddings (4643 productos) y Neo4j corriendo;
en escenarios de test offline, este mock devuelve resultados
deterministicos basados en match lexico TF-IDF crudo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clients.data_loader import DataLoader


@dataclass(frozen=True)
class SimilaridadResult:
    """Resultado de buscar similares: subset de SimilarityResult del Bloque 5."""

    sku: str
    score: float
    nombre: str = ""
    categoria: str = ""
    precio: float = 0.0


class SimilarityEngineMock:
    """Match lexico crudo: token overlap normalizado.

    Para cada producto del catalogo, cuenta tokens compartidos con la
    descripcion del trend (lowercase, sin puntuacion). Score =
    overlap / max(len(texto_tokens), len(prod_tokens)).
    """

    def __init__(
        self,
        data_loader: DataLoader | None = None,
    ) -> None:
        self.data_loader = data_loader or DataLoader()

    async def encontrar_similares(
        self,
        texto: str,
        keywords: list[str] | None = None,
        k: int = 10,
        umbral: float = 0.0,
        incluir_desglose: bool = False,
    ) -> list[SimilaridadResult]:
        """Devuelve top-k productos del catalogo por overlap lexico."""
        productos = self.data_loader.load_productos()
        if not productos:
            return []

        text_tokens = set(self._tokenize(texto))
        if keywords:
            text_tokens.update(t.lower() for t in keywords)
        if not text_tokens:
            return []

        scored: list[SimilaridadResult] = []
        for sku, p in productos.items():
            prod_text = f"{p.nombre} {p.nombre_corto} {p.categoria_id}".lower()
            prod_tokens = set(self._tokenize(prod_text))
            if not prod_tokens:
                continue
            overlap = len(text_tokens & prod_tokens)
            denom = max(len(text_tokens), len(prod_tokens))
            score = overlap / denom if denom > 0 else 0.0
            if score < umbral:
                continue
            scored.append(
                SimilaridadResult(
                    sku=sku,
                    score=score,
                    nombre=p.nombre,
                    categoria=p.categoria_id,
                    precio=p.precio_referencia,
                )
            )

        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:k]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        import re
        import string

        cleaned = re.sub(rf"[{re.escape(string.punctuation)}]", " ", text.lower())
        return [t for t in cleaned.split() if len(t) > 2]
