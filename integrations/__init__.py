"""Integraciones con outputs de tareas externas (Bloque 9).

Anti-corruption layer para consumir TrendSignals de la Tarea 5 (Mateo).
NO importa directo el pipeline LLM de Mateo (depende de modulos no
empaquetados: schemas/, clients/, services/). En cambio, replica el
contrato de su TrendSignal canonico via Pydantic + jsonschema y consume
JSON ya producido.

Uso tipico:

    from integrations import process_trend_signal, batch_process
    from integrations.trend_signal import TrendSignalIn

    ts = TrendSignalIn(...)
    result = process_trend_signal(ts, dispatcher=disp, audit_store=store)
    print(result.estado, result.recomendacion)
"""

from __future__ import annotations

from integrations.trend_intake import (
    TrendIntakeResult,
    batch_process,
    process_trend_signal,
)
from integrations.trend_signal import (
    FuenteTrend,
    ProductoSimilarIn,
    TrendSignalIn,
    validar_json_payload,
)

__all__ = [
    "FuenteTrend",
    "ProductoSimilarIn",
    "TrendIntakeResult",
    "TrendSignalIn",
    "batch_process",
    "process_trend_signal",
    "validar_json_payload",
]
