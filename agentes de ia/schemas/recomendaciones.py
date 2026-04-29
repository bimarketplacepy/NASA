"""Schemas de recomendaciones y vulnerabilidades."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from schemas.simulacion import MetricasRiesgo


class ItemCompra(BaseModel):
    """Item recomendado para compra."""

    sku: str
    proveedor_id: str
    cantidad: int
    costo_unitario: float
    descuento_aplicado: float
    costo_total: float
    fecha_pedido_estimada: date
    fecha_arribo_estimada: date
    semanas_buffer_pre_evento: float


class Vulnerabilidad(BaseModel):
    """Riesgo detectado por red-teaming."""

    tipo: Literal[
        "RETRASO_ADUANERO",
        "CAIDA_DEMANDA",
        "QUIEBRE_PROVEEDOR",
        "OBSOLESCENCIA_POST_EVENTO",
        "TIPO_CAMBIO_ADVERSO",
        "COMPETIDOR_DESCUENTO",
        "FALLA_CALIDAD",
    ]
    descripcion: str
    probabilidad_estimada: float
    impacto_usd_esperado: float
    impacto_usd_p95: float
    severidad: Literal["BAJA", "MEDIA", "ALTA", "CRITICA"]
    items_afectados: list[str]
    mitigacion_sugerida: str | None = None


class Recomendacion(BaseModel):
    """Paquete final de decision sugerida."""

    recomendacion_id: str
    timestamp: datetime
    operador_id: str
    evento_objetivo_id: str
    items: list[ItemCompra]
    metricas: MetricasRiesgo
    vulnerabilidades: list[Vulnerabilidad]
    grafo_causal_id: str
    justificacion_texto: str
    nivel_confianza_global: float
    perfil_operador_aplicado: str
    estado: Literal["BORRADOR", "PRESENTADA", "APROBADA", "MODIFICADA", "RECHAZADA"]
    presupuesto_consumido: float
    presupuesto_total: float | None = None
