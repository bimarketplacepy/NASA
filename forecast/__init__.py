"""
forecast - servicio de forecasting + Monte Carlo (Tarea 3).

Marketplace SA Paraguay - Linea Navidad.

API publica:
    from forecast import ForecastService, ForecastResult, CaracteristicasSerie, ForecastConfig

    service = ForecastService(ont_client=OntologyClient())
    result = await service.forecast(sku="114142", semanas_adelante=8)
"""

from forecast.config import ForecastConfig
from forecast.forecast import ForecastService
from forecast.models import CaracteristicasSerie, ForecastResult

__all__ = [
    "CaracteristicasSerie",
    "ForecastConfig",
    "ForecastResult",
    "ForecastService",
]
