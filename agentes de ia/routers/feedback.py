"""Router dedicado de feedback."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from schemas.preferencias import FeedbackSignal, PerfilOperador
from services.runtime import runtime

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackPayload(BaseModel):
    recomendacion_id: str
    operador_id: str
    accion: str
    cambios: dict | None = None
    razones_texto: str | None = None


@router.post("", response_model=PerfilOperador)
async def post_feedback(payload: FeedbackPayload) -> PerfilOperador:
    """Registra feedback y retorna perfil actualizado."""
    signal = FeedbackSignal(
        feedback_id=f"FDB_{uuid.uuid4().hex[:8].upper()}",
        recomendacion_id=payload.recomendacion_id,
        operador_id=payload.operador_id,
        accion=payload.accion,
        cambios=payload.cambios,
        razones_texto=payload.razones_texto,
        timestamp=datetime.now(timezone.utc),
    )
    return runtime.preference_service.registrar_feedback(signal)
