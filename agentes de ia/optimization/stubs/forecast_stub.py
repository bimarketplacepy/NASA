"""Stub del modulo de forecast de Cris (Tarea 3).

Devuelve un ``ForecastResult`` con la forma final que entregara Cris segun
las Especificaciones Tecnicas v2: listas por semana del horizonte,
``caracteristicas_serie`` estructurada, fuente Literal y soporte para
``sku_donante`` en cold-start.

Cuando Cris entregue su modulo real, reemplazar el import en los algoritmos:

    # ANTES
    from optimization.stubs.forecast_stub import obtener_forecast

    # DESPUES
    from forecast.cris_module import obtener_forecast
"""

from __future__ import annotations

import hashlib
import math
from typing import Optional

from optimization.schemas import CaracteristicasSerie, ForecastResult


# Parametros hardcodeados para SKUs conocidos: usados para que los tests sean
# deterministas y para mostrar diferentes regimenes (alta volatilidad, ciclicos,
# poca historia, etc.).
_FORECASTS_HARDCODED: dict[str, dict[str, float]] = {
    "SKU_001": {"media": 760, "volatilidad": 0.18, "semanas_hist": 78, "tendencia": 0.02},
    "SKU_002": {"media": 1450, "volatilidad": 0.22, "semanas_hist": 104, "tendencia": 0.05},
    "SKU_003": {"media": 740, "volatilidad": 0.15, "semanas_hist": 156, "tendencia": -0.01},
    "SKU_004": {"media": 185, "volatilidad": 0.31, "semanas_hist": 60, "tendencia": 0.10},
    "SKU_005": {"media": 810, "volatilidad": 0.19, "semanas_hist": 90, "tendencia": 0.0},
    "SKU_006": {"media": 660, "volatilidad": 0.17, "semanas_hist": 70, "tendencia": 0.03},
    "SKU_007": {"media": 245, "volatilidad": 0.28, "semanas_hist": 45, "tendencia": 0.07},
    "SKU_008": {"media": 110, "volatilidad": 0.35, "semanas_hist": 20, "tendencia": 0.15},
}


def _params_para_sku(sku: str) -> dict[str, float]:
    """Devuelve parametros deterministas para un SKU (hardcoded o pseudo-random)."""
    if sku in _FORECASTS_HARDCODED:
        return _FORECASTS_HARDCODED[sku]
    seed = int(hashlib.md5(sku.encode()).hexdigest()[:8], 16)
    return {
        "media": 200 + (seed % 800),
        "volatilidad": 0.15 + (seed % 25) / 100.0,
        "semanas_hist": (seed % 100),
        "tendencia": ((seed % 20) - 10) / 100.0,  # entre -0.1 y 0.1
    }


def obtener_forecast(
    sku: str,
    horizonte_semanas: int = 8,
    boost_tendencia: float = 1.0,
    sku_donante: Optional[str] = None,
) -> ForecastResult:
    """STUB del forecast de Cris.

    Devuelve un ``ForecastResult`` verosimil con la forma final v2.

    Args:
        sku: SKU a pronosticar.
        horizonte_semanas: Cantidad de semanas hacia adelante.
        boost_tendencia: Factor multiplicativo aplicado a la tendencia local
            (>1.0 acentua, <1.0 amortigua). Util para escenarios de viralidad.
        sku_donante: Si se provee, hereda el historico del donante (cold-start).

    Returns:
        ``ForecastResult`` con listas por semana, intervalos p5/p50/p95
        y caracteristicas de la serie.
    """
    # 1) Decidir de donde sacamos los parametros
    if sku_donante:
        params = _params_para_sku(sku_donante)
        fuente = "inherited"
        semanas_propias = _params_para_sku(sku).get("semanas_hist", 0)
        confianza = 0.65  # heredado tiene menos confianza
    else:
        params = _params_para_sku(sku)
        semanas_propias = int(params.get("semanas_hist", 0))
        if semanas_propias >= 52:
            fuente = "own"
            confianza = 0.88
        elif semanas_propias >= 8:
            fuente = "own"
            confianza = 0.7
        else:
            fuente = "category_default"
            confianza = 0.45

    media_base = float(params["media"])
    volatilidad = float(params["volatilidad"])
    tendencia = float(params.get("tendencia", 0.0)) * boost_tendencia
    desv_semanal = media_base * volatilidad

    # 2) Construir las listas por semana del horizonte (ascendente con tendencia)
    media_lst: list[float] = []
    std_lst: list[float] = []
    p5_lst: list[float] = []
    p50_lst: list[float] = []
    p95_lst: list[float] = []

    for w in range(1, horizonte_semanas + 1):
        media_w = media_base * (1.0 + tendencia * w)
        std_w = desv_semanal * math.sqrt(1.0 + 0.05 * w)  # incertidumbre crece con horizonte
        p5_w = max(0.0, media_w - 1.645 * std_w)
        p50_w = media_w
        p95_w = media_w + 1.645 * std_w

        media_lst.append(round(media_w, 2))
        std_lst.append(round(std_w, 2))
        p5_lst.append(round(p5_w, 2))
        p50_lst.append(round(p50_w, 2))
        p95_lst.append(round(p95_w, 2))

    # 3) Construir caracteristicas de la serie (lo que el dispatcher consulta)
    caract = CaracteristicasSerie(
        volatilidad=volatilidad,
        ciclicidad=0.45 if semanas_propias >= 52 else 0.0,
        tendencia_local=tendencia,
        autocorrelacion_lag1=max(0.0, 0.8 - volatilidad),
        semanas_efectivas=semanas_propias,
    )

    return ForecastResult(
        sku=sku,
        media=media_lst,
        std=std_lst,
        p5=p5_lst,
        p50=p50_lst,
        p95=p95_lst,
        samples=None,  # el modulo real de Cris incluye numpy ndarray (n_sims, horizonte)
        fuente=fuente,
        sku_donante=sku_donante,
        semanas_de_historia_propia=semanas_propias,
        confianza_global=confianza,
        caracteristicas_serie=caract,
    )


def es_sku_conocido(sku: str) -> bool:
    """STUB: indica si un SKU tiene historial hardcoded."""
    return sku in _FORECASTS_HARDCODED


def tiene_historial(sku: str, minimo_semanas: int = 8) -> bool:
    """STUB del ``tiene_historial(sku)`` de Cris.

    Args:
        sku: SKU a consultar.
        minimo_semanas: Umbral minimo para considerar "con historial".

    Returns:
        True si el SKU tiene al menos ``minimo_semanas`` semanas de datos.
    """
    params = _params_para_sku(sku)
    return int(params.get("semanas_hist", 0)) >= minimo_semanas


def caracterizar_serie(sku: str) -> CaracteristicasSerie:
    """STUB de ``caracterizar_serie(sku)`` de Cris.

    El dispatcher de Abi llama esto para decidir que algoritmo invocar.
    """
    f = obtener_forecast(sku, horizonte_semanas=1)
    return f.caracteristicas_serie


if __name__ == "__main__":
    f = obtener_forecast("SKU_001")
    print(f"SKU_001: media[0]={f.media[0]:.0f}, p95[0]={f.p95[0]:.0f}, fuente={f.fuente}")
    print(f"  volatilidad={f.caracteristicas_serie.volatilidad}, "
          f"semanas_efectivas={f.caracteristicas_serie.semanas_efectivas}")

    f_nuevo = obtener_forecast("SKU_NUEVO_999")
    print(f"SKU nuevo: fuente={f_nuevo.fuente}, confianza={f_nuevo.confianza_global}")

    f_heredado = obtener_forecast("SKU_NUEVO_999", sku_donante="SKU_001")
    print(f"SKU heredado de SKU_001: fuente={f_heredado.fuente}, "
          f"sku_donante={f_heredado.sku_donante}, confianza={f_heredado.confianza_global}")

    print(f"tiene_historial(SKU_001) = {tiene_historial('SKU_001')}")
    print(f"tiene_historial(SKU_NUEVO_999) = {tiene_historial('SKU_NUEVO_999')}")
