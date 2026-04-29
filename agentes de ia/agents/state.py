"""Estado compartido de la orquestacion conversacional."""

from __future__ import annotations

from dataclasses import dataclass, field

from schemas.agentes import AgentTrace, IntentClassification
from schemas.contrafactual import EscenarioContrafactual
from schemas.preferencias import PerfilOperador
from schemas.recomendaciones import Recomendacion


@dataclass
class SharedAgentState:
    """Estado de ejecucion para un turno conversacional."""

    mensaje_usuario: str
    intent: IntentClassification | None = None
    contexto_sesion: dict = field(default_factory=dict)
    perfil_operador: PerfilOperador | None = None
    recomendacion_actual: Recomendacion | None = None
    escenario_contrafactual: EscenarioContrafactual | None = None
    traces: list[AgentTrace] = field(default_factory=list)
    respuesta_final: str | None = None
