"""Schemas de trazas y clasificacion de intencion."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """Invocacion de tool dentro de un agente."""

    tool_name: str
    arguments: dict = Field(default_factory=dict)
    result: dict | None = None
    error: str | None = None
    duration_ms: float
    timestamp: datetime


class AgentTrace(BaseModel):
    """Trazabilidad de ejecucion de un agente."""

    agent_name: str
    input_summary: str
    output_summary: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    reasoning: str | None = None
    duration_ms: float


class IntentClassification(BaseModel):
    """Resultado del clasificador de intencion."""

    intent: Literal[
        "CONSULTA_PRODUCTO",
        "SOLICITAR_RECOMENDACION",
        "CONTRAFACTUAL",
        "APROBAR_RECOMENDACION",
        "MODIFICAR_RECOMENDACION",
        "RECHAZAR_RECOMENDACION",
        "PEDIR_BORRADOR_NEGOCIACION",
        "INVESTIGAR_NUEVO",
        "CONSULTAR_TENDENCIAS",
        "EXPLICAR_DECISION",
        "SALUDO",
        "OTRO",
    ]
    confianza: float
    entidades_extraidas: dict = Field(default_factory=dict)
    requiere_confirmacion: bool
