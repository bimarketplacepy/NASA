"""CLI: evalua una decision propuesta contra el catalogo deontico.

Uso:
    python -m deontic.check decision.json
    python -m deontic.check decision.json --catalogo otra_carpeta/normas.ttl
    python -m deontic.check decision.json --no-color --json

Formato del decision.json:

    {
      "decision": {
        "tipo": "compra",
        "monto_usd": 7000.0,
        "lead_time_dias": 5.0,
        "aprobacion_supervisor": false
      },
      "contexto": {
        "perecedero": false,
        "sku_critico": true,
        "proveedores_disponibles": 1,
        "proveedor_activo": true,
        "now": "2026-12-15T10:00:00+00:00"   // opcional
      }
    }

Exit codes:
    0  decision permitida (no hay normas que la bloqueen).
    1  decision bloqueada (hay Prohibitions u Obligations pendientes).
    2  conflicto deontico irresoluble (raise UnresolvedDeonticConflict).
    3  error de input (archivo no existe, JSON invalido, schema incorrecto).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deontic import DeonticResolver, UnresolvedDeonticConflict  # noqa: E402
from deontic.norm import EvaluacionDeontica  # noqa: E402


DEFAULT_CATALOGO = ROOT / "ontology_semantic" / "normas_marketplace.ttl"
DEFAULT_AUDIT = ROOT / "data" / "deontic_audit.jsonl"


def _parse_now(value):
    """Convierte string ISO-8601 a datetime si es string; passthrough si ya es datetime."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            raise SystemExit(
                f"Error: contexto.now no es ISO-8601 valido: {value!r}"
            )
    return value


def _load_input(path: Path) -> tuple[dict, dict]:
    if not path.exists():
        print(f"Error: no existe el archivo {path}", file=sys.stderr)
        sys.exit(3)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Error: JSON invalido en {path}: {e}", file=sys.stderr)
        sys.exit(3)

    if not isinstance(data, dict):
        print(
            f"Error: {path} debe ser un objeto JSON con keys 'decision' y 'contexto'.",
            file=sys.stderr,
        )
        sys.exit(3)

    decision = data.get("decision")
    contexto = data.get("contexto", {})
    if not isinstance(decision, dict):
        print(
            f"Error: falta 'decision' o no es objeto en {path}.", file=sys.stderr
        )
        sys.exit(3)
    if not isinstance(contexto, dict):
        print(
            f"Error: 'contexto' no es objeto en {path}.", file=sys.stderr
        )
        sys.exit(3)

    if "now" in contexto:
        contexto["now"] = _parse_now(contexto["now"])

    return decision, contexto


def _format_human(ev: EvaluacionDeontica, use_color: bool) -> str:
    """Formato legible para operador (multilinea)."""
    GREEN = "\033[32m" if use_color else ""
    RED = "\033[31m" if use_color else ""
    YELLOW = "\033[33m" if use_color else ""
    BOLD = "\033[1m" if use_color else ""
    RESET = "\033[0m" if use_color else ""

    lines = []
    lines.append(f"{BOLD}=== Evaluacion deontica ==={RESET}")
    lines.append(f"Evaluada en: {ev.evaluated_at.isoformat()}")

    if ev.permitida:
        lines.append(f"Veredicto: {GREEN}{BOLD}PERMITIDA{RESET}")
    else:
        lines.append(f"Veredicto: {RED}{BOLD}BLOQUEADA{RESET}")

    if ev.bloqueada_por:
        lines.append(f"\n{RED}Prohibiciones aplicables (bloqueada_por):{RESET}")
        for nid in ev.bloqueada_por:
            lines.append(f"  - {nid}")

    if ev.obligaciones_pendientes:
        lines.append(
            f"\n{YELLOW}Obligaciones pendientes (no satisfechas):{RESET}"
        )
        for nid in ev.obligaciones_pendientes:
            lines.append(f"  - {nid}")

    if ev.normas_aplicadas:
        lines.append(f"\nNormas aplicadas (no derrotadas): {len(ev.normas_aplicadas)}")
        for nid in ev.normas_aplicadas:
            lines.append(f"  - {nid}")
    else:
        lines.append("\nNormas aplicadas: ninguna.")

    if ev.normas_derrotadas:
        lines.append(f"\nNormas derrotadas: {len(ev.normas_derrotadas)}")
        for nid, motivo in ev.normas_derrotadas:
            lines.append(f"  - {nid}: {motivo}")

    lines.append(f"\n{BOLD}Razonamiento:{RESET}")
    for paso in ev.razonamiento:
        lines.append(f"  {paso}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="deontic.check",
        description=(
            "Evalua un decision.json contra el catalogo deontico y devuelve "
            "veredicto + razonamiento."
        ),
    )
    parser.add_argument(
        "decision_json",
        type=Path,
        help="Ruta a un .json con keys 'decision' y 'contexto'.",
    )
    parser.add_argument(
        "--catalogo",
        type=Path,
        default=DEFAULT_CATALOGO,
        help=f"Ruta al TTL de normas (default: {DEFAULT_CATALOGO.name}).",
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=DEFAULT_AUDIT,
        help=f"Ruta JSONL para audit trail (default: data/deontic_audit.jsonl).",
    )
    parser.add_argument(
        "--no-audit",
        action="store_true",
        help="Desactiva el audit trail (no escribe JSONL).",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Salida plana sin colores ANSI.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime el resultado como JSON en lugar de formato humano.",
    )

    args = parser.parse_args(argv)

    decision, contexto = _load_input(args.decision_json)

    audit_path = None if args.no_audit else args.audit

    try:
        resolver = DeonticResolver.from_ttl(
            args.catalogo, audit_path=audit_path
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3

    try:
        ev = resolver.evaluar(decision, contexto)
    except UnresolvedDeonticConflict as e:
        print(f"Conflicto deontico irresoluble: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(ev.to_dict(), indent=2, ensure_ascii=False))
    else:
        # Detectar TTY para color
        use_color = (
            not args.no_color
            and sys.stdout.isatty()
            and sys.platform != "win32"
        )
        print(_format_human(ev, use_color=use_color))

    return 0 if ev.permitida else 1


if __name__ == "__main__":
    sys.exit(main())
