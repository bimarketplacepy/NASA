"""Servicio para generar y recuperar grafos causales."""

from __future__ import annotations

from pathlib import Path
import json

from schemas.grafo_causal import GrafoCausal
from schemas.recomendaciones import Recomendacion
from services.causal_graph.graph_builder import build_graph_from_recommendation


GRAPH_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "recomendaciones"


class CausalGraphService:
    """Orquesta construccion y cache de grafo causal."""

    def construir(self, rec: Recomendacion) -> GrafoCausal:
        graph = build_graph_from_recommendation(rec)
        self._save_graph(graph)
        return graph

    def cargar_por_recomendacion_id(self, recomendacion_id: str) -> GrafoCausal | None:
        path = GRAPH_CACHE_DIR / f"GRAFO_{recomendacion_id}.json"
        if not path.exists():
            return None
        return GrafoCausal(**json.loads(path.read_text(encoding="utf-8")))

    def _save_graph(self, graph: GrafoCausal) -> None:
        GRAPH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = GRAPH_CACHE_DIR / f"{graph.grafo_id}.json"
        path.write_text(json.dumps(graph.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
