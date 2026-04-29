"""Schemas del dominio de proveedores."""

from typing import Literal

from pydantic import BaseModel, Field


class TramoDescuento(BaseModel):
    """Regla de descuento por volumen."""

    cantidad_minima: int
    descuento_porcentaje: float


class Proveedor(BaseModel):
    """Entidad proveedor."""

    proveedor_id: str
    nombre: str
    pais: str
    region: Literal["nacional", "regional", "asia", "europa", "otros"]
    lead_time_dias_min: int
    lead_time_dias_max: int
    confiabilidad: float
    reputacion_score: float
    moneda: str
    permite_negociacion_volumen: bool
    contacto: dict = Field(default_factory=dict)


class RelacionComercial(BaseModel):
    """Relacion SKU-proveedor."""

    proveedor_id: str
    sku: str
    precio_unitario: float
    moq: int
    descuentos_volumen: list[TramoDescuento] = Field(default_factory=list)
    moneda: str
    activo: bool
