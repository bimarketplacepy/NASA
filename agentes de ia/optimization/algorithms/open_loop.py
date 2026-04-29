"""Algoritmo Open-Loop Baseline.

Baseline simple: cantidad = suma de la media del horizonte * factor de seguridad.
No usa retroalimentacion ni revisa la decision a medida que llegan datos.
Sirve como linea base contra la cual comparar el resto de algoritmos.

Referencia: paper de robust optimization, seccion 1 (baseline trivial).
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


class OpenLoopAlgorithm(BaseAlgorithm):
    """Open-Loop Baseline.

    Cuando lo elige el dispatcher: cold-start sin sku_donante, baseline simple,
    cuando se quiere una recomendacion sin asumir nada sobre la dinamica.
    """

    id = "open_loop"
    nombre = "Open-Loop Baseline"
    paper_seccion = "1.0 (baseline)"
    requiere_semanas_minimas = 0
    soporta_unbounded = False
    complejidad = "baja"

    def precondiciones(self, ctx: DecisionContext) -> bool:
        """Aplica siempre (es el baseline)."""
        return True

    def run(
        self,
        ctx: DecisionContext,
        restricciones: list[Restriccion],
        parametros: Optional[dict[str, Any]] = None,
    ) -> RecomendacionCompra:
        f = ctx.forecast
        razones: list[str] = []

        # 1) Cantidad central = suma de la media del horizonte
        cantidad_central = int(round(f.media_demanda))
        cantidad_p5 = int(round(f.p5_demanda))
        cantidad_p95 = int(round(f.p95_demanda))
        razones.append(f"Suma de media en {f.horizonte_semanas} semanas = {cantidad_central}")

        # 2) Aplicar buffer minimo si hay restriccion deontica
        cantidad_central, factor = aplicar_buffer_minimo(cantidad_central, restricciones)
        if factor > 1.0:
            cantidad_p95 = int(round(cantidad_p95 * factor))
            razones.append(f"Buffer minimo aplicado: factor {factor}")

        # 3) Elegir proveedor
        proveedor_elegido, alternativos = elegir_proveedor(
            ctx.proveedores_candidatos, restricciones, cantidad_central,
        )
        razones.append(
            f"Proveedor {proveedor_elegido.proveedor_id} elegido por confiabilidad="
            f"{proveedor_elegido.confiabilidad}, lead_time={proveedor_elegido.lead_time_dias}d",
        )

        # 4) Cap por presupuesto
        cantidad_central, capado = cap_por_presupuesto(
            cantidad_central, proveedor_elegido.precio_unitario, ctx.presupuesto_disponible,
        )
        if capado:
            razones.append(f"Cantidad capada por presupuesto disponible USD {ctx.presupuesto_disponible}")
            cantidad_p95 = min(cantidad_p95, cantidad_central)

        # 5) Cantidades p5/p95 coherentes
        cantidad_p5 = min(cantidad_p5, cantidad_central)
        cantidad_p95 = max(cantidad_p95, cantidad_central)

        # 6) VaR / CVaR
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
            confianza_resultado=f.confianza_global * 0.85,  # baseline tiene menor confianza relativa
        )
