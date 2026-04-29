"""trend_intake: pipeline ACL para TrendSignals de la Tarea 5.

Pipeline en 5 etapas para cada TrendSignal:

    1. Schema check (jsonschema) + pydantic semantic validation.
    2. Stop-words check (descripcion no puede ser puro ruido).
    3. Triage por confianza_extraccion (< threshold -> manual_review).
    4. Construccion de DecisionContext (Bloque 7) con tipo_sku=TRENDING,
       similares mapeados, trend_signal del Bloque 7, eval_deontica
       opcional inyectada por el caller.
    5. AlgorithmDispatcher.decidir(ctx) (Bloque 7) + AuditStore.log_decision
       (Bloque 8) si estan disponibles.

API publica:
    process_trend_signal(ts, dispatcher, audit_store=None, threshold=0.4)
        -> TrendIntakeResult
    batch_process(signals, dispatcher, audit_store=None, threshold=0.4)
        -> tuple[list[TrendIntakeResult], dict[str, int]]

CLI:
    python -m integrations.trend_intake samples/trends_navidad_2026.json
    python -m integrations.trend_intake X.json --threshold 0.5 --json --no-audit

Exit codes:
    0  todas las signals procesaron OK.
    1  al menos una quedo en manual_review.
    2  al menos una rechazada (schema o stop-words).
    3  error de input (archivo, JSON, schema invalido a nivel raiz).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Optional

from pydantic import ValidationError

from dispatcher import (
    AlgorithmDispatcher,
    AlgorithmRecommendation,
    DecisionContext,
    SimilarRef,
    TipoSku,
    TrendSignal as DispatcherTrendSignal,
)
from integrations.stop_words import es_descripcion_vacia_o_stops
from integrations.trend_signal import (
    ProductoSimilarIn,
    TrendSignalIn,
    validar_json_payload,
)


# Estado del resultado del intake
EstadoIntake = Literal[
    "processed",          # paso pipeline completo + dispatcher invocado
    "manual_review",      # paso schema/stops pero confianza baja -> bypass
    "rejected_schema",    # falla validacion estructural (jsonschema o pydantic)
    "rejected_stopwords", # descripcion vacia o solo stop-words
    "rejected_runtime",   # error inesperado en pipeline (raise capturado)
]


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_THRESHOLD = 0.4
DEFAULT_AUDIT_PATH = ROOT / "data" / "audit_log_v1.ttl"


# =============================================================================
# Result dataclass
# =============================================================================


@dataclass(frozen=True)
class TrendIntakeResult:
    """Resultado del procesamiento de UNA TrendSignal por el ACL.

    Attributes:
        trend_id: id del trend (del input). Vacio si no parseo.
        estado: uno de los EstadoIntake.
        razon: explicacion legible del estado (auditoria humana).
        recomendacion: AlgorithmRecommendation si paso el dispatcher.
            None si manual_review o rejected.
        audit_decision_id: decisionId del audit store (Bloque 8) si se
            persistio. None si audit_store=None o si no se invoco.
        confianza_ajustada: confianza final post-ajustes del pipeline
            (cross-check con Bloque 5, etc.). 0.0 si rejected.
        razonamiento: lista paso a paso de las decisiones del ACL
            (parecido al razonamiento del dispatcher pero centrado
            en el ACL).
    """

    trend_id: str
    estado: EstadoIntake
    razon: str
    recomendacion: Optional[AlgorithmRecommendation] = None
    audit_decision_id: Optional[str] = None
    confianza_ajustada: float = 0.0
    razonamiento: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serializa a dict JSON-friendly."""
        return {
            "trend_id": self.trend_id,
            "estado": self.estado,
            "razon": self.razon,
            "audit_decision_id": self.audit_decision_id,
            "confianza_ajustada": self.confianza_ajustada,
            "razonamiento": list(self.razonamiento),
            "recomendacion": (
                self.recomendacion.to_dict()
                if self.recomendacion is not None
                else None
            ),
        }


# =============================================================================
# process_trend_signal: pipeline principal
# =============================================================================


def process_trend_signal(
    ts: TrendSignalIn,
    dispatcher: AlgorithmDispatcher,
    audit_store: Optional[object] = None,
    threshold: float = DEFAULT_THRESHOLD,
    eval_deontica: Optional[object] = None,
) -> TrendIntakeResult:
    """Procesa una sola TrendSignal a traves del pipeline ACL.

    Args:
        ts: TrendSignalIn ya validada (sintactica y semantica).
        dispatcher: AlgorithmDispatcher del Bloque 7 (lleva sus reglas).
        audit_store: AuditStore del Bloque 8. None desactiva audit PROV-O.
        threshold: confianza_extraccion minima para auto-procesamiento.
            Trends con confianza menor caen a estado manual_review.
        eval_deontica: opcional. Si el caller ya evaluo deonticamente la
            decision propuesta (compra inducida por el trend), pasa el
            resultado del Bloque 6 aca. Si esta bloqueada, el dispatcher
            corta la decision igual que en el flujo del Bloque 7.

    Returns:
        TrendIntakeResult con estado, recomendacion (si aplica), y
        razonamiento legible.
    """
    razonamiento: list[str] = [
        f"Trend {ts.trend_id} (fuente={ts.fuente.value if hasattr(ts.fuente, 'value') else ts.fuente}, "
        f"velocidad={ts.velocidad_crecimiento:.1f}%, confianza={ts.confianza_extraccion:.2f}).",
        f"Descripcion: {ts.descripcion[:80]}{'...' if len(ts.descripcion) > 80 else ''}",
    ]

    # --- Paso 1: Stop-words check (schema/pydantic ya pasaron pre-llamada) ---
    if es_descripcion_vacia_o_stops(ts.descripcion):
        razonamiento.append(
            "Paso 1 - stop-words: descripcion es vacia o solo stop-words. "
            "RECHAZADA antes de invocar dispatcher."
        )
        return TrendIntakeResult(
            trend_id=ts.trend_id,
            estado="rejected_stopwords",
            razon="Descripcion vacia o compuesta solo por stop-words / "
            "tokens genericos navidenos. Anti-pattern del prompt.",
            confianza_ajustada=0.0,
            razonamiento=tuple(razonamiento),
        )
    razonamiento.append("Paso 1 - stop-words: OK (tokens utiles presentes).")

    # --- Paso 2: Triage por confianza ---
    if ts.confianza_extraccion < threshold:
        razonamiento.append(
            f"Paso 2 - triage: confianza {ts.confianza_extraccion:.2f} "
            f"< threshold {threshold}. -> MANUAL REVIEW (sin dispatcher)."
        )
        return TrendIntakeResult(
            trend_id=ts.trend_id,
            estado="manual_review",
            razon=(
                f"Confianza de extraccion ({ts.confianza_extraccion:.2f}) "
                f"por debajo del threshold ({threshold}). El sistema "
                "marca para revision humana en lugar de auto-procesar."
            ),
            confianza_ajustada=ts.confianza_extraccion,
            razonamiento=tuple(razonamiento),
        )
    razonamiento.append(
        f"Paso 2 - triage: confianza {ts.confianza_extraccion:.2f} >= "
        f"{threshold}. Procedo al pipeline."
    )

    # --- Paso 3: Construir DecisionContext ---
    context = _construir_decision_context(ts, eval_deontica)
    razonamiento.append(
        f"Paso 3 - DecisionContext armado: tipo=TRENDING, similar_top_k="
        f"{len(context.similar_top_k)}, trend_confianza="
        f"{context.trend_confidence:.2f}."
    )

    # --- Paso 4: Dispatcher (Bloque 7) ---
    try:
        recomendacion = dispatcher.decidir(context)
    except Exception as exc:  # noqa: BLE001
        razonamiento.append(
            f"Paso 4 - dispatcher levanto {type(exc).__name__}: {exc}. "
            "Trend marcado como rejected_runtime."
        )
        return TrendIntakeResult(
            trend_id=ts.trend_id,
            estado="rejected_runtime",
            razon=f"Error en dispatcher: {exc}",
            confianza_ajustada=ts.confianza_extraccion,
            razonamiento=tuple(razonamiento),
        )

    razonamiento.append(
        f"Paso 4 - dispatcher: regla={list(recomendacion.reglas_aplicadas) or '<ninguna>'}, "
        f"confianza={recomendacion.confianza:.2f}, "
        f"stages={len(recomendacion.stages)}, "
        f"bloqueada_deontica={bool(recomendacion.bloqueada_por_deontica)}."
    )

    # --- Paso 5: Audit (Bloque 8) ---
    # IMPORTANTE: si el dispatcher ya tiene su propio audit_store wireado,
    # YA logueo via su hook _audit_prov() durante decidir(). En ese caso
    # NO duplicamos el log aca - solo recuperamos el ultimo decision_id
    # del store. Esto evita el double-logging al wirear ambos extremos.
    audit_decision_id: Optional[str] = None
    dispatcher_ya_loguea = (
        getattr(dispatcher, "audit_store", None) is not None
    )

    if dispatcher_ya_loguea and audit_store is not None:
        # El dispatcher ya logueo en decidir(); el ultimo id en el
        # mismo store es de esta decision (single-thread assumption).
        try:
            ids = audit_store.list_decisions()
            audit_decision_id = ids[-1] if ids else None
            razonamiento.append(
                f"Paso 5 - audit: persistido via dispatcher hook "
                f"({audit_decision_id})."
            )
        except Exception:
            razonamiento.append(
                "Paso 5 - audit: dispatcher logueo pero no pude leer el id."
            )
    elif audit_store is not None:
        # ACL es el unico que loguea
        try:
            normas_evaluadas = ()
            if eval_deontica is not None:
                normas_evaluadas = (
                    tuple(getattr(eval_deontica, "bloqueada_por", ()))
                    + tuple(getattr(eval_deontica, "obligaciones_pendientes", ()))
                )
            audit_decision_id = audit_store.log_decision(
                context=context,
                recomendacion=recomendacion,
                agent_uri="agente_dispatcher_v1",
                normas_evaluadas=normas_evaluadas,
            )
            razonamiento.append(
                f"Paso 5 - audit: persistido en PROV-O como "
                f"{audit_decision_id}."
            )
        except Exception as exc:  # noqa: BLE001
            razonamiento.append(
                f"Paso 5 - audit FALLO ({type(exc).__name__}: {exc}). "
                "La recomendacion sigue valida; solo el audit no se "
                "persistio. Considerar revisar Neo4j/disco."
            )
    else:
        razonamiento.append("Paso 5 - audit: desactivado (audit_store=None).")

    # --- Estado final ---
    confianza_ajustada = recomendacion.confianza
    return TrendIntakeResult(
        trend_id=ts.trend_id,
        estado="processed",
        razon=(
            f"Trend procesado end-to-end. Dispatcher recomienda "
            f"{list(recomendacion.descriptores_ids) or '<sin stages>'} "
            f"con confianza {recomendacion.confianza:.2f}."
        ),
        recomendacion=recomendacion,
        audit_decision_id=audit_decision_id,
        confianza_ajustada=confianza_ajustada,
        razonamiento=tuple(razonamiento),
    )


# =============================================================================
# Construccion del DecisionContext desde TrendSignalIn
# =============================================================================


def _construir_decision_context(
    ts: TrendSignalIn,
    eval_deontica: Optional[object],
) -> DecisionContext:
    """Mapea TrendSignalIn -> DecisionContext (Bloque 7).

    Convenciones:
    - tipo_sku = TRENDING (siempre, para TrendSignals).
    - sku = ts.trend_id (no es un SKU del catalogo, pero el contexto lo
      necesita; el dispatcher no lo dereferencia).
    - nombre = descripcion truncada (para razonamiento legible).
    - categoria = categoria del top-1 similar, o cadena vacia.
    - similar_top_k = ProductoSimilarIn -> SimilarRef del Bloque 7.
    - trend_signal = TrendSignal del Bloque 7 con fuente, valor,
      confianza derivados.
    - eval_deontica = inyectada del caller (None es valido).
    """
    # Mapear similares al formato del dispatcher
    similar_top_k = tuple(
        SimilarRef(
            sku=ps.sku,
            score_total=float(ps.score),
            confidence=min(1.0, max(0.0, float(ps.score))),
        )
        for ps in ts.productos_existentes_similares
    )

    # Categoria heredada del top-1 si existe
    top_similar = ts.top_similar
    categoria = top_similar.categoria if top_similar is not None else ""

    # TrendSignal del Bloque 7 (NO confundir con TrendSignalIn de aca,
    # son dos modelos distintos en arquitecturas distintas)
    trend_block7 = DispatcherTrendSignal(
        fuente=ts.fuente.value if hasattr(ts.fuente, "value") else str(ts.fuente),
        valor=float(ts.velocidad_crecimiento),
        confianza=float(ts.confianza_extraccion),
    )

    return DecisionContext(
        sku=ts.trend_id,  # placeholder - el dispatcher no lo dereferencia
        tipo_sku=TipoSku.TRENDING,
        nombre=ts.descripcion[:80],
        categoria=categoria,
        # Sin historia propia (es trend, no SKU establecido)
        semanas_historia=0,
        cantidad_stock=0.0,
        velocidad=0.0,
        # Volatilidad inferida: trends son volatiles por definicion
        volatilidad_forecast=0.6,
        cold_start_confidence=float(ts.confianza_extraccion),
        similar_top_k=similar_top_k,
        evento_proximo=None,  # el caller puede inyectarlo si conoce
        trend_signal=trend_block7,
        proveedores_disponibles=2,  # asumimos disponibilidad estandar
        eval_deontica=eval_deontica,
    )


# =============================================================================
# batch_process
# =============================================================================


def batch_process(
    signals: Iterable[TrendSignalIn],
    dispatcher: AlgorithmDispatcher,
    audit_store: Optional[object] = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[list[TrendIntakeResult], dict[str, int]]:
    """Procesa varias TrendSignals devolviendo resultados + summary.

    Args:
        signals: iterable de TrendSignalIn ya validadas.
        dispatcher, audit_store, threshold: igual que process_trend_signal.

    Returns:
        (lista de TrendIntakeResult, dict {estado: count}).
    """
    results: list[TrendIntakeResult] = []
    summary: dict[str, int] = {}
    for ts in signals:
        r = process_trend_signal(
            ts, dispatcher, audit_store=audit_store, threshold=threshold
        )
        results.append(r)
        summary[r.estado] = summary.get(r.estado, 0) + 1
    return results, summary


# =============================================================================
# Carga de archivo: JSON -> list[TrendSignalIn] con errores agrupados
# =============================================================================


def cargar_signals_desde_json(
    path: str | Path,
) -> tuple[list[TrendSignalIn], list[dict[str, Any]]]:
    """Carga un .json con un array de TrendSignal y devuelve (validos, rejected).

    El archivo top-level puede ser:
    - un array de objetos: [{...}, {...}, ...]
    - un objeto con key 'signals' o 'tendencias': {"signals": [...]}

    Args:
        path: ruta al .json.

    Returns:
        (signals_validos, payloads_rejected).
        signals_validos: list[TrendSignalIn] (solo los que pasaron).
        payloads_rejected: list[dict] cada uno con {payload, errors, etapa}
        para los que fallaron schema o pydantic.

    Raises:
        FileNotFoundError, json.JSONDecodeError: si el archivo no existe
            o es JSON invalido a nivel raiz.
        ValueError: si la estructura top-level no es array ni dict con
            key conocida.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No existe el archivo de signals: {p}")

    raw = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = (
            raw.get("signals")
            or raw.get("tendencias")
            or raw.get("trend_signals")
        )
        if items is None:
            raise ValueError(
                f"{p}: top-level es dict pero sin key 'signals', "
                f"'tendencias' o 'trend_signals'."
            )
    else:
        raise ValueError(
            f"{p}: top-level debe ser array o dict, recibido "
            f"{type(raw).__name__}."
        )

    validos: list[TrendSignalIn] = []
    rejected: list[dict[str, Any]] = []

    for idx, payload in enumerate(items):
        if not isinstance(payload, dict):
            rejected.append(
                {
                    "index": idx,
                    "payload": payload,
                    "etapa": "schema",
                    "errors": [
                        f"Item #{idx} no es objeto: {type(payload).__name__}"
                    ],
                }
            )
            continue

        # Capa 1: jsonschema
        ok, errs = validar_json_payload(payload)
        if not ok:
            rejected.append(
                {
                    "index": idx,
                    "payload": payload,
                    "etapa": "schema",
                    "errors": errs,
                }
            )
            continue

        # Capa 2: pydantic semantic
        try:
            ts = TrendSignalIn.model_validate(payload)
        except ValidationError as e:
            rejected.append(
                {
                    "index": idx,
                    "payload": payload,
                    "etapa": "pydantic",
                    "errors": [str(e)],
                }
            )
            continue

        validos.append(ts)

    return validos, rejected


# =============================================================================
# CLI
# =============================================================================


def _format_result_human(r: TrendIntakeResult, color: bool) -> str:
    GREEN = "\033[32m" if color else ""
    RED = "\033[31m" if color else ""
    YELLOW = "\033[33m" if color else ""
    BLUE = "\033[34m" if color else ""
    BOLD = "\033[1m" if color else ""
    RESET = "\033[0m" if color else ""

    color_estado = {
        "processed": GREEN,
        "manual_review": YELLOW,
        "rejected_schema": RED,
        "rejected_stopwords": RED,
        "rejected_runtime": RED,
    }[r.estado]

    lines = [f"{BOLD}--- Trend {r.trend_id} ---{RESET}"]
    lines.append(
        f"  Estado: {color_estado}{BOLD}{r.estado.upper()}{RESET}"
    )
    lines.append(f"  Razon:  {r.razon}")
    lines.append(f"  Confianza ajustada: {r.confianza_ajustada:.2f}")
    if r.recomendacion is not None:
        lines.append(
            f"  Regla:  {list(r.recomendacion.reglas_aplicadas) or '<ninguna>'}"
        )
        lines.append(
            f"  Stages: {list(r.recomendacion.descriptores_ids) or '<sin stages>'}"
        )
    if r.audit_decision_id is not None:
        lines.append(f"  Audit:  {BLUE}{r.audit_decision_id}{RESET}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="integrations.trend_intake",
        description=(
            "Procesa un .json con TrendSignals (output del pipeline de "
            "Tarea 5) a traves del ACL: schema -> stop-words -> triage "
            "-> dispatcher -> audit."
        ),
    )
    parser.add_argument(
        "trends_json",
        type=Path,
        help="Ruta al .json con array de TrendSignals canonicos.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Confianza minima para auto-procesar (default {DEFAULT_THRESHOLD}). "
        "Trends por debajo van a manual_review.",
    )
    parser.add_argument(
        "--reglas",
        type=Path,
        default=ROOT / "config" / "dispatcher_rules.yaml",
        help="Ruta al rules.yaml del dispatcher.",
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=DEFAULT_AUDIT_PATH,
        help="Ruta al audit_log_v1.ttl (PROV-O).",
    )
    parser.add_argument(
        "--no-audit",
        action="store_true",
        help="Desactiva audit trail (no escribe TTL).",
    )
    parser.add_argument(
        "--no-color", action="store_true", help="Sin colores ANSI."
    )
    parser.add_argument(
        "--json", action="store_true", help="Salida JSON (en vez de humana)."
    )
    args = parser.parse_args(argv)

    # Carga signals (valida schema + pydantic)
    try:
        signals, rejected = cargar_signals_desde_json(args.trends_json)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error de input: {e}", file=sys.stderr)
        return 3

    # Construir dispatcher + audit
    try:
        from audit import AuditStore
        audit_store = None if args.no_audit else AuditStore(args.audit)
    except Exception as e:
        print(
            f"Error inicializando AuditStore: {e}. Continuando sin audit.",
            file=sys.stderr,
        )
        audit_store = None

    try:
        dispatcher = AlgorithmDispatcher.from_yaml(
            args.reglas, audit_store=audit_store
        )
    except Exception as e:
        print(f"Error cargando reglas: {e}", file=sys.stderr)
        return 3

    # Process
    results, summary = batch_process(
        signals,
        dispatcher,
        audit_store=audit_store,
        threshold=args.threshold,
    )

    # Agregar los rejected en schema/pydantic como TrendIntakeResult
    for rej in rejected:
        results.insert(
            rej["index"] if rej["index"] < len(results) else len(results),
            TrendIntakeResult(
                trend_id=str(
                    (rej.get("payload") or {}).get("trend_id", "<sin id>")
                ),
                estado="rejected_schema",
                razon=f"[{rej['etapa']}] " + "; ".join(rej["errors"][:3]),
                confianza_ajustada=0.0,
                razonamiento=(
                    f"Rechazado en etapa {rej['etapa']}: "
                    + "; ".join(rej["errors"][:3]),
                ),
            ),
        )
        summary["rejected_schema"] = summary.get("rejected_schema", 0) + 1

    if args.json:
        out = {
            "summary": summary,
            "results": [r.to_dict() for r in results],
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        use_color = (
            not args.no_color
            and sys.stdout.isatty()
            and sys.platform != "win32"
        )
        print(f"=== Procesados {len(results)} trends ===\n")
        for r in results:
            print(_format_result_human(r, color=use_color))
            print()
        print("=== Summary ===")
        for estado, n in sorted(summary.items()):
            print(f"  {estado:20} {n}")

    # Exit code
    if summary.get("rejected_schema", 0) or summary.get("rejected_runtime", 0):
        return 2
    if summary.get("manual_review", 0) or summary.get("rejected_stopwords", 0):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
