"""Implementaciones de algoritmos de optimizacion (Tarea 4 - Mati).

Cada algoritmo expone una clase que cumple el contrato ``IAlgorithm``
(definido en ``optimization.schemas``). El dispatcher de Abi (Bloque 7)
elige cual invocar segun el contexto del SKU.

Registro central de algoritmos disponibles: ``ALGORITMOS_DISPONIBLES``.
"""

from __future__ import annotations

from optimization.algorithms.affine_simple import AffineSimpleAlgorithm
from optimization.algorithms.base import BaseAlgorithm
from optimization.algorithms.cold_inherit import ColdInheritAlgorithm
from optimization.algorithms.inv_buffer import InvBufferAlgorithm
from optimization.algorithms.open_loop import OpenLoopAlgorithm
from optimization.algorithms.robust_satisficing import RobustSatisficingAlgorithm
from optimization.algorithms.safety_stock import SafetyStockAlgorithm

# Registro central — el dispatcher de Abi consulta esta lista.
ALGORITMOS_DISPONIBLES: dict[str, type[BaseAlgorithm]] = {
    OpenLoopAlgorithm.id: OpenLoopAlgorithm,
    ColdInheritAlgorithm.id: ColdInheritAlgorithm,
    InvBufferAlgorithm.id: InvBufferAlgorithm,
    SafetyStockAlgorithm.id: SafetyStockAlgorithm,
    AffineSimpleAlgorithm.id: AffineSimpleAlgorithm,
    RobustSatisficingAlgorithm.id: RobustSatisficingAlgorithm,
}


def crear_algoritmo(algoritmo_id: str) -> BaseAlgorithm:
    """Factory: instancia un algoritmo por su ID.

    Args:
        algoritmo_id: ID del algoritmo (ej: 'open_loop', 'inv_buffer').

    Returns:
        Instancia del algoritmo.

    Raises:
        KeyError: si el ID no esta registrado.
    """
    if algoritmo_id not in ALGORITMOS_DISPONIBLES:
        disponibles = ", ".join(sorted(ALGORITMOS_DISPONIBLES.keys()))
        raise KeyError(
            f"Algoritmo '{algoritmo_id}' no registrado. Disponibles: {disponibles}",
        )
    return ALGORITMOS_DISPONIBLES[algoritmo_id]()


__all__ = [
    "ALGORITMOS_DISPONIBLES",
    "BaseAlgorithm",
    "AffineSimpleAlgorithm",
    "ColdInheritAlgorithm",
    "InvBufferAlgorithm",
    "OpenLoopAlgorithm",
    "RobustSatisficingAlgorithm",
    "SafetyStockAlgorithm",
    "crear_algoritmo",
]
