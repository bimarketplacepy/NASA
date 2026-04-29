"""Algoritmo Cold-start Heredado.

Para SKUs nuevos sin historia propia: hereda los parametros del SKU donante
(identificado por similarity engine de Abi) y aplica un descuento de
confianza por la incertidumbre adicional de la herencia.

Referencia: paper de robust optimization, seccion 4 (cold-start estructurado).
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

# Factor de descuento aplicado a las cantidades heredadas:
# si donante = 100 unidades, heredamos 100 * factor para no sobrecomprar
# en un SKU nuevo del que no sabemos casi nada.
FACTOR_DESCUENTO_HERENCIA_DEFAULT = 0.7


class ColdInheritAlgorithm(BaseAlgorithm):
    """Cold-start Heredado.

    Cuando lo elige el dispatcher: SKU nuevo CON sku_donante asignado por
    el similarity engine de Abi (top-K similar identificado).

    Precondicion: ctx.sku_donante is not None.
    """

    id = "cold_inherit"
    nombre = "Cold-start Heredado"
    paper_seccion = "4.0 (cold-start estructurado)"
    requiere_semanas_minimas = 0
    soporta_unbounded = False
    complejidad = "baja"

    def precondiciones(self, ctx: DecisionContext) -> bool:
        """Aplica solo si hay donante (cold-start estructurado)."""
        # Si el forecast viene marcado como 'inherited' tambien lo aceptamos.
        return ctx.sku_donante is not None or ctx.forecast.fuente == "inherited"

    def run(
        self,
        ctx: DecisionContext,
        restricciones: list[Restriccion],
        parametros: Optional[dict[str, Any]] = None,
    ) -> RecomendacionCompra:
        params = parametros or {}
        factor_descuento = float(params.get("factor_descuento_herencia", FACTOR_DESCUENTO_HERENCIA_DEFAULT))

        f = ctx.forecast
        razones: list[str] = []

        donante = ctx.sku_donante or f.sku_donante or "desconocido"
        razones.append(f"Cold-start con donante={donante}, factor_descuento={factor_descuento}")
        razones.append(
            f"Forecast heredado: confianza={f.confianza_global:.2f}, "
            f"semanas_donante={f.caracteristicas_serie.semanas_efectivas}",
        )

        # 1) Cantidades heredadas con descuento
        cantidad_central = int(round(f.media_demanda * factor_descuento))
        cantidad_p5 = int(round(f.p5_demanda * factor_descuento))
        cantidad_p95 = int(round(f.p95_demanda * factor_descuento))

        # 2) Buffer minimo si hay restriccion
        cantidad_central, factor_buffer = aplicar_buffer_minimo(cantidad_central, restricciones)
        if factor_buffer > 1.0:
            cantidad_p95 = int(round(cantidad_p95 * factor_buffer))
            razones.append(f"Buffer minimo deontico: factor {factor_buffer}")

        # 3) Proveedor
        proveedor_elegido, alternativos = elegir_proveedor(
            ctx.proveedores_candidatos, restricciones, cantidad_central,
        )
        razones.append(f"Proveedor elegido: {proveedor_elegido.proveedor_id}")

        # 4) Cap por presupuesto
        cantidad_central, capado = cap_por_presupuesto(
            cantidad_central, proveedor_elegido.precio_unitario, ctx.presupuesto_disponible,
        )
        if capado:
            razones.append("Cantidad capada por presupuesto")

        cantidad_p5 = min(cantidad_p5, cantidad_central)
        cantidad_p95 = max(cantidad_p95, cantidad_central)

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
            confianza_resultado=f.confianza_global * 0.7,  # cold-start hereda menos confianza
        )
