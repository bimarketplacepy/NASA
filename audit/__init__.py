"""Audit trail con PROV-O (Bloque 8).

Provenance W3C-compliant para decisiones del dispatcher (Bloque 7) y del
resolver deontico (Bloque 6). Persiste en Turtle append-only consultable
con SPARQL. Opcionalmente espeja a Neo4j via el bridge del Bloque 3.

Uso tipico:

    from audit import AuditStore, replay

    store = AuditStore("data/audit_log_v1.ttl")
    decision_id = store.log_decision(
        context=ctx,
        recomendacion=rec,
        agent_uri="agente_dispatcher_v1",
    )
    # ...mas tarde
    summary = replay(decision_id, store, dispatcher)
    print(summary.diff)
"""

from __future__ import annotations

from audit.store import (
    AuditStore,
    AuditStoreError,
    DecisionNotFoundError,
)
from audit.replay import ReplaySummary, replay
from audit.queries import QUERIES

__all__ = [
    "AuditStore",
    "AuditStoreError",
    "DecisionNotFoundError",
    "ReplaySummary",
    "replay",
    "QUERIES",
]
