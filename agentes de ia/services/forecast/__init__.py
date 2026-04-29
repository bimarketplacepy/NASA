"""Servicios y utilidades de pronostico de demanda.

Este paquete encapsula la logica de forecast para SKUs con y sin historial
suficiente, con una interfaz unificada para el resto del sistema.
"""

from services.forecast.forecast_service import ForecastService

__all__ = ["ForecastService"]
