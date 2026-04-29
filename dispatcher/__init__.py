"""Dispatcher de algoritmos (Bloque 7).

Modulo del Marketplace SA Paraguay para mapear DecisionContext rico
(producto + stock + similitud + evento + deontica) a una combinacion
de descriptores de algoritmos del paper de robust optimization.

NO ejecuta algoritmos - solo describe que invocar y con que parametros.
La ejecucion real es responsabilidad del equipo de Tarea 4.

Uso tipico:

    from dispatcher import AlgorithmDispatcher
    from dispatcher.context import DecisionContext, TipoSku, SimilarRef

    dispatcher = AlgorithmDispatcher.from_yaml(
        "config/dispatcher_rules.yaml",
        audit_path="data/dispatcher_audit.jsonl",
    )

    ctx = DecisionContext(
        sku="246295",
        tipo_sku=TipoSku.NEW,
        similar_top_k=(SimilarRef(sku="247329", score_total=0.85),),
        cold_start_confidence=0.5,
    )

    rec = dispatcher.decidir(ctx)
    if rec.algoritmo_invocado:
        ejecutar_algoritmo(rec)  # Tarea 4
    else:
        notificar_operador(rec.razonamiento)
"""

from __future__ import annotations

from dispatcher.algorithms import (
    CATALOGO,
    AlgorithmDescriptor,
    Kind,
    ParameterSpec,
    dump_to_turtle,
    get,
    list_by_kind,
    parse_shorthand,
    validate_combination,
)
from dispatcher.conditions import (
    ExpresionInsegura,
    ExpresionInvalida,
    SafeExpressionEvaluator,
)
from dispatcher.context import (
    DecisionContext,
    EventoProximo,
    SimilarRef,
    TipoSku,
    TrendSignal,
    from_ontology,
)
from dispatcher.dispatcher import AlgorithmDispatcher, DispatcherError
from dispatcher.recommendation import (
    AlgorithmRecommendation,
    AlgorithmStage,
)
from dispatcher.rules import Rule, RulesYAMLInvalido, load_rules

__all__ = [
    "AlgorithmDescriptor",
    "AlgorithmDispatcher",
    "AlgorithmRecommendation",
    "AlgorithmStage",
    "CATALOGO",
    "DecisionContext",
    "DispatcherError",
    "EventoProximo",
    "ExpresionInsegura",
    "ExpresionInvalida",
    "Kind",
    "ParameterSpec",
    "Rule",
    "RulesYAMLInvalido",
    "SafeExpressionEvaluator",
    "SimilarRef",
    "TipoSku",
    "TrendSignal",
    "dump_to_turtle",
    "from_ontology",
    "get",
    "list_by_kind",
    "load_rules",
    "parse_shorthand",
    "validate_combination",
]
