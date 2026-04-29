"""Carga y cache de datos CSV en memoria."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Any

import pandas as pd

from schemas.eventos import EventoComercial
from schemas.productos import Categoria, Producto
from schemas.proveedores import Proveedor, RelacionComercial, TramoDescuento


DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class DataLoader:
    """Singleton con lazy loading de datasets del dominio."""

    def __init__(self) -> None:
        self._productos: dict[str, Producto] | None = None
        self._categorias: dict[str, Categoria] | None = None
        self._proveedores: dict[str, Proveedor] | None = None
        self._relaciones: list[RelacionComercial] | None = None
        self._ventas: pd.DataFrame | None = None
        self._inventario: dict[str, int] | None = None
        self._eventos: list[EventoComercial] | None = None

    def _csv_path(self, filename: str) -> Path:
        path = DATA_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"No existe archivo de datos: {path}")
        return path

    def load_productos(self) -> dict[str, Producto]:
        """Carga el catalogo de productos indexado por SKU."""
        if self._productos is None:
            df = pd.read_csv(self._csv_path("catalogo_productos.csv"))
            self._productos = {}
            for _, row in df.iterrows():
                tags_raw = row.get("tags", "")
                tags = [t for t in str(tags_raw).split(";") if t] if pd.notna(tags_raw) else []
                vida_raw = row.get("vida_util_dias")
                vida_util = int(vida_raw) if pd.notna(vida_raw) else None
                item = Producto(
                    sku=str(row["sku"]),
                    nombre=str(row["nombre"]),
                    categoria_id=str(row["categoria_id"]),
                    perecedero=bool(row["perecedero"]),
                    vida_util_dias=vida_util,
                    precio_referencia=float(row["precio_referencia"]),
                    margen_objetivo=float(row["margen_objetivo"]),
                    descripcion=str(row["descripcion"]),
                    tags=tags,
                )
                self._productos[item.sku] = item
        return self._productos

    def load_categorias(self) -> dict[str, Categoria]:
        """Carga categorias indexadas por id."""
        if self._categorias is None:
            df = pd.read_csv(self._csv_path("categorias.csv"))
            self._categorias = {}
            for _, row in df.iterrows():
                patron_raw = str(row["patron_estacional"])
                patron = [float(x) for x in patron_raw.split(",") if x]
                categoria = Categoria(
                    categoria_id=str(row["categoria_id"]),
                    nombre=str(row["nombre"]),
                    patron_estacional=patron,
                    elasticidad_precio=float(row["elasticidad_precio"]),
                )
                self._categorias[categoria.categoria_id] = categoria
        return self._categorias

    def load_proveedores(self) -> dict[str, Proveedor]:
        """Carga proveedores indexados por id."""
        if self._proveedores is None:
            df = pd.read_csv(self._csv_path("proveedores.csv"))
            self._proveedores = {}
            for _, row in df.iterrows():
                contacto = {
                    "email": str(row.get("email", "")),
                    "telefono": str(row.get("telefono", "")),
                    "idioma_preferido": str(row.get("idioma_preferido", "es")),
                }
                prov = Proveedor(
                    proveedor_id=str(row["proveedor_id"]),
                    nombre=str(row["nombre"]),
                    pais=str(row["pais"]),
                    region=str(row["region"]),
                    lead_time_dias_min=int(row["lead_time_dias_min"]),
                    lead_time_dias_max=int(row["lead_time_dias_max"]),
                    confiabilidad=float(row["confiabilidad"]),
                    reputacion_score=float(row["reputacion_score"]),
                    moneda=str(row["moneda"]),
                    permite_negociacion_volumen=bool(row["permite_negociacion_volumen"]),
                    contacto=contacto,
                )
                self._proveedores[prov.proveedor_id] = prov
        return self._proveedores

    def load_relaciones(self) -> list[RelacionComercial]:
        """Carga relaciones comerciales SKU-proveedor."""
        if self._relaciones is None:
            df = pd.read_csv(self._csv_path("relacion_producto_proveedor.csv"))
            self._relaciones = []
            for _, row in df.iterrows():
                raw_discounts = str(row.get("descuentos_volumen", "")).strip()
                tramos: list[TramoDescuento] = []
                if raw_discounts:
                    for token in raw_discounts.split("|"):
                        qty, disc = token.split(":")
                        tramos.append(
                            TramoDescuento(
                                cantidad_minima=int(qty),
                                descuento_porcentaje=float(disc),
                            )
                        )

                rel = RelacionComercial(
                    proveedor_id=str(row["proveedor_id"]),
                    sku=str(row["sku"]),
                    precio_unitario=float(row["precio_unitario"]),
                    moq=int(row["moq"]),
                    descuentos_volumen=tramos,
                    moneda=str(row["moneda"]),
                    activo=bool(row["activo"]),
                )
                self._relaciones.append(rel)
        return self._relaciones

    def load_ventas_historicas(self) -> pd.DataFrame:
        """Carga dataframe de ventas historicas."""
        if self._ventas is None:
            self._ventas = pd.read_csv(self._csv_path("ventas_historicas.csv"))
        return self._ventas.copy()

    def load_inventario(self) -> dict[str, int]:
        """Carga inventario por SKU."""
        if self._inventario is None:
            df = pd.read_csv(self._csv_path("inventario_actual.csv"))
            self._inventario = {str(row["sku"]): int(row["inventario_actual"]) for _, row in df.iterrows()}
        return self._inventario

    def load_eventos(self) -> list[EventoComercial]:
        """Carga eventos comerciales."""
        if self._eventos is None:
            df = pd.read_csv(self._csv_path("eventos_comerciales.csv"))
            self._eventos = []
            for _, row in df.iterrows():
                # Nota: fecha_objetivo se setea aproximada para esta etapa.
                semana = int(row["semana_objetivo"])
                fecha = pd.Timestamp("2026-01-01") + pd.Timedelta(weeks=max(semana - 1, 0))
                evento = EventoComercial(
                    evento_id=str(row["evento_id"]),
                    nombre=str(row["nombre"]),
                    fecha_objetivo=fecha.date(),
                    semanas_pico=[semana],
                    boost_demanda=float(row["boost_demanda"]),
                )
                self._eventos.append(evento)
        return self._eventos

    def dump_snapshot(self) -> dict[str, Any]:
        """Devuelve estado resumido para debugging."""
        return {
            "productos": len(self.load_productos()),
            "categorias": len(self.load_categorias()),
            "proveedores": len(self.load_proveedores()),
            "relaciones": len(self.load_relaciones()),
            "eventos": len(self.load_eventos()),
        }

    def save_snapshot_json(self, output_path: Path) -> None:
        """Persistencia auxiliar de snapshot."""
        output_path.write_text(json.dumps(self.dump_snapshot(), indent=2), encoding="utf-8")


@lru_cache(maxsize=1)
def get_data_loader() -> DataLoader:
    """Devuelve una instancia singleton de DataLoader."""
    return DataLoader()
