"""Reglas incrementales de actualizacion de perfil."""

from __future__ import annotations

from schemas.preferencias import FeedbackSignal, PerfilOperador


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def apply_feedback_rules(perfil: PerfilOperador, signal: FeedbackSignal) -> PerfilOperador:
    """Aplica reglas deterministicas sobre perfil segun accion."""
    updates: dict = {
        "version": perfil.version + 1,
        "historial_feedback": [*perfil.historial_feedback, signal.feedback_id],
    }

    if signal.accion == "APROBAR":
        updates["confianza_perfil"] = _clamp01(perfil.confianza_perfil + 0.03)
    elif signal.accion == "RECHAZAR":
        updates["confianza_perfil"] = _clamp01(perfil.confianza_perfil - 0.06)
    elif signal.accion == "MODIFICAR":
        updates["confianza_perfil"] = _clamp01(perfil.confianza_perfil + 0.02)
        cambios = signal.cambios or {}
        motivo = str(cambios.get("motivo", "")).lower()
        if "cantidad_up" in motivo:
            updates["aversion_stockout"] = _clamp01(perfil.aversion_stockout + 0.05)
        if "cantidad_down" in motivo:
            updates["aversion_capital_inmovilizado"] = _clamp01(
                perfil.aversion_capital_inmovilizado + 0.05
            )
        if "proveedor_mas_rapido" in motivo:
            updates["sensibilidad_lead_time"] = _clamp01(perfil.sensibilidad_lead_time + 0.05)
        if "proveedor_mas_barato" in motivo:
            updates["sensibilidad_precio"] = _clamp01(perfil.sensibilidad_precio + 0.05)
        if "proveedor_mas_calidad" in motivo:
            updates["sensibilidad_calidad"] = _clamp01(perfil.sensibilidad_calidad + 0.05)

    return perfil.model_copy(update=updates)
