"""Schemas del grafo causal."""

from typing import Literal

from pydantic import BaseModel, Field


class NodoCausal(BaseModel):
    """Nodo del grafo causal."""

    id: str
    tipo: Literal["sku", "proveedor", "categoria", "evento", "restriccion", "tendencia", "vulnerabilidad"]
    label: str
    peso_influencia: float
    metadata: dict = Field(default_factory=dict)


class AristaCausal(BaseModel):
    """Relacion causal entre nodos."""

    source_id: str
    target_id: str
    tipo_relacion: Literal[
        "SUMINISTRA",
        "PERTENECE_A",
        "SUSTITUYE",
        "COMPLEMENTA",
        "AFECTA",
        "RESTRINGE",
        "INFLUYE_POSITIVO",
        "INFLUYE_NEGATIVO",
    ]
    peso: float
    explicacion: str


class GrafoCausal(BaseModel):
    """Representacion final de explicabilidad."""

    grafo_id: str
    recomendacion_id: str
    nodos: list[NodoCausal]
    aristas: list[AristaCausal]
    nodo_central_id: str
