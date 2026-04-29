"""Motor principal de simulacion Monte Carlo.

Implementa simulacion vectorizada de retorno y riesgo para un plan de compra.
"""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from clients.data_loader import DataLoader, get_data_loader
from schemas.recomendaciones import ItemCompra
from schemas.simulacion import ForecastResult, MetricasRiesgo, ResultadoMonteCarlo
from services.monte_carlo.correlations import estimate_correlation_matrix
from services.monte_carlo.risk_metrics import conditional_var, probability_of_loss, sharpe_ratio, value_at_risk


@dataclass(frozen=True)
class SimulationContext:
    """Contexto interno de simulacion por item."""

    sku: str
    quantity: float
    unit_cost: float
    sale_price: float
    is_perishable: bool
    margin_lost: float


class MonteCarloSimulator:
    """Simulador vectorizado de escenarios de demanda y retorno."""

    def __init__(self, data_loader: DataLoader | None = None) -> None:
        """Inicializa dependencias para lookup de productos."""
        self.data_loader = data_loader or get_data_loader()

    def simular(
        self,
        items: list[ItemCompra],
        forecasts: dict[str, ForecastResult],
        n_sims: int = 10000,
        correlaciones: np.ndarray | None = None,
        seed: int = 42,
    ) -> ResultadoMonteCarlo:
        """Ejecuta simulacion Monte Carlo para plan de compra.

        Args:
            items: Plan de compra por SKU/proveedor.
            forecasts: Forecast por SKU.
            n_sims: Numero de simulaciones.
            correlaciones: Matriz opcional de correlaciones.
            seed: Semilla reproducible.

        Returns:
            ResultadoMonteCarlo con distribuciones y metricas.
        """
        if n_sims < 100:
            raise ValueError("n_sims debe ser >= 100 para estabilidad estadistica.")
        if not items:
            raise ValueError("Se requiere al menos un item de compra.")

        context = self._build_context(items)
        sku_order = [c.sku for c in context]
        demand_samples = self._sample_demands(
            sku_order=sku_order,
            forecasts=forecasts,
            n_sims=n_sims,
            correlaciones=correlaciones,
            seed=seed,
        )

        quantities = np.array([c.quantity for c in context], dtype=float)[None, :]
        unit_costs = np.array([c.unit_cost for c in context], dtype=float)[None, :]
        sale_prices = np.array([c.sale_price for c in context], dtype=float)[None, :]
        margin_lost = np.array([c.margin_lost for c in context], dtype=float)[None, :]
        perish_factor = np.array([1.0 if c.is_perishable else 0.7 for c in context], dtype=float)[None, :]

        sold = np.minimum(quantities, demand_samples)
        leftover = np.maximum(0.0, quantities - demand_samples)
        shortage = np.maximum(0.0, demand_samples - quantities)

        revenue = sold * sale_prices
        purchase_cost = quantities * unit_costs
        dead_stock_cost = leftover * unit_costs * perish_factor
        opportunity_cost = shortage * margin_lost
        profit_items = revenue - purchase_cost - dead_stock_cost - opportunity_cost
        total_profit = np.sum(profit_items, axis=1)

        total_dead_stock = np.sum(dead_stock_cost, axis=1)
        total_lost_sales = np.sum(opportunity_cost, axis=1)
        total_purchase_cost = float(np.sum(purchase_cost))

        metricas = MetricasRiesgo(
            stock_muerto_esperado=float(np.mean(total_dead_stock)),
            stock_muerto_p95=float(np.percentile(total_dead_stock, 95)),
            ventas_perdidas_esperadas=float(np.mean(total_lost_sales)),
            ventas_perdidas_p95=float(np.percentile(total_lost_sales, 95)),
            costo_total=total_purchase_cost,
            retorno_esperado=float(np.mean(total_profit)),
            retorno_p5=float(np.percentile(total_profit, 5)),
            retorno_p95=float(np.percentile(total_profit, 95)),
            var_95=value_at_risk(total_profit, alpha=0.95),
            cvar_95=conditional_var(total_profit, alpha=0.95),
            probabilidad_perdida=probability_of_loss(total_profit),
            sharpe_ratio=sharpe_ratio(total_profit, risk_free=0.0),
        )

        return ResultadoMonteCarlo(
            n_simulaciones=n_sims,
            metricas=metricas,
            distribucion_retorno=[float(x) for x in total_profit],
            distribucion_stock_muerto=[float(x) for x in total_dead_stock],
            distribucion_ventas_perdidas=[float(x) for x in total_lost_sales],
            seed=seed,
        )

    def estimate_correlations_from_history(self, skus: list[str]) -> np.ndarray:
        """Estima correlaciones desde ventas historicas para los SKUs dados."""
        ventas_df = self.data_loader.load_ventas_historicas()
        return estimate_correlation_matrix(ventas_df=ventas_df, skus=skus)

    def _build_context(self, items: list[ItemCompra]) -> list[SimulationContext]:
        productos = self.data_loader.load_productos()
        context: list[SimulationContext] = []
        for item in items:
            prod = productos.get(item.sku)
            if prod is None:
                raise ValueError(f"SKU no encontrado en catalogo: {item.sku}")
            margin_lost = max(0.0, prod.precio_referencia - item.costo_unitario)
            context.append(
                SimulationContext(
                    sku=item.sku,
                    quantity=float(item.cantidad),
                    unit_cost=float(item.costo_unitario),
                    sale_price=float(prod.precio_referencia),
                    is_perishable=bool(prod.perecedero),
                    margin_lost=float(margin_lost),
                )
            )
        return context

    def _sample_demands(
        self,
        sku_order: list[str],
        forecasts: dict[str, ForecastResult],
        n_sims: int,
        correlaciones: np.ndarray | None,
        seed: int,
    ) -> np.ndarray:
        means = np.array([forecasts[sku].media for sku in sku_order], dtype=float)
        stds = np.array([max(1e-6, forecasts[sku].std) for sku in sku_order], dtype=float)
        rng = np.random.default_rng(seed)

        if correlaciones is None:
            demands = rng.normal(loc=means[None, :], scale=stds[None, :], size=(n_sims, len(sku_order)))
            return np.maximum(demands, 0.0)

        if correlaciones.shape != (len(sku_order), len(sku_order)):
            raise ValueError("Dimension de correlaciones invalida para los SKUs recibidos.")

        cov = np.outer(stds, stds) * correlaciones
        demands = rng.multivariate_normal(mean=means, cov=cov, size=n_sims, method="eigh")
        return np.maximum(demands, 0.0)
