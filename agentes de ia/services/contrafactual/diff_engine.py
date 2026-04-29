"""Motor de diferencias entre recomendacion base y alterna."""

from __future__ import annotations

from schemas.contrafactual import DiffPlan
from schemas.recomendaciones import ItemCompra, Recomendacion


def compute_diff(base: Recomendacion, alterna: Recomendacion) -> DiffPlan:
    """Computa diff estructurado entre dos planes.

    Args:
        base: Recomendacion base.
        alterna: Recomendacion alternativa.

    Returns:
        DiffPlan con cambios por item y deltas agregados.
    """
    base_map = {(i.sku, i.proveedor_id): i for i in base.items}
    alt_map = {(i.sku, i.proveedor_id): i for i in alterna.items}

    keys_base = set(base_map)
    keys_alt = set(alt_map)

    added = [alt_map[k] for k in sorted(keys_alt - keys_base)]
    removed = [base_map[k] for k in sorted(keys_base - keys_alt)]

    modified: list[dict] = []
    for k in sorted(keys_base & keys_alt):
        b = base_map[k]
        a = alt_map[k]
        if (b.cantidad != a.cantidad) or (abs(b.costo_unitario - a.costo_unitario) > 1e-9):
            modified.append(
                {
                    "sku": b.sku,
                    "proveedor_id": b.proveedor_id,
                    "antes": b.model_dump(mode="json"),
                    "despues": a.model_dump(mode="json"),
                }
            )

    base_suppliers = {i.proveedor_id for i in base.items}
    alt_suppliers = {i.proveedor_id for i in alterna.items}

    return DiffPlan(
        items_agregados=added,
        items_removidos=removed,
        items_modificados=modified,
        delta_costo_total=alterna.presupuesto_consumido - base.presupuesto_consumido,
        delta_retorno_esperado=alterna.metricas.retorno_esperado - base.metricas.retorno_esperado,
        delta_var=alterna.metricas.var_95 - base.metricas.var_95,
        nuevos_proveedores_incluidos=sorted(alt_suppliers - base_suppliers),
        proveedores_excluidos=sorted(base_suppliers - alt_suppliers),
    )
