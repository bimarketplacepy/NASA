"""Modelo ETS (Holt-Winters) para forecast con historial suficiente."""

from __future__ import annotations

import numpy as np
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from services.forecast.seasonal_decompose import summarize_distribution


class ETSForecaster:
    """Wrapper de Holt-Winters con bootstrap de residuos."""

    def fit_and_forecast(
        self,
        history: np.ndarray,
        steps: int = 1,
        n_samples: int = 1000,
        seed: int = 42,
    ) -> tuple[dict[str, float], list[float]]:
        """Entrena ETS y devuelve distribucion calibrada por bootstrap.

        Args:
            history: Serie historica de demanda.
            steps: Horizonte de pronostico.
            n_samples: Cantidad de muestras para intervalo empirico.
            seed: Semilla reproducible.

        Returns:
            Tupla (resumen estadistico, muestras).
        """
        if len(history) < 52:
            raise ValueError("ETS requiere al menos 52 observaciones para estacionalidad anual.")

        model = ExponentialSmoothing(
            history,
            trend="add",
            seasonal="add",
            seasonal_periods=52,
            initialization_method="estimated",
        )
        fit = model.fit(optimized=True, use_brute=True)

        point_forecast = np.asarray(fit.forecast(steps), dtype=float)
        fitted = np.asarray(fit.fittedvalues, dtype=float)
        residuals = history - fitted

        # Fallback estable si residuos son degenerados.
        if np.allclose(np.std(residuals), 0.0):
            residuals = np.array([0.0, 1.0, -1.0], dtype=float)

        rng = np.random.default_rng(seed)
        sampled_residuals = rng.choice(residuals, size=n_samples, replace=True)
        samples = point_forecast[-1] + sampled_residuals
        samples = np.maximum(samples, 0.0)

        summary = summarize_distribution(samples)
        return summary, samples.tolist()
