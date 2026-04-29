"""Metricas de riesgo financiero para simulaciones."""

from __future__ import annotations

import numpy as np


def value_at_risk(samples: np.ndarray, alpha: float = 0.95) -> float:
    """Calcula VaR con convencion de perdida positiva.

    Args:
        samples: Muestras de retorno/ganancia.
        alpha: Nivel de confianza.

    Returns:
        Value at Risk (positivo en magnitud de perdida).
    """
    q = float(np.percentile(samples, (1 - alpha) * 100))
    return max(0.0, -q)


def conditional_var(samples: np.ndarray, alpha: float = 0.95) -> float:
    """Calcula CVaR (Expected Shortfall) para cola de perdidas.

    Args:
        samples: Muestras de retorno/ganancia.
        alpha: Nivel de confianza.

    Returns:
        Conditional VaR (positivo).
    """
    threshold = float(np.percentile(samples, (1 - alpha) * 100))
    tail = samples[samples <= threshold]
    if tail.size == 0:
        return 0.0
    return max(0.0, -float(np.mean(tail)))


def sharpe_ratio(samples: np.ndarray, risk_free: float = 0.0) -> float | None:
    """Calcula Sharpe ratio simple.

    Args:
        samples: Muestras de retorno.
        risk_free: Tasa libre de riesgo (misma unidad temporal).

    Returns:
        Sharpe ratio o None si desvio cero.
    """
    excess = samples - risk_free
    std = float(np.std(excess, ddof=0))
    if np.isclose(std, 0.0):
        return None
    return float(np.mean(excess) / std)


def probability_of_loss(samples: np.ndarray) -> float:
    """Calcula probabilidad de perdida.

    Args:
        samples: Muestras de retorno.

    Returns:
        Probabilidad P(retorno < 0).
    """
    return float(np.mean(samples < 0))
