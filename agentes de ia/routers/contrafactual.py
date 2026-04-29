"""Router de escenarios contrafactuales."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from schemas.contrafactual import EscenarioContrafactual
from services.contrafactual.nl_parser import parse_perturbacion
from services.runtime import runtime

router = APIRouter(prefix="/contrafactual", tags=["contrafactual"])


class ContrafactualNLRequest(BaseModel):
    """Payload NL para contrafactual."""

    perturbacion_descripcion_natural: str


@router.post("/natural-language", response_model=EscenarioContrafactual)
async def contrafactual_nl(payload: ContrafactualNLRequest) -> EscenarioContrafactual:
    """Construye escenario alternativo desde texto."""
    if runtime.last_recomendacion is None:
        raise HTTPException(status_code=400, detail={"error_code": "NO_BASE_RECOMMENDATION"})
    pert = parse_perturbacion(payload.perturbacion_descripcion_natural)
    escenario = runtime.contrafactual_service.reoptimizar(
        rec_base=runtime.last_recomendacion,
        perturbacion=pert,
        forecasts_base=runtime.last_forecasts,
        perfil=runtime.perfil_demo(),
    )
    return escenario
