"""Tests para critic service."""

from __future__ import annotations

from clients.data_loader import get_data_loader
from schemas.preferencias import PerfilOperador
from services.critic.critic_service import CriticService
from services.forecast.forecast_service import ForecastService
from services.optimizer.optimizer_service import OptimizerService


def test_critic_returns_vulnerabilities() -> None:
    loader = get_data_loader()
    fs = ForecastService(loader)
    os = OptimizerService(loader)
    perfil = PerfilOperador(
        operador_id="operador_demo",
        aversion_stockout=0.8,
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
    skus = list(loader.load_productos().keys())[:5]
    forecasts = {s: fs.forecast(s, 1, 120, 3) for s in skus}
    rec = os.optimizar(skus, forecasts, loader.load_eventos()[0], perfil, presupuesto=60000.0)
    vulns = CriticService().atacar(rec)
    assert isinstance(vulns, list)
    assert all(v.impacto_usd_p95 >= v.impacto_usd_esperado for v in vulns)
