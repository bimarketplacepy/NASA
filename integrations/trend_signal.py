"""TrendSignalIn: replica del contrato canonico de Mateo (Tarea 5).

Pydantic v2. Replica exacta de los 11 campos de schemas.tendencias.TrendSignal
con validators estrictos. NO importa el modulo de Mateo (depende de modulos
no empaquetados); el contrato vive aca local del lado mio del ACL.

Si Mateo termina de empaquetar sus schemas, podemos agregar un
`from_external(ts)` classmethod que tome su pydantic model y devuelva
TrendSignalIn — pero el formato de wire (JSON) ya es identico.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator
from pydantic import BaseModel, ConfigDict, Field, field_validator


_SCHEMA_PATH = Path(__file__).resolve().parent / "trend_signal_schema.json"


# =============================================================================
# Enums
# =============================================================================


class FuenteTrend(str, Enum):
    """Plataformas soportadas (alineado al enum de Mateo)."""

    TIKTOK = "TIKTOK"
    INSTAGRAM = "INSTAGRAM"
    PINTEREST = "PINTEREST"
    GOOGLE_TRENDS = "GOOGLE_TRENDS"
    OTHER = "OTHER"


# =============================================================================
# Pydantic models (validacion semantica fuerte)
# =============================================================================


class ProductoSimilarIn(BaseModel):
    """Replica de schemas.tendencias.ProductoSimilar."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    sku: str = Field(..., min_length=1)
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    nombre: str = Field(default="")
    categoria: str = Field(default="")
    precio_referencia: float = Field(default=0.0, ge=0.0)

    @field_validator("sku", mode="before")
    @classmethod
    def _sku_to_str(cls, v: Any) -> str:
        # Acepta int o str; el bug latente del v1 con sku int/str (Bloque 5)
        # se neutraliza aca normalizando a string.
        return str(v)


class TrendSignalIn(BaseModel):
    """TrendSignal canonico tal como lo emite Mateo (Tarea 5).

    Validacion estricta:
    - descripcion 10-500 chars (mismo rango que SHACL de Mateo).
    - fuente debe ser un FuenteTrend valido.
    - velocidad_crecimiento [0, 1000] (porcentaje semanal).
    - confianza_extraccion [0, 1].

    Campos opcionales con defaults seguros (palabras_clave [], productos_*
    [], metadata_fuente {}). validado_shacl/provisional con defaults False/True
    si Mateo no los manda.
    """

    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
        use_enum_values=False,
    )

    trend_id: str = Field(..., min_length=1)
    descripcion: str = Field(..., min_length=10, max_length=500)
    palabras_clave: list[str] = Field(default_factory=list)
    fuente: FuenteTrend
    fecha_deteccion: datetime
    metadata_fuente: dict[str, Any] = Field(default_factory=dict)
    velocidad_crecimiento: float = Field(..., ge=0.0, le=1000.0)
    confianza_extraccion: float = Field(..., ge=0.0, le=1.0)
    productos_existentes_similares: list[ProductoSimilarIn] = Field(
        default_factory=list
    )
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
            try:
                dt = datetime.fromisoformat(s)
            except ValueError as e:
                raise ValueError(
                    f"fecha_deteccion no parsea como ISO-8601: {v!r}"
                ) from e
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        raise ValueError(f"fecha_deteccion debe ser str ISO o datetime, recibido {type(v).__name__}")

    @field_validator("fuente", mode="before")
    @classmethod
    def _normalize_fuente(cls, v: Any) -> str:
        if isinstance(v, FuenteTrend):
            return v.value
        s = str(v).strip().upper().replace(" ", "_")
        # Aliases por compatibilidad con outputs sucios del LLM (Mateo
        # los normaliza tambien en su _normalizar_dict_tendencia_llm).
        aliases = {
            "TIK_TOK": "TIKTOK",
            "META": "INSTAGRAM",
            "IG": "INSTAGRAM",
            "PIN": "PINTEREST",
            "GOOGLE": "GOOGLE_TRENDS",
            "TRENDS": "GOOGLE_TRENDS",
        }
        return aliases.get(s, s)

    @field_validator("descripcion")
    @classmethod
    def _descripcion_no_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("descripcion no puede ser solo whitespace")
        return v

    # -------------------------------------------------------------------------
    # Helpers de propiedad para el pipeline
    # -------------------------------------------------------------------------

    @property
    def top_similar(self) -> ProductoSimilarIn | None:
        """ProductoSimilar con score mas alto, o None si lista vacia."""
        if not self.productos_existentes_similares:
            return None
        return max(self.productos_existentes_similares, key=lambda p: p.score)


# =============================================================================
# JSON Schema validator (capa sintactica)
# =============================================================================


_validator: Draft7Validator | None = None


def _get_validator() -> Draft7Validator:
    """Lazy-load del Draft7Validator. Singleton por proceso."""
    global _validator
    if _validator is None:
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = json.load(f)
        _validator = Draft7Validator(schema)
    return _validator


def validar_json_payload(payload: Any) -> tuple[bool, list[str]]:
    """Valida UN payload (dict) contra el JSON Schema.

    Args:
        payload: dict con los campos del TrendSignal.

    Returns:
        (conforms, errors). errors es lista de mensajes legibles (paths).
    """
    validator = _get_validator()
    errors: list[str] = []
    for err in validator.iter_errors(payload):
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"{path}: {err.message}")
    return (len(errors) == 0, errors)
