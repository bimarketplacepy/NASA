"""Tests para servicio de grafo causal."""

from __future__ import annotations

from clients.data_loader import get_data_loader
from schemas.preferencias import PerfilOperador
from services.causal_graph.graph_service import CausalGraphService
from services.forecast.forecast_service import ForecastService
from services.optimizer.optimizer_service import OptimizerService


def test_build_and_load_graph() -> None:
    loader = get_data_loader()
    fs = ForecastService(loader)
    os = OptimizerService(loader)
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
    skus = list(loader.load_productos().keys())[:3]
    forecasts = {s: fs.forecast(s, 1, 100, 9) for s in skus}
    rec = os.optimizar(skus, forecasts, loader.load_eventos()[0], perfil, presupuesto=28000.0)

    service = CausalGraphService()
    graph = service.construir(rec)
    loaded = service.cargar_por_recomendacion_id(rec.recomendacion_id)

    assert graph.recomendacion_id == rec.recomendacion_id
    assert loaded is not None
    assert len(loaded.nodos) >= 1
