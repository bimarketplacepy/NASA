"""Contenedor runtime simple para wiring de endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid

from clients.data_loader import get_data_loader
from schemas.chat import ChatMessage, SesionChat
from schemas.preferencias import PerfilOperador
from schemas.recomendaciones import Recomendacion
from schemas.simulacion import ForecastResult
from services.causal_graph.graph_service import CausalGraphService
from services.contrafactual.reoptimizer import ContrafactualService
from services.critic.critic_service import CriticService
from services.forecast.forecast_service import ForecastService
from services.negotiator.negotiator_service import NegotiatorService
from services.optimizer.optimizer_service import OptimizerService
from services.preference_learning.preference_service import PreferenceService


@dataclass
class RuntimeContainer:
    """Instancias singleton de servicios del backend."""

    data_loader = get_data_loader()
    forecast_service: ForecastService = field(default_factory=lambda: ForecastService(get_data_loader()))
    optimizer_service: OptimizerService = field(default_factory=lambda: OptimizerService(get_data_loader()))
    critic_service: CriticService = field(default_factory=CriticService)
    preference_service: PreferenceService = field(default_factory=PreferenceService)
    graph_service: CausalGraphService = field(default_factory=CausalGraphService)
    negotiator_service: NegotiatorService = field(default_factory=NegotiatorService)
    contrafactual_service: ContrafactualService = field(
        default_factory=lambda: ContrafactualService(OptimizerService(get_data_loader()))
    )
    last_recomendacion: Recomendacion | None = None
    last_forecasts: dict[str, ForecastResult] = field(default_factory=dict)
    sesiones_chat: dict[str, SesionChat] = field(default_factory=dict)
    traces_by_recommendation: dict[str, list[dict]] = field(default_factory=dict)

    def perfil_demo(self) -> PerfilOperador:
        return PerfilOperador(
            operador_id="operador_demo",
            aversion_stockout=0.75,
            aversion_capital_inmovilizado=0.4,
            sensibilidad_precio=0.6,
            sensibilidad_lead_time=0.5,
            sensibilidad_calidad=0.5,
            preferencia_proveedor_conocido=0.3,
            tolerancia_riesgo=0.5,
            horizonte_planeacion_preferido_semanas=8,
            historial_feedback=[],
            version=1,
            confianza_perfil=0.2,
        )


runtime = RuntimeContainer()


def create_or_append_chat_message(
    sesion_id: str,
    operador_id: str,
    role: str,
    content: str,
    objetos_adjuntos: dict | None = None,
) -> SesionChat:
    """Agrega mensaje a sesion y devuelve sesion actualizada."""
    sesion = runtime.sesiones_chat.get(
        sesion_id,
        SesionChat(sesion_id=sesion_id, operador_id=operador_id, mensajes=[], contexto_activo={}),
    )
    msg = ChatMessage(
        mensaje_id=f"MSG_{uuid.uuid4().hex[:10].upper()}",
        sesion_id=sesion_id,
        role=role,
        content=content,
        agent_traces=None,
        objetos_adjuntos=objetos_adjuntos,
        timestamp=datetime.now(timezone.utc),
    )
    sesion.mensajes.append(msg)
    runtime.sesiones_chat[sesion_id] = sesion
    return sesion
