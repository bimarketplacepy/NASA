"""Orquestador conversacional inicial."""

from __future__ import annotations

from datetime import datetime, timezone

from agents.intent_classifier import IntentClassifier
from agents.state import SharedAgentState
from schemas.agentes import AgentTrace, ToolCall
from services.contrafactual.nl_parser import parse_perturbacion
from services.runtime import runtime


class AgentOrchestrator:
    """Resuelve intenciones de usuario sobre servicios backend."""

    def __init__(self) -> None:
        self.intent_classifier = IntentClassifier()

    def run(self, mensaje_usuario: str, operador_id: str) -> SharedAgentState:
        """Procesa mensaje y retorna estado final con respuesta."""
        state = SharedAgentState(
            mensaje_usuario=mensaje_usuario,
            perfil_operador=runtime.perfil_demo().model_copy(update={"operador_id": operador_id}),
            recomendacion_actual=runtime.last_recomendacion,
        )
        state.intent = self.intent_classifier.classify(mensaje_usuario)

        if state.intent.intent == "SALUDO":
            state.respuesta_final = "Hola, puedo ayudarte a generar recomendaciones y simular escenarios."
            state.traces.append(self._trace("fallback_agent", "saludo", "respuesta saludo"))
            return state

        if state.intent.intent == "SOLICITAR_RECOMENDACION":
            evento = runtime.data_loader.load_eventos()[0]
            skus = list(runtime.data_loader.load_productos().keys())[:8]
            forecasts = {s: runtime.forecast_service.forecast(s, 1, 180) for s in skus}
            rec = runtime.optimizer_service.optimizar(
                skus_objetivo=skus,
                forecasts=forecasts,
                evento=evento,
                perfil=state.perfil_operador,
                presupuesto=50000.0,
                metodo="dispatcher",
            )
            rec = rec.model_copy(update={"vulnerabilidades": runtime.critic_service.atacar(rec)})
            runtime.last_recomendacion = rec
            runtime.last_forecasts = forecasts
            runtime.graph_service.construir(rec)
            runtime.traces_by_recommendation[rec.recomendacion_id] = [
                {"agent": "orchestrator", "summary": "Intent SOLICITAR_RECOMENDACION"}
            ]
            state.recomendacion_actual = rec
            state.respuesta_final = f"Recomendacion generada: {rec.recomendacion_id}"
            state.traces.append(self._trace("optimizer_agent", "generar recomendacion", "recomendacion generada"))
            return state

        if state.intent.intent == "CONTRAFACTUAL":
            if runtime.last_recomendacion is None:
                state.respuesta_final = "Necesito una recomendacion base para correr el contrafactual."
                state.traces.append(self._trace("contrafactual_agent", "sin base", "respuesta sin base"))
                return state
            pert = parse_perturbacion(mensaje_usuario)
            esc = runtime.contrafactual_service.reoptimizar(
                rec_base=runtime.last_recomendacion,
                perturbacion=pert,
                forecasts_base=runtime.last_forecasts,
                perfil=state.perfil_operador,
            )
            state.escenario_contrafactual = esc
            state.respuesta_final = f"Escenario generado: {esc.escenario_id}"
            state.traces.append(self._trace("contrafactual_agent", "simular", "escenario generado"))
            return state

        if state.intent.intent == "CONSULTAR_TENDENCIAS":
            state.respuesta_final = (
                "Detecte tendencias candidatas: Proyector Aurora LED y Mini Aldea Nevada."
            )
            state.traces.append(self._trace("trends_agent", "consultar tendencias", "respuesta tendencias"))
            return state

        if state.intent.intent == "EXPLICAR_DECISION":
            rec = runtime.last_recomendacion
            if rec is None:
                state.respuesta_final = "Todavia no hay recomendacion para explicar."
            else:
                state.respuesta_final = (
                    f"La recomendacion {rec.recomendacion_id} prioriza factibilidad, costo y riesgo (VaR95)."
                )
            state.traces.append(self._trace("response_formatter", "explicar", "explicacion emitida"))
            return state

        state.respuesta_final = "No entendi la solicitud. Puedo generar recomendacion o simular un que-pasa-si."
        state.traces.append(self._trace("fallback_agent", "otro", "respuesta fallback"))
        return state

    def _trace(self, agent_name: str, input_summary: str, output_summary: str) -> AgentTrace:
        now = datetime.now(timezone.utc)
        tool_call = ToolCall(
            tool_name="runtime_service_call",
            arguments={"agent": agent_name},
            result={"ok": True},
            error=None,
            duration_ms=1.0,
            timestamp=now,
        )
        return AgentTrace(
            agent_name=agent_name,
            input_summary=input_summary,
            output_summary=output_summary,
            tool_calls=[tool_call],
            reasoning=None,
            duration_ms=1.0,
        )
