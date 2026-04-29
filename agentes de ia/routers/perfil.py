"""Router de perfil de operador."""

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from schemas.preferencias import FeedbackSignal, PerfilOperador
from services.runtime import runtime

router = APIRouter(prefix="/perfil", tags=["perfil"])


@router.get("/{operador_id}", response_model=PerfilOperador)
async def get_perfil(operador_id: str) -> PerfilOperador:
    """Retorna perfil (demo en esta etapa)."""
    perfil = runtime.perfil_demo()
    return perfil.model_copy(update={"operador_id": operador_id})


class FeedbackRequest(BaseModel):
    """Payload simple de feedback."""

    recomendacion_id: str
    operador_id: str
    accion: str
    motivo: str | None = None


@router.post("/feedback", response_model=PerfilOperador)
async def post_feedback(payload: FeedbackRequest) -> PerfilOperador:
    """Registra feedback y devuelve perfil actualizado."""
    signal = FeedbackSignal(
        feedback_id=f"FDB_{uuid.uuid4().hex[:8].upper()}",
        recomendacion_id=payload.recomendacion_id,
        operador_id=payload.operador_id,
        accion=payload.accion,  # validado por schema Literal
        cambios={"motivo": payload.motivo} if payload.motivo else None,
        razones_texto=payload.motivo,
        timestamp=datetime.now(timezone.utc),
    )
    return runtime.preference_service.registrar_feedback(signal)
