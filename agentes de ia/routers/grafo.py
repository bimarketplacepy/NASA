"""Router de grafos causales."""

from fastapi import APIRouter, HTTPException

from schemas.grafo_causal import GrafoCausal
from services.runtime import runtime

router = APIRouter(prefix="/grafo", tags=["grafo"])


@router.get("/causal/{recomendacion_id}", response_model=GrafoCausal)
async def get_grafo_causal(recomendacion_id: str) -> GrafoCausal:
    """Recupera grafo causal de una recomendacion."""
    graph = runtime.graph_service.cargar_por_recomendacion_id(recomendacion_id)
    if graph is None:
        raise HTTPException(status_code=404, detail={"error_code": "GRAFO_NOT_FOUND", "recomendacion_id": recomendacion_id})
    return graph
