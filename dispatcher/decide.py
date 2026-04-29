"""CLI: decide algoritmo para un DecisionContext en JSON.

Uso:
    python -m dispatcher.decide ctx.json
    python -m dispatcher.decide ctx.json --reglas otras.yaml --json --no-color

Formato del ctx.json: dict con los campos del DecisionContext (sku,
tipo_sku, semanas_historia, similar_top_k, etc.). Ver
dispatcher/samples/*.json para ejemplos.

Exit codes:
    0  algoritmo recomendado.
    1  decision bloqueada por deontica (sin algoritmo).
    2  ninguna regla disparo (no deberia pasar si hay fallback).
    3  error de input (archivo, JSON, schema).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dispatcher import (  # noqa: E402
    AlgorithmDispatcher,
    DecisionContext,
    RulesYAMLInvalido,
)
from dispatcher.recommendation import AlgorithmRecommendation  # noqa: E402


DEFAULT_RULES = ROOT / "config" / "dispatcher_rules.yaml"
DEFAULT_AUDIT = ROOT / "data" / "dispatcher_audit.jsonl"


def _load_ctx(path: Path) -> DecisionContext:
    if not path.exists():
        print(f"Error: no existe el archivo {path}", file=sys.stderr)
        sys.exit(3)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Error: JSON invalido en {path}: {e}", file=sys.stderr)
        sys.exit(3)
    # Limpia keys auxiliares (los _descripcion de los samples)
    data = {k: v for k, v in data.items() if not k.startswith("_")}
    try:
        return DecisionContext.from_dict(data)
    except Exception as e:
        print(f"Error: schema de DecisionContext invalido: {e}", file=sys.stderr)
        sys.exit(3)


def _format_human(rec: AlgorithmRecommendation, color: bool) -> str:
    GREEN = "\033[32m" if color else ""
    RED = "\033[31m" if color else ""
    YELLOW = "\033[33m" if color else ""
    BOLD = "\033[1m" if color else ""
    RESET = "\033[0m" if color else ""

    lines = []
    lines.append(f"{BOLD}=== Decision del Dispatcher ==={RESET}")
    lines.append(f"SKU: {rec.sku}")
    lines.append(f"Evaluada: {rec.evaluated_at.isoformat()}")

    if rec.bloqueada_por_deontica:
        lines.append(f"\n{RED}{BOLD}BLOQUEADA por deontica.{RESET}")
        lines.append(f"Normas: {list(rec.bloqueada_por_deontica)}")
    elif not rec.algoritmo_invocado:
        lines.append(f"\n{YELLOW}{BOLD}NINGUNA REGLA DISPARO.{RESET}")
    else:
        lines.append(f"\n{GREEN}{BOLD}Algoritmo recomendado.{RESET}")
        lines.append(f"Regla aplicada: {list(rec.reglas_aplicadas)}")
        lines.append(f"Confianza: {rec.confianza:.2f}")
        lines.append(f"\nStages ({len(rec.stages)}):")
        for s in rec.stages:
            lines.append(f"  [{s.kind}] {s.descriptor_id}")
            for pname, pval in s.parametros.items():
                lines.append(f"    - {pname} = {pval!r}")

    lines.append(f"\n{BOLD}Razonamiento:{RESET}")
    for paso in rec.razonamiento:
        lines.append(f"  {paso}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="dispatcher.decide",
        description="Decide algoritmo para un DecisionContext JSON.",
    )
    p.add_argument("ctx_json", type=Path, help="Ruta al .json del DecisionContext.")
    p.add_argument(
        "--reglas",
        type=Path,
        default=DEFAULT_RULES,
        help=f"Ruta al rules.yaml (default: {DEFAULT_RULES.relative_to(ROOT)}).",
    )
    p.add_argument(
        "--audit",
        type=Path,
        default=DEFAULT_AUDIT,
        help="Ruta JSONL para audit trail.",
    )
    p.add_argument(
        "--no-audit", action="store_true", help="Desactiva audit trail."
    )
    p.add_argument(
        "--no-color", action="store_true", help="Sin colores ANSI."
    )
    p.add_argument(
        "--json", action="store_true", help="Salida JSON en lugar de humana."
    )
    args = p.parse_args(argv)

    ctx = _load_ctx(args.ctx_json)

    audit_path = None if args.no_audit else args.audit

    try:
        dispatcher = AlgorithmDispatcher.from_yaml(args.reglas, audit_path=audit_path)
    except (FileNotFoundError, RulesYAMLInvalido) as e:
        print(f"Error cargando reglas: {e}", file=sys.stderr)
        return 3

    rec = dispatcher.decidir(ctx)

    if args.json:
        print(json.dumps(rec.to_dict(), indent=2, ensure_ascii=False))
    else:
        use_color = (
            not args.no_color
            and sys.stdout.isatty()
            and sys.platform != "win32"
        )
        print(_format_human(rec, color=use_color))

    if rec.bloqueada_por_deontica:
        return 1
    if not rec.algoritmo_invocado:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
