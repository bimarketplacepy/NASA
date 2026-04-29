"""Schemas de escenarios contrafactuales."""

from typing import Literal

from pydantic import BaseModel, Field

from schemas.recomendaciones import ItemCompra, Recomendacion


class Perturbacion(BaseModel):
    """Cambio hipotetico aplicado sobre una recomendacion."""

    tipo: Literal[
        "QUIEBRE_PROVEEDOR",
        "CAMBIO_DEMANDA",
        "ADELANTO_EVENTO",
        "ATRASO_EVENTO",
        "CAMBIO_PRESUPUESTO",
        "TIPO_CAMBIO",
        "MOQ_CAMBIA",
        "LEAD_TIME_CAMBIA",
        "NUEVO_COMPETIDOR",
        "CUSTOM",
    ]
    parametros: dict = Field(default_factory=dict)
    descripcion_natural: str


class DiffPlan(BaseModel):
    """Diferencias entre plan base y plan alterno."""

    items_agregados: list[ItemCompra]
    items_removidos: list[ItemCompra]
    items_modificados: list[dict] = Field(default_factory=list)
    delta_costo_total: float
    delta_retorno_esperado: float
    delta_var: float
    nuevos_proveedores_incluidos: list[str]
    proveedores_excluidos: list[str]


class EscenarioContrafactual(BaseModel):
    """Salida de reoptimizacion con hipotesis."""

    escenario_id: str
    recomendacion_base_id: str
    perturbacion: Perturbacion
    recomendacion_alterna: Recomendacion
    diff: DiffPlan
    factibilidad: Literal["FACTIBLE", "FACTIBLE_DEGRADADO", "INFACTIBLE"]
    explicacion_natural: str
