"""Forecast cold start para SKUs con poco o nulo historial.

El enfoque usa el patron estacional de la categoria y lo escala con el
nivel esperado del SKU. Si no hay historia del SKU, usa promedio de categoria.
"""

from __future__ import annotations

import numpy as np

from clients.data_loader import DataLoader
from clients.ontologia_client import OntologiaClient
from services.forecast.seasonal_decompose import summarize_distribution


class ColdStartForecaster:
    """Motor de forecast cold-start basado en categoria."""

    def __init__(self, data_loader: DataLoader, ontologia_client: OntologiaClient) -> None:
        """Inicializa dependencias.

        Args:
            data_loader: Cargador de datos para ventas historicas.
            ontologia_client: Cliente de ontologia para mapear SKU->categoria.
        """
        self.data_loader = data_loader
        self.ontologia_client = ontologia_client

    def estimate_level(self, sku: str) -> float:
        """Estima nivel base del SKU usando historia parcial o categoria.

        Args:
            sku: SKU objetivo.

        Returns:
            Nivel promedio esperado de unidades por semana.
        """
        ventas = self.data_loader.load_ventas_historicas()
        sku_hist = ventas[ventas["sku"] == sku]
        if not sku_hist.empty:
            return float(max(1.0, sku_hist["ventas_unidades"].mean()))

        categoria = self.ontologia_client.categoria_de_sku(sku)
        productos = self.data_loader.load_productos()
        skus_categoria = [p.sku for p in productos.values() if p.categoria_id == categoria.categoria_id]
        cat_hist = ventas[ventas["sku"].isin(skus_categoria)]
        if cat_hist.empty:
            return 5.0
        return float(max(1.0, cat_hist["ventas_unidades"].mean()))

    def estimate_std_with_penalty(self, sku: str, penalty_factor: float = 1.5) -> float:
        """Estima desvio estandar penalizado por incertidumbre de cold start.

        Args:
            sku: SKU objetivo.
            penalty_factor: Multiplicador de incertidumbre adicional.

        Returns:
            Desvio estandar estimado.
        """
        categoria = self.ontologia_client.categoria_de_sku(sku)
        productos = self.data_loader.load_productos()
        ventas = self.data_loader.load_ventas_historicas()
        skus_categoria = [p.sku for p in productos.values() if p.categoria_id == categoria.categoria_id]
        cat_hist = ventas[ventas["sku"].isin(skus_categoria)]
        base_std = float(cat_hist["ventas_unidades"].std(ddof=0)) if not cat_hist.empty else 2.0
        return max(1.0, base_std * penalty_factor)

    def forecast_distribution(
        self,
        sku: str,
        semana_objetivo: int,
        n_samples: int = 1000,
        seed: int = 42,
    ) -> tuple[dict[str, float], list[float]]:
        """Genera distribucion de demanda cold-start para semana objetivo.

        Args:
            sku: SKU objetivo.
            semana_objetivo: Semana del anio objetivo (1..52).
            n_samples: Cantidad de simulaciones.
            seed: Semilla para reproducibilidad.

        Returns:
            Tupla (resumen estadistico, muestras).
        """
        categoria = self.ontologia_client.categoria_de_sku(sku)
        pattern = categoria.patron_estacional
        idx = (semana_objetivo - 1) % 52
        seasonal_multiplier = float(pattern[idx])

        nivel = self.estimate_level(sku)
        std = self.estimate_std_with_penalty(sku)
        media = max(0.0, nivel * seasonal_multiplier)

        rng = np.random.default_rng(seed)
        samples = rng.normal(loc=media, scale=std, size=n_samples)
        samples = np.maximum(samples, 0.0)
        summary = summarize_distribution(samples)
        return summary, samples.tolist()
