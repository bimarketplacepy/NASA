"""Algoritmo Robust Satisficing bajo restriccion de cash.

Maximiza el nivel de servicio sujeto a la restriccion de presupuesto.
Resuelve un MILP simple en cerrado: dada la cantidad central deseada y el
presupuesto, ajusta la cantidad real para no superar el cash disponible
mientras maximiza el percentil de demanda cubierto.

Referencia: paper de robust optimization, seccion 3.4 (robust satisficing).
"""

from __future__ import annotations

from typing import Any, Optional

from optimization.algorithms.base import (
    BaseAlgorithm,
    calcular_var_cvar,
    costo_esperado,
    elegir_proveedor,
    listar_restricciones_aplicadas,
)
from optimization.schemas import (
    DecisionContext,
    RecomendacionCompra,
    Restriccion,
)


class RobustSatisficingAlgorithm(BaseAlgorithm):
    """Robust Satisficing bajo restriccion de cash.

    Cuando lo elige el dispatcher: presupuesto ajustado y se necesita
    maximizar service level dado el cash disponible.

    Estrategia:
        - Empieza con la cantidad p95 (servicio maximo).
        - Si excede presupuesto, baja al maximo entero comprable.
        - Calcula el "service level efectivo" interpolando entre p5/p50/p95.
    """

    id = "robust_satisficing"
    nombre = "Robust Satisficing (cash-constrained)"
    paper_seccion = "3.4 (robust satisficing)"
    requiere_semanas_minimas = 8
    soporta_unbounded = True
    complejidad = "media"

    def precondiciones(self, ctx: DecisionContext) -> bool:
        """Aplica si hay un presupuesto positivo y al menos un proveedor."""
        return ctx.presupuesto_disponible > 0 and len(ctx.proveedores_candidatos) > 0

    def run(
        self,
        ctx: DecisionContext,
        restricciones: list[Restriccion],
        parametros: Optional[dict[str, Any]] = None,
    ) -> RecomendacionCompra:
        params = parametros or {}
        objetivo_servicio = float(params.get("objetivo_servicio", 0.95))

        f = ctx.forecast
        razones: list[str] = []

        # 1) Elegir proveedor mas barato que cumpla restricciones (prioritario en cash-constrained)
        # En modo cash-tight nos importa precio mas que confiabilidad.
        proveedores_ordenados = sorted(
            ctx.proveedores_candidatos, key=lambda p: p.precio_unitario,
        )
        # Aplicar el ranking estandar pero con bias a precio
        proveedor_elegido, alternativos = elegir_proveedor(
            proveedores_ordenados, restricciones, int(round(f.p95_demanda)),
        )
        # Si el mas barato cabe, preferirlo
        mas_barato = proveedores_ordenados[0]
        if mas_barato.precio_unitario < proveedor_elegido.precio_unitario:
            cantidad_max_barato = int(ctx.presupuesto_disponible // mas_barato.precio_unitario)
            if cantidad_max_barato >= f.p50_demanda:
                proveedor_elegido = mas_barato
                razones.append(f"Cambiado a proveedor mas barato {mas_barato.proveedor_id} por restriccion de cash")

        precio = proveedor_elegido.precio_unitario

        # 2) Capacidad maxima dada el presupuesto
        cantidad_max_presup = int(ctx.presupuesto_disponible // precio) if precio > 0 else 0

        # 3) Cantidad objetivo segun service level deseado
        if objetivo_servicio >= 0.9:
            cantidad_objetivo = int(round(f.p95_demanda))
            razones.append(f"Objetivo service level {objetivo_servicio:.0%}: cantidad ideal={cantidad_objetivo}")
        else:
            mix = (objetivo_servicio - 0.5) / 0.4
            mix = max(0.0, min(1.0, mix))
            cantidad_objetivo = int(round((1 - mix) * f.p50_demanda + mix * f.p95_demanda))
            razones.append(f"Objetivo service level {objetivo_servicio:.0%}: cantidad ideal={cantidad_objetivo}")

        # 4) Tomar el min de objetivo y lo que cabe en presupuesto
        cantidad_central = min(cantidad_objetivo, cantidad_max_presup)
        if cantidad_central < cantidad_objetivo:
            razones.append(
                f"Cantidad reducida de {cantidad_objetivo} a {cantidad_central} por presupuesto USD {ctx.presupuesto_disponible}",
            )

        # 5) Calcular service level efectivo
        if cantidad_central >= f.p95_demanda:
            sl_efectivo = 0.95
        elif cantidad_central >= f.p50_demanda:
            sl_efectivo = 0.5 + 0.45 * (cantidad_central - f.p50_demanda) / max(1.0, f.p95_demanda - f.p50_demanda)
        elif cantidad_central >= f.p5_demanda:
            sl_efectivo = 0.05 + 0.45 * (cantidad_central - f.p5_demanda) / max(1.0, f.p50_demanda - f.p5_demanda)
        else:
            sl_efectivo = 0.05
        razones.append(f"Service level efectivo alcanzable: {sl_efectivo:.0%}")

        # 6) Intervalos coherentes
        cantidad_p5 = min(int(round(f.p5_demanda)), cantidad_central)
        cantidad_p95 = max(cantidad_central, int(round(f.p95_demanda)))
        # En cash-constrained el p95 esta capado por el presupuesto si es relevante
        if cantidad_p95 > cantidad_max_presup:
            cantidad_p95 = cantidad_max_presup

        # 7) VaR / CVaR
        var, cvar = calcular_var_cvar(cantidad_p5, cantidad_central, cantidad_p95, precio)

        return RecomendacionCompra(
            sku=ctx.sku,
            cantidad_central=cantidad_central,
            cantidad_p5=cantidad_p5,
            cantidad_p95=cantidad_p95,
            proveedor_sugerido=proveedor_elegido.proveedor_id,
            proveedores_alternativos=[p.proveedor_id for p in alternativos[:2]],
            costo_esperado=costo_esperado(cantidad_central, precio),
            var_95=var,
            cvar_95=cvar,
            razon_eleccion=razones,
            algoritmo_id=self.id,
            restricciones_aplicadas=listar_restricciones_aplicadas(restricciones),
            confianza_resultado=min(0.95, f.confianza_global * (0.7 + 0.3 * sl_efectivo)),
        )
