"""Replay contrafactual de decisiones registradas.

`replay(decision_id, store, dispatcher)` reconstruye el DecisionContext
exacto de una decision pasada (desde el contextSnapshot del PROV-O) y la
re-ejecuta con el dispatcher actual (es decir, con las reglas, normas y
catalogo de algoritmos vigentes HOY).

Esto habilita el caso contrafactual del prompt: "que pasaria si esta
decision se evaluara hoy con normas/reglas actuales?". Si las reglas no
cambiaron, el resultado deberia ser identico (modulo timestamps). Si
cambiaron, el diff te muestra exactamente que decision distinta tomaria
el sistema hoy.

NO se intenta "replay exacto bit-by-bit con normas-at-time" porque eso
requeriria snapshotear el catalogo de normas/reglas al momento de cada
decision, lo cual es deuda futura. La aproximacion actual es: contexto
exacto + sistema actual.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from dispatcher.context import DecisionContext
from dispatcher.recommendation import AlgorithmRecommendation, AlgorithmStage

if TYPE_CHECKING:
    from audit.store import AuditStore
    from dispatcher.dispatcher import AlgorithmDispatcher


# =============================================================================
# ReplaySummary
# =============================================================================


@dataclass(frozen=True)
class ReplaySummary:
    """Resultado de un replay.

    Attributes:
        decision_id: identificador de la decision original.
        original_rule: rule_id que disparo en el momento original.
        original_confidence: confianza en el momento original.
        original_stages: descriptor_ids en el momento original.
        original_blocked_by_deontic: si la original quedo bloqueada.

        replayed: AlgorithmRecommendation producido por re-evaluar contra
            el dispatcher actual. None si el contexto no se pudo
            reconstruir.

        diff: dict con los cambios detectados:
            {
                "rule_changed": bool,            # cambio la regla disparada?
                "confidence_delta": float,       # diff de confianza
                "stages_added": list[str],       # nuevos descriptores
                "stages_removed": list[str],     # descriptores quitados
                "blocked_changed": bool,         # cambio el bloqueo deontico?
            }

        igual: True sii rule, stages y blocked_by_deontic son identicos.
    """

    decision_id: str
    original_rule: Optional[str]
    original_confidence: Optional[float]
    original_stages: tuple[str, ...]
    original_blocked_by_deontic: bool
    replayed: Optional[AlgorithmRecommendation]
    diff: dict
    igual: bool

    @property
    def replayed_rule(self) -> Optional[str]:
        if self.replayed is None or not self.replayed.reglas_aplicadas:
            return None
        return self.replayed.reglas_aplicadas[0]

    def render(self) -> str:
        """Formato humano legible del resumen del replay."""
        lines = [f"=== Replay de {self.decision_id} ==="]
        lines.append(f"Regla original:     {self.original_rule}")
        lines.append(f"Regla replayed:     {self.replayed_rule}")
        lines.append(
            f"Confidence original: {self.original_confidence:.2f}"
            if self.original_confidence is not None
            else "Confidence original: -"
        )
        if self.replayed is not None:
            lines.append(f"Confidence replayed: {self.replayed.confianza:.2f}")
        lines.append(f"Stages original:    {list(self.original_stages)}")
        if self.replayed is not None:
            lines.append(
                f"Stages replayed:    {list(self.replayed.descriptores_ids)}"
            )
        lines.append("")
        if self.igual:
            lines.append("VEREDICTO: identico (la decision no cambia con sistema actual).")
        else:
            lines.append("VEREDICTO: DIFIERE")
            if self.diff.get("rule_changed"):
                lines.append(f"  - regla cambio: {self.original_rule} -> {self.replayed_rule}")
            if self.diff.get("blocked_changed"):
                lines.append(f"  - bloqueo deontico cambio: "
                             f"{self.original_blocked_by_deontic} -> "
                             f"{self.replayed.bloqueada_por_deontica if self.replayed else None}")
            cd = self.diff.get("confidence_delta")
            if cd is not None and abs(cd) > 0.001:
                lines.append(f"  - confidence delta: {cd:+.3f}")
            added = self.diff.get("stages_added") or []
            removed = self.diff.get("stages_removed") or []
            if added:
                lines.append(f"  - stages agregados: {added}")
            if removed:
                lines.append(f"  - stages quitados:  {removed}")
        return "\n".join(lines)


# =============================================================================
# replay()
# =============================================================================


def replay(
    decision_id: str,
    store: "AuditStore",
    dispatcher: "AlgorithmDispatcher",
) -> ReplaySummary:
    """Reconstruye el contexto y re-ejecuta con el dispatcher actual.

    Args:
        decision_id: id de la decision a replayar.
        store: instancia de AuditStore con el log persistido.
        dispatcher: instancia de AlgorithmDispatcher con las reglas
            actuales (no las del momento original; ese es justamente el
            modo contrafactual).

    Returns:
        ReplaySummary con original + replayed + diff.

    Raises:
        DecisionNotFoundError: si decision_id no esta en el store.
        AuditStoreError: si el contextSnapshot esta corrupto.
    """
    rec = store.get_decision(decision_id)

    original_rule = rec.get("rule_applied")
    original_confidence = rec.get("confidence")
    original_stages = tuple(rec.get("stages") or [])
    original_blocked = bool(rec.get("blocked_by_deontic", False))

    snap = rec.get("context_snapshot") or {}
    if not snap:
        # No hay snapshot - no podemos hacer replay
        return ReplaySummary(
            decision_id=decision_id,
            original_rule=original_rule,
            original_confidence=original_confidence,
            original_stages=original_stages,
            original_blocked_by_deontic=original_blocked,
            replayed=None,
            diff={"error": "contextSnapshot vacio o ausente"},
            igual=False,
        )

    # Reconstruir DecisionContext desde snapshot
    try:
        ctx = DecisionContext.from_dict(snap)
    except Exception as e:
        return ReplaySummary(
            decision_id=decision_id,
            original_rule=original_rule,
            original_confidence=original_confidence,
            original_stages=original_stages,
            original_blocked_by_deontic=original_blocked,
            replayed=None,
            diff={"error": f"Reconstruccion fallo: {type(e).__name__}: {e}"},
            igual=False,
        )

    # Re-ejecutar con dispatcher actual (no audit recursivo)
    audit_path_backup = dispatcher.audit_path
    dispatcher.audit_path = None  # disable JSONL audit en este pass
    try:
        replayed_rec = dispatcher.decidir(ctx)
    finally:
        dispatcher.audit_path = audit_path_backup

    # Calcular diff
    new_rule = replayed_rec.reglas_aplicadas[0] if replayed_rec.reglas_aplicadas else None
    new_stages = list(replayed_rec.descriptores_ids)
    new_blocked = bool(replayed_rec.bloqueada_por_deontica)

    rule_changed = new_rule != original_rule
    blocked_changed = new_blocked != original_blocked
    stages_added = sorted(set(new_stages) - set(original_stages))
    stages_removed = sorted(set(original_stages) - set(new_stages))
    confidence_delta = (
        replayed_rec.confianza - original_confidence
        if original_confidence is not None
        else None
    )

    diff = {
        "rule_changed": rule_changed,
        "blocked_changed": blocked_changed,
        "stages_added": stages_added,
        "stages_removed": stages_removed,
        "confidence_delta": confidence_delta,
    }
    igual = (
        not rule_changed
        and not blocked_changed
        and not stages_added
        and not stages_removed
    )

    return ReplaySummary(
        decision_id=decision_id,
        original_rule=original_rule,
        original_confidence=original_confidence,
        original_stages=original_stages,
        original_blocked_by_deontic=original_blocked,
        replayed=replayed_rec,
        diff=diff,
        igual=igual,
    )
