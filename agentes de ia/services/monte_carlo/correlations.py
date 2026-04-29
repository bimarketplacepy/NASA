"""Estimacion de correlaciones entre SKUs para demanda simulada."""

from __future__ import annotations

import numpy as np
import pandas as pd


def nearest_psd(matrix: np.ndarray) -> np.ndarray:
    """Proyecta una matriz simetrica a semidefinida positiva.

    Args:
        matrix: Matriz candidata.

    Returns:
        Matriz PSD aproximada.
    """
    sym = (matrix + matrix.T) / 2.0
    eigvals, eigvecs = np.linalg.eigh(sym)
    clipped = np.clip(eigvals, a_min=1e-8, a_max=None)
    psd = eigvecs @ np.diag(clipped) @ eigvecs.T
    # Re-normaliza diagonal para aproximar matriz de correlacion.
    d = np.sqrt(np.diag(psd))
    d[d == 0] = 1.0
    corr = psd / np.outer(d, d)
    return np.clip(corr, -1.0, 1.0)


def estimate_correlation_matrix(ventas_df: pd.DataFrame, skus: list[str]) -> np.ndarray:
    """Calcula matriz de correlacion de Pearson por SKU.

    Args:
        ventas_df: DataFrame de ventas historicas.
        skus: Lista de SKUs en orden deseado.

    Returns:
        Matriz de correlacion PSD de dimension len(skus) x len(skus).
    """
    pivot = (
        ventas_df[ventas_df["sku"].isin(skus)]
        .pivot_table(index="semana", columns="sku", values="ventas_unidades", aggfunc="sum")
        .reindex(columns=skus)
        .ffill()
        .bfill()
        .fillna(0.0)
    )
    if pivot.shape[1] == 1:
        return np.array([[1.0]], dtype=float)

    corr = np.corrcoef(pivot.to_numpy(dtype=float).T)
    if np.isnan(corr).any():
        corr = np.nan_to_num(corr, nan=0.0)
        np.fill_diagonal(corr, 1.0)
    return nearest_psd(corr)
