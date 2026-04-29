"""Schemas de simulacion y riesgo."""

from typing import Literal

from pydantic import BaseModel


class ForecastResult(BaseModel):
    """Resultado de forecast por SKU."""

    sku: str
    semana_objetivo: int
    media: float
    std: float
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float
    metodo: Literal["ets", "prophet", "categoria_cold_start", "tendencia"]
    intervalo_confianza_calibrado: bool
    samples: list[float] | None = None


class MetricasRiesgo(BaseModel):
    """Metricas financieras del escenario."""

    stock_muerto_esperado: float
    stock_muerto_p95: float
    ventas_perdidas_esperadas: float
    ventas_perdidas_p95: float
    costo_total: float
    retorno_esperado: float
    retorno_p5: float
    retorno_p95: float
    var_95: float
    cvar_95: float
    probabilidad_perdida: float
    sharpe_ratio: float | None = None


class ResultadoMonteCarlo(BaseModel):
    """Salida completa de simulacion Monte Carlo."""

    n_simulaciones: int
    metricas: MetricasRiesgo
    distribucion_retorno: list[float]
    distribucion_stock_muerto: list[float]
    distribucion_ventas_perdidas: list[float]
    seed: int


class AffinePolicyParams(BaseModel):
    """Parametros de politica afin robusta."""

    y_0: float
    y_i: float
    ewma_alpha: float
    ewma_k: float


class FinancialConstraints(BaseModel):
    """Restricciones financieras del modelo robusto."""

    min_turnover_ratio_psi: float
    min_revenue_target_phi: float
    initial_cash_Zt: float
    holding_cost_rate_h: float
    stockout_penalty_rate_c: float
