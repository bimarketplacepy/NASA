"""Algoritmo Affine Ordering Policy + EWMA Suavizado (version simple).

Implementacion light de affine policy: la cantidad pedida es funcion afin de
las semanas observadas, con suavizado exponencial (EWMA) sobre la media.
Ajustada por la tendencia local detectada en la serie.

Referencia: paper de robust optimization, seccion 2.1, 2.4, 3.2 (affine policy).
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


def _ewma_smooth(values: list[float], alpha: float = 0.3) -> float:
    """EWMA simple. Devuelve el valor suavizado al final de la serie."""
    if not values:
        return 0.0
    s = values[0]
    for v in values[1:]:
        s = alpha * v + (1 - alpha) * s
    return s


class AffineSimpleAlgorithm(BaseAlgorithm):
    """Affine Ordering Policy con EWMA bounded.

    Cuando lo elige el dispatcher: SKU con >= 52 semanas y volatilidad < 0.3.
    Es el caso "feliz" donde podemos hacer lo mejor del paper sin sufrir
    inestabilidad numerica.
    """

    id = "affine_simple"
    nombre = "Affine Policy + EWMA Bounded"
    paper_seccion = "2.1, 2.4, 3.2 (affine policy con EWMA)"
    requiere_semanas_minimas = 52
    soporta_unbounded = False
    complejidad = "alta"

    def precondiciones(self, ctx: DecisionContext) -> bool:
        """Requiere suficiente historial Y volatilidad acotada."""
        caract = ctx.forecast.caracteristicas_serie
        return (
            caract.semanas_efectivas >= self.requiere_semanas_minimas
            and caract.volatilidad <= 0.45
        )

    def run(
        self,
        ctx: DecisionContext,
        restricciones: list[Restriccion],
        parametros: Optional[dict[str, Any]] = None,
    ) -> RecomendacionCompra:
        params = parametros or {}
        alpha = float(params.get("ewma_alpha", 0.3))
        beta_tendencia = float(params.get("beta_tendencia", 1.0))

        f = ctx.forecast
        caract = f.caracteristicas_serie
        razones: list[str] = []

        # 1) EWMA sobre la media del horizonte
        media_suavizada = _ewma_smooth(f.media, alpha=alpha)
        razones.append(f"EWMA con alpha={alpha} sobre media del horizonte: {media_suavizada:.1f}")

        # 2) Affine policy: ajustar por tendencia_local
        ajuste_tendencia = 1.0 + caract.tendencia_local * beta_tendencia * f.horizonte_semanas
        ajuste_tendencia = max(0.5, min(2.0, ajuste_tendencia))  # bounded
        razones.append(f"Ajuste afin por tendencia local {caract.tendencia_local:+.3f}: factor {ajuste_tendencia:.2f}")

        cantidad_central = int(round(media_suavizada * f.horizonte_semanas * ajuste_tendencia))

        # 3) Intervalos: usar p5/p95 ajustados por la confianza global
        confianza = f.confianza_global
        cantidad_p5 = int(round(f.p5_demanda * (0.9 + 0.1 * confianza)))
        cantidad_p95 = int(round(f.p95_demanda * (0.9 + 0.1 * confianza)))

        # 4) Buffer deontico
        cantidad_central, factor_buffer = aplicar_buffer_minimo(cantidad_central, restricciones)
        if factor_buffer > 1.0:
            cantidad_p95 = int(round(cantidad_p95 * factor_buffer))
            razones.append(f"Buffer deontico: factor {factor_buffer}")

        # 5) Proveedor
        proveedor_elegido, alternativos = elegir_proveedor(
            ctx.proveedores_candidatos, restricciones, cantidad_central,
        )
        razones.append(f"Proveedor {proveedor_elegido.proveedor_id}")

        # 6) Cap por presupuesto
        cantidad_central, capado = cap_por_presupuesto(
            cantidad_central, proveedor_elegido.precio_unitario, ctx.presupuesto_disponible,
        )
        if capado:
            razones.append("Capada por presupuesto")

        cantidad_p5 = min(cantidad_p5, cantidad_central)
        cantidad_p95 = max(cantidad_p95, cantidad_central)

        # 7) VaR / CVaR
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
            confianza_resultado=f.confianza_global * 0.95,  # affine policy es la mas confiable
        )
