"""Schemas de perfil y feedback del operador."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class FeedbackSignal(BaseModel):
    """Evento de feedback del operador."""

    feedback_id: str
    recomendacion_id: str
    operador_id: str
    accion: Literal["APROBAR", "MODIFICAR", "RECHAZAR", "POSTERGAR", "DELEGAR"]
    cambios: dict | None = None
    razones_texto: str | None = None
    timestamp: datetime


class PerfilOperador(BaseModel):
    """Preferencias aprendidas del operador."""

    operador_id: str
    aversion_stockout: float
    aversion_capital_inmovilizado: float
    sensibilidad_precio: float
    sensibilidad_lead_time: float
    sensibilidad_calidad: float
    preferencia_proveedor_conocido: float
    tolerancia_riesgo: float
    horizonte_planeacion_preferido_semanas: int
    historial_feedback: list[str]
    version: int
    confianza_perfil: float
