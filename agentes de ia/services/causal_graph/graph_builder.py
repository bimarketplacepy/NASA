"""Constructor de grafos causales desde recomendaciones."""

from __future__ import annotations

from schemas.grafo_causal import AristaCausal, GrafoCausal, NodoCausal
from schemas.recomendaciones import Recomendacion


def build_graph_from_recommendation(rec: Recomendacion) -> GrafoCausal:
    """Construye un grafo causal base para explicar una recomendacion."""
    nodos: list[NodoCausal] = []
    aristas: list[AristaCausal] = []

    event_node_id = f"evento:{rec.evento_objetivo_id}"
    nodos.append(
        NodoCausal(
            id=event_node_id,
            tipo="evento",
            label=rec.evento_objetivo_id,
            peso_influencia=1.0,
            metadata={"recomendacion_id": rec.recomendacion_id},
        )
    )

    total_qty = max(1, sum(i.cantidad for i in rec.items))
    seen_nodes = {event_node_id}

    for item in rec.items:
        sku_node = f"sku:{item.sku}"
        prov_node = f"prov:{item.proveedor_id}"
        if sku_node not in seen_nodes:
            nodos.append(
                NodoCausal(
                    id=sku_node,
                    tipo="sku",
                    label=item.sku,
                    peso_influencia=round(item.cantidad / total_qty, 4),
                    metadata={"cantidad": item.cantidad, "costo_total": item.costo_total},
                )
            )
            seen_nodes.add(sku_node)
        if prov_node not in seen_nodes:
            nodos.append(
                NodoCausal(
                    id=prov_node,
                    tipo="proveedor",
                    label=item.proveedor_id,
                    peso_influencia=round(item.costo_total / max(1.0, rec.presupuesto_consumido), 4),
                    metadata={"costo_total": item.costo_total},
                )
            )
            seen_nodes.add(prov_node)

        aristas.append(
            AristaCausal(
                source_id=event_node_id,
                target_id=sku_node,
                tipo_relacion="AFECTA",
                peso=round(item.cantidad / total_qty, 4),
                explicacion="El evento objetivo incrementa demanda del SKU.",
            )
        )
        aristas.append(
            AristaCausal(
                source_id=sku_node,
                target_id=prov_node,
                tipo_relacion="SUMINISTRA",
                peso=round(item.costo_total / max(1.0, rec.presupuesto_consumido), 4),
                explicacion="El proveedor participa en el abastecimiento del SKU.",
            )
        )

    for vuln in rec.vulnerabilidades:
        vuln_id = f"vuln:{vuln.tipo}:{len(vuln.items_afectados)}"
        nodos.append(
            NodoCausal(
                id=vuln_id,
                tipo="vulnerabilidad",
                label=vuln.tipo,
                peso_influencia=min(1.0, vuln.impacto_usd_esperado / max(1.0, rec.presupuesto_consumido)),
                metadata={"severidad": vuln.severidad, "impacto_p95": vuln.impacto_usd_p95},
            )
        )
        for sku in vuln.items_afectados:
            aristas.append(
                AristaCausal(
                    source_id=vuln_id,
                    target_id=f"sku:{sku}",
                    tipo_relacion="INFLUYE_NEGATIVO",
                    peso=0.8,
                    explicacion=vuln.descripcion,
                )
            )

    return GrafoCausal(
        grafo_id=f"GRAFO_{rec.recomendacion_id}",
        recomendacion_id=rec.recomendacion_id,
        nodos=nodos,
        aristas=aristas,
        nodo_central_id=event_node_id,
    )
