"""Funciones auxiliares de estacionalidad para forecasting.

Este modulo contiene utilidades matematicas simples para manipular
componentes estacionales y calcular estadisticas de error.
"""

from __future__ import annotations

import numpy as np


def week_of_year_from_absolute_week(absolute_week: int) -> int:
    """Convierte semana absoluta (1..N) en semana del anio (1..52).

    Args:
        absolute_week: Semana absoluta en la serie historica.

    Returns:
        Semana del anio en el rango [1, 52].
    """
    return ((absolute_week - 1) % 52) + 1


def enforce_positive_demand(values: np.ndarray) -> np.ndarray:
    """Recorta valores negativos de demanda y devuelve copia segura.

    Args:
        values: Array de valores de demanda.

    Returns:
        Array sin valores negativos.
    """
    return np.maximum(values, 0.0)


def summarize_distribution(samples: np.ndarray) -> dict[str, float]:
    """Resume una distribucion en media, desvio y percentiles canonicos.

    Args:
        samples: Muestras de demanda simuladas.

    Returns:
        Diccionario con estadisticos: media, std, p5, p25, p50, p75, p95.
    """
    safe = enforce_positive_demand(samples)
    return {
        "media": float(np.mean(safe)),
        "std": float(np.std(safe, ddof=0)),
        "p5": float(np.percentile(safe, 5)),
        "p25": float(np.percentile(safe, 25)),
        "p50": float(np.percentile(safe, 50)),
        "p75": float(np.percentile(safe, 75)),
        "p95": float(np.percentile(safe, 95)),
    }
