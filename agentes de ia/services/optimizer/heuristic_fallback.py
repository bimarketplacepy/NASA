"""Heuristica greedy para generar solucion factible rapida.

Este modulo se usa cuando el solver exacto no converge o como punto de
partida incremental para la fase de optimizacion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from clients.data_loader import DataLoader
from schemas.eventos import EventoComercial
from schemas.recomendaciones import ItemCompra
from schemas.simulacion import ForecastResult


@dataclass(frozen=True)
class HeuristicResult:
    """Resultado estructurado de la heuristica."""

    items: list[ItemCompra]
    heuristic_used: bool
    notes: list[str]


class HeuristicOptimizer:
    """Generador greedy de plan de compra.

    Reglas:
    1. SKU por SKU, elegir proveedor viable mas barato.
    2. Respetar MOQ.
    3. Aplicar multiplicador por aversion a stockout.
    4. Recortar por presupuesto si excede.
    """

    def __init__(self, data_loader: DataLoader) -> None:
        self.data_loader = data_loader

    def build_plan(
        self,
        skus_objetivo: list[str],
        forecasts: dict[str, ForecastResult],
        evento: EventoComercial,
        presupuesto: float | None,
        aversion_stockout: float,
        proveedores_excluidos: list[str] | None = None,
    ) -> HeuristicResult:
        """Construye plan factible por heuristica.

        Args:
            skus_objetivo: SKUs a optimizar.
            forecasts: Pronosticos por SKU.
            evento: Evento comercial objetivo.
            presupuesto: Tope de gasto opcional.
            aversion_stockout: Peso de cobertura extra [0, 1].
            proveedores_excluidos: Lista de proveedores bloqueados.

        Returns:
            Resultado heuristico con items y notas.
        """
        excluded = set(proveedores_excluidos or [])
        relaciones = self.data_loader.load_relaciones()
        proveedores = self.data_loader.load_proveedores()

        items: list[ItemCompra] = []
        notes: list[str] = []
        today = date.today()

        for sku in skus_objetivo:
            if sku not in forecasts:
                notes.append(f"SKU {sku} omitido: no hay forecast.")
                continue

            demand = max(0.0, forecasts[sku].p50)
            coverage_multiplier = 1.0 + (0.35 * aversion_stockout)
            target_qty = int(round(demand * coverage_multiplier))

            rels = [
                r
                for r in relaciones
                if r.sku == sku and r.activo and r.proveedor_id not in excluded and r.proveedor_id in proveedores
            ]
            if not rels:
                notes.append(f"SKU {sku} omitido: sin proveedores viables.")
                continue

            # Priorizamos costo unitario, con bonus a mejor confiabilidad.
            rels_sorted = sorted(
                rels,
                key=lambda r: (r.precio_unitario, -proveedores[r.proveedor_id].confiabilidad),
            )
            best = rels_sorted[0]
            qty = max(target_qty, int(best.moq))
            descuento = self._discount_for_qty(qty, best)
            unit_cost_effective = float(best.precio_unitario * (1.0 - descuento))
            total_cost = unit_cost_effective * qty

            lead_days = int(
                (proveedores[best.proveedor_id].lead_time_dias_min + proveedores[best.proveedor_id].lead_time_dias_max)
                / 2
            )
            arrival = today + timedelta(days=lead_days)
            # Pedido conservador: salir hoy para no romper ventana en esta fase.
            pedido = today
            buffer_weeks = max(0.0, (evento.fecha_objetivo - arrival).days / 7.0)

            items.append(
                ItemCompra(
                    sku=sku,
                    proveedor_id=best.proveedor_id,
                    cantidad=qty,
                    costo_unitario=round(unit_cost_effective, 4),
                    descuento_aplicado=round(descuento, 4),
                    costo_total=round(total_cost, 2),
                    fecha_pedido_estimada=pedido,
                    fecha_arribo_estimada=arrival,
                    semanas_buffer_pre_evento=round(buffer_weeks, 2),
                )
            )

        if presupuesto is not None:
            items = self._trim_to_budget(items, presupuesto, notes)

        return HeuristicResult(items=items, heuristic_used=True, notes=notes)

    def _discount_for_qty(self, qty: int, rel) -> float:
        """Calcula descuento efectivo por tramos."""
        best = 0.0
        for tramo in rel.descuentos_volumen:
            if qty >= tramo.cantidad_minima:
                best = max(best, float(tramo.descuento_porcentaje))
        return best

    def _trim_to_budget(self, items: list[ItemCompra], presupuesto: float, notes: list[str]) -> list[ItemCompra]:
        """Recorta items hasta cumplir presupuesto.

        Estrategia:
        - Ordenar por costo total descendente.
        - Reducir a MOQ implícito (50% como aproximacion segura) y luego eliminar.
        """
        total = sum(i.costo_total for i in items)
        if total <= presupuesto:
            return items

        notes.append(f"Recorte por presupuesto activado: total={total:.2f} presupuesto={presupuesto:.2f}")
        adjusted = sorted(items, key=lambda x: x.costo_total, reverse=True)

        for idx, item in enumerate(adjusted):
            if total <= presupuesto:
                break
            reduced_qty = max(1, int(item.cantidad * 0.5))
            if reduced_qty < item.cantidad:
                new_total = round(reduced_qty * item.costo_unitario, 2)
                total -= item.costo_total - new_total
                adjusted[idx] = item.model_copy(update={"cantidad": reduced_qty, "costo_total": new_total})

        final_items: list[ItemCompra] = []
        for item in adjusted:
            if total <= presupuesto:
                final_items.append(item)
                continue
            total -= item.costo_total
            notes.append(f"Item removido por presupuesto: {item.sku}/{item.proveedor_id}")

        return final_items
