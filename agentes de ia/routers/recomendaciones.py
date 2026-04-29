"""Router de recomendaciones."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from schemas.recomendaciones import Recomendacion
from services.runtime import runtime

router = APIRouter(prefix="/recomendaciones", tags=["recomendaciones"])


class GenerarRecomendacionRequest(BaseModel):
    """Payload para generar recomendacion."""

    evento_id: str
    semanas_hasta_evento: int = 1
    presupuesto: float | None = None
    skus_objetivo: list[str] | None = None


@router.post("/generar", response_model=Recomendacion)
async def generar_recomendacion(payload: GenerarRecomendacionRequest) -> Recomendacion:
    """Genera recomendacion desde forecasts + optimizador."""
    skus = payload.skus_objetivo or list(runtime.data_loader.load_productos().keys())[:8]
    forecasts = {
        sku: runtime.forecast_service.forecast(sku, semanas_adelante=payload.semanas_hasta_evento, n_samples=200)
        for sku in skus
    }
    evento = next((e for e in runtime.data_loader.load_eventos() if e.evento_id == payload.evento_id), None)
    if evento is None:
        raise HTTPException(status_code=404, detail={"error_code": "EVENTO_NOT_FOUND", "evento_id": payload.evento_id})

    perfil = runtime.perfil_demo()
    rec = runtime.optimizer_service.optimizar(
        skus_objetivo=skus,
        forecasts=forecasts,
        evento=evento,
        perfil=perfil,
        presupuesto=payload.presupuesto,
        metodo="dispatcher",
    )
    rec = rec.model_copy(update={"vulnerabilidades": runtime.critic_service.atacar(rec)})
    runtime.last_recomendacion = rec
    runtime.last_forecasts = forecasts
    runtime.graph_service.construir(rec)
    runtime.traces_by_recommendation[rec.recomendacion_id] = [
        {
            "agent": "optimizer_service",
            "summary": "Generacion de recomendacion con heuristica + montecarlo + critic",
        }
    ]
    return rec


@router.get("/{recomendacion_id}", response_model=Recomendacion)
async def get_recomendacion(recomendacion_id: str) -> Recomendacion:
    """Recupera ultima recomendacion en memoria o cache."""
    if runtime.last_recomendacion and runtime.last_recomendacion.recomendacion_id == recomendacion_id:
        return runtime.last_recomendacion
    raise HTTPException(status_code=404, detail={"error_code": "RECOMENDACION_NOT_FOUND", "id": recomendacion_id})
