"""Tests para preference learning."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from schemas.preferencias import FeedbackSignal
from services.preference_learning.preference_service import PreferenceService


def test_registrar_feedback_updates_profile() -> None:
    service = PreferenceService()
    signal = FeedbackSignal(
        feedback_id=f"FDB_{uuid.uuid4().hex[:8].upper()}",
        recomendacion_id="REC_TEST_001",
        operador_id="operador_demo",
        accion="MODIFICAR",
        cambios={"motivo": "proveedor_mas_rapido"},
        razones_texto="Prefiero lead time bajo.",
        timestamp=datetime.now(timezone.utc),
    )
    perfil = service.registrar_feedback(signal)
    assert perfil.operador_id == "operador_demo"
    assert perfil.version >= 2
    assert signal.feedback_id in perfil.historial_feedback
