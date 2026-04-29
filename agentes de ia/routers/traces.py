"""Router de trazas de recomendacion."""

from fastapi import APIRouter, HTTPException

from services.runtime import runtime

router = APIRouter(prefix="/traces", tags=["traces"])


@router.get("/{recomendacion_id}")
async def get_traces(recomendacion_id: str) -> dict:
    """Retorna trazas asociadas a una recomendacion."""
    traces = runtime.traces_by_recommendation.get(recomendacion_id)
    if traces is None:
        raise HTTPException(status_code=404, detail={"error_code": "TRACES_NOT_FOUND"})
    return {"recomendacion_id": recomendacion_id, "traces": traces}
