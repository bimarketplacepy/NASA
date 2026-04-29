"""
forecast/models.py
-------------------
Modelos Pydantic v2 para el servicio de forecasting (Tarea 3).

Define el contrato de retorno de forecast() y la caracterizacion de serie
que el dispatcher de Abi consume para elegir el algoritmo de optimizacion.

Spec autoritativo: Especificaciones_CRIS.pdf v2, secciones 4.2 y 4.4.

Marketplace SA Paraguay - Linea Navidad - Tarea 3 (Cris).
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CaracteristicasSerie(BaseModel):
    """Metricas que describen la serie historica de un SKU.

    El dispatcher de Abi consume estas metricas para decidir que algoritmo
    de optimizacion invocar. Ejemplo del spec (seccion 4.4): si volatilidad
    < 0.3 y semanas_efectivas > 52, usa EWMA bounded; si es alta volatilidad
    y cold-start, usa robust affine + buffer.

    Attributes:
        volatilidad: Coeficiente de variacion (std/media) sobre toda la serie.
        ciclicidad: Autocorrelacion a lag 52 (senal de estacionalidad anual).
        tendencia_local: Pendiente de regresion sobre las ultimas 12 semanas.
        autocorrelacion_lag1: Autocorrelacion a lag 1 (memoria de corto plazo).
        semanas_efectivas: Cantidad de semanas con observaciones utiles.
    """

    volatilidad: float
    ciclicidad: float
    tendencia_local: float
    autocorrelacion_lag1: float
    semanas_efectivas: int


class ForecastResult(BaseModel):
    """Resultado de una llamada a forecast() para un SKU.

    Es el contrato que consume el dispatcher de Abi (paso 5 del flujo
    end-to-end de la seccion 6 de la spec). Incluye prediccion puntual,
    dispersion, percentiles y metadata decisional para que el razonador
    formal sepa cuanto confiar en cada prediccion.

    Las listas media, std, p5, p50, p95 representan la prediccion semana
    a semana del horizonte. Todas tienen la misma longitud (validado).

    Attributes:
        sku: Identificador del SKU pronosticado. La spec lo define como
            string aunque en Neo4j :Producto.sku se guarde como int; el
            casteo lo hace forecast() al consultar el grafo.
        media: Pronostico puntual de unidades por semana del horizonte.
        std: Desvio estandar del pronostico por semana.
        p5: Percentil 5 (cota inferior 90%) por semana.
        p50: Mediana por semana.
        p95: Percentil 95 (cota superior 90%) por semana.
        samples: Array NumPy con shape (n_sims, semanas_adelante).
            Tipo `Any` por arbitrary_types_allowed (no se valida estructura).
        fuente: Origen de los datos usados:
            - 'own': historico propio del SKU.
            - 'inherited': heredado del sku_donante via similarity engine.
            - 'category_default': default de la categoria (sin donante).
            - 'trend_only': solo senal de tendencia (Mateo), sin historico.
        sku_donante: SKU usado como base cuando fuente='inherited'.
        semanas_de_historia_propia: Cuantas semanas tenia el SKU original
            antes de heredar (si aplica). 0 si no tenia nada propio.
        confianza_global: Score en [0, 1] que el dispatcher usa para
            ponderar esta prediccion frente a otras senales.
        caracteristicas_serie: Metricas descriptivas de la serie usada.
    """

    sku: str
    media: list[float]
    std: list[float]
    p5: list[float]
    p50: list[float]
    p95: list[float]
    samples: Any  # numpy.ndarray; no validar estructura

    # Metadata decisional (extension v2 sobre el docx original de Mateo)
    fuente: Literal["own", "inherited", "category_default", "trend_only"]
    sku_donante: Optional[str] = None
    semanas_de_historia_propia: int = Field(ge=0)
    confianza_global: float = Field(ge=0.0, le=1.0)
    caracteristicas_serie: CaracteristicasSerie

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @model_validator(mode="after")
    def _validar_longitudes_iguales(self) -> "ForecastResult":
        """media/std/p5/p50/p95 deben tener la misma cantidad de semanas."""
        n = len(self.media)
        for nombre, lista in (
            ("std", self.std),
            ("p5", self.p5),
            ("p50", self.p50),
            ("p95", self.p95),
        ):
            if len(lista) != n:
                raise ValueError(
                    f"Longitud inconsistente: media tiene {n} elementos, "
                    f"{nombre} tiene {len(lista)}"
                )
        return self

    @model_validator(mode="after")
    def _validar_coherencia_donante(self) -> "ForecastResult":
        """fuente='inherited' implica sku_donante presente y distinto del sku."""
        if self.fuente == "inherited":
            if self.sku_donante is None:
                raise ValueError(
                    "fuente='inherited' requiere sku_donante no nulo"
                )
            if self.sku_donante == self.sku:
                raise ValueError(
                    "sku_donante no puede ser igual al sku objetivo"
                )
        return self
