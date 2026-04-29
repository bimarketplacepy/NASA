"""DataLoader: lee productos del catalogo Pegasus (CSV o Neo4j v1).

trends_service.py espera `data_loader.load_productos() -> dict[sku, Producto]`.
Implementamos via dos backends:

1. Neo4j v1 (preferido): si OntologyClient v1 esta disponible.
2. Fallback CSV: si hay un productos.csv en data/.
3. Fallback minimal: lista hardcoded chica para testing offline.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from schemas.productos import Producto


_PROYECTO_ROOT = Path(__file__).resolve().parent.parent
_CSV_DEFAULT = _PROYECTO_ROOT / "data" / "productos.csv"


class DataLoader:
    """Carga productos del catalogo. Cache en memoria por instancia."""

    def __init__(self, csv_path: Path | str | None = None) -> None:
        self.csv_path = Path(csv_path) if csv_path is not None else _CSV_DEFAULT
        self._cache: dict[str, Producto] | None = None

    def load_productos(self) -> dict[str, Producto]:
        """Carga productos. Idempotente.

        Returns:
            dict {sku: Producto}.
        """
        if self._cache is not None:
            return self._cache

        productos: dict[str, Producto] = {}

        # 1. Intentar Neo4j v1 OntologyClient (puede no estar disponible)
        productos = self._cargar_desde_neo4j()
        if productos:
            self._cache = productos
            return productos

        # 2. CSV
        productos = self._cargar_desde_csv()
        if productos:
            self._cache = productos
            return productos

        # 3. Minimal hardcoded (smoke testing offline)
        productos = self._cargar_minimal()
        self._cache = productos
        return productos

    def _cargar_desde_neo4j(self) -> dict[str, Producto]:
        try:
            # OntologyClient v1 podria no estar configurado en el sandbox
            from ontology import OntologyClient

            with OntologyClient() as ont:
                productos_raw = ont.productos_top(1000)  # asume API existente
            return {
                str(p.get("sku", "")): Producto(**p)
                for p in productos_raw
                if p.get("sku")
            }
        except Exception:
            return {}

    def _cargar_desde_csv(self) -> dict[str, Producto]:
        if not self.csv_path.exists():
            return {}
        productos: dict[str, Producto] = {}
        try:
            with open(self.csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sku = str(row.get("sku", "")).strip()
                    if not sku:
                        continue
                    try:
                        productos[sku] = Producto(
                            sku=sku,
                            nombre=str(row.get("nombre", "")).strip(),
                            nombre_corto=str(row.get("nombre_corto", "")).strip(),
                            categoria_id=str(row.get("categoria_id", row.get("categoria", ""))).strip(),
                            grupo_id=str(row.get("grupo_id", row.get("grupo", ""))).strip(),
                            precio_referencia=float(row.get("precio_referencia", 0.0) or 0.0),
                            pais_origen=str(row.get("pais_origen", "")).strip(),
                            perecedero=str(row.get("perecedero", "false")).lower() in ("true", "1", "yes"),
                        )
                    except (ValueError, TypeError):
                        continue
        except OSError:
            return {}
        return productos

    def _cargar_minimal(self) -> dict[str, Producto]:
        """Set minimal de productos navidenos para smoke testing offline."""
        seed: list[dict[str, Any]] = [
            {"sku": "247329", "nombre": "ESFERA DECOR 10X10 DORADA",
             "categoria_id": "DECORACION", "grupo_id": "ESFERAS",
             "precio_referencia": 4500.0, "pais_origen": "PY"},
            {"sku": "247330", "nombre": "ESFERA NAVIDENA 8CM DORADA",
             "categoria_id": "DECORACION", "grupo_id": "ESFERAS",
             "precio_referencia": 3800.0, "pais_origen": "PY"},
            {"sku": "230101", "nombre": "ARBOL ARTIFICIAL 1.80M PRELIT",
             "categoria_id": "ARBOLES", "grupo_id": "ARBOLES_ARTIF",
             "precio_referencia": 89000.0, "pais_origen": "CN"},
            {"sku": "230102", "nombre": "ARBOL ARTIFICIAL 2.10M LED",
             "categoria_id": "ARBOLES", "grupo_id": "ARBOLES_ARTIF",
             "precio_referencia": 125000.0, "pais_origen": "CN"},
            {"sku": "250541", "nombre": "FIG SANTA 27CM",
             "categoria_id": "FIGURAS", "grupo_id": "FIG_SANTA",
             "precio_referencia": 8900.0, "pais_origen": "CN"},
            {"sku": "246295", "nombre": "ESFERA NAVIDENA NUEVA",
             "categoria_id": "VARIOS", "grupo_id": "VARIOS",
             "precio_referencia": 2500.0, "pais_origen": "PY"},
            {"sku": "43208", "nombre": "GUIRNALDA PY",
             "categoria_id": "DECORACION", "grupo_id": "GUIRNALDAS",
             "precio_referencia": 12000.0, "pais_origen": "PY"},
            {"sku": "190886", "nombre": "TAZA NAVIDENA",
             "categoria_id": "BAZAR", "grupo_id": "TAZAS",
             "precio_referencia": 4200.0, "pais_origen": "CN"},
        ]
        return {p["sku"]: Producto(**p) for p in seed}
