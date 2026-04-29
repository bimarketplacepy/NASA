"""Estrategias de red-teaming sobre recomendaciones."""

from __future__ import annotations

from schemas.recomendaciones import Recomendacion, Vulnerabilidad


def strategy_retraso_aduanero(rec: Recomendacion) -> list[Vulnerabilidad]:
    """Evalua exposicion a proveedores de region externa."""
    vulnerabilidades: list[Vulnerabilidad] = []
    impacted = [i for i in rec.items if "ASIA" in i.proveedor_id or "EUR" in i.proveedor_id]
    if not impacted:
        return vulnerabilidades
    impacto = sum(i.costo_total for i in impacted) * 0.18
    vulnerabilidades.append(
        Vulnerabilidad(
            tipo="RETRASO_ADUANERO",
            descripcion="Dependencia de proveedores internacionales con riesgo logistico.",
            probabilidad_estimada=0.32,
            impacto_usd_esperado=round(impacto, 2),
            impacto_usd_p95=round(impacto * 1.7, 2),
            severidad="MEDIA" if impacto < 20000 else "ALTA",
            items_afectados=[i.sku for i in impacted],
            mitigacion_sugerida="Diversificar parte del volumen con proveedor regional.",
        )
    )
    return vulnerabilidades


def strategy_caida_demanda(rec: Recomendacion) -> list[Vulnerabilidad]:
    """Evalua sobrante potencial con escenario de demanda baja."""
    exp_stock = rec.metricas.stock_muerto_p95
    if exp_stock < 5000:
        return []
    return [
        Vulnerabilidad(
            tipo="CAIDA_DEMANDA",
            descripcion="El plan presenta riesgo de sobrestock ante escenario de baja demanda.",
            probabilidad_estimada=0.28,
            impacto_usd_esperado=round(exp_stock * 0.55, 2),
            impacto_usd_p95=round(exp_stock * 0.9, 2),
            severidad="MEDIA" if exp_stock < 20000 else "ALTA",
            items_afectados=[i.sku for i in rec.items],
            mitigacion_sugerida="Reducir cobertura en SKUs de menor rotacion.",
        )
    ]


def strategy_tipo_cambio(rec: Recomendacion) -> list[Vulnerabilidad]:
    """Evalua sensibilidad a shock cambiario en proveedores externos."""
    externos = [i for i in rec.items if "ASIA" in i.proveedor_id or "EUR" in i.proveedor_id]
    if not externos:
        return []
    costo_externo = sum(i.costo_total for i in externos)
    shock = costo_externo * 0.2
    return [
        Vulnerabilidad(
            tipo="TIPO_CAMBIO_ADVERSO",
            descripcion="Un movimiento adverso de tipo de cambio impactaria el costo total.",
            probabilidad_estimada=0.25,
            impacto_usd_esperado=round(shock, 2),
            impacto_usd_p95=round(shock * 1.35, 2),
            severidad="MEDIA" if shock < 15000 else "ALTA",
            items_afectados=[i.sku for i in externos],
            mitigacion_sugerida="Cerrar precio anticipado o cubrir parcialmente moneda.",
        )
    ]
