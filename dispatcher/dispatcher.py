"""AlgorithmDispatcher: routing context-aware sobre el catalogo de algoritmos.

Pipeline:

    1. Si DecisionContext.eval_deontica reporta bloqueada (Bloque 6): NO
       se invoca algoritmo. Devuelve Recommendation con
       `bloqueada_por_deontica` poblado y stages=().

    2. Itera reglas en orden de prioridad descendente. Para cada regla,
       evalua todas las expresiones `cuando` contra el contexto. Si TODAS
       son verdaderas, la regla gana (first-match-wins).

    3. Construye los stages de la regla ganadora resolviendo:
       - shorthand "a + b + c" -> lista de descriptor_ids (en load).
       - parametros literales y templates {{ context.x }}.

    4. Calcula la confianza ajustando la confianza_base de la regla con
       factores del contexto (cold_start_confidence, trend_confidence).

    5. Audit trail JSONL append-only (consistente con Bloque 6).

NO ejecuta los algoritmos. Solo describe que invocar y con que parametros.
La ejecucion real es responsabilidad del equipo de Tarea 4.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from dispatcher.algorithms import CATALOGO, AlgorithmDescriptor
from dispatcher.conditions import (
    ExpresionInsegura,
    ExpresionInvalida,
    SafeExpressionEvaluator,
)
from dispatcher.context import DecisionContext
from dispatcher.recommendation import (
    AlgorithmRecommendation,
    AlgorithmStage,
)
from dispatcher.rules import Rule, load_rules, resolve_params


# =============================================================================
# Excepciones
# =============================================================================


class DispatcherError(RuntimeError):
    """Error generico del dispatcher (no recuperable por la regla)."""


# =============================================================================
# Dispatcher
# =============================================================================


@dataclass
class AlgorithmDispatcher:
    """Selector context-aware de algoritmos del catalogo.

    Args:
        rules: lista de reglas ya cargadas y validadas (via load_rules).
        evaluator: evaluador de expresiones; si None, usa default
            SafeExpressionEvaluator({"context"}).
        audit_path: ruta JSONL para audit trail operacional. None desactiva.
        rules_source: ruta original del rules.yaml (para razonamiento;
            no se usa para reload).
        audit_store: AuditStore opcional (Bloque 8). Si esta seteado, cada
            llamada a decidir() persiste un subgrafo PROV-O al store ademas
            del JSONL. Coexisten - JSONL para ops, TTL para auditoria
            consultable con SPARQL.
        audit_agent: agent_uri (local-name) bajo el cual se loguea la
            decision en el AuditStore. Default "agente_dispatcher_v1".
    """

    rules: list[Rule]
    evaluator: SafeExpressionEvaluator = field(
        default_factory=lambda: SafeExpressionEvaluator({"context"})
    )
    audit_path: Optional[Path] = None
    rules_source: Optional[str] = None
    audit_store: Optional[object] = None  # type: AuditStore | None
    audit_agent: str = "agente_dispatcher_v1"

    @classmethod
    def from_yaml(
        cls,
        rules_path: str | Path,
        audit_path: Optional[str | Path] = None,
        audit_store: Optional[object] = None,
        audit_agent: str = "agente_dispatcher_v1",
    ) -> "AlgorithmDispatcher":
        """Construye un dispatcher cargando reglas desde un YAML."""
        evaluator = SafeExpressionEvaluator({"context"})
        rules = load_rules(rules_path, evaluator=evaluator)
        return cls(
            rules=rules,
            evaluator=evaluator,
            audit_path=Path(audit_path) if audit_path is not None else None,
            rules_source=str(rules_path),
            audit_store=audit_store,
            audit_agent=audit_agent,
        )

    # -------------------------------------------------------------------------
    # API publica
    # -------------------------------------------------------------------------

    def decidir(self, context: DecisionContext) -> AlgorithmRecommendation:
        """Decide el algoritmo a invocar para un contexto dado.

        Returns:
            AlgorithmRecommendation. Si la decision esta bloqueada
            deonticamente, `stages=()` y `bloqueada_por_deontica` no es
            vacia. Si ninguna regla aplica (caso impredecible si hay
            fallback), devuelve un recommendation vacio con razonamiento
            explicandolo.
        """
        razonamiento: list[str] = [
            f"Decision para SKU {context.sku} (tipo={context.tipo_sku.value}).",
            f"Evaluada {context.evaluated_at.isoformat()}.",
        ]

        # 1. Filtro deontico
        if context.deontica_bloqueada:
            motivos = context.deontica_motivos
            razonamiento.append(
                f"Deontica BLOQUEA: {list(motivos)}. No se invoca algoritmo."
            )
            rec = AlgorithmRecommendation(
                sku=context.sku,
                stages=(),
                reglas_aplicadas=(),
                confianza=0.0,
                bloqueada_por_deontica=motivos,
                razonamiento=tuple(razonamiento),
            )
            self._audit(context, rec)
            self._audit_prov(context, rec)
            return rec

        if context.eval_deontica is not None:
            razonamiento.append(
                f"Deontica permite (eval_deontica.permitida=True). Continuamos."
            )

        # 2. Evaluar reglas en orden de prioridad
        razonamiento.append(
            f"Evaluando {len(self.rules)} reglas por prioridad desc."
        )
        ns: dict[str, Any] = {"context": context}

        regla_ganadora: Rule | None = None
        for rule in self.rules:
            if self._regla_dispara(rule, ns, razonamiento):
                regla_ganadora = rule
                break

        if regla_ganadora is None:
            razonamiento.append(
                "Ninguna regla disparo (esperado: el fallback regla_999 "
                "deberia disparar siempre). Devuelvo recommendation vacio."
            )
            rec = AlgorithmRecommendation(
                sku=context.sku,
                stages=(),
                reglas_aplicadas=(),
                confianza=0.0,
                razonamiento=tuple(razonamiento),
            )
            self._audit(context, rec)
            self._audit_prov(context, rec)
            return rec

        # 3. Construir stages de la regla ganadora
        razonamiento.append(
            f"Regla disparada: {regla_ganadora.rule_id} "
            f"(prio {regla_ganadora.prioridad}, "
            f"confianza_base {regla_ganadora.confianza:.2f})."
        )
        razonamiento.append(f"  nombre: {regla_ganadora.nombre!r}")
        razonamiento.append(
            f"  algoritmo: {' + '.join(regla_ganadora.descriptor_ids)}"
        )

        # Resolver parametros (templates {{...}} -> valores)
        try:
            params_resueltos = resolve_params(
                regla_ganadora.parametros, ns, self.evaluator
            )
        except (ExpresionInsegura, ExpresionInvalida) as e:
            raise DispatcherError(
                f"Error resolviendo templates de regla "
                f"{regla_ganadora.rule_id!r}: {e}"
            ) from e

        stages = self._construir_stages(
            regla_ganadora, params_resueltos, razonamiento
        )

        # 4. Confianza ajustada
        confianza = self._ajustar_confianza(
            regla_ganadora.confianza, context, razonamiento
        )

        rec = AlgorithmRecommendation(
            sku=context.sku,
            stages=tuple(stages),
            reglas_aplicadas=(regla_ganadora.rule_id,),
            confianza=confianza,
            razonamiento=tuple(razonamiento),
        )
        self._audit(context, rec)
        self._audit_prov(context, rec)
        return rec

    # -------------------------------------------------------------------------
    # Internals
    # -------------------------------------------------------------------------

    def _regla_dispara(
        self,
        rule: Rule,
        namespace: Mapping[str, Any],
        razonamiento: list[str],
    ) -> bool:
        """True sii TODAS las condiciones de la regla son verdaderas."""
        if not rule.cuando:
            razonamiento.append(
                f"  -> {rule.rule_id}: sin condiciones -> dispara."
            )
            return True

        for cond in rule.cuando:
            try:
                value = self.evaluator.evaluate(cond, namespace)
            except (ExpresionInsegura, ExpresionInvalida) as e:
                # Esto no deberia pasar (load_rules pre-valida) pero por
                # las dudas: si una condicion explota en runtime, la
                # tratamos como False y seguimos.
                razonamiento.append(
                    f"  -> {rule.rule_id}: cond {cond!r} levanto {e}; "
                    f"tratada como False."
                )
                return False
            if not value:
                # No imprimir cada condicion fallida (ruido). Solo
                # cuando *toda* la regla pasa o cuando la regla queda
                # dudosa.
                return False
        razonamiento.append(
            f"  -> {rule.rule_id}: todas las condiciones cumplen -> dispara."
        )
        return True

    def _construir_stages(
        self,
        rule: Rule,
        params_resueltos: Mapping[str, Mapping[str, Any]],
        razonamiento: list[str],
    ) -> list[AlgorithmStage]:
        """Materializa AlgorithmStage por cada descriptor de la regla.

        Args:
            rule: la regla ganadora.
            params_resueltos: ya con templates resueltos.
            razonamiento: log mutable que se appende.
        """
        stages: list[AlgorithmStage] = []
        for desc_id in rule.descriptor_ids:
            descriptor: AlgorithmDescriptor = CATALOGO[desc_id]

            # Mezclar defaults del descriptor con overrides de la regla
            params: dict[str, Any] = {
                p.nombre: p.default for p in descriptor.parametros
            }
            overrides = params_resueltos.get(desc_id, {})
            params.update(overrides)

            stages.append(
                AlgorithmStage(
                    kind=descriptor.kind.value,
                    descriptor_id=desc_id,
                    parametros=params,
                )
            )
            if overrides:
                razonamiento.append(
                    f"    {desc_id}: overrides {dict(overrides)}"
                )
        return stages

    @staticmethod
    def _ajustar_confianza(
        base: float, context: DecisionContext, razonamiento: list[str]
    ) -> float:
        """Aplica factores del contexto a la confianza base.

        Heuristicas:
        - Si tipo=NEW y cold_start_confidence < 0.7: penaliza (multiplica
          por cold_start_confidence).
        - Si trend_signal presente con confianza alta: bonus moderado.
        - Resultado clamp a [0, 1].
        """
        ajustado = base
        razon = []
        if (
            context.tipo_sku.value == "new"
            and context.cold_start_confidence < 0.7
        ):
            factor = max(0.3, context.cold_start_confidence)
            ajustado *= factor
            razon.append(
                f"penalizada por cold_start_confidence={context.cold_start_confidence:.2f}"
                f" (factor {factor:.2f})"
            )
        if context.trend_confidence >= 0.8:
            ajustado = min(1.0, ajustado * 1.05)
            razon.append(
                f"bonus por trend_confidence={context.trend_confidence:.2f}"
            )
        ajustado = max(0.0, min(1.0, ajustado))
        if razon:
            razonamiento.append(
                f"  confianza ajustada {base:.2f} -> {ajustado:.2f} "
                f"({'; '.join(razon)})"
            )
        else:
            razonamiento.append(
                f"  confianza final {ajustado:.2f} (sin ajustes)"
            )
        return ajustado

    # -------------------------------------------------------------------------
    # Audit trail JSONL
    # -------------------------------------------------------------------------

    def _audit(
        self,
        context: DecisionContext,
        recommendation: AlgorithmRecommendation,
    ) -> None:
        if self.audit_path is None:
            return
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        line = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "context": _safe_for_json(context),
            "recommendation": recommendation.to_dict(),
        }
        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")

    def _audit_prov(
        self,
        context: DecisionContext,
        recommendation: AlgorithmRecommendation,
    ) -> None:
        """Hook opcional al AuditStore PROV-O (Bloque 8).

        Si self.audit_store esta seteado, persiste el subgrafo PROV-O
        de esta decision. Pasa como `normas_evaluadas` la union de
        bloqueada_por + obligaciones_pendientes del contexto deontico
        (las normas que afectaron la decision; subset auditado del
        catalogo total que se consulto).

        Si el AuditStore falla (I/O, schema, Neo4j), el dispatcher NO
        propaga el error - el audit es side effect, no debe romper la
        decision principal.
        """
        if self.audit_store is None:
            return

        normas_evaluadas: tuple[str, ...] = ()
        if context.eval_deontica is not None:
            bloq = tuple(getattr(context.eval_deontica, "bloqueada_por", ()))
            pend = tuple(
                getattr(context.eval_deontica, "obligaciones_pendientes", ())
            )
            normas_evaluadas = bloq + pend

        try:
            self.audit_store.log_decision(
                context=context,
                recomendacion=recommendation,
                agent_uri=self.audit_agent,
                normas_evaluadas=normas_evaluadas,
            )
        except Exception:
            # Audit es side effect - no rompemos la decision principal
            # si el store falla. En produccion habria que loguear esto
            # con un logger configurado.
            pass


def _safe_for_json(value):
    """Convierte recursivamente a tipos JSON-serializables."""
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if hasattr(value, "__dataclass_fields__"):
        out = {}
        for fname in value.__dataclass_fields__:
            out[fname] = _safe_for_json(getattr(value, fname))
        return out
    if isinstance(value, Mapping):
        return {str(k): _safe_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_for_json(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "value"):
        return value.value
    return str(value)
