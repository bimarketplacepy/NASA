"""Tests del orquestador de agentes."""

from __future__ import annotations

from agents.orchestrator import AgentOrchestrator


def test_orchestrator_generates_recommendation() -> None:
    orch = AgentOrchestrator()
    state = orch.run("genera recomendacion para black friday", "operador_demo")
    assert state.intent is not None
    assert state.intent.intent == "SOLICITAR_RECOMENDACION"
    assert state.recomendacion_actual is not None
    assert "Recomendacion generada" in (state.respuesta_final or "")


def test_orchestrator_handles_greeting() -> None:
    orch = AgentOrchestrator()
    state = orch.run("hola", "operador_demo")
    assert state.intent is not None
    assert state.intent.intent == "SALUDO"
    assert state.respuesta_final is not None
