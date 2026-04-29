"""Tests del optimizador robusto afin."""

from __future__ import annotations

from clients.data_loader import get_data_loader
from schemas.preferencias import PerfilOperador
from services.forecast.forecast_service import ForecastService
from services.optimizer.optimizer_service import OptimizerService


def test_optimizer_robust_affine_generates_recommendation() -> None:
    loader = get_data_loader()
    fs = ForecastService(loader)
    os = OptimizerService(loader)

    skus = list(loader.load_productos().keys())[:4]
    forecasts = {sku: fs.forecast(sku, semanas_adelante=1, n_samples=150, seed=4) for sku in skus}
    perfil = PerfilOperador(
        operador_id="operador_demo",
        aversion_stockout=0.7,
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
    rec = os.optimizar(
        skus_objetivo=skus,
        forecasts=forecasts,
        evento=loader.load_eventos()[0],
        perfil=perfil,
        presupuesto=60000.0,
        metodo="robust_affine",
    )
    assert rec.items
    assert rec.metricas.costo_total > 0
    assert rec.justificacion_texto
