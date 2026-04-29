"""Servicio unificado de pronostico de demanda.

Selecciona automaticamente la estrategia:
- ETS con bootstrap para SKUs con >=52 semanas.
- Cold-start por categoria para SKUs con historial corto.
"""

from __future__ import annotations

import numpy as np

from clients.data_loader import DataLoader, get_data_loader
from clients.ontologia_client import OntologiaClient
from schemas.simulacion import ForecastResult
from services.forecast.cold_start import ColdStartForecaster
from services.forecast.ets_model import ETSForecaster
from services.forecast.seasonal_decompose import week_of_year_from_absolute_week


class ForecastService:
    """Interfaz de pronostico para el resto de la plataforma."""

    def __init__(
        self,
        data_loader: DataLoader | None = None,
        ontologia_client: OntologiaClient | None = None,
    ) -> None:
        """Inicializa el servicio y sus motores internos.

        Args:
            data_loader: Instancia opcional para inyeccion en tests.
            ontologia_client: Instancia opcional de cliente ontologico.
        """
        self.data_loader = data_loader or get_data_loader()
        self.ontologia_client = ontologia_client or OntologiaClient()
        self.ets = ETSForecaster()
        self.cold_start = ColdStartForecaster(self.data_loader, self.ontologia_client)

    def forecast(
        self,
        sku: str,
        semanas_adelante: int = 1,
        n_samples: int = 1000,
        seed: int = 42,
    ) -> ForecastResult:
        """Calcula forecast para SKU y horizonte indicado.

        Args:
            sku: SKU a pronosticar.
            semanas_adelante: Horizonte en semanas hacia adelante.
            n_samples: Cantidad de muestras para intervalos.
            seed: Semilla reproducible.

        Returns:
            ForecastResult con intervalos calibrados y muestras opcionales.
        """
        if semanas_adelante < 1:
            raise ValueError("semanas_adelante debe ser >= 1")

        productos = self.data_loader.load_productos()
        if sku not in productos:
            raise ValueError(f"SKU no encontrado: {sku}")

        ventas = self.data_loader.load_ventas_historicas()
        sku_hist = ventas[ventas["sku"] == sku].sort_values("semana")
        history = sku_hist["ventas_unidades"].to_numpy(dtype=float)

        current_abs_week = int(ventas["semana"].max())
        target_abs_week = current_abs_week + semanas_adelante
        semana_objetivo = week_of_year_from_absolute_week(target_abs_week)

        if len(history) >= 52:
            summary, samples = self.ets.fit_and_forecast(
                history=history,
                steps=semanas_adelante,
                n_samples=n_samples,
                seed=seed,
            )
            metodo = "ets"
            calibrated = True
        else:
            summary, samples = self.cold_start.forecast_distribution(
                sku=sku,
                semana_objetivo=semana_objetivo,
                n_samples=n_samples,
                seed=seed,
            )
            metodo = "categoria_cold_start"
            calibrated = False

        self._validate_quantile_order(summary)
        return ForecastResult(
            sku=sku,
            semana_objetivo=semana_objetivo,
            media=summary["media"],
            std=max(0.01, summary["std"]),
            p5=summary["p5"],
            p25=summary["p25"],
            p50=summary["p50"],
            p75=summary["p75"],
            p95=summary["p95"],
            metodo=metodo,
            intervalo_confianza_calibrado=calibrated,
            samples=[float(x) for x in samples],
        )

    def _validate_quantile_order(self, summary: dict[str, float]) -> None:
        """Verifica orden estricto de cuantiles para sanidad del forecast.

        Args:
            summary: Resumen estadistico del forecast.
        """
        if not (summary["p5"] <= summary["p25"] <= summary["p50"] <= summary["p75"] <= summary["p95"]):
            raise ValueError("Cuantiles invalidos en forecast.")
