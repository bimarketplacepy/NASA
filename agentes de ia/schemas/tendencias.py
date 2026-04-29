"""Schemas para deteccion de tendencias."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class FuenteTendencia(BaseModel):
    """Fuente observada de tendencia."""

    plataforma: Literal["TIKTOK", "INSTAGRAM", "PINTEREST", "GOOGLE_TRENDS", "REDDIT", "FORO"]
    url: str | None = None
    fecha_observacion: datetime
    metricas: dict = Field(default_factory=dict)


class TendenciaDetectada(BaseModel):
    """Producto emergente detectado."""

    tendencia_id: str
    producto_emergente: str
    categoria_estimada: str
    motivo_viralidad: str
    fuentes: list[FuenteTendencia]
    nivel_confianza: float
    velocidad_crecimiento: float
    fecha_deteccion: datetime
    estado: Literal["PROVISIONAL", "VALIDADO", "DESCARTADO"]
    semanas_anticipacion_estimadas: int


class NodoProvisional(BaseModel):
    """Nodo temporal para inyeccion en ontologia."""

    nodo_id: str
    tipo: Literal["producto", "proveedor", "tendencia"]
    datos: dict = Field(default_factory=dict)
    origen: Literal["web_research", "tendencia", "manual"]
    confianza: float
    fuentes: list[str] = Field(default_factory=list)
    fecha_creacion: datetime
    requiere_revision: bool
