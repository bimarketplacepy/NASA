"""Schemas de chat conversacional."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from schemas.agentes import AgentTrace


class ChatMessage(BaseModel):
    """Mensaje de sesion de chat."""

    mensaje_id: str
    sesion_id: str
    role: Literal["user", "assistant", "tool", "system"]
    content: str
    agent_traces: list[AgentTrace] | None = None
    objetos_adjuntos: dict | None = None
    timestamp: datetime


class SesionChat(BaseModel):
    """Contenedor de la conversacion."""

    sesion_id: str
    operador_id: str
    mensajes: list[ChatMessage] = Field(default_factory=list)
    contexto_activo: dict = Field(default_factory=dict)
