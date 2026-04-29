"""Pruebas basicas del simulador Monte Carlo."""

from __future__ import annotations

from datetime import date, datetime

from clients.data_loader import get_data_loader
from schemas.recomendaciones import ItemCompra
from schemas.simulacion import ForecastResult
from services.monte_carlo.simulator import MonteCarloSimulator


def _build_item(sku: str, costo_unitario: float, cantidad: int = 250) -> ItemCompra:
    return ItemCompra(
        sku=sku,
        proveedor_id="PROV_NAC_01",
        cantidad=cantidad,
        costo_unitario=costo_unitario,
        descuento_aplicado=0.0,
        costo_total=costo_unitario * cantidad,
        fecha_pedido_estimada=date(2026, 10, 1),
        fecha_arribo_estimada=date(2026, 10, 10),
        semanas_buffer_pre_evento=4.0,
    )


def _build_forecast(sku: str, media: float, std: float) -> ForecastResult:
    return ForecastResult(
        sku=sku,
        semana_objetivo=47,
        media=media,
        std=std,
        p5=max(0.0, media - 1.65 * std),
        p25=max(0.0, media - 0.67 * std),
        p50=media,
        p75=media + 0.67 * std,
        p95=media + 1.65 * std,
        metodo="ets",
        intervalo_confianza_calibrado=True,
        samples=None,
    )


def test_simular_resultado_valido() -> None:
    loader = get_data_loader()
    productos = list(loader.load_productos().values())[:2]
    item_a = _build_item(productos[0].sku, costo_unitario=12.0, cantidad=200)
    item_b = _build_item(productos[1].sku, costo_unitario=18.0, cantidad=180)

    forecasts = {
        item_a.sku: _build_forecast(item_a.sku, media=220.0, std=35.0),
        item_b.sku: _build_forecast(item_b.sku, media=190.0, std=28.0),
    }

    sim = MonteCarloSimulator(loader)
    result = sim.simular(items=[item_a, item_b], forecasts=forecasts, n_sims=1200, seed=11)

    assert result.n_simulaciones == 1200
    assert len(result.distribucion_retorno) == 1200
    assert result.metricas.costo_total > 0
    assert 0.0 <= result.metricas.probabilidad_perdida <= 1.0
