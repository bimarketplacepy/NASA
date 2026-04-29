"""
forecast/config.py
-------------------
Configuracion del ForecastService.

Toda la "magia numerica" (pesos de la formula de confianza, n_sims del
Monte Carlo interno, parametros de Holt-Winters, etc.) vive aca para
que sea facil tunearla sin tocar la logica.

Marketplace SA Paraguay - Linea Navidad - Tarea 3 (Cris).
"""

from dataclasses import dataclass, field
from typing import Literal, Optional


# Defaults razonables para la formula de confianza_global.
# La suma debe ser 1.0 (no se enforza con error pero se valida en __post_init__).
_PESOS_DEFAULT = {
    "historia":   0.30,
    "volatilidad": 0.25,
    "ciclicidad": 0.15,
    "fuente":     0.30,
}

_CONFIANZA_POR_FUENTE_DEFAULT = {
    "own":              1.0,
    "inherited":        0.7,
    "category_default": 0.4,
    "trend_only":       0.3,
}


@dataclass
class ForecastConfig:
    """Parametros configurables del servicio de forecasting.

    Todos los campos tienen defaults razonables y se pueden sobrescribir
    en runtime: `ForecastConfig(n_sims=10, peso_historia=0.5, ...)`.

    Attributes:
        seasonal_periods: Periodicidad estacional (52 semanas = anual).
        trend: Componente de tendencia de Holt-Winters: 'add', 'mul' o None.
        seasonal: Componente estacional: 'add', 'mul' o None. Para
            navideños 'mul' es lo natural (los picos escalan, no suman).
        min_semanas_propias: Minimo de semanas con ventas propias para
            considerar fuente='own'. Si tiene menos, se intenta donante.
        min_semanas_estacional: Minimo de semanas para ajustar estacional.
            Holt-Winters requiere >= 2 ciclos completos (104 semanas).
            Si la serie es mas corta, fitea sin componente estacional.
        n_sims: Cantidad de samples Monte Carlo internos para construir
            los percentiles. Cris pidio 20 max para mantener latencia.
            Esto NO es el Monte Carlo del item #21 (que va aparte).
        peso_historia: Peso de "tengo mucho historico" en confianza_global.
        peso_volatilidad: Peso de "la serie es estable" en confianza_global.
        peso_ciclicidad: Peso de "hay senal estacional" en confianza_global.
        peso_fuente: Peso de "la fuente es propia/heredada" en confianza_global.
        semanas_referencia: Semanas que consideramos "historico ideal" (1.0
            en factor_historia). Default 104 (2 anios = 2 ciclos navidenos).
        confianza_por_fuente: Mapping fuente -> factor [0, 1] para confianza.
        semilla_random: Para reproducibilidad de los samples Monte Carlo.
    """

    # Holt-Winters
    seasonal_periods: int = 52
    trend: Optional[Literal["add", "mul"]] = "add"
    seasonal: Optional[Literal["add", "mul"]] = "mul"
    min_semanas_propias: int = 12
    min_semanas_estacional: int = 104

    # Monte Carlo interno (n_sims pequeño - decision Cris 2026-04-29)
    n_sims: int = 20

    # Cold-start via similarity engine de Abi (ontology_semantic).
    # Threshold minimo de score_total para aceptar un sku como donante.
    # Ver distribucion en logs de precompute_top_k: P75 suele estar ~0.7.
    umbral_similitud_donante: float = 0.6

    # Pesos de la formula confianza_global = sum(w_i * factor_i)
    peso_historia: float = _PESOS_DEFAULT["historia"]
    peso_volatilidad: float = _PESOS_DEFAULT["volatilidad"]
    peso_ciclicidad: float = _PESOS_DEFAULT["ciclicidad"]
    peso_fuente: float = _PESOS_DEFAULT["fuente"]
    semanas_referencia: int = 104

    confianza_por_fuente: dict = field(
        default_factory=lambda: dict(_CONFIANZA_POR_FUENTE_DEFAULT)
    )

    semilla_random: int = 42

    def __post_init__(self) -> None:
        suma = (
            self.peso_historia
            + self.peso_volatilidad
            + self.peso_ciclicidad
            + self.peso_fuente
        )
        if abs(suma - 1.0) > 1e-6:
            raise ValueError(
                f"Pesos de confianza deben sumar 1.0 (suman {suma:.4f}). "
                f"Ajustar peso_historia/volatilidad/ciclicidad/fuente."
            )
        if self.n_sims < 2:
            raise ValueError(f"n_sims debe ser >= 2 (es {self.n_sims})")
        if self.semanas_referencia <= 0:
            raise ValueError("semanas_referencia debe ser > 0")
