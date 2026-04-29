"""Algoritmo Safety Stock (heuristica clasica).

Heuristica conservadora: cantidad = p95_demanda. Util como fallback cuando
no se quiere optimizar, sino tener una garantia de service level alta.

Referencia: paper de robust optimization, seccion 1 (baseline / heuristica).
"""

from __future__ import annotations

from typing import Any, Optional

from optimization.algorithms.base import (
    BaseAlgorithm,
    aplicar_buffer_minimo,
    calcular_var_cvar,
    cap_por_presupuesto,
    costo_esperado,
    elegir_proveedor,
    listar_restricciones_aplicadas,
)
from optimization.schemas import (
    DecisionContext,
    RecomendacionCompra,
    Restriccion,
)


class SafetyStockAlgorithm(BaseAlgorithm):
    """Safety Stock heuristico (cantidad = p95).

    Cuando lo elige el dispatcher: cuando no se puede correr nada mas
    sofisticado, o cuando el contexto es de muy alta criticidad y se prioriza
    no quebrar stock por sobre minimizar costo.
    """

    id = "safety_stock"
    nombre = "Safety Stock (heuristica p95)"
    paper_seccion = "1.0 (heuristica conservadora)"
    requiere_semanas_minimas = 4
    soporta_unbounded = True
    complejidad = "baja"

    def run(
        self,
        ctx: DecisionContext,
        restricciones: list[Restriccion],
        parametros: Optional[dict[str, Any]] = None,
    ) -> RecomendacionCompra:
        params = parametros or {}
        usar_p99 = bool(params.get("usar_p99", False))

        f = ctx.forecast
        razones: list[str] = []

        # 1) Cantidad central = p95 (o p99 aproximado si se solicita)
        if usar_p99:
            # Aproximar p99 como p95 + 1 sigma adicional
            extra = 0.0
            if f.std and f.media:
                extra = sum(f.std) * 0.5
            cantidad_central = int(round(f.p95_demanda + extra))
            razones.append(f"Heuristica p99 aproximada (p95 + 0.5*std)")
        else:
            cantidad_central = int(round(f.p95_demanda))
            razones.append(f"Heuristica safety stock: cantidad = p95 = {cantidad_central}")

        cantidad_p5 = int(round(f.p50_demanda))  # piso conservador en safety_stock
        cantidad_p95 = cantidad_central

        # 2) Buffer deontico
        cantidad_central, factor_buffer = aplicar_buffer_minimo(cantidad_central, restricciones)
        if factor_buffer > 1.0:
            cantidad_p95 = cantidad_central
            razones.append(f"Buffer minimo deontico: factor {factor_buffer}")

        # 3) Proveedor
        proveedor_elegido, alternativos = elegir_proveedor(
            ctx.proveedores_candidatos, restricciones, cantidad_central,
        )
        razones.append(f"Proveedor {proveedor_elegido.proveedor_id}")

        # 4) Cap por presupuesto
        cantidad_central, capado = cap_por_presupuesto(
            cantidad_central, proveedor_elegido.precio_unitario, ctx.presupuesto_disponible,
        )
        if capado:
            razones.append("Cantidad capada por presupuesto disponible")
            cantidad_p95 = cantidad_central

        cantidad_p5 = min(cantidad_p5, cantidad_central)

        # 5) VaR / CVaR
        var, cvar = calcular_var_cvar(
            cantidad_p5, cantidad_central, cantidad_p95, proveedor_elegido.precio_unitario,
        )

        return RecomendacionCompra(
            sku=ctx.sku,
            cantidad_central=cantidad_central,
            cantidad_p5=cantidad_p5,
            cantidad_p95=cantidad_p95,
            proveedor_sugerido=proveedor_elegido.proveedor_id,
            proveedores_alternativos=[p.proveedor_id for p in alternativos[:2]],
            costo_esperado=costo_esperado(cantidad_central, proveedor_elegido.precio_unitario),
            var_95=var,
            cvar_95=cvar,
            razon_eleccion=razones,
            algoritmo_id=self.id,
            restricciones_aplicadas=listar_restricciones_aplicadas(restricciones),
            confianza_resultado=f.confianza_global * 0.85,
        )
