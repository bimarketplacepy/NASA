"""Stub del DeonticResolver de Abi (capa deontica - Bloque 5).

Genera restricciones verosimiles segun el contexto, simulando el comportamiento
del razonador formal real. Las firmas (``evaluar_restricciones`` y
``accion_bloqueada``) coinciden con las que entregara Abi.

Cuando Abi entregue su modulo real:

    # ANTES
    from optimization.stubs.deontic_stub import DeonticResolverStub

    # DESPUES
    from ontology_semantic.deontic import DeonticResolver
"""

from __future__ import annotations

from optimization.schemas import DecisionContext, Restriccion


class DeonticResolverStub:
    """STUB del razonador deontico.

    Implementa una version simplificada de las normas que estan en
    ``shapes.ttl`` y ``deontic_rules.ttl`` de Abi. Las firmas son las
    finales — solo cambia la implementacion.
    """

    def evaluar_restricciones(self, ctx: DecisionContext) -> list[Restriccion]:
        """Devuelve las restricciones que aplican al contexto.

        Reglas implementadas (subset del razonador real de Abi):

        - **N-STUB-001**: si el presupuesto es bajo, recomienda proveedor local.
        - **N-STUB-002**: si la volatilidad es alta, exige buffer de seguridad.
        - **N-STUB-003**: si hay TrendSignal con alta confianza, exige doble proveedor.
        - **N-STUB-004**: si es perecedero, prohibe exceder dias de validez.
        - **N-STUB-005**: si hay sku_donante (cold-start heredado), exige confianza minima.
        """
        restricciones: list[Restriccion] = []
        caract = ctx.forecast.caracteristicas_serie

        # N-STUB-001 - Presupuesto bajo - preferir nacional
        if ctx.presupuesto_disponible < 5000:
            restricciones.append(
                Restriccion(
                    tipo="preferir_proveedor_local",
                    parametros={"region_preferida": "nacional"},
                    fuente_norma_id="N-STUB-001",
                    severidad="recomendada",
                )
            )

        # N-STUB-002 - Alta volatilidad - buffer minimo
        if caract.volatilidad > 0.25:
            restricciones.append(
                Restriccion(
                    tipo="buffer_minimo",
                    parametros={"factor_seguridad": 1.3},
                    fuente_norma_id="N-STUB-002",
                    severidad="obligatoria",
                )
            )

        # N-STUB-003 - Trend con alta confianza - doble proveedor
        if ctx.trend_signal and ctx.trend_signal.confianza_extraccion > 0.7:
            restricciones.append(
                Restriccion(
                    tipo="min_proveedores",
                    parametros={"cantidad": 2},
                    fuente_norma_id="N-STUB-003",
                    severidad="obligatoria",
                )
            )

        # N-STUB-004 - Perecedero - no exceder dias_validez
        if ctx.es_perecedero and ctx.dias_validez:
            restricciones.append(
                Restriccion(
                    tipo="no_exceder_dias_validez",
                    parametros={"dias_validez": ctx.dias_validez},
                    fuente_norma_id="N-STUB-004",
                    severidad="obligatoria",
                )
            )

        # N-STUB-005 - Cold-start heredado con confianza baja - revisar manualmente
        if ctx.forecast.fuente == "inherited" and ctx.forecast.confianza_global < 0.5:
            restricciones.append(
                Restriccion(
                    tipo="requerir_revision_humana",
                    parametros={"motivo": "confianza_inherited_baja"},
                    fuente_norma_id="N-STUB-005",
                    severidad="recomendada",
                )
            )

        # N-STUB-006 - Cap de presupuesto - costo total no puede superar disponible
        restricciones.append(
            Restriccion(
                tipo="cap_presupuesto",
                parametros={"max_usd": ctx.presupuesto_disponible},
                fuente_norma_id="N-STUB-006",
                severidad="obligatoria",
            )
        )

        return restricciones

    def accion_bloqueada(self, ctx: DecisionContext) -> tuple[bool, str]:
        """Indica si la decision esta prohibida (no debe ejecutarse).

        Returns:
            ``(True, razon)`` si esta bloqueada, ``(False, "")`` si no.
        """
        # Perecedero con dias de validez insuficientes
        if ctx.es_perecedero and ctx.dias_validez is not None:
            min_lead_time = min(
                (p.lead_time_dias for p in ctx.proveedores_candidatos),
                default=999,
            )
            if min_lead_time >= ctx.dias_validez:
                return (
                    True,
                    f"N-STUB-004: perecedero con dias_validez={ctx.dias_validez} "
                    f"y lead_time minimo={min_lead_time} - inviable temporalmente",
                )

        # Sin proveedores candidatos no se puede comprar
        if not ctx.proveedores_candidatos:
            return True, "Sin proveedores candidatos disponibles"

        # Presupuesto en cero o negativo
        if ctx.presupuesto_disponible <= 0:
            return True, "Sin presupuesto disponible"

        return False, ""


if __name__ == "__main__":
    from optimization.schemas import ProveedorCandidato
    from optimization.stubs.forecast_stub import obtener_forecast

    forecast = obtener_forecast("SKU_004")
    proveedor = ProveedorCandidato(
        proveedor_id="PROV_NAC_01", nombre="Test", precio_unitario=10.0,
        moq=100, lead_time_dias=10, confiabilidad=0.9, region="nacional",
    )
    ctx = DecisionContext(
        sku="SKU_004", forecast=forecast,
        proveedores_candidatos=[proveedor], presupuesto_disponible=3000.0,
    )

    resolver = DeonticResolverStub()
    bloqueada, razon = resolver.accion_bloqueada(ctx)
    print(f"Bloqueada? {bloqueada} - {razon}")

    restricciones = resolver.evaluar_restricciones(ctx)
    print(f"Restricciones detectadas: {len(restricciones)}")
    for r in restricciones:
        print(f"  - [{r.severidad}] {r.tipo}: {r.parametros}  ({r.fuente_norma_id})")
