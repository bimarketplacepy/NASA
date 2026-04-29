"""Router de chat conversacional."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.orchestrator import AgentOrchestrator
from schemas.chat import SesionChat
from services.runtime import create_or_append_chat_message, runtime

router = APIRouter(prefix="/chat", tags=["chat"])
orchestrator = AgentOrchestrator()


class ChatRequest(BaseModel):
    """Payload de consulta conversacional."""

    operador_id: str
    mensaje: str
    sesion_id: str | None = None


@router.post("", response_model=SesionChat)
async def post_chat(payload: ChatRequest) -> SesionChat:
    """Recibe mensaje y ejecuta respuesta simple orientada a intents."""
    sesion_id = payload.sesion_id or f"SES_{uuid.uuid4().hex[:10].upper()}"
    create_or_append_chat_message(
        sesion_id=sesion_id,
        operador_id=payload.operador_id,
        role="user",
        content=payload.mensaje,
    )
    state = orchestrator.run(payload.mensaje, payload.operador_id)
    objetos: dict | None = None
    if state.recomendacion_actual is not None and "Recomendacion generada:" in (state.respuesta_final or ""):
        objetos = {"recomendacion_id": state.recomendacion_actual.recomendacion_id}
    if state.escenario_contrafactual is not None:
        objetos = {"escenario_id": state.escenario_contrafactual.escenario_id}

    return create_or_append_chat_message(
        sesion_id=sesion_id,
        operador_id=payload.operador_id,
        role="assistant",
        content=state.respuesta_final or "Sin respuesta",
        objetos_adjuntos=objetos,
    )


@router.get("/sesiones/{sesion_id}", response_model=SesionChat)
async def get_sesion(sesion_id: str) -> SesionChat:
    """Recupera sesion de chat."""
    sesion = runtime.sesiones_chat.get(sesion_id)
    if sesion is None:
        raise HTTPException(status_code=404, detail={"error_code": "SESION_NOT_FOUND", "sesion_id": sesion_id})
    return sesion
