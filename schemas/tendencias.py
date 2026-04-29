"""Schemas canonicos de tendencias para integracion Tarea 5 (Mateo).

Estos modelos son el contrato wire entre el pipeline de Mateo y mi
Tarea 1. NO se modifican unilateralmente - cualquier cambio se discute.

Es deliberadamente compatible con `integrations.trend_signal.TrendSignalIn`:
las dos representaciones expresan el mismo concepto, una es la
canonica del scraper (Mateo), la otra es la del ACL (mia con validators).
La funcion `to_intake()` mapea TrendSignal -> TrendSignalIn.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# Enums
# =============================================================================


class FuenteTrend(str, Enum):
    """Plataformas de origen de la senal."""

    TIKTOK = "TIKTOK"
    INSTAGRAM = "INSTAGRAM"
    PINTEREST = "PINTEREST"
    GOOGLE_TRENDS = "GOOGLE_TRENDS"
    OTHER = "OTHER"


# =============================================================================
# Modelos
# =============================================================================


class ProductoSimilar(BaseModel):
    """Producto del catalogo similar a una TrendSignal."""

    model_config = ConfigDict(extra="ignore")

    sku: str = Field(..., min_length=1)
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    nombre: str = ""
    categoria: str = ""
    precio_referencia: float = 0.0


class TrendOutputCincoCampos(BaseModel):
    """Contrato de 5 campos que Mateo extrae del LLM (pre-enriquecimiento)."""

    model_config = ConfigDict(extra="ignore")

    descripcion: str = Field(..., min_length=10, max_length=500)
    fuente: str
    velocidad_crecimiento: float = Field(..., ge=0.0, le=1000.0)
    confianza_extraccion: float = Field(..., ge=0.0, le=1.0)
    productos_existentes_similares: list[Any] = Field(default_factory=list)


class TrendSignal(BaseModel):
    """TrendSignal canonico post-pipeline de Mateo.

    Diferencias con TrendSignalIn (mi ACL):
    - tiene `palabras_clave`, `metadata_fuente`, `validado_shacl`,
      `provisional` que el ACL puede ignorar.
    - productos_existentes_similares es list[ProductoSimilar] (rico),
      no list[dict] crudo.
    """

    model_config = ConfigDict(extra="ignore")

    trend_id: str = Field(..., min_length=1)
    descripcion: str = Field(..., min_length=10, max_length=500)
    palabras_clave: list[str] = Field(default_factory=list)
    fuente: str
    fecha_deteccion: datetime
    metadata_fuente: dict[str, Any] = Field(default_factory=dict)
    velocidad_crecimiento: float = Field(..., ge=0.0, le=1000.0)
    confianza_extraccion: float = Field(..., ge=0.0, le=1.0)
    productos_existentes_similares: list[ProductoSimilar] = Field(default_factory=list)
    validado_shacl: bool = False
    provisional: bool = True

    @field_validator("fecha_deteccion", mode="before")
    @classmethod
    def _parse_fecha(cls, v: Any) -> datetime:
        if isinstance(v, datetime):
            return v.astimezone(timezone.utc) if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if isinstance(v, str):
            s = v.strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        raise ValueError(f"fecha_deteccion no es ISO-8601 ni datetime: {v!r}")


class NodoProvisional(BaseModel):
    """Nodo provisional para inyectar al grafo (mock OntologiaClient)."""

    model_config = ConfigDict(extra="ignore")

    nodo_id: str
    tipo: str = "tendencia"
    datos: dict[str, Any] = Field(default_factory=dict)
    origen: str = "tendencia"
    confianza: float = 0.0
    fuentes: list[str] = Field(default_factory=list)
    fecha_creacion: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    requiere_revision: bool = False
