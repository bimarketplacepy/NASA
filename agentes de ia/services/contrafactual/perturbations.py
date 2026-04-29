"""Catalogo de perturbaciones para escenarios contrafactuales."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from schemas.contrafactual import Perturbacion
from schemas.simulacion import ForecastResult


@dataclass(frozen=True)
class PerturbationContext:
    """Contexto mutable para aplicar perturbaciones."""

    excluded_suppliers: list[str]
    budget_override: float | None
    demand_multipliers_by_sku: dict[str, float]
    demand_multipliers_global: float


def create_base_context() -> PerturbationContext:
    """Construye contexto inicial sin cambios."""
    return PerturbationContext(
        excluded_suppliers=[],
        budget_override=None,
        demand_multipliers_by_sku={},
        demand_multipliers_global=1.0,
    )


def apply_perturbation(ctx: PerturbationContext, perturbacion: Perturbacion) -> PerturbationContext:
    """Aplica perturbacion al contexto.

    Args:
        ctx: Contexto base.
        perturbacion: Perturbacion estructurada.

    Returns:
        Nuevo contexto con cambios aplicados.
    """
    tipo = perturbacion.tipo
    p = perturbacion.parametros or {}

    if tipo == "QUIEBRE_PROVEEDOR":
        proveedor_id = str(p.get("proveedor_id", "")).strip()
        if proveedor_id:
            excluded = list(dict.fromkeys([*ctx.excluded_suppliers, proveedor_id]))
            return PerturbationContext(
                excluded_suppliers=excluded,
                budget_override=ctx.budget_override,
                demand_multipliers_by_sku=ctx.demand_multipliers_by_sku.copy(),
                demand_multipliers_global=ctx.demand_multipliers_global,
            )

    if tipo == "CAMBIO_DEMANDA":
        factor = float(p.get("factor", 1.0))
        sku = p.get("sku")
        if sku:
            by_sku = ctx.demand_multipliers_by_sku.copy()
            by_sku[str(sku)] = by_sku.get(str(sku), 1.0) * factor
            return PerturbationContext(
                excluded_suppliers=ctx.excluded_suppliers.copy(),
                budget_override=ctx.budget_override,
                demand_multipliers_by_sku=by_sku,
                demand_multipliers_global=ctx.demand_multipliers_global,
            )
        return PerturbationContext(
            excluded_suppliers=ctx.excluded_suppliers.copy(),
            budget_override=ctx.budget_override,
            demand_multipliers_by_sku=ctx.demand_multipliers_by_sku.copy(),
            demand_multipliers_global=ctx.demand_multipliers_global * factor,
        )

    if tipo == "CAMBIO_PRESUPUESTO":
        new_budget = float(p.get("nuevo_presupuesto"))
        return PerturbationContext(
            excluded_suppliers=ctx.excluded_suppliers.copy(),
            budget_override=new_budget,
            demand_multipliers_by_sku=ctx.demand_multipliers_by_sku.copy(),
            demand_multipliers_global=ctx.demand_multipliers_global,
        )

    if tipo == "NUEVO_COMPETIDOR":
        impacto = float(p.get("impacto_demanda_pct", 0.15))
        factor = max(0.05, 1.0 - impacto)
        return PerturbationContext(
            excluded_suppliers=ctx.excluded_suppliers.copy(),
            budget_override=ctx.budget_override,
            demand_multipliers_by_sku=ctx.demand_multipliers_by_sku.copy(),
            demand_multipliers_global=ctx.demand_multipliers_global * factor,
        )

    # Tipos no implementados aun: passthrough.
    return PerturbationContext(
        excluded_suppliers=ctx.excluded_suppliers.copy(),
        budget_override=ctx.budget_override,
        demand_multipliers_by_sku=ctx.demand_multipliers_by_sku.copy(),
        demand_multipliers_global=ctx.demand_multipliers_global,
    )


def apply_demand_multipliers(
    base_forecasts: dict[str, ForecastResult],
    ctx: PerturbationContext,
) -> dict[str, ForecastResult]:
    """Aplica multiplicadores de demanda sobre forecasts existentes."""
    out: dict[str, ForecastResult] = {}
    for sku, f in base_forecasts.items():
        factor = ctx.demand_multipliers_global * ctx.demand_multipliers_by_sku.get(sku, 1.0)
        out[sku] = f.model_copy(
            update={
                "media": max(0.0, f.media * factor),
                "std": max(0.01, f.std * max(0.5, factor)),
                "p5": max(0.0, f.p5 * factor),
                "p25": max(0.0, f.p25 * factor),
                "p50": max(0.0, f.p50 * factor),
                "p75": max(0.0, f.p75 * factor),
                "p95": max(0.0, f.p95 * factor),
                "samples": [max(0.0, x * factor) for x in (f.samples or [])] or None,
            }
        )
    return out
