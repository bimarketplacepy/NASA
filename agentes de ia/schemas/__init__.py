"""Paquete de contratos de datos del backend NASA."""

from schemas.agentes import AgentTrace, IntentClassification, ToolCall
from schemas.chat import ChatMessage, SesionChat
from schemas.contrafactual import DiffPlan, EscenarioContrafactual, Perturbacion
from schemas.errores import ErrorRespuesta
from schemas.eventos import EventoComercial
from schemas.grafo_causal import AristaCausal, GrafoCausal, NodoCausal
from schemas.preferencias import FeedbackSignal, PerfilOperador
from schemas.productos import Categoria, Producto
from schemas.proveedores import Proveedor, RelacionComercial, TramoDescuento
from schemas.recomendaciones import ItemCompra, Recomendacion, Vulnerabilidad
from schemas.simulacion import (
    AffinePolicyParams,
    FinancialConstraints,
    ForecastResult,
    MetricasRiesgo,
    ResultadoMonteCarlo,
)
from schemas.tendencias import FuenteTendencia, NodoProvisional, TendenciaDetectada

__all__ = [
    "AgentTrace",
    "AristaCausal",
    "Categoria",
    "ChatMessage",
    "DiffPlan",
    "ErrorRespuesta",
    "EscenarioContrafactual",
    "EventoComercial",
    "FinancialConstraints",
    "FeedbackSignal",
    "ForecastResult",
    "FuenteTendencia",
    "GrafoCausal",
    "IntentClassification",
    "ItemCompra",
    "MetricasRiesgo",
    "NodoCausal",
    "NodoProvisional",
    "PerfilOperador",
    "Perturbacion",
    "Producto",
    "Proveedor",
    "Recomendacion",
    "RelacionComercial",
    "AffinePolicyParams",
    "ResultadoMonteCarlo",
    "SesionChat",
    "TendenciaDetectada",
    "ToolCall",
    "TramoDescuento",
    "Vulnerabilidad",
]
