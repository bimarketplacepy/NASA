"""scraper_runner: orquestador raw_posts -> TrendsService (Mateo) -> ACL (mio).

Pipeline end-to-end del Bloque 9 con el agente real:

    raw_posts (JSON) --> TrendsService (Mateo, Tarea 5)
                          - LLM heuristico extrae trends
                          - SHACL valida
                          - SemanticMatcher cruza con catalogo
                          - SimilarityEngine enriquece productos
                          - trend_injector persiste a grafo provisional
                       --> list[TrendSignal canonico]
                          --> mapeo a TrendSignalIn (ACL contract)
                             --> trend_intake.batch_process
                                - schema check + stop-words + triage
                                - DecisionContext + dispatcher (Bloque 7)
                                - audit PROV-O (Bloque 8)
                             --> list[TrendIntakeResult]

API:
    run_scraper_pipeline(raw_posts, dispatcher, audit_store=None,
                        threshold=0.4, ...) -> tuple[list[TrendIntakeResult], dict]

CLI:
    python -m integrations.scraper_runner data/posts_simulados.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from clients.data_loader import DataLoader
from clients.llm_client import LLMClient
from clients.ontologia_client import OntologiaClient
from clients.similarity_mock import SimilarityEngineMock
from dispatcher import AlgorithmDispatcher
from integrations.trend_intake import (
    DEFAULT_AUDIT_PATH,
    DEFAULT_THRESHOLD,
    TrendIntakeResult,
    batch_process,
)
from integrations.trend_signal import (
    FuenteTrend,
    ProductoSimilarIn,
    TrendSignalIn,
)
from schemas.tendencias import TrendSignal as MateoTrendSignal
from trends.semantic_matcher import SemanticMatcher
from trends.shacl_validator import SHACLValidator
from trends.trends_service import TrendsService


ROOT = Path(__file__).resolve().parent.parent


# =============================================================================
# Mapeo: TrendSignal canonico de Mateo -> TrendSignalIn del ACL
# =============================================================================


def _mateo_a_intake(ts: MateoTrendSignal) -> TrendSignalIn:
    """Convierte el TrendSignal canonico de Mateo al TrendSignalIn del ACL.

    Los dos modelos son casi identicos (mismas 11 keys); la diferencia es
    que el de Mateo tiene productos_existentes_similares: list[ProductoSimilar]
    (rico, con precio/categoria/nombre), y el del ACL tiene la misma forma
    pero como ProductoSimilarIn. Mapeo 1-a-1.
    """
    productos = [
        ProductoSimilarIn(
            sku=str(ps.sku),
            score=float(ps.score),
            nombre=ps.nombre,
            categoria=ps.categoria,
            precio_referencia=float(ps.precio_referencia),
        )
        for ps in ts.productos_existentes_similares
    ]
    return TrendSignalIn(
        trend_id=ts.trend_id,
        descripcion=ts.descripcion,
        palabras_clave=list(ts.palabras_clave),
        fuente=FuenteTrend(ts.fuente)
        if ts.fuente in [f.value for f in FuenteTrend]
        else FuenteTrend.OTHER,
        fecha_deteccion=ts.fecha_deteccion,
        metadata_fuente=dict(ts.metadata_fuente),
        velocidad_crecimiento=float(ts.velocidad_crecimiento),
        confianza_extraccion=float(ts.confianza_extraccion),
        productos_existentes_similares=productos,
        validado_shacl=bool(ts.validado_shacl),
        provisional=bool(ts.provisional),
    )


# =============================================================================
# run_scraper_pipeline: API publica
# =============================================================================


async def _run_async(
    raw_posts: list[dict[str, Any]],
    umbral_confianza_minima: float,
    umbral_similitud: float,
    inyectar_en_grafo: bool,
) -> list[MateoTrendSignal]:
    """Ejecuta el TrendsService de Mateo (async)."""
    data_loader = DataLoader()
    llm = LLMClient()  # heuristico, sin API
    ontologia = OntologiaClient()
    similarity = SimilarityEngineMock(data_loader=data_loader)
    matcher = SemanticMatcher(data_loader=data_loader, umbral_aprobacion=0.05)

    service = TrendsService(
        llm_client=llm,
        data_loader=data_loader,
        ontologia_client=ontologia,
        shacl_validator=SHACLValidator(),
        semantic_matcher=matcher,
        similarity_engine=similarity,
    )
    return await service.procesar_senales_scrapeadas(
        raw_data=raw_posts,
        umbral_confianza_minima=umbral_confianza_minima,
        umbral_similitud=umbral_similitud,
        inyectar_en_grafo=inyectar_en_grafo,
    )


def run_scraper_pipeline(
    raw_posts: list[dict[str, Any]],
    dispatcher: AlgorithmDispatcher,
    audit_store: Optional[object] = None,
    threshold: float = DEFAULT_THRESHOLD,
    mateo_umbral_confianza: float = 0.05,
    mateo_umbral_similitud: float = 0.05,
    inyectar_grafo_provisional: bool = True,
) -> tuple[list[TrendIntakeResult], dict[str, int]]:
    """Pipeline completo: raw_posts -> TrendsService -> ACL.

    Args:
        raw_posts: lista de posts crudos (formato del stream simulator).
        dispatcher: AlgorithmDispatcher (Bloque 7).
        audit_store: AuditStore (Bloque 8) opcional.
        threshold: confianza minima del ACL para auto-procesar
            (Trends por debajo van a manual_review).
        mateo_umbral_confianza: umbral del TrendsService de Mateo
            para INYECTAR al grafo provisional. Bajo por default
            para que pase el filtro y nuestro ACL haga el triage final.
        mateo_umbral_similitud: umbral del SimilarityEngine de Mateo
            para incluir productos en productos_existentes_similares.
        inyectar_grafo_provisional: si True, persiste a
            data/grafo_provisional.json (mock OntologiaClient).

    Returns:
        (results, summary). Mismo formato que batch_process del ACL.
    """
    # 1. Pipeline async de Mateo (extrae + valida + enriquece)
    mateo_signals: list[MateoTrendSignal] = asyncio.run(
        _run_async(
            raw_posts,
            mateo_umbral_confianza,
            mateo_umbral_similitud,
            inyectar_grafo_provisional,
        )
    )

    # 2. Mapear a TrendSignalIn del ACL
    intake_signals = [_mateo_a_intake(ts) for ts in mateo_signals]

    # 3. ACL del Bloque 9
    return batch_process(
        intake_signals,
        dispatcher,
        audit_store=audit_store,
        threshold=threshold,
    )


# =============================================================================
# CLI
# =============================================================================


def _cargar_posts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"No existe {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        # Permite formatos {"posts": [...]} o {"items": [...]}
        return list(raw.get("posts") or raw.get("items") or [])
    if isinstance(raw, list):
        return raw
    raise ValueError(f"{path}: top-level debe ser array o dict")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="integrations.scraper_runner",
        description=(
            "Pipeline completo: raw posts crudos -> TrendsService de Mateo "
            "-> ACL trend_intake -> dispatcher + audit."
        ),
    )
    parser.add_argument(
        "posts_json",
        type=Path,
        help="Ruta al JSON con array de posts crudos del stream simulator.",
    )
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=f"Confianza minima del ACL (default {DEFAULT_THRESHOLD}).",
    )
    parser.add_argument(
        "--reglas", type=Path,
        default=ROOT / "config" / "dispatcher_rules.yaml",
    )
    parser.add_argument(
        "--audit", type=Path, default=DEFAULT_AUDIT_PATH,
    )
    parser.add_argument("--no-audit", action="store_true")
    parser.add_argument("--no-inyectar-grafo", action="store_true",
        help="No persistir TrendSignals al grafo provisional.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)

    try:
        raw_posts = _cargar_posts(args.posts_json)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
        print(f"Error cargando posts: {e}", file=sys.stderr)
        return 3
    print(f"Cargados {len(raw_posts)} posts crudos", file=sys.stderr)

    try:
        from audit import AuditStore
        audit_store = None if args.no_audit else AuditStore(args.audit)
    except Exception as e:
        print(f"AuditStore desactivado: {e}", file=sys.stderr)
        audit_store = None

    try:
        dispatcher = AlgorithmDispatcher.from_yaml(
            args.reglas, audit_store=audit_store
        )
    except Exception as e:
        print(f"Error cargando reglas: {e}", file=sys.stderr)
        return 3

    results, summary = run_scraper_pipeline(
        raw_posts,
        dispatcher,
        audit_store=audit_store,
        threshold=args.threshold,
        inyectar_grafo_provisional=not args.no_inyectar_grafo,
    )

    if args.json:
        print(json.dumps(
            {"summary": summary, "results": [r.to_dict() for r in results]},
            indent=2, ensure_ascii=False,
        ))
    else:
        from integrations.trend_intake import _format_result_human
        use_color = not args.no_color and sys.stdout.isatty() and sys.platform != "win32"
        print(f"\n=== Pipeline scraper-real produjo {len(results)} TrendSignals ===\n")
        for r in results:
            print(_format_result_human(r, color=use_color))
            print()
        print("=== Summary ===")
        for estado, n in sorted(summary.items()):
            print(f"  {estado:20} {n}")

    if summary.get("rejected_schema", 0) or summary.get("rejected_runtime", 0):
        return 2
    if summary.get("manual_review", 0) or summary.get("rejected_stopwords", 0):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
