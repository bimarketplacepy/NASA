"""Dispatcher de REFERENCIA — para que Abi tenga el contrato esperado.

NOTA IMPORTANTE: este NO es el dispatcher final. El dispatcher real vive en
la capa de razonamiento formal de Abi (Bloque 7), que usa OWL/SHACL/HermiT
y logica deontica defeasible para decidir.

Este archivo solo expone la interfaz que Abi necesita imitar/superar y sirve
como fallback funcional cuando el razonador formal no esta disponible.

Uso:
    from optimization.dispatcher_ref import DispatcherReferencia
    d = DispatcherReferencia()
    rec = d.decidir(ctx, restricciones=[])
"""

from __future__ import annotations

import logging
from typing import Optional

from optimization.algorithms import (
    ALGORITMOS_DISPONIBLES,
    AffineSimpleAlgorithm,
    BaseAlgorithm,
    ColdInheritAlgorithm,
    InvBufferAlgorithm,
    OpenLoopAlgorithm,
    RobustSatisficingAlgorithm,
    SafetyStockAlgorithm,
    crear_algoritmo,
)
from optimization.schemas import (
    DecisionContext,
    RecomendacionCompra,
    Restriccion,
)

logger = logging.getLogger(__name__)


class DispatcherReferencia:
    """Dispatcher de referencia (NO es el formal de Abi).

    Aplica reglas heuristicas para elegir un algoritmo de la biblioteca.
    Es transparente: explica por que eligio cada uno via el campo
    ``razon_eleccion`` de la recomendacion.

    Reglas aplicadas (en orden):
        1. Si presupuesto < cantidad_objetivo * precio_min  ->  robust_satisficing
        2. Si forecast.fuente == 'inherited' o sku_donante  ->  cold_inherit
        3. Si semanas_efectivas >= 52 y volatilidad <= 0.45  ->  affine_simple
        4. Si es_perecedero o (semanas >= 8 y volatilidad <= 0.4) ->  inv_buffer
        5. Si semanas_efectivas >= 4 y prioridad_critica  ->  safety_stock
        6. Fallback                                         ->  open_loop
    """

    def __init__(self) -> None:
        self._instancias: dict[str, BaseAlgorithm] = {}

    def _get(self, algoritmo_id: str) -> BaseAlgorithm:
        if algoritmo_id not in self._instancias:
            self._instancias[algoritmo_id] = crear_algoritmo(algoritmo_id)
        return self._instancias[algoritmo_id]

    def elegir_algoritmo(self, ctx: DecisionContext) -> str:
        """Devuelve el ID del algoritmo elegido para el contexto.

        El dispatcher real de Abi va a usar OWL/SHACL para esto. Este es solo
        un fallback heuristico.
        """
        f = ctx.forecast
        caract = f.caracteristicas_serie

        # 1) Cash-tight: el costo minimo posible no entra en el presupuesto a p50
        if ctx.proveedores_candidatos and ctx.presupuesto_disponible > 0:
            precio_min = min(p.precio_unitario for p in ctx.proveedores_candidatos)
            costo_p50 = f.p50_demanda * precio_min
            if ctx.presupuesto_disponible < costo_p50 * 1.1:
                return RobustSatisficingAlgorithm.id

        # 2) Cold-start con donante
        if f.fuente == "inherited" or ctx.sku_donante:
            return ColdInheritAlgorithm.id

        # 3) Historial extenso y baja volatilidad - affine policy
        if caract.semanas_efectivas >= 52 and caract.volatilidad <= 0.45:
            return AffineSimpleAlgorithm.id

        # 4) Perecedero o historial moderado con baja volatilidad - inv_buffer
        if ctx.es_perecedero or (caract.semanas_efectivas >= 8 and caract.volatilidad <= 0.40):
            return InvBufferAlgorithm.id

        # 5) Historial corto - safety_stock conservador
        if caract.semanas_efectivas >= 4:
            return SafetyStockAlgorithm.id

        # 6) Fallback total
        return OpenLoopAlgorithm.id

    def decidir(
        self,
        ctx: DecisionContext,
        restricciones: Optional[list[Restriccion]] = None,
        algoritmo_forzado: Optional[str] = None,
    ) -> RecomendacionCompra:
        """Elige un algoritmo y lo ejecuta.

        Args:
            ctx: contexto de decision.
            restricciones: restricciones deonticas (vacio si no se proveen).
            algoritmo_forzado: si se especifica, ignora la heuristica de
                seleccion y usa este ID.

        Returns:
            ``RecomendacionCompra`` con el algoritmo elegido.

        Raises:
            ValueError: si el algoritmo elegido no aplica al contexto.
        """
        restricciones = restricciones or []
        alg_id = algoritmo_forzado or self.elegir_algoritmo(ctx)
        alg = self._get(alg_id)

        if not alg.precondiciones(ctx):
            logger.warning(
                "Algoritmo %s elegido pero no cumple precondiciones para SKU %s, "
                "fallback a open_loop",
                alg_id, ctx.sku,
            )
            alg = self._get(OpenLoopAlgorithm.id)

        rec = alg.run(ctx, restricciones)
        rec.razon_eleccion.insert(
            0,
            f"Dispatcher de referencia eligio '{alg.id}' "
            f"(no es el dispatcher formal de Abi)",
        )
        return rec


def listar_algoritmos_aplicables(ctx: DecisionContext) -> list[str]:
    """Devuelve los IDs de algoritmos cuyas precondiciones se cumplen para ctx."""
    aplicables = []
    for alg_id in ALGORITMOS_DISPONIBLES:
        alg = crear_algoritmo(alg_id)
        if alg.precondiciones(ctx):
            aplicables.append(alg_id)
    return aplicables


if __name__ == "__main__":
    from optimization.schemas import ProveedorCandidato
    from optimization.stubs.forecast_stub import obtener_forecast

    forecast = obtener_forecast("SKU_001")
    proveedor = ProveedorCandidato(
        proveedor_id="PROV_NAC_01", nombre="Test",
        precio_unitario=10.0, moq=50, lead_time_dias=7, confiabilidad=0.9,
    )
    ctx = DecisionContext(
        sku="SKU_001",
        forecast=forecast,
        proveedores_candidatos=[proveedor],
        presupuesto_disponible=15000.0,
    )

    dispatcher = DispatcherReferencia()
    elegido = dispatcher.elegir_algoritmo(ctx)
    aplicables = listar_algoritmos_aplicables(ctx)
    print(f"Dispatcher eligio: {elegido}")
    print(f"Algoritmos aplicables al contexto: {aplicables}")
    rec = dispatcher.decidir(ctx, restricciones=[])
    print(f"Recomendacion: cant={rec.cantidad_central}, costo=USD {rec.costo_esperado:.2f}")
