"""Capa deontica defeasible (Bloque 6).

Modulo del Marketplace SA Paraguay para evaluar decisiones contra un catalogo
de normas (:Obligation, :Permission, :Prohibition) con resolucion de conflictos
por relacion :defeats explicita y prioridad numerica.

Las normas se cargan desde Turtle (ontology_semantic/normas_marketplace.ttl)
y los predicados appliesWhen se resuelven por nombre via registry seguro
(NUNCA eval()).

Uso tipico:

    from deontic import DeonticResolver

    resolver = DeonticResolver.from_ttl(
        "ontology_semantic/normas_marketplace.ttl",
        audit_path="data/deontic_audit.jsonl",
    )
    eval_ = resolver.evaluar(decision, contexto)
    if eval_.permitida:
        ejecutar(decision)
    else:
        notificar_operador(eval_.razonamiento)
"""

from __future__ import annotations

# Importar predicados de dominio: el side-effect del modulo es registrar
# todas las funciones decoradas con @register_predicate. Se ejecuta una sola
# vez por proceso.
from deontic import predicados_marketplace  # noqa: F401
from deontic.norm import (
    EvaluacionDeontica,
    Modality,
    NormaInvalida,
    Norm,
    Obligation,
    Permission,
    Prohibition,
    UnresolvedDeonticConflict,
)
from deontic.predicates import (
    Predicate,
    get_predicate,
    list_predicates,
    register_predicate,
)
from deontic.resolver import DeonticResolver

__all__ = [
    "DeonticResolver",
    "EvaluacionDeontica",
    "Modality",
    "Norm",
    "NormaInvalida",
    "Obligation",
    "Permission",
    "Predicate",
    "Prohibition",
    "UnresolvedDeonticConflict",
    "get_predicate",
    "list_predicates",
    "register_predicate",
]
