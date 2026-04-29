"""Tests basicos de flujo contrafactual."""

from __future__ import annotations

from clients.data_loader import get_data_loader
from schemas.preferencias import PerfilOperador
from services.contrafactual.nl_parser import parse_perturbacion
from services.contrafactual.reoptimizer import ContrafactualService
from services.forecast.forecast_service import ForecastService
from services.optimizer.optimizer_service import OptimizerService


def _perfil_demo() -> PerfilOperador:
    return PerfilOperador(
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


def test_reoptimizar_con_quiebre_proveedor() -> None:
    loader = get_data_loader()
    fs = ForecastService(loader)
    os = OptimizerService(loader)
    cs = ContrafactualService(os)
    perfil = _perfil_demo()

    skus = list(loader.load_productos().keys())[:4]
    forecasts = {sku: fs.forecast(sku, semanas_adelante=1, n_samples=150, seed=5) for sku in skus}
    base = os.optimizar(
        skus_objetivo=skus,
        forecasts=forecasts,
        evento=loader.load_eventos()[0],
        perfil=perfil,
        presupuesto=35000.0,
    )
    pert = parse_perturbacion("que pasa si el proveedor PROV_ASIA_01 quiebra")
    escenario = cs.reoptimizar(base, pert, forecasts, perfil)

    assert escenario.recomendacion_base_id == base.recomendacion_id
    assert escenario.perturbacion.tipo == "QUIEBRE_PROVEEDOR"
    assert escenario.recomendacion_alterna.items
