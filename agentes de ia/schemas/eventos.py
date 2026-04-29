"""Schemas para eventos comerciales."""

from datetime import date

from pydantic import BaseModel


class EventoComercial(BaseModel):
    """Evento objetivo de compra."""

    evento_id: str
    nombre: str
    fecha_objetivo: date
    semanas_pico: list[int]
    boost_demanda: float
