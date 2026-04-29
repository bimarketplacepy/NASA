"""Simula ingesta tipo stream desde corpus JSON (demo / pitch sin APIs sociales)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from loguru import logger

_DEFAULT_CORPUS = Path(__file__).resolve().parents[2] / "data" / "posts_simulados.json"


def _parse_fecha(post: dict[str, Any]) -> datetime:
    raw = str(post.get("fecha", ""))
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw)


class TrendStreamSimulator:
    """
    Entrega posts del corpus ordenados por fecha, filtrados por una ventana de tiempo
    simulada. Sustituye a llamadas en vivo a TikTok/Instagram para el hackathon.
    """

    def __init__(self, corpus_path: Path | str | None = None) -> None:
        path = Path(corpus_path) if corpus_path else _DEFAULT_CORPUS
        self.posts: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        self.posts.sort(key=_parse_fecha)
        self.tiempo_virtual: datetime = max(_parse_fecha(p) for p in self.posts) - timedelta(days=7)
        logger.info(f"TrendStreamSimulator: {len(self.posts)} posts, t0 virtual={self.tiempo_virtual.isoformat()}")

    def avanzar_tiempo(self, horas: float = 24.0) -> None:
        self.tiempo_virtual += timedelta(hours=horas)
        logger.info(f"Tiempo virtual → {self.tiempo_virtual.isoformat()}")

    def posts_en_ventana(self, ventana_horas: int = 24) -> list[dict[str, Any]]:
        """Posts con fecha en (tiempo_virtual - ventana, tiempo_virtual]."""
        inicio = self.tiempo_virtual - timedelta(hours=ventana_horas)
        out: list[dict[str, Any]] = []
        for p in self.posts:
            t = _parse_fecha(p)
            if inicio < t <= self.tiempo_virtual:
                out.append(p)
        logger.debug(f"Ventana {ventana_horas}h: {len(out)} posts")
        return out

    def simular_crecimiento_viral(self, post_id: str, factor: float = 1.5) -> None:
        for post in self.posts:
            if post.get("post_id") != post_id:
                continue
            m = post.setdefault("metricas", {})
            for k in ("views", "likes", "shares", "comments"):
                if k in m:
                    m[k] = int(float(m[k]) * factor)
            logger.info(f"Post {post_id} amplificado x{factor}")
            return
        logger.warning(f"Post no encontrado: {post_id}")
