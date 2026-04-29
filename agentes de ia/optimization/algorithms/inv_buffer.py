"""Algoritmo Inventory Buffer Robusto.

Usa percentiles directos del forecast Monte Carlo de Cris (p50 como cantidad
central, p5/p95 como intervalos). Aplica buffer extra si hay restriccion
deontica de seguridad. Optimizado para perecederos con vigencia proxima.

Referencia: paper de robust optimization, seccion 3.2 (robust constraints).
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


class InvBufferAlgorithm(BaseAlgorithm):
    """Inventory Buffer Robusto con percentiles.

    Cuando lo elige el dispatcher: SKU con suficiente historial para tener
    percentiles confiables, pero no tanto como para usar affine policy.
    Caso ideal: perecederos con horizonte corto.
    """

    id = "inv_buffer"
    nombre = "Inventory Buffer Robusto"
    paper_seccion = "3.2 (robust constraints con chance constraints)"
    requiere_semanas_minimas = 8
    soporta_unbounded = False
    complejidad = "media"

    def run(
        self,
        ctx: DecisionContext,
        restricciones: list[Restriccion],
        parametros: Optional[dict[str, Any]] = None,
    ) -> RecomendacionCompra:
        params = parametros or {}
        nivel_servicio = float(params.get("nivel_servicio", 0.9))

        f = ctx.forecast
        razones: list[str] = []

        # 1) Cantidad central = mediana (p50). Buffer hacia p95 si nivel_servicio alto.
        cantidad_central_base = f.p50_demanda
        if nivel_servicio >= 0.9:
            # Mezcla entre p50 y p95 segun nivel de servicio
            mix = (nivel_servicio - 0.5) / 0.45  # 0.9 -> ~0.89, 0.95 -> 1.0
            mix = max(0.0, min(1.0, mix))
            cantidad_central_base = (1 - mix) * f.p50_demanda + mix * f.p95_demanda
            razones.append(f"Nivel de servicio {nivel_servicio:.0%}: cantidad ponderada p50/p95")

        cantidad_central = int(round(cantidad_central_base))
        cantidad_p5 = int(round(f.p5_demanda))
        cantidad_p95 = int(round(f.p95_demanda))

        # 2) Buffer extra si es perecedero con dias_validez ajustado
        if ctx.es_perecedero:
            ajuste = 0.85  # menos buffer para perecederos (riesgo de tirar producto)
            cantidad_central = int(round(cantidad_central * ajuste))
            cantidad_p95 = int(round(cantidad_p95 * ajuste))
            razones.append(f"Perecedero detectado: ajuste por vigencia (factor {ajuste})")

        # 3) Buffer minimo deontico
        cantidad_central, factor_buffer = aplicar_buffer_minimo(cantidad_central, restricciones)
        if factor_buffer > 1.0:
            cantidad_p95 = int(round(cantidad_p95 * factor_buffer))
            razones.append(f"Buffer deontico: factor {factor_buffer}")

        # 4) Proveedor
        proveedor_elegido, alternativos = elegir_proveedor(
            ctx.proveedores_candidatos, restricciones, cantidad_central,
        )
        razones.append(
            f"Proveedor {proveedor_elegido.proveedor_id} (precio={proveedor_elegido.precio_unitario}, "
            f"lead={proveedor_elegido.lead_time_dias}d)",
        )

        # 5) Cap por presupuesto
        cantidad_central, capado = cap_por_presupuesto(
            cantidad_central, proveedor_elegido.precio_unitario, ctx.presupuesto_disponible,
        )
        if capado:
            razones.append("Capada por presupuesto disponible")

        cantidad_p5 = min(cantidad_p5, cantidad_central)
        cantidad_p95 = max(cantidad_p95, cantidad_central)

        # 6) VaR / CVaR
        var, cvar = calcular_var_cvar(
            cantidad_p5, cantidad_central, cantidad_p95, proveedor_elegido.precio_unitario,
        )

        razones.append(f"Inventory buffer con nivel servicio objetivo {nivel_servicio:.0%}")

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
            confianza_resultado=f.confianza_global * 0.92,
        )
