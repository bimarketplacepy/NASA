"""Stub inicial de solver MILP con PuLP.

Nota: en esta etapa la optimizacion productiva usa heuristica. Este archivo
define la interfaz para evolucionar a modelo exacto sin romper contratos.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MilpSolveResult:
    """Salida futura del solver exacto."""

    feasible: bool
    objective_value: float
    status: str
    items: list[dict]


class MilpSolver:
    """Interfaz de solver MILP (pendiente de formulacion completa)."""

    def solve(self, *_args, **_kwargs) -> MilpSolveResult:
        """Resuelve modelo MILP.

        Actualmente devuelve estado no implementado para habilitar wiring
        progresivo del `OptimizerService`.
        """
        return MilpSolveResult(
            feasible=False,
            objective_value=0.0,
            status="NOT_IMPLEMENTED",
            items=[],
        )
