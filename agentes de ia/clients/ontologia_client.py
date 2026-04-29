"""Cliente mock de ontologia, reemplazable por Neo4j."""

from __future__ import annotations

import json
from pathlib import Path

from clients.data_loader import get_data_loader
from schemas.productos import Categoria
from schemas.proveedores import Proveedor, RelacionComercial
from schemas.tendencias import NodoProvisional


GRAFO_PATH = Path(__file__).resolve().parent.parent / "data" / "grafo_provisional.json"


class OntologiaClient:
    """API publica estable para futura integracion con Neo4j."""

    def __init__(self) -> None:
        self.loader = get_data_loader()

    def proveedores_de_sku(self, sku: str) -> list[Proveedor]:
        """Retorna proveedores que comercializan un SKU."""
        relaciones = [r for r in self.loader.load_relaciones() if r.sku == sku and r.activo]
        proveedores = self.loader.load_proveedores()
        return [proveedores[r.proveedor_id] for r in relaciones if r.proveedor_id in proveedores]

    def categoria_de_sku(self, sku: str) -> Categoria:
        """Retorna categoria de un SKU."""
        productos = self.loader.load_productos()
        categorias = self.loader.load_categorias()
        producto = productos.get(sku)
        if producto is None:
            raise ValueError(f"SKU no encontrado: {sku}")
        categoria = categorias.get(producto.categoria_id)
        if categoria is None:
            raise ValueError(f"Categoria no encontrada para SKU {sku}")
        return categoria

    def sustitutos_de_sku(self, sku: str) -> list[str]:
        """Retorna sustitutos simples por misma categoria."""
        productos = self.loader.load_productos()
        if sku not in productos:
            return []
        categoria_id = productos[sku].categoria_id
        return [
            p.sku
            for p in productos.values()
            if p.categoria_id == categoria_id and p.sku != sku
        ][:5]

    def proveedores_similares(self, proveedor_id: str, k: int = 3) -> list[Proveedor]:
        """Busca proveedores cercanos por region y confiabilidad."""
        proveedores = list(self.loader.load_proveedores().values())
        base = next((p for p in proveedores if p.proveedor_id == proveedor_id), None)
        if base is None:
            return []
        ranked = sorted(
            [p for p in proveedores if p.proveedor_id != proveedor_id],
            key=lambda p: (
                p.region != base.region,
                abs(p.confiabilidad - base.confiabilidad),
                abs(p.reputacion_score - base.reputacion_score),
            ),
        )
        return ranked[:k]

    def relacion_comercial(self, sku: str, proveedor_id: str) -> RelacionComercial:
        """Retorna relacion comercial puntual."""
        relaciones = self.loader.load_relaciones()
        rel = next((r for r in relaciones if r.sku == sku and r.proveedor_id == proveedor_id), None)
        if rel is None:
            raise ValueError(f"Relacion no encontrada para sku={sku} proveedor={proveedor_id}")
        return rel

    def inyectar_nodo_provisional(self, nodo: NodoProvisional) -> bool:
        """Inserta/merge nodo provisional en JSON local."""
        graph = self._load_graph()
        nodos = graph.setdefault("nodos_provisionales", [])
        payload = nodo.model_dump(mode="json")
        replaced = False
        for idx, existing in enumerate(nodos):
            if existing.get("nodo_id") == nodo.nodo_id:
                nodos[idx] = payload
                replaced = True
                break
        if not replaced:
            nodos.append(payload)
        self._save_graph(graph)
        return True

    def listar_nodos_provisionales(self) -> list[NodoProvisional]:
        """Lista nodos provisionales del grafo."""
        graph = self._load_graph()
        raw = graph.get("nodos_provisionales", [])
        return [NodoProvisional(**item) for item in raw]

    def vecinos(self, nodo_id: str, tipo_relacion: str | None = None) -> list[dict]:
        """Retorna vecinos desde aristas mock del grafo."""
        graph = self._load_graph()
        aristas = graph.get("aristas", [])
        vecinos: list[dict] = []
        for arista in aristas:
            if arista.get("source_id") != nodo_id and arista.get("target_id") != nodo_id:
                continue
            if tipo_relacion and arista.get("tipo_relacion") != tipo_relacion:
                continue
            vecinos.append(arista)
        return vecinos

    def _load_graph(self) -> dict:
        if not GRAFO_PATH.exists():
            return {"nodos_provisionales": [], "aristas": []}
        return json.loads(GRAFO_PATH.read_text(encoding="utf-8"))

    def _save_graph(self, data: dict) -> None:
        GRAFO_PATH.parent.mkdir(parents=True, exist_ok=True)
        GRAFO_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
