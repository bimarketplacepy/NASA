"""Router de simulacion Monte Carlo ad-hoc."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from schemas.simulacion import ResultadoMonteCarlo
from services.runtime import runtime

router = APIRouter(prefix="/simulacion", tags=["simulacion"])


class MonteCarloRequest(BaseModel):
    n_sims: int = 2000


@router.post("/montecarlo", response_model=ResultadoMonteCarlo)
async def simular_montecarlo(payload: MonteCarloRequest) -> ResultadoMonteCarlo:
    """Corre Monte Carlo sobre la ultima recomendacion generada."""
    if runtime.last_recomendacion is None or not runtime.last_forecasts:
        raise HTTPException(status_code=400, detail={"error_code": "NO_RECOMENDACION_BASE"})
    return runtime.optimizer_service.simulator.simular(
        items=runtime.last_recomendacion.items,
        forecasts=runtime.last_forecasts,
        n_sims=payload.n_sims,
        correlaciones=None,
        seed=42,
    )
